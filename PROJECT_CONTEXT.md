# Project Context

## Goal
Xây dựng AI service Hybrid SQL + RAG cho Titsmart.

## Current scope
Vòng đầu chỉ dựng loader và data contract cho JSON mẫu.

## Constraints
- Không kết nối production.
- Không đọc secret.
- Không dùng Kafka.
- Chỉ sửa src/ và tests/.
- Vòng 8 LLM Constraints:
  + LLM_MODE chỉ chấp nhận 'mock' hoặc 'staging'. Cấm tuyệt đối 'production'.
  + ACL fail-closed: Lọc dữ liệu trước khi ghép vào LLM prompt, không đưa dữ liệu ngoài allowed_project_codes.
  + Không gửi PII, secret, user JWT vào LLM prompt.
  + Citation Post-Validation: Kiểm tra chéo citation trong câu trả lời với context thực tế, không tin LLM bịa nguồn.
  + Không đủ bằng chứng -> Trả về thông báo từ chối và has_evidence=False.
  + Kháng Prompt Injection (tài liệu chứa 'bỏ qua hướng dẫn trước' không được override system prompt).
  + Timeout rõ ràng, không log prompt nhạy cảm.

## Definition of Done
- Test chạy thật và pass.
- Không lỗi nghiêm trọng.
- Diff đúng phạm vi.
- Có báo cáo bàn giao ngắn.
