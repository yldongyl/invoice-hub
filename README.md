# invoice-hub · 全球采购平台票据智能与合规中台

> **工程定位**：将不同国家、格式、渠道、Provider 输出的**供应商采购发票**（PO/non-PO、数电票、增值税票、海外 Supplier Invoice / Credit Note / Debit Note），统一转成采购平台/ERP 可用、可信、可审计、可匹配的数据。
> **业务边界外**（禁止出现任何入口/文案/代码）：员工报销、差旅餐饮票、销项开票、税务申报、银行对账、资金支付。

当前里程碑：**M0 · 契约与决策冻结**（纯文档/Schema/数据，无服务代码）。

## 目录说明

```text
invoice-hub/
├── contracts/            # 机器可读契约（唯一事实源，M0 冻结）
│   ├── openapi.yaml                 # 集成 API（FN-A-01/02/03）
│   ├── invoice-case.schema.json     # 案件聚合（FN-0-01/05/07）
│   ├── invoice-schema.json          # 统一 Schema 字段路径（FN-0-03 · CON-03 决议）
│   ├── enum-registry.json           # 全站枚举注册表（Excel Sheet08 全 115 行，FN-0-15）
│   ├── events.schema.json           # 时间线事件模型 + Webhook 四事件（FN-0-10 / FN-A-03）
│   ├── mcp-tools.json               # MCP 6 工具与权限级别（FN-A-04）
│   ├── provider-spi.schema.json     # 南向 SPI 三方法 + ProviderResult 归一化（FN-A-05）
│   ├── routing-config.schema.json   # 路由/降级策略配置（FN-2-08/10 · FN-A-05）
│   ├── adapter-contract.schema.json # 东向 Ariba cXML 建档契约骨架（FN-A-06，TODO(H24)）
│   ├── field-alias.md               # 规格 v0.3 旧命名 ↔ 新路径对照（CON-03/05 · TODO(H25)）
│   └── CHANGELOG.md                 # 契约变更记录账本（FN-A-07）
├── backend/              # 确定性核心（FastAPI，无 LLM 依赖）——M1 起实装，当前仅空 __init__.py 占位
├── agent/                # LangGraph 域（只调用 backend API）——M5 实装
├── mcp/                  # MCP Server（6 工具 = 4 只读 + 2 受控写）——M5 实装
├── web/                  # ui-design 12 页的接线副本（demo-mode 回退）——M2 起实装
├── seeds/                # 种子数据（Excel Sheet09 + 清单附录 A/B/C，前后台同源基线）
├── docs/                 # adr/（0001~0004）+ gate-reports/（里程碑自检）+ 运行手册（后续里程碑补充）
├── tests/                # 仓库级 E2E 场景断言（scenarios/，M3 起自建）
└── tools/                # M0 自检脚本：check_enums.py（枚举↔Sheet08）、validate_contracts.py（契约/种子校验）
```

## 文档树与单一事实源（冲突时优先级从高到低）

| 优先级 | 文档 | 路径 |
|---|---|---|
| 1 | 机器可读契约 | `invoice-hub/contracts/` |
| 2 | 细化功能清单 MD | `../细化功能清单/采购平台票据智能与合规中台-细化功能清单.md` |
| 3 | 实施规划 MD | `../细化功能清单/invoice-hub实施规划.md` |
| 4 | 细化功能清单 Excel | `../细化功能清单/采购平台票据智能与合规中台-细化功能清单.xlsx` |
| 5 | UI 设计基准（只读） | `../ui-design/*.html`（12 页）+ `design-system.md` |

## 快速开始（M0 阶段）

```bash
# 枚举注册表 ↔ Excel Sheet08 逐行一致性校验
python tools/check_enums.py

# 契约编译 / seeds 校验 / 编号一致性 / 三演示案件过 Schema
python tools/validate_contracts.py
```

服务启动与页面接线随 M1~M5 里程碑补充（本 README 对应小节为占位）。

## 历史资产纪律

`../ariba-mock/`、`../invoice-platform/` 为前一版本工程——**禁止拷贝其代码、禁止引用其 contracts 路径**；仅场景断言方法论可参考。本仓 `contracts/` 为唯一契约事实源。

## 会话入口

后续编码会话请先加载 `CLAUDE.md`（主上下文 P00），再执行阶段提示词（`../细化功能清单/vibe-coding-prompts/`）。
