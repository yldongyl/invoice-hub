# -*- coding: utf-8 -*-
"""断点续跑重试任务（WP1.3 钩子 · FN-0-02/0-10：查验超时→NOT_VERIFIED→单独排定重试，不重跑识别）。

演示口径（P00 §6）：本模块只登记任务并给出下次执行时刻（指数退避口径来自 config.sla_targets：
queue_callback_retry_max=5）；真实异步消费者与队列面板属 M3/FN-9-07。
"""

from datetime import datetime, timedelta, timezone

from app.domain import models as m
from app.services.audit_chain import now_iso


def next_run_at(minutes: int) -> str:
    return (datetime.now(timezone.utc).astimezone() + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def enqueue_verify_retry(session, case_id: str, *, attempt: int = 0, backoff_minutes: int = 5,
                         note: str | None = None, commit: bool = True) -> m.VerifyRetryTask:
    """排定「仅查验步骤」重试任务（step 固定 verify_auth：断点续跑只重试相关步骤，识别不重跑）。"""
    task = m.VerifyRetryTask(case_id=case_id, step="verify_auth", attempts=attempt,
                             next_run_at=next_run_at(backoff_minutes), state="queued",
                             note=note or "授权查验超时重试（断点续跑钩子 · 演示口径队列）")
    session.add(task)
    if commit:
        session.commit()
    else:
        session.flush()
    return task
