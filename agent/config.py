# -*- coding: utf-8 -*-
"""Agent 域配置管理（WP5.5 · ADR-0001 / FN-8-08 / FN-9-11）。

模型名称与版本配置化，默认使用 qwen-finance-v2 为演示口径。
所有配置均可经环境变量覆盖。
"""

import os

# 默认后端 API 地址（用于只读工具调用，零 DB 直连）
BACKEND_BASE_URL = os.environ.get("INVOICE_HUB_BACKEND_URL", "http://127.0.0.1:8000")

# 模型客户端配置（可替换）
DEFAULT_MODEL_NAME = os.environ.get("INVOICE_HUB_MODEL_NAME", "qwen-finance-v2")
DEFAULT_MODEL_VERSION = os.environ.get("INVOICE_HUB_MODEL_VERSION", "2026-10-15")

# 数据合规：Prompt / 响应保留天数（默认 30 天，FN-9-11）
PROMPT_RETENTION_DAYS = int(os.environ.get("INVOICE_HUB_PROMPT_RETENTION_DAYS", "30"))

# 法定免责声明文本（FN-0-09 / FN-8-08）
DISCLAIMER_TEXT = (
    "⚠️ 【本建议由大模型生成，不自动执行业务操作，请人工确认后操作】"
    "确定性判断（税额 / 容差 / 状态转换）以规则引擎结论为准。"
)
