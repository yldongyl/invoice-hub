# -*- coding: utf-8 -*-
"""领域模型（WP1.2 · FN-0-01/03/04/10 数据契约的持久化形态）。

设计口径：
  - 复杂子结构（meta/checks/links/items/file/ai/nextAction/evidence/timeline）以 raw_json
    逐字快照列承载（= contracts/invoice-case.schema.json 契约形态，保障聚合重建逐字一致），
    同时把「需要查询/校验」的键投影为结构化列（字段级证据按 field 查、Link 按类型查、
    状态/风险/租户维度过滤）——双层一致由 seed_loader 装载时强制校验，禁止旁路写投影列。
  - 枚举字段一律经 domain/registry.py 引用 enum-registry/契约内联枚举校验，禁止字面量散落
    （依赖纪律第 4 条）。
  - 五类 Link 词表 = enum-registry.link_type（v1.1.0 增补，值源清单 FN-0-04 原文；
    M1 门禁 MINOR M-M1-002 于 M2 关闭——原硬编码常量改为 registry 引用）。
  - Batch/FileIntake/Provider/Policy/MappingRule 为接口位（WP1.2 仅建模与装载，业务行为在 M3/M4）。
  - AuditBlock：append-only（WORM 语义）——仓储层只暴露 insert/读取，无 update/delete API
    （完整性校验与哈希链实装属 WP1.4，本阶段装载 seeds 短哈希展示口径逐字保留）。
"""

from sqlalchemy import (JSON, Boolean, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.registry import get_registry
from app.services.persistence import Base


def link_types() -> tuple:
    """五类 Link 词表（FN-0-04）——enum-registry.link_type 运行时引用（M-M1-002 关闭）。"""
    return tuple(get_registry().category("link_type"))


class Case(Base):
    """InvoiceCase 持久化案件（FN-0-01）；status 只存顶层，meta 不再冗余状态位（契约口径）。"""

    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    detail_level: Mapped[str] = mapped_column(String(10))           # full | list（契约内联）
    status: Mapped[str] = mapped_column(String(20), index=True)     # enum-registry.case_status
    summary: Mapped[str | None] = mapped_column(Text)
    instance: Mapped[str] = mapped_column(String(2), index=True)    # 契约 meta.instance（CN|OS）
    # —— meta 投影列（列表/过滤/聚合查询用）——
    region: Mapped[str | None] = mapped_column(String(40))
    ext: Mapped[str | None] = mapped_column(String(60))
    invoice_type: Mapped[str | None] = mapped_column(String(60))
    po: Mapped[str | None] = mapped_column(String(40))
    supplier: Mapped[str | None] = mapped_column(String(120), index=True)
    supplier_id: Mapped[str | None] = mapped_column(String(12))
    amount_display: Mapped[str | None] = mapped_column(String(40))
    currency: Mapped[str | None] = mapped_column(String(3))
    invoice_amount: Mapped[float | None] = mapped_column(Float)
    po_amount: Mapped[float | None] = mapped_column(Float)
    variance: Mapped[float | None] = mapped_column(Float)
    risk_label: Mapped[str | None] = mapped_column(String(40), index=True)
    confidence: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(60))
    channel: Mapped[str | None] = mapped_column(String(80))
    adapter: Mapped[str | None] = mapped_column(String(80))
    trace_id: Mapped[str | None] = mapped_column(String(12), index=True)
    claimed_by: Mapped[str | None] = mapped_column(String(60))
    claimed_at: Mapped[str | None] = mapped_column(String(30))
    doc_hold_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # 装载序（seeds/cases.json 原始顺序，0 起）——case-detail 切换器/聚合排序稳定源（M2 WP2.1）
    load_seq: Mapped[int] = mapped_column(Integer, default=0)
    # —— 契约子结构逐字快照 ——
    meta_raw: Mapped[dict] = mapped_column(JSON)
    facts_raw: Mapped[dict] = mapped_column(JSON)
    checks_raw: Mapped[dict | None] = mapped_column(JSON)
    links_raw: Mapped[dict | None] = mapped_column(JSON)
    items_raw: Mapped[dict | None] = mapped_column(JSON)
    file_raw: Mapped[dict | None] = mapped_column(JSON)
    ai_raw: Mapped[dict | None] = mapped_column(JSON)
    next_action_raw: Mapped[dict | None] = mapped_column(JSON)
    source_xml: Mapped[str | None] = mapped_column(Text)
    paper_template: Mapped[str | None] = mapped_column(String(10))
    # 种子原始顶层键集（list/full 案件键集不同构，聚合重建须按原始存在性还原，保证逐字段深比对）
    seed_keys: Mapped[list] = mapped_column(JSON, default=list)


