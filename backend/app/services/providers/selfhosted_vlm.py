# -*- coding: utf-8 -*-
"""自托管 OCR-VLM Provider SPI Stub（FN-2-02/13 · 演示口径）。"""

from typing import Any
from app.services.providers.base import BaseProvider


class SelfhostedVlmProvider(BaseProvider):
    provider_id = "selfhosted-ocr-vlm"
    display_name = "自托管 OCR-VLM"
    provider_label = "私有化"
    deploy_mode = "私有化自托管（GPU）"

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_label": self.provider_label,
            "deploy_mode": self.deploy_mode,
            "invoice_types": ["增值税专票/普票（纸质扫描）", "Supplier Invoice", "Credit Note"],
            "regions": ["CN", "APAC"],
            "formats": ["pdf_scan", "image"],
            "services": ["recognize"],
            "sla": {
                "availability_pct": 99.80,
                "p95_latency_ms": 3400.0,
            },
            "lock": False,
            "compliance_note": "数据不出客户控制域 · 输出仅作证据源，非天然可信",
        }

    def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        hint = payload.get("doc_type_hint") or ""
        sha = payload.get("sha256") or "00000000"

        # SIM 置信度矩阵口径（Supplier Invoice 0.90；Credit Note 0.74；纸质专票 0.85）
        if "Credit Note" in hint or "贷记" in hint:
            conf = 0.74
        elif "Supplier Invoice" in hint or "海外" in hint:
            conf = 0.90
        else:
            conf = 0.85

        gross = round(1000 + int(sha[:6], 16) % 89000 + (int(sha[6:10], 16) % 100) / 100, 2)
        inv_no = f"INV-{sha[:10].upper()}"

        return {
            "fields": [
                {
                    "name": "total.gross_amount",
                    "value": gross,
                    "confidence": conf,
                    "source": "model",  # vlm -> model
                    "bbox": [110, 300, 270, 325],
                    "raw_text": f"{gross:,.2f}",
                    "model_version": "ocr-vlm-2026-10",
                },
                {
                    "name": "header.invoice_no",
                    "value": inv_no,
                    "confidence": conf,
                    "source": "model",
                    "bbox": [75, 85, 255, 110],
                    "raw_text": inv_no,
                    "model_version": "ocr-vlm-2026-10",
                },
            ],
            "meta": {
                "provider_id": self.provider_id,
                "latency_ms": 3400.0,
                "cost": {
                    "currency": "CNY",
                    "amount": 0.02,
                },
            },
        }
