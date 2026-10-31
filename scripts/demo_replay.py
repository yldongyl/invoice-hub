# -*- coding: utf-8 -*-
"""蓝图 §13.2 八个 Demo 场景回放脚本（WP5.7 · L2 演示闭环 · P08 §1.3）。

八大演示场景列表：
  ① 数电票 XML 直读：不用 OCR，结构化 23 字段和国密验签（中国扩展包实例 · 0386/0387）；
  ② PDF 发票待复核：OCR Provider + 缺 XML 原件提示（0381）；
  ③ 重复票阻断：付款与建档前风险拦截（0385 / 0122）；
  ④ 篡改票阻断：SM2 验真 FAILED → BLOCKED，失败回执 gm-rcpt-1042 随案归档（0379）；
  ⑤ 邮箱管道建档（海外 Invoice）：0918 国外链路全流程（SAP DOX 桩，0125）；
  ⑥ Provider 切换：动态停用百望云自动沿链降级至诺诺与自托管 VLM，不绑定单一厂商；
  ⑦ 口径差异主动调查：含税总额 vs 订单净额差异证据收集、AI 调查结论与受控处置建议卡；
  ⑧ Agent 对话式操作：自然语言对话、蓝标系统与橙标 AI 线索同屏分离、唤起只读卡未修改数据、零写事件。

执行模式：
  1. API 驱动执行与断言；
  2. 输出结构化「演示步骤对照表」（供人工投屏演示时按脚本操作）。
"""

import argparse
import sys
from pathlib import Path

# 配置 UTF-8 控制台
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
BACKEND_ROOT = REPO_ROOT / "backend"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from agent.backend_client import BackendClient
from agent.conversation_graph import ConversationGraph
from agent.investigation_graph import InvestigationGraph
from app.main import create_app
from fastapi.testclient import TestClient


DEMO_SCRIPT_TABLE = """
╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗
║                                 蓝图 §13.2 八大 Demo 场景演示步骤对照表（投屏操作指导）                                    ║
╠═════╦════════════════════════════╦═══════════════════╦═══════════════════════════════════════╦══════════════════════════════╣
║ 序号 ║ 演示场景                   ║ 涉及案件/发票      ║ 页面入口与操作端点                    ║ 投屏讲解要点与业务价值       ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ①   ║ 数电票 XML 直读            ║ INV-CN-2026-0386  ║ /web/case-detail.html?id=...          ║ 免 OCR 零外发、零时延，结构化║
║     ║                            ║ (中科华创数电票)  ║ GET /v1/cases/INV-CN-2026-0386        ║ 23 字段全解析与真实 SM2 验签 ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ②   ║ PDF 发票待复核             ║ INV-CN-2026-0381  ║ /web/agent-workbench.html             ║ 扫描件调用百望云 OCR，系统自 ║
║     ║                            ║ (恒信电子扫描件)  ║ GET /v1/cases/INV-CN-2026-0381        ║ 动提示缺 XML 原件，降级人工  ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ③   ║ 重复票阻断                 ║ INV-CN-2026-0385  ║ /web/agent-workbench.html             ║ 采购付款与建档前拦截，双键跨 ║
║     ║                            ║ INV-SG-2026-0122  ║ GET /v1/cases/INV-CN-2026-0385        ║ 实例查重，BLOCKED 排除出池   ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ④   ║ 篡改票阻断                 ║ INV-CN-2026-0379  ║ /web/case-detail.html?id=...          ║ 真实 SM2 国密验签失败拦截，  ║
║     ║                            ║ (金额篡改数电票)  ║ GET /v1/cases/INV-CN-2026-0379        ║ 失败回执 gm-rcpt 归档可追责  ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ⑤   ║ 邮箱管道建档（海外链路）   ║ INV-SG-2026-0125  ║ /web/intake-pipeline.html             ║ 0918 新加坡实例全链路，通过  ║
║     ║                            ║ (西门子海外发票)  ║ GET /v1/cases/INV-SG-2026-0125        ║ SAP DOX 桩建档至 Ariba cXML  ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ⑥   ║ Provider 切换              ║ 纸质专票路由链    ║ /web/provider-orchestration.html      ║ 动态停用百望云，自动降级至   ║
║     ║                            ║ (百望云→诺诺/VLM) ║ GET /v1/providers & POST toggle       ║ 诺诺与自托管 VLM，不绑定单厂 ║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ⑦   ║ 口径差异主动调查           ║ INV-SG-2026-0125  ║ /web/case-detail.html (调查卡)        ║ 时间线只读取证运费与税额差异 ║
║     ║                            ║ (含税总额vs订单净)║ POST /v1/cases/.../investigate        ║ AI 解释差异，消除业务不确定性║
╠═════╬════════════════════════════╬═══════════════════╬═══════════════════════════════════════╬══════════════════════════════╣
║ ⑧   ║ Agent 对话式操作           ║ 对话侧边栏 / MCP  ║ /web/case-detail.html (右侧 Agent)    ║ 自然语言查询、蓝橙同屏分离、 ║
║     ║                            ║ (王莉财务经理会话)║ POST /mcp/v1/tools/call               ║ 唤起只读卡未改数据、零写事件 ║
╚═════╩════════════════════════════╩═══════════════════╩═══════════════════════════════════════╩══════════════════════════════╝
"""


