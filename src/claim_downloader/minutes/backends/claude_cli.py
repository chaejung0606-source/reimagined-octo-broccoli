"""Claude Code CLI 백엔드 — 이 PC 에 로그인된 구독으로 돈다. API 키가 없다.

앱이 넘기는 것은 폴더 경로 한 줄뿐이고, 자료는 에이전트가 스스로 읽는다(Read·Glob·Bash·PowerShell).
회의 1건에 20~35턴이 들고 결과는 에이전트가 meeting.json 으로 저장한다.

옛 도구(core.py)의 find_claude · claude_command · _run_kwargs · check_claude · build_prompt 와
process_meeting 의 앞부분(CLI 실행 → JSON 읽기)을 그대로 옮겼다. **프롬프트는 글자 하나 바꾸지
않는다** — 길어지면 턴이 늘고 담당자는 Pro 플랜이다. 문서 만들기(뒷부분)는 백엔드와 무관하므로
process.py 에 있다.

--allowedTools 에 PowerShell 이 빠지면 안 된다. 윈도우의 Claude Code 에는 Bash 와 별개로
PowerShell 도구가 있어, 허용하지 않으면 계속 거부당하며 회의 1건에 22~33턴을 낭비한다.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import traceback
from pathlib import Path

from ... import settings
from ..errors import BackendError, _extract_json, _failure_reason
from ..logbook import log
from ..rules import load_rules
from ..textfile import _read_text

# 회의 1건당 최대 대기 시간(초)
TIMEOUT_SEC = 1800


def find_claude():
    """claude 실행 파일 경로를 찾는다. .exe 뿐 아니라 npm 설치본(.cmd)도 찾는다."""
    # 1) PATH 탐색. shutil.which 는 PATHEXT 를 적용하므로 claude.cmd 도 잡힌다.
    found = shutil.which("claude")
    if found:
        return found
    # 2) 알려진 설치 위치
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        os.path.join(home, ".local", "bin", "claude.exe"),
        os.path.join(home, ".local", "bin", "claude"),
        os.path.join(localappdata, "Programs", "claude", "claude.exe"),
        os.path.join(appdata, "npm", "claude.cmd"),
        os.path.join(appdata, "npm", "claude"),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return ""


def claude_command(exe, cli_args):
    """.cmd/.bat 은 CreateProcess 로 직접 실행할 수 없으므로 cmd.exe 로 감싼다."""
    if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/d", "/c", exe] + cli_args
    return [exe] + cli_args


def _run_kwargs(cwd, timeout):
    kwargs = dict(cwd=cwd, capture_output=True, text=True,
                  encoding="utf-8", errors="replace", timeout=timeout,
                  stdin=subprocess.DEVNULL)
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


LOGIN_HELP = (
    "Claude 에 로그인되어 있지 않은 것으로 보입니다.\n\n"
    "로그인이 필요하다면 이 창을 닫고 화면 맨 위 오른쪽의\n"
    "AI 단추('Claude Code · 로그인 필요')를 눌러 [로그인] 을 고르세요.\n"
    "알아서 로그인 창을 열어 드립니다.\n\n"
    "다만 이 확인이 틀릴 수도 있습니다.\n"
    "데스크톱 Claude 앱을 함께 쓰고 있거나 로그인 정보를 갱신하는 중이면\n"
    "실제로는 로그인되어 있는데도 이렇게 보일 수 있습니다.\n\n"
    "그래도 지금 작업을 시작할까요?\n"
    "(이미 로그인하셨다면 [예] 를 누르세요. 실제로 로그인이 안 되어 있으면\n"
    " 첫 회의가 실패하면서 바로 알려 드리고, 남은 회의는 건너뜁니다.)"
)


def check_claude():
    """실행 전 점검.

    돌려주는 값은 (상태, 안내문).
    상태는 'ok'(정상), 'no_claude'(claude 를 쓸 수 없음), 'no_login'(로그인 의심)."""
    exe = find_claude()
    if not exe:
        return ("no_claude", "claude 명령을 찾을 수 없습니다.\n\n"
                             "Claude Code 를 설치한 뒤 컴퓨터를 다시 시작하거나,\n"
                             "명령 프롬프트에서 'claude --version' 이 동작하는지 확인해 주세요.")
    try:
        r = subprocess.run(claude_command(exe, ["--version"]), **_run_kwargs(None, 60))
    except Exception as e:
        return ("no_claude", "claude 실행에 실패했습니다.\n\n%s\n%s" % (exe, e))
    if r.returncode != 0:
        return ("no_claude", "claude 실행에 실패했습니다.\n\n%s\n%s"
                % (exe, (r.stderr or r.stdout or "").strip()[:300]))
    version = (r.stdout or "").strip()

    # 로그인 여부는 참고용으로만 본다. 이 확인이 틀려도 작업을 막지 않는다.
    try:
        a = subprocess.run(claude_command(exe, ["auth", "status", "--json"]),
                           **_run_kwargs(None, 60))
        info = _extract_json(a.stdout)
        if isinstance(info, dict) and info.get("loggedIn") is False:
            log("로그인 확인 결과 loggedIn=false\nstdout=%s\nstderr=%s"
                % ((a.stdout or "")[:500], (a.stderr or "")[:500]))
            return ("no_login", LOGIN_HELP)
    except Exception:
        pass        # 예전 버전이라 auth 명령이 없으면 그냥 넘어간다
    return ("ok", version)


def build_prompt(meeting_dir, json_path, rules=None):
    return (
        "당신은 대학 사업단의 회의비 정산용 '회의록' 작성 도구입니다.\n"
        "'" + meeting_dir + "' 폴더 안의 모든 회의 자료 파일을 읽으세요(하위 폴더 포함).\n"
        "다만 이 폴더에 있는 .hwpx 파일과, 파일명이 날짜(yyyy-mm-dd)로 시작하는 .docx 파일은 "
        "이 도구가 앞서 만든 회의록이므로 자료가 아닙니다. "
        "그런 파일은 열지도 말고 참고하지도 마세요.\n"
        "PDF와 이미지(영수증·서명부 사진 등)는 직접 읽으세요.\n"
        ".docx 는 ZIP 압축 파일이므로, Bash 도구에서 사용 가능한 방법(unzip, python, powershell 등 "
        "그 환경에서 실제로 동작하는 것)으로 풀어 word/document.xml 의 본문 텍스트를 읽으세요.\n"
        ".hwp 는 직접 읽기 어려우니 읽지 못하면 supplement 에 '한글(.hwp) 파일은 PDF로 변환 후 다시 넣어주세요'라고 적으세요.\n"
        "아래 [규칙]에 따라 회의록 내용을 정리한 뒤, 결과를 정확히 '" + json_path + "' 경로에 UTF-8 JSON 파일로 저장하세요(Write 도구 사용).\n"
        "JSON 스키마:\n"
        '{\n'
        '  "filenameBase": "[yyyy-mm-dd(요일) 안건요약]",\n'
        '  "agenda": "회의안건",\n'
        '  "date": "YYYY. M. D. (요일) HH:MM ~ HH:MM",\n'
        '  "place": "회의장소",\n'
        '  "expensePlace": "회의비 사용처(영수증 가맹점명)",\n'
        '  "amount": "금액(영수증 합계, 예: 120,000원)",\n'
        '  "attendeeCount": 8,\n'
        '  "attendees": [{"org": "강원대학교", "name": "이성재"}, {"org": "강원대학교", "name": "황승재"}],\n'
        '  "content": ["회의내용 1문단(여러 문장)", "2문단(여러 문장)"],\n'
        '  "supplement": "보완요청. 문제 없으면 \\"보완사항 없음\\""\n'
        '}\n'
        "attendees 는 이름을 확인할 수 있는 사람만 소속/이름으로 한 명씩 담으세요.\n"
        "attendeeCount 는 회의비 기안공문에 적힌 참석 인원 수입니다. 단가별 인원이 적혀 있으면 "
        "그 수(여러 단가면 합계)를 숫자로 넣으세요. 찾지 못하면 0 을 넣으세요.\n"
        "위 JSON 파일 하나만 저장하고 다른 파일은 만들지 마세요. 반드시 한국어로 작성하세요.\n\n"
        "[규칙]\n" + (rules if rules is not None else load_rules())
    )


def open_login(email: str = "") -> None:
    """Claude 로그인 창을 대신 열어 준다(claude 가 PATH 에 없어도 동작).

    로그인 절차가 눈에 보여야 하므로 새 콘솔 창에서 실행한다. 이메일은 로그인 화면에 미리 채워
    넣는 용도이고 settings.claude_email 에만 남는다 — 비밀번호는 어디에도 두지 않는다.
    """
    exe = find_claude()
    if not exe:
        raise BackendError("claude 명령을 찾을 수 없음")
    args = ["auth", "login", "--claudeai"]
    if email:
        args += ["--email", email]
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    subprocess.Popen(claude_command(exe, args), **kwargs)


class ClaudeCliBackend:
    key = "claude-cli"
    label = "Claude Code (이 PC 에 로그인된 Claude 구독)"

    def __init__(self, model: str | None = None):
        # 비우면 CLI 의 기본 모델. 설정(minutes_model)으로 바꿀 수 있다.
        self.model = settings.load().minutes_model if model is None else model
        self.last_state = ""        # check_claude 의 상태 — 화면이 '로그인 확인' 을 따로 보여 준다

    def available(self) -> tuple[bool, str]:
        state, info = check_claude()
        self.last_state = state
        if state == "no_claude":
            return False, info
        if state == "no_login":
            return True, "로그인이 풀린 것으로 보입니다 (틀릴 수 있어 막지는 않습니다)"
        return True, "Claude Code " + info

    def generate(self, meeting_dir: Path, rules: str) -> dict:
        meeting_dir = str(meeting_dir)
        exe = find_claude()
        if not exe:
            raise BackendError("claude 명령을 찾을 수 없음")

        tmp = tempfile.mkdtemp(prefix="mm_")
        json_path = os.path.join(tmp, "meeting.json")
        cli_args = [
            "-p", build_prompt(meeting_dir, json_path, rules),
            "--output-format", "json",
            "--permission-mode", "acceptEdits",
            "--allowedTools", "Read,Glob,Grep,Write,Edit,Bash,PowerShell",
            "--add-dir", tmp,
        ]
        if self.model:
            cli_args += ["--model", self.model]
        args = claude_command(exe, cli_args)

        try:
            r = subprocess.run(args, **_run_kwargs(meeting_dir, TIMEOUT_SEC))
        except FileNotFoundError:
            shutil.rmtree(tmp, ignore_errors=True)
            log("실행 실패(FileNotFoundError): %s" % exe)
            raise BackendError("claude 실행 파일을 열 수 없음")
        except subprocess.TimeoutExpired:
            shutil.rmtree(tmp, ignore_errors=True)
            log("시간 초과: %s" % meeting_dir)
            raise BackendError("시간 초과(자료가 너무 많음)")
        except Exception as e:
            shutil.rmtree(tmp, ignore_errors=True)
            log("실행 오류: %s\n%s" % (meeting_dir, traceback.format_exc()))
            raise BackendError("실행 오류: " + str(e)[:60])

        data = None
        if not os.path.exists(json_path):
            cands = glob.glob(os.path.join(tmp, "*.json"))
            json_path = cands[0] if cands else None
        if json_path and os.path.exists(json_path):
            try:
                text = _read_text(json_path)
            except Exception:
                log("결과 파일을 읽지 못함: %s\n%s" % (json_path, traceback.format_exc()))
                text = ""
            try:
                data = json.loads(text)
            except Exception:
                data = _extract_json(text)

        if data is None:
            # 파일이 없으면 CLI 출력(JSON)의 result 안에 내용이 들어있는 경우가 있다.
            outer = _extract_json(r.stdout)
            if isinstance(outer, dict) and outer.get("result"):
                data = _extract_json(str(outer.get("result")))

        shutil.rmtree(tmp, ignore_errors=True)
        if not isinstance(data, dict):
            log("회의록 데이터 없음: %s\nrc=%s\nstdout=%s\nstderr=%s"
                % (meeting_dir, r.returncode, (r.stdout or "")[:4000], (r.stderr or "")[:4000]))
            raise BackendError(_failure_reason(r))
        return data
