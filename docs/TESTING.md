# invoice-hub · 测试体系架构与规范说明（P08 · FN-A-08）

> **单一事实源与治理总纲**：按细化功能清单 `FN-A-08`（三层契约测试）与《实施规划》§7 建立完整五层测试体系：契约层、单元测试最小集、E2E 场景断言、红线回归集与一致性校验工具。测试数据一律来自 `seeds/`（禁止另造平行数据集，防止口径漂移）。

---

## 1. 测试分层架构

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        invoice-hub 完整测试体系                         │
├────────────────────────────────────────────────────────────────────────┤
│ 1. 契约测试（FN-A-08）                                                 │
│    ├── 结构层：JSON Schema 编译 (Draft 2020-12) / openapi.yaml 规范 lint │
│    ├── 语义层：核心 API 响应 Schema 校验 / 枚举一致性 / 正则编号规则 / 流转合法性 │
│    └── 版本兼容层：CHANGELOG 账本审计 / v1 冻结破坏性变更检测 (Breaking Detector) │
├────────────────────────────────────────────────────────────────────────┤
│ 2. 单元测试最小集（Domain + Services · 覆盖率 ≥ 80%）                    │
│    ├── 状态机：六条流转规则逐条 / 认领子态不扩状态 / 双人会签解除拦截            │
│    ├── 审计哈希链：链校验通过 / 篡改定位 / 导出自入链头 / WORM 禁止 update/del  │
│    ├── 受控写框架：五要素逐项缺失拒绝 / 批量含 BLOCKED 跳过明细 / 处置意见必填  │
│    ├── 人工修正字段：原因必填 / source=manual / 置信度 1.0 / raw_text 追溯 / 审计 │
│    ├── 规则引擎：附录 C 规则正反用例 / 两套容差 (±0.06 / ±S$50) / 验签失败降级   │
│    ├── 查重服务：CN/OS 双键构造 / 相似度阈值边界 / DEDUP_BLOCKED 不入发票池    │
│    ├── 路由引擎：三条件匹配优先级 / 降级链 / 停用跳过 / 异源交叉互证 / 五项兜底  │
│    ├── 推演一致性：模拟推演步骤 = 真实路由执行日志逐步对齐 (S-M4-01 核心断言)   │
│    ├── 建档链路：五步顺序 / 冲减 Link 校验拦截 / BLOCKED/INVESTIGATING 挂起    │
│    ├── 发号器与租户：分域递增 / 四隔离边界越权拒绝 / 强制注入租户上下文         │
│    └── 配置中心：diff 计算 / 发布版本递增 / 安全回滚恢复 / 红线绕过拦截          │
├────────────────────────────────────────────────────────────────────────┤
│ 3. E2E 场景断言（17 条全量官方场景 · make test-e2e）                     │
│    ├── M3 核心场景 (S-M3-01~05)：受理放行全链 / 重复票 / 篡改票 / 多源冲突 / 五要素缺失 │
│    ├── M4 编排场景 (S-M4-01~05)：推演一致 / 停用降级 / 口径放行 / Link 拦截 / 策略发布 │
│    └── M5 平台场景 (S-M5-01~07)：红线告警拦截 / 配置回滚 / Agent 对话 / MCP / 抽检熔断 │
├────────────────────────────────────────────────────────────────────────┤
│ 4. 红线回归集（R-01~R-06 · 零 skip 全量激活 · make test-redline）         │
│    ├── R-01: 低置信 (<80) 案件不存在任何自动放行路径（行为用例 + 源码走查）      │
│    ├── R-02: 验签失败 → BLOCKED 不可绕过（含配置篡改尝试拦截）                   │
│    ├── R-03: BLOCKED 不可批量放行（全跳列因 + processed=0 + 零留痕污染）         │
│    ├── R-04: 错误自动放行率红线告警不可停用（尝试关闭强制 403 拦截并记入审计链）  │
│    ├── R-05: LLM 输出永不直接写入 checks/status/字段值（静态检查 + 零写断言）     │
│    └── R-06: 写操作无审计记录 → 测试失败（双写完整性断链注入整笔回滚）           │
├────────────────────────────────────────────────────────────────────────┤
│ 5. 一致性校验脚本（tools/ · 前置门禁）                                  │
│    ├── check_enums.py: enum-registry ↔ Excel Sheet08 142 行逐字比对             │
│    ├── validate_contracts.py: 40 项契约、Schema 与跨文件引用自检                │
│    ├── check_seeds_vs_ui.py: 11 案件关键数值与 ui-design 各页常量交叉核验        │
│    ├── check_breaking_changes.py: v1 冻结契约破坏性变更检测 (CI 门禁)           │
│    └── verify_portal_sync.py: api-portal 文档站与 contracts/ 100% 同步校验     │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 常用执行命令（CLI & Makefile 等价入口）

