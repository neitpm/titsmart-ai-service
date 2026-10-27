import os
from pathlib import Path
from typing import Optional, Set
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, ValidationInfo


class Settings(BaseSettings):
    """
    Cấu hình ứng dụng titsmart-ai-service.
    Tuân thủ an toàn:
    - SUPABASE_ENV chỉ chấp nhận 'staging' hoặc 'development'.
    - SUPABASE_ALLOWED_PROJECT_REF: Allowlist bắt buộc ref project staging.
    - Không log secret/token.
    """
    APP_NAME: str = "TITSmart AI Service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000

    # Đường dẫn thư mục dữ liệu mẫu offline
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    SAMPLE_DATA_DIR: Path = BASE_DIR / "data" / "sample"

    # Supabase Staging Settings
    SUPABASE_ENV: str = "development"  # Chỉ chấp nhận 'development' hoặc 'staging'
    SUPABASE_ALLOWED_PROJECT_REF: Optional[str] = None  # Allowlist ref (ví dụ: 'xyz-staging-123')
    SUPABASE_URL: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None
    SUPABASE_REQUEST_TIMEOUT: float = 10.0  # Timeout giây

    # LLM Settings
    LLM_MODE: str = "mock"  # Chỉ chấp nhận 'mock' hoặc 'staging'. CẤM TUYỆT ĐỐI 'production'
    LLM_API_BASE: Optional[str] = None  # Endpoint cho LLM Staging (ví dụ Ollama/vLLM/OpenAI-compatible)
    LLM_API_KEY: Optional[str] = None
    LLM_MODEL: str = "titsmart-mock-llm"
    LLM_REQUEST_TIMEOUT: float = 10.0  # Fail-closed timeout (giây)

    # Authentication & Security
    AUTH_MODE: str = "mock"  # "mock" hoặc "jwt"
    INTERNAL_AUTH_SECRET: Optional[str] = None  # Secret cho reverse proxy khi chạy mock mode
    JWT_SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: Optional[str] = None  # Ví dụ: "https://<ref>.supabase.co/auth/v1"
    JWT_AUDIENCE: Optional[str] = "authenticated"  # Supabase default role/audience

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("AUTH_MODE")
    @classmethod
    def check_auth_mode_not_mock_in_prod(cls, v: str, info: ValidationInfo) -> str:
        app_env = str(info.data.get("APP_ENV", "development")).lower()
        if app_env in ("production", "prod") and v.lower() == "mock":
            raise ValueError(
                "LỖI BẢO MẬT: Tuyệt đối không được bật AUTH_MODE='mock' trong môi trường PRODUCTION!"
            )
        return v.lower()

    @field_validator("SUPABASE_ENV")
    @classmethod
    def check_env_not_production(cls, v: str) -> str:
        if v.lower() in ("production", "prod"):
            raise ValueError("Tuyệt đối không được cấu hình SUPABASE_ENV=production!")
        return v.lower()

    @field_validator("LLM_MODE")
    @classmethod
    def check_llm_mode(cls, v: str) -> str:
        val = v.lower()
        if val in ("production", "prod"):
            raise ValueError("Tuyệt đối không được cấu hình LLM_MODE=production! Chỉ chấp nhận 'mock' hoặc 'staging'.")
        if val not in ("mock", "staging"):
            raise ValueError(f"LLM_MODE không hợp lệ: '{v}'. Chỉ chấp nhận 'mock' hoặc 'staging'.")
        return val

    @field_validator("SUPABASE_URL", mode="after")
    @classmethod
    def check_url_allowlist(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        if not v:
            return None

        # Phân tích URL chính xác bằng urllib.parse
        from urllib.parse import urlparse
        parsed = urlparse(v)
        hostname = (parsed.hostname or "").lower()

        # Kiểm tra allowlist project ref chính xác trên hostname: <allowed-ref>.supabase.co
        allowed_ref = info.data.get("SUPABASE_ALLOWED_PROJECT_REF")
        if allowed_ref:
            expected_host = f"{allowed_ref.lower()}.supabase.co"
            if hostname != expected_host and not hostname.endswith(f".{expected_host}"):
                raise ValueError(
                    f"SUPABASE_URL có hostname '{hostname}' không khớp với allowlist chính xác ('{expected_host}')!"
                )
        return v

    def validate_staging_credentials(self) -> None:
        """Kiểm tra có đủ credentials staging và allowlist khi kích hoạt Supabase adapter."""
        if not self.SUPABASE_URL or not self.SUPABASE_ANON_KEY:
            raise ValueError(
                "Thiếu cấu hình Supabase Staging: SUPABASE_URL và SUPABASE_ANON_KEY bắt buộc phải được khai báo."
            )
        if self.SUPABASE_ENV not in ("staging", "development"):
            raise ValueError(f"Môi trường không an toàn: {self.SUPABASE_ENV}. Chỉ chấp nhận 'staging' hoặc 'development'.")


settings = Settings()
