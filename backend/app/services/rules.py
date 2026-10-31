# -*- coding: utf-8 -*-
"""规则引擎框架（WP1.6 · FN-0-07 + 附录 C + CON-12/05/06）。

口径：
  - 注册制：可调用规则必须能溯源到 rules_catalog.json 条目（rule_id 或 machine_id），
    未注册=缺陷（E_RULE_NOT_REGISTERED）；族级中文标识的机器 id（line_amount_sum_check/
    dedup_business_key/tolerance_check/redline_policy）已由 seed note 授权于 M1 登记回写；
  - 每条规则=纯函数：输入字段上下文 dict → {rule_id, result, note}；不触库、不读时钟以外全局态；
  - 确定性判断只归规则引擎（依赖纪律⑥）：LLM 输出永不写入本层；
  - 本阶段实装与内核相关的 13 条；其余注册条目（tax_rate_13_check、tax_code_mapping、
    po_line_coverage、credit_link_check、gst_rate_sg_check、manual_edit_audit）归属 M3/M4 编排
    与匹配域，调用即报 E_RULE_NOT_IMPLEMENTED——不静默缺席；
  - 容差两套分开配置（CON-12）：reconcile ±0.06（CN 金额勾稽）/ po ±S$50（PO 匹配），
    由调用方从 config_center 注入上下文，规则内不写字面值。
"""

import re
from datetime import date

_EPS = 1e-9   # 十进制金额的二进制浮点表示误差容许（边界语义仍由业务容差值决定）

from app.domain.registry import EnumViolation, get_registry
from app.services.errors import (E_RULE_NOT_IMPLEMENTED, E_RULE_NOT_REGISTERED, CommandError)

# 实装集（P02 WP1.6 点名 13 条 + M3 WP3.1 受理流水线 2 条 + M4 WP4.4 税码映射；机器 id 用 catalog 登记值）
IMPLEMENTED = {
    "amount_tax_sum_check", "amount_sum_check", "line_amount_sum_check",
    "invoice_no_format_check", "date_valid_range", "supplier_master_match",
    "tax_id_checksum", "buyer_entity_match", "currency_iso_check",
    "sg_uen_format_check", "tolerance_check", "redline_policy", "dedup_business_key",
    "non_invoice_doc_filter", "carrier_route_detect",      # M3 WP3.1（FN-1-05②③，v1.1.0 规则目录增补）
    "tax_code_mapping",                                   # M4 WP4.4（FN-6-04，v1.4 表驱动）
}

# —— 校验结果值一律取自 enum-registry.check_result（引用不造词）——

def _res(code: str):
    reg = get_registry()
    reg.validate("check_result", code, where="rule.result")
    return code


PASSED = "PASSED"
NOT_VERIFIED = "NOT_VERIFIED"
AMOUNT_VARIANCE = "AMOUNT_VARIANCE"
FAILED = "FAILED"


def out(rule_id: str, result: str, note: str) -> dict:
    rid = resolve_rule_id(rule_id)
    if rid not in IMPLEMENTED:
        raise CommandError(E_RULE_NOT_IMPLEMENTED,
                           f"规则 {rule_id!r} 已注册未实装（归属 M3/M4，P02 范围纪律）", http=501)
    return {"rule_id": rid, "result": _res(result), "note": note}


_catalog = None


def _catalog_ids() -> dict:
    """catalog 视图：rule_id 与 machine_id 双向归一（族级中文标识经 M1 登记的机器 id 解析）。"""
    global _catalog
    if _catalog is None:
        import json
        from app.domain.registry import SEEDS_DIR
        data = json.loads((SEEDS_DIR / "rules_catalog.json").read_text(encoding="utf-8"))
        m = {}
        for r in data["rules"]:
            mid = r.get("machine_id") or r["rule_id"]
            m[r["rule_id"]] = mid
            m.setdefault(mid, mid)
        _catalog = m
    return _catalog


def resolve_rule_id(rule_id: str) -> str:
    """中文族级标识→机器 id；完全未注册→E_RULE_NOT_REGISTERED（未注册=缺陷）。"""
    cat = _catalog_ids()
    if rule_id in cat:
        return cat[rule_id]
    raise CommandError(E_RULE_NOT_REGISTERED,
                       f"规则 {rule_id!r} 不在 rules_catalog 注册表（未注册=缺陷）", http=500)


