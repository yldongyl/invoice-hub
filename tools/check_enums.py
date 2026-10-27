#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enum-registry.json ↔ Excel Sheet08《枚举字典》逐行一致性校验（M0 验收①，后续收工检查单复用）。

比对口径（docs/adr 与 enum-registry 头部 notes 声明）：
  - 每个 values 条目的 code / label / color_raw / note 四字段，与 Sheet08 的
    「值 / 代码」「标签 / 含义」「颜色 / 级别」「备注」四列逐字一致；
  - 类别顺序与条目顺序均须一致（逐行对齐，不是集合比对）；
  - Sheet08 共 142 行数据（第 5–146 行；v1.1.0 增补 link_type 5 行；v1.2.0 增补受理域 5 类 22 行），注册表 categories 须为 25 类、合计 142 值；
  - color（语义 token）、pattern、actor、access、machine、min/max、enabled_default、level 等
    为注册表附加的机器可读字段，不参与逐字比对。

用法：python tools/check_enums.py [--excel <xlsx路径>]
退出码：0 通过；1 不一致（stdout 输出差异清单）。
"""

import argparse
import json
import os
import sys

# Windows 控制台 UTF-8 兜底
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_EXCEL = os.path.join(
    REPO_ROOT, os.pardir, "细化功能清单",
    "采购平台票据智能与合规中台-细化功能清单.xlsx",
)
REGISTRY = os.path.join(REPO_ROOT, "contracts", "enum-registry.json")

# Sheet08「类别」列（原文）→ 注册表 category key
CATEGORY_MAP = {
    "案件状态 status": "case_status",
    "状态流转": "state_transition",
    "字段来源 source": "field_source",
    "Checks 结果": "check_result",
    "四校验项 checks": "check_item",
    "置信度分档": "confidence_band",
    "时间线主体 actor": "timeline_actor",
    "事件码 act": "timeline_event",
    "差异类型徽章": "diff_type",
    "风险标签 risk": "risk_label",
    "批次进度状态": "batch_status",
    "Adapter 状态": "adapter_status",
    "标注任务状态": "anno_status",
    "告警级别": "alert_level",
    "兜底触发条件": "fallback_trigger",
    "MCP 工具": "mcp_tool",
    "Webhook 事件": "webhook_event",
    "映射来源三分类": "mapping_source",
    "编号规则": "id_format",
    "Link 类型": "link_type",
    # ── v1.2.0 M3 受理域增补（顺序必须与 registry categories 追加顺序一致）──
    "接入渠道 channel": "intake_channel",
    "载体分流路径": "carrier_route",
    "流水线步骤态": "pipeline_step_status",
    "文件受理处置": "intake_file_disposition",
    "非发票文档类型": "non_invoice_doc_type",
}

DATA_START_ROW = 5  # 第 1–2 行说明、第 3 行空、第 4 行表头
EXPECTED_TOTAL = 142


def norm(v):
    """单元格规范化：None→空串，去首尾空白，内部换行折叠为 ⏎ 显示差异用。"""
    return ("" if v is None else str(v)).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--excel", default=os.path.normpath(DEFAULT_EXCEL))
    args = ap.parse_args()

    import openpyxl  # 延迟导入：仅校验收工检查单运行时需要

    with open(REGISTRY, encoding="utf-8") as f:
        reg = json.load(f)
    wb = openpyxl.load_workbook(args.excel, read_only=True, data_only=True)
    ws = wb["08-枚举字典"]

    diffs = []
    by_cat = {}          # category key -> [ {code,label,color_raw,note} ... ]（注册表顺序）
    for key, cdef in reg["categories"].items():
        by_cat[key] = list(cdef["values"])

    seen_order = []      # Sheet08 类别首次出现顺序
    idx = {}             # category key -> 已消费行数
    total = 0
    for row in ws.iter_rows(min_row=DATA_START_ROW, max_col=5, values_only=True):
        cat_raw = norm(row[0])
        if not cat_raw:
            continue
        key = CATEGORY_MAP.get(cat_raw)
        if key is None:
            diffs.append(f"未知类别（Sheet08 出现但 CATEGORY_MAP 无映射）：{cat_raw!r}")
            continue
        idx.setdefault(key, 0)
        if key not in seen_order:
            seen_order.append(key)
        expect = by_cat.get(key)
        if expect is None:
            diffs.append(f"注册表缺少类别 {key}（Sheet08 类别 {cat_raw!r}）")
            continue
        i = idx[key]
        if i >= len(expect):
            diffs.append(f"[{key}] Sheet08 第 {total + DATA_START_ROW - 1} 行多出行（注册表仅 {len(expect)} 值）：{row!r}")
            total += 1
            continue
        e = expect[i]
        got = {
            "code": norm(row[1]),
            "label": norm(row[2]),
            "color_raw": norm(row[3]),
            "note": norm(row[4]),
        }
        for field in ("code", "label", "color_raw", "note"):
            if got[field] != norm(e.get(field, "")):
                diffs.append(
                    f"[{key}] 第 {i + 1} 值 {e['code']!r} 字段 {field} 不一致："
                    f"Sheet08={got[field]!r} vs registry={norm(e.get(field, ''))!r}"
                )
        idx[key] = i + 1
        total += 1

    # 注册表有而 Sheet08 缺
    for key, vals in by_cat.items():
        if idx.get(key, 0) < len(vals):
            for extra in vals[idx.get(key, 0):]:
                diffs.append(f"[{key}] 注册表多出值（Sheet08 无此行）：{extra['code']!r}")

    # 类别顺序
    sheet_cats_in_order = seen_order
    reg_cats_in_order = list(reg["categories"].keys())
    if sheet_cats_in_order != reg_cats_in_order:
        diffs.append(
            f"类别顺序不一致：Sheet08={sheet_cats_in_order} vs registry={reg_cats_in_order}"
        )

    # 总量与类别数
    if total != EXPECTED_TOTAL:
        diffs.append(f"Sheet08 数据行总数应为 {EXPECTED_TOTAL}，实际 {total}")
    reg_total = sum(len(v["values"]) for v in reg["categories"].values())
    if reg_total != EXPECTED_TOTAL:
        diffs.append(f"registry 值总数应为 {EXPECTED_TOTAL}，实际 {reg_total}")
    if len(reg["categories"]) != len(CATEGORY_MAP):
        diffs.append(f"registry 类别数应为 {len(CATEGORY_MAP)}，实际 {len(reg['categories'])}")

    print(f"enum-registry v{reg['version']}  类别 {len(reg['categories'])} / 值 {reg_total}")
    print(f"Sheet08 数据行 {total}（第 {DATA_START_ROW} 行起）")
    if diffs:
        print(f"\n❌ 不一致 {len(diffs)} 处：")
        for d in diffs:
            print("  -", d)
        sys.exit(1)
    print(f"✅ check_enums 通过：enum-registry 与 Sheet08 全 {EXPECTED_TOTAL} 行逐行逐字一致")


if __name__ == "__main__":
    main()
