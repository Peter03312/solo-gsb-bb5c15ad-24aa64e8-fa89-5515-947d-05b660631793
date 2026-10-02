"""请求/响应模型。时间一律要求带时区（AwareDatetime），入库前归一化为 UTC。"""
from datetime import datetime
from typing import Literal, Optional

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator


def _clean_allergens(values: list[str]) -> list[str]:
    cleaned = sorted({v.strip() for v in values if v and v.strip()})
    return cleaned


class MaterialCreate(BaseModel):
    batch_id: str = Field(min_length=1)
    allergens: list[str] = []
    pending: bool = False
    declared_at: Optional[AwareDatetime] = None  # 缺省取服务器当前时间

    @field_validator("allergens")
    @classmethod
    def _v_allergens(cls, v):
        return _clean_allergens(v)


class DeclarationCreate(BaseModel):
    """原料声明更正：追加一个新版本，当前有效声明以最新版本为准。"""

    allergens: list[str] = []
    pending: bool = False
    declared_at: Optional[AwareDatetime] = None

    @field_validator("allergens")
    @classmethod
    def _v_allergens(cls, v):
        return _clean_allergens(v)


def _clean_batch_refs(values: list[str]) -> list[str]:
    """批次引用列表：去空白、去空项；空列表或含重复项一律拒绝。"""
    ids = [x.strip() for x in values if x and x.strip()]
    if len(ids) != len(set(ids)):
        raise ValueError("批次号重复")
    if not ids:
        raise ValueError("不能为空")
    return ids


class ProcessingCreate(BaseModel):
    processing_id: str = Field(min_length=1)
    equipment_id: str = Field(min_length=1)
    start_utc: AwareDatetime
    end_utc: AwareDatetime
    inputs: list[str] = Field(min_length=1)
    outputs: list[str] = Field(min_length=1)

    @field_validator("inputs", "outputs")
    @classmethod
    def _v_batches(cls, v):
        return _clean_batch_refs(v)


class ProcessingInputCorrectionCreate(BaseModel):
    """加工投入纠正：完整的正确投入列表（整表替换，非增量补丁）。"""

    inputs: list[str] = Field(min_length=1)

    @field_validator("inputs")
    @classmethod
    def _v_inputs(cls, v):
        return _clean_batch_refs(v)


class CleaningCreate(BaseModel):
    equipment_id: str = Field(min_length=1)
    cleaned_at: AwareDatetime
    verified: bool = True


class LabelCreate(BaseModel):
    # 走“签发申请 -> 审核批准”流程时必填：已批准且结论未变化的签发申请号。
    # 缺省（None）为历史兼容的直接签发路径（封存批次仍拒绝）。
    approval_id: Optional[int] = None
    supersedes_id: Optional[int] = None  # 关联被替代的旧标签


class LabelApplicationCreate(BaseModel):
    """标签签发申请（质控提交，进入可审计审批环节）。"""

    batch_id: str = Field(min_length=1)
    applicant: str = Field(min_length=1)   # 申请人
    reason: str = Field(min_length=1)      # 审批理由（必填）
    label_note: Optional[str] = None       # 拟签发标签备注（可空）
    # 提交时客户端已同步到的溯源事件游标（GET /changes/events 的 next_cursor）。
    # 越界（负数/超过当前最大序号）返回 400，要求先同步后再申请。
    cursor: int = Field(ge=0)

    @field_validator("batch_id", "applicant", "reason")
    @classmethod
    def _v_nonblank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v

    @field_validator("label_note")
    @classmethod
    def _v_note(cls, v):
        if v is None:
            return ""
        return v.strip()


class LabelApplicationDecision(BaseModel):
    """审核决定：批准（approve）或驳回（reject）。

    reviewer 必填；reject 时 reject_reason 必填（空白 422）；note 为可选审核备注。
    """

    decision: Literal["approve", "reject"]
    reviewer: str = Field(min_length=1)
    reject_reason: Optional[str] = None
    note: Optional[str] = None

    @model_validator(mode="after")
    def _v_reject_reason(self):
        if self.decision == "reject":
            reason = (self.reject_reason or "").strip()
            if not reason:
                raise ValueError("驳回必须填写驳回原因（reject_reason）")
            self.reject_reason = reason
        return self

    @field_validator("reviewer")
    @classmethod
    def _v_reviewer(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v

    @field_validator("reject_reason", "note")
    @classmethod
    def _v_optional_strip(cls, v):
        if v is None:
            return None
        return v.strip() or None


class InvestigationCreate(BaseModel):
    """疑似交叉接触调查登记：唯一调查号、疑似批次、原因。"""

    investigation_id: str = Field(min_length=1)
    batch_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("investigation_id", "batch_id", "reason")
    @classmethod
    def _v_nonblank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class AllergenCodeMergeCreate(BaseModel):
    """过敏原代码并码登记：把旧过敏原代码并入目标代码（必填原因）。"""

    old_code: str = Field(min_length=1)
    target_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)

    @field_validator("old_code", "target_code", "reason")
    @classmethod
    def _v_nonblank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


class AllergenCodeMergeRevokeCreate(BaseModel):
    """过敏原代码并码撤销：撤销单条并码关系（必填撤销原因）。"""

    reason: str = Field(min_length=1)

    @field_validator("reason")
    @classmethod
    def _v_nonblank(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("不能为空")
        return v


# 声明更正预演请求与正式更正同构；清洗撤销预演/凭据提交无请求体，
# 仅以路径参数（清洗 id / 预演凭据）定位。
class DeclarationPreviewCreate(DeclarationCreate):
    """声明更正预演：拟更正内容（不落库）。"""
