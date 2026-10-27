"""FastAPI application factory and routes."""
from fastapi import FastAPI, Query
from titsmart_ai.config import settings
from titsmart_ai.ingestion.sample_loader import SampleDataLoader

# Cache kết quả nạp sample trong bộ nhớ
_sample_stats_cache = None


def get_sample_stats(force_reload: bool = False):
    """
    Lấy thông tin thống kê dữ liệu sample.
    - Mặc định: dùng cache để tránh I/O đĩa lặp lại.
    - force_reload=True: nạp lại từ đĩa khi có thay đổi dữ liệu hoặc reindex.
    """
    global _sample_stats_cache
    if _sample_stats_cache is None or force_reload:
        loader = SampleDataLoader()
        _sample_stats_cache = loader.load_all_summary()
    return _sample_stats_cache


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Hybrid SQL + RAG Backend for TITSmart",
    )

    @app.get("/health")
    def health_check(refresh: bool = Query(default=False, description="Bắt buộc nạp lại dữ liệu từ đĩa")):
        stats = get_sample_stats(force_reload=refresh)
        return {
            "status": "healthy",
            "app": settings.APP_NAME,
            "environment": settings.APP_ENV,
            "mode": "offline_sample_only",
            "database_connected": False,
            "cache_refreshed": refresh,
            "sample_data": {
                "total_loaded": stats["total_loaded"],
                "total_skipped": stats["total_skipped"],
                "projects_count": stats["projects"]["loaded"],
                "tasks_count": stats["tasks"]["loaded"],
                "field_logs_count": stats["field_logs"]["loaded"],
                "issues_count": stats["issues"]["loaded"],
                "document_tracks_count": stats["document_tracks"]["loaded"],
            },
        }

    return app


app = create_app()