class FieldEvidence(Base):
    """字段级证据（FN-0-05 最小数据契约）：每字段=值+证据，可按字段查询。"""

    __tablename__ = "field_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(60), index=True)      # 统一 Schema 路径（FN-0-03）
    source: Mapped[str] = mapped_column(String(16))                 # field_source 六枚举
    confidence: Mapped[float] = mapped_column(Float)                # [0,1]
    evidence_raw: Mapped[dict] = mapped_column(JSON)                # 契约 evidenceEntry 逐字


class CheckResult(Base):
    """四校验结果（FN-0-07 · 只由规则引擎写入——本阶段仅装载/读取）。"""

    __tablename__ = "check_results"
    __table_args__ = (UniqueConstraint("case_id", "item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    item: Mapped[str] = mapped_column(String(20))                   # check_item 四值
    result: Mapped[str] = mapped_column(String(20))                 # check_result 四值
    note: Mapped[str] = mapped_column(Text)


class TimelineEvent(Base):
    """案件时间线事件（FN-0-10 {t,a,act,d,x,v}；投影自审计链，双写口径）。"""

    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    t: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(10))                  # timeline_actor 四枚举
    act: Mapped[str] = mapped_column(String(40), index=True)        # timeline_event 事件码
    event_raw: Mapped[dict] = mapped_column(JSON)                   # events.schema 逐字


class ObjectLink(Base):
    """可查询、可校验的结构化关系（FN-0-04）；词表=清单五类中文名。"""

    __tablename__ = "object_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    link_type: Mapped[str] = mapped_column(String(8), index=True)   # enum-registry.link_type 五值
    ref: Mapped[str | None] = mapped_column(String(60))             # 关系目标（po/grn/案件号/供应商）
    po_state: Mapped[str | None] = mapped_column(String(20))        # 匹配态（check_result 同源）
    link_raw: Mapped[dict] = mapped_column(JSON)


class Batch(Base):
    """批次（FN-1-06；BT-YYYYMMDD-NNN；M3 WP3.2 激活业务行为）。"""

    __tablename__ = "batches"

    batch_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    channel: Mapped[str] = mapped_column(String(20))                 # enum-registry.intake_channel
    instance_display: Mapped[str] = mapped_column(String(10))       # 页面口径 中国/海外
    files: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))                 # batch_status 枚举（存储态为合并前词汇，读侧归一）
    ok: Mapped[int] = mapped_column(Integer)
    err: Mapped[int] = mapped_column(Integer)
    filtered: Mapped[int] = mapped_column(Integer)
    time: Mapped[str] = mapped_column(String(10))
    # —— M3 运行期列（seed 行为 null；断点续跑检查点与 KPI 时延数据源）——
    created_ts: Mapped[str | None] = mapped_column(String(30))      # 批次受理时刻（ISO）
    instance: Mapped[str | None] = mapped_column(String(2))         # CN|OS（运行期批次租户归属）
    trace_id: Mapped[str | None] = mapped_column(String(12))