def set_catalog_ids(mapping: dict):
    """测试/装载期注入 catalog 视图（rule_id/machine_id→machine_id）。"""
    global _catalog
    _catalog = dict(mapping)


# ────────────────────────────── 金额勾稽类 ──────────────────────────────

def amount_tax_sum_check(ctx: dict) -> dict:
    """CN：净额+税额=价税合计（容差 ±0.06，CON-12 reconcile 套）。"""
    tol = float(ctx["tolerance_reconcile"])
    diff = abs(float(ctx["net"]) + float(ctx["tax"]) - float(ctx["gross"]))
    if diff <= tol + _EPS:
        return out("amount_tax_sum_check", PASSED,
                   f"净额+税额=价税合计（差额 {diff:.4f} ≤ 容差 {tol}）")
    return out("amount_tax_sum_check", FAILED,
               f"净额+税额 ≠ 价税合计（差额 {diff:.4f} 超容差 {tol}）")


def amount_sum_check(ctx: dict) -> dict:
    """OS：Net+GST+Freight=Gross（容差按 reconcile 套；0125 精确勾稽）。"""
    tol = float(ctx["tolerance_reconcile"])
    freight = float(ctx.get("freight") or 0.0)
    diff = abs(float(ctx["net"]) + float(ctx["tax"]) + freight - float(ctx["gross"]))
    if diff <= tol + _EPS:
        return out("amount_sum_check", PASSED, f"Net+GST+Freight=Gross（差额 {diff:.4f}）")
    return out("amount_sum_check", FAILED, f"勾稽不成立（差额 {diff:.4f} 超容差 {tol}）")


def line_amount_sum_check(ctx: dict) -> dict:
    """行级勾稽 Σ行金额=合计（机器 id 由 catalog 登记；OS 行含税额对 Gross 口径）。"""
    tol = float(ctx["tolerance_reconcile"])
    target = float(ctx.get("line_target", ctx["net"]))
    s = sum(float(l.get("amount", 0)) for l in ctx.get("lines") or [])
    diff = abs(s - target)
    if not ctx.get("lines"):
        return out("line_amount_sum_check", NOT_VERIFIED, "无行项目输入，行级勾稽未验证")
    if diff <= tol + _EPS:
        return out("line_amount_sum_check", PASSED, f"Σ行金额=合计（差额 {diff:.4f}）")
    return out("line_amount_sum_check", FAILED, f"Σ行金额 ≠ 合计（差额 {diff:.4f} 超容差 {tol}）")


def tolerance_check(ctx: dict) -> dict:
    """容差判定（两套分开，CON-12）：kind=reconcile（±0.06）/ po（±S$50）。
    边界口径：|diff| ≤ 容差 → 容差内（含恰好等于）；> 容差 → 超出。"""
    kind = ctx.get("kind", "reconcile")
    tol = float(ctx["tolerance_reconcile"]) if kind == "reconcile" else float(ctx["tolerance_po"])
    diff = abs(float(ctx.get("diff", 0.0)))
    within = diff <= tol + _EPS   # 「恰好等于」判容差内（浮点 epsilon，DEC 金额二进制表示误差）
    return out("tolerance_check", PASSED if within else AMOUNT_VARIANCE,
               f"{'勾稽' if kind == 'reconcile' else 'PO 匹配'}容差 ±{tol}：|差异|={diff:g} "
               f"{'≤（容差内，含恰等于）' if within else '>（超出）'}±{tol}")


# ────────────────────────────── 格式/区间类 ──────────────────────────────

def invoice_no_format_check(ctx: dict) -> dict:
    """发票号格式（CON-03 路径 header.invoice_no）：CN 数字 8–20 位（数电票 20/老票 8，
    演示种子为 14 位数字段）；OS 字母数字与连字符组合。"""
    no = str(ctx.get("invoice_no") or "")
    inst = ctx.get("instance", "CN")
    if inst == "CN":
        ok = bool(re.match(r"\d{8,20}\Z", no))
    else:
        ok = bool(re.match(r"[A-Z0-9][A-Z0-9\-]{4,22}[A-Z0-9]\Z", no))
    if ok:
        return out("invoice_no_format_check", PASSED, f"票号格式合规（{inst} 口径，{len(no)} 位）")
    return out("invoice_no_format_check", FAILED, f"票号 {no!r} 不符 {inst} 格式")


