# -*- coding: utf-8 -*-
"""百望云 Provider SPI Stub（FN-2-02/13 · 演示口径）。"""

from typing import Any
from app.services.providers.base import BaseProvider


class BaiwangYunProvider(BaseProvider):
    provider_id = "bwyun-cn"
    display_name = "百望云"
    provider_label = "商业厂商"
    deploy_mode = "API（SaaS）"

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_label": self.provider_label,
            "deploy_mode": self.deploy_mode,
            "invoice_types": ["数电票", "增值税专票/普票（纸质扫描）"],
            "regions": ["CN"],
            "formats": ["xml", "ofd", "pdf_scan", "image"],
            "services": ["recognize", "verify"],
            "sla": {
                "availability_pct": 99.95,
                "p95_latency_ms": 2100.0,
            },
            "lock": False,
            "compliance_note": "合同含「不留存、不训练」条款 ✓",
        }

    def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        hint = payload.get("doc_type_hint") or ""
        sha = payload.get("sha256") or "00000000"

        # SIM 置信度矩阵口径（纸质专票 0.82；数电票 0.97）
        if "数电" in hint:
            conf = 0.97
        elif "专票" in hint or "纸质" in hint or "普票" in hint:
            conf = 0.82
        else:
            conf = 0.85

        gross = round(1000 + int(sha[:6], 16) % 89000 + (int(sha[6:10], 16) % 100) / 100, 2)
        tax = round(gross * 0.13 / 1.13, 2)
        net = round(gross - tax, 2)
        inv_no = f"24312{sha[:15].upper()}"[:20]

        return {
            "fields": [
                {
                    "name": "total.gross_amount",
                    "value": gross,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [120, 310, 280, 335],
                    "raw_text": f"¥{gross:,.2f}",
                    "model_version": "bwyun-ocr v4.1.2",
                },
                {
                    "name": "total.net_amount",
                    "value": net,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [120, 280, 280, 305],
                    "raw_text": f"¥{net:,.2f}",
                    "model_version": "bwyun-ocr v4.1.2",
                },
                {
                    "name": "total.tax_amount",
                    "value": tax,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [120, 340, 280, 365],
                    "raw_text": f"¥{tax:,.2f}",
                    "model_version": "bwyun-ocr v4.1.2",
                },
                {
                    "name": "header.invoice_no",
                    "value": inv_no,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [80, 90, 260, 115],
                    "raw_text": inv_no,
                    "model_version": "bwyun-ocr v4.1.2",
                },
                {
                    "name": "seller.name",
                    "value": "北京测试科技有限公司",
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [80, 140, 280, 165],
                    "raw_text": "北京测试科技有限公司",
                    "model_version": "bwyun-ocr v4.1.2",
                },
            ],
            "meta": {
                "provider_id": self.provider_id,
                "latency_ms": 2100.0,
                "cost": {
                    "currency": "CNY",
                    "amount": 0.08,
                },
            },
        }

    def verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = payload.get("caseId") or "INV-CN-2026-0001"
        seq = case_id.split("-")[-1]
        rcpt_no = f"gm-rcpt-{seq.zfill(4)}"
        return {
            "result": "PASSED",
            "receipt": {
                "receipt_no": rcpt_no,
                "archived": True,
            },
            "note": "百望云税务授权查验通道验证通过（演示口径）",
        }
