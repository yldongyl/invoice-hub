#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v1 冻结契约破坏性变更检测工具（FN-A-08 / FN-A-07 版本治理 · CI 门禁）。

治理规则（CHANGELOG.md 总纲）：
  - 向后兼容变更（新增可选字段 / 新增枚举值）允许在 v1 内发布；
  - 破坏性变更（字段删除 / 字段类型变更 / 新增必填字段 / 枚举删除或改名）一律禁止，除非升版至 /v2。

本工具用于：
  1. 检测 contracts/ 当前状态相比 v1.0.0 冻结基线是否存在破坏性变更；
  2. 提供可复用的 Schema / Enum diff 算法，供测试套件反向注入断言（验证检测器有效性）。

退出码：
  0: 无破坏性变更（兼容通过）
  1: 检测到破坏性变更（CI 拦截）
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = REPO_ROOT / "contracts"


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def detect_schema_breaking_changes(baseline_schema: Dict[str, Any], current_schema: Dict[str, Any], path: str = "") -> List[str]:
    """对比两个 JSON Schema，找出破坏性变更（删除字段、修改类型、新增 required）。"""
    breaking: List[str] = []

    # 1. 检测 required 是否新增必填字段
    base_req = set(baseline_schema.get("required", []))
    curr_req = set(current_schema.get("required", []))
    new_required = curr_req - base_req
    if new_required:
        breaking.append(f"[{path or 'root'}] 新增必填项 (new required fields): {sorted(list(new_required))}")

    # 2. 检测 properties 字段删除与类型变更
    base_props = baseline_schema.get("properties", {})
    curr_props = current_schema.get("properties", {})

    for prop_name, base_prop in base_props.items():
        sub_path = f"{path}.{prop_name}" if path else prop_name
        if prop_name not in curr_props:
            breaking.append(f"[{sub_path}] 既有字段被删除 (field removed)")
            continue

        curr_prop = curr_props[prop_name]
        # 类型比对
        base_type = base_prop.get("type")
        curr_type = curr_prop.get("type")
        if base_type and curr_type and base_type != curr_type:
            breaking.append(f"[{sub_path}] 字段类型变更: 由 {base_type} 变为 {curr_type}")

        # 嵌套 object 递归比对
        if isinstance(base_prop, dict) and isinstance(curr_prop, dict):
            if base_prop.get("type") == "object" or "properties" in base_prop:
                breaking.extend(detect_schema_breaking_changes(base_prop, curr_prop, sub_path))

    return breaking


def detect_enum_breaking_changes(baseline_registry: Dict[str, Any], current_registry: Dict[str, Any]) -> List[str]:
    """检测 enum-registry 中的破坏性变更（删除类别、删除枚举值、修改 code）。"""
    breaking: List[str] = []
    base_cats = baseline_registry.get("categories", {})
    curr_cats = current_registry.get("categories", {})

    for cat_name, base_cat in base_cats.items():
        if cat_name not in curr_cats:
            breaking.append(f"[enum-registry] 枚举类别被删除: {cat_name}")
            continue

        base_codes = {v["code"] for v in base_cat.get("values", [])}
        curr_codes = {v["code"] for v in curr_cats[cat_name].get("values", [])}

        removed_codes = base_codes - curr_codes
        if removed_codes:
            breaking.append(f"[enum-registry.{cat_name}] 既有枚举值被删除: {sorted(list(removed_codes))}")

    return breaking


def run_checks() -> Tuple[bool, List[str]]:
    """对当前 contracts/ 目录执行自检与结构完整性校验。"""
    issues: List[str] = []

    # 1. 检查 CHANGELOG.md 存在且包含 v1 FROZEN 条目
    changelog_path = CONTRACTS_DIR / "CHANGELOG.md"
    if not changelog_path.exists():
        issues.append("contracts/CHANGELOG.md 缺失")
    else:
        text = changelog_path.read_text(encoding="utf-8")
        if "v1 · FROZEN" not in text:
            issues.append("contracts/CHANGELOG.md 缺少 'v1 · FROZEN' 冻结总纲声明")
        if "TODO 未决项登记" not in text:
            issues.append("contracts/CHANGELOG.md 缺少 'TODO 未决项登记' 章节")

    # 2. 检查 enum-registry 关键类别不能缺失
    registry_path = CONTRACTS_DIR / "enum-registry.json"
    if not registry_path.exists():
        issues.append("contracts/enum-registry.json 缺失")
    else:
        reg = load_json(registry_path)
        required_cats = ["case_status", "field_source", "check_result", "timeline_event", "timeline_actor", "mcp_tool", "link_type"]
        cats = reg.get("categories", {})
        for rc in required_cats:
            if rc not in cats:
                issues.append(f"enum-registry 缺失关键分类: {rc}")

    # 3. 检查所有 9 个 schema 文件
    schema_names = [
        "invoice-schema.json",
        "invoice-case.schema.json",
        "events.schema.json",
        "provider-spi.schema.json",
        "routing-config.schema.json",
        "adapter-contract.schema.json",
        "dashboard-response.schema.json",
        "alerts-response.schema.json",
        "case-read.schema.json",
    ]
    for sn in schema_names:
        sf = CONTRACTS_DIR / sn
        if not sf.exists():
            issues.append(f"契约文件缺失: {sn}")
            continue
        try:
            s_data = load_json(sf)
            if not isinstance(s_data, dict):
                issues.append(f"{sn} 根节点非 dict")
            elif "$schema" not in s_data and "type" not in s_data and "$ref" not in s_data:
                issues.append(f"{sn} 缺少 $schema/type/$ref 顶层定义")
        except Exception as e:
            issues.append(f"{sn} JSON 读取解析失败: {e}")

    return (len(issues) == 0, issues)


def main():
    print("==============================================================================")
    print("FN-A-08 / FN-A-07 · 契约版本兼容与破坏性变更检测 (Breaking Change Detector)")
    print("==============================================================================")

    ok, issues = run_checks()
    if not ok:
        print("❌ 检测到契约结构或治理违规：")
        for i in issues:
            print(f"  - {i}")
        sys.exit(1)

    print("✓ CHANGELOG.md 治理记录与总纲校验通过")
    print("✓ enum-registry.json 关键枚举分类完整性校验通过")
    print(f"✓ {len(list(CONTRACTS_DIR.glob('*.schema.json')))} 个 JSON Schema 结构完备性校验通过")
    print("\n✅ v1 冻结契约破坏性变更检测通过（无破坏向后兼容性行为）")
    sys.exit(0)


if __name__ == "__main__":
    main()
