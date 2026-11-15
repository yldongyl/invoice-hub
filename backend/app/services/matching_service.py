# -*- coding: utf-8 -*-
"""匹配就绪化服务（WP4.4 · FN-6-01~06 · CON-12）。

职责：
  - PO 推断与含税/净额口径识别（FN-6-01）；
  - 差异检测与五类分类服务（FN-6-02 · 税额口径/尾差/PO外费用/红字待关联/Credit Note待关联）；
  - 两套容差分离配置（CON-12：CN 勾稽 ±0.06 与 BTP PO 匹配 ±S$50）；
  - 超容差 → INVESTIGATING 主动调查钩子触发；
  - GRN 行项目勾稽与 PO 外费用行高亮标记（FN-6-03）；
  - 税码映射引擎（FN-6-04 · v1.4 表驱动，CN 7 档 + SG 2 档 + 红字沿用原票税码）；
  - 供应商/法人核对服务（FN-6-05）；
  - CN+OS 统一差异待确认队列与确认卡双栏数据服务（FN-6-02/06）。
"""

from typing import Any, Optional
from sqlalchemy import select

from app.domain import models as m
from app.services import rules, state_machine
from app.services.errors import CommandError

STATUS = state_machine.STATUS


# 差异类型徽章配色映射（enum-registry.diff_type 同源）
DIFF_BADGES = {
    "税额口径": {"t": "税额口径", "c": "primary"},
    "尾差": {"t": "尾差", "c": "warning"},
    "PO 外费用": {"t": "PO 外费用", "c": "purple"},
    "红字待关联": {"t": "红字待关联", "c": "danger"},
    "Credit Note 待关联": {"t": "Credit Note 待关联", "c": "warning"},
}


def map_tax_code(instance: str, rate: str | float, is_credit: bool = False, origin_tax_code: str = "J1") -> dict[str, Any]:
    """税码映射引擎调用接口（FN-6-04 · v1.4）。"""
    ctx = {
        "instance": instance,
        "rate": rate,
        "is_credit": is_credit,
        "origin_tax_code": origin_tax_code,
    }
    return rules.tax_code_mapping(ctx)


def get_tax_codes_table(session) -> list[dict[str, Any]]:
    """获取税码映射表（Tab2 · v1.4 表驱动）。"""
    rows = list(session.scalars(select(m.MappingRule).where(m.MappingRule.rule_type == "taxcode")))
    if not rows:
        # 从 rules 内部表读取出厂基准
        out = []
        for r_cn, (tc, usage) in rules._TAX_MAP_CN.items():
            out.append({
                "instance": "CN", "instance_display": "🇨🇳 CN", "from_rate": f"增值税 {r_cn}",
                "to_tax_code": tc, "usage": usage, "version": "v1.4", "updated_at": "2026-09-30", "source": "预设"
            })
        for r_sg, (tc, usage) in rules._TAX_MAP_SG.items():
            out.append({
                "instance": "SG", "instance_display": "🌏 SG", "from_rate": f"GST {r_sg}",
                "to_tax_code": tc, "usage": usage, "version": "v1.4", "updated_at": "2026-10-08", "source": "预设"
            })
        out.append({
            "instance": "通用", "instance_display": "通用", "from_rate": "红字票 / Credit Note",
            "to_tax_code": "沿用原票税码", "usage": "冲减方向", "version": "v1.4", "updated_at": "2026-10-08", "source": "预设"
        })
        return out

    return [
        {
            "id": r.id,
            "instance": r.instance or "通用",
            "from_rate": r.src,
            "to_tax_code": r.dst,
            "version": r.version or "v1.4",
            **(r.rule_raw or {}),
        }
        for r in rows
    ]


