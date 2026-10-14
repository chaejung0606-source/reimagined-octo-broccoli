"""자동 업데이트.

Claude 가 저장소에 기능을 올리면 앱이 그것을 받아 오도록 한다.
설치본이 git 작업본이면 `git pull --ff-only` 로 갱신한다.

안전 원칙
  - 정해진 저장소·브랜치에서만 받는다. 임의 원격은 거부한다.
  - 확인과 적용을 분리한다. 기본값은 '확인만' 이고, 적용은 사용자가 누른다.
  - 설정과 받은 기록은 `~/.claim-downloader/` 에 있어 pull 대상이 아니다.
    업데이트를 받아도 저장 폴더 지정과 받은 기록이 그대로 남는다.
  - 로컬 변경이 있으면 덮어쓰지 않고 멈춘다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 이 저장소·브랜치에서만 업데이트를 받는다. 이름은 지출 서류 검토 앱 시절 그대로다 —
# 이미 설치된 앱들이 이 브랜치를 보고 있어서 바꾸면 업데이트가 끊긴다.
EXPECTED_REPO = "chaejung0606-source/reimagined-octo-broccoli"
BRANCH = "claude/expense-document-review-criteria-yzji9p"

GIT_TIMEOUT = 60


@dataclass
class UpdateStatus:
    available: bool = False
    behind: int = 0
    current: str = ""
    latest: str = ""
    messages: tuple[str, ...] = ()
    blocked_reason: str = ""     # 적용할 수 없는 이유 (로컬 변경 등)
    error: str = ""

    @property
    def can_apply(self) -> bool:
        return self.available and not self.blocked_reason and not self.error

    def describe(self) -> str:
        if self.error:
            return f"업데이트를 확인하지 못했습니다: {self.error}"
        if not self.available:
            return "최신 상태입니다."
        head = f"새 업데이트 {self.behind}건이 있습니다."
        if self.blocked_reason:
            return f"{head} 다만 {self.blocked_reason}"
        return head


def _git(*args: str, timeout: int = GIT_TIMEOUT) -> subprocess.CompletedProcess:
    """git 을 돌리고 결과를 돌려준다. 실패해도 예외를 던지지 않는다.

    호출부가 returncode 만 보게 하려는 것이다. 예외가 위로 새면 화면에는
    '오류가 발생했습니다' 만 남고 무엇이 문제인지 알 수 없다.

    인코딩을 UTF-8 로 못박는다. 한글 윈도우에서 text=True 만 주면 파이썬이
    CP949 로 해석해 커밋 메시지와 날짜 구분점(·)이 깨진다.
    """
    env = {
        **os.environ,
        # 자격 증명 창이 뜨면 앱이 멈춘 것처럼 보인다. 물어보지 말고 실패시킨다.
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "never",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    # 줄바꿈 변환을 끈다. 저장소의 .bat/.vbs 는 CRLF 인데 윈도우 git 의 autocrlf=true 아래서는
    # 이 파일들이 늘 '수정됨' 으로 보여 업데이트가 "저장하지 않은 변경" 으로 막혔다(2026-10-12).
    # 받은 파일은 저장소에 있는 그대로(파이썬은 LF, 배치는 CRLF) 쓰면 되므로 변환이 필요 없다.
    command = [_git_executable(), "-c", "core.autocrlf=false", "-c", "core.safecrlf=false",
               "-C", str(REPO_ROOT), *args]
    # 창 없는 실행(pythonw) 아래서는 git 이 호출마다 검은 콘솔 창을 띄웠다 닫는다. 숨긴다.
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        done = subprocess.run(
            command,
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env, **hidden,
        )
    except FileNotFoundError:
        return _result(args, 127,
                       "Git 이 설치되어 있지 않습니다. https://git-scm.com/download/win "
                       "에서 설치한 뒤 앱을 다시 시작하세요.")
    except subprocess.TimeoutExpired:
        return _result(args, 124,
                       f"응답이 {timeout}초 안에 오지 않았습니다. 네트워크를 확인해 주세요.")
    except OSError as error:
        return _result(args, 1, str(error))

    # stdout/stderr 를 문자열로 못박는다.
    # 캡처가 되지 않으면 파이썬은 None 을 돌려준다. 호출부는 .strip() 을 부르므로
    # 그대로 두면 'NoneType has no attribute strip' 으로 앱이 죽는다.
    # 실제로 사용자 PC에서 이 지점이 터졌다.
    return subprocess.CompletedProcess(
        done.args, done.returncode, done.stdout or "", done.stderr or "")


def relaunch_command() -> list[str]:
    """앱을 새로 띄우는 명령. 화면의 [새로고침] 이 쓴다.

    윈도우에서는 '앱 실행 (창 없이).vbs' 를 우선 쓴다 — 준비 표시(setup-claim-vN)를 보고, 의존성이
    바뀐 업데이트면 준비 단계까지 다시 돌아 주기 때문이다. 없으면 지금 파이썬으로 모듈을 띄운다
    (pythonw 로 떴으면 pythonw 라 창이 없다).
    """
    vbs = REPO_ROOT / "앱 실행 (창 없이).vbs"
    if os.name == "nt" and vbs.exists():
        return ["wscript.exe", str(vbs)]
    return [sys.executable, "-m", "claim_downloader.ui.app"]


def relaunch() -> None:
    """새 앱을 띄운다. 부르는 쪽이 곧 자기 창을 닫는다 — 둘이 겹치는 순간은 2~3초뿐이다."""
    extra = {}
    if os.name == "nt":
        # 지금 프로세스가 끝나도 새 앱이 따라 죽지 않게 떼어 낸다
        extra["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        extra["start_new_session"] = True
    # 입출력도 떼어 낸다 — 물려받으면 새 앱이 이 프로세스의 파이프를 붙들고 있어 부모가 못 끝날 수 있다
    subprocess.Popen(relaunch_command(), cwd=str(REPO_ROOT), close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **extra)


def _git_executable() -> str:
    """PATH 에 git 이 없어도 설치 스크립트(setup.ps1)가 둔 휴대용 MinGit 을 찾는다.

    설치 스크립트는 관리자 권한 없이 쓰려고 Git 을 시스템에 설치하지 않고 앱 옆 tools\\MinGit 에
    푼다. 바탕화면 바로가기로 띄운 앱의 PATH 에는 그것이 없으므로 여기서 직접 찾는다. 일반 설치본
    (Git for Windows)의 기본 위치도 함께 본다 — PATH 에 안 넣고 설치한 경우가 있다.
    """
    found = shutil.which("git")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("PROGRAMFILES", "")
    candidates = [REPO_ROOT.parent / "tools" / "MinGit" / "cmd" / "git.exe"]      # setup.ps1 의 배치
    if local:
        candidates.append(Path(local) / "COSS업무데스크" / "tools" / "MinGit" / "cmd" / "git.exe")
        candidates.append(Path(local) / "Programs" / "Git" / "cmd" / "git.exe")
    if program_files:
        candidates.append(Path(program_files) / "Git" / "cmd" / "git.exe")
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return "git"


def _result(args, code: int, message: str) -> subprocess.CompletedProcess:
    """git 을 못 돌렸을 때 쓸 결과. 호출부가 returncode 만 보면 되도록 모양을 맞춘다."""
    return subprocess.CompletedProcess(args, code, "", message)


def _first_line(text: str, fallback: str) -> str:
    """git 이 남긴 설명 중 쓸 만한 마지막 줄. 비어 있으면 준비된 문구로."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1][:200] if lines else fallback