def date_valid_range(ctx: dict) -> dict:
    """开票日期有效区间（ISO，[2015-01-01, 今天+1d]；today 可注入 ctx['today'] 保测试确定性）。"""
    raw = str(ctx.get("issue_date") or "")
    today = ctx.get("today") or date.today().isoformat()
    try:
        d = date.fromisoformat(raw)
        lo, hi = date(2015, 1, 1), date.fromisoformat(today)
    except ValueError:
        return out("date_valid_range", FAILED, f"日期不可解析：{raw!r}")
    if lo <= d <= hi:
        return out("date_valid_range", PASSED, f"{raw} 在有效区间内")
    return out("date_valid_range", FAILED, f"{raw} 越出有效区间 [{lo}, {hi}]")


def currency_iso_check(ctx: dict) -> dict:
    """币种 ISO-4217（外部标准，非站内枚举；ISO 4217:2022 alpha-3 大写字母）。"""
    cur = str(ctx.get("currency") or "")
    if re.match(r"[A-Z]{3}\Z", cur):
        return out("currency_iso_check", PASSED, f"ISO-4217 形态合规：{cur}")
    return out("currency_iso_check", FAILED, f"币种 {cur!r} 非 ISO-4217 alpha-3")


def sg_uen_format_check(ctx: dict) -> dict:
    """新加坡 UEN/GST Reg. No 格式（OS 票 seller.tax_id；演示口径 10 位：字母+8数字+字母）。"""
    v = str(ctx.get("tax_id") or "")
    if re.match(r"[A-Z]\d{8}[A-Z]\Z", v):
        return out("sg_uen_format_check", PASSED, f"UEN 形态合规：{v}")
    return out("sg_uen_format_check", FAILED, f"UEN {v!r} 不符 10 位形态（字母+8数字+字母）")


# ────────────────────────────── 主数据/实体类 ──────────────────────────────

def supplier_master_match(ctx: dict) -> dict:
    """供应商主数据匹配（名称+税号 vs SUP 档案；FN-0-07 supplierMatch 判定内容）。"""
    s = ctx.get("supplier") or {}
    if not s.get("master_name"):
        return out("supplier_master_match", NOT_VERIFIED, "无供应商主数据档案输入，未验证")
    name_ok = s.get("name") == s.get("master_name")
    tax_ok = (not s.get("tax_id")) or s.get("tax_id") == s.get("master_tax_id")
    if name_ok and tax_ok:
        return out("supplier_master_match", PASSED,
                   f"供应商名称+税号与 {s.get('master_id', '主数据')} 一致")
    return out("supplier_master_match", FAILED,
               f"与主数据不一致（名称{'✓' if name_ok else '✗'} / 税号{'✓' if tax_ok else '✗'}）")


_CN_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_CN_W = [1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 11, 24, 13, 8, 19, 20, 29]


def _uscc_checksum(code: str):
    """GB32100-2015 校验位；None=结构不合规则无法计算。"""
    if len(code) != 18 or any(c not in _CN_CHARSET for c in code.upper()):
        return None
    tot = sum(_CN_CHARSET.index(code[i]) * _CN_W[i] for i in range(17))
    return _CN_CHARSET[(31 - tot % 31) % 31]


def tax_id_checksum(ctx: dict) -> dict:
    """税号校验位：结构违例 → FAILED；结构合规但校验位不符 → NOT_VERIFIED
    （演示口径：种子为虚构号码，不据以判真伪；正式授权名录校验走 FN-5-02，M3 桩）。"""
    v = str(ctx.get("tax_id") or "")
    if ctx.get("instance", "CN") == "OS":
        return out("tax_id_checksum", NOT_VERIFIED, "海外 Tax ID 走名录校验（FN-5-03），校验位算法不适用")
    expect = _uscc_checksum(v)
    if expect is None:
        return out("tax_id_checksum", FAILED, f"统一社会信用代码 {v!r} 结构违例（18 位/字符集）")
    if expect == v[17].upper():
        return out("tax_id_checksum", PASSED, "18 位结构与 GB32100 校验位一致")
    return out("tax_id_checksum", NOT_VERIFIED,
               f"结构合规、校验位不符（期望 {expect}，实得 {v[17].upper()}）· 演示种子为虚构号码，不判真伪")


