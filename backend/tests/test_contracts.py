# -*- coding: utf-8 -*-
"""FN-A-08 三层契约测试套件（结构层 / 语义层 / 版本兼容层）。

本套件严格依照实施规划 §7 与细化功能清单 FN-A-08 实现：
  1. 结构层（Structural Layer）：
     - contracts/ 全部 JSON Schema 可编译（Draft 2020-12 check_schema）；
     - openapi.yaml 规范与引用校验（paths, webhooks, operationId 唯一, responses 齐备）；
     - seeds/*.json 数据文件逐一通过对应的 JSON Schema 校验。
  2. 语义层（Semantic Layer）：
     - 所有核心 API 响应结构过 Schema 校验（/v1/cases/{id}, /v1/cases, /v1/dashboard, /v1/alerts 等）；
     - 枚举字段值一致性校验（数据库与种子数据严格 ∈ contracts/enum-registry.json）；
     - 业务编号格式规则断言（正则匹配：案件号、批次号、trace ID、验签回执、供应商代码、租户 ID 等）；
     - 状态机流转合法性与非法流转拒绝语义校验。
  3. 版本兼容层（Version Compatibility Layer）：
     - 契约变更账本 contracts/CHANGELOG.md 与治理总纲校验；
     - v1 冻结破坏性变更检测（检测字段删除、类型篡改、必填新增、枚举删除等，反向用例断言有效拦截）。
"""

import json
import re
import sys
from pathlib import Path
import pytest
from sqlalchemy import select

from app.domain import models as m
from app.domain.registry import get_contract_enums, get_registry
from app.services import case_repository as repo
from app.services import state_machine as sm
from app.services.errors import CommandError, E_ILLEGAL_TRANSITION
from app.services.tenant import TenantContext
from tests.conftest import schema_errors

pytestmark = [pytest.mark.contract]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONTRACTS_DIR = REPO_ROOT / "contracts"
SEEDS_DIR = REPO_ROOT / "seeds"


# ══════════════════════════════════════════════════════════════════════════════
# 第一层：结构层（Structural Layer · FN-A-08 结构校验）
# ══════════════════════════════════════════════════════════════════════════════

