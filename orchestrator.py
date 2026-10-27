"""
Multi-Agent Orchestrator: Antigravity (Coder) <-> Codex (Reviewer)
Tự động lặp lại quy trình:
Antigravity viết code -> State = REVIEW -> Codex review -> State = NEEDS_FIX / PASSED
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path

REPO_DIR = Path("D:/titsmart-ai-service").resolve()
STATE_FILE = REPO_DIR / "state.json"
CONTEXT_FILE = REPO_DIR / "PROJECT_CONTEXT.md"
CODER_REPORT = REPO_DIR / "handoff" / "coder_report.md"
REVIEW_FEEDBACK = REPO_DIR / "handoff" / "review_feedback.md"

MAX_GLOBAL_ITERATIONS = 20
TURN_TIMEOUT_SECONDS = 300  # 5 phút tối đa cho mỗi lượt gọi


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Orchestrator] Lỗi đọc state.json: {e}")
        return {}


def write_state(data: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_coder_antigravity(task_desc: str) -> bool:
    """Gọi Antigravity CLI non-interactively bằng lệnh agy --print"""
    print(f"\n[Orchestrator] >>> GỌI ANTIGRAVITY (CODER)...")
    prompt = (
        f"Bạn là CODER trong repo {REPO_DIR}. "
        f"Hãy đọc PROJECT_CONTEXT.md, state.json, handoff/review_feedback.md và git diff. "
        f"Thực hiện task: {task_desc}. "
        f"Chạy test kiểm chứng, cập nhật handoff/coder_report.md và cập nhật state.json sang state=REVIEW, next_actor=CODEX. "
        f"Tuyệt đối không sửa ngoài scope cho phép."
    )
    cmd = [
        "agy",
        "--print",
        prompt,
        "--project", str(REPO_DIR),
        "--dangerously-skip-permissions",
        "--print-timeout", f"{TURN_TIMEOUT_SECONDS}s"
    ]
    try:
        res = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True, timeout=TURN_TIMEOUT_SECONDS)
        print(f"[Orchestrator] Antigravity hoàn thành (exit code: {res.returncode})")
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[Orchestrator] Antigravity bị timeout ({TURN_TIMEOUT_SECONDS}s)")
        return False
    except Exception as e:
        print(f"[Orchestrator] Lỗi khi gọi Antigravity: {e}")
        return False


def run_reviewer_codex(task_desc: str) -> bool:
    """Gọi Codex CLI non-interactively bằng lệnh codex exec"""
    print(f"\n[Orchestrator] >>> GỌI CODEX (REVIEWER)...")
    prompt = (
        f"Bạn là REVIEWER trong repo {REPO_DIR}. "
        f"Hãy đọc PROJECT_CONTEXT.md, state.json, handoff/coder_report.md và git diff. "
        f"Review task: {task_desc}. "
        f"Chạy lệnh 'python -m pytest tests -q' để xác minh. "
        f"Nếu đạt yêu cầu thì ghi nhận xét vào handoff/review_feedback.md và cập nhật state.json sang state=PASSED, next_actor=ANTIGRAVITY. "
        f"Nếu chưa đạt, ghi lỗi cụ thể vào handoff/review_feedback.md và cập nhật state.json sang state=NEEDS_FIX, next_actor=ANTIGRAVITY."
    )
    cmd = [
        "codex",
        "exec",
        prompt,
        "--cd", str(REPO_DIR),
        "--dangerously-bypass-approvals-and-sandbox"
    ]
    try:
        res = subprocess.run(cmd, cwd=str(REPO_DIR), capture_output=True, text=True, timeout=TURN_TIMEOUT_SECONDS)
        print(f"[Orchestrator] Codex hoàn thành (exit code: {res.returncode})")
        return res.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[Orchestrator] Codex bị timeout ({TURN_TIMEOUT_SECONDS}s)")
        return False
    except Exception as e:
        print(f"[Orchestrator] Lỗi khi gọi Codex: {e}")
        return False


def main():
    print("==========================================================")
    print("  TITSMART AI: MULTI-AGENT ORCHESTRATOR (CLI-BASED)      ")
    print("==========================================================")

    state = read_state()
    current_iteration = state.get("iteration", 1)
    task_desc = state.get("task", "Triển khai tính năng mới")

    print(f"Khởi động vòng lặp tự động cho task: {task_desc}")
    print(f"Thư mục làm việc: {REPO_DIR}")

    while current_iteration <= MAX_GLOBAL_ITERATIONS:
        state = read_state()
        current_state = state.get("state", "CODING")
        next_actor = state.get("next_actor", "ANTIGRAVITY")
        task_desc = state.get("task", task_desc)

        print(f"\n--- [Iteration {current_iteration}] State: {current_state} | Next Actor: {next_actor} ---")

        if current_state == "PASSED":
            print(f"\n[Orchestrator] >>> THÀNH CÔNG! Task '{task_desc}' đã đạt PASSED bởi Codex.")
            break

        if current_state in ("CODING", "NEEDS_FIX") or next_actor == "ANTIGRAVITY":
            # 1. Gọi Antigravity (Coder)
            success = run_coder_antigravity(task_desc)
            time.sleep(2)
            state = read_state()
            if state.get("state") != "REVIEW":
                print(f"[Orchestrator] Cảnh báo: State chưa chuyển sang REVIEW (Hiện tại: {state.get('state')})")

        elif current_state == "REVIEW" or next_actor == "CODEX":
            # 2. Gọi Codex (Reviewer)
            success = run_reviewer_codex(task_desc)
            time.sleep(2)
            state = read_state()
            if state.get("state") == "PASSED":
                print(f"\n[Orchestrator] >>> HOÀN TẤT: Codex đã phê duyệt [ĐẠT] / PASSED!")
                break
            elif state.get("state") == "NEEDS_FIX":
                print(f"[Orchestrator] Codex yêu cầu sửa (NEEDS_FIX). Chuyển lại cho Antigravity...")

        current_iteration += 1
        state["iteration"] = current_iteration
        write_state(state)

    if current_iteration > MAX_GLOBAL_ITERATIONS:
        print(f"\n[Orchestrator] Đã chạm ngưỡng tối đa {MAX_GLOBAL_ITERATIONS} vòng lặp. Dừng khẩn cấp!")


if __name__ == "__main__":
    main()
