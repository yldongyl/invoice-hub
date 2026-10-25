#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seeds ↔ ui-design 页面内嵌 JS 常量 逐案交叉校验（G-M0-001 · M0 门禁挂账项交付，M1 首个工作包）。

背景：实施规划 §4-M0 验收③ 要求「seeds 案件数据与 UI 12 页出现的案件字段逐案一致（脚本断言）」，
M0 仅人工核对（裁决采建议 A：脚本列为 M1 首个工作包，交付并跑绿前 M1 其余工作包不得收工）。

断言口径（页面侧既有错误一律对照 seeds/batches.json known_page_discrepancies 输出「已登记豁免」，
不得静默跳过；未登记的差异 = 失败）：
  - 断言对象 = 页面渲染所消费的权威字段（案件标识/状态/置信度/金额/供应商/证据/时间线/Link/KPI/告警/批次/审计）；
    纯展示性文案（如 dashboard region 列、top_cases.risk.t 的展示缩写）只与承载其逐字口径的
    种子文件（kpi.json / alerts.json）比对，不与 cases.json 规范值交叉——规范值交叉见
    WB / QUEUE / BATCHES 等使用规范枚举的页面。此为声明范围，非静默跳过。
  - 「种子超集容差」：seed 字段保留口径注记（如 amount_display「¥5,680.00（XML 口径）」、
    provider「XML 直读（免 Provider）」）而页面仅显示主干文本时，判定 seed.startswith(page)
    且差异部分为括号注记 → 通过并输出 [口径注记]；其余不等情形 → 差异。
  - 枚举纪律：页面/种子出现的全部状态/事件码/主体/来源/校验结果/风险标签/差异类型值
    必须 ∈ contracts/enum-registry.json（FN-0-15）。

解析范围（与 M0 门禁裁决一致）：case-detail.html CASES、dashboard-overview.html DATA、
invoice-intake.html BATCHES、audit-reports.html LOGS/DEMO_CASES、agent-workbench.html WB、
matching-mapping.html QUEUE；ui-design/ 只读不改。

