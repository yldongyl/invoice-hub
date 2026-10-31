# -*- coding: utf-8 -*-
"""可替换模型客户端实现（WP5.5 · FN-6-08 / FN-8-09 / FN-9-11）。

特性：
  - 模型名与版本配置化，支持第三方 API / 私有化 VLM 替换；
  - 演示口径：默认以 qwen-finance-v2 为基线实现；
  - 逐次调用审计留痕（记录模型版本、输入摘要、输出、token 等）；
  - 数据合规：Prompt / 响应 30 天清理任务接口。
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field

from agent.config import DEFAULT_MODEL_NAME, DEFAULT_MODEL_VERSION, PROMPT_RETENTION_DAYS


class ModelResponse(BaseModel):
    call_id: str
    model: str
    version: str
    output_text: str
    confidence: float = 0.88
    prompt_digest: str
    tokens_used: int = 120
    ts: str


class CallAuditEntry(BaseModel):
    call_id: str
    ts: datetime
    model: str
    version: str
    prompt_digest: str
    prompt_snippet: str
    output_snippet: str
    tokens_used: int


class ModelClient:
    """可替换的大模型客户端统一接口。"""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, model_version: str = DEFAULT_MODEL_VERSION):
        self.model_name = model_name
        self.model_version = model_version
        self._audit_log: list[CallAuditEntry] = []

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> ModelResponse:
        """模型推理入口，含逐次调用审计记录。"""
        now = datetime.now(timezone.utc).astimezone()
        prompt_digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        call_id = f"call-{secrets.token_hex(8)}"

        # 演示口径响应逻辑（覆盖三类主要生成场景）
        output_text = self._infer(prompt, system_prompt)
        confidence = 0.88
        if "0387" in prompt:
            confidence = 0.92
        elif "0125" in prompt:
            confidence = 0.86
        elif "低置信" in prompt or "低匹配" in prompt:
            confidence = 0.75  # 触发 <80% 强制人工标注

        response = ModelResponse(
            call_id=call_id,
            model=self.model_name,
            version=self.model_version,
            output_text=output_text,
            confidence=confidence,
            prompt_digest=prompt_digest,
            tokens_used=len(prompt) // 4 + len(output_text) // 4,
            ts=now.isoformat(timespec="seconds"),
        )

        # 逐次调用留痕（FN-9-11）
        self._audit_log.append(CallAuditEntry(
            call_id=call_id,
            ts=now,
            model=self.model_name,
            version=self.model_version,
            prompt_digest=prompt_digest,
            prompt_snippet=prompt[:80],
            output_snippet=output_text[:80],
            tokens_used=response.tokens_used,
        ))

        return response

    def _infer(self, prompt: str, system_prompt: Optional[str]) -> str:
        """核心推理实现（可重写接入真实 API，如通义金融/OpenAI兼容端点）。"""
        p_lower = prompt.lower()
        if "0387" in prompt or "税额" in prompt:
            return (
                "【差异归因解释】INV-CN-2026-0387 含税总额 ¥113,000.00 vs PO-2026-0881 净额 ¥100,000.00，"
                "差额 ¥13,000.00 恰为 13% 增值税额。综合采购订单税率映射与 XML 直读原件，"
                "判定为含税/不含税登记口径差异而非价格错误。建议：按口径差异路径放行并回填 PO 含税金额。"
            )
        elif "0125" in prompt or "siemens" in p_lower:
            return (
                "【调查结论解释】INV-SG-2026-0125 Invoice Gross S$84,200.00 vs PO Net S$78,600.00，"
                "差异 S$5,600.00 包含 GST 9% (S$4,100.00) + 合同约定运费行 (S$1,500.00)。"
                "收货单 GRN-SG-2026-0044 已覆盖发票物料行，运费行符合合同条款 Annex 3 运费报销口径。建议人工确认口径后放行。"
            )
        elif "重复" in prompt or "海外" in prompt:
            return (
                "【重复风险筛查】本月海外供应商发票中共筛查出 1 起高风险案件：INV-SG-2026-0122（Schaeffler Singapore），"
                "发票号 SCH-SG-77410 与已建档案件 INV-SG-2026-0098 完全一致，已在建档前被规则查重硬拦截（BLOCKED），"
                "未推送建档，资金风险为 0。"
            )
        elif "映射" in prompt or "报关单" in prompt:
            return (
                "建议将源字段「报关单号」映射至统一 Schema 扩展字段「custom_fields.customs_ref」。"
                "理由：语义匹配度 86%，符合进口报关附单归档规范。"
            )
        elif "归因" in prompt:
            return (
                "近 7 日审计日志周期归因：① 邮箱渠道重复票占 80%，建议受理层增加预检；"
                "② OCR P95 尾部抖动来自倾斜专票；③ XML 与 OCR 冲突场景建议坚持结构化原件优先。"
            )
        return (
            f"已基于 {self.model_name}({self.model_version}) 完成分析。请复核员在工作台核对原件证据，受控确认处置。"
        )

    def cleanup_expired_prompts(self, retention_days: int = PROMPT_RETENTION_DAYS) -> int:
        """清理超过保留期限的 Prompt / 响应审计日志（FN-9-11）。"""
        cutoff = datetime.now(timezone.utc).astimezone() - timedelta(days=retention_days)
        initial_count = len(self._audit_log)
        self._audit_log = [e for e in self._audit_log if e.ts >= cutoff]
        return initial_count - len(self._audit_log)

    def get_audit_log_count(self) -> int:
        return len(self._audit_log)


# 全局默认模型客户端单例
_default_model_client = ModelClient()


def get_model_client() -> ModelClient:
    return _default_model_client


def set_model_client(client: ModelClient) -> None:
    global _default_model_client
    _default_model_client = client
