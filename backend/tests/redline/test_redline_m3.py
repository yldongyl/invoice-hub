# -*- coding: utf-8 -*-
"""红线回归集 R-01~R-06（P08 §1.4 · tests/redline/ 每里程碑门禁必跑）。

M3 适用条目建立：**R-01/R-02/R-03/R-06 全数通过**；R-04（告警停用拦截=FN-9-08 管理面）
与 R-05（agent 层写路径静态检查）依赖 M5 面，按 pytest.skip 登记去向——
R-05 的 backend 侧代偿（零 LLM 依赖/写路径不经 LLM）由 test_dependency_discipline 常驻覆盖，
本文件另立行为断言「LLM 输出不落 checks」的结构走查（inspect 源审计）。
失败信息规范同 P08 §2（RL-xx 前缀+断言点+期望/实际+FN）。
"""

import inspect

import pytest
from sqlalchemy import func, select

from app.domain import models as m
from app.services import audit_chain, governed_commands as gc, persistence, state_machine
from app.services.state_machine import STATUS

pytestmark = pytest.mark.redline


def rl(cond, rid, point, want, got, fn):
    if not cond:
        raise AssertionError(f"[{rid}] 断言点：{point} | 期望：{want} | 实际：{got} | 关联 FN：{fn}")


# ── R-01 低置信（<80）案件不存在任何自动放行路径（行为用例+代码走查） ──

def test_r01_low_confidence_has_no_auto_release(fresh_session):
    rid = "R-01"
    # 行为：conf 70 + Checks 全 PASSED 的 RECOGNIZED 案件 → 自动链只能进人工队列，不得直达 RESOLVED
    c = fresh_session.get(m.Case, "INV-CN-2026-0386")          # seed 唯一 RECOGNIZED CN 案
    c.meta_raw = {**c.meta_raw, "confidence": 70}              # meta_raw 为真相源（_sync_meta 会回刷投影列）
    c.confidence = 70
    c.checks_raw = {item: {"result": "PASSED", "note": "R-01 注入（全通过假象）"}
                    for item in ("supplierMatch", "authenticity", "duplicate", "poMatch")}
    fresh_session.commit()
    cands = state_machine.evaluate(fresh_session, "INV-CN-2026-0386")
    rl(all(e["to"] != "RESOLVED" for e in cands), rid, "RECOGNIZED 低置信评估不产出 RESOLVED 边",
       "无 RESOLVED 候选", cands, "FN-0-02/5-05")
    path = state_machine.auto_flow(fresh_session, "INV-CN-2026-0386")
    rl([t["to"] for t in path] == ["NEEDS_REVIEW"], rid, "auto_flow 终态停在人工队列",
       ["NEEDS_REVIEW"], [t["to"] for t in path], "FN-0-02")
    # 人工队列内同样封死自动放行：<80 红档时「全 PASSED 自动路径」边不得触发
    again = state_machine.evaluate(fresh_session, "INV-CN-2026-0386")
    rl(all(e["to"] != "RESOLVED" for e in again), rid, "NEEDS_REVIEW+全 PASSED 但 conf<80 仍无自动放行",
       "无 RESOLVED 候选", again, "FN-0-06/5-05/P00 §5")
    # 代码走查：①RESOLVED 边的来源态只允许人工队列态；②自动放行下限=红档界 80（registry 解析）
    edges, _ = state_machine.load_edges()
    res_sources = {frm for (frm, to) in edges if to == "RESOLVED"}
    rl(res_sources == {STATUS.NEEDS_REVIEW, STATUS.INVESTIGATING}, rid,
       "state_transition 中 RESOLVED 来源态集合", "{NEEDS_REVIEW, INVESTIGATING}", res_sources, "FN-0-02")
    rl(state_machine._auto_release_floor() == 80, rid, "自动放行置信度下限（registry「<80%」解析）",
       "80", state_machine._auto_release_floor(), "FN-0-06")
    src = inspect.getsource(state_machine.evaluate)
    rl("_auto_release_floor" in src, rid, "evaluate 源码含低置信自动放行闸门", "存在", "", "FN-5-05")


# ── R-02 验签失败→BLOCKED 不可绕过（含配置篡改尝试） ──