class FileIntake(Base):
    """批次文件级受理明细（FN-1-06；M3 运行期激活：摘要/载体/处置/时延列）。"""

    __tablename__ = "file_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.batch_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    file: Mapped[str] = mapped_column(String(120))
    case_id: Mapped[str | None] = mapped_column(String(20))
    status_snapshot: Mapped[str | None] = mapped_column(String(20))
    conf: Mapped[int | None] = mapped_column(Integer)
    intake_raw: Mapped[dict] = mapped_column(JSON)
    # —— M3 运行期列（seed 节选行为 null）——
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)   # 原件摘要（id_format.原件摘要）
    mime_type: Mapped[str | None] = mapped_column(String(60))
    disposition: Mapped[str | None] = mapped_column(String(20))          # intake_file_disposition 枚举
    carrier_route: Mapped[str | None] = mapped_column(String(20))        # carrier_route 枚举
    doc_type: Mapped[str | None] = mapped_column(String(30))             # non_invoice_doc_type（FILTERED 时）
    local_path: Mapped[str | None] = mapped_column(String(200))          # 对象存储本地目录（ADR-0002 PoC）
    accepted_ts: Mapped[str | None] = mapped_column(String(30))          # 接入时刻（KPI 时延起点）
    digest_ts: Mapped[str | None] = mapped_column(String(30))            # 摘要登记时刻（④完成）
    note: Mapped[str | None] = mapped_column(Text)


class IntakeLedger(Base):
    """原件摘要登记台账（FN-1-05④ 受理即登记；CON-05 业务层幂等键=sha256+target_doc_ref，
    同摘要+同目标单据不重复受理——409 返回既有案件）。"""

    __tablename__ = "intake_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    target_doc_ref: Mapped[str | None] = mapped_column(String(60))
    batch_id: Mapped[str] = mapped_column(String(16), index=True)
    file_seq: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[str | None] = mapped_column(String(20), index=True)
    channel: Mapped[str] = mapped_column(String(20))                    # intake_channel 枚举
    instance: Mapped[str] = mapped_column(String(2))
    trace_id: Mapped[str | None] = mapped_column(String(12))
    accepted_at: Mapped[str] = mapped_column(String(30))
    __table_args__ = (UniqueConstraint("sha256", "target_doc_ref", name="uq_intake_business_key"),)


class RequestIdLedger(Base):
    """传输层幂等台账（X-Request-Id，与业务层摘要键分离——CON-05/06；有效期=渠道配置幂等键 TTL）。"""

    __tablename__ = "request_id_ledger"

    request_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    case_id: Mapped[str | None] = mapped_column(String(20))
    batch_id: Mapped[str | None] = mapped_column(String(16))
    instance: Mapped[str | None] = mapped_column(String(2))
    response_raw: Mapped[dict | None] = mapped_column(JSON)             # 首发响应快照（重放同形返回）
    created_at: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[str] = mapped_column(String(30))


class FileStep(Base):
    """五步流水线步骤级状态持久化（FN-1-05 · 断点续跑检查点：每步一行，重跑仅续做未 DONE 步骤）。"""

    __tablename__ = "file_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(16), index=True)
    file_seq: Mapped[int] = mapped_column(Integer)
    step_no: Mapped[int] = mapped_column(Integer)                       # 1..5（流水线步序）
    status: Mapped[str] = mapped_column(String(12))                     # pipeline_step_status 枚举
    detail_raw: Mapped[dict | None] = mapped_column(JSON)               # 步骤结果快照（规则命中/载体/摘要/案件号）
    ts: Mapped[str] = mapped_column(String(30))
    __table_args__ = (UniqueConstraint("batch_id", "file_seq", "step_no", name="uq_file_step"),)


class EgressLog(Base):
    """数据最小外发台账（FN-5-08 演示口径：每次向 Provider/外部通道的载荷外发登记一行；
    直读路径必须零记录——E2E 断言「外发记录为零」的对照表）。"""

    __tablename__ = "egress_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(30))
    batch_id: Mapped[str | None] = mapped_column(String(16), index=True)
    file_seq: Mapped[int | None] = mapped_column(Integer)
    case_id: Mapped[str | None] = mapped_column(String(20))
    provider_id: Mapped[str] = mapped_column(String(60))                # stub Provider 标识（M4 实装同源）
    purpose: Mapped[str] = mapped_column(String(30))                    # recognize/verify/webhook…
    payload_digest: Mapped[str | None] = mapped_column(String(64))      # 外发内容 SHA-256（最小化：只发必要字段）
    bytes_out: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str | None] = mapped_column(Text)                      # 演示口径注记


