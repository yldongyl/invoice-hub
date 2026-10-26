# -*- coding: utf-8 -*-
"""编号发号器（WP1.7 · FN-0-13）。

分域递增计数（IdCounter 表），域键：
  case:CN / case:SG（实例域案件号 INV-{CN|SG}-{YYYY}-{NNNN}，CON-04）；
  batch:{instance}:{YYYYMMDD}（批次号 BT-YYYYMMDD-NNN，分日重置）；
  gm_rcpt（验签回执 gm-rcpt-NNNN，全域递增）；
  qa:{YYYY}-W{WW}（抽检批次 QA-YYYY-Wnn-NN，分周）；anno:{YYYY}（标注任务 ANNO-YYYY-NNNN，分年）。
每次发号结果一律对照 contracts/enum-registry.json 的 id_format pattern 自校验（不硬编码格式）。
seed 装载时按现存数据播种各域现值（seed_counters_from_data），保证「分实例域递增」从演示基线续起。

trace ID 为随机 8hex（非序列），本模块统一生成并 pattern 校验；audit_chain/state_machine 经此入口取号。
"""

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select

from app.domain import models as m
from app.domain.registry import get_registry
from app.services.errors import CommandError


def _pattern(domain_code: str) -> str:
    return get_registry().id_pattern(domain_code)


def _check(code: str, value: str):
    if not re.match(_pattern(code), value):
        raise CommandError("E_ISSUER_PATTERN", f"发号结果 {value!r} 不符编号规则 {code}")
    return value


def _bump(session, domain: str) -> int:
    row = session.get(m.IdCounter, domain)
    if row is None:
        row = m.IdCounter(domain=domain, seq=0,
                          updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        session.add(row)
        session.flush()
    row.seq += 1
    row.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return row.seq


# 实例 → 案件号段（CON-04：CN 实例=CN 段，海外实例=SG 段）
_INSTANCE_TO_SEGMENT = {"CN": "CN", "OS": "SG"}


def next_case_no(session, instance: str, year: int) -> str:
    seg = _INSTANCE_TO_SEGMENT.get(instance)
    if seg is None:
        raise CommandError("E_ISSUER_DOMAIN", f"实例 {instance!r} 无案件号段映射（契约 instance 枚举）")
    n = _bump(session, f"case:{seg}")
    return _check("案件号", f"INV-{seg}-{year}-{n:04d}")


def next_batch_no(session, instance: str, date: str | None = None) -> str:
    d = date or datetime.now(timezone.utc).strftime("%Y%m%d")
    n = _bump(session, f"batch:{instance}:{d}")
    return _check("批次号", f"BT-{d}-{n:03d}")


def next_gm_rcpt(session) -> str:
    n = _bump(session, "gm_rcpt")
    return _check("验签回执", f"gm-rcpt-{n:04d}")


def next_qa_batch(session, year: int, week: int, seq: int | None = None) -> str:
    n = seq if seq is not None else _bump(session, f"qa:{year}-W{week:02d}")
    return _check("抽检批次", f"QA-{year}-W{week:02d}-{n:02d}")


def next_anno_task(session, year: int) -> str:
    n = _bump(session, f"anno:{year}")
    return _check("标注任务", f"ANNO-{year}-{n:04d}")


def new_trace_id() -> str:
    tid = f"tr-{secrets.token_hex(4)}"
    return _check("trace ID", tid)


# ───────────────────────── seed 播种 ─────────────────────────

def seed_counters_from_data(session, *, case_ids: list[str], batch_ids: list[str],
                            receipt_nos: list[str]) -> int:
    """从已装载种子推各域现值（幂等：重建表后重播；不越过现存最大值）。

    批次域键含实例（batch:{instance}:{date}）；seed 批次不携实例维度，故按日最大值
    同时播种 CN/OS 两域（演示口径：发号绝不与既有批次号碰撞）。
    """
    counters: dict[str, int] = {}
    for cid in case_ids:
        seg = cid[4:6]
        counters[f"case:{seg}"] = max(counters.get(f"case:{seg}", 0), int(cid.split("-")[-1]))
    day_max: dict[str, int] = {}
    for bid in batch_ids:
        _, d, seq = bid.split("-")
        day_max[d] = max(day_max.get(d, 0), int(seq))
    for d, mx in day_max.items():
        for inst in ("CN", "OS"):
            counters[f"batch:{inst}:{d}"] = mx
    for rc in receipt_nos:
        counters["gm_rcpt"] = max(counters.get("gm_rcpt", 0), int(rc.split("-")[-1]))
    n = 0
    for domain, seq in counters.items():
        session.add(m.IdCounter(domain=domain, seq=seq, updated_at="seed-loader"))
        n += 1
    session.flush()
    return n
