# field-alias.md · 字段命名对照表（CON-03 / CON-05 决议承载 · v1 FROZEN）

> 依据：docs/adr/0004（2026-10-25 用户确认）。**新路径唯一事实源 = `contracts/invoice-schema.json`**（UI/API 路径为准）；本表承接《平台功能规格说明书》v0.3 §4 旧命名与口径迁移，供历史文档阅读、旧样例回放与字段治理使用。**实现不得引用「旧名」列作为字段路径。**

## §1 发票头（规格 §4.1 → header.*）

| 规格 v0.3 旧名 | 新路径（冻结） | 分区 | 说明 |
|---|---|---|---|
| `invoice_number` | `header.invoice_no` | Core | FN-0-03 UI 基准路径 |
| `issue_date` | `header.issue_date` | Core | FN-0-03 行文写作 `header.invoice_date`，但 ui-design 页面与规格旧版均为 `issue_date`；按 CON-03「UI/API 路径为准」落 `issue_date`（CHANGELOG.md ① 登记） |
| `invoice_code` | `header.invoice_code` | CN Ext | 数电票为 null；查重键 null→空串（CON-05） |
| `currency` | `total.currency` | Core | 自发票头迁入 total 分区（FN-0-03 total.* 口径） |
| `invoice_type` | `invoice_type` | Core | 顶层保留；统一枚举以 FN-4-01 清单口径为准（规格 16 类含 9 类国标凭证留位为细档，映射随票种分类规则版本化，CON-03 对照） |
| `remarks` | `header.remarks` | Core | — |

## §2 购销双方（规格 §4.2 → seller.* / buyer.*）

| 旧名 | 新路径 | 说明 |
|---|---|---|
| `seller.name` / `seller.tax_id` | 同名保留 | 路径一致，无需迁移 |
| `buyer.name` / `buyer.tax_id` | 同名保留 | buyer.tax_id 改为可空（海外票面常缺省） |
| （无） | `buyer.entity_id` | 新增：购买方法人实体（FN-6-05 buyer_entity_match，双实例主体不同） |

## §3 行项目（规格 §4.3 → items[]）

| 旧名 | 新路径 | 说明 |
|---|---|---|
| `name` | `items[].name` | OS 口径 `Description` → 同字段 |
| `spec` / `unit` | `items[].spec` / `items[].unit` | CN 8 列口径；OS 缺省 |
| `quantity` | `items[].qty` | 更名 |
| `unit_price` | `items[].unit_price` | 一致 |
| `tax_rate` | `items[].tax_rate` | CN 口径；OS 用 `items[].tax`（GST 9% / 0% zero-rated 文本列） |
| `tax_amount`（行） | 行税额并入 `items[].tax`（OS）；CN 行级以 amount×rate 勾稽 | FN-6-06 行级税码 |
| `amount` | `items[].amount` | CN=不含税行金额；OS 行含税额 |
| （无） | `items[].po_outside_fee` | 新增：PO 外费用标记（FN-6-03，UI 黄底高亮） |

## §4 合计（规格 §4.4 → total.*）

| 旧名 | 新路径 | 说明 |
|---|---|---|
| `total.amount` | `total.net_amount` | 更名（FN-0-03） |
| `total.tax_amount` | `total.tax_amount` | 一致 |
| `total.gross_amount` | `total.gross_amount` | 一致（中国口径核心字段；OS=Total Due；红字/CN 负数） |
| （无） | `total.gross_in_words` | 新增：价税合计大写（CN） |
| （无） | `total.freight` | 新增：运费合计（OS/APAC，0125 案） |

## §5 识别质量与结论（规格 §4.5 → 案件模型承载）

