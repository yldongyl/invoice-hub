# -*- coding: utf-8 -*-
"""受理 KPI 聚合（WP3.2 · FN-1-09 顶部统计条）。

口径（M2 dashboard 同纪律：快照源+库内真算+差异登记）：
  - baseline 段=intake 页锚点原值（channels.json today_counters/kpi_baseline，页面↔API↔seeds 三方同源）；
  - runtime 段=运行期实算：今日批次文件（FileIntake×Batch）按渠道计数、过滤细分（doc_type）、
    待人工分拣（disposition=MANUAL_SORT，含加密件判定=carrier 文案「加密」）、成功率（受理登记成功/接入总量）、
    时延（accepted_ts→digest_ts，秒；均值+P95，不含识别耗时）与分时序列；
  - merged 段=页面渲染值（baseline+runtime 合并）；统计口径须与 audit Tab2 报表一致的约束在 M5 对账。
"""

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select

from app.domain import models as m


def _today() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def _latency_seconds(row: m.FileIntake) -> float | None:
    if not (row.accepted_ts and row.digest_ts):
        return None
    try:
        a = datetime.fromisoformat(row.accepted_ts)
        d = datetime.fromisoformat(row.digest_ts)
        return max(0.0, (d - a).total_seconds())
    except ValueError:
        return None


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    import math
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


def compute(session, *, instance: str | None = None) -> dict:
    meta = session.get(m.SeedMeta, "intake_kpi_baseline")
    base = meta.payload if meta else {}
    b_kpi = base.get("kpi_baseline") or {}
    b_chan = base.get("today_counters") or {}
    today = _today()

    rows = session.scalars(select(m.FileIntake)).all()
    bmap = {b.batch_id: b for b in session.scalars(select(m.Batch))}
    rt_files = [r for r in rows if bmap.get(r.batch_id) and
                (bmap[r.batch_id].created_ts or "").startswith(today) and
                (instance is None or bmap[r.batch_id].instance == instance)]
    by_channel = defaultdict(int)
    filt = defaultdict(int)
    manual = 0
    encrypted = 0
    accepted = failed = 0
    lats: list[float] = []
    hourly = defaultdict(int)
    for r in rt_files:
        ch = bmap[r.batch_id].channel
        by_channel[ch] += 1
        if r.doc_type:
            filt[r.doc_type] += 1
        if r.disposition == "MANUAL_SORT":
            manual += 1
            if "加密" in (r.note or ""):
                encrypted += 1
        if r.disposition == "ACCEPTED":
            accepted += 1
        if r.disposition == "FAILED":
            failed += 1
        lat = _latency_seconds(r)
        if lat is not None:
            lats.append(lat)
            hourly[(r.accepted_ts or "")[11:13]] += 1

    total_in = len(rt_files)
    # 成功率口径（FN-1-09「受理登记成功/接入总量」）：ACCEPTED 与 FILTERED 均为受理处置成功，
    # 仅 FAILED（损坏/异常未登记）计失败——退回非失败。
    success_rate = round((accepted + len(filt)) / total_in * 100, 1) if total_in else None
    avg_lat = round(sum(lats) / len(lats), 1) if lats else None

    merged_daily = int(b_kpi.get("daily_received_total", 0)) + total_in
    merged_chan = {ch: int((b_chan.get(ch) or {}).get("received", 0)) + by_channel.get(ch, 0)
                   for ch in ("供应商邮箱", "API 集成", "门户上传", "SAP DOX")}
    merged_filt = {k: int((b_kpi.get("filtered_by_doc_type") or {}).get(k, 0)) + v
                   for k, v in sorted(filt.items())}
    for k, v in (b_kpi.get("filtered_by_doc_type") or {}).items():
        merged_filt.setdefault(k, v)
    merged_manual = int((b_kpi.get("manual_sort_pending") or {}).get("total", 0)) + manual
    merged_enc = int((b_kpi.get("manual_sort_pending") or {}).get("encrypted_pdf", 0))
    # 运行期成功率口径优先（有运行数据时给真算值；无运行数据回落页面锚点 98.7）
    rate = success_rate if total_in else b_kpi.get("success_rate_pct")
    series = [dict(x) for x in (b_kpi.get("hourly_series") or [])]
    for h, c in sorted(hourly.items()):
        nxt = next((x for x in series if x["hour"] == h), None)
        if nxt:
            nxt["count"] += c
        else:
            series.append({"hour": h, "count": c})

    return {
        "instance": instance,
        "baseline": {"today_counters": b_chan, "kpi": b_kpi,
                     "caliber_note": "intake 页锚点（v1.2-candidate 演示样例口径）；运行期真算见 runtime 段"},
        "runtime": {
            "date": today, "files_in": total_in, "by_channel": dict(by_channel),
            "filtered_by_doc_type": dict(filt),
            "manual_sort_pending": manual, "encrypted_pdf_in_manual": encrypted,
            "accepted": accepted, "failed": failed,
            "success_rate_pct": success_rate,
            "avg_latency_s": avg_lat, "p95_latency_s": round(_p95(lats), 1) if lats else None,
            "hourly": {k: v for k, v in sorted(hourly.items())},
        },
        "merged": {
            "daily_received_total": merged_daily,
            "by_channel": merged_chan,
            "filtered_by_doc_type": merged_filt,
            "manual_sort_pending": {"total": merged_manual, "encrypted_pdf": merged_enc},
            "success_rate_pct": rate,
            "avg_latency_s": avg_lat if lats else b_kpi.get("avg_latency_s"),
            "p95_latency_s": round(_p95(lats), 1) if lats else b_kpi.get("p95_latency_s"),
            "hourly_series": series,
            "as_of": datetime.now(timezone.utc).astimezone().strftime("%H:%M"),
        },
        "calibers": {
            "success_rate": "受理登记成功 / 接入总量（FN-1-09）",
            "latency": "接入 → 摘要登记，不含识别耗时（FN-1-09）",
        },
    }