所有命令均支持 `make <target>` 或 `python scripts/hub.py <command>` 执行：

| 任务目标 | Makefile 命令 | 直接命令（Windows / 无 make） | 说明与验收基准 |
|---|---|---|---|
| **全部测试** | `make test` | `python scripts/hub.py test` | 运行全量 405+ 测试，包含单元、集成、契约测试 |
| **E2E 场景断言** | `make test-e2e` | `python scripts/hub.py test-e2e` | 重放全部 17 条官方场景（S-M3-01~05, S-M4-01~05, S-M5-01~07） |
| **红线回归集** | `make test-redline` | `python scripts/hub.py test-redline` | 运行 R-01~R-06 全量红线门禁（零 skip） |
| **Demo 场景回放** | `make demo-replay` | `python scripts/hub.py demo-replay` | 回放蓝图 §13.2 八大场景并输出「演示步骤对照表」 |
| **枚举一致性** | `make verify-enums` | `python scripts/hub.py verify:enums` | 校验 enum-registry 与 Excel Sheet08 逐行逐字一致 |
| **契约结构自检** | `make verify-contracts` | `python scripts/hub.py verify:contracts` | 校验 9 个 JSON Schema 编译与 40 项交叉约束 |
| **UI 原型交叉核验** | `make verify-ui` | `python scripts/hub.py verify:ui` | 校验 seeds 与 ui-design 原型 11 案关键数值 |
| **门户文档契约同步** | `make verify-contracts-sync` | `python scripts/hub.py verify:contracts-sync` | 校验 api-portal 与契约同步 + 破坏性变更检测 |
| **全量校验流水线** | `make verify` | `python scripts/hub.py verify` | 顺序执行上述全部 4 项前置校验脚本 |
| **全流程离线检验** | `make all` | `python scripts/hub.py all` | 串行执行 clean → seed → verify → test → test-redline |

---

## 3. 测试数据纪律与隔离原则

1. **单一数据源**：测试数据一律源自 `seeds/` 目录中冻结的基准数据，禁止在测试代码中私自伪造脱离契约的平行数据集。
2. **测试隔离（临时库）**：
   - 会修改数据的测试（状态机流转、受控命令、哈希链注入、配置变更）强制使用 `fresh_session` fixture 或 `api_client` 临时库，避免测试用例相互污染；
   - 只读比对与契约校验测试使用 session 级共享库；
   - 文件与收据目录通过 `monkeypatch` 重定向到 `tmp_path`，防止污染物理 `runtime/` 目录。
3. **失败信息规范（P08 §2）**：
   - 场景断言与红线测试的断言失败信息必须统一包含：`[场景编号] 断言点：xxx | 期望：xxx | 实际：xxx | 关联 FN：FN-x-xx`，确保任一失败均可快速逆向定位到细化功能清单条款。

---

## 4. 破坏性变更检测机制（Breaking Change Detector）

依据《CHANGELOG.md》v1 FROZEN 治理总纲，任何向后破坏性变更一律被严厉禁止：
- **检测维度**：
  1. 字段删除检测（既有 properties 被移除）；
  2. 字段类型变更检测（既有类型被篡改，如 string 变 number）；
  3. 必填项新增检测（既有 top-level required 列表增加了新字段）；
  4. 枚举值删除检测（既有 enum-registry code 被删除或改名）。
- **执行方式**：
  - 工具脚本：`python tools/check_breaking_changes.py`；
  - 自动化反向断言测试：`test_layer3_breaking_change_detector_synthetic_mutations` 在 CI 运行期自动注入 4 类合成变体，断言检测算法必然有效拦截。

---

## 5. 新增测试用例与场景扩展规范

当平台因新需求需要增补测试时，必须遵循以下步骤：
1. **单测用例**：放入 `backend/tests/` 对应模块，使用标准 pytest 语法，不得直接 import `agent` 或 `mcp` 包；
2. **契约用例**：涉及新端点或响应 Schema 时，同步增补 `backend/tests/test_contracts.py` 语义层断言；
3. **E2E 场景**：在 `tests/scenarios/` 对应里程碑文件中新增函数，打上 `@pytest.mark.scenario` 标记，并在 `tests/scenarios/README.md` 中同步回填台账；
4. **红线用例**：涉及错误自动放行率、SM2 验签、受控写审计等安全红线时，在 `tests/redline/test_redline.py` 增补并打上 `@pytest.mark.redline` 标记，严禁标记 `skip`。
