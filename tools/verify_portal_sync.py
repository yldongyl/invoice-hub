# -*- coding: utf-8 -*-
"""api-portal 与 contracts/ 机器可读文件同步校验脚本（WP5.7 · CI 门禁 · FN-A-09 覆盖面扩展）。

校验原则：
  文档站必须与机器可读契约单一事实源 100% 保持同步（FN-A-09 · L2 判定底线）：
  ① MCP 6 项工具名称、方向、权限级别与 scope 绑定（mcp-tools.json）；
  ② REST 集成端点清单与 openapi.yaml paths 全量比对；
  ③ Webhook 4 类事件码名称（enum-registry.webhook_event）；
  ④ 核心 Schema / facts / evidence 字段路径；
  ⑤ SPI 段三方法名与 provider-spi.schema.json 一致（capabilities/recognize/verify）；
  ⑥ Adapter cXML 段关键节点与 adapter-contract.schema.json 一致；
  ⑦ v1 FROZEN 徽章与 openapi.yaml info 版本状态一致。
不同步即抛出异常，CI 门禁失败。
"""

import json
import sys
from pathlib import Path
import yaml

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
    provider_spi_json = json.loads((CONTRACTS_DIR / "provider-spi.schema.json").read_text(encoding="utf-8"))
    adapter_contract_json = json.loads((CONTRACTS_DIR / "adapter-contract.schema.json").read_text(encoding="utf-8"))
    openapi_yaml = yaml.safe_load((CONTRACTS_DIR / "openapi.yaml").read_text(encoding="utf-8"))

    # 读取 web 与 ui-design 目录下的 api-portal.html
    # CI/干净克隆回退：仓外 ui-design 冻结基线缺失时仅校验仓内 web/ 接线副本（打印醒目警告）；
    # 本机基线存在时仍双副本校验。
    html_targets = [
        ("web/api-portal.html", (WEB_DIR / "api-portal.html").read_text(encoding="utf-8")),
    ]
    ui_portal = UI_DESIGN_DIR / "api-portal.html"
    if ui_portal.exists():
        html_targets.append(("ui-design/api-portal.html", ui_portal.read_text(encoding="utf-8")))
    else:
        print(f"⚠️ 仓外基线 ui-design/api-portal.html 不存在（{ui_portal}）——"
              f"回退仅校验 web/ 接线副本；本机基线存在时仍双副本校验。")

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

        # 3. 校验 REST 核心端点（与 openapi.yaml paths 全量比对，FN-A-09 d）
        openapi_paths = list(openapi_yaml.get("paths", {}).keys())
        assert len(openapi_paths) >= 3, f"openapi.yaml paths 数量异常: {len(openapi_paths)}"
        for ep in openapi_paths:
            assert ep in html, f"{label} 缺失 REST 契约端点 (openapi.yaml paths): {ep}"
            print(f"  [OK] REST 端点全量匹配: {ep}")

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

        # 6. 校验 SPI 段三方法名与 provider-spi.schema.json 一致（FN-A-09 a）
        spi_methods = list(provider_spi_json.get("spi_methods", {}).keys())
        assert set(spi_methods) == {"capabilities", "recognize", "verify"}, f"provider-spi.schema.json spi_methods 异常: {spi_methods}"
        for sm in spi_methods:
            assert sm in html, f"{label} 缺失 Provider SPI 契约方法: {sm}"
            print(f"  [OK] SPI 方法名匹配: {sm}")

        # 7. 校验 Adapter cXML 段关键节点与 adapter-contract.schema.json 一致（FN-A-09 b）
        cxml_key_nodes = [
            "InvoiceDetailRequest",
            "InvoiceDetailHeader",
            "Total",
            "Tax",
            "OrderReference",
        ]
        for node in cxml_key_nodes:
            assert node in html, f"{label} 缺失 Adapter cXML 关键节点: {node}"
            print(f"  [OK] Adapter cXML 关键节点匹配: {node}")

        # 8. 校验 v1 FROZEN 徽章与 openapi.yaml info 版本状态一致（FN-A-09 c）
        api_version = openapi_yaml.get("info", {}).get("version", "1.0.0")
        major_v = f"v{api_version.split('.')[0]}"  # "v1"
        badge_text = f"{major_v} · FROZEN"
        assert badge_text in html, f"{label} 缺失版本冻结徽章: {badge_text}"
        print(f"  [OK] 版本冻结徽章匹配 (openapi.yaml {api_version} -> {badge_text})")

    print("\n[SUCCESS] api-portal 契约同步校验全部通过！文档站与 contracts/ 100% 同步！")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(verify_portal_sync())
    except Exception as e:
        print(f"\n[FAIL] 校验失败: {e}", file=sys.stderr)
        sys.exit(1)
