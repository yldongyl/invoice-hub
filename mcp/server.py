# -*- coding: utf-8 -*-
"""MCP Server 6 工具核心分发与策略执行（WP5.6 · contracts/mcp-tools.json）。

规范与红线：
  - 工具层为 backend API 薄封装（零业务逻辑，代码走查可追溯）；
  - 工具同源原则：与 agent/ 共用 BackendClient 与底层调用链，严禁私有旁路；
  - 严禁 DB / ORM 直连；
  - 安全策略强制（FN-A-04 / policy）：
    * 受控写工具（invoices.recognize / case.action）必须持有 invoice.write.controlled 权限范围；
    * 强制要求人工确认凭据（confirm_token）与操作人（operator），缺一即以 428/400 拦截并返回明确错误；
    * 严防 AI 静默写。
"""

from typing import Any, Optional
from fastapi import HTTPException, status

from agent.backend_client import BackendClient
from agent.tools import case_get_evidence, case_search, dedup_report, provider_list
from mcp.auth import SCOPE_READ, SCOPE_WRITE_CONTROLLED, verify_scope
from mcp.tools_registry import get_mcp_policy, get_tool_definition, list_tools


class McpServer:
    """MCP 6 工具调度执行器。"""

    def __init__(self, backend_client: Optional[BackendClient] = None):
        self.backend_client = backend_client or BackendClient()

    def list_tools(self) -> list[dict[str, Any]]:
        """获取工具清单（与 mcp-tools.json 契约 100% 一致）。"""
        return list_tools()

    def call_tool(self, tool_name: str, arguments: dict[str, Any], authorization: Optional[str] = None) -> dict[str, Any]:
        """执行工具调用，包含鉴权校验、confirm_token 策略拦截与后端 API 薄封装转发。"""
        tool_def = get_tool_definition(tool_name)
        if not tool_def:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未注册的 MCP 工具: {tool_name!r}",
            )

        # 1. OAuth2 Scope 权限校验
        is_write = tool_def.get("access") == "controlled_write"
        verify_scope(authorization, SCOPE_READ)
        if is_write:
            verify_scope(authorization, SCOPE_WRITE_CONTROLLED)

        # 2. 受控写策略强制（write_tools_require_human_confirm_token）
        if is_write:
            confirm_token = arguments.get("confirm_token")
            operator = arguments.get("operator")
            if not confirm_token:
                raise HTTPException(
                    status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                    detail={
                        "error_code": "E_CONFIRM_TOKEN_REQUIRED",
                        "message": f"受控写工具 {tool_name!r} 缺少人工确认凭据 confirm_token（write_tools_require_human_confirm_token 策略强制，AI 禁止静默写）",
                    },
                )
            if not operator:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "error_code": "E_OPERATOR_REQUIRED",
                        "message": f"受控写工具 {tool_name!r} 缺少操作人身份 operator",
                    },
                )

        # 3. 工具分发（纯薄封装转发至 BackendClient）
        if tool_name == "case.search":
            return self._tool_case_search(arguments)
        elif tool_name == "case.get_evidence":
            return self._tool_case_get_evidence(arguments)
        elif tool_name == "dedup.report":
            return self._tool_dedup_report(arguments)
        elif tool_name == "provider.list":
            return self._tool_provider_list(arguments)
        elif tool_name == "invoices.recognize":
            return self._tool_invoices_recognize(arguments)
        elif tool_name == "case.action":
            return self._tool_case_action(arguments)
        else:
            raise HTTPException(status_code=404, detail=f"未知工具实现: {tool_name}")

    # ───────────────────────── 4 只读工具薄封装 ─────────────────────────

    def _tool_case_search(self, args: dict[str, Any]) -> dict[str, Any]:
        """只读：case.search。"""
        results = case_search(
            self.backend_client,
            query=args.get("keyword") or args.get("supplier"),
            status=args.get("status"),
        )
        return {
            "tool": "case.search",
            "count": len(results),
            "items": results,
        }

    def _tool_case_get_evidence(self, args: dict[str, Any]) -> dict[str, Any]:
        """只读：case.get_evidence。"""
        case_id = args.get("caseId")
        if not case_id:
            raise HTTPException(status_code=400, detail="缺少必需参数 caseId")
        evidence = case_get_evidence(self.backend_client, case_id=case_id, field=args.get("field"))
        return {
            "tool": "case.get_evidence",
            "caseId": case_id,
            "field": args.get("field"),
            "evidence": evidence,
        }

    def _tool_dedup_report(self, args: dict[str, Any]) -> dict[str, Any]:
        """只读：dedup.report。"""
        matches = dedup_report(
            self.backend_client,
            invoice_no=args.get("invoice_no"),
            supplier=args.get("supplier"),
        )
        return {
            "tool": "dedup.report",
            "blocked_count": len(matches),
            "records": matches,
            "conclusion": "业务键全局查重完成，命中记录已由规则引擎阻断" if matches else "无重复命中记录",
        }

    def _tool_provider_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """只读：provider.list。"""
        providers = provider_list(self.backend_client)
        return {
            "tool": "provider.list",
            "count": len(providers),
            "providers": providers,
        }

    # ───────────────────────── 2 受控写工具薄封装 ─────────────────────────

    def _tool_invoices_recognize(self, args: dict[str, Any]) -> dict[str, Any]:
        """受控写：invoices.recognize（转发至 POST /v1/invoices:recognize）。"""
        file_ref = args["file_ref"]
        instance = args["instance"]
        confirm_token = args["confirm_token"]
        operator = args["operator"]
        po_ref = args.get("po_ref")
        callback = args.get("callback")

        try:
            res = self.backend_client.recognize_invoice(
                file_ref=file_ref,
                instance=instance,
                confirm_token=confirm_token,
                operator=operator,
                po_ref=po_ref,
                callback=callback,
            )
            return {
                "tool": "invoices.recognize",
                "status": "ACCEPTED",
                "result": res,
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"识别受理失败: {e}")

    def _tool_case_action(self, args: dict[str, Any]) -> dict[str, Any]:
        """受控写：case.action（转发至 POST /v1/cases/{id}/actions/{action}）。"""
        case_id = args["caseId"]
        action = args["action"]
        confirm_token = args["confirm_token"]
        operator = args["operator"]
        opinion = args.get("opinion")

        try:
            res = self.backend_client.execute_case_action(
                case_id=case_id,
                action=action,
                confirm_token=confirm_token,
                operator=operator,
                opinion=opinion,
            )
            return {
                "tool": "case.action",
                "caseId": case_id,
                "action": action,
                "operator": operator,
                "result": res,
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"受控动作执行失败: {e}")
