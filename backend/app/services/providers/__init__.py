# -*- coding: utf-8 -*-
"""Provider 注册表与 SPI 实例映射（FN-2-02 · FN-A-05）。"""

from typing import Optional
from app.services.providers.base import BaseProvider
from app.services.providers.bwyun import BaiwangYunProvider
from app.services.providers.nuonuo import NuonuoProvider
from app.services.providers.customer_ocr import CustomerOcrProvider
from app.services.providers.selfhosted_vlm import SelfhostedVlmProvider
from app.services.providers.overseas_einv import OverseasEInvoicingProvider
from app.services.providers.human_fallback import HumanFallbackProvider

_PROVIDERS: dict[str, BaseProvider] = {
    "bwyun-cn": BaiwangYunProvider(),
    "nuonuo-cn": NuonuoProvider(),
    "customer-ocr": CustomerOcrProvider(),
    "selfhosted-ocr-vlm": SelfhostedVlmProvider(),
    "overseas-einv-sg": OverseasEInvoicingProvider(),
    "human-fallback": HumanFallbackProvider(),
}


def get_provider(provider_id: str) -> Optional[BaseProvider]:
    """获取指定 Provider SPI 实例。"""
    return _PROVIDERS.get(provider_id)


def list_spi_providers() -> list[BaseProvider]:
    """获取全部 6 个 Provider SPI 实例列表。"""
    return list(_PROVIDERS.values())
