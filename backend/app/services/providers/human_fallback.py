# -*- coding: utf-8 -*-
"""人工兜底 Provider SPI Stub（FN-2-02/03/13 · 平台内置）。"""

from typing import Any
from app.services.providers.base import BaseProvider


class HumanFallbackProvider(BaseProvider):
    provider_id = "human-fallback"
    display_name = "人工兜底"
    provider_label = "平台内置"
    deploy_mode = "平台复核工作台"

    def capabilities(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_label": self.provider_label,
            "deploy_mode": self.deploy_mode,
            "invoice_types": ["数电票", "增值税专票/普票（纸质扫描）", "Supplier Invoice", "Credit Note", "Debit Note"],
            "regions": ["CN", "APAC", "EU", "US"],
            "formats": ["xml", "ofd", "pdf_text", "pdf_scan", "image", "peppol_ubl"],
            "services": ["recognize"],
            "sla": {
                "availability_pct": 100.0,
                "p95_latency_ms": 0.0,
            },
            "lock": True,
            "compliance_note": "所有降级链路的最终兜底，不可停用",
        }

    def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        sha = payload.get("sha256") or "00000000"
        gross = round(1000 + int(sha[:6], 16) % 89000 + (int(sha[6:10], 16) % 100) / 100, 2)
        inv_no = f"MAN-{sha[:8].upper()}"

        return {
            "fields": [
                {
                    "name": "total.gross_amount",
                    "value": gross,
                    "confidence": 1.0,
                    "source": "manual",
                    "bbox": None,
                    "raw_text": f"¥{gross:,.2f}",
                    "model_version": "human-reviewer",
                },
                {
                    "name": "header.invoice_no",
                    "value": inv_no,
                    "confidence": 1.0,
                    "source": "manual",
                    "bbox": None,
                    "raw_text": inv_no,
                    "model_version": "human-reviewer",
                },
            ],
            "meta": {
                "provider_id": self.provider_id,
                "latency_ms": 0.0,
                "cost": {
                    "currency": "CNY",
                    "amount": 0.0,
                },
            },
        }
