# -*- coding: utf-8 -*-
"""海外 e-invoicing（新加坡）Provider SPI Stub（FN-2-02/13 · 演示口径）。"""

from typing import Any
from app.services.providers.base import BaseProvider


class OverseasEInvoicingProvider(BaseProvider):
    provider_id = "overseas-einv-sg"
    display_name = "海外 e-invoicing（新加坡）"
    provider_label = "商业厂商"
    deploy_mode = "API（SaaS）"

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_label": self.provider_label,
            "deploy_mode": self.deploy_mode,
            "invoice_types": ["Supplier Invoice", "Credit Note", "Debit Note"],
            "regions": ["APAC", "EU"],
            "formats": ["xml", "pdf_text", "pdf_scan", "image", "peppol_ubl"],
            "services": ["recognize", "verify"],
            "sla": {
                "availability_pct": 99.85,
                "p95_latency_ms": 1900.0,
            },
            "lock": False,
            "compliance_note": "覆盖 Peppol / UBL / GST 校验",
        }

    def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        hint = payload.get("doc_type_hint") or ""
        sha = payload.get("sha256") or "00000000"

        # SIM 置信度矩阵口径（Supplier Invoice 0.93；Credit Note 0.78）
        if "Credit Note" in hint or "贷记" in hint:
            conf = 0.78
        elif "Supplier Invoice" in hint or "海外" in hint:
            conf = 0.93
        else:
            conf = 0.90

        gross = round(1000 + int(sha[:6], 16) % 89000 + (int(sha[6:10], 16) % 100) / 100, 2)
        tax = round(gross * 0.09 / 1.09, 2)   # SG GST 9%
        net = round(gross - tax, 2)
        inv_no = f"SG-INV-{sha[:8].upper()}"

        return {
            "fields": [
                {
                    "name": "total.gross_amount",
                    "value": gross,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [115, 305, 275, 330],
                    "raw_text": f"S${gross:,.2f}",
                    "model_version": "overseas-einv v2.0",
                },
                {
                    "name": "total.net_amount",
                    "value": net,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [115, 275, 275, 300],
                    "raw_text": f"S${net:,.2f}",
                    "model_version": "overseas-einv v2.0",
                },
                {
                    "name": "total.tax_amount",
                    "value": tax,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [115, 335, 275, 360],
                    "raw_text": f"S${tax:,.2f}",
                    "model_version": "overseas-einv v2.0",
                },
                {
                    "name": "header.invoice_no",
                    "value": inv_no,
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [78, 88, 258, 112],
                    "raw_text": inv_no,
                    "model_version": "overseas-einv v2.0",
                },
                {
                    "name": "seller.uen",
                    "value": "201912345K",
                    "confidence": conf,
                    "source": "ocr",
                    "bbox": [78, 138, 258, 162],
                    "raw_text": "UEN: 201912345K",
                    "model_version": "overseas-einv v2.0",
                },
            ],
            "meta": {
                "provider_id": self.provider_id,
                "latency_ms": 1900.0,
                "cost": {
                    "currency": "SGD",
                    "amount": 0.05,
                },
            },
        }

    def verify(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = payload.get("caseId") or "INV-SG-2026-0001"
        seq = case_id.split("-")[-1]
        rcpt_no = f"gm-rcpt-{seq.zfill(4)}"
        return {
            "result": "PASSED",
            "receipt": {
                "receipt_no": rcpt_no,
                "archived": True,
            },
            "note": "新加坡 IRAS / Peppol 名录验证通过（演示口径）",
        }
