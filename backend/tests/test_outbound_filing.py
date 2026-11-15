# -*- coding: utf-8 -*-
"""出站台账与受控重推真实测试（FN-7-05 / FN-7-06 · 20261102 S4 #61/#62）。

验证要点：
  1. GET /v1/outbound/batches 列表与服务端筛选（目标平台、状态）；
  2. KPI 五卡聚合（待出站、推送中、建档成功、失败待人工、平均回写时延）；
  3. Ariba 4 类单据枚举（Invoice(PO/Contract/Non-PO/Credit Memo)）与 cXML 报文结构；
  4. 状态语义符合「建档成功/对账完成（生成支付凭证传会计系统）」，严禁「已付款」；
  5. execute_filing 真实落库出站批次与明细记录；
  6. 红字票缺失原发票号强阻断出站；
  7. 失败记录退避调度与受控重推（五要素闭环、ops/admin 权限、退避期拦截、审计链留痕）；
  8. list_adapter_queue 真实读库。
"""

import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.domain import models as m
from app.services import adapter_service, outbound_service
from app.services.audit_chain import now_iso
from app.services.errors import CommandError


def test_outbound_batches_list_and_kpi(api_client):
    """断言 GET /v1/outbound/batches 结构、筛选与 KPI 五卡聚合。"""
    res = api_client.get("/v1/outbound/batches")
    assert res.status_code == 200
    data = res.json()

    assert "batches" in data
    assert "kpi" in data
    assert data["total"] >= 4

    # 断言 KPI 五卡键
    kpi = data["kpi"]
    assert "wait" in kpi
    assert "pushing" in kpi
    assert "ok" in kpi
    assert "bad" in kpi
    assert "avg_latency" in kpi
    assert "avg_latency_display" in kpi

    # 批次结构
    b1 = data["batches"][0]
    assert "id" in b1
    assert "adapter" in b1
    assert "adapter_id" in b1
    assert "status" in b1
    assert "docs" in b1
    assert "ok" in b1
    assert "fail" in b1
    assert "retry" in b1
    assert "detail" in b1

    # 服务端筛选：按平台
    res_ariba = api_client.get("/v1/outbound/batches?adapter=ariba")
    assert res_ariba.status_code == 200
    d_ariba = res_ariba.json()
    assert all(b["adapter_id"] == "ariba" for b in d_ariba["batches"])

    # 服务端筛选：按状态
    res_st = api_client.get("/v1/outbound/batches?status=已完成")
    assert res_st.status_code == 200
    d_st = res_st.json()
    assert all(b["status"] == "已完成" for b in d_st["batches"])


def test_outbound_batch_detail_and_four_doc_types(api_client):
    """断言批次明细包含 Ariba 4 类单据枚举并展示完整字段。"""
    res = api_client.get("/v1/outbound/batches/OB-20261029-001")
    assert res.status_code == 200
    batch = res.json()
    assert batch["id"] == "OB-20261029-001"
    assert len(batch["detail"]) >= 4

    # 提取单据类型枚举
    doc_types = {d["docType"] for d in batch["detail"]}
    assert "Invoice(PO)" in doc_types
    assert "Invoice(Contract)" in doc_types
    assert "Invoice(Non-PO)" in doc_types
    assert "Invoice(Credit Memo)" in doc_types

    # 检查单据明细关键字段
    for d in batch["detail"]:
        assert "caseId" in d
        assert "receipt" in d
        assert "payload" in d
        assert "attach" in d
        assert "writeback" in d
        assert "filing_status" in d
        # 严禁出现「已付款」
        assert "已付款" not in d["filing_status"]
        assert "Ariba 付款成功" not in d["filing_status"]

    # 验证 Credit Memo 带原发票号
    cm_item = next(d for d in batch["detail"] if d["docType"] == "Invoice(Credit Memo)")
    assert "MasterInvoiceNumber" in cm_item.get("payload_body", "")


def test_filing_execution_persists_outbound_record_and_batch(fresh_session):
    """断言 execute_filing 真实落库出站批次与出站单据记录。"""
    # 使用 0387 执行 Ariba 沙箱建档
    c = fresh_session.get(m.Case, "INV-CN-2026-0387")
    res = adapter_service.execute_filing(
        fresh_session,
        adapter_id="ariba",
        case_id="INV-CN-2026-0387",
        is_sandbox=True,
    )
    assert res["success"] is True
    receipt = res["receipt_no"]

    # 查询数据库是否落库出站单据记录
    rec = fresh_session.scalar(
        select(m.OutboundFilingRecord)
        .where(m.OutboundFilingRecord.case_id == "INV-CN-2026-0387")
        .order_by(m.OutboundFilingRecord.id.desc())
    )
    assert rec is not None
    assert rec.receipt_no == receipt
    assert rec.doc_type == "Invoice(PO)"
    assert rec.adapter_id == "ariba"
    assert rec.is_sandbox is True
    assert rec.filing_status == "建档成功/对账完成（生成支付凭证传会计系统）"
    assert "已付款" not in rec.filing_status

    # 查询出站批次 docs / ok 是否递增
    batch = fresh_session.get(m.OutboundBatch, rec.batch_id)
    assert batch is not None
    assert batch.ok >= 1


