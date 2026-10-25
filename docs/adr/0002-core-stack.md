# ADR-0002 · 核心技术栈：Python + FastAPI，组件选型走 PoC 口径可替换

- **状态**：已接受（2026-10-22 用户确认，见实施规划 §1；本文件为落仓全文）
- **关联**：清单 §7 TS-01~TS-18（能力维度，技术中立）；蓝图 §8.4；实施规划 §1/§6

## 背景

需要在功能清单（技术中立 What 层）之下冻结一套架构级技术栈，供 AI Vibe Coding 全量生成与自测；但蓝图与清单均不绑定中间件/存储产品（UI 中 Prometheus/MinIO/Redis 等为演示示例，不构成选型约束）。

## 备选项

| 方案 | 优点 | 否决理由 |
|---|---|---|
| Java/Spring（SAP 生态惯性） | 企业集成成熟 | LangGraph / MCP Python SDK 同为 Python 生态，跨语言分裂双轨边界；XML/OFD/SM2 国密库 Python 侧可得；vibe coding 生成+自测回路更慢 |
| Node/TypeScript | 前后端同语言 | 同上：Agent/MCP 生态与国密/OFD 解析支撑弱；确定性核心与前端耦合风险 |
| **Python + FastAPI（选定）** | 与 LangGraph / MCP Python SDK 同语言同生态；Pydantic 契约与 JSON Schema 双向一致；async 原生支撑同步/异步混合 API（TS-01）；OpenAPI 自动导出 | 需要依赖纪律防"顺手 import LLM 库"（以评审红线+import 检查兜底） |

## 决策

- 语言/框架：**Python + FastAPI**（backend 确定性核心与 web 数据面）；agent 域 **LangGraph**、对外 **MCP Python SDK**（同栈不同包，边界由目录与依赖纪律承载）；
- 组件级选型**不在本 ADR 冻结**：数据层（SQLite 可切 PostgreSQL）、队列（内存队列可切 Redis）、对象存储（本地目录可切 MinIO）一律按 PoC 口径实施，**每次切换须另立 ADR**（实施规划 §1 注）；
- 测试基座：pytest + jsonschema（契约测试三层：结构/语义/版本兼容，FN-A-08）。

## 后果

- **正面**：单语言覆盖双轨+接口面，Vibe Coding 会话生成物可直接 `pytest` 自测；PoC→生产演进路径明确且不阻塞里程碑；
- **代价**：OFD 版式解析、SM2 国密库的成熟度需在 M3 前完成验证（TS-08/09 风险项，验签失败面由红线策略兜底）；
- **约束落点**：本 ADR 只冻结架构级决策；SQLite/本地目录/内存队列在 seeds/runbook 中一律标注"演示口径，可替换"。
