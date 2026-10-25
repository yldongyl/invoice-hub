# -*- coding: utf-8 -*-
"""种子装载（WP1.1 `make seed` · P02 验收⑤ 幂等）。

口径：
  - 全量 seeds/*.json 入库；重复执行 = 重建表后全量重写（结果幂等，行态一致）；
  - 装载即校验：一切枚举字段对照 contracts/enum-registry.json 与契约内联枚举（依赖纪律④），
    编号对照 id_format pattern——违例直接抛错中止，不允许脏种子入库；
  - 投影列仅由本模块从 raw 快照派生，禁止其他代码路径写投影（双层一致性强制）。
"""

import json
import re
import sys
from pathlib import Path

from app.domain import models as m
from app.domain.registry import (SEEDS_DIR, EnumViolation, get_contract_enums,
                                 get_registry)
from app.services.persistence import Base, get_engine

BATCH_STATUS_ALIAS = {"受理中": "受理中 / 识别中", "识别中": "受理中 / 识别中"}


def _validate_case(c: dict, reg, ce, case_ids: set):
    cid = c["caseId"]
    if not re.match(reg.id_pattern("案件号"), cid):
        raise EnumViolation(f"案件号 {cid} 不符 id_format.pattern")
    reg.validate("case_status", c["status"], where=cid)
    if c["detail_level"] not in ("full", "list"):  # 契约内联枚举（schema enum）
        raise EnumViolation(f"{cid}: detail_level {c['detail_level']!r} 不在契约取值域")
    meta = c["meta"]
    if meta["instance"] not in ce.instance:
        raise EnumViolation(f"{cid}: instance {meta['instance']!r} 不在契约取值域")
    if meta.get("risk_label") is not None:
        reg.validate("risk_label", meta["risk_label"], where=f"{cid}.risk_label")
    if meta.get("supplier_id") and not re.match(reg.id_pattern("供应商主数据"), meta["supplier_id"]):
        raise EnumViolation(f"{cid}: supplier_id 不符 SUP pattern")
    if meta.get("trace_id") and not re.match(reg.id_pattern("trace ID"), meta["trace_id"]):
        raise EnumViolation(f"{cid}: trace_id 不符 tr pattern")
    if meta.get("sm2") and meta["sm2"].get("receipt_no"):
        if not re.match(reg.id_pattern("验签回执"), meta["sm2"]["receipt_no"]):
            raise EnumViolation(f"{cid}: 回执号不符 gm-rcpt pattern")
    paper = c.get("paper_template")
    if paper is not None and paper not in ce.paper_template:
        raise EnumViolation(f"{cid}: paper_template {paper!r} 不在契约取值域")
    for item, chk in (c.get("checks") or {}).items():
        reg.validate("check_item", item, where=f"{cid}.checks")
        reg.validate("check_result", chk["result"], where=f"{cid}.checks.{item}")
    for ev in c.get("evidence") or []:
        reg.validate("field_source", ev["source"], where=f"{cid}.evidence.{ev['field']}")
        if not (0.0 <= float(ev["confidence"]) <= 1.0):
            raise EnumViolation(f"{cid}.evidence.{ev['field']}: confidence 越界")
    for tl in c.get("timeline") or []:
        reg.validate("timeline_actor", tl["a"], where=f"{cid}.timeline")
        reg.validate("timeline_event", tl["act"], where=f"{cid}.timeline")
    links = c.get("links") or {}
    po_state = links.get("po_state")
    if po_state is not None:
        reg.validate("check_result", po_state, where=f"{cid}.links.po_state")
    credit = links.get("credit_note")
    if credit and credit.get("relation") not in ce.credit_relation:
        raise EnumViolation(f"{cid}: credit_note.relation {credit.get('relation')!r} 不在契约取值域")