| 旧名 | 新承载 | 说明 |
|---|---|---|
| `confidence`（整票） | `meta.confidence`（0–100 展示）+ `evidence[].confidence`（字段级 0–1） | 规格 [0,1] 与 UI 百分制并存：契约字段级用 [0,1]（FN-0-05），meta 展示档用整数 |
| `field_confidence`（map） | `evidence[].confidence` 数组化 | 逐字段带证据，不再另设映射位 |
| `verification{method,result,detail,verified_at}` | `checks.authenticity{result,note}` + `meta.sm2/meta.vat` + `evidence[field=evidence.sm2_signature]` | 六态/四校验模型取代 verification 对象（CON-02）；`method=manual` 人工查验记录并入 case-detail 操作区（CON-13，M3 TODO(CON-13)） |
| `duplicate{is_duplicate,matched_invoice_id}` | `checks.duplicate{result,note}` + 告警 `seeds/alerts.json` | 两键分离见 §7 |
| `review{needed,reason,fields[]}` | `status=NEEDS_REVIEW` + `nextAction` + `evidence[].confidence<阈值` 字段集 | 不再另设 review 对象 |
| `source{file_name,file_digest,original_format,has_xml_original}` | `file{name,sha256,has_xml_original,note}` + `meta.channel` + `recognition_path` | 原件摘要受理即登记（FN-0-13） |
| `sub_invoices`（混贴子票） | **新 Schema v1 未收录** | 演示口径不含混贴分割；需要时按 FN-A-07 v1 兼容新增可选字段登记 |
| `recognition_path`（§5.3） | `recognition_path`（同名保留） | 枚举一致：L1_xml_direct / L1_ofd_direct / L1_pdf_text / L2_ocr_vlm / L3_vlm_fallback / L4_manual_review；`canned_fixture` 仅 Mock 允许 |

## §6 SPI / Provider 侧 source 词表归一映射（ADR-0004 附#1 裁决）

**注册表唯一口径 = 六枚举**（enum-registry.field_source）。api-portal 页面 SPI 示例注释中的细粒度词表（页面只读，不改）按下列映射归一后方可进入内核：

| Provider/SPI 侧词表 | 归一目标 | 依据 |
|---|---|---|
| `xml_direct` | `xml_direct` | 直接一致 |
| `pdf_text` | `xml_direct` | 同属「直读族」（结构化/文本层直读，零模型参与）；识别路径细分保留在 `recognition_path=L1_pdf_text` |
| `ocr` | `ocr` | 直接一致 |
| `vlm` | `model` | VLM 文档理解输出（仅作证据源） |
| `verify_api` | `webhook` | 授权查验/名录校验外部回执族 |
| （人工修正） | `manual` | FN-8-05 |
| （二维码/条码） | `qr_code` | FN-2-01 |

## §7 查重键 / 幂等键旧口径对照（CON-05 / CON-06）

| 键 | 规格 v0.3 | 冻结口径（ADR-0004 决议五） |
|---|---|---|
| 幂等键（业务层） | 原件摘要 + 目标单据号 | `file_sha256 + target_doc_ref`（同义，更名机读化） |
| 幂等键（传输层） | — | `requestId`（与 caseId 关系见 CON-06 两层说明，openapi.yaml 承载） |
| 查重业务键 CN | 发票代码(null→空串)+号码+价税合计 | `invoice_code(null→"") + invoice_no + gross_amount`，`seller_tax_id` 辅助、开票日期辅助（FN-5-04 UI 口径并入） |
| 查重业务键 OS | （规格未细化） | `invoice_no + gross_amount + supplier_id` |

## §8 Ariba cXML 承载（Extrinsic cn:* · TODO(H25) 阻塞级待确认）

| 新路径字段 | Ariba cXML 承载（演示口径） | 状态 |
|---|---|---|
| `header.invoice_no` | `InvoiceDetailHeader/@invoiceID`（+ `InvoiceIDInfo/@uniqueID` 旧位） | v1 冻结骨架，细则 TODO(H24) |
| `total.gross_amount` | `Total/Money`（旧 DueAmount 位） | 同上 |
| `total.tax_amount` + `tax.tax_code` | `Tax` 节点（含税档描述） | 同上 |
| `header.po` / `links.po` | `OrderReference/@orderID`（缺省走 non-PO） | FN-A-06 三条基础映射 |
| **CN 扩展字段**（invoice_code、tax_id、SM2 回执、大写金额等） | `Extrinsic name="cn:*"`（Custom Fields 通道，Ariba 侧 14 个 Custom Fields 之一族） | **TODO(H25)：中国字段承载待确认**——不阻塞海外链路；调查结论落地后按 FN-A-07 兼容登记刷新 |
| `supplier_id` 等主数据 | `Contact/@addressID` 映射 | TODO(H24) |

> H25 结论刷新纪律（CON-10）：映射模板数据模型支持"按真实字段面刷新版"（模板版本化 v1.4 已具备），变更走版本刷新不动内核。
