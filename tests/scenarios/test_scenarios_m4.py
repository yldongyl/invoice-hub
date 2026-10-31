# -*- coding: utf-8 -*-
"""M4 E2E 场景断言（S-M4-01~05 · 实施规划 §4-M4 验收标准）。

直接桥接并运行 backend/tests/test_scenarios_m4.py 中官方五大场景：
  S-M4-01: "纸质专票"推演与真实路由行为一致（百望云 0.82<0.88→降级诺诺 0.91 通过；推演输出=真实执行日志逐步比对）
  S-M4-02: 停用百望云→数电票路由自动跳过→XML 直读不受影响+留痕 PROVIDER_DISABLED
  S-M4-03: 0387 口径差异：确认卡数据完整→"确认口径差异并放行建议"→差异标记+PO 含税回填→放行→Ariba 沙箱建档→回执 AID-* 归档时间线
  S-M4-04: 0384→0310：Link 候选四项校验→未确认时建档被拦截（反向用例）→确认全额冲减→对象模型+时间线→建档前 Link 校验通过
  S-M4-05: 策略发布：草稿改阈值→推演生效→发布版本递增+diff 入审计→回滚旧版恢复行为
"""

import pytest
from backend.tests.test_scenarios_m4 import (  # noqa: F401
    test_s_m4_01_paper_vat_inference_and_real_routing_consistency,
    test_s_m4_02_disabled_provider_auto_skip_and_xml_direct,
    test_s_m4_03_0387_tax_variance_release_and_filing,
    test_s_m4_04_0384_link_validation_and_pre_filing_interception,
    test_s_m4_05_policy_publish_draft_update_and_rollback,
)

pytestmark = pytest.mark.scenario
