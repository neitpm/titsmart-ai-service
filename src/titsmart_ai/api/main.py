"""FastAPI application factory and routes."""
from fastapi import FastAPI, Query, Depends, HTTPException, status
from titsmart_ai.config import settings
from titsmart_ai.ingestion.sample_loader import SampleDataLoader
from titsmart_ai.security.auth import AuthContext, get_auth_context
from titsmart_ai.domain.chat import ChatRequest, ChatResponse
from titsmart_ai.domain.chat_engine import ChatEngine
from titsmart_ai.router.query_router import QueryRouter
from titsmart_ai.tools.query_tool import InMemoryDataQueryTool
from titsmart_ai.tools.vector_store import InMemoryVectorStore, DeterministicFakeEmbeddingProvider
from titsmart_ai.ingestion.document_builder import DocumentBuilder, TextChunker

# Cache kết quả nạp sample trong bộ nhớ
_sample_stats_cache = None
_chat_engine_instance = None


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


def get_chat_engine() -> ChatEngine:
    """Khởi tạo và inject các components cho ChatEngine (Offline / Mock Mode)."""
    global _chat_engine_instance
    if _chat_engine_instance is None:
        loader = SampleDataLoader()
        projects = loader.load_projects()
        tasks = loader.load_tasks()
        issues = loader.load_issues()
        field_logs = loader.load_field_logs()

        # 1. Khởi tạo QueryTool
        query_tool = InMemoryDataQueryTool(projects=projects, tasks=tasks, issues=issues)

        # 2. Khởi tạo VectorStore và nạp vector từ sample
        embedding_provider = DeterministicFakeEmbeddingProvider(dimensions=384)
        vector_store = InMemoryVectorStore(expected_dimensions=384)
        chunker = TextChunker(chunk_size=1000, overlap=150)

        all_chunks = []
        for fl in field_logs:
            doc = DocumentBuilder.build_from_field_log(fl)
            if doc:
                all_chunks.extend(chunker.chunk_document(doc))

        for iss in issues:
            doc = DocumentBuilder.build_from_issue(iss)
            if doc:
                all_chunks.extend(chunker.chunk_document(doc))

        for t in tasks:
            doc = DocumentBuilder.build_from_task(t)
            if doc:
                all_chunks.extend(chunker.chunk_document(doc))

        if all_chunks:
            embeddings = embedding_provider.embed([c.content for c in all_chunks])
            vector_store.upsert(all_chunks, embeddings)

        # 3. Khởi tạo QueryRouter
        known_codes = {p.code for p in projects}
        router = QueryRouter(known_projects=known_codes)

        _chat_engine_instance = ChatEngine(
            router=router,
            query_tool=query_tool,
            vector_store=vector_store,
            embedding_provider=embedding_provider,
        )

    return _chat_engine_instance


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

    @app.post("/api/chat", response_model=ChatResponse)
    def chat_endpoint(
        request: ChatRequest,
        auth_context: AuthContext = Depends(get_auth_context),
        engine: ChatEngine = Depends(get_chat_engine),
    ) -> ChatResponse:
        """
        Endpoint trả lời câu hỏi thông minh Hybrid SQL + RAG:
        - Nhận duy nhất question trong request body.
        - Quyền truy cập project bắt buộc lấy từ AuthContext (JWT/Header).
        """
        return engine.answer(request.question, auth_context)

    return app


app = create_app()
