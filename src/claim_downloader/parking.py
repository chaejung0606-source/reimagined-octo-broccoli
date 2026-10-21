"""주차등록 — 교내 주차 등록 사이트(traffic.kangwon.ac.kr)를 앱 브라우저에서 열고 자동으로 로그인한다.

담당자 요청(2026-10-21): 업무에 주차등록을 더하고, 기본은 앱 화면에서 입력하면 사이트에 들어가는 방식(2단계), 그리고 브라우저를 열어
직접 입력하는 단추도. 사이트 화면은 아직 실측 전이다(이 작업 환경에서는 그 주소에 닿지 않는다) — 1단계는 사이트를 열고 로그인까지,
등록 화면의 칸은 담당자가 [화면 구조 저장] 으로 실측을 보내 준 뒤에 만든다(CLAUDE.md 4절 '실측부터').

로그인 정보: ERP 와 달리 담당자가 자동 로그인을 허락했다(2026-10-21 — "여기엔 개인정보같은게 없어서 자동 로그인해도 괜찮습니다").
그래도 코드 · 저장소 · 설정 파일(config.json) · 기록에는 두지 않는다. 담당자가 설정 화면에서 한 번 넣으면 이 PC 의 사용자 폴더
`_주차로그인.json` 에 두고, 비밀번호는 윈도우 DPAPI(그 윈도우 사용자 계정으로만 풀리는 암호화)로 감싼다. ERP 쪽 코드는 이 파일을
읽지 않는다(tests/test_safety.py).

자동 로그인은 사이트를 열 때 **한 번만** 한다 — 아이디 · 비밀번호 칸을 찾아 넣고 Enter, 로그인 칸이 그대로면 '로그인' 단추를 한 번.
그래도 안 되면 멈추고 사람에게 넘기며, 앱을 다시 켜거나 로그인 정보를 고치기 전에는 다시 시도하지 않는다(틀린 비밀번호로 여러 번
시도해 계정이 잠기지 않게). Playwright 를 들여오지 않는다 — 창(page)은 session.py 가 넘겨준다.
"""
from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from . import settings

DEFAULT_URL = "https://traffic.kangwon.ac.kr/login"
HOST = "traffic.kangwon.ac.kr"
IS_WINDOWS = os.name == "nt"           # 담당자 PC — 비밀번호를 DPAPI 로 감싼다(시험에서 바꿔 끼운다)

# 보이는 비밀번호 칸의 수 — 로그인 화면인지 본다
LOGIN_FORM_JS = """() => Array.from(document.querySelectorAll('input[type=password]')).filter(e => {
  const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length"""

