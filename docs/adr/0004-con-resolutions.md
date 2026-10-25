# ADR-0004 · 阻塞 CON 项决议冻结（CON-01~05）与口径冲突裁决

- **状态**：已接受并冻结（**2026-10-25 用户于 M0/WP0.1 人工确认闸门逐项确认**："五项全部按建议确认"，另对 SPI source 词表冲突裁决"六枚举为准+归一映射表"）
- **关联**：实施规划 §3（决议建议原文）；清单 §5.2（CON-01~14 台账）；本决议生效后 Excel Sheet06 对应行收敛状态更新为"已冻结（M0）"
- **纪律**：本 ADR 即 WP0.1 闸门产物；后续会话不得重开这五项讨论（P00 §3/§8）

## 决议一：CON-01 · 置信度全局默认阈值

- **结论**：全局默认阈值 = **0.85**（与 UI 配置中心及路由规则基数一致）；规格 v0.3 §5.2 的 0.75 标注为**历史默认**，由新仓配置种子承载（不再作为实现值）。
- **细则**：路由阈值仍按规则逐条配置（数电票 0.85 / 纸质专票 0.88 / Supplier Invoice 0.85 / Credit Note 0.90）；全局默认值属配置中心租户级覆盖项（FN-9-09），阈值资产版本化+审计。
- **落点**：`seeds/config.json`（confidence_threshold_default=0.85）、`contracts/enum-registry.json` 关联口径（展示分档不变：≥95/80–94/<80）。

## 决议二：CON-02 · 案件状态机模型（含 CON-11 认领态）

- **结论**：**六态为唯一实现模型**（FN-0-02：RECOGNIZED/VERIFYING/NEEDS_REVIEW/INVESTIGATING/RESOLVED/BLOCKED）。
- **规格三态映射**（§5.2 路由判定）：`ok → RECOGNIZED（自动路径）/RESOLVED`；`review_needed → NEEDS_REVIEW`；`blocked → BLOCKED`。
- **建档两态不扩案件状态**（§7.2）：`pending_review` = 建档挂起标记（NEEDS_REVIEW/INVESTIGATING/BLOCKED 下的子标志）；`document_created` = RESOLVED 后的**建档回执事件**（非状态）。
- **CON-11 认领态随本项一并决议**：认领 = **NEEDS_REVIEW 子态字段**（`claimed_by` / `claimed_at` / 锁超时），**不扩状态机**、不设第七状态。
- **落点**：`contracts/enum-registry.json`（case_status / state_transition）、`contracts/invoice-case.schema.json`（status + meta.claimed_* + meta.doc_hold_pending / document_created 回执）、M1 状态机服务；规格 D17 据此收敛。

## 决议三：CON-03 · Schema 字段命名

- **结论**：**以 UI/API 路径为准**冻结 `contracts/invoice-schema.json`（`header.invoice_no`、`total.gross_amount`、`links.po`、`ext.*`、`custom_fields.*`、`discount_lines`、`invoice_type` 等）。
- **规格 v0.3 §4 旧命名**（invoice_number / total.amount / items[].quantity 等）通过 `contracts/field-alias.md` 对照表承接，不改新路径。
- **中国字段 Ariba 承载**仍走 cXML `Extrinsic cn:*`——**H25 未决不阻塞**，别名表与 adapter-contract 标注 `TODO(H25)`。
- **落点**：`contracts/invoice-schema.json`、`contracts/field-alias.md`。

## 决议四：CON-04 · 案件号格式

- **结论**：案件号 = **`INV-{CN|SG}-2026-NNNN`**（带实例域，按租户实例分域发号）。
- **配套义务**：api-portal 页面响应示例（现为 `INV-2026-00125` 不带域）随契约升版更新；`ui-design/` 只读不改，新契约/openapi/seeds 一律使用带域格式，变更记录登记 `contracts/CHANGELOG.md`。
- **落点**：`contracts/enum-registry.json`（id_format）、`contracts/openapi.yaml` 示例、`seeds/cases.json`、M1 发号器。

## 决议五：CON-05 · 查重键与幂等键两键分离

- **结论**：
  - **幂等键**：业务层 = `file_sha256 + target_doc_ref`；传输层 = `requestId`；
  - **查重业务键**：CN = `invoice_code(null→"") + invoice_no + gross_amount`（`seller_tax_id` 辅助、开票日期辅助）；OS = `invoice_no + gross_amount + supplier_id`；
  - UI 告警文案须补"发票代码"要素说明（dashboard/workbench 文案，M2/M3 落实）。
- **两键分离目的**：重试不误判为重复、重复不被幂等吞掉（规格 §5.4 关键设计，采纳）。
- **落点**：`contracts/openapi.yaml`（idempotency 语义）、M3 查重服务、`seeds/alerts.json` 文案口径。

## 附：本闸门发现并裁决的两处口径冲突

| # | 冲突 | 用户裁决（2026-10-25） | 落点 |
|---|---|---|---|
| 1 | **SPI 归一化 source 词表**：api-portal 页 SPI 示例注释用 `ocr \| xml_direct \| pdf_text \| vlm \| verify_api`（5 值），与清单 FN-0-05/Sheet08 六枚举（xml_direct/ocr/qr_code/model/manual/webhook）不一致 | **以六枚举为唯一注册表口径**；provider-spi.schema.json 中 source 约束为六枚举，并登记归一映射 `pdf_text→xml_direct`（同属直读族）、`vlm→model`、`verify_api→webhook`；映射表写入 field-alias.md 与 SPI 契约注释；UI 页面只读不动 | `contracts/provider-spi.schema.json`、`contracts/field-alias.md` |
| 2 | **置信度中档上界**：design-system.md §3 写"80–95% 橙"，清单 FN-0-06/Sheet08 写"80–94% 橙" | 按清单/Excel 取 **80–94%**（文档优先级 2/4 > 5；UI 页面徽章实现 confBadge 实为 ≥95 绿/≥80 橙，与清单一致，design-system.md 属笔误） | `contracts/enum-registry.json`（confidence_band） |

## 未决 CON 的处理纪律（不变）

其余 9 项 CON（06/07/08/09/10/12/13/14 及 H 关联项）不阻塞 M0：按清单建议方向在对应里程碑实现，代码标注 `TODO(CON-xx)`；CON-06 两层幂等关系、CON-12 两套容差配置在 `contracts/` 与 `seeds/config.json` 中先行承载口径。