def is_git_checkout() -> bool:
    return (REPO_ROOT / ".git").exists()


def _remote_is_expected() -> bool:
    result = _git("remote", "get-url", "origin")
    return result.returncode == 0 and EXPECTED_REPO in result.stdout


def current_version() -> str:
    """짧은 커밋 해시 + 날짜. 화면에 '설치된 버전'으로 보여 준다."""
    if not is_git_checkout():
        return "(개발 설치)"
    result = _git("log", "-1", "--format=%h · %cd", "--date=format:%Y-%m-%d")
    return result.stdout.strip() if result.returncode == 0 else "(알 수 없음)"


def check() -> UpdateStatus:
    """원격에 새 커밋이 있는지 본다. 파일은 건드리지 않는다.

    무슨 일이 있어도 예외를 던지지 않는다. 예외가 위로 새면 화면에는
    '오류가 발생했습니다' 만 남고 무엇이 문제인지 알 수 없다. 예상 못 한
    상황이라도 사람이 읽을 수 있는 문구로 바꿔 돌려준다.
    """
    try:
        return _check()
    except Exception as error:                       # noqa: BLE001
        return UpdateStatus(error=f"업데이트 확인 중 예상 못 한 문제: {error}"[:200])


def _check() -> UpdateStatus:
    if not is_git_checkout():
        return UpdateStatus(
            error="설치 폴더에 저장소 정보(.git)가 없어 자동 업데이트를 쓸 수 없습니다. "
                  "새 zip 을 받아 폴더째 교체해 주세요.")
    remote = _git("remote", "get-url", "origin")
    if remote.returncode != 0:
        return UpdateStatus(error=_first_line(remote.stderr, "저장소 정보를 읽지 못했습니다."))
    if EXPECTED_REPO not in remote.stdout:
        return UpdateStatus(error="원격 저장소가 예상과 다릅니다. 업데이트를 중단합니다.")

    # 느린 학교망에서 받기가 멈춘 채 붙들려 있지 않게 — 30초 동안 초당 1KB 도 안 오면 끊는다
    fetched = _git("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=30", "fetch", "origin", BRANCH)
    if fetched.returncode != 0:
        # 학교망·방화벽에서 막히는 일이 실제로 있었다. 막힌 채로 두지 않고
        # 다른 길을 함께 알려 준다.
        return UpdateStatus(error=(
            _first_line(fetched.stderr, "네트워크 오류")
            + "  ·  받아오지 못하면 새 zip 을 받아 폴더째 교체하셔도 됩니다."))

    counted = _git("rev-list", "--count", f"HEAD..origin/{BRANCH}")
    if counted.returncode != 0:
        return UpdateStatus(error=_first_line(counted.stderr, "변경 사항을 세지 못했습니다."))
    try:
        behind = int(counted.stdout.strip() or 0)
    except ValueError:
        return UpdateStatus(error="변경 사항 수를 읽지 못했습니다.")

    status = UpdateStatus(
        available=behind > 0,
        behind=behind,
        current=current_version(),
        latest=_git("log", "-1", "--format=%h", f"origin/{BRANCH}").stdout.strip(),
    )
    if behind:
        log = _git("log", "--format=%s", f"HEAD..origin/{BRANCH}")
        status.messages = tuple(line for line in log.stdout.strip().splitlines() if line)[:10]

    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty.returncode == 0 and dirty.stdout.strip():
        status.blocked_reason = (
            "이 폴더에 저장하지 않은 변경이 있어 자동 적용을 멈췄습니다. "
            "변경을 정리한 뒤 다시 시도하세요."
        )
    return status