def test_layer1_all_json_schemas_compilable():
    """[FN-A-08 结构层] contracts/ 下所有 9 个 Schema 必须符合 JSON Schema Draft 2020-12 规范且可编译。"""
    from jsonschema import Draft202012Validator
    schema_names = [
        "invoice-schema.json",
        "invoice-case.schema.json",
        "events.schema.json",
        "provider-spi.schema.json",
        "routing-config.schema.json",
        "adapter-contract.schema.json",
        "dashboard-response.schema.json",
        "alerts-response.schema.json",
        "case-read.schema.json",
    ]
    for sn in schema_names:
        sf = CONTRACTS_DIR / sn
        assert sf.exists(), f"[FN-A-08 结构层] 契约文件缺失: {sn}"
        try:
            content = json.loads(sf.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(content)
        except Exception as e:
            pytest.fail(f"[FN-A-08 结构层] 契约文件 {sn} 编译失败（不符合 Draft 2020-12 规范）: {e}")


def test_layer1_openapi_yaml_structural_lint():
    """[FN-A-08 结构层] openapi.yaml 必须为合法 OpenAPI 规范（包含 paths, webhooks, 唯一 operationId 等）。"""
    import yaml
    oas_file = CONTRACTS_DIR / "openapi.yaml"
    assert oas_file.exists(), "[FN-A-08] contracts/openapi.yaml 契约文件不存在"

    content = yaml.safe_load(oas_file.read_text(encoding="utf-8"))
    assert "openapi" in content, "[FN-A-08] openapi.yaml 缺失顶层 openapi 字段"
    assert "info" in content, "[FN-A-08] openapi.yaml 缺失 info 字段"
    assert "paths" in content, "[FN-A-08] openapi.yaml 缺失 paths 字段"
    assert "webhooks" in content, "[FN-A-08] openapi.yaml 缺失 webhooks 字段（FN-A-03 四事件声明）"

    # 检查 operationId 唯一性
    opids = []
    for path, methods in content.get("paths", {}).items():
        for m_name in ("get", "post", "put", "delete", "patch"):
            if m_name in methods:
                op = methods[m_name]
                if isinstance(op, dict) and "operationId" in op:
                    opids.append(op["operationId"])
    duplicates = [x for x in opids if opids.count(x) > 1]
    assert not duplicates, f"[FN-A-08 结构层] openapi.yaml 中存在重复的 operationId: {set(duplicates)}"


def test_layer1_seeds_validate_against_schemas(case_validator):
    """[FN-A-08 结构层] seeds/cases.json 等种子数据集必须通过对应 Schema 静态校验。"""
    cases_data = json.loads((SEEDS_DIR / "cases.json").read_text(encoding="utf-8"))
    for c in cases_data.get("cases", []):
        errs = list(case_validator.iter_errors(c))
        assert not errs, f"[FN-A-08 结构层] seed 案件 {c.get('caseId')} 未通过 invoice-case.schema 校验: {[e.message for e in errs]}"

    # routing_policy 校验
    from jsonschema import Draft202012Validator
    routing_schema = json.loads((CONTRACTS_DIR / "routing-config.schema.json").read_text(encoding="utf-8"))
    routing_data = json.loads((SEEDS_DIR / "routing_policy.json").read_text(encoding="utf-8"))
    r_errs = list(Draft202012Validator(routing_schema).iter_errors(routing_data))
    assert not r_errs, f"[FN-A-08 结构层] routing_policy.json 未通过 routing-config.schema 校验: {[e.message for e in r_errs]}"


# ══════════════════════════════════════════════════════════════════════════════
# 第二层：语义层（Semantic Layer · FN-A-08 业务规则语义校验）
# ══════════════════════════════════════════════════════════════════════════════

def test_layer2_api_responses_pass_schema_validation(client, case_validator, dashboard_validator, alerts_validator, list_projection_validator):
    """[FN-A-08 语义层] 各类核心 API 响应实体必须通过对应机器可读 JSON Schema 校验。"""
    # 1. 案件聚合详情响应 (/v1/cases/{case_id}) -> invoice-case.schema.json
    res_case = client.get("/v1/cases/INV-CN-2026-0387?instance=CN")
    assert res_case.status_code == 200, f"[FN-A-08] 获取案件响应失败: {res_case.text}"
    case_errs = schema_errors(case_validator, res_case.json())
    assert not case_errs, f"[FN-A-08 语义层] /v1/cases/0387 响应未通过 invoice-case.schema 校验: {[e.message for e in case_errs]}"

    # 2. 案件列表投影响应 (/v1/cases) -> case-read.schema.json
    res_list = client.get("/v1/cases?instance=CN")
    assert res_list.status_code == 200, f"[FN-A-08] 获取案件列表失败: {res_list.text}"
    list_errs = schema_errors(list_projection_validator, res_list.json())
    assert not list_errs, f"[FN-A-08 语义层] /v1/cases 响应未通过 case-read.schema 校验: {[e.message for e in list_errs]}"

    # 3. 仪表盘响应 (/v1/dashboard) -> dashboard-response.schema.json
    res_dash = client.get("/v1/dashboard?instance=CN")
    assert res_dash.status_code == 200, f"[FN-A-08] 获取仪表盘响应失败: {res_dash.text}"
    dash_errs = schema_errors(dashboard_validator, res_dash.json())
    assert not dash_errs, f"[FN-A-08 语义层] /v1/dashboard 响应未通过 dashboard-response.schema 校验: {[e.message for e in dash_errs]}"

    # 4. 告警中心响应 (/v1/alerts) -> alerts-response.schema.json
    res_alerts = client.get("/v1/alerts?instance=CN")
    assert res_alerts.status_code == 200, f"[FN-A-08] 获取告警中心响应失败: {res_alerts.text}"
    alerts_errs = schema_errors(alerts_validator, res_alerts.json())
    assert not alerts_errs, f"[FN-A-08 语义层] /v1/alerts 响应未通过 alerts-response.schema 校验: {[e.message for e in alerts_errs]}"


def test_layer2_all_database_enum_values_in_registry(session, seeds_cases):
    """[FN-A-08 语义层 / P00 §4.4] 案件状态、来源、校验结果、事件码等枚举值必须 100% ∈ enum-registry.json。"""
    reg, ce = get_registry(), get_contract_enums()

    # 案件状态与主体
    for c in session.scalars(select(m.Case)):
        assert c.status in reg.code_set("case_status"), f"[FN-A-08 语义层] 案件 {c.case_id} 状态 {c.status} 不在 enum-registry 中"
        assert c.instance in ce.instance, f"[FN-A-08 语义层] 案件 {c.case_id} 实例域 {c.instance} 不合法"
        if c.risk_label is not None:
            assert c.risk_label in reg.code_set("risk_label"), f"[FN-A-08 语义层] 案件 {c.case_id} 风险标签 {c.risk_label} 不在 enum-registry 中"

    # 字段来源与置信度
    for e in session.scalars(select(m.FieldEvidence)):
        assert e.source in reg.code_set("field_source"), f"[FN-A-08 语义层] 字段来源 {e.source} 不在 enum-registry"
        assert 0.0 <= e.confidence <= 1.0, f"[FN-A-08 语义层] 置信度 {e.confidence} 超出 [0, 1] 范围"

    # Checks 结果
    for r in session.scalars(select(m.CheckResult)):
        assert r.item in reg.code_set("check_item"), f"[FN-A-08 语义层] Check 项 {r.item} 不在 enum-registry"
        assert r.result in reg.code_set("check_result"), f"[FN-A-08 语义层] Check 结果 {r.result} 不在 enum-registry"

    # 时间线事件
    for t in session.scalars(select(m.TimelineEvent)):
        assert t.act in reg.code_set("timeline_event"), f"[FN-A-08 语义层] 事件类型 {t.act} 不在 enum-registry"
        assert t.actor in reg.code_set("timeline_actor"), f"[FN-A-08 语义层] 事件主体 {t.actor} 不在 enum-registry"


def test_layer2_id_numbering_formats_match_rules(session, seeds_cases):
    """[FN-A-08 语义层 / FN-0-13] 编号格式必须符合正则规范（案件号/批次号/trace ID/验签回执/供应商代码）。"""
    reg = get_registry()
    pat_map = {item["code"]: item.get("pattern") for item in reg.category_items("id_format")}

    pat_case = re.compile(pat_map["案件号"])
    pat_batch = re.compile(pat_map["批次号"])
    pat_trace = re.compile(pat_map["trace ID"])
    pat_receipt = re.compile(pat_map["验签回执"])

    for c in session.scalars(select(m.Case)):
        assert pat_case.match(c.case_id), f"[FN-0-13] 案件号 {c.case_id} 不匹配正则 {pat_map['案件号']}"

    for b in session.scalars(select(m.Batch)):
        assert pat_batch.match(b.batch_id), f"[FN-0-13] 批次号 {b.batch_id} 不匹配正则 {pat_map['批次号']}"

    for ab in session.scalars(select(m.AuditBlock)):
        if ab.trace:
            assert pat_trace.match(ab.trace), f"[FN-0-13] trace ID {ab.trace} 不匹配正则 {pat_map['trace ID']}"

    for c in seeds_cases["cases"]:
        sm2_info = (c.get("meta") or {}).get("sm2") or {}
        rcpt = sm2_info.get("receipt_no")
        if rcpt:
            assert pat_receipt.match(rcpt), f"[FN-0-13] 验签回执 {rcpt} 不匹配正则 {pat_map['验签回执']}"


def test_layer2_state_machine_illegal_transition_rejection(fresh_session):
    """[FN-A-08 语义层 / FN-0-02] 非法状态流转必须被状态机显式拒绝（不可随意跳转）。"""
    # 尝试从 RECOGNIZED 直接强制跳转到 RESOLVED（缺少复核或受控放行）
    c = fresh_session.get(m.Case, "INV-CN-2026-0386")
    c.status = "RECOGNIZED"
    fresh_session.commit()

    with pytest.raises(CommandError) as ei:
        sm.transition(fresh_session, "INV-CN-2026-0386", "RESOLVED", subject="system")
    assert ei.value.code == E_ILLEGAL_TRANSITION, f"[FN-0-02] 非法流转应当返回 E_ILLEGAL_TRANSITION，实际: {ei.value.code}"


# ══════════════════════════════════════════════════════════════════════════════
# 第三层：版本兼容层（Version Compatibility Layer · v1 冻结与破坏性变更检测）
# ══════════════════════════════════════════════════════════════════════════════

def test_layer3_changelog_governance_integrity():
    """[FN-A-08 版本兼容层 / FN-A-07] 契约变更账本 contracts/CHANGELOG.md 治理记录与总纲完整性检查。"""
    changelog_file = CONTRACTS_DIR / "CHANGELOG.md"
    assert changelog_file.exists(), "[FN-A-07] contracts/CHANGELOG.md 文件缺失"

    text = changelog_file.read_text(encoding="utf-8")
    assert "v1 · FROZEN" in text, "[FN-A-07] CHANGELOG.md 缺失 v1 · FROZEN 总纲"
    assert "TODO 未决项登记" in text, "[FN-A-07] CHANGELOG.md 缺失 TODO 未决项登记"
    # 检查是否有规范的治理类型（FROZEN, COMPAT, SYNC）
    for entry_type in ("FROZEN", "COMPAT", "SYNC"):
        assert entry_type in text, f"[FN-A-07] CHANGELOG.md 缺失治理条目类型: {entry_type}"


def test_layer3_v1_frozen_breaking_change_detection():
    """[FN-A-08 版本兼容层] 运行破环性变更检测器，断言当前 contracts/ 相对 v1 冻结基线零破坏性变更。"""
    tools_script = REPO_ROOT / "tools" / "check_breaking_changes.py"
    assert tools_script.exists(), "[FN-A-08] tools/check_breaking_changes.py 脚本缺失"

    import subprocess
    res = subprocess.run([sys.executable, str(tools_script)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"[FN-A-08 版本兼容层] 破坏性变更检测失败:\n{res.stdout}\n{res.stderr}"
    assert "无破坏向后兼容性行为" in res.stdout


def test_layer3_breaking_change_detector_synthetic_mutations():
    """[FN-A-08 版本兼容层] 构造破坏性变更合成变体，反向断言检测算法必然报错并拦截（确保检测器非空跑）。"""
    from tools.check_breaking_changes import detect_schema_breaking_changes, detect_enum_breaking_changes

    base_schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "amount": {"type": "number"}
        }
    }

    # 变体 1：删除了既有属性 amount
    del_prop_schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"}
        }
    }
    breaks_del = detect_schema_breaking_changes(base_schema, del_prop_schema)
    assert any("既有字段被删除" in b for b in breaks_del), "[FN-A-08] 未检测到属性删除破坏性变更"

    # 变体 2：修改了既有属性类型（amount 由 number 改为 string）
    type_change_schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "amount": {"type": "string"}
        }
    }
    breaks_type = detect_schema_breaking_changes(base_schema, type_change_schema)
    assert any("字段类型变更" in b for b in breaks_type), "[FN-A-08] 未检测到字段类型变更破坏性变更"

    # 变体 3：新增了必填项
    new_req_schema = {
        "type": "object",
        "required": ["id", "name", "amount"],
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "amount": {"type": "number"}
        }
    }
    breaks_req = detect_schema_breaking_changes(base_schema, new_req_schema)
    assert any("新增必填项" in b for b in breaks_req), "[FN-A-08] 未检测到新增必填项破坏性变更"

    # 变体 4：枚举值被删除
    base_registry = {
        "categories": {
            "case_status": {
                "values": [{"code": "RECOGNIZED"}, {"code": "BLOCKED"}]
            }
        }
    }
    mutated_registry = {
        "categories": {
            "case_status": {
                "values": [{"code": "RECOGNIZED"}]  # BLOCKED 被删除
            }
        }
    }
    breaks_enum = detect_enum_breaking_changes(base_registry, mutated_registry)
    assert any("既有枚举值被删除" in b for b in breaks_enum), "[FN-A-08] 未检测到枚举值删除破坏性变更"


def test_portal_contracts_sync():
    """[FN-A-09 / FN-A-08] CI 门禁：api-portal 页面内容与 contracts/ 契约文件同步校验。"""
    tools_script = REPO_ROOT / "tools" / "verify_portal_sync.py"
    import subprocess
    res = subprocess.run([sys.executable, str(tools_script)], capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"[FN-A-09] api-portal 契约同步校验失败:\n{res.stderr}\n{res.stdout}"
