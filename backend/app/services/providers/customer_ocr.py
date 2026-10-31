# -*- coding: utf-8 -*-
"""客户自有 OCR Provider SPI Stub（FN-2-02/13 · 演示口径）。"""

from typing import Any
from app.services.providers.base import BaseProvider


class CustomerOcrProvider(BaseProvider):
    provider_id = "customer-ocr"
    display_name = "客户自有 OCR"
    provider_label = "客户已有"
    deploy_mode = "客户环境 API"

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_label": self.provider_label,
            "deploy_mode": self.deploy_mode,
            "invoice_types": ["增值税专票/普票（纸质扫描）", "Supplier Invoice"],
            "regions": ["CN", "APAC"],
            "formats": ["pdf_scan", "image"],
            "services": ["recognize"],
            "sla": {
                "availability_pct": 99.20,
                "p95_latency_ms": 8200.0,
            },
            "lock": False,
            "compliance_note": "接入走 Provider SPI 归一化契约",
        }

    def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        hint = payload.get("doc_type_hint") or ""
        sha = payload.get("sha256") or "00000000"

        # SIM 置信度矩阵口径（纸质专票 0.88）
        conf = 0.88

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
                    "bbox": [130, 315, 285, 340],
                    "raw_text": f"¥{gross:,.2f}",
                    "model_version": "customer-ocr v2.1",
                },
                {
                    "name": "total.net_amount",
                    "value": net,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [130, 285, 285, 310],
                    "raw_text": f"¥{net:,.2f}",
                    "model_version": "customer-ocr v2.1",
                },
                {
                    "name": "total.tax_amount",
                    "value": tax,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [130, 345, 285, 370],
                    "raw_text": f"¥{tax:,.2f}",
                    "model_version": "customer-ocr v2.1",
                },
                {
                    "name": "header.invoice_no",
                    "value": inv_no,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [85, 95, 265, 120],
                    "raw_text": inv_no,
                    "model_version": "customer-ocr v2.1",
                },
            ],
            "meta": {
                "provider_id": self.provider_id,
                "latency_ms": 8200.0,
                "cost": {
                    "currency": "CNY",
                    "amount": 0.0,
                },
            },
        }