LOCK_STALE_SECONDS = 600


def _clear_stale_lock() -> None:
    """앞선 적용이 끊겨 남은 .git/index.lock 을 치운다 — 남아 있으면 적용이 매번 실패했다. 10분 넘은 것만(지금 도는 git 의 것은 아니다)."""
    lock = REPO_ROOT / ".git" / "index.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
            lock.unlink()
    except OSError:
        pass


def apply() -> tuple[bool, str]:
    """확인된 업데이트를 적용한다. 되돌릴 수 없는 병합은 하지 않는다.

    check() 와 마찬가지로 예외를 밖으로 내보내지 않는다.
    """
    try:
        return _apply()
    except Exception as error:                       # noqa: BLE001
        return False, f"업데이트 적용 중 예상 못 한 문제: {error}"[:200]


def _apply() -> tuple[bool, str]:
    status = check()
    if status.error:
        return False, status.error
    if not status.available:
        return True, "이미 최신 상태입니다."
    if status.blocked_reason:
        return False, status.blocked_reason

    _clear_stale_lock()
    # 파일을 바꾸는 단계라 60초에 끊지 않는다 — 백신 검사로 느린 PC 에서 중간에 끊겨 반쯤 바뀐 채 남을 수 있었다(2026-10-14 점검)
    pulled = _git("merge", "--ff-only", f"origin/{BRANCH}", timeout=600)
    if pulled.returncode != 0:
        return False, (
            "빨리감기로 갱신할 수 없습니다. 로컬 커밋이 있는지 확인하세요.\n"
            + _first_line(pulled.stderr, "")
        )
    return True, f"업데이트 {status.behind}건을 적용했습니다. 앱을 다시 시작하면 반영됩니다."