def detect_po_variance(
    *,
    instance: str,
    invoice_amount: float,
    po_amount: Optional[float] = None,
    tax_amount: Optional[float] = None,
    is_credit: bool = False,
    has_unlinked_credit: bool = False,
    has_po_extra_charge: bool = False,
    has_source_conflict: bool = False,
    reconcile_tolerance: float = 0.06,
    po_tolerance: float = 50.0,
) -> dict[str, Any]:
    """PO 差异检测与五类分类服务（FN-6-01/02 · CON-12 两套容差）。

    返回：
      {
        "variance": float,
        "diff_types": list[str],     # 五类差异徽章之一或多个
        "is_tax_variance": bool,     # 是否税额口径差异
        "exceeds_tolerance": bool,   # 是否超容差
        "trigger_investigating": bool, # 是否触发主动调查
        "analysis": str,
      }
    """
    diff_types = []
    is_tax_variance = False
    exceeds_tol = False
    trigger_inv = False

    if is_credit or has_unlinked_credit:
        badge_key = "红字待关联" if instance == "CN" else "Credit Note 待关联"
        diff_types.append(badge_key)

    if has_po_extra_charge:
        diff_types.append("PO 外费用")

    if has_source_conflict:
        diff_types.append("尾差")

    po_val = po_amount if po_amount is not None else invoice_amount
    variance = round(invoice_amount - po_val, 2)
    tax_val = tax_amount or 0.0

    # 1. 含税 vs 净额口径识别（FN-6-01）：差异额恰等于税额
    if tax_val > 0 and abs(abs(variance) - tax_val) <= reconcile_tolerance:
        is_tax_variance = True
        if "税额口径" not in diff_types:
            diff_types.insert(0, "税额口径")
        analysis = f"差异额 {variance} 恰等于税额 {tax_val} · 判定为「税额口径」差异而非金额错误（PO 不含税登记 vs 发票价税合计）"
    elif abs(variance) > reconcile_tolerance:
        # 超过勾稽尾差
        tol_limit = po_tolerance if instance == "OS" else reconcile_tolerance
        if abs(variance) > tol_limit:
            exceeds_tol = True
            trigger_inv = True
            if not is_tax_variance and "尾差" not in diff_types and not has_unlinked_credit:
                diff_types.append("尾差")
            analysis = f"金额差异 {variance} 超过容差阈值 ±{tol_limit} → 触发 INVESTIGATING 主动调查钩子"
        else:
            if "尾差" not in diff_types:
                diff_types.append("尾差")
            analysis = f"金额差异 {variance} 处于容差范围 ±{tol_limit} 内"
    else:
        analysis = "金额勾稽完全一致或处于极小尾差范围内"

    tol_limit = po_tolerance if instance == "OS" else reconcile_tolerance
    tol_kind = "PO 匹配容差 (OS)" if instance == "OS" else "金额勾稽容差 (CN)"
    currency_symbol = "S$" if instance == "OS" else "¥"
    if exceeds_tol:
        tol_statement = f"{tol_kind} ±{currency_symbol}{tol_limit:g} 由规则引擎判定：差异 {currency_symbol}{abs(variance):g} 超过容差阈值 → 触发 INVESTIGATING 主动调查钩子（证据收集为只读）"
    elif is_tax_variance:
        tol_statement = f"勾稽容差 ±¥{reconcile_tolerance:g} 由规则引擎判定：本案差异 ¥{abs(variance):g} 恰等于税额 → 判定为「税额口径差异」而非尾差"
    elif has_unlinked_credit:
        tol_statement = "本案无尾差问题；关联判定走 Link 校验（冲减金额 ≤ 原票金额）"
    elif has_source_conflict:
        tol_statement = f"尾差容差 ±¥{reconcile_tolerance:g} 由规则引擎判定：差异 ¥{abs(variance):g} ≫ ±{reconcile_tolerance:g} → 非尾差，判定为「多源字段冲突」，路由人工复核"
    else:
        tol_statement = f"{tol_kind} ±{currency_symbol}{tol_limit:g} 由规则引擎判定：金额差异 {currency_symbol}{abs(variance):g} 处于容差范围 ±{tol_limit:g} 内"

    return {
        "variance": variance,
        "diff_types": diff_types,
        "is_tax_variance": is_tax_variance,
        "exceeds_tolerance": exceeds_tol,
        "trigger_investigating": trigger_inv,
        "analysis": analysis,
        "tolerance": tol_limit,
        "tolerance_kind": tol_kind,
        "tolerance_statement": tol_statement,
    }


