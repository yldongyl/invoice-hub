# -*- coding: utf-8 -*-
"""Agent / MCP 内部后端 API 客户端（WP5.5/WP5.6 · ADR-0001 依赖纪律②）。

红线约束：
  - 严禁直接 import backend 的 ORM/DB/models 进行数据库直连；
  - 一律通过 HTTP/REST API 与后端确定性核心交互（工具同源原则）；
  - 遵循四隔离：查询自动携带或派生 instance（CN/OS）租户上下文；
  - 受控写操作必须携带 confirm_token 与 operator。
"""

from typing import Any, Optional
import httpx

from agent.config import BACKEND_BASE_URL


def infer_instance_from_case_id(case_id: Optional[str]) -> Optional[str]:
    """根据案件号实例段推导租户实例（CON-04 决议）。"""
    if not case_id or not str(case_id).startswith("INV-"):
        return None
    seg = case_id[4:6]
    return {"CN": "CN", "SG": "OS"}.get(seg)


class BackendClient:
    """与后端 API 通信的轻量客户端（零 DB 直连）。"""

    def __init__(self, base_url: str = BACKEND_BASE_URL, http_client: Optional[Any] = None):
        self.base_url = base_url.rstrip("/")
        # 支持传入已初始化的 TestClient（用于测试隔离）或独立 httpx.Client
        self._client = http_client

    def _get_client(self):
        if self._client is not None:
            return self._client
        return httpx.Client(base_url=self.base_url, timeout=10.0)

    # ───────────────────────── 只读查询接口 ─────────────────────────

    def search_cases(self, **params) -> list[dict[str, Any]]:
        """调用 backend /v1/cases 列表查询接口（同源 MCP: case.search）。
        若未指定 instance，分别查询 CN 与 OS 实例并聚合返回。
        """
        client = self._get_client()
        if "instance" in params and params["instance"]:
            resp = client.get("/v1/cases", params=params)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("items", []) if isinstance(data, dict) else data
            return []

        # 双实例聚合
        merged = []
        for inst in ("CN", "OS"):
            p = dict(params)
            p["instance"] = inst
            resp = client.get("/v1/cases", params=p)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("items", []) if isinstance(data, dict) else data
                merged.extend(items)
        return merged

    def get_case(self, case_id: str) -> Optional[dict[str, Any]]:
        """调用 backend /v1/cases/{id} 详情接口。"""
        client = self._get_client()
        inst = infer_instance_from_case_id(case_id)
        params = {"instance": inst} if inst else {}
        resp = client.get(f"/v1/cases/{case_id}", params=params)
        if resp.status_code == 200:
            return resp.json()
        return None

    def get_evidence(self, case_id: str, field: Optional[str] = None) -> list[dict[str, Any]]:
        """调用 backend /v1/cases/{id}/evidence 证据链接口（同源 MCP: case.get_evidence）。"""
        client = self._get_client()
        inst = infer_instance_from_case_id(case_id)
        params = {"field": field} if field else {}
        if inst:
            params["instance"] = inst
        resp = client.get(f"/v1/cases/{case_id}/evidence", params=params)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("items", []) if isinstance(data, dict) else data
        return []

    def list_providers(self) -> list[dict[str, Any]]:
        """调用 backend /v1/providers 接口（同源 MCP: provider.list）。"""
        client = self._get_client()
        resp = client.get("/v1/providers")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("providers", []) if isinstance(data, dict) else data
        return []

    # ───────────────────────── 受控写接口 ─────────────────────────

    def execute_case_action(self, case_id: str, action: str, confirm_token: str,
                            operator: str, opinion: Optional[str] = None) -> dict[str, Any]:
        """调用 backend /v1/cases/{id}/actions/{action} 受控处置（同源 MCP: case.action）。"""
        client = self._get_client()
        inst = infer_instance_from_case_id(case_id) or "CN"
        # 映射契约动作码至内核动作 (RELEASE->release, HOLD->hold, REJECT->return)
        act_map = {"RELEASE": "release", "HOLD": "hold", "REJECT": "return"}
        internal_act = act_map.get(action, action.lower())
        payload = {
            "actor": operator,
            "instance": inst,
            "token": confirm_token,
            "self_confirmed": True,
            "opinion": opinion or ("（未填写处置意见）" if internal_act != "return" else opinion),
        }
        resp = client.post(f"/v1/cases/{case_id}/actions/{internal_act}", json=payload)
        if resp.status_code == 200:
            return resp.json()
        raise RuntimeError(f"后端执行受控动作失败 (HTTP {resp.status_code}): {resp.text}")

    def recognize_invoice(self, file_ref: str, instance: str, confirm_token: str,
                          operator: str, po_ref: Optional[str] = None,
                          callback: Optional[str] = None) -> dict[str, Any]:
        """调用 backend /v1/invoices:recognize 识别受理接口（同源 MCP: invoices.recognize）。"""
        client = self._get_client()
        payload = {
            "file": {"ref": file_ref, "mime_type": "application/pdf", "sha256": "0" * 64},
            "instance": instance,
            "po_ref": po_ref,
            "callback_url": callback,
            "options": {"sync_fast_path_only": True},
        }
        resp = client.post("/v1/invoices:recognize", json=payload)
        if resp.status_code in (200, 202):
            return resp.json()
        raise RuntimeError(f"后端识别受理失败 (HTTP {resp.status_code}): {resp.text}")
