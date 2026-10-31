# tests/scenarios/ · 仓库级 E2E 场景断言（P08 §1.3）

新仓自建（方法论参考旧 ariba-mock S01~S16，代码不复用）：完整场景集 = **17 条**（M3 五条 + M4 五条 + M5 七条，实施规划 §7 与 P08 §1.3）；红线回归集（R-01~R-06）为每里程碑必跑门禁。

**执行口径**：场景断言以 pytest 承载于 `tests/scenarios/` 与 `backend/tests/test_scenarios_*.py`（`pytestmark = pytest.mark.scenario`），
`make test-e2e` = `pytest -m scenario` 一键全量重放；本文件维护 17 条官方场景台账与断言要点。

## 17 条官方 E2E 场景台账

| 编号 | 里程碑/工作包 | 场景名称 | 核心断言要点 | 实现位置 | 状态 |
|---|---|---|---|---|---|
| **S-M3-01** | WP3.6 | 上传→流水线→案件→NEEDS_REVIEW→放行→RESOLVED 全链留痕 | 低置信 auto_flow→NEEDS_REVIEW；受控放行→RESOLVED；时间线序 ACTION_RELEASE→STATUS_CHANGE(→RESOLVED)+处置意见入 x+三域链 verify | `test_scenarios_m3.py::test_s_m3_01_*` | ✅ 通过 |
| **S-M3-02** | WP3.6 | 重复票→DEDUP_BLOCKED→批量放行跳过→双人解除 | 硬命中 BLOCKED+告警+池排除（A∈池/B∉池，解除前核证）；批量全跳列因 processed=0；缺会签 409→会签成功回落 NEEDS_REVIEW | `test_scenarios_m3.py::test_s_m3_02_*` | ✅ 通过 |
| **S-M3-03** | WP3.6 | 篡改票（0379 路径重放）→SM2 FAILED→BLOCKED→建档挂起→失败回执归档 | 真实验签失败；doc_hold_pending+回执文件 FAILED 在档+SM2_VERIFY_FAILED+验真红线告警+链 verify | `test_scenarios_m3.py::test_s_m3_03_*` | ✅ 通过 |
| **S-M3-04** | WP3.6 | 多源冲突（0381 路径）→事件+降级 82%→人工修正以 XML 为准→原值保留+FIELD_EDITED | 冲突事件+degrade_to 82+NEEDS_REVIEW；edit_field 基准行 5650→5680（原值保留）、OCR 未采信行留存（role 保护）、FIELD_EDITED | `test_scenarios_m3.py::test_s_m3_04_*` | ✅ 通过 |
| **S-M3-05** | WP3.6 | 受控写五要素逐项缺失→全部拒绝 | 权限①403/凭据②缺+伪造 428/一次性重放 428/勾选③422/必填意见④422/审计注入⑤500+整笔回滚（状态与链计数不变）；含五要素齐备正路径对照 | `test_scenarios_m3.py::test_s_m3_05_*` | ✅ 通过 |
| **S-M4-01** | WP4.7 | "纸质专票"推演与真实路由行为一致 | 百望云 0.82 < 0.88→降级诺诺 0.91 通过；推演输出与真实执行日志逐步比对完全一致，含时延与成本字段 | `test_scenarios_m4.py::test_s_m4_01_*` | ✅ 通过 |
| **S-M4-02** | WP4.7 | 停用百望云→数电票路由自动跳过 | 停用 Provider 自动 skip；XML 直读不受影响；审计链留痕 PROVIDER_DISABLED | `test_scenarios_m4.py::test_s_m4_02_*` | ✅ 通过 |
| **S-M4-03** | WP4.7 | 0387 口径差异确认放行建档 | 确认卡数据完整→"确认口径差异并放行建议"→差异标记+PO 含税回填→受控放行→Ariba 沙箱建档→回执 AID-* 归档案件时间线 | `test_scenarios_m4.py::test_s_m4_03_*` | ✅ 通过 |
| **S-M4-04** | WP4.7 | 0384→0310 Link 确认与拦截 | Link 候选四项校验→未确认时建档被拦截（反向用例 409 E_LINK_UNCONFIRMED）→确认全额冲减→对象模型+时间线→建档前 Link 校验通过 | `test_scenarios_m4.py::test_s_m4_04_*` | ✅ 通过 |
| **S-M4-05** | WP4.7 | 策略发布与旧版安全回滚 | 草稿改阈值→推演生效→发布版本递增+diff 入不可篡改审计链→一键回滚旧版恢复历史路由行为 | `test_scenarios_m4.py::test_s_m4_05_*` | ✅ 通过 |
| **S-M5-01** | WP5.7 | 红线告警关闭拦截+留痕 | 向 P0 红线告警发送关闭请求，被 HTTP 403 强制拦截拒绝，开关回弹保持开启，尝试行为写入不可篡改审计链 | `test_scenarios_m5.py::test_s_m5_01_*` | ✅ 通过 |
| **S-M5-02** | WP5.7 | 配置发布→行为变化→回滚恢复 | 配置中心发布新阈值（0.85→0.90）使得 86% 置信度案件流转为 NEEDS_REVIEW（低置信），回滚后系统行为恢复基线 | `test_scenarios_m5.py::test_s_m5_02_*` | ✅ 通过 |
| **S-M5-03** | WP5.7 | Agent 三意图真实工具链 | 蓝橙标分离+免责声明+工具名+只读卡唤起（带未修改标记），对话全程零写事件断言通过 | `test_scenarios_m5.py::test_s_m5_03_*` | ✅ 通过 |
| **S-M5-04** | WP5.7 | MCP 枚举 6 工具+写工具缺 token 拒绝 | tools/list 发现 6 工具与契约 100% 一致；写工具缺 confirm_token 返回 428；agent 与 mcp 底层工具层同源 | `test_scenarios_m5.py::test_s_m5_04_*` | ✅ 通过 |
| **S-M5-05** | WP5.7 | 审计导出自入链头+链校验全通过 | 自审计事件 AUDIT_EXPORT 写入链头，链头块高 blk# 严格递增断言通过，链校验全域通过 | `test_scenarios_m5.py::test_s_m5_05_*` | ✅ 通过 |
| **S-M5-06** | WP5.7 | 标注回流→沉淀规则→规则生效 | 人工修正样本自动入队（真实错误优先），创建任务并流转至已完成，规则沉淀入 catalog，规则引擎实跑通过 | `test_scenarios_m5.py::test_s_m5_06_*` | ✅ 通过 |
| **S-M5-07** | WP5.7 | 抽检异常→冻结自动放行联动 | 周期抽检发现原件摘要异常，自动触发熔断，联动冻结自动放行，违例记录入不可篡改审计链 | `test_scenarios_m5.py::test_s_m5_07_*` | ✅ 通过 |

> 纪律：所有场景必须可在临时库中一键可重放（零真实外部网络强依赖，零测试数据污染）；
> `make test-e2e` 执行全量 17 条 E2E 场景断言；
> 失败信息规范（P08 §2）：包含「场景名 + 断言点 + 期望/实际 + 关联 FN 编号」。