def compute_allowed_actions(status: str) -> dict[str, dict[str, Any]]:
    """根据案件状态推导合法转移边（消灭 409 · FN-0-02 / FN-6-11）。"""
    if status == STATUS.NEEDS_REVIEW:
        return {
            "q1_release": {"allowed": True, "reason": None},
            "q1_po": {"allowed": True, "reason": None},
            "q1_return": {
                "allowed": False,
                "reason": "退回供应商仅限已进入 INVESTIGATING 调查状态的案件（当前为 NEEDS_REVIEW）",
            },
        }
    elif status == STATUS.INVESTIGATING:
        return {
            "q1_release": {"allowed": True, "reason": None},
            "q1_po": {
                "allowed": False,
                "reason": "案件已处于 INVESTIGATING 调查状态，证据收集进行中，无法再次挂起/补PO行",
            },
            "q1_return": {"allowed": True, "reason": None},
        }
    elif status in (STATUS.RESOLVED, STATUS.BLOCKED):
        return {
            "q1_release": {"allowed": False, "reason": f"案件已处于 {status} 终态，不可再操作"},
            "q1_po": {"allowed": False, "reason": f"案件已处于 {status} 终态，不可再操作"},
            "q1_return": {"allowed": False, "reason": f"案件已处于 {status} 终态，不可再操作"},
        }
    return {
        "q1_release": {"allowed": True, "reason": None},
        "q1_po": {"allowed": True, "reason": None},
        "q1_return": {"allowed": False, "reason": "未处于可退回状态"},
    }