class VerifyCache(Base):
    """同票查验结果缓存（FN-5-02：避免重复计费；键=CN/OS 查重业务键同源口径）。"""

    __tablename__ = "verify_cache"

    biz_key: Mapped[str] = mapped_column(String(120), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(20), index=True)
    result: Mapped[str] = mapped_column(String(20))                  # check_result 枚举
    detail: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[str] = mapped_column(String(30))


class ExportTicket(Base):
    """导出清单限时下载凭据（WP3.4 · FN-8-07/FN-0-08：导出行为自审计入链后发放；
    下载链接 24 小时失效——过期即 410，重导重新签发并重入链）。"""

    __tablename__ = "export_tickets"

    token: Mapped[str] = mapped_column(String(48), primary_key=True)
    actor: Mapped[str] = mapped_column(String(40))
    instance: Mapped[str | None] = mapped_column(String(2))
    filters_raw: Mapped[dict | None] = mapped_column(JSON)
    rows: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(80))
    created_ts: Mapped[str] = mapped_column(String(30))
    expires_ts: Mapped[str] = mapped_column(String(30))
    blk: Mapped[int | None] = mapped_column(Integer)          # 入链块高（链头断言用）
    trace: Mapped[str | None] = mapped_column(String(12))


class WebhookDelivery(Base):
    """Webhook 回调登记（FN-A-03 · 演示口径：本地 outbox 落盘替代真实外呼；
    消费方非 2xx 指数退避重试 ≤8 次=sla_targets.webhook_retry_max，消费者属 M4+）。"""

    __tablename__ = "webhook_deliveries"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event: Mapped[str] = mapped_column(String(30))                      # webhook_event 枚举
    case_id: Mapped[str] = mapped_column(String(20), index=True)
    delivered_to: Mapped[str | None] = mapped_column(String(200))       # callback_url（桩：落 outbox 文件）
    payload_raw: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str | None] = mapped_column(String(80))           # sha256=<hex>（HMAC 演示密钥）
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(12), default="queued")    # queued/delivered（演示桩即 outbox=已投递）
    ts: Mapped[str] = mapped_column(String(30))


class Provider(Base):
    """Provider 注册表（接口位 FN-2-02；SPI stub 实装在 M4）。"""

    __tablename__ = "providers"

    provider_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(60))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    lock: Mapped[bool] = mapped_column(Boolean, default=False)      # 人工兜底锁定不可停用
    provider_raw: Mapped[dict] = mapped_column(JSON)


class RoutingPolicy(Base):
    """路由/降级策略（接口位 FN-2-08/10；版本化发布属 WP1.8 框架复用）。"""

    __tablename__ = "routing_policies"

    version: Mapped[str] = mapped_column(String(30), primary_key=True)
    state: Mapped[str] = mapped_column(String(20))                  # draft | published
    policy_raw: Mapped[dict] = mapped_column(JSON)


class MappingRule(Base):
    """字段/税码映射规则（接口位 FN-6-07/08；税码行级版本 v1.4）。"""

    __tablename__ = "mapping_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_type: Mapped[str] = mapped_column(String(20), index=True)  # taxcode | field | link_candidate
    instance: Mapped[str | None] = mapped_column(String(4))
    src: Mapped[str | None] = mapped_column(String(80))
    dst: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[str | None] = mapped_column(String(12))
    rule_raw: Mapped[dict] = mapped_column(JSON)


class RuleCatalogEntry(Base):
    """规则标识注册表（FN-0-07/WP1.6 依据；rules_catalog.json 20 条，未注册=缺陷）。"""

    __tablename__ = "rule_catalog"

    rule_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    usage: Mapped[str] = mapped_column(Text)
    ref_version: Mapped[str | None] = mapped_column(String(40))
    machine_id_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    # 族级中文标识的机器 rule_id（M1 WP1.6 按 seed note 授权注册；登记前为 null）
    machine_id: Mapped[str | None] = mapped_column(String(60))


