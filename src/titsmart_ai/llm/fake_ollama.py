"""Deterministic FakeOllamaClient for testing without real Ollama instance or cloud models."""
import json
import math
import hashlib
from typing import Optional, Set, Dict, List, Any
import httpx


def generate_deterministic_embedding(text: str, dimensions: int = 1024) -> List[float]:
    """
    Tạo vector embedding tất định (dimensions chiều, mặc định 1024 cho bge-m3:latest)
    chuẩn hóa L2 (L2 norm = 1.0) từ chuỗi văn bản.
    """
    if not text:
        text = ""
    vec: List[float] = []
    for i in range(dimensions):
        seed = f"{text}:{i}:bge-m3"
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        int_val = int.from_bytes(digest[:4], byteorder="big", signed=True)
        vec.append(float(int_val) / (2**31))

    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


class FakeOllamaClient(httpx.Client):
    """
    Fake Ollama Client mô phỏng toàn diện Ollama Local cho Unit Test:
    - Kế thừa httpx.Client sử dụng httpx.MockTransport nội bộ.
    - Không mở cổng socket mạng thực, không phụ thuộc daemon Ollama bên ngoài.
    - Hỗ trợ đầy đủ các endpoint:
      + POST /api/chat & /chat/completions: Sinh phản hồi kỹ thuật.
      + POST /api/embed & /api/embeddings: Vector hóa văn bản bằng bge-m3:latest (1024 chiều).
      + GET /api/tags: Liệt kê danh sách mô hình có sẵn.
    - Kiểm soát nghiêm ngặt:
      + Cấm tuyệt đối dùng bge-m3 để trò chuyện (trả về HTTP 400).
      + Hỗ trợ cấu hình fail_models để mô phỏng lỗi 500 kích hoạt fallback qwen3:4b.
      + Hỗ trợ timeout_models để kiểm tra fail-closed khi LLM timeout.
      + Hỗ trợ network_down để kiểm tra ngắt kết nối mạng an toàn.
      + Ghi nhận call_history để kiểm tra thứ tự gọi chính xác.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        fail_models: Optional[Set[str]] = None,
        timeout_models: Optional[Set[str]] = None,
        network_down: bool = False,
        custom_chat_responses: Optional[Dict[str, str]] = None,
        embedding_dimensions: int = 1024,
        **kwargs,
    ):
        self.mock_base_url = base_url.rstrip("/")
        self.fail_models = set(fail_models or [])
        self.timeout_models = set(timeout_models or [])
        self.network_down = network_down
        self.custom_chat_responses = custom_chat_responses or {}
        self.embedding_dimensions = embedding_dimensions
        self.call_history: List[Dict[str, Any]] = []

        super().__init__(
            transport=httpx.MockTransport(self._handle_request),
            base_url=self.mock_base_url,
            **kwargs,
        )

    def clear_history(self) -> None:
        """Xóa lịch sử gọi phục vụ assert giữa các test case."""
        self.call_history.clear()

    def _handle_request(self, request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        method = request.method

        if self.network_down:
            raise httpx.ConnectError("Không thể kết nối đến Ollama tại 127.0.0.1:11434 (Connection refused)")

        body_data: Dict[str, Any] = {}
        if request.content:
            try:
                body_data = json.loads(request.content.decode("utf-8"))
            except Exception:
                body_data = {}

        model = body_data.get("model", "")
        self.call_history.append({
            "method": method,
            "path": url_path,
            "model": model,
            "body": body_data,
        })

        # 1. Chat endpoints: /api/chat hoặc /chat/completions hoặc /v1/chat/completions
        if any(p in url_path for p in ("/api/chat", "/chat/completions", "/v1/chat/completions")):
            # Ràng buộc an toàn: CẤM TUYỆT ĐỐI bge-m3 dùng cho trò chuyện
            if "bge-m3" in model.lower():
                return httpx.Response(
                    400,
                    json={
                        "error": "bge-m3:latest là mô hình embedding, cấm tuyệt đối sử dụng để sinh văn bản / trò chuyện!"
                    },
                )

            # Mô phỏng Timeout theo mô hình
            if model in self.timeout_models:
                raise httpx.TimeoutException(f"Ollama request for model '{model}' timed out")

            # Mô phỏng lỗi mô hình (HTTP 500)
            if model in self.fail_models:
                return httpx.Response(
                    500,
                    json={"error": f"Model '{model}' failed or not available on Ollama instance"},
                )

            # Phản hồi tùy biến hoặc mặc định chuẩn kỹ thuật
            if model in self.custom_chat_responses:
                reply_text = self.custom_chat_responses[model]
            else:
                reply_text = (
                    f"Báo cáo tiến độ phân tích từ mô hình {model}: "
                    "Hạng mục thi công đang triển khai theo tiến độ phê duyệt căn cứ theo [Nguồn 1]."
                )

            if "/chat/completions" in url_path:
                return httpx.Response(
                    200,
                    json={
                        "id": "chatcmpl-mock",
                        "model": model,
                        "choices": [
                            {"message": {"role": "assistant", "content": reply_text}, "index": 0}
                        ],
                    },
                )
            else:
                # /api/chat chuẩn Ollama native
                return httpx.Response(
                    200,
                    json={
                        "model": model,
                        "message": {"role": "assistant", "content": reply_text},
                        "done": True,
                    },
                )

        # 2. Embedding endpoint: /api/embed (batch)
        if url_path.endswith("/api/embed"):
            if model in self.timeout_models:
                raise httpx.TimeoutException(f"Ollama embedding request for model '{model}' timed out")
            if model in self.fail_models:
                return httpx.Response(500, json={"error": f"Embedding model '{model}' failed"})

            input_val = body_data.get("input", [])
            if isinstance(input_val, str):
                input_val = [input_val]
            embeddings = [
                generate_deterministic_embedding(str(t), self.embedding_dimensions) for t in input_val
            ]
            return httpx.Response(
                200,
                json={"model": model, "embeddings": embeddings},
            )

        # 3. Embedding endpoint: /api/embeddings (single)
        if url_path.endswith("/api/embeddings"):
            if model in self.timeout_models:
                raise httpx.TimeoutException(f"Ollama embedding request for model '{model}' timed out")
            if model in self.fail_models:
                return httpx.Response(500, json={"error": f"Embedding model '{model}' failed"})

            prompt_text = body_data.get("prompt", "")
            emb = generate_deterministic_embedding(str(prompt_text), self.embedding_dimensions)
            return httpx.Response(
                200,
                json={"embedding": emb},
            )

        # 4. Tags / list models: /api/tags
        if "/api/tags" in url_path:
            return httpx.Response(
                200,
                json={
                    "models": [
                        {"name": "qwen3:8b"},
                        {"name": "qwen3:4b"},
                        {"name": "bge-m3:latest"},
                    ]
                },
            )

        return httpx.Response(404, json={"error": f"Endpoint '{url_path}' not found"})