def buyer_entity_match(ctx: dict) -> dict:
    """购买方法人实体核对（双实例主体不同，FN-6-05 消费位；实体白名单=ctx 注入，来源
    cases.json 票面 buyer.name 演示口径，正式实体档案属 M4/M5）。"""
    b = ctx.get("buyer") or {}
    allowed = b.get("master_entities")
    if not allowed:
        return out("buyer_entity_match", NOT_VERIFIED, "无购买方实体档案输入，未验证")
    if b.get("name") in allowed:
        return out("buyer_entity_match", PASSED, f"购买方属实例合法实体（{ctx.get('instance')}）")
    return out("buyer_entity_match", FAILED, f"购买方 {b.get('name')!r} 不在实例实体白名单")


# ────────────────────────────── 红线与查重键 ──────────────────────────────

def redline_policy(ctx: dict) -> dict:
    """红线策略（FN-0-02/0-06/5-05）：验签失败→authenticity FAILED→BLOCKED→建档挂起；
    不可被配置绕过（P00 §5）。"""
    auth = ctx.get("authenticity_result")
    if auth == FAILED:
        return out("redline_policy", FAILED,
                   "验真失败命中产品红线：authenticity=FAILED → BLOCKED（建档挂起）；其余校验不中止")
    if auth == NOT_VERIFIED:
        return out("redline_policy", NOT_VERIFIED, "查验未决（超时/授权查验未回）→ 排定重试，不触发红线")
    return out("redline_policy", PASSED, "验真未命中红线")


def dedup_business_key(ctx: dict) -> dict:
    """查重业务键（CON-05 两实例分离，键计算在此、池比对服务本体 M3）：
    CN = invoice_code(null→"") + invoice_no + gross_amount（seller_tax_id 辅助）；
    OS = invoice_no + gross_amount + supplier_id。"""
    inst = ctx.get("instance", "CN")
    gross = ctx.get("gross")
    gross_s = "" if gross is None else f"{float(gross):.2f}"
    if inst == "CN":
        key = f"{ctx.get('invoice_code') or ''}|{ctx.get('invoice_no', '')}|{gross_s}"
        aux = ctx.get("tax_id")
        return out("dedup_business_key", PASSED,
                   f"CN 查重键=发票代码(空→空串)+号码+价税合计：{key}（辅助 seller_tax_id={aux}）")
    key = f"{ctx.get('invoice_no', '')}|{gross_s}|{ctx.get('supplier_id', '')}"
    return out("dedup_business_key", PASSED, f"OS 查重键=号码+价税合计+供应商：{key}")


# ───────────────────────── M3 受理流水线确定性条款（FN-1-05②③ · WP3.1） ─────────────────────────

def non_invoice_doc_filter(ctx: dict) -> dict:
    """②非发票过滤：合同/对账单/报价单/Order Response 特征判定（关键词=版本化受理规则载荷）。
    result 语义（check_result 四值复用）：FAILED=命中非发票特征（该文档不是发票）；
    PASSED=未命中，进入发票受理。附 doc_type 输出命中细分（enum-registry.non_invoice_doc_type）。"""
    reg = get_registry()
    kws = ctx.get("keywords_by_type") or {}
    hay = " ".join(str(ctx.get(k) or "") for k in ("filename", "text_head")).lower()
    # 类型名也过枚举校验（载荷漂移即违例，禁止造词）
    allowed = reg.code_set("non_invoice_doc_type")
    for dtype, words in sorted(kws.items()):
        if dtype not in allowed:
            raise EnumViolation(f"非发票类型 {dtype!r} 不在 non_invoice_doc_type 取值域")
        for w in sorted(words, key=len, reverse=True):        # 长词优先，避免「对账单」被「对账」遮蔽后歧义
            if str(w).lower() in hay:
                return {"rule_id": "non_invoice_doc_filter", "result": FAILED,
                        "note": f"命中 {dtype} 特征关键词「{w}」→ 退回+通知留痕（可申诉重提，FN-1-05②）",
                        "doc_type": dtype}
    return {"rule_id": "non_invoice_doc_filter", "result": PASSED,
            "note": "未命中合同/对账单/报价单/Order Response 特征 → 判定为供应商采购发票候选",
            "doc_type": None}