def test_r02_sm2_failed_blocked_not_bypassable(api_client, tmp_path, monkeypatch):
    rid = "R-02"
    from app.services import object_store, sm2_service
    monkeypatch.setattr(object_store, "OBJECTS_DIR", tmp_path / "objects")
    monkeypatch.setattr(sm2_service, "GM_RECEIPT_DIR", tmp_path / "gm-receipts")
    signed = sm2_service.attach_signature(
        """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header><InvoiceNo>2444200000060001</InvoiceNo><IssueDate>2026-10-27</IssueDate>
  <InvoiceType>数电票（增值税专用发票）</InvoiceType></Header>
  <Seller><Name>红线演示供应商</Name><TaxID>91310000MA1FL0000X</TaxID></Seller>
  <Buyer><Name>澜坞（上海）采购科技有限公司</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Total><NetAmount>10000.00</NetAmount><TaxAmount>1300.00</TaxAmount>
  <GrossAmount>11300.00</GrossAmount></Total>
</EInvoice>
""".encode("utf-8").decode())
    tampered = signed.replace(b"11300.00", b"99999.00")
    ch = api_client.post("/v1/intake/upload/risk-challenge",
                         json={"actor": "陈铮", "instance": "CN", "action": "intake",
                               "files": [{"name": "a.xml", "size": len(tampered), "mime": None}]})
    r = api_client.post("/v1/intake/upload",
                        data={"actor": "陈铮", "instance": "CN", "token": ch.json()["token"],
                              "self_confirmed": "true"},
                        files=[("files", ("a.xml", tampered, "application/xml"))])
    cid = r.json()["files"][0]["caseId"]
    c = api_client.get(f"/v1/cases/{cid}?instance=CN").json()
    rl(c["status"] == "BLOCKED", rid, "验签失败案件态", "BLOCKED", c["status"], "FN-5-01/0-02")
    # 绕过尝试①：直接单人 release BLOCKED → 状态机/命令双层拒绝
    tok = api_client.post(f"/v1/cases/{cid}/risk-challenge",
                          json={"actor": "王莉", "instance": "CN", "action": "release"}).json()["token"]
    rr = api_client.post(f"/v1/cases/{cid}/actions/release",
                         json={"actor": "王莉", "instance": "CN", "token": tok, "self_confirmed": True})
    rl(rr.status_code == 409 and rr.json()["detail"]["error_code"] == "STATE_PRECONDITION",
       rid, "BLOCKED 单人放行拒绝", "409 STATE_PRECONDITION", rr.json(), "FN-0-08/8-06/5-05")
    # 绕过尝试②：配置篡改放松校验标准——红线关联键关闭被发布层拦截
    pub = api_client.post("/v1/config/low_confidence_force_human/risk-challenge",
                          json={"actor": "陈铮", "instance": "CN", "action": "publish"})
    tok2 = pub.json()["token"]
    bad = api_client.post("/v1/config/actions/publish",
                          json={"actor": "陈铮", "instance": "CN", "token": tok2, "self_confirmed": True,
                                "config_key": "low_confidence_force_human",
                                "config_payload": {"label": "低置信强制人工", "value": False, "note": "R-02 注入"}})
    rl(bad.status_code == 403 and bad.json()["detail"]["error_code"] == "E_CONFIG_REDLINE_BYPASS",
       rid, "放松校验标准的配置篡改被拒", "403 E_CONFIG_REDLINE_BYPASS", bad.json(), "FN-9-09/5-05/P00 §5")


# ── R-03 BLOCKED 不可批量放行 ──

def test_r03_blocked_never_batch_released(api_client):
    rid = "R-03"
    ids = ["INV-CN-2026-0385", "INV-CN-2026-0379"]
    tok = api_client.post("/v1/batch/risk-challenge", json={"actor": "王莉", "instance": "CN",
                                                            "action": "batch_release",
                                                            "case_ids": ids}).json()["token"]
    r = api_client.post("/v1/batch/actions/batch_release",
                        json={"actor": "王莉", "instance": "CN", "token": tok, "self_confirmed": True,
                              "opinion": "R-03 注入：尝试批量放行 BLOCKED", "case_ids": ids})
    body = r.json()
    rl(r.status_code == 200 and body["processed"] == 0 and body["skipped_count"] == 2
       and all("BLOCKED 不可批量放行" in s["reason"] for s in body["skipped"]),
       rid, "批量放行全跳且列因", "processed=0·skipped=2·含红线原因", body, "FN-0-08/8-06")
    still = [api_client.get(f"/v1/cases/{i}?instance=CN").json()["status"] for i in ids]
    rl(still == ["BLOCKED", "BLOCKED"], rid, "批量操作后 BLOCKED 态零变化",
       "两案仍 BLOCKED", still, "FN-0-08")
    with persistence.get_session() as s:
        n = s.scalar(select(func.count()).select_from(m.AuditBlock).where(
            m.AuditBlock.act == "ACTION_RELEASE", m.AuditBlock.case_id.in_(ids)))
        rl(n == 0, rid, "无任何 ACTION_RELEASE 块写入（拒绝路径零留痕污染、也不伪造放行）",
           "0", n, "FN-0-10/0-08")