class ComponentVersion(Base):
    """组件版本清单（附录 B · 时间线 v 字段基线，versions.json）。"""

    __tablename__ = "component_versions"

    component: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[str | None] = mapped_column(String(30))  # 可空：ocr-vlm-2026-10 版本随 Provider 替换（附录 B）
    desc: Mapped[str | None] = mapped_column(Text)


class UserAccount(Base):
    """用户（RBAC 矩阵 M5 实装，本阶段建模+装载；权限桩引用 seeds/users_roles.json）。"""

    __tablename__ = "users"

    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    role: Mapped[str] = mapped_column(String(40))
    org: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10))
    user_raw: Mapped[dict] = mapped_column(JSON)


class RoleDef(Base):
    """角色与 4×7 权限位（FN-9-02）。"""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    who: Mapped[str | None] = mapped_column(String(60))
    grants: Mapped[list] = mapped_column(JSON)                      # 7 位权限向量


class AuditBlock(Base):
    """审计哈希链区块（FN-0-10 · append-only/WORM：仓储层不提供 update/delete）。"""

    __tablename__ = "audit_blocks"

    blk: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String(30))
    trace: Mapped[str | None] = mapped_column(String(12), index=True)
    actor: Mapped[str] = mapped_column(String(10))
    act: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str | None] = mapped_column(String(20))
    case_id: Mapped[str | None] = mapped_column(String(20), index=True)
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    op_component: Mapped[str | None] = mapped_column(String(80))
    hash_display: Mapped[str] = mapped_column(String(12))           # M0 短哈希展示口径逐字（页面口径，不参与链计算）
    prev_hash: Mapped[str | None] = mapped_column(String(64))       # 64hex 前块哈希（WP1.4 建链填充）
    chain_hash: Mapped[str | None] = mapped_column(String(64))      # 64hex 本块链式 SHA-256（WP1.4）
    instance: Mapped[str | None] = mapped_column(String(2))         # 双实例独立成链（FN-0-10/0-11）
    chain_scope: Mapped[str | None] = mapped_column(String(10))     # 链域 CN | OS | PLATFORM（无案件归属的平台事件独立成链，演示口径）


class Adapter(Base):
    """目标采购平台适配状态条（M2 新增，FN-7-01 呈现位 / 清单 §4.3 后台数据契约「Adapter 状态清单」；
    来源 seeds/adapters.json——dashboard 底部 5 行逐字。status_code ∈ enum-registry.adapter_status
    三值装载即校验；glyph 由聚合服务从 status_code 派生，不单独存列。adapter 全量治理属 M4 接线）。"""

    __tablename__ = "adapters"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    mode: Mapped[str | None] = mapped_column(String(60))               # 接口模式（cXML / AP Invoice Import…）
    status_text: Mapped[str] = mapped_column(String(20))               # 状态文案（已实联/适配中/规划中/已对接）
    status_code: Mapped[str] = mapped_column(String(20), index=True)   # adapter_status 三值
    display: Mapped[str] = mapped_column(String(80))                   # 页面小字逐字（模式 · 状态）
    load_seq: Mapped[int] = mapped_column(Integer, default=0)


class Alert(Base):
    """告警（dashboard 同源读模型；告警引擎分发在 M5）。"""

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance: Mapped[str] = mapped_column(String(2))
    level: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(80))
    case_ref: Mapped[str | None] = mapped_column(String(20))
    alert_raw: Mapped[dict] = mapped_column(JSON)


class KpiSnapshot(Base):
    """KPI 快照（FN-8-11；M2 起改聚合服务实时计算，本表承载 seed 口径）。"""

    __tablename__ = "kpi_snapshots"

    instance: Mapped[str] = mapped_column(String(2), primary_key=True)
    snapshot_raw: Mapped[dict] = mapped_column(JSON)