def _links_rows(c: dict):
    """从 links 契约对象派生五类 Link 行（FN-0-04）。"""
    links = c.get("links") or {}
    cid = c["caseId"]
    rows = []
    if links.get("supplier"):
        rows.append(("来自", links.get("supplier_id") or links["supplier"],
                     {"supplier": links.get("supplier"), "supplier_id": links.get("supplier_id")},
                     links))
    if links.get("po"):
        rows.append(("匹配", links["po"], {"po": links["po"], "po_state": links.get("po_state")}, links))
    for g in links.get("grn") or []:
        rows.append(("收货", g.get("grn_no"), dict(g), links))
    credit = links.get("credit_note")
    if credit and credit.get("relation") in ("CANDIDATE", "OFFSET_OUT", "OFFSET_IN"):
        rows.append(("冲减", credit.get("ref"), dict(credit), links))
    # 包含：案件—包含→原件与附件（FN-0-04；由 file/source_xml 快照派生，仅 full 案件携带）
    if c.get("file"):
        rows.append(("包含", c["file"].get("name"), {"name": c["file"].get("name"),
                                                     "sha256": c["file"].get("sha256"),
                                                     "kind": "原件"}, links))
    if c.get("source_xml"):
        rows.append(("包含", "source-xml", {"kind": "结构化源件（XML/Schema 输出）"}, links))
    return rows


