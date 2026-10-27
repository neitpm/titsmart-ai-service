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
LIVE_PROGRESS = REPO_DIR / "handoff" / "live_progress.md"

DEFAULT_MAX_ITERATIONS = 10
TURN_TIMEOUT_SECONDS = 600  # 10 phút tối đa cho mỗi lượt coding phức tạp


def read_state() -> dict:
    """Đọc state.json; dừng ngay lập tức nếu file không tồn tại hoặc nội dung bị hỏng."""
    if not STATE_FILE.exists():
        raise FileNotFoundError(f"[Orchestrator] File {STATE_FILE} không tồn tại!")
    with open(STATE_FILE, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"[Orchestrator] Nội dung {STATE_FILE} không phải JSON object hợp lệ!")
    return data


def write_state(data: dict) -> None:
    """Ghi state.json bằng UTF-8 sạch (không BOM)."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_coder_antigravity(task_desc: str) -> bool:
    """
    Gọi Antigravity CLI:
    - cwd tại REPO_DIR
    - stdin=DEVNULL
    - stream log và kiểm tra chặt chẽ timeout / partial output
    - theo dõi file handoff/live_progress.md
    """
    print(f"\n[Orchestrator] ========================================================")
    print(f"[Orchestrator] >>> BẮT ĐẦU: ANTIGRAVITY (CODER) ĐANG LÀM VIỆC...")
    print(f"[Orchestrator] ========================================================\n")

    prompt = (
        f"Bạn là CODER trong repository {REPO_DIR}. "
        f"Hãy đọc PROJECT_CONTEXT.md, state.json, handoff/review_feedback.md và git diff. "
        f"Nhiệm vụ: {task_desc}.\n\n"
        f"QUY TẮC BẮT BUỘC:\n"
        f"1. Trong khi làm việc, hãy ghi các mốc tiến độ ngắn gọn vào handoff/live_progress.md bằng cách ghi đè nội dung.\n"
        f"   Ví dụ:\n"
        f"   - [HH:MM] Đã đọc context và xác định phạm vi code\n"
        f"   - [HH:MM] Đang sửa src/...\n"
        f"   - [HH:MM] Đang chạy pytest\n"
        f"   - [HH:MM] Đã cập nhật coder_report.md và chuyển state sang REVIEW\n"
        f"   Không ghi chain-of-thought hay suy nghĩ nội bộ vào file này.\n"
        f"2. Chạy test xác minh ('python -m pytest tests -q').\n"
        f"3. Cập nhật handoff/coder_report.md tóm tắt thay đổi.\n"
        f"4. BẮT BUỘC cập nhật state.json: đổi 'state' thành 'REVIEW', 'next_actor' thành 'CODEX'.\n"
        f"Tuyệt đối không sửa ngoài phạm vi cho phép."
    )

    # Dùng cú pháp chuẩn theo khuyến nghị: agy f"--print={prompt}" với model mặc định đã xác nhận hoạt động
    cmd = [
        "agy",
        f"--print={prompt}",
        "--dangerously-skip-permissions",
        f"--print-timeout={TURN_TIMEOUT_SECONDS}s",
    ]

    print(f"[Orchestrator] Running: agy --print=[PROMPT] (cwd={REPO_DIR})")

    collected_output = []
    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(REPO_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in iter(process.stdout.readline, ""):
            collected_output.append(line)
            print(f"[Antigravity] {line}", end="", flush=True)

        return_code = process.wait(timeout=TURN_TIMEOUT_SECONDS)
        full_text = "".join(collected_output)

        # 1. Kiểm tra timeout giả mạo exit code 0
        if "print timeout" in full_text.lower() or "turn in progress" in full_text.lower():
            print(f"\n[Orchestrator] LỖI: Antigravity bị timeout (print timeout) dù exit code là {return_code}!")
            return False

        if return_code != 0:
            print(f"\n[Orchestrator] LỖI: Antigravity kết thúc với mã lỗi {return_code}!")
            return False

        print(f"\n[Orchestrator] Antigravity hoàn thành tiến trình CLI thành công (exit code: 0)")
        return True

    except subprocess.TimeoutExpired:
        process.kill()
        print(f"\n[Orchestrator] LỖI: Subprocess bị timeout ({TURN_TIMEOUT_SECONDS}s)!")
        return False
    except Exception as e:
        print(f"\n[Orchestrator] LỖI khi gọi Antigravity: {e}")
        return False


def run_reviewer_codex(task_desc: str) -> bool:
    """Gọi Codex CLI và stream stdout từng dòng theo thời gian thực."""
    print(f"\n[Orchestrator] ========================================================")
    print(f"[Orchestrator] >>> BẮT ĐẦU: OPENAI CODEX (REVIEWER) ĐANG SOI CODE...")
    print(f"[Orchestrator] ========================================================\n")

    prompt = (
        f"Bạn là REVIEWER trong repo {REPO_DIR}.\n"
        f"PHẠM VI ĐỌC BẮT BUỘC:\n"
        f"- PROJECT_CONTEXT.md\n"
        f"- state.json\n"
        f"- handoff/coder_report.md\n"
        f"- git diff cùng các file nguồn/test bị thay đổi tương ứng\n"
        f"Không đọc lại các file tài liệu hoặc lịch sử ngoài phạm vi này để tối ưu token.\n\n"
        f"Task cần review: {task_desc}.\n"
        f"Chạy lệnh xác minh: python -m pytest tests -q\n"
        f"Nếu đạt yêu cầu thì ghi nhận xét ngắn gọn vào handoff/review_feedback.md và cập nhật state.json sang state=PASSED, next_actor=ANTIGRAVITY.\n"
        f"Nếu chưa đạt, ghi lỗi cụ thể vào handoff/review_feedback.md và cập nhật state.json sang state=NEEDS_FIX, next_actor=ANTIGRAVITY."
    )

    codex_executable = r"C:\Users\MSI\AppData\Roaming\npm\codex.cmd"
    cmd = [
        codex_executable,
        "exec",
        prompt,
        "-C", str(REPO_DIR),
        "--dangerously-bypass-approvals-and-sandbox",
    ]

    print(f"[Orchestrator] Running: codex exec [PROMPT] -C {REPO_DIR} --dangerously-bypass-approvals-and-sandbox")

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(REPO_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        for line in iter(process.stdout.readline, ""):
            print(f"[Codex] {line}", end="", flush=True)

        return_code = process.wait(timeout=TURN_TIMEOUT_SECONDS)
        if return_code != 0:
            print(f"\n[Orchestrator] LỖI: Codex kết thúc với mã lỗi {return_code}!")
            return False

        print(f"\n[Orchestrator] Codex hoàn thành lượt review (exit code: 0)")
        return True

    except subprocess.TimeoutExpired:
        process.kill()
        print(f"\n[Orchestrator] LỖI: Codex bị timeout ({TURN_TIMEOUT_SECONDS}s)!")
        return False
    except Exception as e:
        print(f"\n[Orchestrator] LỖI khi gọi Codex: {e}")
        return False


def main():
    print("==========================================================")
    print("  TITSMART AI: MULTI-AGENT ORCHESTRATOR (CLI-BASED)      ")
    print("==========================================================")

    state = read_state()
    current_iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", DEFAULT_MAX_ITERATIONS)
    task_desc = state.get("task", "Triển khai tính năng mới")

    print(f"Khởi động vòng lặp tự động cho task: {task_desc}")
    print(f"Thư mục làm việc: {REPO_DIR}")
    print(f"Vòng lặp hiện tại: {current_iteration} / {max_iterations}")

    while current_iteration <= max_iterations:
        state = read_state()
        current_state = state.get("state", "CODING")
        next_actor = state.get("next_actor", "ANTIGRAVITY")
        task_desc = state.get("task", task_desc)

        print(f"\n--- [Iteration {current_iteration}/{max_iterations}] State: {current_state} | Next Actor: {next_actor} ---")

        if current_state == "PASSED":
            print(f"\n[Orchestrator] >>> THÀNH CÔNG! Task '{task_desc}' đã đạt PASSED bởi Codex.")
            break

        if current_state in ("CODING", "NEEDS_FIX") or next_actor == "ANTIGRAVITY":
            # 1. Gọi Antigravity (Coder)
            success = run_coder_antigravity(task_desc)
            time.sleep(2)

            # BẮT BUỘC KIỂM TRA CHẶT CHẼ STATE BÀN GIAO:
            state_after = read_state()
            if not success or state_after.get("state") != "REVIEW":
                raise RuntimeError(
                    f"[Orchestrator] DỪNG KHẨN CẤP: Antigravity chưa bàn giao REVIEW "
                    f"(Thành công CLI: {success}, State hiện tại: '{state_after.get('state')}'). "
                    f"Dừng để tránh lặp lại task lỗi."
                )

        elif current_state == "REVIEW" or next_actor == "CODEX":
            # 2. Gọi Codex (Reviewer)
            success = run_reviewer_codex(task_desc)
            time.sleep(2)

            state_after = read_state()
            if state_after.get("state") == "PASSED":
                print(f"\n[Orchestrator] >>> HOÀN TẤT: Codex đã phê duyệt [ĐẠT] / PASSED!")
                break
            elif state_after.get("state") == "NEEDS_FIX":
                print(f"[Orchestrator] Codex yêu cầu sửa (NEEDS_FIX). Chuyển lại cho Antigravity...")
            else:
                raise RuntimeError(
                    f"[Orchestrator] DỪNG KHẨN CẤP: Codex chưa cập nhật trạng thái hợp lệ "
                    f"(State hiện tại: '{state_after.get('state')}')."
                )

        current_iteration += 1
        state_after["iteration"] = current_iteration
        write_state(state_after)

    if current_iteration > max_iterations:
        print(f"\n[Orchestrator] Đã chạm ngưỡng tối đa {max_iterations} vòng lặp. Dừng khẩn cấp!")


if __name__ == "__main__":
    main()
