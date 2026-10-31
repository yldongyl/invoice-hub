# -*- coding: utf-8 -*-
"""Provider SPI 契约测试与 Stub 矩阵断言（WP4.1 · FN-2-02/13 · FN-A-05）。

验证要点：
  1. 六个 stub Provider（百望云、诺诺、客户自有 OCR、自托管 OCR-VLM、海外 e-invoicing、人工兜底）
     全部实现 capabilities、recognize、verify（查验类）方法；
  2. capabilities() 声明全部通过 provider-spi.schema.json 的 CapabilitiesDeclaration 校验；
  3. recognize() 归一化输出全部通过 ProviderResult 校验（字段六枚举、坐标、原文片段、模型版本）；
  4. verify() 输出全部通过 VerifyResult 校验（包含 gm-rcpt-* 验签/查验回执）；
  5. SIM 置信度矩阵口径（纸质专票百望云 0.82、诺诺 0.91、客户自有 OCR 0.88；海外 Supplier Invoice / Credit Note 对齐）；
  6. 负向用例：契约校验器对非法格式（非法字段来源、非法区域枚举、负数金额缺失等）能准确检出。
"""

import pytest

from app.services.providers import get_provider, list_spi_providers
from app.services.providers.base import (
    validate_capabilities,
    validate_recognize_result,
    validate_verify_result,
)


def test_all_six_providers_registered():
    """断言 6 个 Provider 全部实装且注册成功。"""
    providers = list_spi_providers()
    assert len(providers) == 6
    p_ids = {p.provider_id for p in providers}
    expected = {
        "bwyun-cn",
        "nuonuo-cn",
        "customer-ocr",
        "selfhosted-ocr-vlm",
        "overseas-einv-sg",
        "human-fallback",
    }
    assert p_ids == expected


@pytest.mark.parametrize("provider_id", [
    "bwyun-cn",
    "nuonuo-cn",
    "customer-ocr",
    "selfhosted-ocr-vlm",
    "overseas-einv-sg",
    "human-fallback",
])
def test_provider_capabilities_contract(provider_id):
    """断言每个 Provider 的 capabilities() 均合乎 SPI JSON Schema。"""
    p = get_provider(provider_id)
    assert p is not None
    caps = p.capabilities()
    errs = validate_capabilities(caps)
    assert not errs, f"{provider_id} capabilities 不符合契约: {errs}"

    # 关键属性断言
    assert caps["provider_id"] == provider_id
    assert caps["deploy_mode"] in ["API（SaaS）", "客户环境 API", "私有化自托管（GPU）", "平台复核工作台"]
    assert caps["provider_label"] in ["商业厂商", "客户已有", "私有化", "平台内置"]
    assert isinstance(caps["sla"]["availability_pct"], (int, float))
    assert isinstance(caps["sla"]["p95_latency_ms"], (int, float))
    if provider_id == "human-fallback":
        assert caps.get("lock") is True
    else:
        assert caps.get("lock") is False


@pytest.mark.parametrize("provider_id", [
    "bwyun-cn",
    "nuonuo-cn",
    "customer-ocr",
    "selfhosted-ocr-vlm",
    "overseas-einv-sg",
    "human-fallback",
])
def test_provider_recognize_contract(provider_id):
    """断言每个 Provider 的 recognize() 输出均合乎 ProviderResult 契约。"""
    p = get_provider(provider_id)
    payload = {
        "file_ref": f"mock://samples/{provider_id}_invoice.pdf",
        "mime_type": "application/pdf",
        "sha256": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
        "instance": "CN" if "cn" in provider_id or provider_id in ("customer-ocr", "selfhosted-ocr-vlm", "human-fallback") else "OS",
        "doc_type_hint": "增值税专票/普票（纸质扫描）",
        "request_id": f"req-test-{provider_id}",
    }
    res = p.recognize(payload)
    errs = validate_recognize_result(res)
    assert not errs, f"{provider_id} recognize 结果不符合契约: {errs}"

    # 字段来源必须在 enum-registry 六枚举内
    valid_sources = {"xml_direct", "ocr", "qr_code", "model", "manual", "webhook"}
    for f in res["fields"]:
        assert f["source"] in valid_sources
        assert 0.0 <= f["confidence"] <= 1.0
        assert f["name"] is not None
        assert f["raw_text"] is not None

    # meta 结构完整
    assert res["meta"]["provider_id"] == provider_id
    assert res["meta"]["cost"]["currency"] in ["CNY", "SGD", "USD"]


