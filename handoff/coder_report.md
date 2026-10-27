# Coder Report - Round 6 (Fixes applied following Review Feedback)

## Summary of Fixes

### 1. Fix Critical AuthContext Fail-Closed Enforcement (`src/titsmart_ai/security/auth.py`)
- **Removed Default Credentials**: Removed `default="test_engineer_01"` and `default="TITS-01,..."` from `Header(...)`.
- **Fail-Closed on Missing Header**: Any request without `X-User-Id` (or with empty/whitespace `X-User-Id`) immediately raises `HTTP 401 Unauthorized`.
- **Fail-Closed on Missing Allowed Projects**: If `X-Allowed-Projects` is omitted or empty, `allowed_project_codes` defaults strictly to an empty set (`set()`), triggering fail-closed rejection at the query planner.
- **Added Regression Tests**: Added `test_api_chat_rejects_missing_auth_headers`, `test_api_chat_empty_allowed_projects_header`, and verified whitespace/empty handling.

### 2. Fix High SQL Aggregate Cross-Project Data Leakage (`src/titsmart_ai/domain/chat_engine.py`)
- **Strict ACL-Scoped Progress Aggregation**: In `ChatEngine._handle_sql_intent` when `target_code is None`, instead of calling unscoped global summary, the engine now iterates through `sorted(auth_context.allowed_project_codes)` and aggregates progress strictly project-by-project.
- **Discrete Scoped Citations**: Citations are created individually for each authorized project (`f"progress_summary_{p_code}"`), eliminating the unsafe `"all_allowed"` mock source.
- **Added Regression Test**: `test_chat_engine_sql_aggregate_acl_isolation` verifying that User A (granted only `TITS-01`) receives aggregated metrics and citations solely from `TITS-01` without leaking `TITS-02`.

### 3. Regex Boundary Refinement in QueryRouter (`src/titsmart_ai/router/query_router.py`)
- Refined the shorthand project pattern `match_da` with word boundaries `\b(?:dự án|du an|da)\s+([0-9][A-Za-z0-9_-]*|[A-Z]{2,}[-_][A-Za-z0-9_-]+)\b` to prevent matching ordinary Vietnamese text like "dự án hiện tại" as project code "HI".

## Test Results
- `python -m pytest tests -v`: **119 passed, 1 skipped** (live staging integration test).
