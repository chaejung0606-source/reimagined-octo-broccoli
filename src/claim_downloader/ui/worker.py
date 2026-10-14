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

from ..session import BrowserClosed, ErpSession, ListNotFound, file_logger


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

    def __init__(self) -> None:
        super().__init__()
        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._resume = threading.Event()
        self._resume_ok = False
        self._waiting_relogin = False
        self._capture_now = threading.Event()   # 띠에서 기다리는 중에 누른 [화면 구조 저장]
        self._session: ErpSession | None = None
        self._thread = threading.Thread(target=self._loop, name="erp-browser", daemon=True)
        self._thread.start()

    # ── 화면 스레드에서 부르는 것 ──────────────────────────────────────────
    def open_browser(self, scan: bool = True) -> None:
        """scan=False 면 보관 폴더를 읽지 않고 브라우저만 연다 — 일반청구는 보관 폴더가 필요 없다."""
        self._queue.put(("open", (scan,)))

    def fill_claim(self, data: dict, dry_run: bool = True) -> None:
        self._queue.put(("fill_claim", (data, dry_run)))

    def check_claim_form(self) -> None:
        self._queue.put(("check_claim_form", ()))

    def save_claim_draft(self) -> None:
        self._queue.put(("save_claim_draft", ()))

    def search_payee(self, data: dict) -> None:
        self._queue.put(("search_payee", (data,)))

    def search_taxbill(self, data: dict) -> None:
        self._queue.put(("search_taxbill", (data,)))

    def fill_scholarship(self, job, dry_run: bool = True) -> None:
        self._stop.clear()
        self._queue.put(("fill_scholarship", (job, dry_run)))

    def read_list(self) -> None:
        self._queue.put(("read_list", ()))

    def download(self, targets: list[dict]) -> None:
        self._stop.clear()
        self._queue.put(("download", (targets,)))

    def capture_structure(self) -> None:
        """진단 모드 — 지금 열린 화면의 구조를 파일로. 읽기만 한다.

        장학금 노란 띠 · 재로그인 띠로 이 스레드가 기다리는 중이면 그 자리에서 바로 읽는다 — 큐에 넣으면 작업이 다 끝난 뒤에야 돌아,
        띠가 떠 있는 동안 연 팝업(국적 돋보기 등)을 실측할 수 없다(담당자 요청 2026-10-14: 일반청구에서도 화면 구조 저장)."""
        if self._waiting_relogin:
            self._capture_now.set()
        else:
            self._queue.put(("capture", ()))

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
        """[계속]/[멈추기] 를 기다린다. 그 사이 [화면 구조 저장] 을 누르면 이 스레드에서 바로 읽는다(Playwright 는 이 스레드에서만)."""
        while not self._resume.wait(0.25):
            if self._capture_now.is_set():
                self._capture_now.clear()
                self._capture_inline()
        if self._capture_now.is_set():           # 띠가 닫히는 순간 누른 것 — 지금 작업 뒤에 돈다
            self._capture_now.clear()
            self._queue.put(("capture", ()))

    def _capture_inline(self) -> None:
        try:
            self.structure_saved.emit(str(self._session.capture_structure()))
        except Exception as error:  # noqa: BLE001 — 실측이 실패해도 기다리던 작업은 이어 가야 한다(error 신호는 화면이 작업을 끝난 것으로 본다)
            self.log.emit("화면 구조를 저장하지 못했습니다: " + (str(error).splitlines()[0] if str(error) else type(error).__name__))
            self.structure_saved.emit("")

    def _loop(self) -> None:
        log = file_logger(self.log.emit)
        log("════ %s 앱 실행 ════" % time.strftime("%Y-%m-%d"))
        session = ErpSession(log, self._ask_relogin, should_stop=self._stop.is_set)
        self._session = session
        while True:
            command = self._queue.get()
            if command is None:
                session.close()
                return
            name, args = command
            try:
                getattr(self, "_do_" + name)(session, *args)
            except Exception as error:   # noqa: BLE001 — 스레드가 죽으면 앱 전체가 먹통이 된다
                log("오류: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
                log(traceback.format_exc())
                self.error.emit(str(error).splitlines()[0] if str(error) else type(error).__name__)
            finally:
                self.browser_state.emit(session.browser_open)
                self.busy.emit(False, "")

    def _do_open(self, session: ErpSession, scan: bool = True) -> None:
        if scan:
            self.busy.emit(True, "보관 폴더를 읽는 중…")
            self.prepared.emit(session.prepare())
        self.busy.emit(True, "브라우저를 여는 중…")
        session.open_browser()
        self.browser_opened.emit()

    def _do_fill_claim(self, session: ErpSession, data: dict, dry_run: bool) -> None:
        self.busy.emit(True, "일반청구 화면을 확인하는 중…" if dry_run
                       else "일반청구 화면에 채우는 중… (팝업이 뜨면 고르고 [확인] 을 누르세요)")
        self.claim_filled.emit(session.fill_claim(data, dry_run))

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
        """장학금 — 앱이 확신하지 못하는 단계. 재로그인 띠와 같은 방식으로 이 스레드가 [계속]/[멈추기] 를 기다린다."""
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

    def _do_check_claim_form(self, session: ErpSession) -> None:
        self.claim_form_state.emit(session.claim_form_open())

    def _do_capture(self, session: ErpSession) -> None:
        self.busy.emit(True, "화면 구조를 읽는 중…")
        self.structure_saved.emit(str(session.capture_structure()))

    def _do_read_list(self, session: ErpSession) -> None:
        self.busy.emit(True, "결의서 목록을 읽는 중…")
        try:
            selection = session.read_list()
        except (ListNotFound, BrowserClosed) as error:
            self.list_failed.emit(str(error))
            return
        self.listed.emit(selection)

    def _do_download(self, session: ErpSession, targets: list[dict]) -> None:
        self.busy.emit(True, "청구서를 받는 중…")
        summary = session.download(targets, on_item=self.item.emit)
        self.finished.emit(summary)
