# -*- coding: utf-8 -*-
"""Agent 只读工具层（WP5.5 · FN-8-08 · 与 MCP 工具同源）。

4 项只读工具薄封装：
  ① case.search：供应商/状态/日期范围/关键字检索案件列表；
  ② case.get_evidence：字段级结构化证据与原件片段；
  ③ dedup.report：发票号/金额/供应商查重排查报告；
  ④ provider.list：Provider 能力清单与实例状态。

纪律：
  - 严禁任何写操作；
  - 严禁直连数据库，全量通过 BackendClient 走内部 API。
"""

from typing import Any, Optional
from agent.backend_client import BackendClient


def case_search(client: BackendClient, *, query: Optional[str] = None,
                status: Optional[str] = None, region: Optional[str] = None,
                risk: Optional[str] = None) -> list[dict[str, Any]]:
    """MCP: case.search（案件只读检索）。"""
    params = {}
    if query:
        params["query"] = query
    if status:
        params["status"] = status
    if region:
        params["region"] = region
    if risk:
        params["risk"] = risk
    return client.search_cases(**params)


def case_get_evidence(client: BackendClient, case_id: str,
                      field: Optional[str] = None) -> list[dict[str, Any]]:
    """MCP: case.get_evidence（字段级证据链读取）。"""
    return client.get_evidence(case_id, field=field)


def dedup_report(client: BackendClient, *, invoice_no: Optional[str] = None,
                 supplier: Optional[str] = None, instance: Optional[str] = None) -> list[dict[str, Any]]:
    """MCP: dedup.report（查重风险筛查）。"""
    # 检索状态为 BLOCKED 或包含重复风险的案件
    cases = client.search_cases(risk="重复票")
    if not cases:
        # 兜底查询所有 BLOCKED 案件
        cases = client.search_cases(status="BLOCKED")
    results = []
    for c in cases:
        meta = c.get("meta") or {}
        risk_label = meta.get("risk_label") or c.get("risk_label")
        if risk_label == "重复票" or c.get("status") == "BLOCKED":
            if instance and c.get("instance") != instance:
                continue
            results.append(c)
    return results


def provider_list(client: BackendClient) -> list[dict[str, Any]]:
    """MCP: provider.list（Provider 清单只读枚举）。"""
    return client.list_providers()
