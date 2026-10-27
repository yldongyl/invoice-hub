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
| **S-M3-01** | WP3.6 | 上传→流水线→案件→NEEDS_REVIEW→放行→RESOLVED 全链留痕 | 低置信 auto_flow→NEEDS_REVIEW；受控放行→RESOLVED；时间线序 ACTION_RELEASE→STATUS_CHANGE(→RESOLVED)+处置意见入 x+三域链 verify | **test_scenarios_m3_core.py::test_s_m3_01** | ✅ 通过 |
| **S-M3-02** | WP3.6 | 重复票→DEDUP_BLOCKED→批量放行跳过→双人解除 | 硬命中 BLOCKED+告警+池排除（A∈池/B∉池，解除前核证）；批量全跳列因 processed=0；缺会签 409→会签成功回落 NEEDS_REVIEW | **同上::test_s_m3_02**（子集 CMP-02 保留） | ✅ 通过 |
| **S-M3-03** | WP3.6 | 篡改票（0379 路径重放）→SM2 FAILED→BLOCKED→建档挂起→失败回执归档 | 真实验签失败；doc_hold_pending+回执文件 FAILED 在档+SM2_VERIFY_FAILED+验真红线告警+链 verify | **同上::test_s_m3_03**（=CMP-03 同链双挂） | ✅ 通过 |
| **S-M3-04** | WP3.6 | 多源冲突（0381 路径）→事件+降级 82%→人工修正以 XML 为准→原值保留+FIELD_EDITED | 冲突事件+degrade_to 82+NEEDS_REVIEW；edit_field 基准行 5650→5680（原值保留）、OCR 未采信行留存（role 保护）、FIELD_EDITED | **同上::test_s_m3_04** | ✅ 通过 |
| **S-M3-05** | WP3.6 | 受控写五要素逐项缺失→全部拒绝 | 权限①403/凭据②缺+伪造 428/一次性重放 428/勾选③422/必填意见④422/审计注入⑤500+整笔回滚（状态与链计数不变）；含五要素齐备正路径对照 | **同上::test_s_m3_05** | ✅ 通过 |

## 红线回归集（P08 §1.4 · `make test-redline`=pytest -m redline · 每里程碑门禁必跑）

| 编号 | 定义（P08 逐字摘要） | M3 落地 | 状态 |
|---|---|---|---|
| R-01 | 低置信（<80）无任何自动放行路径（代码走查+行为用例） | **暴露并修复**：evaluate 原「NEEDS_REVIEW+全 PASSED→RESOLVED」边未校验置信度红档——补 `_auto_release_floor()`（registry「<80%」解析）闸门（RI-M3-013）；conf70+全 PASSED 终停 NEEDS_REVIEW + 边来源态走查 | ✅ 通过 |
| R-02 | 验签失败→BLOCKED 不可绕过（含配置篡改尝试） | BLOCKED 单人放行 409；红线关联键关闭→发布层 403 E_CONFIG_REDLINE_BYPASS | ✅ 通过 |
| R-03 | BLOCKED 不可批量放行 | 全跳列因+processed=0+状态零变化+无伪造 ACTION_RELEASE 块 | ✅ 通过 |
| R-04 | 错误自动放行率红线告警不可停用 | 停用入口=FN-9-08 管理面（M5）→skip 注记；M3 代偿：告警仅确定性服务生成、Alert 无删除 API | ⏳ 移交 M5 |
| R-05 | LLM 输出永不直接写 checks/status/字段值 | backend 代偿（agent 层随 M5）：edit_field/派生源码无 checks_raw+checks 键集恒四槽+依赖纪律 grep 常驻 | ✅ 通过（子集） |
| R-06 | 写操作无审计记录→测试失败（双写完整性） | append_block 注入断链→release/hold/claim 三类 500 E_AUDIT_WRITE_FAILED+回滚（状态/链计数不变） | ✅ 通过（3 参数化） |

> 纪律：场景须可一键重放（临时库 + tmp 目录 monkeypatch，零真实外呼/零 runtime 污染）；
> `make test-e2e` 现含 12 条（INT-01~05 + CMP-02~03 + **S-M3-01~05 官方五场景**），连续两跑 12/12；
> 失败信息规范（P08 §2）：`expect()`/`rl()` 统一输出「编号+断言点+期望/实际+关联 FN」；
> unit/contract 两标记对存量测试的全量铺记属 P08 测试体系总包，登记移交（M3 自检 §16）。
> 常驻红线补强：RECOGNIZED 无自动放行出口另由 `test_intake_pipeline::test_recognized_case_has_no_auto_release` 长期覆盖。
