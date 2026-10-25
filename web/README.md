# web/ · UI 运行版（ui-design 12 页接线副本，ADR-0003）

M2 起逐页接线：数据入口从内嵌 mock 换为 REST API（`contracts/openapi.yaml`），并保留 **demo-mode 回退**——backend 不可达时回落内嵌 mock（种子=本仓 `seeds/`，页面仍可独立演示）。

- **纪律**：`ui-design/` 只读不改，接线改动只发生在本目录；徽章/枚举一律从 `contracts/enum-registry.json` 渲染；web 只消费 REST API。
- **首批接线**（M2）：case-detail、dashboard-overview、login（演示桩）。
- M0 仅目录占位，**无代码**。