def carrier_route_detect(ctx: dict) -> dict:
    """③载体检测分流：魔数/结构探测 → carrier_route 枚举（确定性判断；能直读的不送 OCR）。
    附 route 输出 = enum-registry.carrier_route 码值（FN-2-14 recognition_path 子集）。"""
    reg = get_registry()
    kind = ctx.get("kind")
    flags = ctx.get("flags") or {}
    if kind == "corrupt" or not flags.get("header_ok"):
        route, why = "L4_manual_review", "文件头/结构损坏 → 人工分拣并向来源渠道回执索取（FN-1-05③）"
    elif kind == "xml":
        route = "L1_xml_direct"
        why = "XML 原件 → 结构化直读（平台内置解析，免 Provider 免 OCR）"
        if not flags.get("xml_parseable"):
            route, why = "L4_manual_review", "XML 声明但不可解析（结构损坏）→ 人工分拣"
    elif kind == "ofd":
        route = "L1_ofd_direct"
        why = "OFD 原件（zip 容器）→ 解包直读（演示口径：内嵌 XML 抽取；完整解包归 FN-2-01/M4）"
    elif kind == "pdf":
        if flags.get("pdf_encrypt"):
            route, why = "L4_manual_review", "加密 PDF · 无法机读 → 人工分拣，向来源渠道回执索取未加密件"
        elif flags.get("has_text_layer"):
            route, why = "L1_pdf_text", "PDF 原生文本层 → 直读（数据最小外发：不送 OCR）"
        else:
            route, why = "L2_ocr_vlm", "PDF 无文本层（扫描件）→ OCR 路由（M4 前走 stub Provider）"
    elif kind == "image":
        route, why = "L2_ocr_vlm", "扫描/图片载体 → OCR 路由（M4 前走 stub Provider）"
    else:
        route, why = "L4_manual_review", f"未识别载体 {kind!r} → 人工分拣"
    reg.validate("carrier_route", route, where="carrier_route_detect")
    return out("carrier_route_detect", PASSED, why) | {"route": route}


# ───────────────────────── M4 匹配就绪化税码映射（FN-6-04 · v1.4 表驱动） ─────────────────────────

# v1.4 表驱动映射规则表（seeds/taxcodes.json 机器可读化对照）
_TAX_MAP_CN = {
    "13%": ("J1", "一般纳税人 · 货物/加工修理修配"),
    "0.13": ("J1", "一般纳税人 · 货物/加工修理修配"),
    "9%": ("J2", "交通运输/建筑/农产品等"),
    "0.09": ("J2", "交通运输/建筑/农产品等"),
    "6%": ("J3", "现代服务/增值电信等"),
    "0.06": ("J3", "现代服务/增值电信等"),
    "3%": ("J4", "小规模纳税人征收率"),
    "0.03": ("J4", "小规模纳税人征收率"),
    "1%": ("J5", "小规模纳税人优惠征收率"),
    "0.01": ("J5", "小规模纳税人优惠征收率"),
    "0%": ("J6", "出口零税率"),
    "0": ("J6", "出口零税率"),
    "0.00": ("J6", "出口零税率"),
    "免税": ("J7", "免税项目 · 票面标注「免税」"),
}

_TAX_MAP_SG = {
    "9%": ("SG-SR", "Standard-Rated"),
    "0.09": ("SG-SR", "Standard-Rated"),
    "0%": ("SG-ZR", "zero-rated · 出口备件行项目"),
    "0": ("SG-ZR", "zero-rated · 出口备件行项目"),
    "zero-rated": ("SG-ZR", "zero-rated · 出口备件行项目"),
}