# 아이디 칸(비밀번호 칸 바로 앞의 글 칸) · 비밀번호 칸에 표시를 붙인다 — 값은 Playwright fill 로 넣는다(키 입력 이벤트가 돈다)
MARK_LOGIN_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const pws = Array.from(document.querySelectorAll('input[type=password]')).filter(vis);
  if (pws.length !== 1) return {ok: false, why: pws.length ? '비밀번호 칸이 여럿' : '비밀번호 칸이 없음'};
  const pw = pws[0];
  const scope = pw.form || document;
  const texts = Array.from(scope.querySelectorAll('input')).filter(e => vis(e) && !e.disabled && !e.readOnly
    && /^(text|email|tel|)$/.test((e.getAttribute('type') || '').toLowerCase()));
  const before = texts.filter(e => e.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING);
  const id = before[before.length - 1];
  if (!id) return {ok: false, why: '비밀번호 칸 앞에 아이디 칸이 없음'};
  document.querySelectorAll('[data-coss-login]').forEach(e => e.removeAttribute('data-coss-login'));
  id.setAttribute('data-coss-login', 'id');
  pw.setAttribute('data-coss-login', 'pw');
  return {ok: true, id: id.name || id.id || '', pw: pw.name || pw.id || ''};
}"""
ID_SELECTOR = "[data-coss-login=id]"
PW_SELECTOR = "[data-coss-login=pw]"

# Enter 로 넘어가지 않을 때 — 비밀번호 칸이 든 양식(없으면 화면)에서 글자 · 값이 '로그인'(Login) 인 단추가 하나일 때만 누른다
SUBMIT_JS = """() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const pw = document.querySelector('[data-coss-login=pw]');
  const scope = (pw && pw.form) || document;
  const label = e => ((e.innerText || e.textContent || '') + ' ' + (e.value || '') + ' ' + (e.getAttribute('alt') || '')
    + ' ' + (e.getAttribute('title') || '')).replace(/\\s+/g, '').toLowerCase();
  const cands = Array.from(scope.querySelectorAll('button, input[type=submit], input[type=button], input[type=image], a'))
    .filter(e => vis(e) && /^(로그인|login|signin|로그인하기)$/.test(label(e)));
  if (cands.length !== 1) return {ok: false, why: cands.length ? "'로그인' 단추가 여럿" : "'로그인' 단추가 없음"};
  cands[0].click();
  return {ok: true};
}"""

FAIL_WORDS = ("틀", "일치하지", "잘못", "확인해", "실패", "없는 아이디", "존재하지", "잠금", "invalid", "incorrect")


# ── 로그인 정보 (이 PC 에만) ──────────────────────────────────────────────
def login_path():
    return settings.data_dir() / "_주차로그인.json"


def _dpapi(data: bytes, protect: bool) -> bytes:
    """윈도우 DPAPI — 같은 윈도우 사용자 계정에서만 풀린다. ctypes 만 쓴다(새 의존성 없음)."""
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    out = Blob()
    ui_forbidden = 0x1
    if protect:
        ok = crypt32.CryptProtectData(ctypes.byref(source), "COSS 업무데스크 주차등록", None, None, None,
                                      ui_forbidden, ctypes.byref(out))
    else:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, ui_forbidden, ctypes.byref(out))
    if not ok:
        raise OSError("윈도우 암호화(DPAPI)에 실패했습니다")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _protect(secret: str) -> tuple[str, str]:
    data = secret.encode("utf-8")
    if IS_WINDOWS:
        return "dpapi", base64.b64encode(_dpapi(data, True)).decode("ascii")
    # 윈도우가 아닌 곳(개발 · 시험)에서는 감싸지 못한다 — 담당자 PC 는 윈도우다
    return "plain", base64.b64encode(data).decode("ascii")


def _unprotect(how: str, value: str) -> str:
    data = base64.b64decode(value.encode("ascii"))
    if how == "dpapi":
        if not IS_WINDOWS:
            raise OSError("윈도우에서 감싼 로그인 정보는 윈도우에서만 풉니다")
        data = _dpapi(data, False)
    return data.decode("utf-8")


def save_login(user: str, secret: str) -> None:
    user, secret = (user or "").strip(), secret or ""
    if not user or not secret:
        forget_login()
        return
    how, value = _protect(secret)
    path = login_path()
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps({"user": user, "how": how, "secret": value}, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    forget_failure()


def load_login() -> tuple[str, str] | None:
    """(아이디, 비밀번호) — 없거나 못 풀면 None(다른 윈도우 계정에서 만든 파일 등)."""
    try:
        data = json.loads(login_path().read_text(encoding="utf-8"))
        user, secret = str(data.get("user", "")), _unprotect(str(data.get("how", "")), str(data.get("secret", "")))
    except (OSError, ValueError, TypeError):
        return None
    return (user, secret) if user and secret else None


def saved_user() -> str:
    """화면에 보여 줄 아이디 — 비밀번호는 풀지 않는다."""
    try:
        return str(json.loads(login_path().read_text(encoding="utf-8")).get("user", ""))
    except (OSError, ValueError):
        return ""


def forget_login() -> None:
    try:
        login_path().unlink()
    except OSError:
        pass
    forget_failure()


# 이번 앱 실행에서 자동 로그인이 실패했는지 — 실패했으면 로그인 정보를 고치기 전에는 다시 시도하지 않는다(계정 잠김 방지)
_failed = {"why": ""}


def failed_before() -> str:
    return _failed["why"]


def forget_failure() -> None:
    _failed["why"] = ""


# ── 사이트 열기 · 로그인 ──────────────────────────────────────────────────
@dataclass
class OpenReport:
    opened: bool = False
    new_tab: bool = False
    tried_login: bool = False
    logged_in: bool = False
    note: str = ""
    messages: list[str] = field(default_factory=list)

    def lines(self) -> list[str]:
        if not self.opened:
            return ["✗ 주차등록 사이트를 열지 못했습니다" + (f" — {self.note}" if self.note else "")]
        out = ["✓ 주차등록 사이트를 열었습니다" + (" (새 탭)" if self.new_tab else "")]
        if self.logged_in:
            out.append("✓ 자동 로그인했습니다")
        elif self.note:
            out.append(("✗ " if self.tried_login else "· ") + self.note)
        out.extend("  사이트 알림: " + m for m in self.messages)
        return out


def is_site(url: str, site_url: str = DEFAULT_URL) -> bool:
    host = _host(site_url) or HOST
    return _host(url) == host


def _host(url: str) -> str:
    rest = str(url or "").split("://", 1)[-1]
    return rest.split("/", 1)[0].split(":", 1)[0].lower()


def login_frame(page):
    """비밀번호 칸이 하나 보이는 프레임(창 자체 먼저). 없으면 None."""
    for frame in list(getattr(page, "frames", []) or [page]):
        try:
            if int(frame.evaluate(LOGIN_FORM_JS) or 0) >= 1:
                return frame
        except Exception:  # noqa: BLE001 — 바뀌는 중인 프레임
            continue
    return None


def _wait_until(check: Callable[[], bool], wait: Callable[[float], None], tries: int, step: float = 0.5) -> bool:
    for _ in range(tries):
        try:
            if check():
                return True
        except Exception:  # noqa: BLE001 — 넘어가는 중
            pass
        wait(step)
    return False


def login(page, user: str, secret: str, log: Callable[[str], None],
          wait: Callable[[float], None] = time.sleep, report: OpenReport | None = None, fresh: bool = True) -> OpenReport:
    """한 번만 로그인한다. 비밀번호는 기록에 남기지 않는다. fresh 가 아니면(이미 열려 있던 탭) 로그인 칸을 기다리지 않고 한 번만 본다."""
    report = report or OpenReport(opened=True)
    frame = None
    if _wait_until(lambda: login_frame(page) is not None, wait, tries=20 if fresh else 1):
        frame = login_frame(page)
    if frame is None:
        report.note = ("로그인 칸이 보이지 않습니다 — 이미 로그인돼 있거나 첫 화면이 다릅니다" if fresh else
                       "이미 열려 있던 탭을 앞으로 가져왔습니다(로그인 화면이 아님)")
        return report
    marked = frame.evaluate(MARK_LOGIN_JS) or {}
    if not marked.get("ok"):
        report.note = f"로그인 칸을 알아보지 못했습니다({marked.get('why', '')}) — 직접 로그인하세요"
        _failed["why"] = report.note
        return report

    def on_dialog(dialog) -> None:
        report.messages.append((dialog.message or "").strip())
        try:
            dialog.accept()
        except Exception:  # noqa: BLE001
            pass

    page.on("dialog", on_dialog)
    report.tried_login = True
    log(f"주차등록 자동 로그인: 아이디 '{user}' (칸 {marked.get('id') or '?'} · {marked.get('pw') or '?'})")
    try:
        frame.fill(ID_SELECTOR, user)
        frame.fill(PW_SELECTOR, secret)
        frame.press(PW_SELECTOR, "Enter")
        gone = _wait_until(lambda: login_frame(page) is None, wait, tries=16)
        if not gone and not report.messages:
            # Enter 로 넘어가지 않는 화면 — '로그인' 단추를 한 번(그것도 하나일 때만)
            try:
                clicked = frame.evaluate(SUBMIT_JS) or {}
            except Exception:  # noqa: BLE001 — 넘어가는 중
                clicked = {"ok": False, "why": "화면이 바뀌는 중"}
            if clicked.get("ok"):
                log("주차등록 자동 로그인: Enter 로 넘어가지 않아 '로그인' 단추를 눌렀습니다")
                gone = _wait_until(lambda: login_frame(page) is None, wait, tries=16)
            elif login_frame(page) is not None:
                log("주차등록 자동 로그인: " + str(clicked.get("why", "")))
    except Exception as error:  # noqa: BLE001
        report.note = "자동 로그인 중 오류: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__)
        _failed["why"] = report.note
        return report
    finally:
        try:
            page.remove_listener("dialog", on_dialog)
        except Exception:  # noqa: BLE001
            pass
    failed_message = any(any(w in m for w in FAIL_WORDS) for m in report.messages)
    if gone and not failed_message:
        report.logged_in = True
        log("주차등록 자동 로그인: 로그인 화면을 넘어갔습니다")
        return report
    shown = " / ".join(m.rstrip(". ") for m in report.messages)
    report.note = ("자동 로그인이 되지 않았습니다" + (f" — 사이트 알림: {shown}" if report.messages else
                   " — 로그인 화면이 그대로입니다") + ". 아이디 · 비밀번호를 확인하고 직접 로그인하세요(앱은 다시 시도하지 않습니다)")
    _failed["why"] = report.note
    log("주차등록 " + report.note)
    return report
