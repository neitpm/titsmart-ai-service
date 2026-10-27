# Titsmart AI Service (Hybrid SQL + RAG)

Hệ thống AI Assistant chuyên dụng cho Titsmart, ứng dụng kiến trúc **Hybrid SQL + RAG**:
- **SQL Engine**: Xử lý các câu hỏi tính toán chính xác tuyệt đối (tiến độ, số lượng, ngày hạn, thống kê dự án).
- **RAG Engine (pgvector)**: Xử lý tìm kiếm ngữ nghĩa văn bản (nhật ký hiện trường, sự cố, nguyên nhân chậm tiến độ, hồ sơ pháp lý).

---

## 1. Cấu trúc thư mục

```text
titsmart-ai-service/
├── data/
│   └── sample/                    # Tập dữ liệu mẫu đã che/ẩn danh thông tin nhạy cảm
│       ├── projects_sample.json
│       ├── tasks_sample.json
│       ├── field_logs_sample.json
│       ├── document_tracks_sample.json
│       └── issues_sample.json
├── src/
│   ├── config/                    # Cấu hình môi trường (Supabase read-only, AI API keys)
│   ├── tools/
│   │   ├── sql_tool.py            # Truy vấn SQL an toàn (Read-Only)
│   │   └── vector_tool.py         # Tìm kiếm RAG trên vector store
│   ├── router/                    # Query Router (phân loại câu hỏi số liệu vs văn bản)
│   └── index.py                   # Điểm vào chính của chatbot
├── .env.example
└── README.md
```

---

## 2. Tiêu chuẩn bảo mật dữ liệu mẫu (Data Masking)
- Các số điện thoại khách hàng, địa chỉ, tên chủ đầu tư đã được che (`[Đã ẩn]`, `09******`).
- Không sao chép các trường nhạy cảm như CCCD, mật khẩu hay tài khoản ngân hàng.
- Kết nối tới Database sử dụng quyền **Read-Only**.
