# Review Feedback — Vòng 6

## Kết quả: PASSED

Đã review độc lập `PROJECT_CONTEXT.md`, `state.json`, `handoff/coder_report.md`, git diff, mã nguồn liên quan và các regression test.

### 1. AuthContext fail-closed — ĐẠT

- `get_auth_context` không còn default cho `X-User-Id` hoặc `X-Allowed-Projects`.
- Thiếu hoặc chỉ chứa whitespace ở `X-User-Id` trả HTTP 401.
- Thiếu/rỗng `X-Allowed-Projects` tạo `allowed_project_codes=set()`; `ChatEngine` từ chối xử lý và không trả evidence.
- Regression test `test_api_chat_rejects_missing_auth_headers` và `test_api_chat_empty_allowed_projects_header` xác nhận hành vi này.

### 2. SQL aggregate được giới hạn theo ACL — ĐẠT

- Nhánh aggregate không còn gọi summary toàn cục không có bộ lọc.
- `ChatEngine._handle_sql_intent` lặp qua `sorted(auth_context.allowed_project_codes)` và gọi `get_progress_summary(project_code=p_code)` cho từng project được cấp quyền.
- Tổng task/chỉ số chỉ được cộng từ summary đã lọc; citation cũng gắn với project cụ thể (`progress_summary_<project>`), không còn source `all_allowed`.
- Regression test `test_chat_engine_sql_aggregate_acl_isolation` xác nhận user chỉ có `TITS-01` không nhận dữ liệu/citation của `TITS-02`.

### Kiểm thử

Lệnh đã chạy: `python -m pytest tests -q`

Kết quả: **119 passed, 1 skipped**.

Không phát hiện lỗi còn tồn tại trong phạm vi review Vòng 6.

## Handoff

`state.json` được cập nhật: `state=PASSED`, `next_actor=ANTIGRAVITY`.
