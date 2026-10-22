"""브라우저 작업 스레드.

Playwright 동기 API 는 시작한 스레드에서만 쓸 수 있다. 그래서 스레드 하나를
앱이 살아 있는 동안 붙잡아 두고, 화면은 명령을 큐로 넘기기만 한다. 결과는
Qt 시그널로 돌아온다 — 다른 스레드에서 보낸 시그널은 Qt 가 화면 스레드로
옮겨 준다.

작업을 화면 스레드에서 돌리면 청구서 한 건(보고서 생성에 수십 초)마다 창이
얼어 사용자는 앱이 죽은 줄 안다.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback

from PySide6.QtCore import QObject, Signal

from .. import erp, navigate, settings
from ..session import BrowserClosed, ErpSession, ListNotFound, file_logger



WATCH_SECONDS = 20 * 60            # 브라우저를 연 뒤 로그인 · 결의서내역 목록을 지켜보는 시간(로그인은 사람)
IDLE_POLL_SECONDS = 2.0            # 할 일이 없을 때 브라우저 창이 닫혔는지 보는 간격

class SessionWorker(QObject):
    log = Signal(str)
    busy = Signal(bool, str)            # 작업 중 여부, 상태 문구
    prepared = Signal(object)           # archive.ScanReport
    browser_opened = Signal()
    listed = Signal(object)             # targets.Selection
    list_failed = Signal(str)
    item = Signal(int, str, str)        # 번호, 상태, 설명
    finished = Signal(object)           # session.RunSummary
    relogin = Signal(str)               # 사람이 다시 로그인해야 함
    error = Signal(str)
    failed = Signal(str, str)           # 명령을 넣은 화면("download" · "claim"), 오류 — 화면마다 제 명령의 오류만 받는다
    browser_state = Signal(bool)        # 명령을 마칠 때마다 브라우저가 살아 있는지
    structure_saved = Signal(str)       # 진단: 화면 구조를 저장한 파일 경로 (못 했으면 "")
    claim_filled = Signal(object)       # 일반청구: claims.form.FillReport
    claim_saved = Signal(object)        # 일반청구: claims.form.SaveReport (임시저장)
    payee_searched = Signal(object)     # 일반청구: claims.payee.PayeeReport (입금처 팝업 검색)
    taxbill_searched = Signal(object)   # 일반청구: claims.taxbill.TaxbillReport (세금계산서 조회 팝업)
    claim_form_state = Signal(bool)     # 일반청구 작성 화면이 브라우저에 떠 있는지
    scholarship_person = Signal(int, str, str)   # 장학금: 명단 번호, 상태, 설명
    scholarship_ask = Signal(str)       # 장학금: 앱이 확신 못 하는 단계 — 사람이 [계속]/[멈추기]
    scholarship_done = Signal(object)   # 장학금: claims.scholarship.ScholarshipReport
    sheet_checked = Signal(object)      # 신청 전 대조: claims.sheet_check.SheetCheck
    card_item = Signal(int, str, str)   # 카드: 결제 건 번호, 상태, 설명
    card_done = Signal(object)          # 카드: claims.card_erp.CardReport
    taxbill_item = Signal(int, str, str)   # 세금계산서 이어 넣기: 화면 줄 번호, 상태, 설명
    taxbill_run_done = Signal(object)      # 세금계산서 이어 넣기: claims.taxbill_run.TaxbillRunReport
    list_ready = Signal()               # 받기: 브라우저를 연 뒤 결의서내역 목록이 보인다 — 화면이 [목록 읽기] 를 저절로
    projects_read = Signal()            # 로그인 뒤 메인화면 과제현황에서 과제 목록을 읽어 _과제목록.json 에 남겼다 — 일반청구의 과제 고르기 칸이 다시 읽는다
    parking_opened = Signal(object)     # 주차등록: parking.OpenReport — 사이트를 열고 자동 로그인했는지
    parking_registered = Signal(object) # 주차등록: parking_link.LinkReport — 앱의 [등록] 으로 할인 링크를 만들었는지
    parking_applied = Signal(object)    # 주차등록: parking_screens.ApplyReport — 창 없이 할인을 적용했는지
    parking_history = Signal(object)    # 주차등록: parking_screens.HistoryReport — 할인 내역 표(읽기만)
    rebudget_planned = Signal(object)   # 대응자금 파일 정리: rebudget.Plan — 옮기기 전 표
    sites_changed = Signal(object)      # 화면 구조 저장: 앱 브라우저에 열린 사이트 {browser, erp, erp_login, parking}(session.open_sites)
    site_opened = Signal(str, str)      # 화면 구조 저장: 사이트를 열었거나 앞으로 가져왔다 — (사이트, 한 줄 안내)
    rebudget_applied = Signal(object)   # 대응자금 파일 정리: 옮긴 결과(rebudget.Move 목록)

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume_ok = False
        self._waiting_relogin = False
        self._capture_now = threading.Event()   # 띠에서 기다리는 중에 누른 [화면 구조 저장]
        self._capture_owner = "download"
        self._idle_stopped = False              # 띠에서 기다리다 오래 비워 멈춤 — 끝난 일을 활동으로 세지 않는다(곧 로그아웃)
        self._session: ErpSession | None = None
        self._capture_site = ""                 # [화면 구조 저장] 으로 읽을 사이트('erp' · 'parking', 빈 값은 모두)
        # 브라우저에 열린 사이트(화면 구조 저장 업무가 읽는다). 이 스레드가 통째로 바꿔 끼우기만 하므로 화면 스레드가 읽어도 된다
        self.sites: dict = {"browser": False, "erp": False, "erp_login": False, "parking": False}
        self._thread = threading.Thread(target=self._loop, name="erp-browser", daemon=True)
        self._thread.start()

    # ── 화면 스레드에서 부르는 것 ──────────────────────────────────────────
    def _put(self, name: str, args: tuple, owner: str) -> None:
        # 받기 · 일반청구 두 화면이 이 스레드를 같이 쓴다. 오류를 둘 다 받으면 같은 오류 창이 두 번 뜨고, 일반청구의 AI 읽기 상태까지
        # 풀렸다(2026-10-14 점검) — 명령마다 넣은 화면을 붙여 오류는 그 화면만 받는다(failed).
        self._queue.put((name, args, owner))

    def open_browser(self, scan: bool = True, owner: str = "download", watch: bool = False) -> None:
        """scan=False 면 보관 폴더를 읽지 않고 브라우저만 연다 — 일반청구는 보관 폴더가 필요 없다(받기 전에는 _ensure_scanned 가 읽는다).
        watch 면 연 뒤 결의서내역 목록이 뜨기를 지켜보다 list_ready 를 알린다(받기 화면). 설정 auto_open_project 면(기본) 어느 화면이 열든
        로그인을 기다렸다가 고른 과제의 청구서 탭까지 간다(navigate.py)."""
        self._put("open", (scan, watch), owner)

    def fill_claim(self, data: dict, dry_run: bool = True, project_no: str = "", folder: str = "", test_mode: bool = False) -> None:
        """project_no 는 그 폴더에 고른 과제(일반청구 화면), test_mode 면 적요 앞에 [시험] 을 붙이고 ERP 중복 확인을 건너뛴다."""
        self._stop.clear()
        self._put("fill_claim", (data, dry_run, project_no, folder, test_mode), "claim")

    def check_sheet(self, job) -> None:
        self._put("check_sheet", (job,), "claim")

    def check_claim_form(self, owner: str = "claim") -> None:
        self._put("check_claim_form", (), owner)

    def save_claim_draft(self) -> None:
        self._put("save_claim_draft", (), "claim")

    def search_payee(self, data: dict) -> None:
        self._put("search_payee", (data,), "claim")

    def search_taxbill(self, data: dict) -> None:
        self._put("search_taxbill", (data,), "claim")

    def fill_scholarship(self, job, dry_run: bool = True) -> None:
        self._stop.clear()
        self._put("fill_scholarship", (job, dry_run), "claim")

    def fill_card(self, job, sheet_index: int, dry_run: bool = True, project_no: str = "", test_mode: bool = False) -> None:
        self._stop.clear()
        self._put("fill_card", (job, sheet_index, dry_run, project_no, test_mode), "claim")

    def fill_taxbill_claims(self, items: list, dry_run: bool = True, test_mode: bool = False) -> None:
        """청구 종류 '세금계산서' 폴더들을 하나씩 일반청구 탭에 넣고 [저장] — 조회에 안 뜨면 건너뛰고 다음 폴더(session.fill_taxbill_claims)."""
        self._stop.clear()
        self._put("fill_taxbill_claims", (list(items), dry_run, test_mode), "claim")

    def open_parking(self, path: str = "") -> None:
        """주차등록 사이트를 앱 브라우저에서 열고(열려 있으면 그 탭) 로그인 정보가 있으면 한 번 자동 로그인(parking.py).
        path 를 주면 그 화면으로(할인 링크 목록 — 사람이 [QR 보기])."""
        self._put("open_parking", (path,), "parking")

    def apply_parking(self, car: str) -> None:
        """창 없이 할인 적용 — 차량번호 → 보유 할인권 '공무확인증' → 할인 선택 '공무확인증' → [종료](parking_screens.py)."""
        self._put("apply_parking", (car,), "parking")

    def read_parking_history(self) -> None:
        """창 없이 운영 → 할인 내역 표를 읽는다(읽기만)."""
        self._put("read_parking_history", (), "parking")

    def register_parking(self, request) -> None:
        """창 없이 앱 칸의 값(parking_link.LinkRequest)으로 주차 사이트의 [새 링크] 창을 채우고 [저장] 까지."""
        self._put("register_parking", (request,), "parking")

    def read_list(self, project_no: str = "") -> None:
        """project_no — 받기 화면에서 고른 과제. 그 과제의 결의서 목록을 앞에 띄운 뒤 읽는다(session.read_list)."""
        self._put("read_list", (project_no,), "download")

    def read_lists(self, projects: list[str]) -> None:
        """받기 화면의 '폴더 만든 과제 모두' — 과제마다 결의서 목록을 띄워 읽고 합친다(session.read_lists)."""
        self._stop.clear()
        self._put("read_lists", (list(projects),), "download")

    def plan_rebudget(self) -> None:
        """이미 받은 대응자금 파일 — 예산 탭 차례를 읽고 바꿀 이름을 정한다(옮기지 않음)."""
        self._put("plan_rebudget", (), "download")

    def apply_rebudget(self, moves: list) -> None:
        """담당자가 표를 보고 [바꾸기] 를 누른 뒤 — 정한 대로 옮긴다."""
        self._put("apply_rebudget", (list(moves),), "download")

    def forget_archive(self) -> None:
        """저장 폴더가 바뀌었다 — 다음 목록 읽기 전에 보관 폴더를 다시 훑게 한다."""
        self._put("forget_archive", (), "download")

    def download(self, targets: list[dict], project_no: str = "") -> None:
        """project_no — 목록을 읽은 과제. 받기 전에 그 과제의 결의서 목록을 앞에 둔다(session.download)."""
        self._stop.clear()
        self._put("download", (targets, project_no), "download")

    def open_site(self, site: str) -> None:
        """화면 구조 저장 업무 — 고른 사이트를 연다. 이미 열려 있으면 그 창을 앞으로만(다시 불러오지 않는다 — 로그인 · 띄운 화면 그대로)."""
        self._put("open_site", (site,), "structure")

    @property
    def waiting(self) -> bool:
        """노란 띠 · 재로그인 띠에서 사람을 기다리는 중 — 그때 누른 [화면 구조 저장] 은 바로 읽힌다."""
        return self._waiting_relogin

    def capture_structure(self, owner: str = "structure", site: str = "") -> None:
        """진단 모드 — 지금 열린 화면의 구조를 파일로. 읽기만 한다.

        장학금 노란 띠 · 재로그인 띠로 이 스레드가 기다리는 중이면 그 자리에서 바로 읽는다 — 큐에 넣으면 작업이 다 끝난 뒤에야 돌아,
        띠가 떠 있는 동안 연 팝업(국적 돋보기 등)을 실측할 수 없다(담당자 요청 2026-10-14: 일반청구에서도 화면 구조 저장)."""
        self._capture_owner = owner
        self._capture_site = site
        if self._waiting_relogin:
            self._capture_now.set()
        else:
            self._put("capture", (site,), owner)

    def request_stop(self) -> None:
        """지금 받는 건을 마치고 멈춘다. 받는 도중 끊으면 반쪽짜리 파일이 남는다."""
        self._stop.set()
        if self._waiting_relogin:
            self.answer_relogin(False)

    def answer_relogin(self, ok: bool) -> None:
        self._resume_ok = ok
        self._resume.set()

    def shutdown(self, timeout: float = 8.0) -> None:
        self.request_stop()
        self._queue.put(None)
        self._thread.join(timeout)

    # ── 작업 스레드 ─────────────────────────────────────────────────────
    def _ask_relogin(self, message: str) -> bool:
        if self._stop.is_set():
            return False
        self._resume.clear()
        self._waiting_relogin = True
        self.relogin.emit(message)
        self._wait_resume()
        self._waiting_relogin = False
        return self._resume_ok and not self._stop.is_set()

    def _wait_resume(self) -> None:
        """[계속]/[멈추기] 를 기다린다. 그 사이 [화면 구조 저장] 을 누르면 이 스레드에서 바로 읽는다(Playwright 는 이 스레드에서만).
        기다리는 동안은 사람이 브라우저를 쓰므로 ERP 확인 창이 브라우저에 그대로 보이게 한다(session._on_dialog)."""
        session = self._session
        was = getattr(session, "hands_on", True)
        if session is not None:
            session.hands_on = True
        try:
            ticks = 0
            while not self._resume.wait(0.25):
                if self._capture_now.is_set():
                    self._capture_now.clear()
                    self._capture_inline()
                ticks += 1
                if session is not None and ticks % 4 == 0:
                    # 1초마다 브라우저 소식을 받는다 — 사람이 띄운 확인 창이 '사람 차례' 일 때 전달돼야 앱이 [계속] 뒤에 대신 누르거나
                    # 앱의 알림 목록에 섞지 않는다(session._on_dialog · fill_scholarship 의 처리기)
                    try:
                        session.poll_alive()
                        due = session.auto_logout_due()
                    except Exception:  # noqa: BLE001
                        due = ""
                    self._emit_sites(session)       # 띠에서 기다리는 동안 연 팝업 · 사이트도 화면 구조 저장 업무에 보이게
                    if due == "idle":
                        # 띠를 띄운 채 오래 비웠다 — 하던 일을 멈추고(멈추기와 같다) 쉬는 고리에서 로그아웃한다(담당자 요청 2026-10-21).
                        # ERP 창을 닫은 것('closed')으로는 멈추지 않는다 — 하던 일이 끝나면 쉬는 고리가 로그아웃한다
                        session.log("띠를 띄운 채 ERP 를 오래 쓰지 않아 하던 일을 멈춥니다 — 곧 자동 로그아웃합니다")
                        self._idle_stopped = True
                        self._stop.set()
                        self._resume_ok = False
                        break
        finally:
            if session is not None:
                session.hands_on = was
        if self._capture_now.is_set():           # 띠가 닫히는 순간 누른 것 — 지금 작업 뒤에 돈다
            self._capture_now.clear()
            self._put("capture", (self._capture_site,), self._capture_owner)

    def _capture_inline(self) -> None:
        try:
            self.structure_saved.emit(str(self._session.capture_structure(self._capture_site)))
        except Exception as error:  # noqa: BLE001 — 실측이 실패해도 기다리던 작업은 이어 가야 한다(error 신호는 화면이 작업을 끝난 것으로 본다)
            self.log.emit("화면 구조를 저장하지 못했습니다: " + (str(error).splitlines()[0] if str(error) else type(error).__name__))
            self.structure_saved.emit("")

    def _loop(self) -> None:
        log = file_logger(self.log.emit)
        log("════ %s 앱 실행 ════" % time.strftime("%Y-%m-%d"))
        session = ErpSession(log, self._ask_relogin, should_stop=self._stop.is_set)
        session.hands_on = True       # 쉬는 동안은 사람이 브라우저를 쓴다 — 명령을 도는 동안만 False(아래)
        self._session = session
        alive = False
        while True:
            try:
                command = self._queue.get(timeout=IDLE_POLL_SECONDS)
            except queue.Empty:
                # 쉬는 동안 사람이 브라우저 창을 닫았으면 화면에 알린다 — 그래야 [브라우저 열기] 가 다시 보인다
                now = session.poll_alive() if alive else False
                self._auto_logout(session)
                if now != alive:
                    alive = now
                    self.browser_state.emit(now)
                self._emit_sites(session)
                continue
            if command is None:
                try:
                    session.auto_logout("app")            # 앱을 닫으면 브라우저도 닫힌다 — 로그아웃 없이 닫지 않게
                except Exception:  # noqa: BLE001
                    pass
                session.close()
                return
            name, args, owner = command
            session.hands_on = False          # 앱이 브라우저를 쓰는 동안 — 처리기 없는 확인 창은 앱이 닫는다(session._on_dialog)
            session.touch()                   # 앱이 ERP 를 쓰는 것도 활동이다(자동 로그아웃)
            self._idle_stopped = False
            try:
                getattr(self, "_do_" + name)(session, *args)
            except Exception as error:   # noqa: BLE001 — 스레드가 죽으면 앱 전체가 먹통이 된다
                log("오류: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
                log(traceback.format_exc())
                message = str(error).splitlines()[0] if str(error) else type(error).__name__
                self.failed.emit(owner, message)
                self.error.emit(message)
            finally:
                session.hands_on = True
                if not self._idle_stopped:
                    session.touch()
                alive = session.browser_open
                self.browser_state.emit(alive)
                self._emit_sites(session)
                self.busy.emit(False, "")

    def _auto_logout(self, session: ErpSession) -> None:
        """쉬는 동안 — 설정한 분(기본 30) 동안 ERP 를 쓰지 않았거나 ERP 창을 닫았으면 로그아웃(session.auto_logout_due · logout.py)."""
        try:
            due = session.auto_logout_due()
            if due:
                session.hands_on = False          # 로그아웃 확인 창은 앱이 받는다(session.logout 의 처리기)
                try:
                    session.auto_logout(due)
                finally:
                    session.hands_on = True
                    self._idle_stopped = False
        except Exception as error:  # noqa: BLE001 — 쉬는 고리가 죽으면 앱 전체가 먹통이 된다
            session.log("자동 로그아웃 중 오류: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
            session.erp_logged_in = False

    def _do_open(self, session: ErpSession, scan: bool = True, watch: bool = False) -> None:
        if scan:
            self.busy.emit(True, "보관 폴더를 읽는 중…")
            self.prepared.emit(session.prepare())
        self.busy.emit(True, "브라우저를 여는 중…")
        session.open_browser()
        self.browser_opened.emit()
        cfg = settings.load()
        if watch or cfg.auto_open_project:
            self.busy.emit(False, "")          # 지켜보는 동안에도 화면의 단추는 눌린다 — 누르면 아래 고리가 바로 끝난다
            self._watch_for_list(session, ready=watch, project_no=cfg.project_no if cfg.auto_open_project else "")

    def _watch_for_list(self, session: ErpSession, ready: bool = True, project_no: str = "") -> None:
        """사람이 로그인하면 — project_no 가 있으면 메인화면 과제현황에서 과제 목록을 읽어 두고 그 과제의 청구서 탭까지 간다(한 번만).
        결의서내역 목록이 보이면(그리드에 행이 두 번 연달아) ready 일 때 list_ready 를 알린다(받기 화면).

        로그인은 사람이 한다(9절) — 앱은 로그인 화면에서 아무것도 누르지 않는다. 다른 명령이 오거나(사람이 단추를 누름 ·
        일반청구가 브라우저를 씀) 브라우저가 닫히거나 WATCH_SECONDS 가 지나면 그만 본다. 이 스레드가 지켜보는 동안 다른 명령은
        길어야 한 번 쉬는 만큼(1.5초) 기다린다. 앱이 못 가면(과제가 안 보임 등) 기록에 까닭을 남기고, 사람이 띄우는 목록을 계속 기다린다."""
        deadline = time.monotonic() + WATCH_SECONDS
        seen = 0
        tried = not project_no
        session.hands_on = True        # 지켜보는 동안 사람이 로그인 · 이동한다 — 로그인 화면의 알림도 브라우저에 보여야 한다
        while time.monotonic() < deadline:
            if not self._queue.empty() or not session.browser_open or session.auto_logout_due():
                return
            try:
                session.page.wait_for_timeout(1500)
                rows = erp.grid_rows_shown(session.page.context)
                if not rows and not tried:
                    projects = session.read_projects()
                    if projects:                       # 로그인됐고 메인화면이 떴다
                        tried = True
                        self._remember_projects(session, projects)
                        session.log(f"로그인을 확인해 과제 {project_no} 의 청구서 화면으로 갑니다 (설정 → 동작에서 끌 수 있습니다)")
                        session.hands_on = False
                        try:
                            session.go_to_claims(project_no)
                        finally:
                            session.hands_on = True
                        rows = erp.grid_rows_shown(session.page.context)
            except Exception:  # noqa: BLE001 — 창이 닫히는 중 등: 지켜보기만 그만둔다
                return
            seen = seen + 1 if rows > 0 else 0
            if seen >= 2:                        # 그려지는 중에 읽지 않게 — 두 번 연달아 보이면
                if ready:
                    session.log("결의서내역 목록이 보여 저절로 읽습니다 (설정에서 끌 수 있습니다)")
                    self.list_ready.emit()
                return

    def _remember_projects(self, session: ErpSession, projects: list) -> None:
        try:
            navigate.save_projects(projects)
        except OSError as error:
            session.log(f"과제 목록을 남기지 못했습니다: {error}")
            return
        now = navigate.running(projects)
        session.log("과제현황에서 과제 %d개를 읽었습니다 (과제기간에 오늘이 든 과제 %d개: %s)"
                    % (len(projects), len(now), ", ".join(p.no for p in now) or "없음"))
        self.projects_read.emit()

    def _do_fill_claim(self, session: ErpSession, data: dict, dry_run: bool, project_no: str = "", folder: str = "",
                       test_mode: bool = False) -> None:
        self.busy.emit(True, "일반청구 화면을 확인하는 중…" if dry_run
                       else "ERP 결의서내역을 확인하고 일반청구 화면에 채우는 중… (팝업이 뜨면 고르고 [확인] 을 누르세요)")
        self.claim_filled.emit(session.fill_claim(data, dry_run, project_no=project_no, folder=folder, test_mode=test_mode,
                                                  ask=self._ask_person))

    def _do_save_claim_draft(self, session: ErpSession) -> None:
        self.busy.emit(True, "ERP 에 임시저장하는 중…")
        self.claim_saved.emit(session.save_claim_draft())

    def _do_search_taxbill(self, session: ErpSession, data: dict) -> None:
        self.busy.emit(True, "세금계산서 조회 팝업에서 조회하는 중…")
        self.taxbill_searched.emit(session.search_taxbill(data))

    def _do_search_payee(self, session: ErpSession, data: dict) -> None:
        self.busy.emit(True, "입금처 팝업에서 거래처를 검색하는 중…")
        self.payee_searched.emit(session.search_payee(data))

    def _ask_person(self, message: str) -> bool:
        """앱이 확신하지 못하는 단계(장학금 · 넣기 전 ERP 중복 확인). 재로그인 띠와 같은 방식으로 이 스레드가 [계속]/[멈추기] 를 기다린다."""
        if self._stop.is_set():
            return False
        self._resume.clear()
        self._waiting_relogin = True
        self.scholarship_ask.emit(message)
        self._wait_resume()
        self._waiting_relogin = False
        return self._resume_ok and not self._stop.is_set()

    def _do_fill_scholarship(self, session: ErpSession, job, dry_run: bool) -> None:
        name = job.spec.name if hasattr(job, "spec") else "장학금"
        self.busy.emit(True, f"{name} 계획을 만드는 중…" if dry_run else f"{name} 청구를 넣는 중… (멈추면 안내를 따라 주세요)")
        report = session.fill_scholarship(job, dry_run=dry_run, ask=self._ask_person, on_person=self.scholarship_person.emit)
        self.scholarship_done.emit(report)

    def _do_fill_taxbill_claims(self, session: ErpSession, items: list, dry_run: bool, test_mode: bool) -> None:
        self.busy.emit(True, "세금계산서 청구 계획을 만드는 중…" if dry_run
                       else "세금계산서 청구를 폴더마다 넣는 중… (팝업 · 증빙 창이 필요하면 노란 띠로 묻습니다)")
        report = session.fill_taxbill_claims(items, dry_run=dry_run, test_mode=test_mode, ask=self._ask_person,
                                             on_item=self.taxbill_item.emit)
        self.taxbill_run_done.emit(report)

    def _do_fill_card(self, session: ErpSession, job, sheet_index: int, dry_run: bool, project_no: str, test_mode: bool) -> None:
        self.busy.emit(True, "카드청구 계획을 만드는 중…" if dry_run else "카드청구를 넣는 중… (멈추면 안내를 따라 주세요)")
        report = session.fill_card(job, sheet_index, dry_run=dry_run, ask=self._ask_person, on_item=self.card_item.emit,
                                   project_no=project_no, test_mode=test_mode)
        self.card_done.emit(report)

    def _do_check_sheet(self, session: ErpSession, job) -> None:
        self.busy.emit(True, "청구내역 표를 읽어 명단과 맞추는 중…")
        self.sheet_checked.emit(session.check_scholarship_sheet(job))

    def _do_check_claim_form(self, session: ErpSession) -> None:
        self.claim_form_state.emit(session.claim_form_open())

    def _do_capture(self, session: ErpSession, site: str = "") -> None:
        self.busy.emit(True, "화면 구조를 읽는 중…")
        self.structure_saved.emit(str(session.capture_structure(site)))

    def _do_open_site(self, session: ErpSession, site: str) -> None:
        if site == "parking":
            self.busy.emit(True, "주차등록 사이트를 여는 중…")
            url, login = self._parking_site()
            report = session.open_parking(url, login)
            note = report.note or ("주차등록 사이트를 열었습니다 — 실측할 화면을 띄운 뒤 [화면 구조 저장] 을 누르세요"
                                   if report.opened else "주차등록 사이트를 열지 못했습니다")
            self.site_opened.emit(site, note)
            return
        self.busy.emit(True, "ERP 를 여는 중…")
        self.site_opened.emit(site, session.show_erp())

    def _emit_sites(self, session: ErpSession) -> None:
        try:
            now = session.open_sites()
        except Exception:  # noqa: BLE001 — 닫히는 중
            now = {"browser": False, "erp": False, "erp_login": False, "parking": False}
        if now != getattr(self, "sites", None):
            self.sites = now
            self.sites_changed.emit(now)

    def _ensure_scanned(self, session: ErpSession) -> None:
        """받기 전에는 보관 폴더를 반드시 한 번 훑는다. 일반청구가 브라우저를 먼저 열면(scan=False) 훑지 않은 채
        받기 화면의 ①이 끝난 것처럼 보여, 이미 받은 청구서를 다시 받고 받은 기록까지 덮어썼다(7절 4번 · 2026-10-14 점검)."""
        if session.archive_report is None or not session.archive_report.ok:     # 실패했으면 폴더를 고쳤을 수 있어 다시
            self.busy.emit(True, "보관 폴더를 읽는 중…")
            self.prepared.emit(session.prepare())

    def _do_forget_archive(self, session: ErpSession) -> None:
        session.archive_report = None

    @staticmethod
    def _parking_site(hidden: bool = False) -> tuple[str, tuple[str, str] | None]:
        """주소 · 로그인 정보. 창 없이 하는 일(hidden)은 '열 때 자동 로그인' 체크와 상관없이 로그인 정보를 쓴다 — 사람이 로그인할 창이 없다."""
        from .. import parking
        cfg = settings.load()
        return cfg.parking_url or parking.DEFAULT_URL, parking.load_login() if (hidden or cfg.parking_auto_login) else None

    def _do_open_parking(self, session: ErpSession, path: str = "") -> None:
        self.busy.emit(True, "주차등록 사이트를 여는 중…")
        url, login = self._parking_site()
        self.parking_opened.emit(session.open_parking(url, login, path))

    def _do_register_parking(self, session: ErpSession, request) -> None:
        self.busy.emit(True, "주차 사이트에 할인 링크를 넣는 중…")
        url, login = self._parking_site(hidden=True)
        self.parking_registered.emit(session.register_parking_link(request, url, login))

    def _do_apply_parking(self, session: ErpSession, car: str) -> None:
        self.busy.emit(True, "주차 사이트에서 할인을 적용하는 중…")
        url, login = self._parking_site(hidden=True)
        self.parking_applied.emit(session.apply_parking_discount(car, url, login))

    def _do_read_parking_history(self, session: ErpSession) -> None:
        self.busy.emit(True, "주차 사이트의 할인 내역을 읽는 중…")
        url, login = self._parking_site(hidden=True)
        self.parking_history.emit(session.read_parking_history(url, login))

    def _do_read_list(self, session: ErpSession, project_no: str = "") -> None:
        if session.browser_open and session.erp_page() is None:
            # 주차등록만 열어 둔 브라우저 — ERP 를 새 탭으로 열고 로그인 뒤 목록이 보이면 받기 화면이 다시 읽는다(list_ready)
            session.open_browser()
            self.browser_opened.emit()
            cfg = settings.load()
            self.busy.emit(False, "")
            self._watch_for_list(session, ready=True, project_no=project_no or (cfg.project_no if cfg.auto_open_project else ""))
            return
        self._ensure_scanned(session)
        self.busy.emit(True, "결의서 목록을 읽는 중…")
        try:
            selection = session.read_list(project_no)
        except (ListNotFound, BrowserClosed) as error:
            self.list_failed.emit(str(error))
            return
        self.listed.emit(selection)

    def _do_read_lists(self, session: ErpSession, projects: list[str]) -> None:
        if session.browser_open and session.erp_page() is None:
            self._do_read_list(session, "")          # 주차등록만 열린 브라우저 — ERP 를 열고 로그인을 기다린다(위와 같음)
            return
        self._ensure_scanned(session)
        self.busy.emit(True, f"과제 {len(projects)}개의 결의서 목록을 읽는 중…")
        try:
            selection = session.read_lists(projects)
        except BrowserClosed as error:
            self.list_failed.emit(str(error))
            return
        self.listed.emit(selection)

    def _do_plan_rebudget(self, session: ErpSession) -> None:
        self.busy.emit(True, "대응자금 과제의 예산 탭을 읽고 받은 파일을 보는 중…")
        self.rebudget_planned.emit(session.plan_rebudget())

    def _do_apply_rebudget(self, session: ErpSession, moves: list) -> None:
        self.busy.emit(True, "대응자금 파일을 옮기는 중…")
        self.rebudget_applied.emit(session.apply_rebudget(moves))

    def _do_download(self, session: ErpSession, targets: list[dict], project_no: str = "") -> None:
        self._ensure_scanned(session)
        self.busy.emit(True, "청구서를 받는 중…")
        summary = session.download(targets, on_item=self.item.emit, project_no=project_no)
        self.finished.emit(summary)
