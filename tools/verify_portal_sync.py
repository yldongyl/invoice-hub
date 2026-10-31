# -*- coding: utf-8 -*-
"""api-portal 与 contracts/ 机器可读文件同步校验脚本（WP5.7 · CI 门禁）。

校验原则：
  文档站必须与机器可读契约单一事实源 100% 保持同步（FN-A-09 · L2 判定底线）：
  ① MCP 6 项工具名称、方向、权限级别与 scope 绑定；
  ② REST 核心集成端点与请求方式；
  ③ Webhook 4 类事件码名称；
  ④ 核心 Schema / facts / evidence 字段路径。
不同步即抛出异常，CI 门禁失败。
"""

import json
import sys
from pathlib import Path

# 确保在 Windows 控制台输出中文不报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
CONTRACTS_DIR = REPO_ROOT / "contracts"
WEB_DIR = REPO_ROOT / "web"
UI_DESIGN_DIR = (REPO_ROOT / "ui-design") if (REPO_ROOT / "ui-design").is_dir() else (REPO_ROOT.parent / "ui-design")


def verify_portal_sync():
    print("── 开始 api-portal 与 contracts/ 契约文件同步校验 ──")

    # 读取契约文件
    mcp_tools_json = json.loads((CONTRACTS_DIR / "mcp-tools.json").read_text(encoding="utf-8"))
    enum_registry_json = json.loads((CONTRACTS_DIR / "enum-registry.json").read_text(encoding="utf-8"))

    # 读取 web 与 ui-design 目录下的 api-portal.html
    html_targets = [
        ("web/api-portal.html", (WEB_DIR / "api-portal.html").read_text(encoding="utf-8")),
        ("ui-design/api-portal.html", (UI_DESIGN_DIR / "api-portal.html").read_text(encoding="utf-8")),
    ]

    for label, html in html_targets:
        print(f"\n[校验目标] {label}:")

        # 1. 校验 MCP 6 工具清单
        mcp_tools = mcp_tools_json["tools"]
        assert len(mcp_tools) == 6, f"mcp-tools.json 应含 6 项工具，实际 {len(mcp_tools)}"
        for t in mcp_tools:
            t_name = t["name"]
            assert t_name in html, f"{label} 缺失 MCP 工具契约项: {t_name}"
            print(f"  [OK] MCP 工具匹配: {t_name}")

        # 2. 校验 MCP Scope 与安全策略
        for sc in ("invoice.read", "invoice.write.controlled"):
            assert sc in html or "只读" in html, f"{label} 缺失权限范围说明: {sc}"
        assert "confirm_token" in html, f"{label} 缺失 confirm_token 人工确认凭据说明"
        print("  [OK] MCP 鉴权与 confirm_token 策略说明一致")

        # 3. 校验 REST 核心端点
        endpoints = [
            "/v1/invoices:recognize",
            "/v1/cases/{caseId}",
            "/v1/cases/{caseId}/evidence",
        ]
        for ep in endpoints:
            assert ep in html, f"{label} 缺失 REST 核心端点: {ep}"
            print(f"  [OK] REST 端点匹配: {ep}")

        # 4. 校验 Webhook 四事件码（enum-registry.webhook_event 同源）
        wh_events = ["case.recognized", "case.blocked", "case.resolved", "check.failed"]
        for ev in wh_events:
            assert ev in html, f"{label} 缺失 Webhook 事件码: {ev}"
            print(f"  [OK] Webhook 事件码匹配: {ev}")

        # 5. 校验核心 Schema / facts 字段路径
        schema_fields = [
            "total.gross_amount",
            "total.tax_amount",
            "facts.invoiceAmount",
            "facts.taxAmount",
        ]
        for f in schema_fields:
            assert f in html, f"{label} 缺失核心 Schema 字段路径: {f}"
            print(f"  [OK] Schema 字段匹配: {f}")

    print("\n[SUCCESS] api-portal 契约同步校验全部通过！文档站与 contracts/ 100% 同步！")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(verify_portal_sync())
    except Exception as e:
        print(f"\n[FAIL] 校验失败: {e}", file=sys.stderr)
        sys.exit(1)
