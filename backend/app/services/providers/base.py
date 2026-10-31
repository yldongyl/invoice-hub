# -*- coding: utf-8 -*-
"""Provider SPI 南向插拔契约基类与归一化校验器（FN-A-05 · FN-2-02/13）。

契约依据：
  - invoice-hub/contracts/provider-spi.schema.json
  - 核心原则：任何 Provider（百望云、诺诺、客户自有 OCR、自托管 VLM、海外 e-invoicing、人工兜底）
    只需实现 capabilities, recognize, verify（可选）三方法，不改平台内核；
  - Provider 输出必须归一化为 ProviderResult 后进入内核（FN-2-13）；
  - 字段来源限制为 enum-registry.field_source 六枚举（xml_direct/ocr/qr_code/model/manual/webhook）；
  - 商业 Provider 一律 SPI stub 演示口径（实施规划 §6）。
"""

from abc import ABC, abstractmethod
import json
from pathlib import Path
from typing import Any

import jsonschema

# 契约 Schema 路径
CONTRACTS_DIR = Path(__file__).resolve().parents[4] / "contracts"
SPI_SCHEMA_PATH = CONTRACTS_DIR / "provider-spi.schema.json"

_spi_schema: dict | None = None
_validator_cap: jsonschema.Draft202012Validator | None = None
_validator_res: jsonschema.Draft202012Validator | None = None
_validator_ver: jsonschema.Draft202012Validator | None = None


def _get_validators():
    global _spi_schema, _validator_cap, _validator_res, _validator_ver
    if _spi_schema is None:
        with open(SPI_SCHEMA_PATH, "r", encoding="utf-8") as f:
            _spi_schema = json.load(f)
        defs = _spi_schema.get("$defs", {})
        _validator_cap = jsonschema.Draft202012Validator(schema=defs["CapabilitiesDeclaration"])
        _validator_res = jsonschema.Draft202012Validator(schema=defs["ProviderResult"])
        _validator_ver = jsonschema.Draft202012Validator(schema=defs["VerifyResult"])
    return _validator_cap, _validator_res, _validator_ver


def validate_capabilities(data: dict) -> list[str]:
    """校验能力声明是否合乎 CapabilitiesDeclaration 契约，返回错误列表。"""
    v_cap, _, _ = _get_validators()
    errors = []
    for err in v_cap.iter_errors(data):
        loc = ".".join(str(p) for p in err.path) if err.path else "root"
        errors.append(f"{loc}: {err.message}")
    return errors


def validate_recognize_result(data: dict) -> list[str]:
    """校验识别归一化结果是否合乎 ProviderResult 契约，返回错误列表。"""
    _, v_res, _ = _get_validators()
    errors = []
    for err in v_res.iter_errors(data):
        loc = ".".join(str(p) for p in err.path) if err.path else "root"
        errors.append(f"{loc}: {err.message}")
    return errors


def validate_verify_result(data: dict) -> list[str]:
    """校验查验结果是否合乎 VerifyResult 契约，返回错误列表。"""
    _, _, v_ver = _get_validators()
    errors = []
    for err in v_ver.iter_errors(data):
        loc = ".".join(str(p) for p in err.path) if err.path else "root"
        errors.append(f"{loc}: {err.message}")
    return errors


class BaseProvider(ABC):
    """Provider SPI 南向抽象基类。"""

    provider_id: str
    display_name: str
    provider_label: str
    deploy_mode: str

    @abstractmethod
    def capabilities(self) -> dict[str, Any]:
        """返回能力声明字典（必须过 CapabilitiesDeclaration 校验）。"""
        pass

    @abstractmethod
    def recognize(self, payload: dict[str, Any]) -> dict[str, Any]:
        """识别入口：接受 RecognizePayload，返回归一化 ProviderResult。"""
        pass

    def verify(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """查验入口：接受 VerifyPayload，返回 VerifyResult。非查验类 Provider 返回 None。"""
        return None