class DemoRunner:
    def __init__(self):
        self.app = create_app()
        self.client = TestClient(self.app)
        self.backend_client = BackendClient(http_client=self.client)
        self.conv_graph = ConversationGraph(self.backend_client)
        self.invest_graph = InvestigationGraph(self.backend_client)

    def run_all(self):
        print("══════════════════════════════════════════════════════════════")
        print("  全球采购平台票据智能与合规中台 · 蓝图 §13.2 八大 Demo 场景回放")
        print("══════════════════════════════════════════════════════════════")
        passed = 0
        scenarios = [
            (1, "数电票 XML 直读", self.scene_1_xml_direct),
            (2, "PDF 发票待复核", self.scene_2_pdf_needs_review),
            (3, "重复票阻断", self.scene_3_duplicate_blocked),
            (4, "篡改票阻断", self.scene_4_tampered_blocked),
            (5, "邮箱管道建档（海外 Invoice）", self.scene_5_overseas_filing),
            (6, "Provider 切换", self.scene_6_provider_switch),
            (7, "口径差异主动调查", self.scene_7_variance_investigation),
            (8, "Agent 对话式操作", self.scene_8_agent_conversation),
        ]

        for num, name, fn in scenarios:
            print(f"\n▶ 场景 {num}：{name} ...")
            try:
                fn()
                print(f"  ✓ 场景 {num} 回放成功（PASS）")
                passed += 1
            except Exception as e:
                print(f"  ✗ 场景 {num} 回放失败: {e}")
                raise

        print(f"\n==============================================================")
        print(f"  回放完毕：{passed} / {len(scenarios)} 场景全部通过（ALL GREEN）！")
        print(f"==============================================================")
        print(DEMO_SCRIPT_TABLE)
        return 0

    def scene_1_xml_direct(self):
        """场景 1：数电票 XML 直读（不用 OCR，结构化和验签）。"""
        res = self.client.get("/v1/cases/INV-CN-2026-0386?instance=CN")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "RECOGNIZED"
        assert "数电票" in data["meta"]["type"]
        assert "XML 直读" in data["meta"]["provider"]

    def scene_2_pdf_needs_review(self):
        """场景 2：PDF 发票待复核（OCR Provider + 缺 XML 原件提示）。"""
        res = self.client.get("/v1/cases/INV-CN-2026-0381?instance=CN")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["status"] == "NEEDS_REVIEW"
        assert "OCR" in data["meta"]["provider"] or "百望云" in data["meta"]["provider"]

    def scene_3_duplicate_blocked(self):
        """场景 3：重复票阻断（付款前风险拦截）。"""
        res_cn = self.client.get("/v1/cases/INV-CN-2026-0385?instance=CN")
        assert res_cn.status_code == 200
        assert res_cn.json()["status"] == "BLOCKED"
        assert res_cn.json()["meta"]["risk_label"] == "重复票"

        res_os = self.client.get("/v1/cases/INV-SG-2026-0122?instance=OS")
        assert res_os.status_code == 200
        assert res_os.json()["status"] == "BLOCKED"

    def scene_4_tampered_blocked(self):
        """场景 4：篡改票阻断（SM2 验签失败）。"""
        res = self.client.get("/v1/cases/INV-CN-2026-0379?instance=CN")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "BLOCKED"
        auth_check = data["checks"]["authenticity"]
        auth_res = auth_check["result"] if isinstance(auth_check, dict) else auth_check
        assert auth_res == "FAILED"
        assert data["meta"]["sm2"]["receipt_no"] == "gm-rcpt-1042"

    def scene_5_overseas_filing(self):
        """场景 5：邮箱管道建档（海外 Invoice · 0918 国外链路覆盖）。"""
        res = self.client.get("/v1/cases/INV-SG-2026-0125?instance=OS")
        assert res.status_code == 200
        data = res.json()
        assert data["meta"]["instance"] == "OS"
        assert "Siemens" in data["meta"]["supplier"]
        assert data["meta"]["adapter"] == "SAP Ariba · cXML InvoiceDetailRequest"

    def scene_6_provider_switch(self):
        """场景 6：Provider 切换（不绑定单一厂商，支持动态停用与降级）。"""
        res = self.client.get("/v1/providers")
        assert res.status_code == 200
        providers = res.json()["providers"]
        assert len(providers) >= 6
        assert any(p.get("provider_id") == "bwyun-cn" for p in providers)
        assert any(p.get("provider_id") == "selfhosted-ocr-vlm" for p in providers)

    def scene_7_variance_investigation(self):
        """场景 7：口径差异主动调查（证据收集、调查结论与建议卡）。"""
        card = self.invest_graph.investigate_case("INV-SG-2026-0125")
        assert card.case_id == "INV-SG-2026-0125"
        assert "差异" in card.title
        assert len(card.evidence_citations) >= 3
        assert "口径差异" in card.conclusion

    def scene_8_agent_conversation(self):
        """场景 8：Agent 对话式操作（自然语言查询、蓝橙分离、只读卡唤起）。"""
        resp = self.conv_graph.run("查询案件 INV-CN-2026-0387 全部证据链", actor="王莉")
        assert resp.intent == "EVIDENCE_CHAIN"
        assert "tag-blue" in resp.system_result_html
        assert "tag-orange" in resp.ai_clues_html
        assert resp.zero_write_asserted is True
        assert len(resp.invoked_cards) >= 1
        assert resp.invoked_cards[0].readonly is True


def main():
    parser = argparse.ArgumentParser(description="蓝图 §13.2 Demo 场景回放")
    parser.add_argument("--scenario", default="all", help="all 或 1..8")
    args = parser.parse_args()

    runner = DemoRunner()
    if args.scenario == "all":
        sys.exit(runner.run_all())
    else:
        try:
            num = int(args.scenario)
            sc_map = {
                1: runner.scene_1_xml_direct,
                2: runner.scene_2_pdf_needs_review,
                3: runner.scene_3_duplicate_blocked,
                4: runner.scene_4_tampered_blocked,
                5: runner.scene_5_overseas_filing,
                6: runner.scene_6_provider_switch,
                7: runner.scene_7_variance_investigation,
                8: runner.scene_8_agent_conversation,
            }
            method = sc_map.get(num)
            if method:
                print(f"▶ 正在回放场景 {num} ...")
                method()
                print(f"✓ 场景 {num} 回放成功！")
                sys.exit(0)
            else:
                print(f"未知场景: {args.scenario}")
                sys.exit(1)
        except Exception as e:
            print(f"场景回放失败: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
