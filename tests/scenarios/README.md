# tests/scenarios/ · 仓库级 E2E 场景断言

新仓自建（方法论参考旧 ariba-mock S01~S16，代码不复用）：最小场景集 = M3 五条 + M4 五条 + M5 七条（实施规划 §7）；红线回归集（低置信禁自动放行 / 验签失败 BLOCKED / BLOCKED 不可批量放行）为每里程碑必跑。

**执行口径（M3 起）**：场景断言以 pytest 承载于 `backend/tests/test_scenarios_*.py`（`pytestmark = scenario`），
`make test-e2e` = `pytest -m scenario` 一键重放；本目录维护场景台账与里程碑映射。

## 场景台账

| 编号 | 里程碑/工作包 | 场景 | 断言要点 | 实现位置 | 状态 |
|---|---|---|---|---|---|
| S-M3-INT-01 | WP3.1/3.2 | 现场造 seeds 外新 XML → 上传 API 全链 → 新案件号 | 五步状态逐步 DONE 且 detail 可查；案件 RECOGNIZED；时间线四事件序完整；审计链三域 verify 通过；trace 贯穿 | backend/tests/test_scenarios_m3_intake.py::test_s_m3_int_01 | ✅ 通过 |
| S-M3-INT-02 | WP3.1 | 直读零外发 / OCR 路由外发一条 | XML 案件 EgressLog=0；扫描件外发恰 1（stub Provider 台账，source=ocr 不冒充直读） | 同上::test_s_m3_int_02 | ✅ 通过 |
| S-M3-INT-03 | WP3.1/3.2 | 摘要幂等 | 重复提交 409；案件/台账计数不变；既有案件可追（CON-05） | 同上::test_s_m3_int_03 | ✅ 通过 |
| S-M3-INT-04 | WP3.1 | 批次中断→检查点续跑 | 中断态步序留存；resume 识别不重跑（外发计数=1）；二次续跑 noop；不重复受理 | 同上::test_s_m3_int_04 | ✅ 通过 |
| S-M3-INT-05 | WP3.2 | 邮箱/DOX 通道桩手动触发 | 本地投递→批次+案件（CN/OS 发号域各自续起）；非发票 FILTERED+退回 outbox；白名单/参与方不符跳过列明；KPI 联动 | 同上::test_s_m3_int_05 | ✅ 通过 |
| S-M3-01 | WP3.6 | 上传→NEEDS_REVIEW→放行→RESOLVED 全链留痕 | 需合规服务激活 checks/红线（WP3.3+）与受控放行（WP3.4+） | 待建 | ⏳ 后续会话 |
| S-M3-02 | WP3.3 | 重复票（异字节同票面）→DEDUP_BLOCKED→批量放行跳过→解除需双人会签 | 两键硬命中→BLOCKED；批量放行 skipped 含「不可批量放行」列因、processed=0；unblock 缺会签 409；运行期红线告警可被 /v1/alerts 消费 | 同上::test_s_m3_cmp_02_duplicate_blocked_batch_skip | ✅ 通过 |
| S-M3-03 | WP3.3 | 篡改票→SM2 FAILED→BLOCKED→建档挂起→失败回执归档 | 真实 SM2 验签失败；meta.sm2.ok=false+gm-rcpt FAILED 回执在档+doc_hold_pending+验真红线告警+链校验 | 同上::test_s_m3_cmp_03_tampered_sm2_failed_blocked | ✅ 通过 |
| S-M3-04 | WP3.6 | 多源冲突→降级→人工修正原值保留 | 依赖 WP3.3 融合 + WP3.4/3.5 edit_field | 待建 | ⏳ 后续会话 |
| S-M3-05 | WP3.6 | 受控写五要素逐项缺失全拒 | 框架既有回归（test_governed_commands）+ 受理动作专项已覆盖权限/凭据/勾选三项（test_intake_api），审计缺失用例待 WP3.6 | 部分就位 | 🔄 进行中 |

> 纪律：场景须可一键重放（临时库 + tmp 目录 monkeypatch，零真实外呼/零 runtime 污染）；红线回归内嵌于各场景——RECOGNIZED 无自动放行出口由 `test_intake_pipeline::test_recognized_case_has_no_auto_release` 常驻补强。
