#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M0 契约与种子自检（P01 WP0.8；后续收工检查单复用）。

检查项：
  A. 全部 JSON Schema 可编译（Draft 2020-12 Validator.check_schema）；
  B. openapi.yaml 可 lint（优先 openapi-spec-validator；未安装则结构化 lint：
     必填段/operationId 唯一/$ref 可解析/响应结构）；
  C. seeds 逐一过对应 Schema（cases→invoice-case；routing_policy→routing-config）；
  D. 编号/枚举一致性断言（对照 contracts/enum-registry.json）：
     案件号/批次号/trace/回执号/SUP/租户 pattern；inline enum ↔ registry；
     MCP 工具名/级别、Webhook 事件名、timeline act/actor 与注册表一致；
     cases 的 status/source/check_result ∈ 注册表；三演示案件（0387/0379/0125）
     为 detail_level=full 且通过 invoice-case.schema 校验；
  E. 交叉一致性：seeds 间 caseId 集合、providers/routing 引用 provider_id 对齐。

退出码：0 全绿；1 任一失败（输出逐项差异）。
"""

import json
import os
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTRACTS = os.path.join(ROOT, "contracts")
SEEDS = os.path.join(ROOT, "seeds")

FAILS = []
PASSES = []

def ok(msg): PASSES.append(msg); print("  ✓", msg)
def fail(msg): FAILS.append(msg); print("  ✗", msg)

def jload(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError as e:
    print("缺少依赖：jsonschema/referencing 未安装（", e, "）"); sys.exit(2)

REG = jload(os.path.join(CONTRACTS, "enum-registry.json"))
CATS = REG["categories"]

def codes_of(cat): return [v["code"] for v in CATS[cat]["values"]]

# ── A. Schema 编译 + 资源注册（相对 $ref → file URI）────────────────
from urllib.parse import quote
def to_file_uri(name):
    p = os.path.join(CONTRACTS, name).replace("\\", "/").lstrip("/")
    return "file:///" + quote(p, safe="/:")  # 路径含空格需 percent-encode，否则非合法 uri-reference

def absolutize_refs(schema, seen=None):
    """把 "$ref": "xxx.json"（同目录相对引用）改写为 file URI，便于 referencing 解析。"""
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k == "$ref" and isinstance(v, str) and re.fullmatch(r"[\w.-]+\.json", v):
                out[k] = to_file_uri(v)
            else:
                out[k] = absolutize_refs(v)
        return out
    if isinstance(schema, list):
        return [absolutize_refs(x) for x in schema]
    return schema

SCHEMA_FILES = ["invoice-schema.json", "invoice-case.schema.json", "events.schema.json",
                "provider-spi.schema.json", "routing-config.schema.json", "adapter-contract.schema.json"]
registry_entries = []
schemas = {}
print("A. JSON Schema 编译")
for name in SCHEMA_FILES:
    try:
        s = absolutize_refs(jload(os.path.join(CONTRACTS, name)))
        Draft202012Validator.check_schema(s)
        schemas[name] = s
        registry_entries.append((to_file_uri(name), s))
        ok(f"{name} 可编译（Draft 2020-12）")
    except Exception as e:
        fail(f"{name} 编译失败：{e}")

try:
    REGISTRY = Registry().with_resources([(uri, Resource.from_contents(s)) for uri, s in registry_entries])
except Exception as e:
    fail(f"引用注册表构建失败：{e}")
    REGISTRY = Registry()

# ── B. openapi lint ────────────────────────────────────────────────
print("B. openapi.yaml lint")
OAS = None
try:
    import yaml
    with open(os.path.join(CONTRACTS, "openapi.yaml"), encoding="utf-8") as f:
        OAS = yaml.safe_load(f)
except Exception as e:
    fail(f"openapi.yaml 解析失败：{e}")

if OAS is not None:
    try:
        from openapi_spec_validator import validate  # 若环境可用则做完整 lint
        # base_uri 使外部 $ref（invoice-case.schema.json 等，契约单一事实源）可被解析
        validate(OAS, base_uri=pathlib.Path(CONTRACTS).resolve().as_uri() + "/")
        ok("openapi-spec-validator 全量 lint 通过（含外部 $ref 解析）")
    except ImportError:
        # 结构化 lint（离线兜底）
        errs = []
        for key in ("openapi", "info", "paths"):
            if key not in OAS: errs.append(f"缺少顶层段 {key}")
        opids = []
        def walk_ref(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k == "$ref" and isinstance(v, str) and not v.startswith("#") and not v.startswith("file:"):
                        pass  # 外部文件引用（invoice-case.schema.json）存在性单独查
                    yield from ()
            # 简化：收集 $ref
        refs = re.findall(r'"?\$ref"?\s*[:=]\s*[\'"]?([^\'"\n]+)', json.dumps(OAS, ensure_ascii=False))
        for r in refs:
            if r.startswith("#/"):
                cur = OAS
                for seg in r[2:].split("/"):
                    seg = seg.replace("~1", "/").replace("~0", "~")
                    if isinstance(cur, dict) and seg in cur: cur = cur[seg]
                    else: errs.append(f"内部 $ref 不可解析: {r}"); break
            elif r.endswith(".json"):
                if not os.path.exists(os.path.join(CONTRACTS, r)): errs.append(f"外部 $ref 文件缺失: {r}")
        for p, item in (OAS.get("paths") or {}).items():
            for m in (item or {}):
                if m in ("get", "post", "put", "delete", "patch"):
                    op = item[m]
                    if isinstance(op, dict):
                        if "operationId" in op: opids.append(op["operationId"])
                        if "responses" not in op: errs.append(f"{m} {p} 缺 responses")
        dup = [x for x in opids if opids.count(x) > 1]
        if dup: errs.append(f"operationId 重复：{set(dup)}")
        if "webhooks" not in OAS: errs.append("缺少 webhooks 段（FN-A-03 四事件）")
        if errs:
            for e in errs: fail("openapi lint：" + e)
        else:
            ok("openapi 结构化 lint 通过（内部/外部 $ref 可解析、operationId 唯一、paths+webhooks 齐备）")
    except Exception as e:
        fail(f"openapi lint 异常：{e}")

# ── C. seeds 过 Schema ─────────────────────────────────────────────
print("C. seeds Schema 校验")

def validate_inst(schema, inst, label):
    errs = sorted(Draft202012Validator(schema, registry=REGISTRY).iter_errors(inst), key=lambda e: list(e.path))
    if errs:
        for e in errs[:6]:
            fail(f"{label}: {'/'.join(map(str,e.path))}: {e.message[:200]}")
        return False
    return True

cases_doc = jload(os.path.join(SEEDS, "cases.json"))
if "invoice-case.schema.json" not in schemas:
    fail("C 段跳过：invoice-case.schema 编译未通过，不作校验（禁止空 Schema 掩盖）")
else:
    all_ok = True
    for c in cases_doc["cases"]:
        if not validate_inst(schemas["invoice-case.schema.json"], c, f"case {c.get('caseId')}"):
            all_ok = False
    if all_ok: ok(f"cases.json：{len(cases_doc['cases'])} 案全部通过 invoice-case.schema 校验")

demo_full = [c["caseId"] for c in cases_doc["cases"] if c.get("detail_level") == "full"]
if sorted(demo_full) == sorted(["INV-CN-2026-0387", "INV-CN-2026-0379", "INV-SG-2026-0125"]):
    ok("三演示案件（0387/0379/0125）为 detail_level=full 且通过 Schema（自检基准达成）")
else:
    fail(f"三演示案件 full 校验异常：{demo_full}")

rp = jload(os.path.join(SEEDS, "routing_policy.json"))
if "routing-config.schema.json" in schemas and validate_inst(schemas["routing-config.schema.json"], rp, "routing_policy"):
    ok("routing_policy.json 通过 routing-config.schema 校验")

# ── D. 编号 / 枚举一致性 ───────────────────────────────────────────
print("D. 编号与枚举一致性（对照 enum-registry）")

pat = {k: v.get("pattern") for v in CATS["id_format"]["values"] for k in [v["code"]]}
P_CASE = pat["案件号"]; P_BATCH = pat["批次号"]; P_TRACE = pat["trace ID"]; P_RCPT = pat["验签回执"]
P_SUP = pat["供应商主数据"]

def check_pat(kind, rx, values):
    bad = [v for v in values if v and not re.fullmatch(rx, v)]
    (ok if not bad else fail)(f"{kind} 全部匹配 {rx}" + (f" · 违例 {bad[:5]}" if bad else "") + f"（{len([v for v in values if v])} 值）")

case_ids = [c["caseId"] for c in cases_doc["cases"]]
check_pat("案件号(caseId)", P_CASE, case_ids + [l["case"] for b in jload(os.path.join(SEEDS,"batches.json"))["batches"] for l in b["detail"] if l.get("case")]
          + [e.get("caseId") for e in jload(os.path.join(SEEDS,"audit_events.json"))["events"]])
check_pat("批次号", P_BATCH, [b["id"] for b in jload(os.path.join(SEEDS, "batches.json"))["batches"]])
check_pat("trace ID", P_TRACE, [e["trace"] for e in jload(os.path.join(SEEDS, "audit_events.json"))["events"]]
          + [c["meta"].get("trace_id") for c in cases_doc["cases"]])
check_pat("验签回执", P_RCPT, [c["meta"]["sm2"]["receipt_no"] for c in cases_doc["cases"]
          if isinstance(c["meta"].get("sm2"), dict) and c["meta"]["sm2"].get("receipt_no")])
check_pat("供应商主数据", P_SUP, [c["meta"].get("supplier_id") for c in cases_doc["cases"]])

STATUS_SET = set(codes_of("case_status")); SRC_SET = set(codes_of("field_source"))
RES_SET = set(codes_of("check_result")); ACT_SET = set(codes_of("timeline_event")); A_SET = set(codes_of("timeline_actor"))

st_bad = [c["caseId"] for c in cases_doc["cases"] if c["status"] not in STATUS_SET]
(ok if not st_bad else fail)("案件 status ∈ case_status 六态" + (f" · 违例 {st_bad}" if st_bad else ""))
src_bad = [(c["caseId"], e["source"]) for c in cases_doc["cases"] for e in c.get("evidence", []) if e["source"] not in SRC_SET]
(ok if not src_bad else fail)("字段来源 source ∈ 六枚举" + (f" · 违例 {src_bad[:3]}" if src_bad else ""))
res_bad = [(c["caseId"], k, v["result"]) for c in cases_doc["cases"] for k, v in (c.get("checks") or {}).items() if v["result"] not in RES_SET]
(ok if not res_bad else fail)("Checks 结果 ∈ 四结果" + (f" · 违例 {res_bad[:3]}" if res_bad else ""))
tl_bad = [(c["caseId"], ev["act"], ev["a"]) for c in cases_doc["cases"] for ev in c.get("timeline", [])
          if ev["act"] not in ACT_SET or ev["a"] not in A_SET]
(ok if not tl_bad else fail)("时间线 act/a ∈ timeline_event(29)/timeline_actor(4)" + (f" · 违例 {tl_bad[:3]}" if tl_bad else ""))

# inline enum ↔ registry
def same_enum(vals, cat, label, subset_ok=False):
    reg = set(codes_of(cat)); v = set(vals)
    good = (v <= reg if subset_ok else v == reg)
    (ok if good else fail)(f"{label} inline enum 与 enum-registry.{cat} {'子集一致' if subset_ok else '一致'}" + ("" if good else f" · 差集 {sorted(v ^ reg)}"))
same_enum(schemas["invoice-case.schema.json"]["properties"]["status"]["enum"], "case_status", "invoice-case.status")
same_enum(schemas["events.schema.json"]["properties"]["act"]["enum"], "timeline_event", "events.act")
same_enum(schemas["events.schema.json"]["properties"]["a"]["enum"], "timeline_actor", "events.a")
same_enum(schemas["invoice-case.schema.json"]["$defs"]["checkResult"]["properties"]["result"]["enum"], "check_result", "checkResult.result")
same_enum(schemas["invoice-case.schema.json"]["$defs"]["evidenceEntry"]["properties"]["source"]["enum"], "field_source", "evidence.source")
same_enum(OAS["components"]["schemas"]["WebhookPayload"]["properties"]["event"]["enum"], "webhook_event", "openapi WebhookPayload.event")
same_enum(OAS["components"]["schemas"]["WebhookPayload"]["properties"]["status"]["enum"], "case_status", "openapi WebhookPayload.status")
same_enum(OAS["components"]["schemas"]["AcceptedResponse"]["properties"]["status"]["enum"], "case_status", "openapi AcceptedResponse.status（202 受理仅可为完成前状态，允许六态子集）", subset_ok=True)

mcp = jload(os.path.join(CONTRACTS, "mcp-tools.json"))
tool_names = [t["name"] for t in mcp["tools"]]
(ok if sorted(tool_names) == sorted(codes_of("mcp_tool")) else fail)(f"mcp-tools 六工具名与 registry.mcp_tool 一致（{len(tool_names)}）")
acc_map = {v["code"]: v.get("access") for v in CATS["mcp_tool"]["values"]}
acc_bad = [t["name"] for t in mcp["tools"] if acc_map.get(t["name"]) != t["access"]]
(ok if not acc_bad else fail)("mcp-tools access 级别与 registry.mcp_tool 一致" + (f" · 违例 {acc_bad}" if acc_bad else ""))

# ── E. 交叉一致性 ──────────────────────────────────────────────────
print("E. 种子间交叉一致性")
prov_ids = {p["provider_id"] for p in jload(os.path.join(SEEDS, "providers.json"))["providers"]}
rp_ids = {s["provider"] for r in rp["rules"] for s in r["strategies"]} - {"xml_direct"}
missing = rp_ids - prov_ids
(ok if not missing else fail)("routing_policy 引用 provider_id 均在 providers.json（xml_direct=内置直读位除外）" + (f" · 缺失 {missing}" if missing else ""))

kb = jload(os.path.join(SEEDS, "batches.json"))
alert_ids = [re.search(r"INV-(?:CN|SG)-\d{4}-\d{4}", a["meta"]) for g in ("cn", "os") for a in jload(os.path.join(SEEDS, "alerts.json"))[g]]
alert_ids = [m.group(0) for m in alert_ids if m]
kb_ids = [l["case"] for b in kb["batches"] for l in b["detail"] if l.get("case")]
case_set = set(case_ids)
unknown = [x for x in set(alert_ids + kb_ids) if x not in case_set]
disc_text = " ".join(kb.get("known_page_discrepancies", []))
undeclared = [x for x in unknown if x not in disc_text]
(ok if not undeclared else fail)("alerts/batches 引用案件均在主数据集或已登记扩展白名单" + (f" · 扩展案件 {unknown}（均见 known_page_discrepancies）" if unknown and not undeclared else f" · 未登记引用 {undeclared}"))

if FAILS:
    print(f"\n❌ validate_contracts：{len(FAILS)} 项失败 / {len(PASSES)} 项通过")
    sys.exit(1)
print(f"\n✅ validate_contracts 全绿：{len(PASSES)} 项检查通过")
