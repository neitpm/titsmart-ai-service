import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Cấu hình ứng dụng titsmart-ai-service.
    Mặc định chỉ dùng mock data offline, không kết nối production.
    """
    APP_NAME: str = "TITSmart AI Service"
    APP_ENV: str = "development"
    DEBUG: bool = True
    PORT: int = 8000

    # Đường dẫn thư mục dữ liệu mẫu
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    SAMPLE_DATA_DIR: Path = BASE_DIR / "data" / "sample"

    # Supabase (Mặc định trống - không tự kết nối khi test local)
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_READONLY: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