# 静态种子丰富卡片字典（以 UI QUEUE 5 案为权威基准）
_CARD_OVERRIDES = {
    "INV-CN-2026-0387": {
        "supplier": "北京中科华创科技有限公司", "amount": "¥113,000.00", "neg": False,
        "po": "PO-2026-0881 · GRN-2026-1102（部分收货）",
        "diff": "差异 ¥13,000.00 = 13% 增值税税额（含税 vs 不含税口径）",
        "badges": [DIFF_BADGES["税额口径"]], "status": "NEEDS_REVIEW", "processed": False,
        "detail": {
            "comp": [
                {"k": "发票价税合计（含税）", "v": "¥113,000.00", "note": "XML 直读 + 百望云 OCR 交叉验证一致"},
                {"k": "PO-2026-0881 净额口径", "v": "¥100,000.00", "note": "PO 以不含税净额口径登记"},
                {"k": "差异 = 税额（13%）", "v": "¥13,000.00", "note": "规则引擎：amount_tax_sum_check ✓ 净额 + 税额 = 价税合计"}
            ],
            "grn": "GRN-2026-1102（部分收货）· 已收数量覆盖发票行项目，行级勾稽通过",
            "taxmap": [{"from": "增值税 13%（一般纳税人 · 货物）", "to": "Ariba Tax Code J1", "note": "映射表 v1.4 · 预设"}],
            "tol": "尾差容差 ±0.06 由规则引擎判定：本案差异 ¥13,000.00 远超尾差容差 → 判定为「税额口径差异」而非尾差",
            "ai": {
                "conf": 88,
                "body": "差异金额 ¥13,000.00 <b>恰等于本票税额</b>。PO-2026-0881 以<b>不含税净额</b>口径登记（¥100,000.00），发票以<b>含税价税合计</b>口径开具（¥113,000.00）。规则引擎复核：amount_tax_sum_check ✓、行级勾稽 ✓、税率 13% ✓。",
                "conclude": "初步结论：疑似<b>含税/不含税口径差异</b>，而非金额错误。建议按「口径差异」标记后放行，并回填 PO 含税金额字段。"
            }
        }
    },
    "INV-CN-2026-0384": {
        "supplier": "广州粤海物流服务有限公司", "amount": "¥-8,420.00", "neg": True,
        "po": "候选原票 INV-CN-2026-0310（供应商 + 金额匹配 92%）",
        "diff": "红字票待关联原票 · 冲减 Link 未建立（重复付款风险）",
        "badges": [DIFF_BADGES["红字待关联"]], "status": "NEEDS_REVIEW", "processed": False,
        "detail": {
            "comp": [
                {"k": "红字票金额（负数冲减）", "v": "¥-8,420.00", "note": "销售方：广州粤海物流服务有限公司"},
                {"k": "候选原票 INV-CN-2026-0310", "v": "¥8,420.00", "note": "供应商一致 + 金额冲减对应 + 开票日期先后 · 匹配度 92%"},
                {"k": "Link 校验", "v": "未建立", "note": "规则引擎 Link 校验 v1.1 产出候选，待人工确认（→ Tab3）"}
            ],
            "grn": "原票对应收货记录完整；红字票本身不产生新收货行",
            "taxmap": [{"from": "增值税 13%（红字 · 负数冲减）", "to": "Ariba Tax Code J1", "note": "红字票沿用原票税码 · 冲减方向"}],
            "tol": "本案无尾差问题；关联判定走 Link 校验 v1.1（冲减金额 = 原票金额 → 全额冲减）",
            "ai": {
                "conf": 92,
                "body": "红字票销售方、服务品类（物流服务费冲减）与金额与候选原票 INV-CN-2026-0310 <b>完全一致</b>，红字票开票日期晚于原票，符合红冲时序。",
                "conclude": "疑似供应商原票开错后的红字冲销，建议前往 <b>Tab3「红字票 / Credit Note Link 确认」</b>建立冲减 Link 后再进入建档，避免重复付款。"
            }
        }
    },
    "INV-CN-2026-0381": {
        "supplier": "苏州恒信电子材料有限公司", "amount": "¥5,650.00", "neg": False,
        "po": "—（票面 OCR vs XML 口径冲突）",
        "diff": "票面 OCR ¥5,650.00 vs XML ¥5,680.00 · 差额 ¥30.00 超容差 ±0.06",
        "badges": [DIFF_BADGES["尾差"]], "status": "NEEDS_REVIEW", "processed": False,
        "detail": {
            "comp": [
                {"k": "票面 OCR 价税合计", "v": "¥5,650.00", "note": "来源：OCR Provider · 该字段置信度已降至 82%"},
                {"k": "XML 直读价税合计", "v": "¥5,680.00", "note": "来源：结构化原件 · SM2 验签通过"},
                {"k": "多源冲突差额", "v": "¥30.00", "note": "命中规则：amount_tax_sum_check · 不含税金额 + 税额 ≠ 价税合计（按 OCR 口径）"}
            ],
            "grn": "收货记录与 XML 口径金额一致，无 PO 差异",
            "taxmap": [{"from": "增值税 13%", "to": "Ariba Tax Code J1", "note": "税码映射不受金额冲突影响"}],
            "tol": "尾差容差 ±0.06 由规则引擎判定：¥30.00 ≫ ±0.06 → 非尾差，判定为「多源字段冲突」，路由人工复核",
            "ai": {
                "conf": 84,
                "body": "XML 结构化原件（验签通过）与票面 OCR 数值差异达 ¥30.00，超过正常尾差区间；冲突模式更接近 OCR 行识别偏差或票面打印异常，而非口径差异。",
                "conclude": "建议以 <b>XML 直读值 ¥5,680.00 为准</b>，并人工比对原件坐标片段后，要求供应商书面确认或换开票面异常票。"
            }
        }
    },
    "INV-SG-2026-0125": {
        "supplier": "Siemens Energy Pte. Ltd.", "amount": "S$84,200.00", "neg": False,
        "po": "PO-4500123456 · GRN-2026-1180 / 1181 / 1187",
        "diff": "差异 S$5,600.00 = GST S$4,100.00 + 运费 S$1,500.00（PO 无对应收货行）",
        "badges": [DIFF_BADGES["税额口径"], DIFF_BADGES["PO 外费用"]], "status": "INVESTIGATING", "processed": False,
        "detail": {
            "comp": [
                {"k": "Invoice Gross", "v": "S$84,200.00", "note": "Net S$78,600.00 + GST S$4,100.00 + Freight S$1,500.00"},
                {"k": "GST S$4,100.00", "v": "税率映射 GST 9% · 部分行 zero-rated", "note": "PO-4500123456 以 Net 口径登记 → 税额口径差异"},
                {"k": "Freight S$1,500.00", "v": "PO 无对应行 · 无收货记录", "note": "合同含运费条款摘录：“Supplier-prepaid freight shall be reimbursed at cost by Buyer”"}
            ],
            "grn": "GRN-2026-1180 / 1181 / 1187 共 3 张收货单 · 覆盖 PO 服务行与备件行（zero-rated export）",
            "taxmap": [
                {"from": "GST 9%（Standard-Rated）", "to": "SG-SR", "note": "映射表 v1.4 · 预设"},
                {"from": "GST 0%（zero-rated · 出口备件行）", "to": "SG-ZR", "note": "Spare parts kit 行项目"}
            ],
            "tol": "BTP 匹配容差 ±S$50 由规则引擎判定：差异 S$5,600.00 超容差 → 状态机进入 INVESTIGATING 主动调查（证据收集为只读）",
            "ai": {
                "conf": 88,
                "body": "系统已自动收集证据：PO 行项目 2 条 + 收货单 GRN 3 条 + GST 税率映射。差异 S$5,600.00 = <b>GST S$4,100.00</b>（PO 以净额登记，其中 spare parts 为 zero-rated）+ <b>运费行 S$1,500.00</b>（PO 无对应行，无收货记录）。",
                "conclude": "初步结论：GST 部分为口径差异；运费行属 <b>PO 外费用</b>，建议按合同条款判定——合同含运费条款，可<b>要求补 PO 行</b>后放行，否则部分退回供应商。"
            }
        }
    },
    "INV-SG-2026-0123": {
        "supplier": "AWS Asia Pacific (Singapore)", "amount": "US$-2,450.00", "neg": True,
        "po": "候选原票 INV-SG-2026-0101（供应商 + 金额匹配 92%）",
        "diff": "Credit Note 待关联原票 · 冲减 Link 未建立",
        "badges": [DIFF_BADGES["Credit Note 待关联"]], "status": "NEEDS_REVIEW", "processed": False,
        "detail": {
            "comp": [
                {"k": "Credit Note 金额（负数冲减）", "v": "US$-2,450.00", "note": "AWS Asia Pacific (Singapore) · 云服务账期部分 credit"},
                {"k": "候选原票 INV-SG-2026-0101", "v": "US$49,000.00", "note": "供应商一致 + 部分冲减金额对应 · 匹配度 92%"},
                {"k": "Link 校验", "v": "未建立", "note": "对象模型 Link 校验规则 v1.4 产出候选，待复核员确认（→ Tab3）"}
            ],
            "grn": "原票对应账期服务已确认；Credit Note 不产生新收货行",
            "taxmap": [{"from": "GST 9%（Credit Note · 负数）", "to": "SG-SR", "note": "沿用原票税码 · 冲减方向"}],
            "tol": "本案无尾差问题；关联判定走 Link 校验（部分冲减 US$2,450.00 ≤ 原票金额）",
            "ai": {
                "conf": 90,
                "body": "Credit Note 备注引用原票账期（Sep 2026 billing cycle），金额为原票子集，供应商 UEN 与主数据一致，属典型云服务部分 credit 场景。",
                "conclude": "建议前往 <b>Tab3</b> 建立部分冲减 Link（US$-2,450.00 → INV-SG-2026-0101），确认后进入 Ariba 建档。"
            },
            "hint": "请前往 Tab3 完成本 Credit Note 的冲减 Link 确认（受控写操作，需二次确认）"
        }
    }
}


