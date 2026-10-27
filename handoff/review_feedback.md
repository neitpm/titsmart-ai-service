# Review Feedback — Vòng 5: QueryRouter

## Kết quả

`python -m pytest tests -q`: **105 passed, 1 skipped**.

## Trạng thái: PASSED

Đã kiểm tra `PROJECT_CONTEXT.md`, `state.json`, `handoff/coder_report.md`, git diff và implementation trong `src/titsmart_ai/router/query_router.py`.

- Prefix collision đã được xử lý bằng regex boundary, không còn substring matching.
- Trường hợp chỉ có quyền `TITS-01` nhưng câu hỏi chứa `TITS-010` được nhận diện là mã ngoài quyền và bị từ chối fail-closed.
- Candidate được sắp xếp theo độ dài giảm dần, bảo đảm longest-match và tính tất định khi câu hỏi có nhiều mã.
- Regression tests tương ứng đã có và toàn bộ test suite đạt.