def tax_code_mapping(ctx: dict) -> dict:
    """税码映射引擎（FN-6-04 · v1.4 表驱动）：
    CN 七档 (J1~J7) + SG 两档 (SG-SR/SG-ZR) + 红字沿用原票税码。"""
    inst = ctx.get("instance", "CN")
    rate_raw = str(ctx.get("rate") or "").strip()
    is_credit = bool(ctx.get("is_credit") or False)

    if is_credit:
        return out("tax_code_mapping", PASSED,
                   "红字票 / Credit Note 沿用原票税码（冲减方向，FN-6-04）") | {
                   "tax_code": ctx.get("origin_tax_code", "J1"),
                   "usage": "红字票沿用原票税码 · 冲减方向",
                   "version": "v1.4"}

    # 规范化税率字符串
    rate_key = rate_raw.replace("增值税", "").replace("GST", "").strip()
    if rate_key.endswith("%"):
        pass
    else:
        try:
            val = float(rate_key)
            rate_key = f"{int(round(val * 100))}%"
        except ValueError:
            pass

    if inst == "CN":
        hit = _TAX_MAP_CN.get(rate_key) or _TAX_MAP_CN.get(rate_raw)
        if hit:
            code, usage = hit
            return out("tax_code_mapping", PASSED, f"增值税 {rate_raw} → Ariba Tax Code {code}（{usage}）") | {
                "tax_code": code, "usage": usage, "version": "v1.4"
            }
        return out("tax_code_mapping", NOT_VERIFIED, f"未匹配到 CN 预设税码（{rate_raw}），需人工复核") | {
            "tax_code": None, "usage": "未知税率", "version": "v1.4"
        }
    else:  # SG / OS
        hit = _TAX_MAP_SG.get(rate_key) or _TAX_MAP_SG.get(rate_raw)
        if hit:
            code, usage = hit
            return out("tax_code_mapping", PASSED, f"GST {rate_raw} → Tax Code {code}（{usage}）") | {
                "tax_code": code, "usage": usage, "version": "v1.4"
            }
        return out("tax_code_mapping", NOT_VERIFIED, f"未匹配到 SG 预设税码（{rate_raw}），需人工复核") | {
            "tax_code": None, "usage": "未知税率", "version": "v1.4"
        }


RULES = {
    "amount_tax_sum_check": amount_tax_sum_check,
    "amount_sum_check": amount_sum_check,
    "line_amount_sum_check": line_amount_sum_check,
    "invoice_no_format_check": invoice_no_format_check,
    "date_valid_range": date_valid_range,
    "supplier_master_match": supplier_master_match,
    "tax_id_checksum": tax_id_checksum,
    "buyer_entity_match": buyer_entity_match,
    "currency_iso_check": currency_iso_check,
    "sg_uen_format_check": sg_uen_format_check,
    "tolerance_check": tolerance_check,
    "redline_policy": redline_policy,
    "dedup_business_key": dedup_business_key,
    "non_invoice_doc_filter": non_invoice_doc_filter,
    "carrier_route_detect": carrier_route_detect,
    "tax_code_mapping": tax_code_mapping,
}


def run_rule(rule_id: str, ctx: dict) -> dict:
    """规则执行统一入口（编排器/调用方一律经此，确保注册制门禁）。"""
    rid = resolve_rule_id(rule_id)
    fn = RULES.get(rid)
    if fn is None:
        raise CommandError(E_RULE_NOT_IMPLEMENTED,
                           f"规则 {rule_id!r} 已注册未实装（归属 M3/M4，P02 范围纪律）", http=501)
    return fn(ctx)


# ────────────────────────────── 置信度分档（FN-0-06） ──────────────────────────────

def _bands():
    """分档边界派生自 enum-registry.confidence_band 编码文本（≥95% / 80–94% / <80%），
    正则解析数字，代码内不写字面值。返回 [(code, lo, hi)]。"""
    reg = get_registry()
    bands = []
    for item in reg.category_items("confidence_band"):
        code = item["code"]
        nums = [int(x) for x in re.findall(r"\d+", code)]
        if code.startswith("≥"):
            lo, hi = nums[0], 100
        elif code.startswith("<"):
            lo, hi = 0, nums[0] - 1
        else:  # 区间 80–94
            lo, hi = nums[0], nums[1]
        bands.append((code, lo, hi))
    return bands


def confidence_band(percent: int) -> str:
    p = int(percent)
    for code, lo, hi in _bands():
        if lo <= p <= hi:
            return code
    raise EnumViolation(f"置信度 {p} 未落入任何 confidence_band 分档")


def auth_failure_degradation(ctx: dict) -> dict:
    """验签失败全字段降级标注（FN-0-06：数值一致 ≠ 原件可信）：authenticity=FAILED 时，
    对全部字段给出「原件不可信降级」标注（展示层消费，M2；不改识别值与证据本体）。"""
    degraded = (ctx.get("authenticity_result") == FAILED)
    items = [{"field": f, "original": b, "band": confidence_band(b),
              "degrade_note": "原件可信性失败：数值一致 ≠ 原件可信（FN-0-06）" if degraded else None}
             for f, b in (ctx.get("field_bands") or {}).items()]
    return {"rule_id": "auth_failure_degradation", "degraded": degraded, "fields": items}