# ── R-05（M3 代偿子集）：checks/status 写入通道与 LLM 无关（结构走查） ──

def test_r05_backend_write_paths_free_of_model(api_client):
    rid = "R-05（backend 代偿；agent 层随 M5）"
    src_gc = inspect.getsource(gc._do_edit_field)
    rl("checks_raw" not in src_gc, rid, "edit_field 不触碰 checks（模型/人工均不得写校验槽）",
       "无 checks_raw", "见源码", "FN-0-09/0-07")
    src_pipe = inspect.getsource(__import__("app.services.intake_pipeline", fromlist=["_"])._derive_case)
    rl("checks_raw" not in src_pipe, rid, "受理派生不直写 checks（唯一入口=orchestrator.apply_results）",
       "无 checks_raw", "见源码", "FN-0-07/依赖纪律⑥")
    with persistence.get_session() as s:
        # 行为对照：0387 的 checks 与 AI 卡内容（seed ai 为展示件）不同源——checks 更新只经 apply_results 通道
        c = s.get(m.Case, "INV-CN-2026-0387")
        rl(set(c.checks_raw) == {"supplierMatch", "authenticity", "duplicate", "poMatch"},
           rid, "checks 键集恒为规则四槽", "四槽", list(c.checks_raw), "FN-0-07")


# ── R-06 写操作无审计记录→失败（审计双写完整性，注入链断） ──

@pytest.mark.parametrize("action,case,inst,extra", [
    ("release", "INV-CN-2026-0381", "CN", {"opinion": "R-06 注入"}),
    ("hold", "INV-CN-2026-0384", "CN", {}),
    ("claim", "INV-CN-2026-0387", "CN", {}),
])
def test_r06_write_without_audit_rolls_back(api_client, action, case, inst, extra):
    rid = "R-06"
    tok = api_client.post(f"/v1/cases/{case}/risk-challenge",
                          json={"actor": "王莉", "instance": inst, "action": action}).json()["token"]
    with persistence.get_session() as s:
        before = s.scalar(select(func.count()).select_from(m.AuditBlock))
    orig = gc.append_block
    orig_sm = state_machine.append_block
    def boom(*a, **k):
        raise RuntimeError("审计链注入断链")
    gc.append_block = boom
    state_machine.append_block = boom
    try:
        r = api_client.post(f"/v1/cases/{case}/actions/{action}",
                            json={"actor": "王莉", "instance": inst, "token": tok,
                                  "self_confirmed": True, **extra})
        rl(r.status_code == 500 and r.json()["detail"]["error_code"] == "E_AUDIT_WRITE_FAILED",
           rid, f"{action} 在审计写入失败时整笔拒绝", "500 E_AUDIT_WRITE_FAILED", r.json(), "FN-0-08 要素⑤")
    finally:
        gc.append_block = orig
        state_machine.append_block = orig_sm
    c = api_client.get(f"/v1/cases/{case}?instance={inst}").json()
    with persistence.get_session() as s:
        after = s.scalar(select(func.count()).select_from(m.AuditBlock))
    expected_status = {"release": "NEEDS_REVIEW", "hold": "NEEDS_REVIEW", "claim": "NEEDS_REVIEW"}[action]
    rl(c["status"] == expected_status, rid, f"{action} 回滚后案件态不变", expected_status, c["status"], "FN-0-08")
    rl(after == before, rid, f"{action} 失败不留半块（链计数不变）", before, after, "FN-0-10")


# ── R-04：M5 面移交注记（当前无停用入口=无从绕过；admin Tab2 落地时补拦截断言） ──

@pytest.mark.skip(reason="R-04 红线告警不可停用：停用入口=FN-9-08 告警引擎管理面（M5/WP3.6 之外的里程碑）；"
                         "M3 代偿=告警仅由确定性服务生成（dedup/compliance），无删除 API——models.Alert 无更新面，"
                         "WORM 由 audit_chain 事件保障。随 P06/M5 建立。")
def test_r04_redline_alert_not_disableable():
    pass
