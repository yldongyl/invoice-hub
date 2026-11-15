# web/ · UI 运行版（ui-design 接线副本 · 现存 12 页，ADR-0003）

M2 起逐页接线：数据入口从内嵌 mock 换为 REST API（`contracts/openapi.yaml`），并保留 **demo-mode 回退**——backend 不可达时回落内嵌 mock（种子=本仓 `seeds/`，页面仍可独立演示）。

- **纪律**：`ui-design/` 只读不改，接线改动只发生在本目录；徽章/枚举一律从 `contracts/enum-registry.json` 渲染；web 只消费 REST API。
- **范围调整（2026-11-15 业务口径）**：`demo-landing.html`（产品演示宣讲页）已移出测试与交付对象范围并从本目录删除；`ui-design/` 冻结基线保持不动。
- **首批接线**（M2）：case-detail、dashboard-overview、login（演示桩）。
- M0 仅目录占位，**无代码**。
