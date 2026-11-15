# -*- coding: utf-8 -*-
"""混合 PDF 前置切分与 Supporting Documents 剥离清洗真实断言测试（20261102 专家口径 S5 第 6 条 · #65）。

验收要点：
1. 对多页 PDF 标记识别出 invoice_pages 与 supporting_doc_pages；
2. 非发票页面转为案件 Supporting Attachment 留存归档链接，不送入主票据 OCR 引擎（数据最小外发）；
3. 受理完成面板与文件明细行呈现「包含支持文档附件 N 页（已清洗剥离）」状态徽章（演示口径：规则切分）；
4. 当扫描图像置信度过低（发票内容不清，S5 第 1 条）时，标记 NEEDS_REVIEW 并高亮提示人工介入复核；
5. 前端 HTML 存在对应接线与演示标注。
"""

from sqlalchemy import select

from app.domain import models as m
from app.services import persistence


# 构造一个含 3 个 /Type /Page 对象的混合 PDF 字节流
MOCK_3PAGE_MIXED_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R 4 0 R 5 0 R] /Count 3 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R >>
endobj
4 0 obj
<< /Type /Page /Parent 2 0 R >>
endobj
5 0 obj
<< /Type /Page /Parent 2 0 R >>
endobj
xref
0 6
0000000000 65535 f
0000000010 00000 n
0000000060 00000 n
0000000130 00000 n
0000000180 00000 n
0000000230 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
280
%%EOF
"""


def _upload_file(api_client, name: str, content: bytes):
    meta = [{"name": name, "size": len(content), "mime": "application/pdf"}]
    ch = api_client.post(
        "/v1/intake/upload/risk-challenge",
        json={"actor": "陈铮", "instance": "CN", "action": "intake", "files": meta},
    )
    assert ch.status_code == 200, ch.json()
    tok = ch.json()["token"]
    data = {"actor": "陈铮", "instance": "CN", "token": tok, "self_confirmed": "true"}
    files = [("files", (name, content, "application/pdf"))]
    r = api_client.post("/v1/intake/upload", data=data, files=files)
    assert r.status_code == 200, r.json()
    return r.json()


def test_mixed_pdf_supporting_documents_split_and_link(api_client):
    """断言 1：多页混合 PDF 切分、Supporting Documents 剥离并在 ObjectLink 挂载存证。"""
    res = _upload_file(
        api_client,
        name="发票_含送货单签收单_mixed.pdf",
        content=MOCK_3PAGE_MIXED_PDF,
    )
    bid = res["batch_id"]
    files = res.get("files") or []
    assert len(files) == 1
    f0 = files[0]
    case_id = f0["caseId"]
    assert case_id is not None

    # 1. 验证步骤 ① 中记录了支持文档清洗剥离
    s1 = next(s for s in f0["steps"] if s["no"] == 1)
    detail1 = s1["detail"]
    assert detail1["total_pages"] == 3
    assert detail1["has_supporting_docs"] is True
    assert detail1["supporting_pages_count"] == 2
    assert "包含支持文档附件 2 页（已清洗剥离）" in detail1["supporting_badge"]

    # 2. 验证批次详情接口 GET /v1/batches/{id} 返回了 supporting_badge
    bdet = api_client.get(f"/v1/batches/{bid}").json()
    fdet0 = bdet["files_detail"][0]
    assert fdet0["has_supporting_docs"] is True
    assert fdet0["supporting_pages_count"] == 2
    assert fdet0["supporting_badge"] == "包含支持文档附件 2 页（已清洗剥离）"

    # 3. 验证数据库中 Case 对象的 file_raw（严守 invoice-case.schema.json 契约，零非法扩展字段）
    with persistence.get_session() as s:
        case = s.get(m.Case, case_id)
        assert case is not None
        assert case.file_raw["pages"] == 3
        assert "已清洗剥离支持文档附件 2 页" in case.file_raw["note"]

        # 4. 验证 ObjectLink 存在 link_type="包含" 记录（FN-0-04 / S5 #65）
        links = list(
            s.scalars(
                select(m.ObjectLink)
                .where(
                    m.ObjectLink.case_id == case_id,
                    m.ObjectLink.link_type == "包含",
                )
            )
        )
        assert len(links) >= 1
        supp_link = links[0]
        assert supp_link.link_raw["type"] == "supporting_attachment"
        assert supp_link.link_raw["cleaned_and_stripped"] is True
        assert supp_link.link_raw["pages"] == [2, 3]
        assert "S5 #65" in supp_link.link_raw["note"]

        # 5. 验证外发台账 EgressLog（OCR 路由下非发票页面不送入主 OCR 引擎）
        egress = list(
            s.scalars(
                select(m.EgressLog).where(m.EgressLog.batch_id == bid)
            )
        )
        if egress:
            for eg in egress:
                # bytes_out 严格小于原始多页内容总长度
                assert eg.bytes_out < len(MOCK_3PAGE_MIXED_PDF)
                assert "已清洗剥离" in eg.note


def test_low_confidence_scan_forces_needs_review(api_client):
    """断言 2：扫描图像置信度过低（<80%）时，标记 NEEDS_REVIEW 并高亮提示人工介入复核（S5 第 1 条）。"""
    res = _upload_file(
        api_client,
        name="增值税发票_模糊_low_conf_001.pdf",
        content=MOCK_3PAGE_MIXED_PDF,
    )
    bid = res["batch_id"]
    case_id = res["files"][0]["caseId"]

    # 1. 验证生成的案件置信度 < 80 且状态为 NEEDS_REVIEW
    with persistence.get_session() as s:
        case = s.get(m.Case, case_id)
        assert case is not None
        assert case.confidence < 80
        assert case.confidence == 72
        assert case.status == "NEEDS_REVIEW"

    # 2. 验证批次明细返回的 status_snapshot 为 NEEDS_REVIEW 且标记为 bad/needs_review
    bdet = api_client.get(f"/v1/batches/{bid}").json()
    fdet0 = bdet["files_detail"][0]
    assert fdet0["status_snapshot"] == "NEEDS_REVIEW"
    assert fdet0["conf"] == 72
    assert fdet0["bad"] is True
    assert fdet0["needs_review"] is True
    assert "80% 阈值" in fdet0["note"] or "强制人工复核" in fdet0["note"]


def test_intake_html_contains_supporting_documents_elements(client):
    """断言 3：前端 invoice-intake.html 包含支持文档剥离徽章、演示口径标注与人工复核提示。"""
    resp = client.get("/web/invoice-intake.html")
    assert resp.status_code == 200
    html = resp.text

    assert "已清洗剥离" in html
    assert "演示口径：规则切分" in html
    assert "Supporting Attachment" in html
    assert "强制转入人工介入复核队列" in html
