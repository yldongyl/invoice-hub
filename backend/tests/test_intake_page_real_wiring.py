# -*- coding: utf-8 -*-
"""受理页（invoice-intake.html）实装接线真实断言测试。

覆盖验收清单：
1. 失败文件行出现「只重试相关步骤」按钮，调用后端后 DB 中该文件 steps 状态真实变化（live 态）；
2. 渠道配置变更走完 risk-challenge → publish，审计链新增对应块，config_version 徽章刷新为服务端值；
3. 完成面板步骤与案件带 field_source 枚举徽章（xml_direct / ocr），桩步骤标注「演示口径」；
4. demo 回退包含假象声明（ADR-0003）；
5. KPI 卡区域注记「统计口径与审计中心 Tab2 同源」（CON-B4/B6）。
"""

from sqlalchemy import select

from app.domain import models as m
from app.services import persistence, sm2_service

SAMPLE_XML = sm2_service.attach_signature(
    """<?xml version="1.0" encoding="UTF-8"?>
<EInvoice xmlns="urn:cn:tax:einvoice:1.0">
  <Header><InvoiceNo>2431200000088991</InvoiceNo><IssueDate>2026-10-28</IssueDate>
  <InvoiceType>数电票（增值税专用发票）</InvoiceType></Header>
  <Seller><Name>广州精密机械制造有限公司</Name><TaxID>91440101MA59KM1234</TaxID></Seller>
  <Buyer><Name>澜坞（上海）采购科技有限公司</Name><TaxID>91310115MA1K35QT7B</TaxID></Buyer>
  <Items><Item lineNo="1"><Name>*机械部件*高精轴承</Name><Spec>A-1</Spec><Unit>套</Unit>
  <Qty>50</Qty><Price>200.00</Price><TaxRate>0.13</TaxRate><Amount>10000.00</Amount></Item></Items>
  <Total><NetAmount>10000.00</NetAmount><TaxAmount>1300.00</TaxAmount>
  <GrossAmount>11300.00</GrossAmount></Total>
</EInvoice>
"""
)


def _do_upload(api_client, name="数电票_广州精密_88991.xml", content=SAMPLE_XML):
    meta = [{"name": name, "size": len(content), "mime": "application/xml"}]
    ch = api_client.post(
        "/v1/intake/upload/risk-challenge",
        json={"actor": "陈铮", "instance": "CN", "action": "intake", "files": meta},
    )
    assert ch.status_code == 200, ch.json()
    tok = ch.json()["token"]
    data = {"actor": "陈铮", "instance": "CN", "token": tok, "self_confirmed": "true"}
    files = [("files", (name, content, "application/xml"))]
    r = api_client.post("/v1/intake/upload", data=data, files=files)
    assert r.status_code == 200, r.json()
    return r.json()


def test_retry_file_failed_steps_live_db_state_and_audit(api_client):
    """验收点 1：失败文件 steps 状态经 retry-steps 后在 DB 中真实从 FAILED 变为 DONE，并写入审计链。"""
    up = _do_upload(api_client)
    bid = up["batch_id"]

    # 1. 模拟步骤 ③ 载体检测失败（置为 FAILED 态），模拟网络/解析中断
    with persistence.get_session() as s:
        step3 = s.scalar(
            select(m.FileStep).where(
                m.FileStep.batch_id == bid,
                m.FileStep.file_seq == 0,
                m.FileStep.step_no == 3,
            )
        )
        assert step3 is not None
        step3.status = "FAILED"
        step3.detail_raw = {"error": "网络超时模拟"}
        f_intake = s.scalar(
            select(m.FileIntake).where(
                m.FileIntake.batch_id == bid, m.FileIntake.seq == 0
            )
        )
        assert f_intake is not None
        f_intake.disposition = "FAILED"
        s.commit()

    # 2. 验证前端展开读到的状态确实为 FAILED
    det1 = api_client.get(f"/v1/batches/{bid}").json()
    f0_det = det1["files_detail"][0]
    s3_info = next(st for st in f0_det["steps"] if st["no"] == 3)
    assert s3_info["status"] == "FAILED"
    assert f0_det["disposition"] == "FAILED"

    # 3. 触发「只重试相关步骤」端点 (POST /v1/batches/{id}/files/{seq}/retry-steps)
    res = api_client.post(f"/v1/batches/{bid}/files/0/retry-steps")
    assert res.status_code == 200, res.json()
    res_data = res.json()
    # 真实重试了步骤 3
    assert res_data["retried_steps"] == [3]
    assert "trace" in res_data

    # 4. 验证 DB 中 steps 状态已真实恢复为 DONE，disposition 恢复为 ACCEPTED
    with persistence.get_session() as s:
        step3_after = s.scalar(
            select(m.FileStep).where(
                m.FileStep.batch_id == bid,
                m.FileStep.file_seq == 0,
                m.FileStep.step_no == 3,
            )
        )
        assert step3_after.status == "DONE"

        f_intake_after = s.scalar(
            select(m.FileIntake).where(
                m.FileIntake.batch_id == bid, m.FileIntake.seq == 0
            )
        )
        assert f_intake_after.disposition == "ACCEPTED"

        # 5. 验证审计链新增了 retry-file 记录（FN-1-07 审计留痕）
        audits = list(
            s.scalars(
                select(m.AuditBlock)
                .where(m.AuditBlock.op_component == "batch-ops/retry-file")
                .order_by(m.AuditBlock.blk.desc())
            )
        )
        assert len(audits) >= 1
        latest_audit = audits[0]
        assert "只重试相关步骤" in latest_audit.note
        assert bid in latest_audit.note
        assert latest_audit.trace == res_data["trace"]


