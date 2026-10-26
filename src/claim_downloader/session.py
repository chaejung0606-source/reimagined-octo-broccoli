"""한 번의 받기 작업 흐름.

    준비(보관 스캔) → 브라우저 열기 → [사람: 로그인·목록 띄우기] → 목록 읽기
    → [사람: 대상 확인] → 받기 → (엑셀 지정 시) 누락 검토

사람이 끼어드는 자리는 호출부가 정한다. 명령줄은 input() 으로, 데스크톱 앱은
버튼으로 기다린다. 이 모듈은 화면을 모른다.

Playwright 동기 API 는 시작한 스레드에서만 써야 한다. 그래서 이 객체의 메서드는
전부 같은 스레드에서 불러야 한다.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from pathlib import Path
from collections.abc import Callable
from dataclasses import dataclass, field

from .claims import attach as claim_attach
from .claims import form as claim_form
from .claims import kinds as claim_kinds
from .claims import payee as claim_payee
from .claims import reattach as claim_reattach
from .claims import record as claim_record
from .claims import scholarship as claim_scholarship
from .claims import taxbill as claim_taxbill
from .claims import taxbill_run
from . import archive, diagnose, erp, logout as logout_mod, naming, navigate, progress, project_folders, purchase, settings as settings_mod, skiplist
from .reconcile import reconcile
from .targets import Selection, select_targets

# 건당 멈춤 재시도 횟수. 2026-10-12 11건 실행에서는 한 번도 필요 없었지만
# 매크로 시절에는 큰 보고서 뒤에 상세화면이 자주 멈췄다.
MAX_RETRY = 2


class ListNotFound(RuntimeError):
    """결의서내역 목록을 못 찾음. dump 에 열린 창·프레임 구조가 들어 있다."""

    def __init__(self, dump: str, message: str = ""):
        super().__init__(message or "결의서내역 목록(그리드)을 찾지 못했습니다.")
        self.dump = dump


class BrowserClosed(RuntimeError):
    pass


def _host(url: str) -> str:
    return str(url or "").split("://", 1)[-1].split("/", 1)[0].lower()


def _is_erp(page) -> bool:
    """ERP 주소(settings.ERP_URL)와 같은 곳의 창인지 — 주차등록 사이트 창과 가른다."""
    try:
        return _host(page.url) == _host(settings_mod.ERP_URL)
    except Exception:  # noqa: BLE001
        return False


def _opener(page):
    try:
        return page.opener()
    except Exception:  # noqa: BLE001 — 가짜 창 · 닫힘
        return None


def _page_state(page) -> str:
    """ERP 창이 로그인 상태인지 — 'in' · 'out' · '?'(옮겨 가는 중 등)."""
    try:
        return page.main_frame.evaluate(logout_mod.STATE_JS)
    except Exception:  # noqa: BLE001
        return "?"


def _minimize(page) -> None:
    """로그아웃하려고 다시 연 창을 작게 — 사람이 막 닫은 창이 다시 크게 뜨지 않게. 크로미움 · 엣지만 되고, 안 되면 그대로 둔다."""
    try:
        cdp = page.context.new_cdp_session(page)
        window = cdp.send("Browser.getWindowForTarget")
        cdp.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "minimized"}})
        cdp.detach()
    except Exception:  # noqa: BLE001
        pass


@dataclass
class RunSummary:
    ok: int = 0
    failed: list[dict] = field(default_factory=list)
    stopped: bool = False
    missing: list[dict] = field(default_factory=list)   # 엑셀 대조 누락
    unwanted: list[dict] = field(default_factory=list)  # 청구서출력이 없어 받지 않는 결의서 목록에 넣은 건(skiplist) — 실패가 아니다
    purchase: object = None                             # 구매요청(계약) 서류 결과(purchase.PurchaseSummary) — 그 줄이 있었을 때만


# on_item(번호, 상태, 설명) — 상태: 'running' | 'done' | 'retry' | 'failed' | 'unwanted'(받지 않는 결의서 목록에 넣음)
ItemCallback = Callable[[int, str, str], None]


def _has_own_dialog_handler(page) -> bool:
    """그 창에 앱이 붙인 dialog 처리기가 있는지(claims/payee.py · person.py · attach.py … 의 page.on("dialog") 와 저장 때의 처리기).
    Playwright 는 묶음(context)의 처리기를 먼저 부르므로, 여기서 창의 처리기를 보고 겹쳐 누르지 않는다. 공개 API 가 없어 안쪽 값을 본다 —
    못 보면 '없음' 으로 본다(그때는 hands_on 규칙대로)."""
    try:
        return bool(page._impl_obj.listeners("dialog"))
    except Exception:  # noqa: BLE001
        return False


class ErpSession:
    def __init__(self, log: Callable[[str], None],
                 ask_relogin: Callable[[str], bool],
                 should_stop: Callable[[], bool] = lambda: False,
                 process=erp.process_one,
                 load_settings: Callable[[], settings_mod.Settings] = settings_mod.load):
        self.log = log
        self.ask_relogin = ask_relogin
        self.should_stop = should_stop
        self._process = process
        self._load_settings = load_settings
        self.done: set[str] = set()
        self.archive_report: archive.ScanReport | None = None
        self._pw = None
        self._hidden = None                   # 주차 사이트 일(할인 적용 · 링크 · 내역)을 하는 보이지 않는 브라우저 — (browser, page)
        self.browser = None
        self.page = None
        # 사람이 브라우저를 쓰는 중인지(앱이 쉬거나 노란 띠 · 재로그인 띠에서 기다릴 때) — 앱의 브라우저 스레드가 바꾼다(ui/worker.py).
        # 이때 ERP 의 확인 창은 브라우저에 그대로 떠서 사람이 누른다. 아니면 전처럼 앱이 닫는다(_on_dialog). 기본은 '아니다' —
        # 콘솔 실행 · 시험 스크립트가 아무도 누르지 않는 확인 창을 기다리며 멈추지 않게.
        self.hands_on = False
        # 자동 로그아웃(logout.py, 담당자 요청 2026-10-21) — 마지막 활동 시각 · ERP 에 로그인돼 있는지 · 사람에게 남겨 둔 확인 창
        self.last_active = time.monotonic()
        self._signals: list = []
        self._logged_in = False
        self._context = None
        self._left_dialogs: list = []
        # 대응자금 과제의 예산 탭 비목 차례(과제번호 → [[비목코드, 비목명], …]) — 브라우저를 여는 동안 한 번만 읽는다
        self._budgets: dict[str, list] = {}

    # ── 준비 ─────────────────────────────────────────────────────────────
    def prepare(self) -> archive.ScanReport:
        """받은 기록을 읽고 보관 폴더를 스캔해 이미 받은 문서번호를 모은다."""
        cfg = self._load_settings()
        self.done = archive.load_done(settings_mod.done_path())
        self.log("보관 폴더 스캔 중… (처음 한 번은 1~2분 걸릴 수 있어요. 다음부터는 바로 됩니다)")
        report = archive.scan_archive(
            cfg.out_root, settings_mod.archive_cache_path(), self.done,
            progress=lambda n: self.log("   … 보관 PDF %d개 읽음" % n))
        if report.ok:
            self.log("보관 폴더 스캔: PDF %d개 중 %d개 새로 읽음 · 이미 보관된 문서번호 %d건을 건너뛰기에 추가"
                     % (report.total_pdfs, report.scanned, report.added))
            archive.save_done(settings_mod.done_path(), self.done)
        else:
            self.log(report.warning)
        if report.unreadable:
            self.log("⚠ 보관 PDF %d개를 읽지 못했습니다(%s%s) — 그 청구서는 이미 받은 것인지 몰라 다시 받을 수 있습니다. "
                     "OneDrive 에만 있는 파일이면 '이 디바이스에 항상 유지' 로 내려받은 뒤 다시 읽으세요(다음 스캔 때 다시 읽습니다)."
                     % (report.unreadable, ", ".join(report.unreadable_names), " …" if report.unreadable > len(report.unreadable_names) else ""))
        self.archive_report = report
        return report

    # ── 브라우저 ─────────────────────────────────────────────────────────
    @property
    def browser_open(self) -> bool:
        """브라우저가 살아 있고 열린 창이 하나라도 있는지. 사람이 마지막 창을 닫아도 브라우저는 연결된 채 남을 수 있어
        창까지 본다 — 안 그러면 ① 이 꺼진 채로 '열린 창이 없음' 만 되풀이했다(2026-10-14 점검)."""
        try:
            if self.browser is None or not self.browser.is_connected():
                return False
            return any(not page.is_closed() for context in self.browser.contexts for page in context.pages)
        except Exception:      # noqa: BLE001
            return False

    def poll_alive(self) -> bool:
        """쉬는 동안 — 사람이 브라우저 창을 닫았는지. Playwright 는 다른 호출을 하는 동안에만 '닫힘' 소식을 받으므로, 가벼운
        왕복 하나로 소식을 받는다(화면은 건드리지 않는다). 전에는 명령을 하나 더 보내야 알아채서, 창을 닫은 뒤에도 앱은 열린 줄 알고
        [브라우저 열기] 를 숨겼다(담당자 2026-10-20: 지출 폴더를 넣고 읽어야 브라우저를 열 수 있었다)."""
        if self.browser is None:
            return False
        try:
            page = next((p for c in self.browser.contexts for p in c.pages if not p.is_closed()), None)
            if page is not None:
                # 화면의 스크립트를 돌리지 않는 왕복(1ms 기다림)으로 소식만 받는다 — evaluate 는 ERP 확인 창이 떠 있는 동안 멈춰,
                # 사람이 그 창을 누를 때까지 이 스레드가 묶였다(_on_dialog 로 확인 창을 브라우저에 보이게 한 뒤, 2026-10-20)
                page.wait_for_timeout(1)
        except Exception:  # noqa: BLE001 — 닫히는 중이면 아래에서 닫힘으로 본다
            pass
        return self.browser_open

    def open_browser(self, start_url: str = "") -> None:
        """ERP 첫 화면을 띄운다. 로그인은 사람이 이 창에서 직접 한다. ERP 아이디·비밀번호는 어디에도 저장하지 않는다.

        start_url 을 주면(주차등록 — parking.py) 그 사이트를 첫 창으로 연다. 브라우저가 이미 열려 있는데 ERP 창이 없으면
        (주차등록만 열어 둔 채 받기 · 일반청구를 누름) ERP 를 새 탭으로 연다 — 전에는 열린 브라우저를 그대로 써 ERP 화면을 끝내 못 찾았다.
        """
        if self.browser_open:
            if not start_url and self.erp_page() is None:
                page = self._live_page().context.new_page()
                page.goto(settings_mod.ERP_URL, wait_until="domcontentloaded")
                self.page = page
                self.log("ERP 창이 없어 새 탭으로 열었습니다. 그 탭에서 로그인하세요.")
            return
        if self.browser is not None:          # 창이 모두 닫힌 채 남은 브라우저 — 새로 띄우기 전에 닫는다
            self.auto_logout("reopen")
            try:
                self.browser.close()
            except Exception:  # noqa: BLE001
                pass
            self.browser = None
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.launch(headless=False)
        except Exception as error:   # noqa: BLE001
            # 학교망에서 크로미움을 못 받은 PC 가 있다. 윈도우에 늘 있는 Edge 로 대신 띄운다.
            self.log("크로미움을 띄우지 못해 Edge 로 엽니다 (%s)" % str(error).splitlines()[0][:120])
            self.browser = self._pw.chromium.launch(headless=False, channel="msedge")
        # 묶음(context)을 따로 만든다 — browser.new_page() 의 묶음에는 앱이 새 탭을 더 열 수 없다(주차등록 · ERP 를 한 브라우저에, 2026-10-21).
        # 쿠키 · 로그인은 이 묶음의 메모리에만 있고 디스크에 남지 않는다(로그인 상태를 파일로 내보내지 않는다 — 9절)
        # no_viewport — 기본값은 화면을 1280×720 에 묶어 창을 키워도 화면이 그대로였다(담당자 2026-10-22 "처음 열린 크기에서 확장이 안 됨")
        self._context = self.browser.new_context(accept_downloads=True, no_viewport=True)
        self.erp_logged_in = False
        self._watch_activity(self._context)
        self.page = self._context.new_page()
        # 새 창(회의록등록 · 입금처 같은 팝업)도 같은 묶음(context)이라 여기 하나로 모든 창의 확인 창을 받는다
        self.page.context.on("dialog", self._on_dialog)
        self.page.goto(start_url or settings_mod.ERP_URL, wait_until="domcontentloaded")
        if start_url:
            return
        cfg = self._load_settings()
        if getattr(cfg, "auto_open_project", False):
            self.log("브라우저를 열었습니다. 로그인만 하세요 — 그 뒤 과제 %s 의 청구서(결의서내역)까지 앱이 갑니다."
                     % (getattr(cfg, "project_no", "") or settings_mod.DEFAULT_PROJECT_NO))
        else:
            self.log("브라우저를 열었습니다. 로그인 → [과제관리 → 과제정보 → 청구서] → 결의서내역 목록을 띄우세요.")

    def _on_dialog(self, dialog) -> None:
        """ERP 의 알림 · 확인 창(alert · confirm · prompt).

        Playwright 는 받는 곳이 없으면 이 창을 **보이지 않고 바로 '취소'** 한다 — 그래서 사람이 앱 브라우저에서 누른 저장이 조용히 취소됐다
        (담당자 2026-10-20: 카드청구 회의록등록 창에서 "이 브라우저에서는 저장이 안됨". 실제 Chromium 으로 확인: confirm 이 false).
        받는 곳을 두되 처리하지 않으면 보통 브라우저처럼 창이 떠서 사람이 [확인]/[취소] 를 누른다.
        - 그 창(page)에 앱의 자동화가 붙인 처리기가 있으면(저장 · 팝업 자동 선택) 거기서 처리한다 — 여기서는 손대지 않는다.
        - 사람이 쓰는 중(hands_on)이면 그대로 둔다 — 브라우저에 보인다.
        - 앱이 넣는 중인데 처리기가 없는 창이면 전처럼(Playwright 기본) 닫는다 — 그대로 두면 자동화가 사람의 클릭을 기다리며 멈춘다."""
        try:
            message = (dialog.message or "").strip()
            page = dialog.page
            if page is not None and _has_own_dialog_handler(page):
                return
            if self.hands_on:
                self.log("ERP 확인 창(브라우저에 보임 — 직접 누르세요): %s" % message[:200])
                self._left_dialogs = self._left_dialogs[-4:] + [dialog]    # 자동 로그아웃 전에 닫는다(사람이 자리를 비웠다)
                return
            self.log("ERP 알림(앱이 닫음): %s" % message[:200])
            if dialog.type == "beforeunload":
                dialog.accept()
            else:
                dialog.dismiss()
        except Exception:  # noqa: BLE001 — 사람이 이미 눌렀거나 창이 닫힌 경우
            pass

    # ── 자동 로그아웃 (logout.py) ────────────────────────────────────────
    def _watch_activity(self, context) -> None:
        """ERP 창에서 사람이 움직이면(마우스 · 키보드) 알림을 받는다 — 30분 동안 아무 일 없으면 로그아웃하려고. 알리기만 하는 스크립트라
        ERP 화면은 그대로다. 못 붙이면(가짜 브라우저 · 옛 Playwright) 앱이 하는 일만 활동으로 센다."""
        try:
            context.expose_binding(logout_mod.BINDING, self._on_erp_signal)
            context.add_init_script(logout_mod.activity_script(_host(settings_mod.ERP_URL)))
        except Exception as error:  # noqa: BLE001
            self.log("ERP 창의 활동을 볼 수 없어 앱이 하는 일만 활동으로 셉니다 (%s)" % (str(error).splitlines()[0][:120] if str(error) else type(error).__name__))

    def _on_erp_signal(self, source, value=None) -> None:
        """브라우저 쪽 알림(ACTIVITY_JS) — 'active:in' · 'load:out' 따위. 이 안에서는 Playwright 를 부르지 않는다 — 부르면 이 스레드가
        멈춘다(실제 Chromium 으로 확인: 알림 처리 중 page.opener()). 로그인 상태는 받아 두었다가 erp_logged_in 을 읽을 때 정한다."""
        kind, state = logout_mod.parse_signal(value)
        if kind == "active":
            self.touch()
        page = source.get("page") if isinstance(source, dict) else None
        if state != "?" and page is not None:
            self._signals.append((page, state))

    @property
    def erp_logged_in(self) -> bool:
        """ERP 에 로그인돼 있는지 — ERP 첫 창(팝업이 아닌 창)의 알림으로만 정한다."""
        while self._signals:
            page, state = self._signals.pop(0)
            if not _is_erp(page) or _opener(page) is not None:
                continue
            if state == "in" and not self._logged_in:
                self.touch()                                # 로그인한 때부터 센다
            self._logged_in = state == "in"
        return self._logged_in

    @erp_logged_in.setter
    def erp_logged_in(self, value: bool) -> None:
        self._signals.clear()
        self._logged_in = bool(value)

    def touch(self) -> None:
        self.last_active = time.monotonic()

    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_active

    def auto_logout_due(self) -> str:
        """지금 자동 로그아웃할 까닭 — 'idle'(설정한 분 동안 활동 없음) · 'closed'(ERP 창을 닫음) · ''(할 것 없음)."""
        if not self.erp_logged_in or self.browser is None:
            return ""
        cfg = self._load_settings()
        if not getattr(cfg, "auto_logout", True):
            return ""
        if self.erp_page() is None:
            return "closed"
        minutes = int(getattr(cfg, "auto_logout_minutes", logout_mod.DEFAULT_MINUTES) or 0)
        if minutes > 0 and self.idle_seconds() >= minutes * 60:
            return "idle"
        return ""

    def auto_logout(self, reason: str) -> bool:
        """설정이 켜져 있고 ERP 에 로그인돼 있으면 로그아웃한다(reason: 'idle' · 'closed' · 'app' · 'reopen')."""
        if not self.erp_logged_in:
            return False
        cfg = self._load_settings()
        if not getattr(cfg, "auto_logout", True):
            return False
        return self.logout(reason, int(getattr(cfg, "auto_logout_minutes", logout_mod.DEFAULT_MINUTES) or 0),
                           timeout=4.0 if reason == "app" else 8.0)        # 앱을 닫을 때는 오래 붙잡지 않는다(worker.shutdown 이 8초 기다림)

    def logout(self, reason: str, minutes: int = logout_mod.DEFAULT_MINUTES, timeout: float = 8.0) -> bool:
        """ERP 위쪽 [로그아웃](#layoutMain_btn_logout) 을 누른다. ERP 창을 닫았으면 같은 묶음에 ERP 를 잠깐 다시 열어(작게 줄여서) 누르고 닫는다 —
        쿠키는 이 묶음의 메모리에 남아 있어 닫은 창의 로그인이 그대로 살아 있다. 누른 뒤 뜨는 확인 창은 이때만 앱이 [확인] 한다."""
        why = logout_mod.reason_text(reason, minutes)
        if self.browser is None or not self.browser.is_connected():
            self.erp_logged_in = False
            self.log("⚠ %s 로그아웃하려 했지만 브라우저가 이미 닫혔습니다. 이 PC 에는 로그인이 남지 않습니다(쿠키를 저장하지 않음) — "
                     "ERP 서버 쪽 접속은 시간이 지나면 끝납니다." % why)
            return False
        for dialog in self._left_dialogs:                   # 사람에게 남겨 둔 확인 창 — 떠 있으면 화면 스크립트가 멈춘다
            try:
                dialog.dismiss()
            except Exception:  # noqa: BLE001 — 사람이 이미 눌렀다
                pass
        self._left_dialogs = []
        page, reopened = self.erp_page(), False
        try:
            if page is None:
                if self._context is None:
                    return False
                page, reopened = self._context.new_page(), True
                _minimize(page)
                page.goto(settings_mod.ERP_URL, wait_until="domcontentloaded")
            ok, note = self._press_logout(page, timeout)
        except Exception as error:  # noqa: BLE001
            ok, note = False, str(error).splitlines()[0][:120] if str(error) else type(error).__name__
        if ok or note == "이미 로그아웃됨":
            self.erp_logged_in = False
            self.log("✓ %s ERP 에서 로그아웃했습니다%s (설정 → 동작에서 끌 수 있습니다)" % (why, " — " + note if note and not ok else ""))
            self._close_erp_popups()
        else:
            # 다시 해 보지 않는다(2초마다 되풀이해 누르지 않게) — 사람이 ERP 에서 다시 움직이면(로그인 상태 알림) 그때부터 다시 센다
            self.erp_logged_in = False
            self.log("⚠ %s 로그아웃하려 했지만 하지 못했습니다: %s — ERP 위쪽 [로그아웃] 을 직접 눌러 주세요." % (why, note))
        if reopened:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass
        return ok

    def _press_logout(self, page, timeout: float) -> tuple[bool, str]:
        frames = [page.main_frame] + [f for f in page.frames if f is not page.main_frame]
        answers: list[str] = []
        moved: list[str] = []

        def on_dialog(dialog) -> None:          # 로그아웃 확인 창 — 이때만 앱이 [확인]
            try:
                answers.append((dialog.message or "").strip()[:120])
                dialog.accept()
            except Exception:  # noqa: BLE001
                pass

        def on_nav(frame) -> None:
            if frame is page.main_frame:
                moved.append(str(frame.url).split("?", 1)[0])       # 물음표 뒤(값)는 남기지 않는다

        result = "none"
        page.on("dialog", on_dialog)
        page.on("framenavigated", on_nav)
        try:
            for frame in frames:
                try:
                    result = frame.evaluate(logout_mod.CLICK_LOGOUT_JS)
                except Exception:  # noqa: BLE001 — 닫히는 프레임
                    continue
                if result != "none":
                    break
            if result != "clicked":
                state = _page_state(page)
                if state == "out":
                    return False, "이미 로그아웃됨"
                return False, {"none": "[로그아웃] 단추가 없음", "text": "[로그아웃] 글자가 다름",
                               "hidden": "[로그아웃] 단추가 보이지 않음"}.get(result, result)
            # 로그인 화면이 뜨거나, 창이 다른 주소로 옮겨 [로그아웃] 이 두 번 연달아 안 보이면 끝
            deadline, gone = time.monotonic() + timeout, 0
            while time.monotonic() < deadline:
                page.wait_for_timeout(500)
                state = _page_state(page)
                gone = gone + 1 if state == "out" or (moved and state != "in") else 0
                if state == "out" or gone >= 2:
                    break
            else:
                return False, "누른 뒤에도 로그인 화면으로 바뀌지 않음"
        finally:
            for name, handler in (("dialog", on_dialog), ("framenavigated", on_nav)):
                try:
                    page.remove_listener(name, handler)
                except Exception:  # noqa: BLE001
                    pass
        if answers:
            self.log("   로그아웃 확인 창: " + " / ".join(answers))
        if moved:
            self.log("   로그아웃 뒤 주소: " + " → ".join(dict.fromkeys(moved)))
        return True, ""

    def _close_erp_popups(self) -> None:
        """로그아웃한 뒤 남은 ERP 팝업(입금처 · 보고서 …) — 지난 화면이 그대로 보이지 않게 닫는다(ERP 단추가 아니라 창 닫기)."""
        for page in self._pages():
            if _is_erp(page) and _opener(page) is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass

    def close(self) -> None:
        self._close_hidden()
        try:
            if self.browser is not None:
                self.browser.close()
        except Exception:      # noqa: BLE001
            pass
        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:      # noqa: BLE001
            pass
        self.browser = self._pw = self.page = self._context = None
        self.erp_logged_in = False

    # ── 진단 ─────────────────────────────────────────────────────────────
    # 화면 구조 저장 업무(담당자 2026-10-21)가 고르는 사이트 — 이름 · 그 사이트의 창인지
    SITES = {"erp": "ERP", "parking": "주차등록 사이트", "kcloud": "K-Cloud"}

    def _site_finder(self):
        """창 주소 → 'erp' · 'parking' · 'kcloud' · ''. 주차 · K-Cloud 주소는 설정에서 한 번만 읽는다."""
        from . import parking
        cfg = self._load_settings()
        parking_url = getattr(cfg, "parking_url", "") or parking.DEFAULT_URL
        erp_host = _host(settings_mod.ERP_URL)
        kcloud_host = _host(getattr(cfg, "kcloud_url", "") or settings_mod.KCLOUD_URL)

        def site_of(url: str) -> str:
            host = _host(url)
            if host and host == erp_host:
                return "erp"
            if parking.is_site(url, parking_url):
                return "parking"
            if host and host == kcloud_host:
                return "kcloud"
            return ""
        return site_of

    def open_sites(self) -> dict:
        """지금 앱 브라우저에 열린 사이트 — 화면 구조 저장 업무가 '이미 열려 있음 · 로그인됨' 을 보인다. 브라우저 스레드에서만 부른다.
        창 주소는 Playwright 가 이미 아는 값이라 화면과 주고받지 않는다."""
        pages = self._pages() if self.browser is not None else []
        site_of = self._site_finder()
        sites = {site_of(p.url) for p in pages}
        erp_open = "erp" in sites
        return {"browser": bool(pages), "erp": erp_open, "erp_login": erp_open and self.erp_logged_in, "parking": "parking" in sites,
                "kcloud": "kcloud" in sites}

    def show_erp(self) -> str:
        """화면 구조 저장 업무의 [ERP 열기] — 열린 ERP 창이 있으면 앞으로 가져오기만 한다(다시 불러오지 않아 로그인 · 띄운 화면이 그대로).
        없으면 연다(브라우저가 닫혀 있으면 새로, 주차 탭만 있으면 새 탭). 로그인 뒤 과제로 가는 자동 이동은 하지 않는다 — 실측할 화면은 사람이 띄운다."""
        page = self.erp_page() if self.browser_open else None
        if page is not None:
            page.bring_to_front()
            return "이미 열린 ERP 창을 앞으로 가져왔습니다 — 다시 로그인하지 않아도 됩니다"
        if self.browser_open:
            page = self._live_page().context.new_page()
            page.goto(settings_mod.ERP_URL, wait_until="domcontentloaded")
            self.page = page
        else:
            self.open_browser(start_url=settings_mod.ERP_URL)
        self.log("화면 구조 저장: ERP 를 열었습니다 — 로그인하고 실측할 화면을 띄운 뒤 저장하세요")
        return "ERP 를 열었습니다 — 로그인하고 실측할 화면을 띄운 뒤 [화면 구조 저장] 을 누르세요"

    def show_kcloud(self) -> str:
        """화면 구조 저장 업무의 [K-Cloud 열기] — ERP 와 같다: 열린 K-Cloud 창이 있으면 앞으로 가져오기만(다시 불러오지 않아 로그인 · 띄운 화면 그대로),
        없으면 연다(브라우저가 닫혀 있으면 새로, 다른 사이트만 있으면 새 탭). 로그인은 사람이 그 창에서 직접(27절, 실측 전) — 아이디 · 비밀번호는 어디에도 두지 않는다.
        ERP 작업 창(self.page)은 바꾸지 않는다."""
        url = getattr(self._load_settings(), "kcloud_url", "") or settings_mod.KCLOUD_URL
        site_of = self._site_finder()
        page = next((p for p in self._pages() if site_of(p.url) == "kcloud"), None) if self.browser_open else None
        if page is not None:
            page.bring_to_front()
            return "이미 열린 K-Cloud 창을 앞으로 가져왔습니다 — 다시 로그인하지 않아도 됩니다"
        if self.browser_open:
            page = self._live_page().context.new_page()
            page.goto(url, wait_until="domcontentloaded")
        else:
            self.open_browser(start_url=url)
        self.log("화면 구조 저장: K-Cloud 를 열었습니다 — 로그인하고 실측할 화면을 띄운 뒤 저장하세요")
        return "K-Cloud 를 열었습니다 — 로그인하고 실측할 화면을 띄운 뒤 [화면 구조 저장] 을 누르세요"

    def capture_structure(self, site: str = "") -> Path:
        """지금 열린 화면의 창·프레임·입력 요소를 _화면구조.txt 로. 읽기만 한다(diagnose.py).
        site 를 주면('erp' · 'parking' · 'kcloud') 그 사이트의 창만 — 다른 업무가 연 창이어도 그대로 읽는다(누르거나 다시 불러오지 않는다)."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        site_of = self._site_finder()
        keep = (lambda url: site_of(url) == site) if site else None
        windows = diagnose.capture(self._live_page().context, frame_kind=erp.frame_kind, keep=keep)
        label = self.SITES.get(site, "")
        if site and not windows:
            raise BrowserClosed(f"{label} 창이 열려 있지 않습니다 — 먼저 {label} 를 열고 실측할 화면을 띄우세요.")
        path = settings_mod.structure_path()
        report = diagnose.format_report(windows, target=label)
        path.write_text(report, encoding="utf-8")
        number = diagnose.append_to_book(settings_mod.structure_book_path(), report)
        count = sum(len(fr.get("elements", [])) for win in windows for fr in win["frames"])
        self.log("화면 구조 저장%s: 창 %d · 요소 %d개 → %s (모음 %d번째)" % (f"({label})" if label else "", len(windows), count, path, number))
        return path

    # ── 로그인 뒤 청구서 화면까지 (navigate.py) ────────────────────────────
    def read_projects(self) -> list:
        """메인화면 과제현황의 과제들 — 로그인 전이면 빈 목록. 읽기만 한다."""
        if not self.browser_open:
            return []
        return navigate.read_projects(self.page.context)

    def go_to_claims(self, project_no: str) -> tuple[bool, str]:
        """고른 과제의 과제정보 → 청구서 탭 → 결의서내역 목록까지. 누르는 것은 과제명 링크와 '청구서' 탭뿐."""
        if not self.browser_open:
            return False, "브라우저가 닫혀 있습니다"
        ok, message = navigate.go_to_claims(self.page.context, project_no, self.log, self._wait)
        self.log(("✓ " if ok else "⚠ ") + message)
        return ok, message

    def _wait(self, seconds: float) -> None:
        self._live_page().wait_for_timeout(int(seconds * 1000))

    def _pages(self) -> list:
        if self.browser is None:
            return []
        try:
            return [p for c in self.browser.contexts for p in c.pages if not p.is_closed()]
        except Exception:  # noqa: BLE001 — 닫히는 중
            return []

    def _live_page(self):
        """작업 창(self.page)이 닫혔으면(주차등록 탭을 닫음 등) 열린 다른 창 — 기다리기 · 새 탭 열기에 쓴다."""
        try:
            if self.page is not None and not self.page.is_closed():
                return self.page
        except Exception:  # noqa: BLE001
            pass
        pages = self._pages()
        if pages:
            self.page = next((p for p in pages if _is_erp(p)), pages[0])
        return self.page

    def erp_page(self):
        """ERP 첫 창(팝업이 아닌 창). 없으면 None — 주차등록 사이트만 열려 있을 수 있다."""
        return next((p for p in self._pages() if _is_erp(p) and _opener(p) is None), None)

    # ── 주차등록 (parking.py) ──────────────────────────────────────────────
    def open_parking(self, url: str = "", login: tuple[str, str] | None = None, path: str = ""):
        """주차등록 사이트를 앱 브라우저에서 연다(열려 있으면 그 탭을 앞으로, 없으면 새 탭). login 이 있고 로그인 화면이면 한 번만 자동 로그인.
        path 를 주면(예: 할인 링크 목록 — 사람이 [QR 보기] 를 누르게) 그 화면으로 옮겨 간다. 누르지는 않는다.
        ERP 창(self.page)은 그대로 둔다 — ERP 일과 섞이지 않게."""
        report = self._open_parking(url, login)
        if path and report.opened:
            page, base, _ = self._parking_tab(url, None, report)
            try:
                if page is not None and not page.url.split("?", 1)[0].endswith(path):
                    page.goto(base + path, wait_until="domcontentloaded")
                    page.bring_to_front()
            except Exception as error:  # noqa: BLE001
                report.note = path + " 화면을 열지 못했습니다: " + (str(error).splitlines()[0][:120] if str(error) else type(error).__name__)
        return report

    def _open_parking(self, url: str = "", login: tuple[str, str] | None = None):
        from . import parking
        url = url or parking.DEFAULT_URL
        report = parking.OpenReport()
        fresh = True
        try:
            if not self.browser_open:
                self.open_browser(start_url=url)
                page = self.page
                report.new_tab = False
            else:
                page = next((p for p in self._pages() if parking.is_site(p.url, url)), None)
                if page is None:
                    page = self._live_page().context.new_page()
                    page.goto(url, wait_until="domcontentloaded")
                    report.new_tab = True
                else:
                    fresh = False                         # 이미 열린 탭 — 로그인돼 있으면 로그인 칸을 기다리지 않는다
                page.bring_to_front()
        except Exception as error:  # noqa: BLE001
            report.note = str(error).splitlines()[0][:120] if str(error) else type(error).__name__
            self.log("주차등록 사이트를 열지 못했습니다: " + report.note)
            return report
        report.opened = True
        self.log("주차등록 사이트를 열었습니다: " + url)
        if not login:
            report.note = "자동 로그인 정보가 없어 직접 로그인하세요(설정 → '주차등록 로그인 정보' 에 넣으면 다음부터 앱이 합니다)"
            return report
        if parking.failed_before():
            report.note = "앞서 자동 로그인이 되지 않아 다시 시도하지 않습니다 — 로그인 정보를 고쳐 저장하면 다시 합니다"
            return report
        was, self.hands_on = self.hands_on, False       # 로그인하는 동안 사이트 알림은 앱이 받는다(parking.login 의 처리기)
        try:
            return parking.login(page, login[0], login[1], self.log,
                                 wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)), report=report, fresh=fresh)
        finally:
            self.hands_on = was

    def _parking_tab(self, url: str, login: tuple[str, str] | None, opened=None):
        """사이트를 열고(로그인 정보가 있으면 한 번 자동 로그인 — 이미 열었으면 opened) 그 탭 · 주소 앞부분(포트까지) · 못 열었을 때의 까닭."""
        from . import parking
        url = url or parking.DEFAULT_URL
        opened = opened or self._open_parking(url, login)
        page = next((p for p in self._pages() if parking.is_site(p.url, url)), None)
        if not opened.opened or page is None:
            return None, "", opened.note or "주차 사이트를 열지 못했습니다"
        scheme, _, rest = url.partition("://")
        return page, scheme + "://" + rest.split("/", 1)[0], ""

    def _on_parking_tab(self, url: str, login, work):
        """보이는 브라우저의 주차 사이트 탭에서 work(page, base, wait) 를 돌린다 — [목록 · QR 보기] 처럼 사람이 볼 화면만."""
        page, base, note = self._parking_tab(url, login)
        if page is None:
            return None, note
        was, self.hands_on = self.hands_on, False
        try:
            result = work(page, base, lambda s: page.wait_for_timeout(int(s * 1000)))
        finally:
            self.hands_on = was
        for line in result.lines():
            self.log(line)
        try:
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass
        return result, ""

    # ── 주차등록 — 창 없이(보이지 않는 브라우저) ──────────────────────────
    # 담당자 2026-10-21: "할인적용과 할인링크 만들기는 브라우저 열기가 아니기 때문에 브라우저가 열리지 않은 상태에서 이루어져야 함".
    # 그래서 할인 적용 · 할인 링크 만들기 · 할인 내역 읽기는 화면에 뜨지 않는 브라우저를 따로 띄워 한다. 로그인은 설정의 주차등록 로그인 정보로
    # 앱이 한다(9절의 예외 — 주차 사이트만). 쿠키는 그 브라우저의 메모리에만 있고 앱을 닫으면 사라진다. ERP 는 이 브라우저에 열지 않는다.
    # 사람이 직접 볼 때([브라우저에서 사이트 열기] · [목록 · QR 보기])만 보이는 브라우저를 쓴다.
    NO_PARKING_LOGIN = ("설정 → '주차등록 로그인 정보' 에 아이디 · 비밀번호를 넣어 주세요 — 할인 적용 · 링크 만들기 · 할인 내역은 "
                        "브라우저 창 없이 앱이 로그인해서 합니다")

    def _hidden_alive(self) -> bool:
        try:
            return self._hidden is not None and self._hidden[0].is_connected() and not self._hidden[1].is_closed()
        except Exception:  # noqa: BLE001
            return False

    def _close_hidden(self) -> None:
        hidden, self._hidden = self._hidden, None
        if hidden is not None:
            try:
                hidden[0].close()
            except Exception:  # noqa: BLE001 — 이미 닫힘
                pass

    def _hidden_parking_page(self, url: str, login: tuple[str, str] | None):
        """창 없이 주차 사이트에 로그인한 창. 처음이면 보이지 않는 브라우저를 띄우고 로그인한다. 못 하면 (None, 까닭)."""
        from . import parking
        if self._hidden_alive():
            return self._hidden[1], ""
        self._close_hidden()
        if not login:
            return None, self.NO_PARKING_LOGIN
        if parking.failed_before():
            return None, "앞서 자동 로그인이 되지 않아 다시 시도하지 않습니다 — 설정에서 로그인 정보를 고쳐 저장하면 다시 합니다"
        from playwright.sync_api import sync_playwright

        if self._pw is None:
            self._pw = sync_playwright().start()
        try:
            browser = self._pw.chromium.launch(headless=True)
        except Exception as error:   # noqa: BLE001 — 크로미움을 못 받은 PC(open_browser 와 같은 까닭)
            self.log("크로미움을 띄우지 못해 Edge 로 엽니다 (%s)" % str(error).splitlines()[0][:120])
            browser = self._pw.chromium.launch(headless=True, channel="msedge")
        try:
            page = browser.new_context().new_page()
            page.goto(url, wait_until="domcontentloaded")
            report = parking.login(page, login[0], login[1], self.log, wait=lambda s: page.wait_for_timeout(int(s * 1000)))
        except Exception as error:  # noqa: BLE001
            browser.close()
            return None, "주차 사이트에 닿지 못했습니다: " + (str(error).splitlines()[0][:120] if str(error) else type(error).__name__)
        if not report.logged_in and parking.login_frame(page) is not None:
            browser.close()
            return None, report.note or "주차 사이트에 로그인하지 못했습니다"
        self._hidden = (browser, page)
        self.log("주차 사이트에 창 없이 로그인했습니다")
        return page, ""

    def _on_parking_hidden(self, url: str, login, work, empty):
        """보이지 않는 브라우저에서 work(page, base, wait). 사이트 접속이 끝나 로그인 화면으로 돌아갔으면 한 번만 다시 로그인하고 다시 한다.
        못 하면 empty(까닭) — 각 일의 보고 꼴."""
        from . import parking
        url = url or parking.DEFAULT_URL
        scheme, _, rest = url.partition("://")
        base = scheme + "://" + rest.split("/", 1)[0]
        result = None
        for again in (False, True):
            page, note = self._hidden_parking_page(url, login)
            if page is None:
                result = empty(note)
                break
            result = work(page, base, lambda s, page=page: page.wait_for_timeout(int(s * 1000)))
            if again or parking.login_frame(page) is None:
                break
            self.log("주차 사이트 접속이 끝나 다시 로그인합니다")
            self._close_hidden()
        for line in result.lines():
            self.log(line)
        return result

    def save_parking_screen(self, why: str, car: str = "") -> str:
        """창 없이 하던 일이 멈춘 화면의 모양을 _화면구조.txt · _화면구조_모음.txt 에 — 실측 전 화면이라 그 파일로 고친다.
        차량번호는 가린다(parking_screens.mask_cars). 남긴 파일 이름(못 남겼으면 '')."""
        from . import parking_screens
        if not self._hidden_alive():
            return ""
        try:
            windows = diagnose.capture(self._hidden[1].context)
            report = diagnose.format_report(windows, target="주차등록 사이트 · 앱이 창 없이 하다 멈춘 화면")
            report = report.replace("읽기만 했습니다. 아무것도 누르거나 넣지 않았습니다.",
                                    "앱이 멈춘 그대로 읽었습니다(멈춘 까닭: %s)." % parking_screens.mask_cars(why), 1)
            number = re.sub(r"\s+", "", car or "")
            if number:
                report = report.replace(number, "(차량번호)")
            report = parking_screens.mask_cars(report)
            path = settings_mod.structure_path()
            path.write_text(report, encoding="utf-8")
            diagnose.append_to_book(settings_mod.structure_book_path(), report)
        except Exception as error:  # noqa: BLE001 — 남기지 못해도 하던 일의 결과는 그대로 알린다
            self.log("멈춘 화면을 남기지 못했습니다: " + (str(error).splitlines()[0][:100] if str(error) else type(error).__name__))
            return ""
        self.log("멈춘 화면의 모양을 남겼습니다 → " + settings_mod.structure_book_path().name)
        return settings_mod.structure_book_path().name

    def register_parking_link(self, request, url: str = "", login: tuple[str, str] | None = None):
        """주차등록 — 할인 링크 화면의 [새 링크] 창에 넣고 [저장] 까지(parking_link.py). 창 없이."""
        from . import parking_link
        return self._on_parking_hidden(url, login, lambda page, base, wait: parking_link.create(
            page, request, self.log, wait=wait, base_url=base), lambda note: parking_link.LinkReport(note=note))

    def apply_parking_discount(self, car: str, url: str = "", login: tuple[str, str] | None = None):
        """주차등록 — 할인 적용: 차량번호 → 보유 할인권 '공무확인증' → 할인 선택 '공무확인증' → [종료](parking_screens.py). 창 없이.
        멈추면 그 화면의 모양을 남긴다(실측 전이라)."""
        from . import parking_screens
        result = self._on_parking_hidden(url, login, lambda page, base, wait: parking_screens.apply_discount(
            page, car, self.log, wait=wait, base_url=base), lambda note: parking_screens.ApplyReport(note=note))
        if result.capture:
            result.saved = self.save_parking_screen(result.note, car)
        return result

    def read_parking_history(self, url: str = "", login: tuple[str, str] | None = None):
        """주차등록 — 운영 → 할인 내역 화면의 표를 읽기만 한다(parking_screens.py) + 보유 잔량([새 링크] 창의 상품 보기, parking_link.read_products).
        창 없이. 표가 없으면 그 화면의 모양을 남긴다."""
        from . import parking_ledger, parking_link, parking_screens

        since = parking_ledger.history_since()          # 올해 1월 1일(또는 대장의 가장 이른 일자)부터 — 모든 쪽(담당자 2026-10-22)

        def work(page, base, wait):
            report = parking_screens.read_history(page, self.log, wait=wait, base_url=base, since=since)
            if report.ok:
                report.products = parking_link.read_products(page, self.log, wait=wait, base_url=base).products
                # 잔량은 표 다음에 읽는다 — 이 때 앞의 사용은 모두 표에 있다(쌓인 잔량 기록과 견줄 때, parking_ledger.drain_study)
                report.read_stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return report

        result = self._on_parking_hidden(url, login, work, lambda note: parking_screens.HistoryReport(note=note))
        if not result.ok and "표가 없습니다" in result.note:
            self.save_parking_screen(result.note)
        return result

    def _project(self, project_no: str = "") -> str:
        """폴더에 붙은 과제(일반청구 화면에서 고름) — 없으면 마지막으로 고른 과제, 그것도 없으면 담당자가 정한 기본 과제."""
        cfg = self._load_settings()
        return re.sub(r"\D", "", project_no or getattr(cfg, "project_no", "") or settings_mod.DEFAULT_PROJECT_NO)

    def _duplicate_check(self, summary: str, project: str, ask, test_mode: bool, fallback=None) -> str:
        """넣기 전 — 그 과제의 ERP 결의서내역에 대표적요가 같은 청구서가 있으면 묻는다. 멈추면 그 까닭, 이어 가면 ''.

        담당자 요청(2026-10-19): 앱에 넣은 이력보다 실제 ERP 내역에 같은 것이 있는지가 먼저다 — ERP 에서 지운 청구서를 앱 이력 때문에
        다시 넣지 못하게 막던 창을 걷어냈다. 결의서내역을 못 읽을 때만 앱 이력(fallback() 의 글)으로 묻는다. 시험이면 묻지 않는다."""
        if test_mode:
            self.log("시험 — ERP 결의서내역 중복 확인을 건너뜁니다 (대표적요 앞에 [시험])")
            return ""
        move = bool(getattr(self._load_settings(), "auto_new_sheet", True))     # 새 청구서를 앱이 띄울 때만 화면을 옮겨 읽는다
        rows, total, why = navigate.existing_claims(self.page.context, project, summary, self.log, self._wait, move=move)
        if rows is None:
            self.log("ERP 결의서내역을 읽지 못해 앱 기록으로 봅니다: " + why)
            warning = fallback() if fallback else ""
            if warning and not ask("ERP 결의서내역을 읽지 못해 앱 기록으로 봅니다(%s).\n%s\n그래도 넣으려면 [계속], 아니면 [멈추기]."
                                   % (why, warning)):
                return "앱 기록에 넣은 이력이 있어 멈춤"
            return ""
        if not rows:
            self.log("✓ ERP 결의서내역(과제 %s, %d건)에 대표적요가 같은 청구서 없음" % (project, total))
            return ""
        found = ", ".join("결의번호 %s(%s%s)" % (r.get("seq") or "?", r.get("state") or "진행구분 모름",
                                                f" · {int(r['amt']):,}원" if str(r.get("amt", "")).lstrip("-").isdigit() else "")
                          for r in rows[:5]) + (" 외" if len(rows) > 5 else "")
        self.log("ERP 결의서내역에 대표적요가 같은 청구서가 있습니다: " + found)
        # 보완요청 · 임시저장 청구서가 있으면 첨부만 다시 올리는 길을 띠에서 바로 — 담당자 2026-10-23 "보완요청 와서 첨부문서 수정해야 한다고 … 그냥 장학금
        # 청구하는 것처럼 파일만 다시 올려달라고"(이 띠에서 [ERP 에서 지운 뒤 다시] 를 읽고 막혔다). 글에 REATTACH_CHOICE 가 들면 화면이 그 단추를 보인다.
        editable = any(any(w in str(r.get("state") or "") for w in claim_reattach.STATE_WORDS) for r in rows)
        hint = (f"첨부문서만 바꾸려는 것이면(보완요청 · 임시저장) {claim_reattach.REATTACH_CHOICE} — 값은 넣지 않고 청구내역 줄마다 첨부를 모두 지운 뒤 "
                "폴더의 지금 파일을 올려 [저장] 합니다.\n") if editable else ""
        if not ask(f"ERP 결의서내역에 대표적요 '{summary}' 청구서가 이미 있습니다 — {found}.\n" + hint
                   + "새 청구서로 또 넣으면 같은 지출이 두 번 청구됩니다. 다시 넣는 것이면 ERP 에서 그 청구서를 지운 뒤 다시 누르고, 이미 올린 폴더로 "
                   "시험하는 것이면 아래 [시험] 을 켜고 다시 누르세요.\n그래도 새 청구서에 넣으려면 [계속], 아니면 [멈추기]."):
            return "ERP 결의서내역에 대표적요가 같은 청구서가 있어 멈춤"
        return ""

    def _fresh_sheet(self, page, frame, project: str):
        """이 과제의 새 작성 화면을 결의서 목록의 [일반청구] 로 띄워 앞에 둔다(설정 auto_new_sheet, 담당자 허락 2026-10-19).
        저장된 청구서 · 다른 과제의 청구서 · (결의서내역을 읽느라 뒤로 간) 빈 새 청구서를 새 것으로 바꾼다. 입력이 남은 화면은 바꾸지 않는다.
        끄면 · 못 띄우면 받은 그대로 돌려준다(사람이 띄운 화면을 쓴다)."""
        cfg = self._load_settings()
        if not getattr(cfg, "auto_new_sheet", True):
            return page, frame
        if navigate.list_frame(self.page.context, project) is None:
            self.go_to_claims(project)
        opened, note, _fresh = navigate.open_new_sheet(self.page.context, self.log, self._wait, project, replace_empty=True)
        if not opened:
            self.log("새 청구서를 앱이 띄우지 못함: " + note)
            return page, frame
        return claim_form.wait_for_form(self.page.context, log=self.log)

    def _typed_sheet(self, frame) -> list[str]:
        """사람이 입력하다 만 저장 전 작성 화면이면 그 칸들 — 앱이 새 청구서로 바꾸면 날아가므로 손대지 않는다."""
        if frame is None:
            return []
        state = navigate._sheet_state(frame)
        if state.get("REQ_CNT") or state.get("APPR_DIV_CD") == "40":
            return []
        return navigate.typed_fields(state)

    # ── 일반청구 ─────────────────────────────────────────────────────────
    def claim_form_open(self) -> bool:
        """지금 브라우저에 일반청구 작성 화면이 떠 있는지."""
        if not self.browser_open:
            return False
        _page, frame = claim_form.find_form(self.page.context)
        return frame is not None

    def fill_claim(self, data: dict, dry_run: bool = True, project_no: str = "", folder: str = "", test_mode: bool = False,
                   ask=None) -> claim_form.FillReport:
        """일반청구 작성 화면에 값을 채운다(claims/form.py). 저장·신청은 사람이.
        실제로 넣을 때는 먼저 그 과제의 ERP 결의서내역에서 적요가 같은 청구서를 찾고(_duplicate_check), 결의서 목록의 [일반청구] 로
        새 청구서를 띄워 넣는다(_fresh_sheet). 시험이면 적요 앞에 [시험] 을 붙이고 중복 확인을 건너뛴다."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        if test_mode and not str(data.get("summary", "")).startswith(claim_scholarship.TEST_PREFIX.strip()):
            data = dict(data, summary=claim_scholarship.TEST_PREFIX + str(data.get("summary", "")))
        page, frame = claim_form.wait_for_form(self.page.context, log=self.log)
        if not dry_run:
            typed = self._typed_sheet(frame)
            if typed:
                report = claim_form.FillReport(dry_run=dry_run)
                report.blocked = (f"작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있습니다 — 그 청구서를 [저장] 하거나 비운 뒤 다시 누르세요. "
                                  "앱은 그 화면을 바꾸지 않습니다.")
                self.log(report.blocked)
                return report
            project = self._project(project_no)

            def history() -> str:
                from .claims import record
                before = record.previous(folder) if folder else None
                return (f"이 폴더는 {before.get('when')} 에 적요 '{before.get('summary')}' 로 넣은 적이 있습니다."
                        if before else "")

            stop = self._duplicate_check(str(data.get("summary", "")), project, ask or (lambda _m: False), test_mode, history)
            if stop:
                report = claim_form.FillReport(dry_run=dry_run)
                report.blocked = stop
                return report
            page, frame = self._fresh_sheet(page, frame, project)
        if frame is None:
            report = claim_form.FillReport(dry_run=dry_run)
            report.blocked = ("일반청구 작성 화면을 찾지 못했습니다. 앱이 연 브라우저에서 결의서내역 → [일반청구] 를 눌러 "
                              "새 청구서 화면을 띄운 뒤 다시 누르세요.")
            self.log(report.blocked)
            return report
        wait = lambda seconds: page.wait_for_timeout(int(seconds * 1000))  # noqa: E731
        report = claim_form.fill(frame, data, self.log, dry_run=dry_run, wait=wait)
        if dry_run or report.blocked:
            return report
        # 칸을 다 넣었으면 팝업을 차례로 — 고르기·[확인] 은 사람(1차). 세금계산서 팝업을 사람이 닫을 때까지(최대 3분)
        # 기다렸다가 입금처 팝업을 연다. 두 팝업을 한꺼번에 띄우면 어느 쪽부터 할지 헷갈리고, 같은 창 이름이면 서로 덮는다.
        auto_pick, email = self._popup_options()
        if claim_taxbill.wanted(data) and (claim_taxbill.query_for(data) or email):
            report.taxbill = claim_taxbill.search(page, frame, data, self.log, wait=wait, auto_pick=auto_pick, email=email)
            if report.taxbill.ok and not report.taxbill.picked:
                popup = claim_payee.find_popup(page.context, claim_taxbill.POPUP_PROBE_JS)
                was, self.hands_on = self.hands_on, True     # 사람이 팝업에서 고르는 동안 — ERP 확인 창이 브라우저에 보여야 한다
                try:
                    closed = popup is None or claim_payee.wait_closed(popup, wait)
                finally:
                    self.hands_on = was
                if not closed:
                    self.log("세금계산서 팝업이 아직 열려 있어 입금처 검색은 건너뜁니다 — 고른 뒤 [입금처 찾기] 를 누르세요")
                    return report
        if claim_payee.query_for(data):
            report.payee = claim_payee.search(page, frame, data, self.log, wait=wait, auto_pick=auto_pick)
        return report

    def search_taxbill(self, data: dict) -> claim_taxbill.TaxbillReport:
        """세금계산서 조회 팝업만 다시 — [선택] 을 눌러 열고 사업자번호로 조회한다(claims/taxbill.py). 고르기·[확인] 은 사람."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        page, frame = claim_form.wait_for_form(self.page.context, log=self.log)
        if frame is None:
            report = claim_taxbill.TaxbillReport(ok=False, note="일반청구 작성 화면을 찾지 못했습니다")
            self.log(report.note)
            return report
        auto_pick, email = self._popup_options()
        return claim_taxbill.search(page, frame, data, self.log, wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)),
                                    auto_pick=auto_pick, email=email)

    def search_payee(self, data: dict) -> claim_payee.PayeeReport:
        """입금처 팝업만 다시 — 돋보기를 눌러 열고 거래처를 검색한다(claims/payee.py). 고르기·[확인] 은 사람."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        page, frame = claim_form.wait_for_form(self.page.context, log=self.log)
        if frame is None:
            report = claim_payee.PayeeReport(ok=False, note="일반청구 작성 화면을 찾지 못했습니다")
            self.log(report.note)
            return report
        return claim_payee.search(page, frame, data, self.log, wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)),
                                  auto_pick=self._popup_options()[0])

    # ── 세금계산서 청구 이어 넣기 ───────────────────────────────────────
    def fill_taxbill_claims(self, items: list[taxbill_run.TaxbillItem], dry_run: bool = True, test_mode: bool = False,
                            ask=None, on_item=None) -> taxbill_run.TaxbillRunReport:
        """청구 종류 '세금계산서' 폴더들을 하나씩 — 새 청구서 → 비목 · 증빙(세금계산서) → 조회 팝업(승인번호 → 사업자번호 + 수신메일) →
        뜨면 골라 [확인] → 나머지 칸 → (사람) 청구종류 · 증빙 창 → 입금처 → 첨부 → [저장] → 다음 폴더. 조회 결과가 없으면 그 폴더는
        '세금계산서 없음' 으로 건너뛰고 다음 폴더로(담당자 2026-10-22). [신청] 은 누르지 않는다.

        ask(글) 은 노란 띠 — True 면 [계속], False 면 [멈추기](남은 폴더는 두고 끝). on_item(row, status, note) 은 폴더마다 화면에."""
        ask = ask or (lambda _m: False)
        on_item = on_item or (lambda _r, _s, _n: None)
        if dry_run:
            return taxbill_run.plan(items)
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        report = taxbill_run.TaxbillRunReport(dry_run=False)
        self.log("세금계산서 청구 시작: %d개 폴더%s" % (len(items), " (시험)" if test_mode else ""))
        for item in items:
            if self.should_stop():
                report.stopped = True
                break
            on_item(item.row, "erp", "")
            result = self._fill_taxbill_item(item, test_mode, ask)
            report.results.append(result)
            on_item(item.row, result.status, result.note)
            self.log("%s: %s%s" % (item.name, result.label, (" — " + result.note) if result.note else ""))
            if result.status in ("stopped", "failed") and result.note.startswith(("브라우저", "작성 화면")):
                report.blocked = result.note
                report.stopped = True
                break
            if result.status == "stopped":
                report.stopped = True
                break
        done = {r.row for r in report.results}
        for item in items:
            if item.row not in done:
                on_item(item.row, "waiting", "")
        return report

    def _fill_taxbill_item(self, item: taxbill_run.TaxbillItem, test_mode: bool, ask) -> taxbill_run.ItemResult:
        result = taxbill_run.ItemResult(item.row, item.name, "failed")
        data = dict(item.data, evidence=claim_taxbill.EVIDENCE_TAXBILL)
        if test_mode and not str(data.get("summary", "")).startswith(claim_scholarship.TEST_PREFIX.strip()):
            data["summary"] = claim_scholarship.TEST_PREFIX + str(data.get("summary", ""))
        wait = self._wait
        page, frame = claim_form.wait_for_form(self.page.context, log=self.log)
        typed = self._typed_sheet(frame)
        if typed:
            result.note = (f"작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있습니다 — 그 청구서를 [저장] 하거나 비운 뒤 다시 누르세요. "
                           "앱은 그 화면을 바꾸지 않습니다.")
            result.status = "stopped"
            return result
        project = self._project(item.project_no)
        stop = self._duplicate_check(str(data.get("summary", "")), project, ask, test_mode,
                                     lambda: (f"이 폴더는 {claim_record.previous(item.folder).get('when')} 에 넣은 적이 있습니다."
                                              if claim_record.previous(item.folder) else ""))
        if stop:
            result.status, result.note = "stopped", stop
            return result
        page, frame = self._fresh_sheet(page, frame, project)
        if frame is None:
            result.status = "stopped"
            result.note = "작성 화면을 찾지 못했습니다. 앱이 연 브라우저에서 결의서내역 → [일반청구] 를 눌러 새 청구서 화면을 띄운 뒤 다시 누르세요."
            return result
        # ① 비목 · 세목 · 증빙구분(세금계산서) — [선택] 이 보이게 된다
        head = claim_form.fill(frame, data, self.log, dry_run=False, wait=wait, keys=("expCategory", "expDetail", "evidence"))
        if head.blocked:
            result.status, result.note = "stopped", head.blocked
            return result
        result.detail += [f"{'✓' if st.ok else '✗'} {st.label}: {st.value}" + (f" — {st.note}" if st.note else "") for st in head.steps]
        # ② 세금계산서 조회 — 승인번호 → 사업자번호(+ 수신메일). 없으면 이 폴더는 건너뛴다
        auto_pick, email = self._popup_options()
        tb = claim_taxbill.search(page, frame, data, self.log, wait=wait, auto_pick=auto_pick, email=email)
        result.detail += tb.lines()
        if not tb.ok:
            result.note = "세금계산서 팝업: " + (tb.note or "열지 못함")
            return result
        if tb.missing:
            self._close_popup(page, claim_taxbill.POPUP_PROBE_JS)
            result.status = "missing"
            result.note = f"'{tb.query}' 로 조회했지만 결과가 없음 — 본부가 아직 등록하지 않았을 수 있습니다. 등록된 뒤 다시 넣으세요"
            return result
        if not tb.picked:
            ok, why = self._ask_until(lambda: self._taxbill_attached(page, frame), ask, taxbill_run.TAXBILL_ASK + (f" ({tb.pick_note})" if tb.pick_note else ""))
            if not ok:
                result.status, result.note = "stopped", "세금계산서를 고르지 않음 — " + why
                return result
            result.detail.append("✓ 세금계산서: 사람이 골라 [확인]")
        # ③ 나머지 칸 — 지출일자는 계산서가 채웠고, 금액 · 적요 · 결제방법 · 계좌
        rest = claim_form.fill(frame, data, self.log, dry_run=False, wait=wait,
                               keys=tuple(k for k, *_ in claim_form.FIELDS if k not in ("expCategory", "expDetail", "evidence")))
        result.detail += [f"{'✓' if st.ok else '✗'} {st.label}: {st.value}" + (f" — {st.note}" if st.note else "") for st in rest.steps]
        if rest.blocked:
            result.status, result.note = "stopped", rest.blocked
            return result
        for st in rest.steps:
            if not st.ok:
                result.review.append(f"{st.label} 을 넣지 못함({st.note}) — ERP 에서 확인")
        # ④ 청구종류 · 증빙 창 — 사람(미실측). 증빙이 붙었는지(#REQ_DIV_LNK)만 본다
        div = str(data.get("claimDiv") or "물품구매 · 용역구매 등")
        if not ask(taxbill_run.EVIDENCE_ASK.format(div=div)):
            result.status, result.note = "stopped", "청구종류 · 증빙 창에서 멈춤"
            return result
        if not self._evidence_link(frame):
            result.review.append("청구종류의 증빙(#REQ_DIV_LNK)이 붙지 않음 — [신청] 전에 증빙 창을 확인")
        # ⑤ 입금처 — 거래처 팝업. 확실하면 앱이, 아니면 사람
        if claim_payee.query_for(data):
            pr = claim_payee.search(page, frame, data, self.log, wait=wait, auto_pick=auto_pick)
            result.detail += pr.lines()
            picked = bool(pr.ok and pr.picked)
        else:
            picked = False
        if not picked:
            ok, why = self._ask_until(lambda: self._payee_filled(frame), ask, taxbill_run.PAYEE_ASK)
            if not ok:
                result.status, result.note = "stopped", "입금처를 고르지 않음 — " + why
                return result
        # ⑥ 첨부 — AI 가 고른 폴더 파일. 없거나 못 올리면 사람
        files = item.attachments()
        if files:
            messages: list[str] = []
            at = claim_attach.upload(page, frame, files, self.log, wait=wait, messages=messages)
            result.detail += at.lines()
            if not at.ok and not ask(taxbill_run.ATTACH_ASK + (f" ({at.note})" if at.note else "")):
                result.status, result.note = "stopped", "첨부에서 멈춤"
                return result
        else:
            result.review.append("첨부할 파일을 폴더에서 찾지 못해 올리지 않음 — [신청] 전에 첨부")
        # ⑦ [저장](임시저장) — [신청] 은 사람
        sr = self.save_claim_draft()
        result.detail += sr.lines()
        if not sr.ok:
            result.status = "stopped"
            result.note = "임시저장이 안 됨 — " + (sr.note or " · ".join(sr.messages) or "ERP 에서 [저장] 을 직접 누른 뒤 다음 폴더를 다시 넣으세요")
            return result
        result.status = "saved"
        result.req_cnt = str((sr.after or {}).get("REQ_CNT") or "")
        if not test_mode:
            try:
                claim_record.remember(item.folder, data, kind=claim_kinds.TAXBILL)
            except Exception as error:  # noqa: BLE001 — 기록을 못 남겨도 저장은 됐다
                self.log("채운 기록을 남기지 못했습니다: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
        return result

    def _ask_until(self, check, ask, message: str, tries: int = 3) -> tuple[bool, str]:
        """노란 띠로 묻고 [계속] 뒤 check() 가 참이면 이어 간다. 세 번까지."""
        for _ in range(tries):
            if not ask(message):
                return False, "멈춤"
            if check():
                return True, ""
            message = "아직 되지 않았습니다. " + message
        return False, "세 번 물어도 되지 않음"

    def _taxbill_attached(self, page, frame) -> bool:
        """작성 화면에 계산서가 붙었는지(#TAXBILL_SEQ_NO) — 사람이 팝업에서 고른 뒤."""
        try:
            state = claim_form.read_state(frame, ["TAXBILL_SEQ_NO"])
            if (state.get("TAXBILL_SEQ_NO") or {}).get("value"):
                return True
        except Exception:  # noqa: BLE001
            pass
        popup = claim_payee.find_popup(page.context, claim_taxbill.POPUP_PROBE_JS)
        return popup is None and self._taxbill_date_set(frame)

    @staticmethod
    def _taxbill_date_set(frame) -> bool:
        try:
            return bool((claim_form.read_state(frame, ["EXP_DT"]).get("EXP_DT") or {}).get("value"))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _payee_filled(frame) -> bool:
        try:
            return bool((claim_form.read_state(frame, ["RCV_NM"]).get("RCV_NM") or {}).get("value"))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _evidence_link(frame) -> bool:
        from .claims import card_erp
        return bool(card_erp._link(frame, "REQ_DIV_LNK"))

    def _close_popup(self, page, probe_js: str) -> None:
        """앱이 연 팝업 창을 닫는다(창 닫기 — ERP 단추가 아니다). 세금계산서가 없을 때 다음 폴더로 가기 전에."""
        popup = claim_payee.find_popup(page.context, probe_js)
        if popup is None:
            return
        try:
            popup.close()
        except Exception:  # noqa: BLE001
            pass

    def _popup_options(self) -> tuple[bool, str]:
        """팝업 설정 — (결과가 확실하면 앱이 고르나, 세금계산서 조회에 넣을 계산서수신메일)."""
        cfg = self._load_settings()
        return bool(getattr(cfg, "claim_auto_pick", True)), str(getattr(cfg, "taxbill_email", "") or "").strip()

    def save_claim_draft(self) -> claim_form.SaveReport:
        """일반청구 [저장](임시저장)을 누른다. ERP 가 띄우는 알림·확인 창은 글을 모으고 넘긴다. 신청은 누르지 않는다."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        page, frame = claim_form.wait_for_form(self.page.context, log=self.log)
        if frame is None:
            report = claim_form.SaveReport(ok=False)
            report.note = "일반청구 작성 화면을 찾지 못했습니다. 채운 화면이 그대로 열려 있는지 확인하세요."
            self.log(report.note)
            return report
        saved_no = claim_form.saved_sheet(claim_form.read_state(frame, ["REQ_CNT", "APPR_DIV_CD"]))
        if saved_no:
            # 이미 저장된 청구서 — [임시저장] 을 두 번 누르거나 다른 청구서가 떠 있으면 줄이 하나 더 생긴다
            report = claim_form.SaveReport(ok=False)
            report.note = (f"이 화면은 이미 임시저장된 청구서입니다(결의번호 {saved_no}). 다시 누르면 줄이 하나 더 생겨 누르지 않았습니다. "
                           "ERP 의 청구내역 표에서 저장된 것을 확인하세요.")
            self.log(report.note)
            return report
        messages: list[str] = []

        def on_dialog(dialog) -> None:
            messages.append(dialog.message.strip())
            self.log("ERP 알림: %s" % dialog.message.strip())
            try:
                dialog.accept()
            except Exception:  # noqa: BLE001 — 이미 닫힌 창
                pass

        page.on("dialog", on_dialog)
        try:
            return claim_form.save_draft(frame, self.log, messages,
                                         wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)))
        finally:
            page.remove_listener("dialog", on_dialog)

    # ── 첨부만 다시 올리기 ───────────────────────────────────────────────
    def reattach_files(self, plan, dry_run: bool = True, ask=None, on_row=None) -> claim_reattach.ReattachReport:
        """이미 있는 청구서(임시저장 · 보완요청)의 청구내역 줄마다 첨부문서를 지우고 폴더 파일로 다시 붙여 [저장](claims/reattach.py,
        담당자 2026-10-23). 결의서내역에서 대표적요가 같은 그 청구서를 찾아 [상세조회/변경] 으로 띄운다(navigate.open_saved_sheet). [신청] 은 사람.

        ask(문구) 는 실측 전 단계(줄 다시 열기 · '삭제')가 기대대로 안 될 때 사람에게 — True 면 [계속], False 면 [멈추기]."""
        ask = ask or (lambda _m: False)
        if dry_run:
            return claim_reattach.run(None, None, plan, self.log, ask=ask, dry_run=True)
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        report = claim_reattach.ReattachReport(dry_run=False, plan=plan)
        project = self._project(getattr(plan, "project_no", ""))
        _page, current = claim_form.wait_for_form(self.page.context, tries=1)
        typed = self._typed_sheet(current)
        if typed:
            report.blocked = (f"작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있습니다 — 그 청구서를 [저장] 하거나 비운 뒤 다시 누르세요. "
                              "앱은 그 화면을 바꾸지 않습니다.")
            self.log(report.blocked)
            return report
        page, frame, row, why = navigate.open_saved_sheet(self.page.context, project, plan.summary, self.log, self._wait,
                                                          states=claim_reattach.STATE_WORDS)
        if frame is None and not getattr(plan, "project_no", "") and "청구서가 없습니다" in why:
            # 폴더에 과제가 없어 마지막에 고른 과제에서 찾았는데 없다 — 오늘이 과제기간에 든 다른 과제의 결의서내역도 차례로 본다
            # (담당자 실제 2026-10-23 17:18: 마지막 과제 202409710003(대응자금)에서 '없습니다' 로 멈췄는데 청구서 223 은 202408470003 에 있었다)
            for other, _label in navigate.choices(""):
                if other == project:
                    continue
                self.log(f"과제 {project} 의 결의서내역에 없어 과제 {other} 도 봅니다 (폴더에 과제가 비어 있음 — ② 의 과제 칸에서 고르면 그 과제에서 바로 찾습니다)")
                page, frame, row, why2 = navigate.open_saved_sheet(self.page.context, other, plan.summary, self.log, self._wait,
                                                                   states=claim_reattach.STATE_WORDS)
                if frame is not None:
                    project = other
                    break
                why = why + "\n" + why2
                if "청구서가 없습니다" not in why2:          # 둘 이상 · 못 띄움 — 그 까닭으로 멈춘다
                    break
        if frame is None:
            report.blocked = why
            self.log("첨부만 다시 올리기 — " + why)
            return report
        messages: list[str] = []

        def on_dialog(dialog) -> None:
            if self.hands_on:
                # 노란 띠에서 사람을 기다리는 동안 사람이 누른 것 — 앱이 대신 [확인] 하지 않고 브라우저에 보이게 둔다(_on_dialog)
                self.log("ERP 확인 창(브라우저에 보임 — 직접 누르세요): %s" % dialog.message.strip()[:200])
                return
            messages.append(dialog.message.strip())
            self.log("ERP 알림: %s" % dialog.message.strip())
            try:
                dialog.accept()
            except Exception:  # noqa: BLE001
                pass

        page.on("dialog", on_dialog)
        try:
            return claim_reattach.run(
                page, frame, plan, self.log, ask=ask, wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)),
                messages=messages, should_stop=self.should_stop, on_row=on_row, dry_run=False,
                req_cnt=str(row.get("seq") or ""), state=str(row.get("state") or ""))
        finally:
            page.remove_listener("dialog", on_dialog)

    # ── 장학금 ───────────────────────────────────────────────────────────
    def fill_scholarship(self, job, dry_run: bool = True, ask=None, on_person=None) -> claim_scholarship.ScholarshipReport:
        """장학금 청구 — 작성 화면 인건비 탭에 학생 한 명씩 넣고 [저장](claims/scholarship.py). [신청] 은 사람.

        ask(문구) 는 앱이 확신하지 못하는 단계에서 사람에게 묻는다 — True 면 [계속], False 면 [멈추기]. 이 스레드에서 기다린다.
        """
        with claim_scholarship.marked(job):                    # 시험이면 넣는 동안만 대표적요 앞에 [시험]
            if dry_run:
                # 미리 보기는 ERP 화면 없이 계획만 — 브라우저가 없어도 된다
                return claim_scholarship.run(None, None, job, self.log, ask=lambda _m: False, dry_run=True)
            return self._fill_scholarship(job, ask or (lambda _m: False), on_person)

    def _fill_scholarship(self, job, ask, on_person) -> claim_scholarship.ScholarshipReport:
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        cfg = self._load_settings()
        project = self._project(getattr(job, "project_no", ""))
        auto_sheet = getattr(cfg, "auto_new_sheet", True)
        # 앱이 새 청구서를 띄울 것이면 작성 화면이 없는 것이 보통이다 — '작성 화면을 찾지 못함' 대신 무엇을 할지 적는다(진단 줄은 그대로 남긴다)
        page, frame = claim_form.wait_for_form(self.page.context, log=None if auto_sheet else self.log)
        if frame is None and auto_sheet:
            self.log("작성 화면이 떠 있지 않음 (%s) — 결의서내역을 본 뒤 새 청구서를 띄웁니다" % claim_form.describe_frames(self.page.context))
        # 이 폴더의 청구서(멈췄다가 이어 넣기 — 결의번호 · 대표적요로 알아본다)가 앞에 있으면 그대로. 아니면 그 과제의 ERP 결의서내역에서
        # 대표적요가 같은 청구서를 먼저 찾고(담당자 요청 2026-10-19), 결의서 목록의 [일반청구] 로 새 청구서를 띄운다.
        continuing = False
        if frame is not None and navigate.frame_project(frame) in ("", project):
            own, why = claim_scholarship.sheet_owner(job, *claim_scholarship._read_sheet(frame))
            continuing = own and why != "새 청구서"
        if not continuing:
            report = claim_scholarship.ScholarshipReport(dry_run=False)
            typed = self._typed_sheet(frame)
            if typed:
                report.blocked = (f"작성 화면에 저장하지 않은 입력({' · '.join(typed)})이 있습니다 — 그 청구서를 [저장] 하거나 비운 뒤 다시 누르세요. "
                                  "앱은 그 화면을 바꾸지 않습니다.")
                self.log(report.blocked)
                return report
            stop = self._duplicate_check(job.main_summary, project, ask, getattr(job, "test_mode", False),
                                         lambda: claim_scholarship.record_warning(job))
            if stop:
                report.blocked = stop
                self.log(f"{job.spec.name} 청구 멈춤 — {stop}")
                return report
            page, frame = self._fresh_sheet(page, frame, project)
        if frame is None:
            report = claim_scholarship.ScholarshipReport(dry_run=False)
            report.blocked = ("작성 화면을 찾지 못했습니다. 앱이 연 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄운 뒤 "
                              "다시 누르세요. (인건비 탭은 앱이 누릅니다)")
            self.log(report.blocked)
            return report

        def open_sheet():
            # 넣는 도중 다른 청구서가 떠 있으면(_ensure_own_sheet) — 그 과제의 결의서 목록에서 새로 띄운다
            if navigate.list_frame(self.page.context, project) is None:
                self.go_to_claims(project)
            return navigate.open_new_sheet(self.page.context, self.log, self._wait, project)

        open_sheet = open_sheet if auto_sheet else None
        dry_run = False
        messages: list[str] = []

        def on_dialog(dialog) -> None:
            if self.hands_on:
                # 노란 띠에서 사람을 기다리는 동안 사람이 누른 것 — 앱이 대신 [확인] 하지 않고 브라우저에 보이게 둔다(_on_dialog)
                self.log("ERP 확인 창(브라우저에 보임 — 직접 누르세요): %s" % dialog.message.strip()[:200])
                return
            messages.append(dialog.message.strip())
            self.log("ERP 알림: %s" % dialog.message.strip())
            try:
                dialog.accept()
            except Exception:  # noqa: BLE001
                pass

        page.on("dialog", on_dialog)
        try:
            return claim_scholarship.run(
                page, frame, job, self.log, ask=ask or (lambda _m: False),
                wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)), messages=messages,
                should_stop=self.should_stop, on_person=on_person, dry_run=dry_run, auto_pick=self._popup_options()[0],
                open_sheet=open_sheet)
        finally:
            page.remove_listener("dialog", on_dialog)

    # ── 카드 ─────────────────────────────────────────────────────────────
    def card_members(self, job) -> list:
        """참여연구원 명단 — 설정의 파일, 없으면 카드 폴더 · 그 위 폴더의 '참여연구원 …' 엑셀 · PDF. 없으면 [] (참석자는 모두 내부참석자로)."""
        import os
        from .claims import participants
        folder = getattr(job, "folder", "") or ""
        path = participants.find_file(str(getattr(self._load_settings(), "participants_file", "") or ""),
                                      folder, os.path.dirname(folder))
        members = participants.read(path) if path else []
        self.log("참여연구원 명단: %s" % (f"{os.path.basename(path)} — {len(members)}명" if path else "없음 (설정 → 일반청구에서 고르세요)"))
        return members

    def fill_card(self, job, sheet_index: int, dry_run: bool = True, ask=None, on_item=None, project_no: str = "",
                  test_mode: bool = False):
        """카드청구 — 결제 기간 폴더의 청구서 하나(비목 하나)를 카드청구 작성 화면에 결제 건마다 넣고 [저장](claims/card_erp.py). [신청] 은 사람.

        이 청구서에 이어 넣는 것이 아니면 일반청구처럼 먼저 결의서내역에서 대표적요가 같은 청구서를 찾고(18절), 결의서 목록의 [카드청구](#P11)로
        새 카드청구 화면을 띄운다(담당자 허락 2026-10-20, 설정 auto_new_sheet). 못 띄우면 사람에게 띄우게 묻는다."""
        from .claims import card_erp
        sheet = job.sheets[sheet_index]
        members = self.card_members(job)
        summary = card_erp.main_summary(sheet, test_mode)
        if dry_run:
            return card_erp.run(None, None, job, sheet, self.log, ask=lambda _m: False, dry_run=True, members=members, test_mode=test_mode)
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        ask = ask or (lambda _m: False)
        project = self._project(project_no)
        context = self.page.context
        auto = bool(getattr(self._load_settings(), "auto_new_sheet", True))
        report = card_erp.CardReport(dry_run=False, summary=summary)
        page, frame = card_erp.wait_for_card_form(context, self._wait, tries=4)
        continuing = False
        if frame is not None and navigate.frame_project(frame) in ("", project):
            own, why = card_erp.sheet_owner(frame, sheet, summary)
            continuing = own and why != "새 카드청구서"
        if not continuing:
            stop = self._duplicate_check(summary, project, ask, test_mode, lambda: card_erp.record_warning(job, sheet))
            if stop:
                report.blocked = stop
                self.log("카드청구 멈춤 — " + stop)
                return report
            if auto:
                page, frame = self._fresh_card_sheet(page, frame, project)
        if frame is None:
            # 앱이 못 띄웠거나(설정에서 끔 · 저장하지 않은 입력) — 결의서 목록까지는 앱이 가고, [카드청구] 는 사람이
            if navigate.list_frame(context, project) is None:
                self.go_to_claims(project)
            for _ in range(3):
                if not ask("카드청구 작성 화면이 없습니다. 앱이 연 브라우저의 결의서내역에서 [카드청구] 를 눌러 카드청구 화면을 띄운 뒤 [계속]."):
                    break
                page, frame = card_erp.wait_for_card_form(context, self._wait, tries=8)
                if frame is not None:
                    break
        if frame is None:
            report.blocked = "카드청구 작성 화면을 찾지 못했습니다 — 결의서내역에서 [카드청구] 를 눌러 띄운 뒤 다시 누르세요."
            self.log(report.blocked)
            return report
        shown = navigate.frame_project(frame)
        if shown and project and shown != project:
            report.blocked = f"카드청구 화면이 다른 과제({shown})의 것입니다 — 고른 과제({project})의 결의서내역에서 [카드청구] 를 눌러 띄우세요."
            self.log(report.blocked)
            return report
        messages: list[str] = []

        def on_dialog(dialog) -> None:
            if self.hands_on:
                self.log("ERP 확인 창(브라우저에 보임 — 직접 누르세요): %s" % dialog.message.strip()[:200])
                return
            messages.append(dialog.message.strip())
            self.log("ERP 알림: %s" % dialog.message.strip())
            try:
                dialog.accept()
            except Exception:  # noqa: BLE001
                pass

        page.on("dialog", on_dialog)
        try:
            report = card_erp.run(page, frame, job, sheet, self.log, ask=ask,
                                  wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)), messages=messages,
                                  should_stop=self.should_stop, on_item=on_item, dry_run=False, members=members,
                                  test_mode=test_mode, find_frame=lambda: card_erp.find_card_form(context))
        finally:
            page.remove_listener("dialog", on_dialog)
        if not test_mode:
            try:
                card_erp.record_sheet(job, sheet, report)
            except Exception as error:  # noqa: BLE001 — 기록을 못 남겨도 넣은 것은 그대로
                self.log("카드청구 기록을 남기지 못했습니다: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
        return report

    def _fresh_card_sheet(self, page, frame, project: str):
        """이 과제의 새 카드청구 화면을 결의서 목록의 [카드청구] 로 띄워 앞에 둔다. 못 띄우면 받은 그대로(사람이 띄운 화면을 쓴다 · 없으면 사람에게 묻는다)."""
        from .claims import card_erp
        context = self.page.context
        if navigate.list_frame(context, project) is None:
            self.go_to_claims(project)
        opened, note, _fresh = navigate.open_card_sheet(context, self.log, self._wait, project, replace_empty=True)
        if not opened:
            # 사람이 띄워 둔 화면이 있으면 그대로 — 다른 청구서이거나 다른 탭 뒤에 있으면 card_erp.run 이 사람에게 묻는다
            self.log("새 카드청구 화면을 앱이 띄우지 못함: " + note)
            return page, frame
        return card_erp.wait_for_card_form(context, self._wait, tries=8)

    def check_scholarship_sheet(self, job):
        """신청 전 대조 — 작성 화면의 청구내역 표를 읽어 명단과 맞춘다(claims/sheet_check.py). 읽기만 한다."""
        from .claims import sheet_check
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        page, frame = claim_form.wait_for_form(self.page.context, log=self.log)
        if frame is None:
            self.log("신청 전 대조: 작성 화면을 찾지 못했습니다")
            return sheet_check.SheetCheck()
        with claim_scholarship.marked(job):                    # 시험으로 넣은 줄은 [시험] 대표적요로 맞춘다
            return claim_scholarship.check_sheet(frame, job, self.log, wait=lambda seconds: page.wait_for_timeout(int(seconds * 1000)))

    # ── 목록 ─────────────────────────────────────────────────────────────
    def read_list(self, project_no: str = "") -> Selection:
        """결의서내역 목록을 끝까지 읽어 받을 건을 고른다. project_no 를 주면(받기 화면의 과제 칸 — 담당자 요청 2026-10-21) 그 과제의
        결의서 목록을 앞에 띄운 뒤 읽는다(다른 과제 · 다른 탭이 앞이면 navigate.show_list 가 옮긴다 — 화면 이동, 6절)."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        ctx = self.page.context
        self.log("결의서 목록 찾는 중…")
        project = re.sub(r"\D", "", project_no or "")
        page, gfr = erp.wait_for_grid(ctx, tries=6 if project else 40)     # 첫 evaluate 함정(7절 1번) — 고른 과제가 있으면 짧게 보고 옮긴다
        if project and (gfr is None or navigate.frame_project(gfr) != project or not erp.grid_shown(gfr)):
            shown, why = navigate.show_list(ctx, project, self.log, self._wait)
            if shown is None or not erp.grid_shown(shown):
                dump = erp.dump_context(ctx)
                message = (f"과제 {project} 의 결의서내역 목록을 띄우지 못했습니다" + (f" — {why}" if why else "")
                           + ". 로그인했는지 보고, 브라우저에서 과제정보 → 청구서 → 결의서내역 목록을 띄운 뒤 다시 누르세요.")
                self.log(message)
                raise ListNotFound(dump, message)
            gfr, page = shown, getattr(shown, "page", page)
        if not gfr:
            dump = erp.dump_context(ctx)
            self.log("결의서내역 목록(그리드)을 찾지 못했습니다. 지금 열려 있는 창/프레임 구조:")
            self.log("─" * 60)
            self.log(dump)
            self.log("─" * 60)
            raise ListNotFound(dump)
        if not erp.grid_shown(gfr):
            # 다른 탭(일반청구 · 카드청구 작성 화면) 뒤에 숨은 목록은 끝까지 내려 읽을 수 없다 — 위쪽 '과제정보' 탭으로 앞에 가져온다
            # (화면 이동 — 담당자 허락 2026-10-19). 그래도 숨어 있으면 일부만 읽은 목록으로 받지 않는다(7절 4번처럼 조용히 빠뜨린다).
            self.log("결의서 목록이 다른 탭 뒤에 있어 앞으로 가져옵니다")
            shown, why = navigate.show_list(ctx, navigate.frame_project(gfr), self.log, self._wait)
            if shown is not None and erp.grid_shown(shown):
                gfr = shown
                page = getattr(shown, "page", page)
            else:
                message = ("결의서내역 목록이 다른 탭(일반청구 · 카드청구 작성 화면 등) 뒤에 있어 끝까지 읽지 못했습니다"
                           + (f" ({why})" if why and "뒤에" not in why else "")
                           + ". 브라우저 위쪽의 '과제정보' 탭을 눌러 목록을 앞에 띄운 뒤 다시 누르세요.")
                self.log(message)
                raise ListNotFound(erp.dump_context(ctx), message)
        # 목록이 그려질 때까지(앱이 막 띄웠으면 늦다 · 빈 과제면 ~5초 뒤 0줄)
        navigate._wait(lambda: (navigate._evaluate(gfr, erp.GRID_ROWS_JS) or 0) > 0, self._wait, tries=10)
        self.page = page            # 목록이 있는 창을 작업 창으로 쓴다
        listed = navigate.frame_project(gfr) or project
        self.log("결의서 목록 발견" + (f"(과제 {listed})" if listed else "") + ". 수집 중…")
        rows = erp.collect_all(gfr)
        self.log("수집 %d행" % len(rows))
        sel = select_targets(rows, self.done)
        unwanted = skiplist.load()
        if unwanted:
            # 청구서출력이 없어 받을 수 없는 결의서(담당자 2026-10-21 "받지 않아도 되는 결의서 목록") — 받을 것에서 뺀다.
            # 목록에 든 결의서구분은 통째로(담당자 2026-10-22 — 같은 구분의 새 결의서를 또 열어 보느라 시간이 들었다)
            names = skiplist.kinds(unwanted)
            by_kind: dict[str, int] = {}
            keep = []
            for r in sel.targets:
                kind = skiplist.kind_of(names, r)
                if kind:
                    by_kind[kind] = by_kind.get(kind, 0) + 1
                elif not skiplist.matches(unwanted, r, listed):
                    keep.append(r)
            sel.excluded = len(sel.targets) - len(keep)
            sel.targets = keep
            if sel.excluded:
                self.log(f"받지 않는 결의서 {sel.excluded}건은 뺐습니다 (청구서출력이 없는 결의서 — 받기 화면 [도구] → [받지 않는 결의서] 에서 봅니다)"
                         + ("" if not by_kind else " — 결의서구분으로 뺀 것: " + " · ".join(f"'{k}' {n}건" for k, n in by_kind.items())))
        sel.projects = [listed] if listed else []
        for row in sel.targets:
            row["project"] = listed          # 받을 때 이 과제의 폴더에 둔다(project_folders)
        root, why = project_folders.save_root(self._load_settings().out_root, listed)
        if root is None:
            # 과제 폴더가 없는 과제는 받지 않는다(담당자 2026-10-21 "지금 폴더 만든 과제만") — 목록에 보여도 받을 것에 넣지 않는다
            self.log("⚠ " + why)
            sel.blocked.append((listed, why))
            sel.targets = []
        elif sel.targets and listed and self._own_budget(listed, root):
            budget, why = self._budget(listed)
            if budget:
                for row in sel.targets:
                    row["budget"] = budget       # 받을 때 비목 번호 · 폴더를 이 차례로(naming.budget_code)
            else:
                # 비목 번호를 모르고 받으면 사업비 폴더(01. 인건비 …)나 미분류에 섞인다 — 받지 않고 까닭을 남긴다
                why = (f"과제 {listed} 는 비목이 사업비와 다릅니다(대응자금 · 연구지원비) — 과제정보 → 예산 탭에서 비목을 읽지 못해({why}) 받지 않았습니다. "
                       "다시 목록을 읽거나, 그대로면 [로그 보내기] 로 기록을 보내 주세요")
                self.log("⚠ " + why)
                sel.blocked.append((listed, why))
                sel.targets = []
        self.log("대상 %d건 (이미 보관된 %d건은 건너뜀)" % (len(sel.targets), sel.skipped)
                 + (f" → {root}" if root is not None and sel.targets else ""))
        try:
            # 다운로드 현황(구글 시트 탭) — 목록의 모든 줄을 받을 것인지 · 왜 아닌지로(progress.py, 담당자 2026-10-23)
            progress.record_claims(listed, rows, self.done, unwanted, root,
                                   blocked=next((why for no, why in sel.blocked if no == listed), ""))
        except OSError as error:
            self.log(f"다운로드 현황을 남기지 못했습니다: {error}")
        return sel

    def _own_budget(self, project: str, root) -> bool:
        """비목이 사업비와 달라 예산 탭 차례로 번호를 붙이는 과제인지 — 과제 폴더 · ERP 과제명에 '대응자금' · '연구지원비' 가 있으면(담당자 2026-10-21 · 10-22)."""
        names = [getattr(root, "name", "")] if project_folders.project_of(root or "") == project else []
        names += [p.name for p in navigate.load_projects()[0] if p.no == project]
        return naming.own_budget(*names)

    def _budget(self, project: str) -> tuple[list, str]:
        """그 과제의 예산 탭 비목 차례 — 한 번 읽으면 기억한다(못 읽으면 다음에 다시)."""
        if project not in self._budgets:
            budget, why = navigate.read_budget(self.page.context, project, self.log, self._wait)
            if not budget:
                return [], why
            self._budgets[project] = budget
            self.log(f"과제 {project} 는 비목이 사업비와 달라(대응자금 · 연구지원비) 비목 번호를 예산 탭 차례로 붙입니다: "
                     + " · ".join("%02d %s" % (i, name) for i, (_code, name) in enumerate(budget, 1)))
        return self._budgets[project], ""

    def plan_rebudget(self):
        """이미 받은 대응자금 파일 정리(rebudget.py, 담당자 2026-10-21) — 대응자금 과제 폴더마다 예산 탭 차례를 읽고 파일마다 할 일을 정한다.
        파일은 건드리지 않는다(옮기기는 담당자가 표를 보고 [바꾸기] 를 누른 뒤 apply_rebudget)."""
        from . import rebudget
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. [브라우저 열기] 로 ERP 에 로그인한 뒤 다시 누르세요.")
        erp_names = {p.no: p.name for p in navigate.load_projects()[0]}
        self.log("── 대응자금 파일 정리: 과제마다 예산 탭의 비목 차례를 읽고 받은 파일을 봅니다 (아직 옮기지 않음)")
        return rebudget.plan(self._load_settings().out_root, self._budget, erp_names, log=self.log)

    def apply_rebudget(self, moves: list):
        from . import rebudget
        self.log(f"── 대응자금 파일 정리: {len(moves)}개를 옮깁니다")
        rebudget.apply(moves, settings_mod.archive_cache_path(), self.log)
        self.log("── 대응자금 파일 정리 끝: 옮김 %d · 못 옮김 %d" % (sum(1 for m in moves if m.done), sum(1 for m in moves if not m.done)))
        return moves

    def _still_logged_in(self, tries: int = 40) -> bool:
        """ERP 를 새로 연 뒤 로그인이 그대로인지 — 메인화면 과제현황이 뜨면 True, 로그인 화면이면 False(최대 ~20초 본다)."""
        ctx = self.page.context
        for _ in range(tries):
            if navigate.read_projects(ctx):
                return True
            if navigate.logged_out(ctx):
                return False
            self._wait(0.5)
        return False

    def read_lists(self, projects: list[str]) -> Selection:
        """폴더 만든 과제 모두(받기 화면의 '폴더 만든 과제 모두') — 과제마다 결의서 목록을 띄워 읽고 합친다.
        목록을 못 띄운 과제는 건너뛰고 까닭을 남긴다(과제현황에 안 보이는 끝난 과제 등 — 사람이 그 과제를 골라 직접 띄우면 된다)."""
        total = Selection()
        for no in projects:
            if self.should_stop():
                total.blocked.append((no, "멈춤 요청으로 읽지 않음"))
                continue
            self.log(f"── 과제 {no} 의 결의서내역")
            try:
                sel = self.read_list(no)
            except ListNotFound as error:
                total.blocked.append((no, str(error).splitlines()[0]))
                continue
            total.targets += sel.targets
            total.skipped += sel.skipped
            total.excluded += sel.excluded
            total.projects += sel.projects
            total.blocked += sel.blocked
        self.log("── 과제 %d개를 읽음 · 받을 건 %d건 (이미 보관된 %d건은 건너뜀)%s"
                 % (len(total.projects), len(total.targets), total.skipped,
                    f" · 못 읽은 과제 {len(total.blocked)}개" if total.blocked else ""))
        return total

    def read_purchases(self, projects: list[str]) -> Selection:
        """구매요청(계약) 서류 — 구매·자산 → 구매진행관리 목록을 고른 과제들의 과제기간(2년씩)으로 조회해 그 과제의 건을 받기 표의 줄로(purchase.py, 23절).
        ERP 에서 과제를 고르지 않고 메인화면에서 바로 들어간다(담당자 2026-10-22). 과제기간은 로그인 뒤 읽어 둔 과제 목록(_과제목록.json · 지금 보이는 과제현황)에서."""
        if not self.browser_open:
            raise BrowserClosed("브라우저가 닫혀 있습니다. 브라우저를 다시 여세요.")
        ctx = self.page.context
        sel = Selection()
        wanted = [n for n in (re.sub(r"\D", "", str(p or "")) for p in projects) if n]
        known = {p.no: p for p in navigate.load_projects()[0]}
        known.update({p.no: p for p in navigate.read_projects(ctx) if p.start and p.end})
        dated = lambda n: n in known and known[n].start and known[n].end       # noqa: E731
        missing = [n for n in wanted if not dated(n)]
        trouble = ""
        if missing:
            # 끝난 과제의 과제기간은 '전체과제' 에만 보인다 — 앱이 거르기를 바꾸고 쪽을 넘겨 읽는다(담당자 2026-10-22 "메인화면에 과제기간이 있잖아")
            self.log(f"과제 {len(missing)}개의 과제기간을 몰라 메인화면 과제현황을 '{navigate.ALL_PROJECTS}' 로 바꿔 모든 쪽을 읽습니다: {' · '.join(missing)}")
            found, trouble = navigate.collect_all_projects(ctx, self.log, self._wait)
            if found:
                try:
                    navigate.save_projects(found)
                except OSError as error:
                    self.log(f"과제 목록을 남기지 못했습니다: {error}")
                known.update({p.no: p for p in found if p.start and p.end})
            if trouble:
                self.log("⚠ " + trouble)
        picked = [known[n] for n in wanted if dated(n)]
        for n in wanted:
            if not dated(n):
                sel.blocked.append((n, trouble or f"메인화면 과제현황 '{navigate.ALL_PROJECTS}' 의 모든 쪽에 과제 {n} 이 없거나 과제기간 칸이 비어 "
                                    "구매요청(계약) 서류를 읽지 않았습니다"))
        rng = purchase.span(picked)
        if not rng:
            self.log("⚠ 고른 과제의 과제기간을 몰라 구매요청(계약) 서류를 읽지 못했습니다")
            return sel
        self.log("구매요청(계약) 서류 — 구매·자산 메뉴로 갑니다 (과제기간 %s ~ %s)" % rng)
        frame, why = purchase.open_list(ctx, self.log, self._wait)
        if frame is None:
            raise ListNotFound(erp.dump_context(ctx), why)
        self.page = getattr(frame, "page", self.page)
        cfg = self._load_settings()
        seen: set[str] = set()
        others = 0
        done_before = purchase.load_done(purchase.purchase_home(cfg.out_root))
        listed: dict[str, list[dict]] = {n: [] for n in wanted}      # 다운로드 현황 — 고른 과제의 줄 전부(이미 다 받은 건도)
        complete = True
        for start, end in purchase.windows(*rng):
            if self.should_stop():
                complete = False
                break
            ok, why = purchase.search(frame, start, end, self.log, self._wait)
            if not ok:
                raise ListNotFound(erp.dump_context(ctx), f"구매진행관리 조회 실패: {why}")
            rows = purchase.read_rows(frame)
            if rows is None:
                raise ListNotFound(erp.dump_context(ctx), "구매진행관리 목록(IBSheet)을 읽지 못했습니다 — 그 화면을 [화면 구조 저장] 으로 보내 주세요")
            mine = 0
            already = 0
            for row in rows:
                no = str(row.get("req_no") or "")
                prj = re.sub(r"\D", "", str(row.get("prj_no") or ""))
                if not no or no in seen:
                    continue
                if prj not in wanted:
                    others += 1
                    continue
                seen.add(no)
                listed[prj].append(row)
                if no in done_before:
                    # 지난 받기에서 끝까지 받은 건 — 다시 열지 않는다(담당자 2026-10-22). 다시 받으려면 [도구] 의 받은 기록 비우기
                    already += 1
                    continue
                mine += 1
                folder, _why = purchase.case_dir(cfg.out_root, prj, no, row.get("title", ""), row.get("req_dt", ""))
                sel.targets.append(purchase.as_target(row, folder))
            self.log(f"구매진행관리 {start} ~ {end}: {len(rows)}줄 · 고른 과제의 건 {mine}건" + (f" · 이미 다 받은 건 {already}건은 뺌" if already else ""))
        for n in wanted:
            base, why = purchase.project_base(cfg.out_root, n)
            if base is None and any(t.get("project") == n for t in sel.targets):
                # 과제 폴더가 없는 과제의 건은 받지 않는다(담당자 2026-10-22 — 22절 청구서와 같은 규칙)
                self.log("⚠ " + why)
                sel.blocked.append((n, why))
                sel.targets = [t for t in sel.targets if t.get("project") != n]
        sel.projects = [p.no for p in picked]
        self.log("구매요청(계약) 건 %d건" % len(sel.targets) + (f" (다른 과제의 건 {others}건은 뺌)" if others else "")
                 + " — 받을 때 건마다 상세를 열어 첨부를 받고, 이미 있는 파일은 건너뜁니다")
        if complete:
            try:
                for n in wanted:
                    if dated(n):
                        progress.record_purchases(n, listed[n], done_before)       # 다운로드 현황(구글 시트 탭)
            except OSError as error:
                self.log(f"다운로드 현황을 남기지 못했습니다: {error}")
        return sel

    def read_docs(self, projects: list[str], claims: bool = True, purchases: bool = False) -> Selection:
        """받기 화면 ① 의 서류 — 청구서(결의서내역)와 구매요청(계약) 서류를 한 표로. 구매 쪽을 못 읽으면 청구서 줄은 두고 까닭만 남긴다."""
        total = Selection()
        if claims:
            sel = self.read_lists(projects) if len(projects) != 1 else self.read_list(projects[0])
            total.targets += sel.targets
            total.skipped += sel.skipped
            total.excluded += sel.excluded
            total.projects += sel.projects
            total.blocked += sel.blocked
        if purchases:
            try:
                psel = self.read_purchases(projects)
            except ListNotFound as error:
                if not claims:
                    raise
                why = str(error).splitlines()[0]
                self.log("⚠ 구매요청(계약) 서류를 읽지 못했습니다 — " + why)
                total.blocked.append(("구매요청(계약) 서류", why))
            else:
                total.targets += psel.targets
                total.blocked += psel.blocked
                for no in psel.projects:
                    if no not in total.projects:
                        total.projects.append(no)
        return total

    # ── 받기 ─────────────────────────────────────────────────────────────
    def download(self, targets: list[dict], on_item: ItemCallback | None = None, project_no: str = "") -> RunSummary:
        cfg = self._load_settings()
        report = on_item or (lambda *_: None)

        def notify(i: int, status: str, detail: str) -> None:
            report(i, status, detail)
            try:
                progress.record_claim_item(targets[i], status, detail)       # 다운로드 현황(구글 시트 탭) — 건마다 O/X
            except OSError as error:
                self.log(f"다운로드 현황을 남기지 못했습니다: {error}")

        summary = RunSummary()
        retried: dict[str, int] = {}
        # 구매요청(계약) 서류 줄(purchase.KIND)은 청구서와 다른 화면(구매·자산)에서 받는다 — 아래 청구서 고리는 건너뛰고 끝에 따로(purchase.run)
        purchase_idx = [i for i, r in enumerate(targets) if r.get("kind") == purchase.KIND]
        claims_left = len(targets) - len(purchase_idx)
        # 일반청구 작성 화면에도 '청구서출력' 이 있어 받기가 그 화면을 상세화면으로 볼 수 있다(7절 8번). 탐지 코드는 겪기 전까지
        # 바꾸지 않기로 했으니, 받기 전에 그 탭을 닫게 한다 — 엉뚱한 화면을 기다리다 ERP 를 새로 열면 작성 중인 값이 사라진다.
        try:
            form_open = self.claim_form_open() if claims_left else False
        except Exception:  # noqa: BLE001
            form_open = False
        if form_open:
            self.log("⚠ 일반청구 작성 화면이 열려 있어 받기 전에 닫게 합니다")
            if not self.ask_relogin("ERP 에 일반청구 작성 화면(청구서(일반) 탭)이 열려 있습니다. 받기가 그 화면을 상세화면으로 잘못 볼 수 "
                                    "있어요. 작성 중인 것이 있으면 [저장] 한 뒤 그 탭(위쪽 '청구서(일반)')을 닫고 계속하세요"
                                    + (" — 결의서내역 목록은 앱이 앞에 띄웁니다." if project_no or any(r.get("project") for r in targets)
                                       else ". 결의서내역 목록을 띄운 다음 계속하세요.")):
                summary.stopped = True
                self.log("사용자가 중단했습니다.")
                return summary
        # 건마다 그 과제(목록을 읽은 과제 — row['project'])의 결의서 목록을 앞에 두고 그 과제의 폴더에 받는다. 숨은 목록은 스크롤이
        # 움직이지 않아 행을 못 찾는다(read_list 와 같은 까닭). '폴더 만든 과제 모두' 면 과제가 바뀔 때마다 그 과제의 목록으로 옮긴다.
        fallback = re.sub(r"\D", "", project_no or "")
        current: str | None = None
        root = None
        i = 0
        while i < len(targets):
            if self.should_stop():
                summary.stopped = True
                self.log("멈춤 요청 — 여기서 그만 받습니다.")
                break
            row = targets[i]
            if row.get("kind") == purchase.KIND:
                i += 1
                continue
            project = re.sub(r"\D", "", str(row.get("project") or "")) or fallback
            if project != current:
                current = project
                root, why = project_folders.save_root(cfg.out_root, project)
                if root is not None and project:
                    shown, list_why = navigate.show_list(self.page.context, project, self.log, self._wait)
                    if shown is None or not erp.grid_shown(shown):
                        root, why = None, f"과제 {project} 의 결의서 목록을 앞에 띄우지 못했습니다: {list_why or '목록이 보이지 않음'}"
                    else:
                        self.page = getattr(shown, "page", self.page)
                if root is not None:
                    self.log(f"── 과제 {project or '(모름)'} → {root}")
                else:
                    self.log("⚠ 받기 건너뜀 — " + why)
            if root is None:
                summary.failed.append(row)
                notify(i, "failed", why)
                i += 1
                continue
            doc_project = re.match(r"(\d{12})-\d{8}-\d+$", str(row.get("docNo") or ""))
            if project and doc_project and doc_project.group(1) != project:
                # 문서번호 앞자리는 과제번호다 — 다른 과제의 청구서를 이 과제 폴더에 두지 않는다
                why_doc = f"문서번호가 다른 과제({doc_project.group(1)})의 것이라 과제 {project} 폴더에 두지 않음"
                self.log("      ✖ " + why_doc)
                summary.failed.append(row)
                notify(i, "failed", why_doc)
                i += 1
                continue
            kind = skiplist.kind_of(skiplist.kinds(skiplist.load()), row)
            if kind:
                # 이번 받기에서 같은 구분의 결의서가 청구서출력이 없다고 들어왔다 — 남은 건은 열어 보지 않고 넘긴다(담당자 2026-10-22)
                self.log("[%d/%d] No %s (결의 %s · %s) — 받지 않는 결의서구분이라 열지 않고 넘깁니다" % (
                    i + 1, len(targets), row.get("no"), row.get("seq"), kind))
                summary.unwanted.append(row)
                notify(i, "unwanted", f"결의서구분 '{kind}' 은 청구서출력이 없어 받지 않음")
                i += 1
                continue
            if row.get("docNo") and row["docNo"] in self.done:
                # 목록을 읽은 뒤 다시 훑은 보관 폴더에 이미 있는 건 — 표가 옛것이어도 다시 받지 않는다(2026-10-14 점검)
                self.log("[%d/%d] No %s — 이미 받은 문서번호라 건너뜀" % (i + 1, len(targets), row.get("no")))
                notify(i, "done", "이미 받음")
                i += 1
                continue
            notify(i, "running", "")
            self.log("[%d/%d] No %s (결의 %s%s) · %s" % (
                i + 1, len(targets), row.get("no"), row.get("seq"),
                f" · {row.get('gubun')}" if row.get("gubun") else "", (row.get("cont") or "")[:30]))
            try:
                _code, dest = self._process(self.page, row, str(root), cfg.name_date_first,
                                            cfg.wait_sec, self.log)
            except erp.NoPrintScreen as error:
                # 청구서가 아닌 결의서(잔액조정 · 대체 …) — 다시 해도 같으니 건너뛰고, 그 과제의 결의서 목록을 다시 앞에 둔 뒤 다음 건으로
                # (2026-10-21 실제: 이것을 멈춤으로 보고 ERP 를 새로 열어 다시 로그인을 물었다)
                reason = str(error).splitlines()[0] if str(error) else "청구서출력 없음"
                self.log("      ↷ 건너뜀 — %s (결의서구분 '%s')" % (reason, row.get("gubun") or "?"))
                # 받지 않는 결의서 목록에 넣어 다음 목록 읽기부터 뺀다(담당자 2026-10-21) — 청구 결의서는 넣지 않는다(skiplist.why_not)
                try:
                    added, why_not = skiplist.add(row, reason, project)
                except OSError as error:
                    added, why_not = False, f"목록 파일을 쓰지 못해서({error.__class__.__name__})"
                if added:
                    self.log("      → 받지 않는 결의서 목록에 넣었습니다 — 다음 목록 읽기부터 뺍니다")
                    summary.unwanted.append(row)
                    notify(i, "unwanted", "청구서출력이 없는 결의서 — 받지 않는 결의서 목록에 넣음")
                else:
                    self.log(f"      (받지 않는 결의서 목록에는 넣지 않음 — {why_not}. 다음에 다시 해 봅니다)")
                    summary.failed.append(row)
                    notify(i, "failed", "건너뜀: " + reason)
                current = None
                i += 1
                continue
            except Exception as error:   # noqa: BLE001
                msg = str(error).splitlines()[0] if str(error) else type(error).__name__
                self.log("      ✖ %s" % msg)
                if not self.browser_open:
                    summary.failed.append(row)
                    notify(i, "failed", "브라우저가 닫힘")
                    summary.stopped = True
                    self.log("브라우저가 닫혀 받기를 멈춥니다.")
                    break
                key = row.get("docNo") or str(i)
                if cfg.freeze_reload and retried.get(key, 0) < MAX_RETRY and erp.is_freeze_error(msg):
                    retried[key] = retried.get(key, 0) + 1
                    self.log("      ↻ 새로고침 후 이어받기 (%d/%d)" % (retried[key], MAX_RETRY))
                    notify(i, "retry", "ERP 를 새로 여는 중")
                    try:
                        self.page.goto(settings_mod.ERP_URL, wait_until="domcontentloaded")
                    except Exception:   # noqa: BLE001
                        pass
                    if project and self._still_logged_in():
                        # 쿠키가 이 브라우저 묶음에 그대로라 대개 로그인이 남아 있다 — 사람을 부르지 않고 그 과제의 목록을 다시 띄워 잇는다
                        self.log("      ERP 를 새로 열었고 로그인이 그대로라 과제 %s 의 결의서 목록을 다시 띄워 이어받습니다" % project)
                        current = None
                        continue
                    if not self.ask_relogin(
                            "상세화면이 멈춰 ERP 를 새로 열었습니다. 다시 로그인하고 "
                            "'결의서내역' 목록을 띄운 뒤 계속하세요."):
                        summary.failed.append(row)
                        notify(i, "failed", msg)
                        summary.stopped = True
                        self.log("사용자가 중단했습니다.")
                        break
                    page, gfr = erp.wait_for_grid(self.page.context)
                    if gfr:
                        self.page = page
                    current = None      # 다시 로그인한 뒤에는 그 과제의 목록을 다시 앞에 둔다
                    continue            # 같은 건 재시도
                summary.failed.append(row)
                notify(i, "failed", msg)
            else:
                self.done.add(row["docNo"])
                archive.save_done(settings_mod.done_path(), self.done)
                summary.ok += 1
                notify(i, "done", dest.name)
            i += 1

        if purchase_idx and not summary.stopped:
            self.log("── 구매요청(계약) 서류 %d건 — 구매·자산 메뉴에서 받습니다" % len(purchase_idx))
            picked = [targets[i] for i in purchase_idx]
            psum = purchase.run(self.page.context, self.page, picked, cfg.out_root, self.log, self._wait,
                                lambda k, status, detail: notify(purchase_idx[k], status, detail), self.should_stop)
            summary.purchase = psum
            try:
                progress.record_purchase_results(psum.cases)                 # 다운로드 현황 — 구매요청 · 검사처리 칸
            except OSError as error:
                self.log(f"다운로드 현황을 남기지 못했습니다: {error}")
            summary.ok += psum.ok
            failed_req = {c.req_no for c in psum.failed}
            summary.failed += [t for t in picked if str(t.get("req_no") or "") in failed_req]
            summary.stopped = summary.stopped or psum.stopped
        elif purchase_idx:
            for i in purchase_idx:
                summary.failed.append(targets[i])
                notify(i, "failed", "멈춤 요청으로 받지 않음")
        self.log("── 끝: 성공 %d건 / 실패 %d건" % (summary.ok, len(summary.failed))
                 + (" / 받지 않음 %d건(청구서출력이 없는 결의서 — 받지 않는 결의서 목록)" % len(summary.unwanted) if summary.unwanted else ""))
        for r in summary.failed:
            if r.get("kind") == purchase.KIND:
                self.log("   실패: 구매요구 %s %s" % (r.get("req_no"), (r.get("cont") or "")[:30]))
            else:
                self.log("   실패: No %s 결의 %s %s" % (r.get("no"), r.get("seq"), (r.get("cont") or "")[:30]))
        summary.missing = reconcile(cfg.excel_path, self.done, self.log)
        return summary


def file_logger(echo: Callable[[str], None] = print) -> Callable[[str], None]:
    """시각을 붙여 화면과 _실행로그.txt 에 함께 남긴다. 디버그는 항상 이 파일부터."""
    path = settings_mod.log_path()

    def log(msg: str) -> None:
        lines = str(msg).splitlines() or [""]
        stamp = time.strftime("%H:%M:%S ")
        text = "\n".join(stamp + line for line in lines)
        echo(text)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except OSError:
            pass

    return log
