# -*- coding: utf-8 -*-
"""确定性内核错误码（FN-0-08 缺任一要素→明确错误码；错误码非枚举注册表类别，
为内核 API 契约词汇，逐条对应 FN-0-08 要素/清单规则，禁止造词式随意新增）。"""


class CommandError(Exception):
    """业务/命令拒绝（HTTP 映射：权限 403、状态/要素 409/422、缺参 422、不存在 404）。"""

    def __init__(self, code: str, message: str, http: int = 422, details: dict | None = None):
        self.code = code
        self.message = message
        self.http = http
        self.details = details or {}
        super().__init__(f"{code}: {message}")


# 错误码词汇表（与文档条目对应关系在注释）
E_CASE_NOT_FOUND = "CASE_NOT_FOUND"            # §3 404
E_ILLEGAL_TRANSITION = "ILLEGAL_TRANSITION"    # FN-0-02 六态之外的流转
E_STATE_PRECONDITION = "STATE_PRECONDITION"    # FN-0-02 触发条件不满足
E_CLAIM_LOCKED = "CLAIM_LOCKED"                # CON-11 认领锁占用
E_PERM_DENIED = "E_PERM_DENIED"                # FN-0-08 要素① 权限位不足（FN-9-02 矩阵）
E_RISK_NOT_SHOWN = "E_RISK_NOT_SHOWN"          # FN-0-08 要素② 风险提示未经展示（缺确认凭据）
E_CONFIRM_INVALID = "E_CONFIRM_INVALID"        # FN-0-08 要素③ 二次确认凭据无效（过期/错绑/已消费）
E_SELF_CONFIRM_REQUIRED = "E_SELF_CONFIRM_REQUIRED"  # FN-0-08 要素③ 本人执行勾选缺失
E_OPINION_REQUIRED = "E_OPINION_REQUIRED"      # FN-0-08 要素④ 处置意见必填（拒绝/退回类）
E_AUDIT_WRITE_FAILED = "E_AUDIT_WRITE_FAILED"  # FN-0-08 要素⑤ 审计写失败→整笔回滚
E_COUNTERSIGN_REQUIRED = "E_COUNTERSIGN_REQUIRED"  # FN-0-02/FN-8-06 双人会签缺会签人
E_REDLINE_BLOCK = "E_REDLINE_BLOCK"            # FN-0-06/5-05 红线：低置信/验签失败禁止自动放行
E_REDLINE_BATCH = "E_REDLINE_BATCH"            # FN-0-08 BLOCKED 不可批量放行（跳过明细）
E_FIELD_NOT_FOUND = "E_FIELD_NOT_FOUND"        # FN-8-05 修正字段必须存在于证据链
E_EDIT_PARAM_REQUIRED = "E_EDIT_PARAM_REQUIRED"  # FN-8-05 新值+原因必填
E_EXPORT_PARAM = "E_EXPORT_PARAM"              # FN-8-07 导出需检索条件与行数留痕
