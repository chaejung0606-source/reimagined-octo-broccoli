"""AI 플랫폼 — 회의록 생성 · 일반청구가 쓰는 AI 를 한 곳에서 고르고, 로그인됐는지 보고, 로그인 창을 연다.

담당자 요청(2026-10-14): 쓸 AI 플랫폼은 설정에서 정하고(회의록 생성 `minutes_backend` · 일반청구 `claim_backend`),
앱을 켜면 홈에서 바로 로그인 상태를 보고, 로그아웃돼 있으면 거기서 로그인한다. 그래서 확인 · 로그인은 화면마다 따로 하지 않고
여기 하나로 모은다(화면 쪽은 ui/ai_status.py 가 이것을 뒤에서 부른다).

Qt 를 들여오지 않는다 — tests/test_ai.py 가 PySide6 없이 본다. 확인(probe)은 몇 초 걸리는 외부 명령(claude --version ·
auth status)이라 부르는 쪽이 화면 스레드 밖에서 부른다. 로그인 정보(비밀번호)는 어디에도 두지 않는다 — 로그인은 그 플랫폼의
로그인 창에서 사람이 한다. 이메일은 로그인 화면에 미리 채우는 용도로만 설정(`claude_email`)에 남는다.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import settings as settings_mod
from .claims import extract
from .minutes import backends as minutes_backends
from .minutes.backends import claude_cli

# 상태 — 화면은 이 글자로 색과 문구를 정한다
CHECKING = "checking"
OK = "ok"
NO_LOGIN = "no_login"        # 설치는 됐는데 로그인이 풀려 있음 — 로그인하면 쓸 수 있다
MISSING = "missing"          # 이 PC 에서 쓸 수 없음(설치 안 됨 등)
ERROR = "error"              # 확인하다 예상 못 한 문제

STATE_TEXT = {
    CHECKING: "확인 중",
    OK: "로그인됨",
    NO_LOGIN: "로그인 필요",
    MISSING: "사용 불가",
    ERROR: "확인 실패",
}
STATE_TONE = {CHECKING: "neutral", OK: "success", NO_LOGIN: "warning", MISSING: "danger", ERROR: "danger"}

# 업무 → 그 업무에 쓸 플랫폼이 적힌 설정 이름
USES = {
    "minutes": ("회의록 생성", "minutes_backend"),
    "claim": ("일반청구", "claim_backend"),
}


@dataclass
class Status:
    key: str
    state: str = CHECKING
    note: str = ""
    checked_at: float = 0.0

    @property
    def label(self) -> str:
        return label_of(self.key)

    @property
    def usable(self) -> bool:
        """작업을 시작해도 되는지. 로그인 확인은 틀릴 수 있어(데스크톱 앱과 함께 쓸 때 등) 막지는 않는다 — 화면이 묻는다."""
        return self.state in (OK, NO_LOGIN)

    @property
    def text(self) -> str:
        return STATE_TEXT.get(self.state, self.state)

    @property
    def tone(self) -> str:
        return STATE_TONE.get(self.state, "neutral")


def platforms(use: str = "minutes") -> list[tuple[str, str]]:
    """(key, 화면 이름) — 그 업무에 고를 수 있는 플랫폼. 일반청구는 일반청구 추출기가 있는 플랫폼만."""
    if use == "claim":
        return extract.labels()
    return minutes_backends.labels()


def label_of(key: str) -> str:
    for k, label in minutes_backends.labels() + extract.labels():
        if k == key:
            return label
    return key


def short_label(key: str) -> str:
    """위쪽 바처럼 좁은 곳에 쓰는 이름 — 괄호 앞까지. 'Claude Code (이 PC 에 …)' → 'Claude Code'."""
    return label_of(key).split(" (", 1)[0]


def chosen(use: str, cfg: settings_mod.Settings | None = None) -> str:
    """그 업무에 쓰기로 정한 플랫폼 key. 모르는 값이면 기본 플랫폼."""
    cfg = cfg or settings_mod.load()
    _name, field = USES[use]
    key = str(getattr(cfg, field, "") or "")
    keys = [k for k, _ in platforms(use)]
    return key if key in keys else (keys[0] if keys else minutes_backends.DEFAULT_KEY)


def used_keys(cfg: settings_mod.Settings | None = None) -> list[str]:
    """지금 설정에서 쓰는 플랫폼들(겹치면 하나) — 홈 · 위쪽 바가 이것들의 상태를 본다."""
    cfg = cfg or settings_mod.load()
    out: list[str] = []
    for use in USES:
        key = chosen(use, cfg)
        if key not in out:
            out.append(key)
    return out


def probe(key: str) -> Status:
    """그 플랫폼을 이 PC 에서 쓸 수 있는지 · 로그인됐는지. 몇 초 걸린다 — 화면 스레드에서 부르지 않는다."""
    status = Status(key=key, checked_at=time.time())
    try:
        # 회의록 · 일반청구가 같은 key 를 쓰면 같은 프로그램이다 — 일반청구에만 있는 플랫폼이면 그쪽 것으로 본다
        backend = minutes_backends.get(key) if key in minutes_backends.keys() else extract.get(key)
        ok, note = backend.available()
        state = getattr(backend, "last_state", "") or ("ok" if ok else "")
    except Exception as error:  # noqa: BLE001 — 확인이 터져도 앱은 떠 있어야 한다
        status.state, status.note = ERROR, (str(error).splitlines()[0][:160] if str(error) else type(error).__name__)
        return status
    status.note = (note or "").replace("\n", " ").strip()
    if not ok:
        status.state = MISSING
    elif state == "no_login":
        status.state = NO_LOGIN
    else:
        status.state = OK
    return status


def can_login(key: str) -> bool:
    return key == claude_cli.ClaudeCliBackend.key


def open_login(key: str, email: str = "") -> None:
    """그 플랫폼의 로그인 창을 연다(Claude Code: 새 콘솔 창 → 브라우저). 못 열면 예외 — 화면이 사유를 보여 준다."""
    if not can_login(key):
        raise RuntimeError(f"'{label_of(key)}' 는 앱에서 로그인 창을 열 수 없습니다")
    claude_cli.open_login(email)


def summary(statuses: list[Status]) -> Status | None:
    """여럿 중 가장 손이 필요한 것 하나 — 위쪽 바 · 홈 띠가 보여 줄 대표. 없으면 None."""
    order = {MISSING: 0, ERROR: 1, NO_LOGIN: 2, CHECKING: 3, OK: 4}
    return min(statuses, key=lambda s: order.get(s.state, 9)) if statuses else None
