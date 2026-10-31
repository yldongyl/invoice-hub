# -*- coding: utf-8 -*-
"""M3 E2E 场景断言（S-M3-01~05 · 实施规划 §4-M3 验收标准）。

直接桥接并运行 backend/tests/test_scenarios_m3_core.py 中官方五大场景：
  S-M3-01: 受理放行全链留痕（低置信 auto_flow→NEEDS_REVIEW，受控放行→RESOLVED，时间线与审计链 verify）
  S-M3-02: 重复票阻断与双人解除（硬命中 BLOCKED+告警+池排除，批量全跳列因，缺会签 409，会签成功回落 NEEDS_REVIEW）
  S-M3-03: 篡改票阻断（真实验签失败 SM2 FAILED，doc_hold_pending+失败回执归档）
  S-M3-04: 多源冲突修正（0381 路径，冲突事件+降级 82%+NEEDS_REVIEW，人工修正基准行，原值保留+FIELD_EDITED）
  S-M3-05: 受控写五要素逐项缺失拒绝（权限/凭据/本人勾选/处置意见/审计留痕五要素全部单独断言拒绝）
"""

import pytest
from backend.tests.test_scenarios_m3_core import (  # noqa: F401
    test_s_m3_01_upload_pipeline_review_release_full_trace,
    test_s_m3_02_duplicate_blocked_batch_skip_dual_unblock,
    test_s_m3_03_tampered_sm2_failed_receipt_archived,
    test_s_m3_04_multi_source_conflict_edit_adopt_xml,
    test_s_m3_05_five_elements_missing_all_rejected,
)

pytestmark = pytest.mark.scenario