def test_sim_confidence_matrix():
    """验证 SIM 置信度矩阵口径（纸质专票百望云 0.82、诺诺 0.91、客户自有 OCR 0.88 等）。"""
    bw = get_provider("bwyun-cn")
    nn = get_provider("nuonuo-cn")
    cust = get_provider("customer-ocr")
    vlm = get_provider("selfhosted-ocr-vlm")
    sg = get_provider("overseas-einv-sg")

    # 1. 增值税专票/普票（纸质扫描）
    payload_paper = {
        "file_ref": "mock://test.pdf",
        "mime_type": "application/pdf",
        "sha256": "1234567890abcdef",
        "instance": "CN",
        "doc_type_hint": "增值税专票/普票（纸质扫描）",
    }
    res_bw = bw.recognize(payload_paper)
    res_nn = nn.recognize(payload_paper)
    res_cust = cust.recognize(payload_paper)

    conf_bw = res_bw["fields"][0]["confidence"]
    conf_nn = res_nn["fields"][0]["confidence"]
    conf_cust = res_cust["fields"][0]["confidence"]

    assert conf_bw == 0.82, f"百望云纸质专票置信度应为 0.82，实际 {conf_bw}"
    assert conf_nn == 0.91, f"诺诺纸质专票置信度应为 0.91，实际 {conf_nn}"
    assert conf_cust == 0.88, f"客户自有 OCR 纸质专票置信度应为 0.88，实际 {conf_cust}"

    # 2. 数电票百望云 0.97
    payload_einvoice = {**payload_paper, "doc_type_hint": "数电票"}
    assert bw.recognize(payload_einvoice)["fields"][0]["confidence"] == 0.97

    # 3. 海外 Supplier Invoice: 新加坡 0.93，自托管 VLM 0.90
    payload_sup = {**payload_paper, "doc_type_hint": "Supplier Invoice", "instance": "OS"}
    assert sg.recognize(payload_sup)["fields"][0]["confidence"] == 0.93
    assert vlm.recognize(payload_sup)["fields"][0]["confidence"] == 0.90

    # 4. 海外 Credit Note: 新加坡 0.78，自托管 VLM 0.74
    payload_cn = {**payload_paper, "doc_type_hint": "Credit Note", "instance": "OS"}
    assert sg.recognize(payload_cn)["fields"][0]["confidence"] == 0.78
    assert vlm.recognize(payload_cn)["fields"][0]["confidence"] == 0.74


@pytest.mark.parametrize("provider_id", ["bwyun-cn", "nuonuo-cn", "overseas-einv-sg"])
def test_verify_contract(provider_id):
    """验证查验类 Provider verify() 输出过 VerifyResult 契约。"""
    p = get_provider(provider_id)
    payload = {
        "caseId": "INV-CN-2026-0387",
        "fields": {"invoice_no": "24312000000012345678", "gross": 113000.0},
        "channel": "tax_auth",
    }
    res = p.verify(payload)
    assert res is not None
    errs = validate_verify_result(res)
    assert not errs, f"{provider_id} verify 输出不符契约: {errs}"
    assert res["result"] in ["PASSED", "NOT_VERIFIED", "FAILED"]
    assert res["receipt"]["receipt_no"].startswith("gm-rcpt-")
    assert res["receipt"]["archived"] is True


def test_schema_validators_negative():
    """负向测试：校验器准确识别非法输出。"""
    # 1. 字段来源非法（违反 enum-registry 六枚举）
    bad_res = {
        "fields": [
            {
                "name": "total.gross_amount",
                "value": 100,
                "confidence": 0.9,
                "source": "illegal_source",  # 不在六枚举
                "bbox": None,
                "raw_text": "100",
                "model_version": None,
            }
        ],
        "meta": {"provider_id": "bwyun-cn", "latency_ms": 100, "cost": {"currency": "CNY", "amount": 0.08}},
    }
    errs = validate_recognize_result(bad_res)
    assert len(errs) > 0

    # 2. 查验回执格式不匹配 gm-rcpt-*
    bad_ver = {
        "result": "PASSED",
        "receipt": {"receipt_no": "bad-receipt-format", "archived": True},
    }
    errs = validate_verify_result(bad_ver)
    assert len(errs) > 0