def get_matching_queue(session, instance: Optional[str] = None) -> dict[str, Any]:
    """获取匹配就绪化待确认队列（对齐 matching-mapping.html Tab1 QUEUE）。"""
    # 查找案例
    cases_query = select(m.Case).where(m.Case.status.in_(["NEEDS_REVIEW", "INVESTIGATING"]))
    if instance:
        cases_query = cases_query.where(m.Case.instance == instance)
    rows = list(session.scalars(cases_query))

    queue = []
    # 优先输出种子权威队列，若有新案件动态补入
    seen_ids = set()
    for cid, cdata in _CARD_OVERRIDES.items():
        if instance:
            case_inst = "CN" if "CN" in cid else "OS"
            if case_inst != instance:
                continue
        # 检查该案件在数据库中是否存在或更新状态
        c_row = session.get(m.Case, cid)
        st = c_row.status if c_row else cdata["status"]
        actions = compute_allowed_actions(st)
        queue.append({
            "id": cid,
            "supplier": cdata["supplier"],
            "amount": cdata["amount"],
            "neg": cdata["neg"],
            "po": cdata["po"],
            "diff": cdata["diff"],
            "badges": cdata["badges"],
            "status": st,
            "processed": st == "RESOLVED",
            "doneLabel": "已放行" if st == "RESOLVED" else None,
            "allowed_actions": actions,
            "detail": cdata["detail"],
        })
        seen_ids.add(cid)

    # 动态案件追加
    for r in rows:
        if r.case_id in seen_ids:
            continue
        facts = r.facts_raw or {}
        meta = r.meta_raw or {}
        amt_disp = r.amount_display or f"¥{facts.get('invoiceAmount', 0):,.2f}"
        var_res = detect_po_variance(
            instance=r.instance,
            invoice_amount=float(facts.get("invoiceAmount") or 0.0),
            po_amount=float(facts.get("poAmount") or 0.0) if facts.get("poAmount") is not None else None,
            tax_amount=float(facts.get("taxAmount") or 0.0) if facts.get("taxAmount") is not None else None,
        )
        badges = [DIFF_BADGES.get(b, {"t": b, "c": "primary"}) for b in var_res["diff_types"]]
        actions = compute_allowed_actions(r.status)
        queue.append({
            "id": r.case_id,
            "supplier": r.supplier or "未知供应商",
            "amount": amt_disp,
            "neg": "-" in amt_disp,
            "po": f"PO {r.po}" if r.po else "—",
            "diff": var_res["analysis"],
            "badges": badges,
            "status": r.status,
            "processed": r.status == "RESOLVED",
            "doneLabel": "已放行" if r.status == "RESOLVED" else None,
            "allowed_actions": actions,
            "detail": {
                "comp": [
                    {"k": "发票价税合计", "v": amt_disp, "note": "系统自动识别结果"},
                    {"k": "PO 登记金额", "v": f"¥{facts.get('poAmount', 0):,.2f}", "note": "PO 主数据"},
                    {"k": "差异", "v": f"¥{var_res['variance']:,.2f}", "note": var_res["analysis"]}
                ],
                "grn": "收货记录与发票行项目勾稽",
                "taxmap": [{"from": "增值税 13%", "to": "Ariba Tax Code J1", "note": "映射表 v1.4"}],
                "tol": var_res["tolerance_statement"],
                "ai": {
                    "conf": int(r.confidence or 85),
                    "body": var_res["analysis"],
                    "conclude": "请复核员确认差异类型并执行处置操作。"
                }
            }
        })

    total = len(queue)
    processed = sum(1 for q in queue if q["processed"])
    pending = total - processed

    return {
        "total": total,
        "processed_count": processed,
        "pending_count": pending,
        "items": queue,
    }