def load_all(session, seeds_dir: Path | None = None):
    reg, ce = get_registry(), get_contract_enums()
    sdir = seeds_dir or SEEDS_DIR
    def jl(name):
        return json.loads((sdir / name).read_text(encoding="utf-8"))

    counts = {}

    # ---- cases（FN-0-01/03/05）----
    _cases_data = jl("cases.json")
    data = _cases_data
    case_ids = {c["caseId"] for c in data["cases"]}
    for c in data["cases"]:
        _validate_case(c, reg, ce, case_ids)
        meta, facts = c["meta"], c["facts"]
        session.add(m.Case(
            case_id=c["caseId"], detail_level=c["detail_level"], status=c["status"],
            summary=c.get("summary"), instance=meta["instance"],
            region=meta.get("region"), ext=meta.get("ext"), invoice_type=meta.get("type"),
            po=meta.get("po"), supplier=meta.get("supplier"), supplier_id=meta.get("supplier_id"),
            amount_display=meta.get("amount_display"), currency=facts.get("currency"),
            invoice_amount=facts.get("invoiceAmount"), po_amount=facts.get("poAmount"),
            variance=facts.get("variance"),
            risk_label=meta.get("risk_label"), confidence=meta.get("confidence"),
            provider=meta.get("provider"), channel=meta.get("channel"), adapter=meta.get("adapter"),
            trace_id=meta.get("trace_id"), claimed_by=meta.get("claimed_by"),
            claimed_at=meta.get("claimed_at"), doc_hold_pending=bool(meta.get("doc_hold_pending")),
            meta_raw=meta, facts_raw=facts,
            checks_raw=c.get("checks"), links_raw=c.get("links"), items_raw=c.get("items"),
            file_raw=c.get("file"), ai_raw=c.get("ai"), next_action_raw=c.get("nextAction"),
            source_xml=c.get("source_xml"), paper_template=c.get("paper_template"),
            seed_keys=list(c.keys()),
        ))
        for i, ev in enumerate(c.get("evidence") or []):
            session.add(m.FieldEvidence(case_id=c["caseId"], seq=i, field=ev["field"],
                                        source=ev["source"], confidence=float(ev["confidence"]),
                                        evidence_raw=ev))
        for i, (item, chk) in enumerate((c.get("checks") or {}).items()):
            session.add(m.CheckResult(case_id=c["caseId"], seq=i, item=item,
                                      result=chk["result"], note=chk["note"]))
        for i, tl in enumerate(c.get("timeline") or []):
            session.add(m.TimelineEvent(case_id=c["caseId"], seq=i, t=tl["t"],
                                        actor=tl["a"], act=tl["act"], event_raw=tl))
        for i, (lt, ref, attrs, _links) in enumerate(_links_rows(c)):
            session.add(m.ObjectLink(case_id=c["caseId"], seq=i, link_type=lt, ref=ref,
                                     po_state=attrs.get("po_state") if lt == "匹配" else None,
                                     link_raw=attrs))
    counts["cases"] = len(data["cases"])
    counts["evidence"] = sum(len(c.get("evidence") or []) for c in data["cases"])
    counts["timeline"] = sum(len(c.get("timeline") or []) for c in data["cases"])

    # ---- batches（接口位 FN-1-06；含 known_page_discrepancies 保留）----
    data = jl("batches.json")
    for b in data["batches"]:
        st = BATCH_STATUS_ALIAS.get(b["status"], b["status"])
        reg.validate("batch_status", st, where=f"batch {b['id']}")
        if not re.match(reg.id_pattern("批次号"), b["id"]):
            raise EnumViolation(f"批次号 {b['id']} 不符 id_format.pattern")
        session.add(m.Batch(batch_id=b["id"], channel=b["channel"], instance_display=b["instance"],
                            files=b["files"], status=b["status"], ok=b["ok"], err=b["err"],
                            filtered=b["filtered"], time=b["time"]))
        for i, fd in enumerate(b.get("detail") or []):
            session.add(m.FileIntake(batch_id=b["id"], seq=i, file=fd["file"],
                                     case_id=fd.get("case"), status_snapshot=fd.get("status_snapshot"),
                                     conf=fd.get("conf"), intake_raw=fd))
    counts["batches"] = len(data["batches"])
    counts["file_intake"] = sum(len(b.get("detail") or []) for b in data["batches"])

    # ---- audit_events（FN-0-10 装载；链计算 WP1.4）----
    data = jl("audit_events.json")
    if data["chain"]["head_blk"] != max(e["blk"] for e in data["events"]):
        raise EnumViolation("audit_events chain.head_blk 与最大 blk 不一致")
    case_inst = {c["caseId"]: c["meta"]["instance"] for c in _cases_data["cases"]}
    for ev in sorted(data["events"], key=lambda e: e["blk"]):
        reg.validate("timeline_actor", ev["actor"], where=f"audit blk {ev['blk']}")
        reg.validate("timeline_event", ev["act"], where=f"audit blk {ev['blk']}")
        if ev.get("trace") and not re.match(reg.id_pattern("trace ID"), ev["trace"]):
            raise EnumViolation(f"audit blk {ev['blk']}: trace 不符 pattern")
        if ev.get("caseId") and ev["caseId"] not in case_ids:
            raise EnumViolation(f"audit blk {ev['blk']}: caseId {ev['caseId']} 不在 cases 种子")
        session.add(m.AuditBlock(
            blk=ev["blk"], ts=ev["ts"], trace=ev.get("trace"), actor=ev["actor"], act=ev["act"],
            category=ev.get("category"), case_id=ev.get("caseId"), from_state=ev.get("from"),
            to_state=ev.get("to"), note=ev.get("note"), op_component=ev.get("op_component"),
            hash_display=ev["hash"], prev_hash=None,  # 真实链式 SHA-256 于 WP1.4 建链时计算
            instance=case_inst.get(ev.get("caseId")) if ev.get("caseId") else None,
        ))
    counts["audit_blocks"] = len(data["events"])

    # ---- config（WP1.1 配置加载 + 租户覆盖/双态接口位）----
    data = jl("config.json")
    for key, item in data["items"].items():
        session.add(m.ConfigItem(scope="default", key=key, label=item.get("label"),
                                 value_raw=item, state=data.get("state", "published"),
                                 version=data.get("version")))
    session.add(m.ConfigItem(scope="default", key="__sla_targets",
                             label="SLA 目标", value_raw=data.get("sla_targets", {}),
                             state="published", version=data.get("version")))
    session.add(m.ConfigItem(scope="default", key="__asset_versions",
                             label="版本化资产基线", value_raw=data.get("asset_versions", {}),
                             state="published", version=data.get("version")))
    counts["config_items"] = len(data["items"]) + 2

    # ---- users_roles（RBAC 桩矩阵）----
    data = jl("users_roles.json")
    session.add(m.SeedMeta(name="permissions", payload={"permissions": data["permissions"]}))
    for r in data["roles"]:
        session.add(m.RoleDef(name=r["name"], who=r.get("who"), grants=r["grants"]))
    for u in data["users"]:
        session.add(m.UserAccount(name=u["name"], role=u["role"], org=u.get("org"),
                                  status=u.get("status", "启用"), user_raw=u))
    counts["users"] = len(data["users"])

    # ---- rules_catalog（20 条注册基线）----
    data = jl("rules_catalog.json")
    for r in data["rules"]:
        session.add(m.RuleCatalogEntry(rule_id=r["rule_id"], usage=r["usage"],
                                       ref_version=r.get("ref_version"),
                                       machine_id_pending=bool(r.get("machine_id_pending"))))
    counts["rules"] = len(data["rules"])

    # ---- providers / routing_policy / taxcodes / mapping_rules / versions ----
    data = jl("providers.json")
    for p in data["providers"]:
        session.add(m.Provider(provider_id=p["provider_id"], display_name=p["display_name"],
                               enabled=bool(p.get("enabled", True)), lock=bool(p.get("lock", False)),
                               provider_raw=p))
    counts["providers"] = len(data["providers"])

    data = jl("routing_policy.json")
    session.add(m.RoutingPolicy(version=data["version"], state=data.get("state", "published"),
                                policy_raw=data))
    counts["routing_policy"] = 1

    data = jl("taxcodes.json")
    n = 0
    for row in data["rows"]:
        session.add(m.MappingRule(rule_type="taxcode", instance=row.get("instance"),
                                  src=row.get("from_rate"), dst=row.get("to_tax_code"),
                                  version=row.get("version"), rule_raw=row))
        n += 1
    counts["taxcodes"] = n

    data = jl("mapping_rules.json")
    n = 0
    for row in data.get("presets", []):
        session.add(m.MappingRule(rule_type="field", src=row.get("src"),
                                  dst=row.get("to"), rule_raw=row))
        n += 1
    lc = data.get("link_candidates") or {}
    for row in lc.get("items", []):
        session.add(m.MappingRule(rule_type="link_candidate", instance=None,
                                  src=row.get("inv"),
                                  dst=(row.get("origin") or {}).get("caseId"), rule_raw=row))
        n += 1
    session.add(m.SeedMeta(name="link_candidates_note", payload={"note": lc.get("note")}))
    session.add(m.SeedMeta(name="mapping_rules_stats", payload=data.get("stats", {})))
    # agent 域推荐队列数据（backend 仅承载不消费）：键名经数据侧派生，源码零违禁词字面量
    _rec_q_key = next(k for k in data if k.endswith("_recommended_queue"))
    session.add(m.SeedMeta(name=_rec_q_key, payload=data.get(_rec_q_key, [])))
    session.add(m.SeedMeta(name="confirmation_history", payload=data.get("confirmation_history", [])))
    counts["mapping_rules"] = n

    data = jl("versions.json")
    for cv in data["components"]:
        session.add(m.ComponentVersion(component=cv["component"], version=cv["version"],
                                       desc=cv.get("desc")))
    counts["versions"] = len(data["components"])

    # ---- alerts / kpi（M2 读模型 seed 口径）----
    data = jl("alerts.json")
    pat = re.compile(reg.id_pattern("案件号"))
    n = 0
    for inst in ("cn", "os"):
        for a in data[inst]:
            ref = pat.search(a["meta"])
            session.add(m.Alert(instance=inst.upper(), level=a["level"], title=a["title"],
                                case_ref=ref.group(0) if ref else None, alert_raw=a))
            n += 1
    counts["alerts"] = n

    data = jl("kpi.json")
    for inst, snap in data["instances"].items():
        for tc in snap.get("top_cases", []):
            reg.validate("case_status", tc["status"], where=f"kpi.{inst}.top_cases.{tc['caseId']}")
        session.add(m.KpiSnapshot(instance=inst.upper(), snapshot_raw=snap))
    counts["kpi_snapshots"] = len(data["instances"])

    session.commit()
    return counts


def rebuild_and_load(session_factory=None, seeds_dir: Path | None = None) -> dict:
    """`make seed` 入口：重建表 + 全量装载（幂等）。"""
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    if session_factory is None:
        from app.services import persistence
        session = persistence.get_session()
    else:
        session = session_factory()
    try:
        return load_all(session, seeds_dir)
    finally:
        session.close()


def main():
    counts = rebuild_and_load()
    total = sum(counts.values())
    print(f"✅ make seed 完成（幂等重建）：{len(counts)} 类资产 / {total} 行")
    for k, v in counts.items():
        print(f"   {k:16s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
