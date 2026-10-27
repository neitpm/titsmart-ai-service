# Coder Report (Round 5 - Iteration 14 - Fix ACL Substring Matching)

## Fixed
- `src/titsmart_ai/router/query_router.py`:
  - Thay thế toàn bộ logic substring `code.upper() in upper_text` bằng **Word Boundary Regex Matching**:
    `re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(code.upper())}(?![A-Za-z0-9_-])")`.
  - Triệt tiêu hoàn toàn lỗi prefix collision: Nếu người dùng có quyền `TITS-01` nhưng hỏi về `TITS-010`, hệ thống nhận diện chính xác `TITS-010` và từ chối truy cập (Fail-Closed).
  - Áp dụng cơ chế **Longest Match First** (sắp xếp ứng viên giảm dần theo độ dài) và chuyển sang list xác định trước khi duyệt để bảo đảm tính tất định 100% giữa các tiến trình.
- `tests/test_query_router.py`:
  - Thêm test `test_prefix_collision_and_boundary_matching` (`TITS-01` vs `TITS-010`).
  - Thêm test `test_multiple_projects_in_question_deterministic` (Longest match first khi câu hỏi chứa nhiều mã).

## Tests
- Command: `python -m pytest tests -q`
- Result: `.........................................................................................................s [100%]` (105 passed, 1 skipped in 0.41s)
