# Coder Report - JWT Claims Hardening & Supabase Membership Provider

## Summary of Changes
1. **Strict JWT Claims Validation (`src/titsmart_ai/security/auth.py`, `src/titsmart_ai/config.py`)**:
   - Enforced verification of `exp`, `sub`, `aud` (default: `"authenticated"` matching Supabase auth conventions), and optional `iss`.
   - Rejects expired or malformed claims with HTTP 401.

2. **Supabase Project Membership Adapter (`src/titsmart_ai/security/membership.py`, `src/titsmart_ai/adapters/supabase_adapter.py`)**:
   - Added `select_project_members(user_id)` to `ReadOnlyDataClient(Protocol)` and `SupabaseReadOnlyClient`.
   - Implemented `SupabaseProjectMembershipProvider` querying `project_members` table directly with fail-closed safety.
   - Added unit tests verifying correct mapping and fail-closed error handling (`test_supabase_project_membership_provider_unit`).

3. **Status Confirmation**:
   - Local/offline security validation achieved: **126 passed, 1 skipped**.
   - Acknowledged status: **[ĐẠT CÓ ĐIỀU KIỆN]** pending live Supabase staging credentials for integration verification.