def test_credit_memo_missing_origin_invoice_blocked(fresh_session):
    """断言红字发票缺失原发票号强阻断出站。"""
    c = fresh_session.get(m.Case, "INV-CN-2026-0384")
    # 0384 未确认 Link 时应直接被阻断
    with pytest.raises(CommandError) as ei:
        adapter_service.execute_filing(
            fresh_session,
            adapter_id="ariba",
            case_id="INV-CN-2026-0384",
            is_sandbox=True,
        )
    assert ei.value.code == "E_LINK_UNCONFIRMED"
    assert "尚未建立/确认冲减 Link" in ei.value.message or "缺失有效原发票号" in ei.value.message


def test_controlled_repush_five_elements_and_backoff(api_client, fresh_session):
    """断言受控重推五要素全序执行、退避拦截与权限控制。"""
    # 查找一条待人工记录 (INV-CN-2026-0381)
    rec = fresh_session.scalar(
        select(m.OutboundFilingRecord)
        .where(m.OutboundFilingRecord.case_id == "INV-CN-2026-0381")
    )
    assert rec is not None
    rec_id = rec.id

    # 1. 权限拦截：复核员王莉无出站重推权限（职责分离）
    ch_rev = api_client.post(
        f"/v1/outbound/records/{rec_id}/risk-challenge",
        json={"actor": "王莉"},
    )
    assert ch_rev.status_code == 403
    assert "复核员不直接重推出站" in ch_rev.json()["detail"]["message"]

    # 2. 正常运营人员刘工签发风险提示与凭据
    ch_res = api_client.post(
        f"/v1/outbound/records/{rec_id}/risk-challenge",
        json={"actor": "刘工"},
    )
    assert ch_res.status_code == 200
    ch_data = ch_res.json()
    assert "token" in ch_data
    assert "risk_text" in ch_data
    assert "INV-CN-2026-0381" in ch_data["risk_text"]

    # 3. 未勾选二次确认拦截
    act_no_self = api_client.post(
        f"/v1/outbound/records/{rec_id}/repush",
        json={
            "actor": "刘工",
            "token": ch_data["token"],
            "self_confirmed": False,
            "opinion": "重新重推",
        },
    )
    assert act_no_self.status_code == 422
    assert "必须勾选二次确认" in act_no_self.json()["detail"]["message"]

    # 4. 执行受控重推（五要素齐全）
    act_res = api_client.post(
        f"/v1/outbound/records/{rec_id}/repush",
        json={
            "actor": "刘工",
            "token": ch_data["token"],
            "self_confirmed": True,
            "opinion": "管理员核实截断策略后重新推放入库",
        },
    )
    assert act_res.status_code == 200
    res_data = act_res.json()
    assert res_data["success"] is True
    assert "AID-2026-" in res_data["receipt_no"]
    assert res_data["filing_status"] == "建档成功/对账完成（生成支付凭证传会计系统）"

    # 5. 凭据一次性防重（幂等防重）
    act_reuse = api_client.post(
        f"/v1/outbound/records/{rec_id}/repush",
        json={
            "actor": "刘工",
            "token": ch_data["token"],
            "self_confirmed": True,
            "opinion": "再次重推",
        },
    )
    assert act_reuse.status_code == 428
    assert "确认凭据已使用" in act_reuse.json()["detail"]["message"] or "凭据" in act_reuse.json()["detail"]["message"]


def test_controlled_repush_backoff_cooldown(fresh_session):
    """断言退避冷静期内重推被强制拦截。"""
    # 构造一条处于退避期内的失败记录
    future_time = (datetime.now(timezone.utc).astimezone() + timedelta(minutes=5)).isoformat(timespec="seconds")
    rec = m.OutboundFilingRecord(
        batch_id="OB-20261029-001",
        case_id="INV-CN-2026-0383",
        adapter_id="ariba",
        doc_type="Invoice(Contract)",
        receipt_no="—",
        payload_summary="cXML · requestId=INV-CN-2026-0383",
        attachment_status="待确认",
        writeback_status="未回写",
        filing_status="失败重试中",
        error_reason="网络超时",
        retry_count=1,
        max_retries=3,
        next_retry_at=future_time,
        created_ts=now_iso(),
        updated_ts=now_iso(),
    )
    fresh_session.add(rec)
    fresh_session.commit()

    with pytest.raises(CommandError) as ei:
        outbound_service.issue_repush_challenge(fresh_session, actor="刘工", record_id=rec.id)
    assert ei.value.code == "E_BACKOFF_ACTIVE"
    assert "退避冷静期" in ei.value.message


def test_list_adapter_queue_reads_db(api_client):
    """断言 list_adapter_queue 端点真实读库返回包含 4 类单据与状态映射。"""
    res = api_client.get("/v1/adapters/ariba/queue")
    assert res.status_code == 200
    q = res.json()["queue"]
    assert len(q) >= 4
    st_set = {item["status"] for item in q}
    assert "ok" in st_set
    assert "retry" in st_set
    assert "manual" in st_set
