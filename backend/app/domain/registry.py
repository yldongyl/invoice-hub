# -*- coding: utf-8 -*-
"""enum-registry / 契约内联枚举加载器（FN-0-15 · 依赖纪律第 4 条）。

全站枚举唯一来源 = contracts/enum-registry.json；契约 Schema 内联枚举（instance、
credit_note.relation、items.layout、ai.status、paper_template 等）来源 = contracts/*.schema.json。
本模块禁止任何业务代码散落枚举字面量：一律经 get_registry()/get_contract_enums() 引用，
写入前用 EnumRegistry.validate(category, value) 校验，违例抛 EnumViolation。
"""

import json
import os
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/app/domain -> invoice-hub/
CONTRACTS_DIR = REPO_ROOT / "contracts"
SEEDS_DIR = REPO_ROOT / "seeds"


class EnumViolation(ValueError):
    """枚举值不在注册表/契约取值域（P00 §4 依赖纪律红线）。"""


class EnumRegistry:
    """contracts/enum-registry.json 的只读视图（25 类 / 142 值，v1.2.0；受理域 5 类为 M3 增补）。"""

    def __init__(self, data: dict):
        self._data = data
        self._codes = {
            cat: [v["code"] for v in spec["values"]]
            for cat, spec in data["categories"].items()
        }
        self._patterns = {
            v["code"]: v.get("pattern")
            for v in data["categories"].get("id_format", {}).get("values", [])
        }

    @property
    def version(self):
        return self._data["version"]

    def category(self, name):
        if name not in self._codes:
            raise EnumViolation(f"未知枚举类别: {name}")
        return self._codes[name]

    def category_items(self, name):
        """完整取值条目（含 label/附注等），供规则/状态机消费定义文本（禁止代码内重写触发条件）。"""
        if name not in self._data["categories"]:
            raise EnumViolation(f"未知枚举类别: {name}")
        return self._data["categories"][name]["values"]

    def code_set(self, name):
        return set(self.category(name))

    def validate(self, category: str, value, *, where: str = ""):
        if value is None:
            raise EnumViolation(f"{category} 不允许 None（{where}）")
        allowed = self._codes.get(category)
        if allowed is None:
            raise EnumViolation(f"未知枚举类别: {category}")
        if value not in allowed:
            raise EnumViolation(
                f"{where or category}: 值 {value!r} 不在 {category} 取值域 {allowed}（enum-registry v{self.version}）")
        return value

    def id_pattern(self, code: str):
        """FN-0-13 编号规则 pattern（案件号/批次/trace/gm-rcpt/SUP/租户/QA/ANNO）。"""
        p = self._patterns.get(code)
        if p is None:
            raise EnumViolation(f"编号规则 {code!r} 未在 id_format 注册")
        return p


class ContractEnums:
    """契约 Schema 内联枚举（非注册表类别）的只读视图。"""

    def __init__(self, case_schema: dict, events_schema: dict):
        props = case_schema["properties"]
        defs = case_schema["$defs"]
        self.case_id_pattern = props["caseId"]["pattern"]
        self.case_status = set(props["status"]["enum"])          # 与 registry.case_status 交叉校验
        self.detail_level = set(props["detail_level"]["enum"])   # full | list
        self.instance = set(props["meta"]["properties"]["instance"]["enum"])  # CN | OS
        self.check_result = set(defs["checkResult"]["properties"]["result"]["enum"])
        self.field_source = set(defs["evidenceEntry"]["properties"]["source"]["enum"])
        self.credit_relation = set(
            props["links"]["properties"]["credit_note"]["properties"]["relation"]["enum"])
        self.items_layout = set(props["items"]["properties"]["layout"]["enum"])
        self.paper_template = set(props["paper_template"]["enum"])  # 含 null
        self.ai_status = set(props["ai"]["properties"]["status"]["enum"])
        self.timeline_event = set(events_schema["properties"]["act"]["enum"])
        self.timeline_actor = set(events_schema["properties"]["a"]["enum"])


_registry = None
_contract_enums = None
# 可重入锁：get_contract_enums 的交叉自检会回调 get_registry
_lock = threading.RLock()


def _load_json(name: str) -> dict:
    path = CONTRACTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"契约文件缺失: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_registry() -> EnumRegistry:
    global _registry
    with _lock:
        if _registry is None:
            _registry = EnumRegistry(_load_json("enum-registry.json"))
        return _registry


def get_contract_enums() -> ContractEnums:
    global _contract_enums
    with _lock:
        if _contract_enums is None:
            ce = ContractEnums(
                _load_json("invoice-case.schema.json"), _load_json("events.schema.json"))
            _cross_check(ce)
            _contract_enums = ce
        return _contract_enums


def _cross_check(ce: ContractEnums):
    """启动自检：契约内联枚举必须是 enum-registry 对应类别的子集（validate_contracts D 段运行期镜像）。

    漂移即拒绝——保证运行期枚举单一来源（依赖纪律第 4 条 / CON-B1）。
    注：contract 内联为「子集」而非全等，因为内联只取实际使用值，registry 为全站完整字典。
    """
    reg = get_registry()
    pairs = [("case_status", ce.case_status), ("field_source", ce.field_source),
             ("check_result", ce.check_result), ("timeline_event", ce.timeline_event),
             ("timeline_actor", ce.timeline_actor)]
    for cat, vals in pairs:
        drift = vals - reg.code_set(cat)
        if drift:
            raise EnumViolation(f"契约内联枚举 {cat} 与 enum-registry 漂移: {sorted(drift)}")
