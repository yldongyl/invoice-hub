# contracts/ 契约变更记录账本（FN-A-07 版本治理）

> 治理总纲：**v1 FROZEN**（2026-10 随蓝图评审冻结，M0 落仓 2026-10-25）；向后兼容变更（新增可选字段/新枚举值）在 v1 内发布并登记本账本；**破坏性变更**（字段语义变更/必填项调整/枚举删除）一律走 `/v2` 并行过渡，不静默变更。契约文档、`contracts/` 机器可读文件、Demo 资产三者同步（FN-A-09/FN-7-11）。

## 登记格式说明

每条记录：编号 · 日期 · 类型（FROZEN 冻结 / COMPAT 兼容新增 / BREAKING→/v2 / SYNC 同步义务）· 影响文件 · 内容 · 依据（FN/CON/H 编号）。

---

## v1 · FROZEN

### ① 2026-10-25 · FROZEN · M0 初冻结（全部契约资产）
- **影响文件**：`enum-registry.json`、`invoice-schema.json`、`invoice-case.schema.json`、`openapi.yaml`、`events.schema.json`、`mcp-tools.json`、`provider-spi.schema.json`、`routing-config.schema.json`、`adapter-contract.schema.json`、`field-alias.md` + `seeds/` 全部 13 文件。
- **内容**：按 CON-01~05 决议（docs/adr/0004，2026-10-25 用户逐项确认）冻结；enum-registry 与 Excel Sheet08 全 115 行逐字一致（tools/check_enums.py 通过）；三演示案件（INV-CN-2026-0387 / 0379 / INV-SG-2026-0125）通过 invoice-case.schema.json 校验（tools/validate_contracts.py）。
- **随冻结登记的口径裁决**：
  1. `header.issue_date`：FN-0-03 行文作 `header.invoice_date`，ui-design 页面与规格旧版均为 `header.issue_date`；按 CON-03「UI/API 路径为准」落 **issue_date**（对照说明见 field-alias.md §1）。
  2. **SPI source 词表归一**：api-portal 页面 SPI 示例注释（ocr/xml_direct/pdf_text/vlm/verify_api）与六枚举不一致——裁决为六枚举唯一口径，归一映射 pdf_text→xml_direct、vlm→model、verify_api→webhook（ADR-0004 附#1；provider-spi.schema.json source_vocabulary_note）。
  3. **置信度中档上界**：按清单/Sheet08 取 80–94%（design-system.md §3 之 80–95% 为笔误；ADR-0004 附#2）。
- **依据**：P01 WP0.1~0.6；实施规划 §3/§4-M0。

### ② 2026-10-25 · SYNC · 页面示例随契约升域（CON-04 同步义务）
- **影响文件**：`openapi.yaml`（响应示例、webhook caseId pattern）、`adapter-contract.schema.json`（cXML payloadID 示例）、`seeds/`。
- **内容**：api-portal.html 页面示例仍为不带域案件号（`INV-2026-00125`、`invoice-hub-INV-2026-00125@ariba`）与旧契约路径文案（`invoice-platform/contracts/`、`ariba-mock/contracts/`）。按 CON-04 决议：契约资产一律使用 `INV-{CN|SG}-2026-NNNN`；`ui-design/` 只读不改（ADR-0003），页面更新列入 M2 接线/web 副本同步范围，文档门户（FN-A-09）与 contracts 同步校验在 M5 验收。
- **依据**：实施规划 §3 CON-04 落点「api-portal 示例随契约升版更新」；ADR-0003。

### ③ 2026-10-25 · COMPAT 预留 · nextAction.type 枚举登记路径
- **影响文件**：`invoice-case.schema.json`（nextAction.type）。
- **内容**：FN-0-01 未定义 nextAction.type 枚举字典（Sheet08 无此类，禁止造词不入注册表）。M0 冻结为自由字符串+口径示例（HUMAN_REVIEW/DUAL_APPROVAL/INVESTIGATE/AUTO_ARCHIVE/PUSH_ADAPTER）；M1 状态机服务定型后作为**新增枚举值**按 FN-A-07 兼容变更登记并入 enum-registry（v1 内 bump 版本号）。
- **依据**：P00 §4.4 枚举纪律。

### ④ 2026-10-25 · COMPAT 预留 · invoice_type 票种统一枚举刷新
- **影响文件**：`invoice-schema.json`（invoice_type）。
- **内容**：票种统一枚举以 FN-4-01 清单口径为准（M0 不锁字面枚举）；规格 16 类（9 类国标凭证留位）映射随票种分类规则版本化刷新（CON-03 对照项），刷新走兼容登记。
- **依据**：清单 FN-4-01 / CON-03。

---

## TODO 未决项登记（冻结不阻塞，实现标注纪律）

| 标记 | 位置 | 内容 |
|---|---|---|
| `TODO(H24)` | adapter-contract（字段级细则、addressID 映射）、invoice-schema x-extension-families、routing-config（目标 Tax Code 刷新） | Ariba cXML 建档接口细则待确认 |
| `TODO(H25)` | field-alias §8、adapter-contract cn_field_carriage、invoice-schema ext/custom_fields | 中国字段 Extrinsic cn:* 承载待确认（阻塞级，不阻塞海外链路） |
| `TODO(H29)` | （M3/M4 Provider 选路收益） | PDF 原生/扫描占比与 OCR 计费口径 |
| `TODO(H38)` | 三单匹配边界（匹配文案 warn） | 三单在 Ariba 还是 ERP 执行 |
| `TODO(H39)` | config/seeds 数据驻留细则 | 中国部署区域与数据驻留（推断标注） |
| `TODO(CON-06)` | openapi 幂等两层说明 | 已按对照承载，规格文档侧待补 |
| `TODO(CON-09)` | 保留期分层（10/7/2 目标策略 vs ≥365 天系统下限） | M3/M5 归档实现时声明分层关系 |
| `TODO(CON-12)` | 两套容差配置（±0.06 勾稽 / ±S$50 PO 匹配） | config.json 已分设两项，admin 页补配置项在 M5 |
| `TODO(CON-13)` | 人工查验操作区（并入 case-detail，决议方向） | M3 实现 |
| `TODO(CON-14)` | 消息中心 vs 告警页入口 | M5 分发渠道落地 |

## /v2 启用条件（未触发）

字段语义变更 / 必填项调整 / 枚举删除。当前未计划任何 /v2 变更；`/v2` 为预告位不静默变更（api-portal 版本治理卡）。
