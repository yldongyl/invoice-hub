# -*- coding: utf-8 -*-
"""SM2 / 国密验签服务（WP3.3 · FN-5-01）。

口径（P00 §6 桩边界）：
  - **算法真实**：gmssl 纯 Python SM2（SM3 摘要 + 签名/验签）对票面规范化内容真实计算；
  - **证书链模拟**：演示 CA 固定密钥对+序列（正式=证书链管理 FR-L1-05 阶段一 + KMS，TODO(FN-9-10)）；
    本服务只认演示 CA 序列；运行期新案件走真实验签，seeds 预置案件（Signature 为展示文案）不经本链路；
  - PASS / FAILED 均产生回执 gm-rcpt-NNNN（issuer 发号+id_format 自校验）并**随案归档**
    （runtime/gm-receipts/ 落盘 + 案件 meta.sm2 + 时间线 SM2_VERIFY / SM2_VERIFY_FAILED + 审计块）；
  - FAILED → authenticity=FAILED 由合规编排写入（红线 → BLOCKED 走 orchestrator/state_machine 既有唯一通道）；
    **数值勾稽一致 ≠ 原件可信**（FN-0-06/5-01）——本服务只回答签名有效性；
  - 演示口径：失败回执文件可用于对供应商追责与司法取证（注记，不外呼）。
"""

import json
import re
from pathlib import Path

from app.domain import models as m
from app.services import state_machine
from app.services.audit_chain import append_block, now_iso
from app.services.errors import CommandError
from app.services.issuer import next_gm_rcpt

REPO_ROOT = Path(__file__).resolve().parents[3]
GM_RECEIPT_DIR = REPO_ROOT / "runtime" / "gm-receipts"

# —— 演示 CA（模拟证书链）：固定密钥对；正式实现=CA 证书链 + KMS（TODO(FN-9-10 / FR-L1-05)）——
DEMO_CA_SERIAL = "DEMO-CA-SM2-0001（模拟证书链 · 演示口径）"
_DEMO_PRIVATE = "00B9AB0B828FF68872F31566BCCAAB3A396954B0B7CE309768488DCD7FB36633"

_SIG_RE = re.compile(r"<Signature[^>]*>(.*?)</Signature>", re.S)


def _keypair():
    from gmssl import sm2
    pub = sm2.CryptSM2(public_key="", private_key=_DEMO_PRIVATE)._kg(
        int(_DEMO_PRIVATE, 16), sm2.default_ecc_table["g"])
    return sm2.CryptSM2(public_key=pub, private_key=_DEMO_PRIVATE), pub


def _canonical(text: str) -> bytes:
    """签名输入规范化：剥离 Signature 节点 + 去空白（确定性，不含签名自身）。"""
    body = _SIG_RE.sub("", text)
    return re.sub(r">\s+<", "><", body).strip().encode("utf-8")


def _digest(text: str) -> bytes:
    from gmssl.sm3 import sm3_hash
    from gmssl.func import bytes_to_list
    return bytes.fromhex(sm3_hash(bytes_to_list(_canonical(text))))


def sign_demo(text: str) -> str:
    """演示 CA 对票面内容签名（受理侧票据生成器/走查样例使用；正式=供应商电子签章）。

    确定性 k=内容摘要派生（RFC6979 同思路演示简化）：**同文必得同签**——
    保证「同文件重复提交同 SHA-256」的摘要幂等断言成立（随机 k 会使字节漂移）。
    """
    import hashlib
    kp, _pub = _keypair()
    rnd = hashlib.sha256(_digest(text)).hexdigest()[:32]
    try:
        sig = kp.sign(_digest(text), rnd)
    except Exception as e:  # pragma: no cover
        raise CommandError("E_SM2_SIGN", f"演示签名失败：{e}", http=500) from e
    return f"SM2DEMO:{sig}::{DEMO_CA_SERIAL}"


def attach_signature(text: str) -> bytes:
    """在闭合根标签前嵌入演示签名（样例件生成用）。"""
    sig = sign_demo(text)
    node = f"<Signature alg=\"SM2\">{sig}</Signature>"
    for close in ("</EInvoice>", "</Invoice>"):
        if close in text:
            return text.replace(close, f"  {node}\n" + close).encode("utf-8")
    return text.rstrip().rstrip(">").rstrip().encode("utf-8")  # pragma: no cover


def verify(text: str) -> dict:
    """真实 SM2 验签：返回 {verifiable, ok, reason}。无 Signature 节点=不适用。"""
    hit = _SIG_RE.search(text)
    if not hit:
        return {"verifiable": False, "ok": None, "reason": "票面无 Signature 节点 · 验签不适用"}
    raw = hit.group(1).strip()
    sig = re.match(r"SM2DEMO:([0-9a-fA-F]{128})::(.+)$", raw)
    if not sig:
        return {"verifiable": True, "ok": False,
                "reason": "Signature 内容非机器可验（seeds 展示口径）或格式非法 → 验签 FAILED"}
    if DEMO_CA_SERIAL not in sig.group(2):
        return {"verifiable": True, "ok": False, "reason": "证书链验证失败：非演示 CA 序列（模拟链）"}
    kp, _pub = _keypair()
    ok = bool(kp.verify(sig.group(1), _digest(text)))
    return {"verifiable": True, "ok": ok,
            "reason": "SM2 验签通过 · 证书链有效（演示 CA）" if ok
            else "SM2 验签失败：票面内容与签名不符（篡改/替换检出）"}


def run_sm2(session, case: m.Case, file_text: str | None) -> dict | None:
    """对运行期案件执行验签+回执归档；返回 {ok, receipt_no, reason}；不适用返回 None。"""
    if file_text is None:
        return None
    res = verify(file_text)
    if not res["verifiable"]:
        return None
    ok = bool(res["ok"])
    rcpt = next_gm_rcpt(session)
    GM_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    receipt = {
        "receipt_no": rcpt, "case_id": case.case_id, "alg": "SM2", "result": "PASS" if ok else "FAILED",
        "cert_serial": DEMO_CA_SERIAL, "reason": res["reason"], "t": now_iso(),
        "original_sha256": (case.file_raw or {}).get("sha256"),
        "note": ("随案归档 · 不可篡改（演示 CA 链 · 模拟证书链，TODO(FN-9-10/FR-L1-05)）"
                 + ("；失败回执可用于对供应商追责与司法取证（FN-5-01，演示口径不外呼）" if not ok else "")),
    }
    (GM_RECEIPT_DIR / f"{rcpt}.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    state_machine.set_meta(case, sm2={"ok": ok, "text": res["reason"], "receipt_no": rcpt})
    state_machine._sync_meta(session, case)
    act = "SM2_VERIFY" if ok else "SM2_VERIFY_FAILED"
    v = state_machine.component_version(session, "gm-verify")
    state_machine.append_case_event(
        session, case, a="provider", act=act,
        d=f"SM2 国密验签 {'PASS' if ok else 'FAILED'}（回执 {rcpt} 归档）",
        x=res["reason"] + ("· 数值勾稽一致 ≠ 原件可信（FN-5-01）" if ok else "· → authenticity FAILED 红线"),
        v=v, commit=False)
    append_block(session, ts=now_iso(), trace=case.trace_id, actor="provider", act=act,
                 cs=case.case_id, from_state="票面规范化 SM3 摘要", to_state=f"{'PASS' if ok else 'FAILED'} · {rcpt}",
                 note=receipt["note"], op=v, category="verify", commit=False)
    session.commit()
    return {"ok": ok, "receipt_no": rcpt, "reason": res["reason"]}
