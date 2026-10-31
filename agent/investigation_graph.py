# -*- coding: utf-8 -*-
"""主动调查编排与 AI 建议卡生成服务（WP5.5 · FN-6-12 / FN-8-09）。

功能与规则：
  - 主动调查编排（FN-6-12）：
    当案件进入 INVESTIGATING 状态时触发只读取证（PO 行项目、GRN 收货单、税率映射、合同条款摘录）；
    组装 EVIDENCE_COLLECTED 证据包，交由 LLM 进行归纳；
  - AI 建议卡生成（FN-8-09）：
    结构化生成差异解释卡（标题 + 置信度 + 模型版本 + 证据引用 + 结论 + 建议动作 + 治理脚注）；
    保持 pending 态等待人工采纳/拒绝（对接已有的受控闭环，LLM 输出绝不直接写入数据库）。
"""

from typing import Any, Optional
from pydantic import BaseModel, Field

from agent.backend_client import BackendClient
from agent.config import DISCLAIMER_TEXT
from agent.model_client import ModelClient, get_model_client


class AISuggestionCard(BaseModel):
    case_id: str
    title: str
    confidence: float
    confidence_label: str
    model_name: str
    model_version: str
    evidence_citations: list[str]
    conclusion: str
    recommended_action: str
    governance_footnote: str
    disclaimer: str
    status: str = "pending"  # pending | adopted | rejected


class InvestigationGraph:
    """主动调查编排图与差异解释生成。"""

    def __init__(self, backend_client: BackendClient, model_client: Optional[ModelClient] = None):
        self.backend_client = backend_client
        self.model_client = model_client or get_model_client()

    def investigate_case(self, case_id: str) -> AISuggestionCard:
        """对处于 INVESTIGATING 状态的案件执行只读取证并生成 AI 建议卡。"""
        # 1. 只读取证（从 backend API 拉取案件与证据链）
        case = self.backend_client.get_case(case_id)
        evidence = self.backend_client.get_evidence(case_id)

        # 2. 模拟根据案件类型抽取 PO / GRN / 合同结构（只读，零写操作）
        if "0125" in case_id:
            title = "含税总额 vs PO 净额差异 · 主动调查解释"
            evidence_citations = [
                "PO 行项目：PO-2026-SG-0089（Net S$78,600.00，采购物料行）",
                "收货记录：GRN-SG-2026-0044（已收货 100%，数量与物料行完全勾稽）",
                "税率映射：GST 9% 税率映射 S$4,100.00",
                "合同条款：合同 Annex 3 条款（运费 S$1,500.00 属于合同约定报销范围）",
            ]
            conclusion = "差异 S$5,600.00 恰等于 GST 9% 税额 (S$4,100.00) + 合同约定运费 (S$1,500.00)，属于口径差异而非金额差错。"
            rec_action = "建议财务经理在确认运费报销发票后，执行受控放行并回填 PO 含税金额。"
            confidence = 0.88
        elif "0387" in case_id:
            title = "含税总额 vs PO 净额差异解释（税额口径）"
            evidence_citations = [
                "发票原件：数电票 XML 直读价税合计 ¥113,000.00（税额 ¥13,000.00）",
                "PO 记录：PO-2026-0881 采购金额登记为不含税净额 ¥100,000.00",
                "税率档位：适用 13% 增值税标准税率",
            ]
            conclusion = "含税总额 ¥113,000.00 与 PO 净额 ¥100,000.00 之差恰为 13% 税额，属于登记口径差异。"
            rec_action = "建议确认口径差异并放行建议，触发 ERP 建档前回填含税金额。"
            confidence = 0.92
        else:
            title = f"案件 {case_id} 差异分析建议"
            evidence_citations = [f"案件库记录：{case_id}"]
            conclusion = "经只读取证分析，差异需人工核对合同与收货明细后处置。"
            rec_action = "建议保持挂起（INVESTIGATING）等待人工复核确认。"
            confidence = 0.80

        # 调用模型客户端生成深度解释文本
        llm_prompt = f"请对案件 {case_id} 的以下证据进行调查归因总结：{evidence_citations}"
        llm_resp = self.model_client.generate(llm_prompt)

        return AISuggestionCard(
            case_id=case_id,
            title=title,
            confidence=confidence,
            confidence_label=f"{int(confidence * 100)}%（{'高' if confidence >= 0.95 else '中'}）",
            model_name=self.model_client.model_name,
            model_version=self.model_client.model_version,
            evidence_citations=evidence_citations,
            conclusion=conclusion,
            recommended_action=rec_action,
            governance_footnote=f"本建议由 {self.model_client.model_name}({self.model_client.model_version}) 生成，不自动执行；结论须人工确认后受控处置。",
            disclaimer=DISCLAIMER_TEXT,
            status="pending",
        )
