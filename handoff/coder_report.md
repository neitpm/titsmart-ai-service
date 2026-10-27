# Coder Report (Round 3 - Iteration 9 - Strict Hostname Matching & Explicit Mapping)

## Changed
- `src/titsmart_ai/config.py`:
  - Dùng `urllib.parse.urlparse` tách riêng `hostname`.
  - Kiểm tra chuẩn xác: hostname bắt buộc phải là `<allowed_ref>.supabase.co` (hoặc subdomain hợp lệ). Ngăn chặn triệt để trường hợp ref xuất hiện trong path (ví dụ `https://malicious.com/staging-ref-xyz`).
- `src/titsmart_ai/adapters/supabase_adapter.py`:
  - Bổ sung `EXPLICIT_FIELD_MAPPING` với các trường cốt lõi của hệ thống TITSmart (`projectCode`, `assignedEngineerName`, `contractValue`, `progressPercent`, etc.).
  - Ngăn chặn hoàn toàn lỗi regex collision trên các từ viết hoa liền kề (`projectID`, `HTMLContent`).
- `tests/test_supabase_adapter.py`:
  - Cập nhật test `test_settings_allowlist_enforcement` để xác nhận URL giả mạo có ref trong path bị từ chối tuyệt đối.

## Tests
- Command: `python -m pytest tests -q`
- Result: `..........................................s [100%]` (42 passed, 1 skipped in 0.36s)

## Staging Verification Note:
- Khung adapter và integration test `test_live_supabase_staging_read_only_and_rls` đã sẵn sàng.
- Khi người dùng cung cấp Staging URL/Key an toàn và đặt biến môi trường `SUPABASE_INTEGRATION_TESTS=1`, test sẽ kích hoạt kiểm thử trực tiếp trên Staging.