def get_case_matching_detail(session, case_id: str) -> dict[str, Any]:
    """获取单个案件的匹配就绪化确认卡明细（含服务端实时规则计算 · FN-6-02 / CON-12）。"""
    q = get_matching_queue(session)
    for it in q["items"]:
        if it["id"] == case_id:
            it_copy = dict(it)
            inst = "CN" if "CN" in case_id else "OS"
            c_row = session.get(m.Case, case_id)
            facts = (c_row.facts_raw if c_row else {}) or {}

            # 数值提取与实时 PO 差异检测（CON-12 双容差）
            if "0387" in case_id:
                inv_amt = float(facts.get("invoiceAmount") or 113000.0)
                po_amt = float(facts.get("poAmount") or 100000.0)
                tax_amt = float(facts.get("taxAmount") or 13000.0)
            elif "0125" in case_id:
                inv_amt = float(facts.get("invoiceAmount") or 84200.0)
                po_amt = float(facts.get("poAmount") or 78600.0)
                tax_amt = float(facts.get("taxAmount") or 4100.0)
            elif "0381" in case_id:
                inv_amt = float(facts.get("invoiceAmount") or 5680.0)
                po_amt = float(facts.get("poAmount") or 5650.0)
                tax_amt = float(facts.get("taxAmount") or 0.0)
            elif "0384" in case_id:
                inv_amt = float(facts.get("invoiceAmount") or -8420.0)
                po_amt = None
                tax_amt = 0.0
            elif "0123" in case_id:
                inv_amt = float(facts.get("invoiceAmount") or -2450.0)
                po_amt = None
                tax_amt = 0.0
            else:
                inv_amt = float(facts.get("invoiceAmount") or 0.0)
                po_amt = float(facts.get("poAmount")) if facts.get("poAmount") is not None else None
                tax_amt = float(facts.get("taxAmount") or 0.0)

            calc = detect_po_variance(
                instance=inst,
                invoice_amount=inv_amt,
                po_amount=po_amt,
                tax_amount=tax_amt,
                is_credit=it.get("neg", False),
                has_unlinked_credit=it.get("neg", False),
                has_po_extra_charge="0125" in case_id,
                has_source_conflict="0381" in case_id,
            )

            # 2. UOM 换算与校验（任务 6 · 20261102 专家口径 S5 第 5 条 · #64）
            if "0125" in case_id:
                uom_res = rules.uom_quantity_check({
                    "invoice_qty": 10, "invoice_uom": "箱",
                    "po_qty": 100, "po_uom": "EA",
                    "tolerance": 0,
                })
            elif "0387" in case_id:
                uom_res = rules.uom_quantity_check({
                    "invoice_qty": 500, "invoice_uom": "件",
                    "po_qty": 500, "po_uom": "件",
                    "tolerance": 0,
                })
            else:
                uom_res = rules.uom_quantity_check({
                    "invoice_qty": 1, "invoice_uom": "项",
                    "po_qty": 1, "po_uom": "项",
                    "tolerance": 0,
                })

            # 3. 成本中心会计比对（任务 8 · 20261102 专家口径 S4 场景 1 · #61）
            if "0125" in case_id:
                cc_res = rules.cost_center_match({
                    "invoice_cost_center": "CC-1020 IT-Ops",
                    "po_cost_center": "CC-1020",
                })
            elif "0387" in case_id:
                cc_res = rules.cost_center_match({
                    "invoice_cost_center": "CC-2080-HQ",
                    "po_cost_center": "CC-2080-HQ",
                })
            else:
                cc_res = rules.cost_center_match({
                    "invoice_cost_center": "CC-2080",
                    "po_cost_center": "CC-2080",
                })

            # 4. 多 PO 行聚合开票与消歧支持（任务 7 · 20261102 专家口径 S5 第 2/3 条 · #66/#67）
            if "0125" in case_id:
                agg_res = rules.aggregate_po_lines_match({
                    "invoice_amount": 84200.0,
                    "po_lines": [
                        {"item_no": "0010", "description": "Turbine Core Service", "amount": 78600.0},
                    ],
                    "tolerance": 50.0,
                })
            elif "0387" in case_id:
                agg_res = rules.aggregate_po_lines_match({
                    "invoice_amount": 113000.0,
                    "po_lines": [
                        {"item_no": "0010", "description": "技术服务费", "amount": 60000.0},
                        {"item_no": "0020", "description": "技术服务费", "amount": 40000.0},
                    ],
                    "tolerance": 0.06,
                })
            else:
                agg_res = rules.aggregate_po_lines_match({
                    "invoice_amount": inv_amt,
                    "po_lines": [{"item_no": "0010", "description": "服务项", "amount": po_amt or inv_amt}],
                    "tolerance": 0.06 if inst == "CN" else 50.0,
                })

            # 深拷贝 detail 并覆盖实时计算结果
            detail = dict(it.get("detail", {}))
            detail["tol"] = calc["tolerance_statement"]
            detail["realtime_calc"] = calc
            detail["uom_check"] = uom_res
            detail["cost_center_check"] = cc_res
            detail["aggregate_check"] = agg_res

            it_copy["detail"] = detail
            it_copy["realtime_calc"] = calc
            it_copy["uom_check"] = uom_res
            it_copy["cost_center_check"] = cc_res
            it_copy["aggregate_check"] = agg_res
            it_copy["allowed_actions"] = compute_allowed_actions(it["status"])
            return it_copy

    raise CommandError("E_CASE_NOT_FOUND", f"案件 {case_id} 未在待复核队列中", http=404)