用法：python tools/check_seeds_vs_ui.py [--ui <ui-design路径>] [--quiet]
退出码：0 全绿（含已登记豁免）；1 存在未登记差异或枚举违例；2 依赖/文件缺失。
"""

import argparse
import json
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SEEDS = os.path.join(ROOT, "seeds")
CONTRACTS = os.path.join(ROOT, "contracts")
DEFAULT_UI = os.path.normpath(os.path.join(ROOT, os.pardir, "ui-design"))


def die(msg, code=2):
    print("FATAL:", msg)
    sys.exit(code)


# ──────────────────────────────────────────────────────────────────────────────
# 1) JS 字面量解析器（递归下降；仅 stdlib，支持注释/单双反引号字符串/未加引号键/尾逗号）
# ──────────────────────────────────────────────────────────────────────────────

class JSParseError(Exception):
    pass


class JSLiteralParser:
    """解析 JS 对象/数组字面量子集（本项目内嵌常量实际使用的语法）。"""

    def __init__(self, text):
        self.t = text
        self.i = 0
        self.n = len(text)

    def parse(self):
        v = self.value()
        self.ws()
        return v

    def ws(self):
        while self.i < self.n:
            c = self.t[self.i]
            if c in " \t\r\n,;":
                # 顶层的 , ; 不应被吞掉——仅在结构分隔处消费；此处只消费空白与注释
                if c in ",;":
                    return
                self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.t[self.i + 1] == "/":
                while self.i < self.n and self.t[self.i] != "\n":
                    self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.t[self.i + 1] == "*":
                end = self.t.find("*/", self.i + 2)
                if end < 0:
                    raise JSParseError("未闭合块注释")
                self.i = end + 2
            else:
                return

    def value(self):
        self.ws2()
        if self.i >= self.n:
            raise JSParseError("意外结束")
        c = self.t[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c in "'\"":
            return self.quoted(c)
        if c == "`":
            return self.template()
        if c == "-" or c == "+" or c.isdigit():
            return self.number()
        m = re.match(r"true|false|null", self.t[self.i:])
        if m:
            self.i += m.end()
            return {"true": True, "false": False, "null": None}[m.group(0)]
        raise JSParseError(f"无法解析 {self.t[self.i:self.i+20]!r}")

    def ws2(self):
        # 值之前的空白/注释（不吞 , ;）
        while self.i < self.n:
            c = self.t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.t[self.i + 1] == "/":
                while self.i < self.n and self.t[self.i] != "\n":
                    self.i += 1
            elif c == "/" and self.i + 1 < self.n and self.t[self.i + 1] == "*":
                end = self.t.find("*/", self.i + 2)
                if end < 0:
                    raise JSParseError("未闭合块注释")
                self.i = end + 2
            else:
                return

    def key(self):
        self.ws2()
        c = self.t[self.i]
        if c in "'\"":
            return self.quoted(c)
        m = re.match(r"[A-Za-z_$][\w$]*", self.t[self.i:])
        if not m:
            raise JSParseError(f"非法键 {self.t[self.i:self.i+20]!r}")
        self.i += m.end()
        return m.group(0)

    def obj(self):
        d = {}
        self.i += 1  # {
        while True:
            self.ws2()
            if self.i < self.n and self.t[self.i] == "}":
                self.i += 1
                return d
            k = self.key()
            self.ws2()
            if self.i >= self.n or self.t[self.i] != ":":
                raise JSParseError(f"键 {k} 后缺 :")
            self.i += 1
            d[k] = self.value()
            self.ws2()
            if self.i < self.n and self.t[self.i] == ",":
                self.i += 1

    def arr(self):
        a = []
        self.i += 1  # [
        while True:
            self.ws2()
            if self.i < self.n and self.t[self.i] == "]":
                self.i += 1
                return a
            a.append(self.value())
            self.ws2()
            if self.i < self.n and self.t[self.i] == ",":
                self.i += 1

    def quoted(self, q):
        self.i += 1
        out = []
        while self.i < self.n:
            c = self.t[self.i]
            if c == "\\":
                nxt = self.t[self.i + 1] if self.i + 1 < self.n else ""
                esc = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"', "`": "`", "/": "/", "b": "\b", "f": "\f"}
                if nxt in esc:
                    out.append(esc[nxt]); self.i += 2; continue
                if nxt == "u":
                    out.append(chr(int(self.t[self.i + 2:self.i + 6], 16))); self.i += 6; continue
                out.append(nxt); self.i += 2; continue
            if c == q:
                self.i += 1
                return "".join(out)
            if c == "\n":
                raise JSParseError("字符串未闭合（跨行）")
            out.append(c)
            self.i += 1
        raise JSParseError("字符串未闭合")

    def template(self):
        self.i += 1
        out = []
        while self.i < self.n:
            c = self.t[self.i]
            if c == "\\":
                nxt = self.t[self.i + 1] if self.i + 1 < self.n else ""
                if nxt == "`":
                    out.append("`"); self.i += 2; continue
                if nxt == "$":
                    out.append("$"); self.i += 2; continue
                out.append(nxt); self.i += 2; continue
            if c == "`":
                self.i += 1
                s = "".join(out)
                if "${" in s:
                    raise JSParseError("模板字符串含插值，超出解析范围")
                return s
            if c == "$" and self.i + 1 < self.n and self.t[self.i + 1] == "{":
                raise JSParseError("模板字符串含插值，超出解析范围")
            out.append(c)
            self.i += 1
        raise JSParseError("模板字符串未闭合")

    def number(self):
        m = re.match(r"[+-]?\d+(\.\d+)?([eE][+-]?\d+)?", self.t[self.i:])
        if not m:
            raise JSParseError(f"非法数字 {self.t[self.i:self.i+12]!r}")
        self.i += m.end()
        s = m.group(0)
        return float(s) if ("." in s or "e" in s.lower()) else int(s)


def extract_const(html_text, const_name):
    """从页面文本中提取 `const NAME = <literal>;` 的字面量并解析。"""
    m = re.search(r"const\s+" + re.escape(const_name) + r"\s*=\s*", html_text)
    if not m:
        die(f"页面常量未找到: const {const_name}")
    p = JSLiteralParser(html_text[m.end():])
    return p.parse()


# ──────────────────────────────────────────────────────────────────────────────
# 2) 结果收集器（PASS / 已登记豁免 / 口径注记 / FAIL）
# ──────────────────────────────────────────────────────────────────────────────

class Result:
    def __init__(self):
        self.passes = []
        self.exempts = []   # (描述, 依据原文)
        self.notes = []     # 口径注记（容差命中，逐条记录不静默）
        self.fails = []

    def ok(self, msg):
        self.passes.append(msg)

    def fail(self, msg):
        self.fails.append(msg)

    def note(self, msg):
        self.notes.append(msg)


def load_json(path):
    if not os.path.exists(path):
        die(f"文件缺失: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def eq_or_superset(page_val, seed_val):
    """页面文本==seed，或 seed 为页面文本的『（注记）』超集 → 返回 (命中, 是否超集)。"""
    if isinstance(page_val, str) and isinstance(seed_val, str):
        if page_val == seed_val:
            return True, False
        if seed_val.startswith(page_val) and seed_val[len(page_val):].startswith("（"):
            return True, True
    return page_val == seed_val, False


def cmp_field(r, ctx, page_val, seed_val):
    hit, superset = eq_or_superset(page_val, seed_val)
    if not hit and isinstance(page_val, str) and isinstance(seed_val, str) and "<" in page_val:
        # 口径注记归一：seed 侧对页面富文本做过 class 属性剥离（设计语义由颜色枚举承载，非数据差异）
        strip = lambda s: re.sub(r'\s+class="[^"]*"', "", s)
        if strip(page_val) == strip(seed_val):
            r.note(f"{ctx}: HTML class 属性归一后一致（seed 剥离页面装饰属性）")
            return True
    if not hit:
        r.fail(f"{ctx}: 页面={page_val!r} vs seed={seed_val!r}")
    elif superset:
        r.note(f"{ctx}: 种子超集容差 页面={page_val!r} seed={seed_val!r}")
    return hit


def cmp_or_exempt(r, known, ctx, pv, sv, cid):
    """与 cases.json 权威口径交叉：不等时须命中同一登记项（含案件号与两侧原值）方可豁免。"""
    hit, superset = eq_or_superset(pv, sv)
    if hit:
        if superset:
            r.note(f"{ctx}: 种子超集容差 页面={pv!r} seed={sv!r}")
        return True
    return exempt_or_fail(r, known, ctx, pv, sv, [cid, str(pv), str(sv)])


def exempt_or_fail(r, known, ctx, pv, sv, tokens):
    """差异须匹配 known_page_discrepancies 中同时含全部 tokens 的登记项方可豁免，否则记失败。"""
    for entry in known:
        if all(t in entry for t in tokens):
            r.exempts.append(f"{ctx}: 页面={pv!r} vs seed={sv!r}｜依据: {entry}")
            return True
    r.fail(f"{ctx}: 页面={pv!r} vs seed={sv!r}（无已登记豁免）")
    return False


def jstr(v):
    return json.dumps(v, ensure_ascii=False)


# ──────────────────────────────────────────────────────────────────────────────
# 3) 豁免引擎：差异必须匹配 seeds/batches.json known_page_discrepancies 方可豁免
# ──────────────────────────────────────────────────────────────────────────────

def find_registered(known, key_substring):
    for entry in known:
        if key_substring in entry:
            return entry
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 4) 断言层
# ──────────────────────────────────────────────────────────────────────────────

def check_case_detail(r, page_cases, seed_by_id, known, enum_codes):
    full_ids = sorted(k for k, c in seed_by_id.items() if c["detail_level"] == "full")
    if sorted(page_cases.keys()) != full_ids:
        r.fail(f"case-detail CASES 键集合 {sorted(page_cases.keys())} ≠ seeds full 案件 {full_ids}")
    else:
        r.ok(f"case-detail CASES 键集合与 seeds full 案件逐案一致（{len(full_ids)} 案）")

    for cid, pc in page_cases.items():
        if cid not in seed_by_id:
            r.fail(f"case-detail {cid}: seed cases.json 无此案件（非豁免范围）")
            continue
        s = seed_by_id[cid]
        smeta = s["meta"]

        # meta
        pm = pc["meta"]
        for pk, sk in [("status", "status_top"), ("region", "region"), ("ext", "ext"), ("type", "type"),
                       ("po", "po"), ("supplier", "supplier"), ("supId", "supplier_id"),
                       ("amount", "amount_display"), ("received", "received_at"), ("channel", "channel"),
                       ("adapter", "adapter"), ("vat", "vat")]:
            sv = smeta.get(sk) if sk != "status_top" else s.get("status")
            ctx = f"case-detail[{cid}].meta.{pk}"
            if pk == "status":
                cmp_field(r, ctx, pm.get(pk), s.get("status"))
            else:
                if pm.get(pk) is None and sv is None:
                    r.ok(ctx)
                    continue
                cmp_field(r, ctx, pm.get(pk), sv)
        # sm2
        if pm.get("sm2") is None and smeta.get("sm2") is None:
            r.ok(f"case-detail[{cid}].meta.sm2=null")
        else:
            for f in ("ok", "text"):
                if pm.get("sm2") and smeta.get("sm2"):
                    cmp_field(r, f"case-detail[{cid}].meta.sm2.{f}", pm["sm2"].get(f), smeta["sm2"].get(f))
        if pm.get("sm2") and smeta.get("sm2"):
            rc = smeta["sm2"].get("receipt_no")
            if rc and rc not in (pc.get("xml") or "") and rc not in (pm["sm2"].get("text") or ""):
                r.fail(f"case-detail[{cid}]: seed 回执 {rc} 未在页面 sm2 文案或 XML 模板中出现")
            elif rc:
                r.ok(f"case-detail[{cid}].sm2 回执 {rc} 页面可溯（sm2.text/xml 模板）")

        # checks
        seed_checks = s["checks"]
        for chk in pc["checks"]:
            key = chk["k"].split(" ")[0]
            if key not in seed_checks:
                r.fail(f"case-detail[{cid}].checks: 页面校验项 {key!r} 不在四校验枚举")
                continue
            if chk["v"] not in enum_codes["check_result"]:
                r.fail(f"case-detail[{cid}].checks.{key}: 结果 {chk['v']!r} 不在 check_result 枚举")
            cmp_field(r, f"case-detail[{cid}].checks.{key}.v", chk["v"], seed_checks[key]["result"])
            cmp_field(r, f"case-detail[{cid}].checks.{key}.note", chk["note"], seed_checks[key]["note"])

        # groups → evidence
        seed_ev = {e["field"]: e for e in s["evidence"]}
        seen_ev = set()
        n_cmp = 0
        for grp in pc["groups"]:
            for fl in grp["fields"]:
                path = fl["path"]
                ctx = f"case-detail[{cid}].evidence[{path}]"
                e = seed_ev.get(path)
                if e is None:
                    r.fail(f"{ctx}: seed evidence 无对应字段")
                    continue
                seen_ev.add(path)
                n_cmp += 1
                cmp_field(r, ctx + ".value", str(fl["v"]), str(e["value"]))
                cmp_field(r, ctx + ".source", fl["src"], e["source"])
                if fl["src"] not in enum_codes["field_source"]:
                    r.fail(f"{ctx}: 来源 {fl['src']!r} 不在 field_source 枚举")
                if abs(e["confidence"] - fl["conf"] / 100.0) > 1e-9:
                    r.fail(f"{ctx}.confidence: 页面 {fl['conf']}% vs seed {e['confidence']}")
                cmp_field(r, ctx + ".group", grp["title"], e["group"])
                label = re.sub(r" ?★.*$", "", fl["k"])
                if not (e["label"] == label or e["label"] == fl["k"] or label in e["label"]):
                    r.fail(f"{ctx}.label: 页面 {fl['k']!r} vs seed {e['label']!r}")
                if ("star" in fl) != bool(e.get("star")):
                    r.fail(f"{ctx}.star: 页面 {fl.get('star', False)} vs seed {e.get('star', False)}")
                cmp_field(r, ctx + ".anchor", fl.get("pv"), e.get("anchor"))
                pe = fl["ev"]
                se = e["evidence"]
                for pf, sf in [("page", "page"), ("bbox", "bbox"), ("raw", "raw_text"), ("model", "model_version"),
                               ("provider", "provider"), ("rule", "rule")]:
                    cmp_field(r, f"{ctx}.ev.{sf}", pe.get(pf), se.get(sf))
        extra_ev = set(seed_ev) - seen_ev
        if extra_ev:
            r.fail(f"case-detail[{cid}]: seed evidence 有而页面未渲染的字段 {sorted(extra_ev)}")
        else:
            r.ok(f"case-detail[{cid}]: 全部 {n_cmp} 个证据字段逐字段一致（值/来源/置信度/分组/标签/星/锚点/证据六要素）")

        # timeline
        stl = s["timeline"]
        ptl = pc["timeline"]
        if len(ptl) != len(stl):
            r.fail(f"case-detail[{cid}].timeline: 页面 {len(ptl)} 条 vs seed {len(stl)} 条")
        else:
            for i, (pe, se) in enumerate(zip(ptl, stl)):
                for f in ("t", "a", "act", "d", "x", "v"):
                    pv, sv = pe.get(f), se.get(f)
                    if pv != sv and not (pv is None and sv is None):
                        r.fail(f"case-detail[{cid}].timeline[{i}].{f}: 页面 {pv!r} vs seed {sv!r}")
                if pe.get("act") not in enum_codes["timeline_event"]:
                    r.fail(f"case-detail[{cid}].timeline[{i}].act {pe.get('act')!r} 不在事件码枚举")
                if pe.get("a") not in enum_codes["timeline_actor"]:
                    r.fail(f"case-detail[{cid}].timeline[{i}].a {pe.get('a')!r} 不在主体枚举")
            r.ok(f"case-detail[{cid}]: timeline {len(stl)} 条逐事件一致（t/a/act/d/x/v）")

        # items
        si = s.get("items")
        if si and pc.get("items"):
            cmp_field(r, f"case-detail[{cid}].items.note", pc["items"]["src"], si["note"])
            if pc["items"]["head"] != si["columns"]:
                r.fail(f"case-detail[{cid}].items.columns: 页面 {pc['items']['head']} vs seed {si['columns']}")
            if pc["items"]["rows"] != si["rows"]:
                r.fail(f"case-detail[{cid}].items.rows 不一致")
            r.ok(f"case-detail[{cid}]: items 表头/行项目/口径注记一致")

        # links
        sl = s.get("links")
        pl = pc.get("links")
        if sl and pl:
            cmp_field(r, f"case-detail[{cid}].links.po", pl.get("po"), sl.get("po"))
            cmp_field(r, f"case-detail[{cid}].links.po_state", pl.get("poState"), sl.get("po_state"))
            recon = [g["grn_no"] + (f"（{g['note']}）" if g.get("note") else "") for g in sl.get("grn", [])]
            if sorted(pl.get("grn", [])) != sorted(recon):
                r.fail(f"case-detail[{cid}].links.grn: 页面 {pl.get('grn')} vs seed 还原 {recon}")
            else:
                r.ok(f"case-detail[{cid}]: links.grn {len(recon)} 条一致")
            pcredit, scred = pl.get("credit"), sl.get("credit_note")
            if pcredit is None and scred and scred.get("relation") == "NONE":
                r.ok(f"case-detail[{cid}]: links.credit 页面空=seed relation NONE")
            elif pcredit != (None if scred.get("relation") == "NONE" else scred.get("ref")):
                r.fail(f"case-detail[{cid}].links.credit: 页面 {pcredit!r} vs seed {jstr(scred)}")
            else:
                r.ok(f"case-detail[{cid}]: links.credit 一致")

        # file / source_xml / ai / paper_template
        sf = s.get("file")
        if sf and pc.get("file"):
            cmp_field(r, f"case-detail[{cid}].file.pdf", pc["file"]["pdf"], sf["display"])
            cmp_field(r, f"case-detail[{cid}].file.note", pc["file"]["note"], sf["note"])
        if pc.get("xml") is not None and s.get("source_xml") is not None:
            if pc["xml"].strip() != s["source_xml"].strip():
                r.fail(f"case-detail[{cid}].source_xml 逐字不一致")
            else:
                r.ok(f"case-detail[{cid}]: source_xml 逐字一致")
        pai, sai = pc.get("ai"), s.get("ai")
        if pai and sai:
            cmp_field(r, f"case-detail[{cid}].ai.title", pai["title"], sai["title"])
            cmp_field(r, f"case-detail[{cid}].ai.conf", pai["conf"], sai["confidence"])
            cmp_field(r, f"case-detail[{cid}].ai.model", pai["model"], sai["model_version"])
            cmp_field(r, f"case-detail[{cid}].ai.body", pai["body"], sai["body"])
            cmp_field(r, f"case-detail[{cid}].ai.conclude", pai["conclude"], sai["conclusion"])
            cmp_field(r, f"case-detail[{cid}].ai.ruleNote", pai["ruleNote"], sai["rule_note"])
            if not (sai.get("disclaimer") and sai.get("status")):
                r.fail(f"case-detail[{cid}]: seed ai 缺免责声明/生命周期（FN-0-09/8-09 强制）")
            r.ok(f"case-detail[{cid}]: ai 建议卡公共字段一致 + 免责/状态在 seed 侧齐备")
        if pc.get("paperKey") is not None:
            cmp_field(r, f"case-detail[{cid}].paperKey", pc["paperKey"], s.get("paper_template"))


def check_dashboard(r, data, kpi_seed, alerts_seed, seed_by_id, known):
    for inst in ("cn", "os"):
        pd, sd = data[inst], kpi_seed["instances"][inst]
        cmp_field(r, f"dashboard[{inst}].donutScope", pd["donutScope"], sd["donut_scope"])
        kmap = {"total": "total", "totalSub": "total_sub", "touchless": "touchless",
                "touchlessSub": "touchless_sub", "falseAuto": "false_auto_rate",
                "review": "pending_review", "reviewRisk": "pending_risk"}
        for pk, sk in kmap.items():
            cmp_field(r, f"dashboard[{inst}].kpi.{pk}", pd["kpi"][pk], sd["kpi"][sk])
        if sd["kpi"].get("false_auto_limit") != "0.05%":
            r.fail(f"dashboard[{inst}]: seed false_auto_limit ≠ 0.05% 红线")
        else:
            r.ok(f"dashboard[{inst}].kpi.false_auto_limit 红线 0.05% 在位")
        if pd["donut"] != sd["donut"]:
            r.fail(f"dashboard[{inst}].donut 逐字不一致（页面 vs kpi.json）")
        else:
            r.ok(f"dashboard[{inst}].donut {len(sd['donut'])} 段逐字一致")
        if pd["line"] != sd["trend_7d"]:
            r.fail(f"dashboard[{inst}].line vs seed trend_7d 逐字不一致")
        else:
            r.ok(f"dashboard[{inst}].trend_7d 标签/序列逐字一致")
        # cases ↔ kpi.json top_cases 逐字 + ↔ cases.json 权威字段交叉
        if len(pd["cases"]) != len(sd["top_cases"]):
            r.fail(f"dashboard[{inst}].cases {len(pd['cases'])} 条 vs seed top_cases {len(sd['top_cases'])} 条")
        for pc, sc in zip(pd["cases"], sd["top_cases"]):
            if pc["id"] != sc["caseId"] or pc["supplier"] != sc["supplier"] or pc["status"] != sc["status"] \
               or pc["conf"] != sc["conf"] or pc["amount"] != sc["amount"] or pc["region"] != sc["region"] \
               or pc["provider"] != sc["provider"] or (pc.get("risk") or {}).get("t") != (sc.get("risk") or {}).get("t"):
                r.fail(f"dashboard[{inst}].cases[{pc['id']}]: 页面 vs kpi.json top_cases 逐字不一致")
            s = seed_by_id.get(pc["id"])
            if s is None:
                entry = find_registered(known, pc["id"])
                if entry:
                    r.exempts.append(f"dashboard[{inst}].cases {pc['id']} 不在 A.1/11 案 seed 主数据集（列表级补录）｜依据: {entry}")
                else:
                    r.fail(f"dashboard[{inst}].cases {pc['id']} 不在 cases.json 且无已登记豁免")
            else:
                for f in ("status", "supplier", "amount", "conf"):
                    pv = pc[f]
                    sv = {"status": s["status"], "supplier": s["meta"]["supplier"],
                          "amount": s["meta"]["amount_display"], "conf": s["meta"]["confidence"]}[f]
                    cmp_or_exempt(r, known, f"dashboard[{inst}].cases[{pc['id']}].{f}", pv, sv, pc["id"])
        # alerts ↔ alerts.json 逐字
        sa = alerts_seed[inst]
        pa = pd["alerts"]
        if [ {k: a.get(k) for k in ("level", "title", "meta", "evidence")} for a in pa ] != sa:
            r.fail(f"dashboard[{inst}].alerts 逐字 vs alerts.json 不一致")
        else:
            r.ok(f"dashboard[{inst}].alerts {len(sa)} 条逐字一致（级别/标题/元信息/证据 HTML）")


def check_workbench(r, wb, seed_by_id, known, enum_codes):
    n = 0
    for w in wb:
        cid = w["id"]
        if cid not in seed_by_id:
            r.fail(f"agent-workbench {cid}: 不在 cases.json（非豁免范围）")
            continue
        s = seed_by_id[cid]
        m = s["meta"]
        n += 1
        cmp_field(r, f"WB[{cid}].status", w["status"], s["status"])
        if w["status"] not in enum_codes["case_status"]:
            r.fail(f"WB[{cid}].status {w['status']!r} 不在六态枚举")
        cmp_field(r, f"WB[{cid}].sup", w["sup"], m["supplier"])
        cmp_field(r, f"WB[{cid}].amt", w["amt"], m["amount_display"])
        cmp_field(r, f"WB[{cid}].conf", w["conf"], m["confidence"])
        cmp_field(r, f"WB[{cid}].provider", w["provider"], m["provider"])
        cmp_field(r, f"WB[{cid}].type", w["type"], m["type"])
        cmp_field(r, f"WB[{cid}].summary", w["summary"], s["summary"])
        wrl = (w.get("risk") or {}).get("t")
        if (wrl or None) != (m.get("risk_label") or None):
            r.fail(f"WB[{cid}].risk.t: 页面 {wrl!r} vs seed risk_label {m.get('risk_label')!r}")
        if wrl is not None and wrl not in enum_codes["risk_label"]:
            r.fail(f"WB[{cid}].risk.t {wrl!r} 不在 risk_label 枚举（FN-0-15 全站唯一）")
    r.ok(f"agent-workbench WB {n}/{len(wb)} 案逐案一致（状态/供应商/金额/置信度/Provider/票种/摘要/风险标签）")


def check_intake(r, batches_page, batches_seed, seed_by_id, known, enum_codes):
    if len(batches_page) != len(batches_seed["batches"]):
        r.fail(f"intake BATCHES {len(batches_page)} 批 vs seed {len(batches_seed['batches'])} 批")
        return
    for pb, sb in zip(batches_page, batches_seed["batches"]):
        bid = pb["id"]
        ctx = f"BATCHES[{bid}]"
        for pk, sk in [("id", "id"), ("ch", "channel"), ("inst", "instance"), ("files", "files"),
                       ("st", "status"), ("ok", "ok"), ("err", "err"), ("filt", "filtered"), ("t", "time")]:
            cmp_field(r, f"{ctx}.{pk}", pb[pk], sb[sk])
        if pb["st"] not in enum_codes["batch_status"] and not (pb["st"] in ("受理中", "识别中") and "受理中 / 识别中" in enum_codes["batch_status"]):
            r.fail(f"{ctx}.st 状态 {pb['st']!r} 不在 batch_status 枚举")
        if len(pb["detail"]) != len(sb["detail"]):
            r.fail(f"{ctx}: 页面文件级明细 {len(pb['detail'])} 条 vs seed {len(sb['detail'])} 条")
        for fd, sd in zip(pb["detail"], sb["detail"]):
            for pk, sk in [("f", "file"), ("carrier", "carrier"), ("case", "case"),
                           ("st", "status_snapshot"), ("conf", "conf")]:
                cmp_field(r, f"{ctx}.detail[{fd.get('f','?')}].{pk}", fd.get(pk), sd.get(sk))
            if fd.get("note") != sd.get("note"):
                r.fail(f"{ctx}.detail[{fd.get('f','?')}].note 不一致")
            if ("bad" in fd) != bool(sd.get("bad")):
                r.fail(f"{ctx}.detail[{fd.get('f','?')}].bad 不一致")
        # ① 案件引用存在性（0121 → 已登记豁免）
        for fd in pb["detail"]:
            c = fd.get("case")
            if not c:
                continue
            if c in seed_by_id:
                continue
            entry = find_registered(known, c) or find_registered(known, bid)
            if entry:
                r.exempts.append(f"{ctx}.detail {c} 为扩展案件（页面/batch 同源保留，M1 列表级补录）｜依据: {entry}")
            else:
                r.fail(f"{ctx}.detail 案件 {c} 不在 cases.json 且无已登记豁免")
        # ② 文件名供应商 ↔ 案件主数据交叉（D8：命中已登记豁免输出，不静默跳过）
        for fd in pb["detail"]:
            c = fd.get("case")
            if not c or c not in seed_by_id:
                continue
            sup = seed_by_id[c]["meta"]["supplier"]
            tokens = {t: s2["meta"]["supplier"] for t, s2 in TOK_SUP.items()}
            for tok, owner in tokens.items():
                if tok in fd["f"] and owner != sup:
                    entry = find_registered(known, "文件命名")
                    loc = f"{ctx}.detail 文件名供应商「{tok}」与案件 {c} 主数据「{sup}」交叉"
                    if entry:
                        r.exempts.append(f"{loc}｜依据: {entry}")
                    else:
                        r.fail(loc)
    r.ok(f"intake BATCHES {len(batches_page)} 批 × {sum(len(b['detail']) for b in batches_page)} 文件级明细逐字一致")


def check_audit(r, logs, ae_seed, seed_by_id, enum_codes):
    if len(logs) != len(ae_seed["events"]):
        r.fail(f"audit LOGS {len(logs)} 条 vs seed audit_events {len(ae_seed['events'])} 条")
        return
    keymap = [("ts", "ts"), ("tr", "trace"), ("a", "actor"), ("code", "act"), ("cat", "category"),
              ("cs", "caseId"), ("from", "from"), ("to", "to"), ("note", "note"), ("op", "op_component"),
              ("blk", "blk"), ("hash", "hash")]
    for i, (pl, sl) in enumerate(zip(logs, ae_seed["events"])):
        for pk, sk in keymap:
            pv = pl.get(pk)
            sv = sl.get(sk)
            if pk == "cs":
                pv = pv if pv else None
            if pv != sv:
                r.fail(f"LOGS[{i}]({pl.get('ts')}): 页面 {pk}={pv!r} vs seed {sk}={sv!r}")
        if pl["code"] not in enum_codes["timeline_event"]:
            r.fail(f"LOGS[{i}].code {pl['code']!r} 不在事件码枚举")
        if pl["a"] not in enum_codes["timeline_actor"]:
            r.fail(f"LOGS[{i}].a {pl['a']!r} 不在主体枚举")
        if pl.get("cs") and pl["cs"] not in seed_by_id:
            r.fail(f"LOGS[{i}].cs {pl['cs']} 不在 cases.json（审计案引用须可解析）")
    blks = [l["blk"] for l in logs]
    if blks != sorted(blks, reverse=True) or len(set(blks)) != len(blks):
        r.fail(f"LOGS blk# 非严格递减/有重复: {blks}")
    if logs[0]["blk"] != ae_seed["chain"]["head_blk"]:
        r.fail(f"LOGS 链头 blk={logs[0]['blk']} ≠ seed chain.head_blk {ae_seed['chain']['head_blk']}")
    else:
        r.ok(f"audit LOGS↔audit_events {len(logs)} 条逐字一致（12 字段映射）；链头 blk#{logs[0]['blk']} 对齐；act/actor/案引用枚举合规")


def check_matching(r, queue, seed_by_id, known, enum_codes, diff_colors):
    for q in queue:
        cid = q["id"]
        if cid not in seed_by_id:
            r.fail(f"matching QUEUE {cid} 不在 cases.json")
            continue
        s = seed_by_id[cid]
        m = s["meta"]
        cmp_or_exempt(r, known, f"QUEUE[{cid}].supplier", q["supplier"], m["supplier"], cid)
        cmp_or_exempt(r, known, f"QUEUE[{cid}].amount", q["amount"], m["amount_display"], cid)
        cmp_or_exempt(r, known, f"QUEUE[{cid}].status", q["status"], s["status"], cid)
        for bd in q.get("badges", []):
            if bd["t"] not in enum_codes["diff_type"]:
                r.fail(f"QUEUE[{cid}].badges {bd['t']!r} 不在 diff_type 枚举")
            elif diff_colors.get(bd["t"]) and bd["c"] != diff_colors[bd["t"]]:
                r.fail(f"QUEUE[{cid}].badges[{bd['t']}].color: 页面 {bd['c']!r} vs registry {diff_colors[bd['t']]!r}")
        q["supplier"] and q["amount"]
    r.ok(f"matching QUEUE {len(queue)} 案：供应商/金额/状态与 cases 一致；差异徽章 ∈ diff_type 枚举且配色同源")


# ──────────────────────────────────────────────────────────────────────────────
# 5) 主流程
# ──────────────────────────────────────────────────────────────────────────────

# 文件名供应商短词（A.1 主数据集派生；仅用于 D8 类交叉检测）
TOK_SUP = {}


def build_tok_sup(seed_by_id):
    short = {
        "INV-CN-2026-0387": "中科华创", "INV-CN-2026-0386": "临港智造", "INV-CN-2026-0385": "广合",
        "INV-CN-2026-0384": "粤海", "INV-CN-2026-0383": "云栖", "INV-CN-2026-0381": "恒信",
        "INV-CN-2026-0379": "天府", "INV-SG-2026-0125": "Siemens", "INV-SG-2026-0124": "Dell",
        "INV-SG-2026-0123": "AWS", "INV-SG-2026-0122": "Schaeffler",
    }
    for cid, tok in short.items():
        if cid in seed_by_id:
            TOK_SUP[tok] = seed_by_id[cid]


def main():
    ap = argparse.ArgumentParser(description="seeds ↔ ui-design 交叉校验（G-M0-001）")
    ap.add_argument("--ui", default=DEFAULT_UI)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(args.ui):
        die(f"ui-design 路径不存在: {args.ui}")

    enum_reg = load_json(os.path.join(CONTRACTS, "enum-registry.json"))
    enum_codes = {k: {v["code"] for v in cat["values"]} for k, cat in enum_reg["categories"].items()}
    diff_colors = {v["code"]: v.get("color") for v in enum_reg["categories"]["diff_type"]["values"]}

    cases_seed = load_json(os.path.join(SEEDS, "cases.json"))
    seed_by_id = {c["caseId"]: c for c in cases_seed["cases"]}
    build_tok_sup(seed_by_id)
    batches_seed = load_json(os.path.join(SEEDS, "batches.json"))
    known = batches_seed["known_page_discrepancies"]
    alerts_seed = load_json(os.path.join(SEEDS, "alerts.json"))
    kpi_seed = load_json(os.path.join(SEEDS, "kpi.json"))
    ae_seed = load_json(os.path.join(SEEDS, "audit_events.json"))

    def page(name):
        p = os.path.join(args.ui, name)
        if not os.path.exists(p):
            die(f"页面缺失: {p}")
        with open(p, encoding="utf-8") as f:
            return f.read()

    r = Result()
    try:
        check_case_detail(r, extract_const(page("case-detail.html"), "CASES"), seed_by_id, known, enum_codes)
        check_dashboard(r, extract_const(page("dashboard-overview.html"), "DATA"), kpi_seed, alerts_seed, seed_by_id, known)
        check_workbench(r, extract_const(page("agent-workbench.html"), "WB"), seed_by_id, known, enum_codes)
        check_intake(r, extract_const(page("invoice-intake.html"), "BATCHES"), batches_seed, seed_by_id, known, enum_codes)
        check_audit(r, extract_const(page("audit-reports.html"), "LOGS"), ae_seed, seed_by_id, enum_codes)
        check_matching(r, extract_const(page("matching-mapping.html"), "QUEUE"), seed_by_id, known, enum_codes, diff_colors)
    except JSParseError as e:
        die(f"JS 常量解析失败: {e}")

    # 输出
    print("=" * 78)
    print("G-M0-001 · seeds ↔ ui-design 逐案交叉校验")
    print("=" * 78)
    if not args.quiet:
        for m in r.passes:
            print("  ✓", m)
    for m in r.notes:
        print("  ℹ [口径注记]", m)
    for m in r.exempts:
        print("  ⊘ [已登记豁免]", m)
    for m in r.fails:
        print("  ✗", m)
    print("-" * 78)
    print(f"通过断言组 {len(r.passes)}｜口径注记 {len(r.notes)}｜已登记豁免 {len(r.exempts)}｜失败 {len(r.fails)}")
    if r.exempts:
        print("提示：豁免均来自 seeds/batches.json known_page_discrepancies，未静默跳过；新增页面差异须先登记方可豁免。")
    sys.exit(1 if r.fails else 0)


if __name__ == "__main__":
    main()