def test_channel_config_risk_challenge_to_publish_full_chain(api_client):
    """验收点 2：渠道配置变更走完 risk-challenge → publish，审计链留痕，版本递增，KMS 掩码保持。"""
    # 1. 读初始配置
    channels_before = api_client.get("/v1/intake/channels").json()["items"]
    portal_before = next(x for x in channels_before if x["channel"] == "门户上传")
    old_version = portal_before.get("config_version")

    # 2. 发起 risk-challenge (FN-1-11 / FN-0-08 要素二)
    key = "channel:门户上传"
    ch = api_client.post(
        f"/v1/config/{key}/risk-challenge",
        json={"actor": "陈铮", "instance": "CN", "action": "publish"},
    )
    assert ch.status_code == 200, ch.json()
    ch_data = ch.json()
    assert "token" in ch_data
    assert "risk_text" in ch_data

    # 3. 提交受控 publish (五要素：actor/token/self_confirmed/config_key/config_payload/opinion)
    pub = api_client.post(
        "/v1/config/actions/publish",
        json={
            "actor": "陈铮",
            "instance": "CN",
            "token": ch_data["token"],
            "self_confirmed": True,
            "config_key": key,
            "config_payload": {
                "max_file_size_mb": 18,
                "max_batch_files": 35,
                "allowed_types": ["xml", "ofd", "pdf"],
            },
            "opinion": "收紧门户单次批量上限至 35 件（运维安全变更）",
        },
    )
    assert pub.status_code == 200, pub.json()
    pub_data = pub.json()
    new_version = pub_data["version"]
    assert new_version != old_version
    assert new_version.startswith("v")

    # 4. 重新查询 channels 端点：验证版本已更新为服务端值，且凭证字段仍被 KMS 掩码
    channels_after = api_client.get("/v1/intake/channels").json()["items"]
    portal_after = next(x for x in channels_after if x["channel"] == "门户上传")
    assert portal_after["config_version"] == new_version
    assert portal_after["config"]["max_file_size_mb"] == 18
    assert portal_after["config"]["max_batch_files"] == 35

    api_ch = next(x for x in channels_after if x["channel"] == "API 集成")
    assert "KMS" in api_ch["config"]["appkey_credential"]

    # 5. 校验审计链中包含本次 channel_config publish 记录
    with persistence.get_session() as s:
        audit_row = s.scalar(
            select(m.AuditBlock)
            .where(
                m.AuditBlock.act == "POLICY_PUBLISHED",
            )
            .order_by(m.AuditBlock.blk.desc())
        )
        assert audit_row is not None
        assert "channel_config" in audit_row.note or "门户上传" in audit_row.note


def test_intake_html_ui_wiring_and_field_source_markers(client):
    """验收点 3~5：页面包含只重试相关步骤、渠道配置受控弹层、field_source 徽章、demo 假象声明与 KPI 同源注记。"""
    resp = client.get("/web/invoice-intake.html")
    assert resp.status_code == 200
    html = resp.text

    # 任务 1：文件级「只重试相关步骤」UI 入口与处理函数
    assert "ihub-retry-steps-btn" in html
    assert "ihRetryFileSteps" in html
    assert "只重试相关步骤" in html

    # 任务 2：渠道配置受控变更入口（FN-1-11）
    assert "ihOpenChannelConfig" in html
    assert "channel-config-modal" in html
    assert "channel-challenge-modal" in html
    assert "ihSubmitChannelConfig" in html
    assert "ihConfirmPublishChannelConfig" in html
    assert "ch-chal-confirm" in html
    assert "/v1/config/actions/publish" in html

    # 任务 3：field_source 来源徽章与演示口径角标（FN-1-05 / §6）
    assert "fieldSourceBadge" in html
    assert "xml_direct" in html
    assert "XML 直读" in html
    assert "演示口径" in html

    # 任务 4：demo 回退假象声明（ADR-0003）
    assert "演示数据：案件号与摘要为示意" in html
    assert "ADR-0003" in html

    # 任务 5：KPI 口径同源注记（CON-B4/B6）
    assert "统计口径与审计中心 Tab2 同源" in html
    assert "CON-B4/B6" in html


def test_seed_batch_retry_file_steps_endpoint(api_client):
    """测试种子批次 BT-20261020-005（部分异常）点击「只重试相关步骤」成功不报错 500。"""
    res = api_client.post("/v1/batches/BT-20261020-005/files/0/retry-steps")
    assert res.status_code == 200, res.json()
    data = res.json()
    assert data["batch"] == "BT-20261020-005"
    assert data["seq"] == 0
    assert data["retried_steps"] == [3]
    assert data["status"] == "RECOGNIZED"
    assert "trace" in data

    # 再次查询批次明细：该文件状态已更新
    det = api_client.get("/v1/batches/BT-20261020-005").json()
    f0 = det["files_detail"][0]
    assert f0["bad"] is False
    assert "重试成功" in f0["note"]
