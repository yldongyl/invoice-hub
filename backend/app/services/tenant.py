# -*- coding: utf-8 -*-
"""租户上下文与四隔离（WP1.7 · FN-0-11/13）。

双实例（CN 中国 / OS 海外，取值=契约 meta.instance 枚举）；四隔离在本阶段的存储层实现：
  ① 数据：一切案件/证据/时间线/审计读写必须携带 TenantContext 并经 instance 维度过滤（本模块强制注入）；
  ② 配置：ConfigItem.scope（default | tenant:{id}）——config_center 读取路径已按 scope 隔离；
  ③ Provider Key：providers.json 的 regions 声明（M4 Provider 路由消费，接口位注记）；
  ④ 发票池：查重池按 instance 分池（WP1.6 dedup_business_key 按实例取键，M3 查重服务消费）。
所有查询与写入必须携带租户上下文——缺失即 E_TENANT_MISSING（P02 WP1.7），
跨实例访问即 E_TENANT_MISMATCH（越权拒绝）。

实例段映射（CON-04 决议）：案件号 INV-{CN|SG}-… → 实例 CN/OS；数据区域为派生展示字段（演示口径）。
"""

from dataclasses import dataclass

from app.domain.registry import get_contract_enums
from app.services.errors import E_TENANT_MISMATCH, E_TENANT_MISSING, CommandError

# 案件号实例域段 → 契约实例（CON-04 决议的映射，仅一处定义）
_SEGMENT_TO_INSTANCE = {"CN": "CN", "SG": "OS"}


@dataclass(frozen=True)
class TenantContext:
    instance: str          # CN | OS（契约 meta.instance）
    region: str            # 数据区域展示字段（演示口径，源自 kpi 实例 label 语义）
    tenant_id: str         # FN-0-13 租户 ID 口径（演示桩，正式注册属 FN-9-01/M5）

    @classmethod
    def of(cls, instance: str | None) -> "TenantContext":
        allowed = get_contract_enums().instance
        if not instance:
            raise CommandError(E_TENANT_MISSING,
                               "缺少租户上下文：所有查询与写入必须携带 instance（CN|OS）（FN-0-11/WP1.7）",
                               http=400)
        if instance not in allowed:
            raise CommandError(E_TENANT_MISSING,
                               f"instance {instance!r} 不在契约取值域 {sorted(allowed)}", http=400)
        region = {"CN": "CN · 境内存储（数据驻留细则 TODO(H39) 推断标注）",
                  "OS": "APAC · 新加坡区域（0918 已验证实例）"}[instance]
        tenant_id = {"CN": "TENANT-CN-LANWU-001", "OS": "TENANT-SG-LANWU-001"}[instance]
        return cls(instance=instance, region=region, tenant_id=tenant_id)

    @classmethod
    def of_case_id(cls, case_id: str) -> "TenantContext":
        seg = case_id[4:6] if case_id and case_id.startswith("INV-") else None
        inst = _SEGMENT_TO_INSTANCE.get(seg)
        if inst is None:
            raise CommandError(E_TENANT_MISMATCH, f"案件号 {case_id!r} 实例域段无法解析", http=403)
        return cls.of(inst)

    def assert_matches_case_id(self, case_id: str):
        """四隔离①数据：按 ID 取数时上下文必须与案件归属实例一致，否则越权拒绝。"""
        own = TenantContext.of_case_id(case_id)
        if own.instance != self.instance:
            raise CommandError(E_TENANT_MISMATCH,
                               f"租户越权：上下文实例 {self.instance} 无权访问归属 {own.instance} 的案件 {case_id}",
                               http=403)
        return own

    def scope(self) -> str:
        """配置隔离 scope 键（FN-0-11 四隔离②，与 config_center 读取路径对接）。"""
        return f"tenant:{self.tenant_id}"