class ConfigItem(Base):
    """配置中心项（FN-9-09 · WP1.1 租户级覆盖模型 + 草稿/已发布双态接口位）。"""

    __tablename__ = "config_items"
    __table_args__ = (UniqueConstraint("scope", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), default="default")  # default | tenant:{id}
    key: Mapped[str] = mapped_column(String(60), index=True)
    label: Mapped[str | None] = mapped_column(String(80))
    value_raw: Mapped[dict] = mapped_column(JSON)                   # {value, ...其余键}
    state: Mapped[str] = mapped_column(String(12), default="published")  # draft|published（WP1.8）
    version: Mapped[str | None] = mapped_column(String(30))


class SeedMeta(Base):
    """装载代际标记（幂等重放与排障用）。"""

    __tablename__ = "seed_meta"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)


class IdCounter(Base):
    """编号发号器计数域（WP1.7 · FN-0-13）：分实例域/分日/分周递增，seed 播种现值。"""

    __tablename__ = "id_counters"

    domain: Mapped[str] = mapped_column(String(40), primary_key=True)   # case:CN / case:SG / batch:{inst}:{date} / gm_rcpt / qa:{y}-W{w} / anno:{y}
    seq: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str | None] = mapped_column(String(30))


class AssetRevision(Base):
    """版本化资产修订（WP1.8 · FN-0-12）：草稿/已发布双态、发布=版本递增+diff+旧版保留+可回滚。

    asset_type：config（本阶段接入）| routing_policy / mapping_table（M4 复用此框架）。
    """

    __tablename__ = "asset_revisions"
    __table_args__ = (UniqueConstraint("asset_type", "key", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_type: Mapped[str] = mapped_column(String(20), index=True)
    key: Mapped[str] = mapped_column(String(60), index=True)
    version: Mapped[str] = mapped_column(String(30))                    # v{YYYY-MM-DD}.{seq}
    state: Mapped[str] = mapped_column(String(12), default="draft")     # draft | published
    payload: Mapped[dict] = mapped_column(JSON)                         # 契约快照（{value,...}）
    diff_json: Mapped[dict | None] = mapped_column(JSON)                # 前值→后值（FN-9-09 diff 二次确认素材）
    prev_version: Mapped[str | None] = mapped_column(String(30))
    updated_by: Mapped[str | None] = mapped_column(String(40))
    updated_at: Mapped[str | None] = mapped_column(String(30))
    opinion: Mapped[str | None] = mapped_column(Text)                   # 发布时处置意见（未填落默认）


class ConfirmToken(Base):
    """受控写二次确认凭据（FN-0-08 要素③ · WP1.5）。

    演示口径：服务端签发、一次性、绑定 actor+action+目标、带过期；真实 MFA/会话绑定属 M5 身份交付
    （SSO/MFA 为演示桩，P00 §6）。
    """

    __tablename__ = "confirm_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(30), index=True)
    action: Mapped[str] = mapped_column(String(20))
    scope_ref: Mapped[str] = mapped_column(String(40))               # caseId 或 batch:{hash}
    issued_at: Mapped[str] = mapped_column(String(30))
    expires_at: Mapped[str] = mapped_column(String(30))
    consumed_at: Mapped[str | None] = mapped_column(String(30))


class VerifyRetryTask(Base):
    """断点续跑重试任务（FN-0-02/0-10 附带动作 · WP1.3 钩子；队列面板与真实消费在 M3/FN-9-07）。"""

    __tablename__ = "verify_retry_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    step: Mapped[str] = mapped_column(String(30))                    # verify_auth（只重试查验，不重跑识别）
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_run_at: Mapped[str | None] = mapped_column(String(30))
    state: Mapped[str] = mapped_column(String(12), default="queued")  # demo口径：queued/done（真实调度 M3）
    note: Mapped[str | None] = mapped_column(Text)


class VerifyRun(Base):
    """哈希链完整性校验登记（FN-0-10 · 校验人/校验时间/结果）。"""

    __tablename__ = "verify_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ran_at: Mapped[str] = mapped_column(String(30))
    verifier: Mapped[str] = mapped_column(String(40))
    scope: Mapped[str | None] = mapped_column(String(10))
    ok: Mapped[bool] = mapped_column(Boolean)
    bad_blk: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)
