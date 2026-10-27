# Coder Report - Security Patch: Server-side Project Membership & JWT Authentication

## Summary of Security Fixes

### 1. Zero Trust on Frontend Custom Headers
- **Root Problem**: Client could previously spoof `X-User-Id` and `X-Allowed-Projects` to gain unauthorized access to projects.
- **Production Standard (`src/titsmart_ai/security/auth.py`)**:
  - In Production or JWT mode, user identity is verified strictly via cryptographic JWT (`Authorization: Bearer <token>`).
  - `allowed_project_codes` is **NEVER** accepted from client headers or request bodies.
  - Server invokes `ProjectMembershipProvider.get_allowed_projects(user_id)` to look up project access directly from server-side database/store.
  - If a client sends spoofed `X-Allowed-Projects` alongside a valid JWT, the header is strictly discarded.

### 2. Guardrails for Local Mock Mode
- **Production Ban**: Pydantic validator (`check_auth_mode_not_mock_in_prod`) and runtime middleware strictly prohibit `AUTH_MODE='mock'` when `APP_ENV='production'` or `'prod'`.
- **Internal Secret Protection**: Optional `INTERNAL_AUTH_SECRET` enforcement (requires `X-Internal-Secret` matching) to secure internal reverse proxy setups.

### 3. Server-Side Membership Lookup (`src/titsmart_ai/security/membership.py`)
- Created `ProjectMembershipProvider(Protocol)` and `InMemoryProjectMembershipProvider` mapping authenticated users directly to their assigned projects.

### 4. Comprehensive Regression Suite (`tests/test_auth_production_security.py`)
- `test_jwt_verification_and_server_side_membership`: Client with JWT for `engineer_tits01` tries spoofing `X-Allowed-Projects: TITS-02`; verified server enforces `TITS-01` and rejects `TITS-02`.
- `test_jwt_invalid_or_expired_token`: Rejects tampered/invalid tokens with HTTP 401.
- `test_jwt_mode_enforced_rejects_mock_headers`: Rejects mock headers when `AUTH_MODE='jwt'`.
- `test_production_environment_rejects_mock_mode`: Rejects mock mode in production with HTTP 500.
- `test_config_validator_prevents_mock_in_production`: Pydantic startup configuration validation.
- `test_internal_secret_protection_in_mock_mode`: Enforces `X-Internal-Secret` in mock mode.

## Test Results
- `python -m pytest tests -v`: **125 passed, 1 skipped** (live staging integration test).
