"""Domain models definition using Pydantic v2."""
from typing import Optional, Union
import math
from pydantic import BaseModel, Field, ConfigDict, field_validator


class BaseDataModel(BaseModel):
    """
    Base model chặt chẽ:
    - extra='forbid': Ngăn chặn triệt để schema drift, bắt lỗi ngay nếu thừa/sai tên field.
    - validate_assignment=True: Kiểm tra kiểu khi gán.
    - strict=False: Vẫn cho phép string float coersion hợp lý ("50.5" -> 50.5), nhưng từ chối bool/nan/inf.
    """
    model_config = ConfigDict(
        populate_by_name=True,
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True
    )


def validate_finite_number(v: Optional[float]) -> Optional[float]:
    """Từ chối boolean, NaN, Infinity và kiểm tra giá trị hữu hạn."""
    if v is None:
        return None
    # Trong Python, bool là subclass của int (isinstance(True, int) == True)
    if isinstance(v, bool):
        raise ValueError("Boolean không được chấp nhận làm giá trị số")
    if isinstance(v, (int, float)):
        if math.isnan(v) or math.isinf(v):
            raise ValueError("NaN và Infinity không được chấp nhận")
    return float(v)


class Project(BaseDataModel):
    """Mô hình thông tin Dự án / Công trình (bảng projects)."""
    id: str
    code: str
    name: str
    client: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = "active"
    progress_percent: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    contract_value: Optional[float] = Field(default=0.0, ge=0.0)
    created_at: Optional[str] = None

    @field_validator("progress_percent", "contract_value", mode="before")
    @classmethod
    def check_finite(cls, v):
        return validate_finite_number(v)


class Task(BaseDataModel):
    """Mô hình Hạng mục công việc / Tiến độ (bảng tasks)."""
    id: str
    project_code: str
    stt: Optional[Union[int, float, str]] = None
    name: str
    volume: Optional[float] = Field(default=0.0, ge=0.0)
    unit: Optional[str] = None
    # Chuẩn hóa duy nhất: progress luôn là phần trăm từ 0.0 đến 100.0%.
    # Quy tắc ingestion rõ ràng: nếu giá trị nguồn là tỷ lệ 0.0 < val <= 1.0, tự động chuẩn hóa sang % (val * 100).
    progress: Optional[float] = Field(default=0.0, ge=0.0, le=100.0)
    status: Optional[str] = None
    purchase_status: Optional[str] = None
    constr_status: Optional[str] = None
    notes: Optional[str] = None
    assigned_engineer_name: Optional[str] = None

    @field_validator("volume", mode="before")
    @classmethod
    def check_volume(cls, v):
        return validate_finite_number(v)

    @field_validator("progress", mode="before")
    @classmethod
    def normalize_progress(cls, v):
        v = validate_finite_number(v)
        if v is not None and 0.0 < v <= 1.0:
            v = v * 100.0
        return v

    @field_validator("stt", mode="before")
    @classmethod
    def check_stt(cls, v):
        if isinstance(v, bool):
            raise ValueError("Boolean không được chấp nhận làm STT")
        return v


class FieldLog(BaseDataModel):
    """Mô hình Nhật ký hiện trường (bảng field_logs)."""
    id: str
    project_code: str
    timestamp: Optional[str] = None
    images_count: Optional[int] = Field(default=0, ge=0)

    @field_validator("images_count", mode="before")
    @classmethod
    def check_images_count(cls, v):
        if isinstance(v, bool):
            raise ValueError("Boolean không được chấp nhận")
        return v


class Issue(BaseDataModel):
    """Mô hình Sự cố / Vướng mắc công trường (bảng issues)."""
    id: str
    project_code: str
    title: str
    description: Optional[str] = None
    priority: Optional[str] = "STANDARD"
    status: Optional[str] = "OPEN"
    reported_time: Optional[str] = None


class DocumentTrack(BaseDataModel):
    """Mô hình Hồ sơ pháp lý & Thanh toán (bảng document_tracks)."""
    id: str
    contract_no: Optional[str] = None
    contract_name: Optional[str] = None
    company: Optional[str] = None
    receiver_name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    send_date: Optional[str] = None
    doc_status: Optional[str] = None
    payment_status: Optional[str] = None
    notes: Optional[str] = None
    contract_value: Optional[float] = Field(default=0.0, ge=0.0)

    @field_validator("contract_value", mode="before")
    @classmethod
    def check_finite(cls, v):
        return validate_finite_number(v)
