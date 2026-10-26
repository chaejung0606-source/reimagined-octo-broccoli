"""일반청구 화면 — 지출 폴더를 넣고 [내용 읽기] → 값을 고치고 → [ERP 에 채우기] → 사람이 입금처·첨부 → [임시저장] → 사람이 검토·신청.

폴더마다 **청구 종류**를 고른다(claims/kinds.py, 담당자 제안 2026-10-14) — 일반(AI 가 서류를 읽음) · 세금계산서(일반처럼 읽되 증빙구분을
세금계산서로 두고, 폴더마다 조회 팝업 → 입금처 → 첨부 → [저장] 까지 이어 넣는다 — 조회에 안 뜨면 건너뛰고 다음 폴더, 담당자 2026-10-22) · 장학금(명단 엑셀 + 공통/개별증빙,
오른쪽 칸이 학생 표로 바뀌고 [ERP 에 넣기] 가 학생마다 인건비 탭에 넣고 저장) · 카드(결제 기간 폴더를 읽어 비목마다 청구서로 나눠
미리 보기만 — ERP 에 넣기는 카드청구 화면 실측 뒤) · 출장비(준비 중, 고를 수 없음). '자동' 이면 폴더 모양으로 정한다.

할 차례인 단계만 위에서 아래로 떠오른다(ui/flow.py, 담당자 요청 2026-10-21 — "클릭해야 하는 이동 순서대로 하나 둘 떠오르게"):
    ① 청구 종류(카드 — 담당자 2026-10-26 "1단계에서 청구종류를 선택") → ② 지출 폴더 넣기(과제 · 끌어다 놓기)
    → ③ 내용 확인(목록 | 고른 줄의 값 · 명단 · 결제 건, 일반은 [내용 읽기](AI))
    → ④ ERP 에 넣기(브라우저 · [미리 보기]/[ERP 에 넣기] · 넣은 뒤 할 것) → ERP 에서 사람이 검토하고 [신청]

담당자 결정(2026-10-13): 내역 작성 후 임시저장까지 앱이, 그 뒤는 사람이. 기본은 '미리 보기만'(dry-run) — 체크를
풀어야 실제로 넣는다. 신청·삭제·초기화는 코드가 절대 누르지 않는다(claims/form.py). 넣기 전에 그 폴더의 과제(폴더마다 고름)의
ERP 결의서내역에서 대표적요가 같은 청구서를 찾아 있으면 묻는다 — 앱 기록(claims/record.py)은 결의서내역을 못 읽을 때만(담당자 요청 2026-10-19).
[시험] 을 켜면 대표적요 앞에 [시험] 을 붙이고 그 확인과 기록을 건너뛴다(이미 올린 폴더로 시험).

브라우저는 청구서 받기와 같은 스레드(app.session_worker)를 쓴다 — ERP 로그인은 한 번이면 된다.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import ai, navigate, settings
from ...claims import card as card_mod
from ...claims import card_erp
from ...claims import participants as part_mod
from ...claims import kinds, record, rules, schema
from ...claims import reattach as reattach_mod
from ...claims import taxbill_run
from ...claims import scholarship as sch
from ...minutes.backends import claude_cli
from .. import ai_status, project_box
from ..art import Art
from ..log_button import LogSendButton, warn
from ..claim_worker import ClaimExtractWorker
from ..flow import HIDDEN, ChoiceCard, FlowArea, FlowStep
from ..flowlogic import CLAIM_ORDER, claim_stage, flow_states
from ..report_dialog import ReportRow, show_report
from ..widgets import Card, Field, Pill, PillDelegate, WrapLabel, muted_label
from ..worker import SessionWorker
from .card import CardPanel, item_detail
from .scholarship import ScholarshipPanel

COLUMNS = [("상태", 96), ("종류", 108), ("지출 (폴더)", 200), ("적요", 280), ("청구액", 110), ("입금처", None)]
COL_STATUS, COL_KIND, COL_DIR, COL_SUMMARY, COL_AMOUNT, COL_PAYEE = 0, 1, 2, 3, 4, 5

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "running": ("읽는 중", "info"),
    "read": ("읽음", "success"),
    "failed": ("실패", "danger"),
    "skipped": ("건너뜀", "warning"),
    "stopped": ("안 함", "neutral"),
    "filled": ("채움", "success"),
    "saved": ("임시저장", "success"),
    "problem": ("확인 필요", "warning"),
    "erp": ("넣는 중", "info"),
    "partial": ("일부 저장", "warning"),
    "missing": ("세금계산서 없음", "warning"),     # 세금계산서 종류 — 조회 팝업에 안 떠서(본부 등록 전) 건너뜀
}

GUIDE_START = "청구 종류를 고르세요. 그다음 지출 폴더를 넣으면 일반 · 세금계산서는 [내용 읽기], 장학금 · 혁신인재지원금은 바로 학생 명단이 나옵니다."
GUIDE_ADD = "과제를 확인하고 지출 폴더를 넣으세요. 폴더 1개 = 청구 1건 — 넣은 뒤에도 ③ 의 오른쪽 칸 위에서 폴더마다 종류를 바꿀 수 있습니다."
GUIDE_SCHOLARSHIP = ("학생 표를 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [ERP 에 넣기] 를 누르세요. "
                     "인건비 탭은 앱이 누릅니다.")
# 새 청구서를 앱이 띄울 때(설정 auto_new_sheet, 기본) — 사람은 로그인만 하면 된다
GUIDE_SCHOLARSHIP_AUTO = ("학생 표와 위의 과제를 확인한 뒤 [ERP 에 넣기] 를 누르세요. 그 과제의 결의서내역에 같은 청구서가 있는지 보고, "
                          "새 청구서 · 인건비 탭은 앱이 띄웁니다. 이미 올린 폴더로 시험하려면 [시험] 을 켜세요.")
GUIDE_CARD = ("비목마다 청구서로 나눠 읽었습니다. 사용일 · 금액 · 청구구분을 확인하고, 틀리면 폴더 이름이나 파일을 고친 뒤 [다시 읽기]. "
              "넣을 때는 '넣을 청구서' 를 고르고 [ERP 에 넣기] — 카드청구 화면은 앱이 결의서내역의 [카드청구] 로 띄웁니다.")
GUIDE_PERSONAL = ("사람 표와 비목 · 대표적요(공통증빙의 지급 공문에서 찾음)를 확인한 뒤 [ERP 에 넣기] 를 누르세요. 일반청구 탭에 사람마다 "
                  "입금처를 고르고 증빙 기타로 넣어 [저장] 합니다. 이미 올린 폴더로 시험하려면 [시험] 을 켜세요.")
GUIDE_READ = ("값을 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [미리 보기] 로 확인하세요. "
              "실제로 넣으려면 '미리 보기만' 체크를 풀고 [ERP 에 채우기].")
GUIDE_TAXBILL = ("세금계산서 폴더입니다 — 값(승인번호 · 사업자번호 · 금액)을 확인한 뒤 [ERP 에 넣기] 를 누르면 읽은 세금계산서 폴더를 하나씩 새 청구서에 "
                 "넣고 [저장] 합니다(조회 팝업에 안 뜨는 폴더는 건너뜀). 청구종류 · 증빙 창은 노란 띠가 뜨면 직접 작성하세요.")
GUIDE_REATTACH = ("'할 일' 이 첨부만 다시 올리기입니다 — 위의 과제가 그 청구서가 있는 과제인지 확인한 뒤 ④ 의 [첨부만 다시 올리기] 를 누르세요. "
                  "앱이 그 과제의 결의서내역에서 대표적요가 같은 임시저장 · 보완요청 청구서를 찾아 열고, 청구내역 줄마다 첨부문서를 지운 뒤 폴더의 지금 파일을 "
                  "올려 [저장] 합니다. 청구내역 값은 넣지 않고 [신청] 은 직접. '미리 보기만' 이면 표로만 봅니다.")
GUIDE_UNREAD = ("일반 폴더는 [내용 읽기] 를 누르면 AI 가 서류를 읽어 오른쪽 칸을 채웁니다(ERP 에는 아직 넣지 않습니다). "
                "읽은 값을 확인하면 ④ 에서 ERP 에 넣습니다.")
NO_BACKEND = ("일반 폴더의 [내용 읽기] 는 Claude Code 가 필요합니다(장학금 · 혁신인재지원금은 AI 없이 됩니다). Claude Code 를 설치한 뒤 "
              "[다시 확인] 을 누르세요. 설치했는데도 이 안내가 보이면 컴퓨터를 다시 시작해 보세요.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


# 장학금 미리 보기 · 넣기 확인 · 결과 창의 표 (ui/report_dialog.py) — 사람마다 한 줄
CARD_COLUMNS = [("상태", 96), ("사용일", 70), ("건명", 200), ("금액", 84), ("청구구분", 110), ("확인할 것", None)]
TAXBILL_COLUMNS = [("상태", 110), ("폴더", 180), ("적요", 260), ("청구액", 90), ("승인번호 · 사업자번호", 190), ("첨부", 48)]
SCH_COLUMNS = [("상태", 104), ("No", 44), ("이름", 92), ("학번", 104), ("청구액", 92), ("개별 적요", 300), ("첨부", 56), ("확인할 것", None)]
# 첨부만 다시 올리기(claims/reattach.py) — 청구내역 줄마다 한 줄
REATTACH_COLUMNS = [("상태", 96), ("줄", 44), ("이름 · 폴더", 150), ("적요", 280), ("파일", 48), ("지움", 48), ("올림", 48), ("확인할 것", None)]
# ② 오른쪽 칸 위 '할 일' — 폴더마다 새 청구서에 넣을지, ERP 에 이미 있는 청구서(임시저장 · 보완요청)의 첨부만 다시 올릴지. ③ 의 큰 단추가 고른 것을 한다
# (담당자 2026-10-23 "첨부문서만 다시 넣는거면은 2단계에서 선택하게 하면 헷갈릴게 줄어들지 않을까" — 전에는 ③ 에 단추가 둘이라 [ERP 에 넣기] 를 눌러 중복 띠에 막혔다).
ACTION_FILL, ACTION_REATTACH = "fill", "reattach"
ACTIONS = [(ACTION_FILL, "새 청구서에 넣기"), (ACTION_REATTACH, "첨부만 다시 올리기 — ERP 에 있는 임시저장 · 보완요청 청구서에")]
REATTACH_STATUS = {"planned": ("할 것", "neutral"), "saved": ("저장", "success"), "skipped": ("건너뜀", "warning"), "failed": ("실패", "danger"),
                   "stopped": ("멈춤", "warning"), "waiting": ("대기", "neutral"), "erp": ("넣는 중", "info")}
SCH_STATUS = {"planned": ("넣을 것", "neutral"), "saved": ("임시저장", "success"), "review": ("저장·확인", "warning"),
              "present": ("이미 있음", "neutral"), "stopped": ("멈춤", "warning"),
              "failed": ("실패", "danger"), "waiting": ("대기", "neutral")}


def reattach_rows(report) -> list[ReportRow]:
    """첨부만 다시 올리기 — 결과(RowResult)마다 표 한 줄. 파일 목록 · 진행 단계는 '자세히' 칸으로."""
    rows = []
    plan = report.plan
    base = plan.folder if plan is not None else ""
    for r in report.results:
        status, tone = REATTACH_STATUS.get(r.status, (r.status, "neutral"))
        if r.status == "saved" and r.review:
            status, tone = "저장·확인", "warning"
        if r.status == "planned" and r.note:
            status, tone = "확인 필요", "warning"
        summary = next((p.summary for p in (plan.rows if plan is not None else []) if p.index == r.index and p.label == r.label), "")
        detail = [f"{r.label}" + (f"  ·  청구내역 {r.sheet_row + 1}번째 줄" if r.sheet_row >= 0 else ""), f"적요: {summary or '—'}",
                  f"붙일 파일 {len(r.files)}개:"]
        for path in r.files:
            detail.append("  " + (os.path.relpath(path, base) if base else os.path.basename(path)))
        for item in r.review:
            detail.append(f"신청 전 확인: {item}")
        if r.note and not r.review:
            detail.append(f"확인할 것: {r.note}")
        if r.detail:
            detail.append("진행:")
            detail.extend("  " + line for line in r.detail)
        rows.append(ReportRow(status, tone, [str(r.sheet_row + 1) if r.sheet_row >= 0 else "—", r.label, summary, f"{len(r.files)}개",
                                             f"{r.removed}개" if r.status == "saved" else "—", f"{r.uploaded}개" if r.status == "saved" else "—",
                                             " / ".join(r.review) or r.note],
                              detail="\n".join(detail), tips={2: summary}, right=(3, 4, 5)))
    return rows


def sheet_check_rows(check) -> list[ReportRow]:
    """신청 전 대조의 줄(사람마다 · 합계) — '✓ …' 맞음, '! …' 확인(두 번 · 금액 다름), '· …' 청구내역에 없음."""
    rows = []
    for line in check.lines:
        mark, _, text = line.partition(" ")
        status, tone = {"✓": ("맞음", "success"), "!": ("확인", "warning")}.get(mark, ("없음", "neutral"))
        rows.append(ReportRow(status, tone, [text], tips={0: text}))
    return rows


def scholarship_rows(job, results) -> list[ReportRow]:
    """결과(PersonResult)마다 표 한 줄. 긴 값(첨부 목록 · 진행 단계)은 '자세히' 칸으로."""
    rows = []
    for r in results:
        status, tone = SCH_STATUS.get(r.status, (r.status, "neutral"))
        if r.status == "planned" and r.note:
            status, tone = "확인 필요", "warning"
        if r.status == "saved" and r.review:
            status, tone = SCH_STATUS["review"]
        main = job.main_summary if job is not None else ""
        # 줄마다 앞의 대표적요는 같다 — 줄을 가르는 뒷부분(_이름 · (이름_교과목))이 보이게 앞을 줄인다
        shown = "…" + r.summary[len(main):] if main and r.summary.startswith(main) and r.summary != main else r.summary
        personal = len(r.files) - r.common_count
        base = job.folder if job is not None else ""
        detail = [f"{r.index + 1}. {r.name}  ·  학번 {r.student_no or '—'}" + (f"  ·  교과목 {r.course}" if r.course else "")
                  + f"  ·  청구액 {_money(r.amount) or '—'}원",
                  f"개별 적요: {r.summary}",
                  f"첨부 {len(r.files)}개 (공통 {r.common_count} · 개별 {personal})"]
        for i, path in enumerate(r.files):
            name = os.path.relpath(path, base) if base else os.path.basename(path)
            detail.append(f"  [{'공통' if i < r.common_count else '개별'}] {name}")
        for item in r.review:
            detail.append(f"신청 전 확인: {item}")
        if r.note and not r.review:
            detail.append(f"확인할 것: {r.note}")
        if r.status != "planned" and r.lines:
            detail.append("진행:")
            detail.extend("  " + line for line in r.lines)
        rows.append(ReportRow(status, tone, [str(r.index + 1), r.name, r.student_no or "—", _money(r.amount) or "—",
                                             shown, f"{len(r.files)}개", " / ".join(r.review) or r.note],
                              detail="\n".join(detail), tips={4: r.summary}, right=(3, 5)))
    return rows


class ClaimPage(QWidget):
    busy_changed = Signal(bool)
    need_settings = Signal()        # [설정에서 바꾸기] — AI 플랫폼은 설정에서 고른다
    attention = Signal()            # 노란 띠에서 사람을 기다림 — 다른 탭에 있으면 이 화면으로(app._wire)

    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self.extractor = ClaimExtractWorker()
        self.browser = worker if worker is not None else SessionWorker()
        self._owns_browser = worker is None
        self._dirs: list[str] = []
        self._status: list[str] = []
        self._data: list[dict] = []
        self._problems: list[list[str]] = []
        self._kinds: list[str] = []                      # 폴더마다 청구 종류 (kinds.GENERAL · SCHOLARSHIP)
        self._jobs: list[sch.Job | None] = []            # 장학금 폴더의 명단 · 증빙
        self._cards: list[card_mod.CardJob | None] = []  # 카드 결제 기간 폴더 — 비목마다 청구서 · 결제 건
        self._projects: list[str] = []                   # 폴더마다 ERP 과제번호 — 폴더를 넣을 때 고른다(담당자 2026-10-19)
        self._actions: list[str] = []                    # 폴더마다 할 일(ACTION_FILL · ACTION_REATTACH) — ② 오른쪽 칸 위에서 고른다
        self._running = False
        self._erp_running = False                        # 장학금을 ERP 에 넣는 중 (브라우저 스레드)
        self._stopping = False
        self._erp_row = -1
        self._erp_sheet = 0                              # 카드: 넣는 중인 청구서(비목) 번호
        self._browser_busy = False
        self._reattach_pending = -1     # 중복 확인 띠에서 [첨부만 다시 올리기] 를 누른 줄 — 넣기가 멈추면 그 폴더로 첨부만 다시 올린다
        self._browser_open = False
        self._available: bool | None = None
        self._backend_state = ""
        self._backend_key = ai.chosen("claim")
        self._done_count = 0
        self._current = -1
        self._loading_form = False

        self._guide = GUIDE_START
        self._guide_where = ""                           # 안내를 둘 단계 — 비면 지금 단계(읽기 안내는 ② 에)
        self._backend_note = ""                          # 일반 폴더를 읽을 AI 를 쓸 수 없을 때 ② 아래 한 줄
        self._folders_open = False                       # 폴더를 넣은 뒤 ② 를 다시 편 것([폴더 더 넣기])
        self._kind_picked = False                        # ① 에서 청구 종류를 골랐는지 — 화면은 ① 부터 연다(2026-10-26)
        self._kind_open = False                          # 폴더를 넣은 뒤 ① 을 다시 편 것([바꾸기] — 다른 종류의 폴더를 더 넣으려고)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 26)
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        layout.addWidget(self._build_ask_banner())       # 사람 차례 — 단계가 스크롤돼도 늘 보이게 단계 밖 위쪽에
        # 단계 — 할 차례인 것만 보인다(ui/flow.py, 담당자 요청 2026-10-21)
        self.step_kind = self._build_kind()
        self.step_add = self._build_add()
        self.step_check = self._build_check()
        self.step_put = self._build_put()
        self.steps = {"kind": self.step_kind, "add": self.step_add, "check": self.step_check, "put": self.step_put}
        self.area = FlowArea()
        self.area.add(self.step_kind)
        self.area.add(self.step_add)
        self.area.add(self.step_check, 1)
        self.area.add(self.step_put)
        self.area.add(self._build_log(), 1)
        layout.addWidget(self.area, 1)

        e = self.extractor
        e.log.connect(self._append_log)
        e.busy.connect(self._on_extract_busy)
        e.started.connect(self._on_started)
        e.done.connect(self._on_done)
        e.skipped.connect(self._on_skipped)
        e.stopped.connect(self._on_stopped)
        e.finished.connect(self._on_finished)
        e.error.connect(self._on_extract_error)
        b = self.browser
        b.log.connect(self._append_log)
        b.busy.connect(self._on_browser_busy)
        b.browser_opened.connect(self._on_browser_opened)
        b.browser_state.connect(self._on_browser_state)
        b.claim_filled.connect(self._on_claim_filled)
        b.claim_saved.connect(self._on_claim_saved)
        b.payee_searched.connect(self._on_payee_searched)
        b.taxbill_searched.connect(self._on_taxbill_searched)
        b.scholarship_person.connect(self._on_sch_person)
        b.scholarship_ask.connect(self._on_sch_ask)
        b.scholarship_done.connect(self._on_sch_done)
        b.sheet_checked.connect(self._on_sheet_checked)
        b.card_item.connect(self._on_card_item)
        b.card_done.connect(self._on_card_done)
        b.taxbill_item.connect(self._on_taxbill_item)
        b.taxbill_run_done.connect(self._on_taxbill_run_done)
        b.reattach_row.connect(self._on_reattach_row)
        b.reattach_done.connect(self._on_reattach_done)
        b.projects_read.connect(self._refresh_projects)
        b.failed.connect(self._on_browser_failed)
        b.sites_changed.connect(lambda _sites: self._sync_put_state())

        self._show_form(-1)
        self._on_platform(self.platform.status())

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        """머리 — 그림 · 제목 · 한 줄 설명 / 오른쪽에 지금 상태 · 진행 수 · [멈추기] · [진행 기록] · [도구].
        [멈추기] 는 읽는 중이든 ERP 에 넣는 중이든 늘 보이는 자리에 둔다(단계는 스크롤될 수 있다)."""
        head = QHBoxLayout()
        head.setSpacing(10)
        self.head_art = Art("claim", 52)
        head.addWidget(self.head_art, 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = self.head_title = QLabel("일반청구")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        self.page_desc = muted_label(
            "지출 폴더마다 청구 종류(일반 · 장학금 …)를 고르면 ERP 일반청구 작성 화면에 채우고 임시저장까지 합니다. "
            "[신청] 은 직접 합니다. 일반 폴더의 자료는 선택한 AI 플랫폼으로 전송됩니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        self.state_pill = Pill("준비", "neutral")
        head.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        self.progress_label = muted_label("")
        head.addWidget(self.progress_label, 0, Qt.AlignVCenter)
        self.stop_button = QPushButton("멈추기")
        self.stop_button.setObjectName("danger")
        self.stop_button.clicked.connect(self._stop)
        head.addWidget(self.stop_button, 0, Qt.AlignVCenter)
        self.log_button = QPushButton("진행 기록")
        self.log_button.setObjectName("ghost")
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("앱이 한 일을 차례로 적은 기록을 아래에 펼칩니다")
        self.log_button.toggled.connect(self._toggle_log)
        head.addWidget(self.log_button, 0, Qt.AlignVCenter)
        head.addWidget(LogSendButton("일반청구"), 0, Qt.AlignVCenter)
        tools = QPushButton("도구")
        tools.setObjectName("ghost")
        menu = QMenu(tools)
        rules_action = menu.addAction("규칙 파일 열기", self._open_rules)
        rules_action.setToolTip("폴더에서 무엇을 어떻게 뽑을지 적은 규칙. 저장만 하면 다음 읽기부터 반영됩니다.")
        menu.setToolTipsVisible(True)
        menu.addAction("로그 파일 열기", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.log_path()))))
        tools.setMenu(menu)
        head.addWidget(tools, 0, Qt.AlignVCenter)
        return head

    def _build_ask_banner(self) -> QFrame:
        """장학금을 넣다가 앱이 확신하지 못하는 단계 — 사람이 ERP 에서 하고 [계속]."""
        self.ask_banner = QFrame()
        self.ask_banner.setObjectName("banner")
        row = QHBoxLayout(self.ask_banner)
        row.setContentsMargins(16, 10, 10, 10)
        row.setSpacing(10)
        row.addWidget(Pill("확인 필요", "warning"), 0, Qt.AlignVCenter)
        self.ask_text = WrapLabel("")
        self.ask_text.setObjectName("bannerText")
        row.addWidget(self.ask_text, 1)
        # 넣기 전 중복 확인에서 보완요청 · 임시저장 청구서가 나왔을 때만 보이는 셋째 단추 — 새로 넣지 않고 그 청구서의 첨부만 다시 올린다
        # (담당자 2026-10-23: 보완요청이 와서 첨부만 바꾸려는데 이 띠의 '지운 뒤 다시' 안내에 막혔다)
        self.reattach_now_button = QPushButton("첨부만 다시 올리기")
        self.reattach_now_button.setObjectName("primary")
        self.reattach_now_button.setToolTip("ERP 에 이미 있는 그 청구서(보완요청 · 임시저장)의 청구내역 줄마다 첨부문서를 모두 지우고 폴더의 지금 파일을 다시 올려 "
                                            "[저장] 합니다.\n값은 넣지 않습니다. [신청] 은 직접 합니다.")
        self.reattach_now_button.clicked.connect(self._answer_reattach)
        self.reattach_now_button.hide()
        self.continue_button = QPushButton("ERP 에서 했어요 · 계속")
        self.continue_button.setObjectName("primary")
        self.continue_button.clicked.connect(lambda: self._answer(True))
        self.halt_button = QPushButton("여기서 멈추기")
        self.halt_button.clicked.connect(lambda: self._answer(False))
        row.addWidget(self.reattach_now_button)
        row.addWidget(self.continue_button)
        row.addWidget(self.halt_button)
        self.ask_banner.hide()
        return self.ask_banner

    @staticmethod
    def _kind_box(with_auto: bool) -> QComboBox:
        """청구 종류 고르기 칸 — 준비 중인 종류는 보이되 고를 수 없다."""
        box = QComboBox()
        if with_auto:
            box.addItem("자동 (폴더 모양으로)", kinds.AUTO)
        for kind in kinds.KINDS:
            box.addItem(kind.name if kind.ready else f"{kind.name} (준비 중)", kind.key)
            index = box.count() - 1
            box.setItemData(index, kind.hint, Qt.ToolTipRole)
            if not kind.ready:
                box.model().item(index).setEnabled(False)
        return box

    # 과제 칸은 받기 화면과 같이 쓴다(ui/project_box.py)
    _project_box = staticmethod(project_box.project_box)
    _last_project = staticmethod(project_box.last_project)
    _fill_project_box = staticmethod(project_box.fill_project_box)

    def _refresh_projects(self) -> None:
        """로그인 뒤 과제현황을 새로 읽었으면(worker.projects_read) 고르기 칸 둘을 다시 채운다 — 폴더에 붙은 과제는 그대로."""
        self._fill_project_box(self.add_project, str(self.add_project.currentData() or self._last_project()))
        self._show_row_project(self._current)

    def _show_row_project(self, row: int) -> None:
        shown = 0 <= row < len(self._projects)
        if shown:
            self._fill_project_box(self.row_project, self._projects[row])
        self.row_project.setVisible(shown)
        self._project_label.setVisible(shown)

    def _add_project_changed(self, _index: int) -> None:
        no = str(self.add_project.currentData() or "")
        self.add_project.setToolTip("ERP 과제: " + navigate.label_of(no))
        if no and no != self._last_project():
            settings.update(project_no=no)          # 마지막으로 고른 과제 — 로그인 뒤 그 과제의 청구서 화면으로 간다

    def _show_row_action(self, row: int) -> None:
        shown = 0 <= row < len(self._actions) and self._kind(row) != kinds.CARD
        if shown:
            self.row_action.blockSignals(True)
            self.row_action.setCurrentIndex(max(self.row_action.findData(self._actions[row]), 0))
            self.row_action.blockSignals(False)
        self.row_action.setVisible(shown)
        self._action_label.setVisible(shown)

    def _row_action_changed(self, _index: int) -> None:
        row = self._current
        action = str(self.row_action.currentData() or ACTION_FILL)
        if self._loading_form or not (0 <= row < len(self._actions)) or self.is_running() or action == self._actions[row]:
            return
        self._actions[row] = action
        self._append_log(f"'{os.path.basename(self._dirs[row])}' 할 일: {dict(ACTIONS)[action]}")
        self._show_form(row)              # 안내 글 · ③ 제목이 할 일을 따른다
        self._sync_buttons()

    def _row_project_changed(self, _index: int) -> None:
        row = self._current
        no = str(self.row_project.currentData() or "")
        if self._loading_form or not no or not (0 <= row < len(self._projects)) or self.is_running():
            return
        self._projects[row] = no
        self.row_project.setToolTip("ERP 과제: " + navigate.label_of(no))
        if no != self._last_project():
            settings.update(project_no=no)
        self._refresh_row(row)

    def _build_kind(self) -> FlowStep:
        """① 청구 종류 — 카드를 누르면 접히고 ② 가 떠오른다(담당자 2026-10-26 "1단계에서 청구종류를 선택할 수 있도록").
        전에는 ① 의 폴더 칸 옆 작은 고르기 칸이라 눈에 띄지 않아, 종류를 모른 채 폴더를 넣었다. 고른 값은 숨은 고르기 칸(add_kind)에 두어
        폴더를 넣는 코드(add_folder)는 그대로 쓴다. 준비 중인 종류는 카드가 보이되 누를 수 없다."""
        step = FlowStep("1", "청구 종류를 고르세요", "이번에 넣을 지출 폴더가 어떤 청구인지 고르세요. 모르면 '자동' — 폴더 모양과 이름으로 정합니다.")
        step.edit.connect(self._open_kinds)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.kind_cards: dict[str, ChoiceCard] = {}
        options = [(kinds.AUTO, "자동", "폴더 모양 · 이름으로 정합니다(명단 엑셀 · 결제 기간 · 세금계산서 파일)", "archive", True, "")]
        options += [(k.key, k.name, k.brief or k.hint, k.art, k.ready, k.hint) for k in kinds.KINDS]
        columns = 4
        for i, (key, name, brief, art, ready, hint) in enumerate(options):
            card = ChoiceCard(key, name, brief, art, pill=not ready)
            if hint:
                card.setToolTip(hint)
            if not ready:
                card.state.set_status("준비 중", "neutral")
                card.setEnabled(False)
            card.chosen.connect(self._choose_kind)
            self.kind_cards[key] = card
            grid.addWidget(card, i // columns, i % columns)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        step.add_layout(grid)
        return step

    def _build_add(self) -> FlowStep:
        """② 지출 폴더 넣기 — 과제를 고르고 폴더를 넣는다. 넣으면 '지출 N건' 으로 접히고 [폴더 더 넣기] 로 편다."""
        step = FlowStep("2", "지출 폴더를 넣으세요", edit_text="폴더 더 넣기")    # 안내는 아래 한 줄(GUIDE_ADD) — 같은 글을 두 번 보이지 않게
        step.edit.connect(self._open_folders)
        choose = QHBoxLayout()
        choose.setSpacing(10)
        # 청구 종류는 ① 의 카드로 고른다 — 이 칸은 보이지 않게 두고 고른 값만 담는다(add_folder · _sync_buttons 가 읽는다)
        self.add_kind = self._kind_box(with_auto=True)
        self.add_kind.setParent(step)
        self.add_kind.hide()
        # ERP 과제 — 폴더를 넣을 때 고른다(담당자 2026-10-19: 설정이 아니라 여기서). 보기는 메인화면 과제현황에서 읽은 과제 중
        # 과제기간에 오늘이 든 것만, 기본은 202408470003(navigate.choices). 마지막으로 고른 과제로 로그인 뒤 이동도 한다.
        project_label = QLabel("과제")
        project_label.setObjectName("fieldLabel")
        choose.addWidget(project_label, 0, Qt.AlignVCenter)
        self.add_project = self._project_box()
        self.add_project.currentIndexChanged.connect(self._add_project_changed)
        project_label.setBuddy(self.add_project)
        choose.addWidget(self.add_project, 0, Qt.AlignVCenter)
        self._fill_project_box(self.add_project, self._last_project())
        choose.addStretch(1)
        step.add_layout(choose)
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        row = QHBoxLayout(self.drop_zone)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(12)
        self.drop_art = Art("archive", 52)
        row.addWidget(self.drop_art, 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        hint = QLabel("여기에 지출 폴더를 끌어다 놓으세요")
        hint.setObjectName("cardTitle")
        texts.addWidget(hint)
        detail = muted_label("상위 폴더를 넣으면 그 안의 하위 폴더마다 1건으로 봅니다.")
        detail.setWordWrap(True)
        texts.addWidget(detail)
        row.addLayout(texts, 1)
        self.add_one_button = QPushButton("지출 폴더 추가")
        self.add_one_button.setObjectName("primary")
        self.add_one_button.clicked.connect(self._add_one)
        self.add_parent_button = QPushButton("상위 폴더 추가")
        self.add_parent_button.clicked.connect(self._add_parent)
        for button in (self.add_one_button, self.add_parent_button):
            row.addWidget(button, 0, Qt.AlignVCenter)
        step.add(self.drop_zone)
        return step

    def _build_check(self) -> FlowStep:
        """② 내용 확인 — 지출 목록(왼쪽)에서 한 줄을 고르면 오른쪽에 그 청구의 값 · 명단 · 결제 건. 일반 폴더는 [내용 읽기](AI) 먼저."""
        step = FlowStep("3", "내용을 확인하세요", editable=False)
        self.clear_button = QPushButton("목록 비우기")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self._clear)
        step.add_side(self.clear_button)
        # 일반 폴더가 있을 때만 — AI 로 서류를 읽는다(장학금 · 카드 등은 앱이 바로 읽어 이 줄이 없다)
        self.ai_bar = QWidget()
        ai_row = QHBoxLayout(self.ai_bar)
        ai_row.setContentsMargins(0, 0, 0, 0)
        ai_row.setSpacing(10)
        self.read_button = QPushButton("내용 읽기")
        self.read_button.setObjectName("primary")
        self.read_button.clicked.connect(self._read_all)
        ai_row.addWidget(self.read_button, 0, Qt.AlignVCenter)
        self.platform = ai_status.PlatformRow("claim")
        self.platform.changed.connect(self._on_platform)
        self.platform.settings_requested.connect(self.need_settings.emit)
        ai_row.addWidget(self.platform, 1)
        step.add(self.ai_bar)
        middle = QWidget()
        row = QHBoxLayout(middle)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(self._build_list_card(), 3)
        row.addWidget(self._build_form_card(), 2)
        self.middle = row
        step.add(middle, 1)
        return step

    def _set_wide_form(self, wide: bool) -> None:
        """장학금은 오른쪽 학생 표가 넓어야 해서 왼쪽 목록과 폭을 바꾼다."""
        self.middle.setStretch(0, 2 if wide else 3)
        self.middle.setStretch(1, 3 if wide else 2)

    def _build_list_card(self) -> QWidget:
        card = Card("지출 목록", margins=(16, 14, 16, 12))
        card.setToolTip("한 줄을 고르면 오른쪽에 그 청구의 내용이 보입니다")
        card.add(self._build_table(), 1)
        return card

    def _build_log(self) -> QWidget:
        """진행 기록 — 머리의 [진행 기록] 을 눌렀을 때만 아래에 펼친다."""
        self.log_card = Card(margins=(16, 10, 16, 12))
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("foldLog")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(3000)
        self.log_card.add(self.log_view, 1)
        self.log_card.hide()
        return self.log_card

    def _toggle_log(self, on: bool) -> None:
        self.log_card.setVisible(on)
        self._sync_flow()
        if on:
            self.area.show_to(self.log_card)

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([name for name, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setSortingEnabled(False)
        self.table.setItemDelegateForColumn(COL_STATUS, PillDelegate(self.table))
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        # 창이 낮아도 지출 몇 줄은 보이게 — 픽셀이 아니라 줄 높이로(넘치면 단계 칸이 스크롤된다)
        self.table.setMinimumHeight(self.table.verticalHeader().defaultSectionSize() * 3
                                    + self.table.horizontalHeader().sizeHint().height())
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setStretchLastSection(True)
        head.setHighlightSections(False)
        for col, (_, width) in enumerate(COLUMNS):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            if width:
                self.table.setColumnWidth(col, width)
        return self.table

    def _build_form_card(self) -> QWidget:
        card = Card("청구 내용", "읽은 값입니다. 틀린 곳은 여기서 고치세요 — ERP 에는 이 값이 들어갑니다.",
                    margins=(16, 14, 16, 12))
        # 고른 폴더의 청구 종류 · ERP 과제 — 넣은 뒤에도 여기서 바꾼다(바꾸면 아래 칸이 그 종류의 칸으로).
        # 머리 줄 오른쪽에 두면 설명 글이 좁은 칸에 여러 줄로 접혀 칸이 길어졌다 — 설명 아래 한 줄로.
        choose = QHBoxLayout()
        choose.setSpacing(8)
        kind_label = QLabel("종류")
        kind_label.setObjectName("fieldLabel")
        choose.addWidget(kind_label, 0, Qt.AlignVCenter)
        self.row_kind = self._kind_box(with_auto=False)
        self.row_kind.setToolTip("이 지출 폴더의 청구 종류")
        self.row_kind.currentIndexChanged.connect(self._row_kind_changed)
        kind_label.setBuddy(self.row_kind)
        choose.addWidget(self.row_kind, 0, Qt.AlignVCenter)
        choose.addStretch(1)
        card.add_layout(choose)
        # 할 일 — 새 청구서에 넣기 / 첨부만 다시 올리기. 보기 글이 길어 종류 줄에 같이 두면 좁은 오른쪽 칸(일반 줄은 2/5)에서 잘린다 — 줄 하나를 따로
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_label = QLabel("할 일")
        action_label.setObjectName("fieldLabel")
        action_row.addWidget(action_label, 0, Qt.AlignVCenter)
        self.row_action = QComboBox()
        for key, name in ACTIONS:
            self.row_action.addItem(name, key)
        self.row_action.setItemData(0, "그 과제의 결의서내역에 같은 청구서가 없는지 보고 새 청구서 작성 화면에 넣어 [저장] 합니다.", Qt.ToolTipRole)
        self.row_action.setItemData(1, "ERP 에 이미 있는 이 폴더의 청구서(임시저장 · 보완요청)를 결의서내역에서 찾아 열고, 청구내역 줄마다 첨부문서를 모두 지운 뒤\n"
                                       "폴더의 지금 파일을 다시 올려 [저장] 합니다. 청구내역 값은 넣지 않습니다. [신청] 은 직접.", Qt.ToolTipRole)
        self.row_action.setToolTip("이 폴더로 ④ 에서 할 일 — 보완요청 · 임시저장 청구서의 첨부문서만 바꾸려면 '첨부만 다시 올리기'")
        self.row_action.currentIndexChanged.connect(self._row_action_changed)
        action_label.setBuddy(self.row_action)
        action_row.addWidget(self.row_action, 0, Qt.AlignVCenter)
        action_row.addStretch(1)
        card.add_layout(action_row)
        self._action_label = action_label
        # 과제는 이름이 길다 — 줄 하나를 다 쓰게 따로 둔다(한 줄에 두면 좁은 오른쪽 칸에서 과제명이 잘렸다, 담당자 2026-10-21)
        project_row = QHBoxLayout()
        project_row.setSpacing(8)
        project_label = QLabel("과제")
        project_label.setObjectName("fieldLabel")
        project_row.addWidget(project_label, 0, Qt.AlignVCenter)
        self.row_project = self._project_box()
        self.row_project.currentIndexChanged.connect(self._row_project_changed)
        project_label.setBuddy(self.row_project)
        project_row.addWidget(self.row_project, 1, Qt.AlignVCenter)
        card.add_layout(project_row)
        self._project_label = project_label
        self.form_stack = QStackedWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("pageBody")
        scroll.setWidget(body)
        form = QVBoxLayout(body)
        form.setContentsMargins(0, 0, 8, 0)
        form.setSpacing(10)
        self.inputs: dict[str, QWidget] = {}

        def line(key: str, label: str, help_text: str = "", placeholder: str = "") -> None:
            edit = QLineEdit()
            edit.setPlaceholderText(placeholder)
            edit.editingFinished.connect(lambda k=key: self._form_changed(k))
            self.inputs[key] = edit
            form.addWidget(Field(label, edit, help_text))

        def combo(key: str, label: str, options, help_text: str = "") -> None:
            box = QComboBox()
            box.addItem("")
            for option in options:
                box.addItem(option)
            box.currentIndexChanged.connect(lambda _i, k=key: self._form_changed(k))
            self.inputs[key] = box
            form.addWidget(Field(label, box, help_text))

        line("summary", "적요", "ERP 적요 칸. 'NN_내용' 형식", "예: 09_2026년 사업단 정수기 임차료(9월)")
        combo("expCategory", "비목", schema.EXP_CATEGORIES)
        line("expDetail", "세목", "비목을 고르면 ERP 에 보기가 뜹니다. 그 이름을 적으세요")
        combo("evidence", "증빙구분", schema.EVIDENCE_KINDS)
        line("expenseDate", "지출일자", "세금계산서 작성일", "YYYY-MM-DD")
        combo("settleMethod", "결제방법", schema.SETTLE_METHODS)
        amounts = QHBoxLayout()
        amounts.setSpacing(8)
        for key, label in (("amount", "청구액"), ("supplyAmount", "공급가액"), ("taxAmount", "부가세")):
            edit = QLineEdit()
            edit.setPlaceholderText("숫자만")
            edit.editingFinished.connect(lambda k=key: self._form_changed(k))
            self.inputs[key] = edit
            amounts.addWidget(Field(label, edit))
        form.addLayout(amounts)
        line("payeeName", "입금처", "ERP 의 입금처 돋보기에서 이 이름으로 찾으세요 (아직 사람이 고릅니다)")
        line("payeeBizNo", "사업자등록번호", "", "000-00-00000")
        line("bank", "은행", "ERP 보기의 은행 이름 (예: 국민은행)")
        line("accountNo", "계좌번호")
        line("owner", "예금주")
        self.attachments_label = muted_label("")
        form.addWidget(Field("첨부 후보", self.attachments_label, "폴더 안 파일 — ERP 의 '첨부' 로 직접 올립니다"))
        self.notes_label = WrapLabel("")
        self.notes_label.setObjectName("body")
        form.addWidget(Field("확인 사항", self.notes_label))
        self.problems_label = WrapLabel("")
        self.problems_label.setObjectName("fieldError")
        form.addWidget(self.problems_label)
        form.addStretch(1)
        self.form_stack.addWidget(scroll)
        self.scholarship_panel = ScholarshipPanel()
        self.scholarship_panel.changed.connect(self._on_panel_changed)
        self.scholarship_panel.reload_requested.connect(self._reload_scholarship)
        # 낮은 창(720)에서는 칸 · 표 · 합계 줄이 다 안 들어간다 — 겹치지 않고 스크롤되게 감싼다
        self.scholarship_scroll = QScrollArea()
        self.scholarship_scroll.setWidgetResizable(True)
        self.scholarship_scroll.setFrameShape(QFrame.NoFrame)
        self.scholarship_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scholarship_scroll.setWidget(self.scholarship_panel)
        self.form_stack.addWidget(self.scholarship_scroll)
        self.card_panel = CardPanel()
        self.card_panel.reload_requested.connect(self._reload_card)
        self.card_panel.sheet_changed.connect(self._sync_buttons)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.NoFrame)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_scroll.setWidget(self.card_panel)
        self.form_stack.addWidget(self.card_scroll)
        card.add(self.form_stack, 1)
        self.form_card = card
        return card

    def _build_put(self) -> FlowStep:
        """③ ERP 에 넣기 — 고른 지출 하나. 브라우저(로그인은 사람) · 미리 보기/시험 · [미리 보기]/[ERP 에 넣기] ·
        넣은 뒤 할 것([청구내역 대조] · [세금계산서 찾기] · [입금처 찾기] · [임시저장]). [신청] 은 끝까지 사람."""
        step = FlowStep("4", "ERP 에 넣으세요", editable=False)
        self.browser_state = Pill("브라우저 닫힘", "neutral")
        step.add_side(self.browser_state)
        # 한 줄 — 왼쪽은 누를 단추(브라우저 · 넣기 · 넣은 뒤 할 것), 오른쪽은 넣는 방법(미리 보기만 · 시험 · 팝업 자동 선택).
        # 두 줄이면 1320×860 창에서 ③ 이 화면 아래로 밀려 스크롤해야 보였다.
        options = QHBoxLayout()
        options.setSpacing(14)
        self.dry_run = QCheckBox("미리 보기만")
        self.dry_run.setChecked(True)
        self.dry_run.setToolTip("체크돼 있으면 ERP 에 넣지 않고 무엇을 넣을지만 보여 줍니다. 풀면 실제로 채웁니다 (저장·신청은 그래도 직접).")
        self.dry_run.toggled.connect(lambda _c: self._sync_buttons())
        options.addWidget(self.dry_run)
        # 시험 — 이미 올린 폴더로 시험해 보려면 같은 대표적요가 ERP 에 이미 있다(담당자 요청 2026-10-19). 켜면 대표적요 앞에 [시험] 을
        # 붙여 진짜 청구서와 구분하고, 넣기 전 ERP 중복 확인과 앱 이력 남기기를 건너뛴다. 앱을 다시 켜면 꺼진다(남겨 두지 않는다).
        self.test_mode = QCheckBox("시험")
        self.test_mode.setToolTip("이미 올린 폴더로 시험할 때 켭니다. 대표적요(일반은 적요) 앞에 [시험] 을 붙여 넣고,\n"
                                  "ERP 결의서내역의 같은 청구서 확인과 앱의 넣은 기록 남기기를 건너뜁니다.\n"
                                  "시험으로 임시저장한 청구서는 ERP 에서 직접 지우세요. 앱을 다시 켜면 꺼집니다.")
        self.test_mode.toggled.connect(lambda _c: self._sync_buttons())
        options.addWidget(self.test_mode)
        # 팝업(세금계산서·입금처)에서 결과가 하나로 확실하면 앱이 골라 [확인] 까지 — 애매하면 사람 (담당자 결정 2026-10-13)
        self.auto_pick = QCheckBox("팝업 자동 선택")
        self.auto_pick.setChecked(bool(settings.load().claim_auto_pick))
        self.auto_pick.setToolTip("세금계산서·입금처 팝업에서 사업자번호·금액이 맞는 결과가 하나뿐이면 앱이 고르고 [확인] 까지 누릅니다.\n"
                                  "여러 개이거나 정보가 모자라면 고르지 않고 두므로 직접 고르세요.")
        self.auto_pick.toggled.connect(lambda on: settings.update(claim_auto_pick=bool(on)))
        options.addWidget(self.auto_pick)
        self.fill_button = QPushButton("ERP 에 채우기")
        self.fill_button.setObjectName("primary")
        self.fill_button.clicked.connect(self._fill)
        # 명단 줄 — [신청] 전에 ERP 청구내역 표를 다시 읽어 명단과 맞춰 본다(읽기만). 넣기를 마치면 저절로도 한 번 한다.
        self.sheet_button = QPushButton("청구내역 대조")
        self.sheet_button.setToolTip("ERP 작성 화면의 청구내역 표를 읽어 명단과 맞춰 봅니다 — 두 번 들어간 사람 · 빠진 사람 · 다른 금액 ·\n"
                                     "명단에 없는 줄 · 합계와 공제합계. 읽기만 하고 아무것도 누르지 않습니다.")
        self.sheet_button.clicked.connect(self._check_sheet)
        # 채운 뒤 팝업을 닫아 버렸을 때 — 증빙 [선택] 팝업을 다시 열어 사업자번호로 조회해 둔다(고르기는 사람)
        self.taxbill_button = QPushButton("세금계산서 찾기")
        self.taxbill_button.setToolTip("증빙 [선택] 팝업을 열어 거래처 사업자번호로 조회해 둡니다. 계산서를 고르고 [확인] 은 직접 누르세요.")
        self.taxbill_button.clicked.connect(self._search_taxbill)
        # 채운 뒤 입금처 팝업을 닫아 버렸을 때 — 돋보기를 다시 눌러 거래처를 검색해 둔다(고르기는 사람)
        self.payee_button = QPushButton("입금처 찾기")
        self.payee_button.setToolTip("입금처 돋보기 팝업을 열어 거래처 이름으로 검색해 둡니다. 목록에서 고르고 [확인] 은 직접 누르세요.")
        self.payee_button.clicked.connect(self._search_payee)
        # 채운 뒤 사람이 입금처·첨부를 넣으면 — 앱이 ERP 의 [저장](임시저장)을 누른다. [신청] 은 끝까지 사람.
        self.save_button = QPushButton("임시저장")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("ERP 의 [저장] 을 눌러 임시저장합니다. [신청] 은 검토 후 직접 누르세요.")
        self.save_button.clicked.connect(self._save_draft)
        # 첨부만 다시 올리기(임시저장 · 보완요청 청구서, 담당자 2026-10-23)는 따로 단추가 아니라 ② 의 '할 일' 로 고르고 fill_button 이 한다(_fill → _reattach)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.setToolTip("앱이 연 브라우저에서 ERP 에 로그인하세요 — 결의서내역 · 새 청구서 화면은 앱이 띄웁니다")
        self.open_button.clicked.connect(lambda: self.browser.open_browser(scan=False, owner="claim"))
        row.addWidget(self.open_button)
        for button in (self.fill_button, self.sheet_button, self.taxbill_button, self.payee_button, self.save_button):
            row.addWidget(button)
        row.addStretch(1)
        row.addLayout(options)
        step.add_layout(row)
        return step

    # ── 상태 ────────────────────────────────────────────────────────────
    def _kind(self, row: int) -> str:
        return self._kinds[row] if 0 <= row < len(self._kinds) else kinds.GENERAL

    def _action(self, row: int) -> str:
        return self._actions[row] if 0 <= row < len(self._actions) else ACTION_FILL

    def _reattaching(self, row: int) -> bool:
        """그 줄의 할 일이 '첨부만 다시 올리기' 이고 할 수 있는 상태(카드가 아니고 폴더를 읽어 둠)인지."""
        return self._action(row) == ACTION_REATTACH and self._reattach_possible(row)

    def _unread_rows(self) -> list[int]:
        """AI 로 읽을 폴더 — 일반 · 세금계산서 종류만. 장학금은 넣을 때 명단을 바로 읽는다."""
        return [i for i, st in enumerate(self._status)
                if kinds.uses_ai(self._kinds[i]) and st in ("waiting", "failed", "skipped", "stopped")]

    def _sync_buttons(self) -> None:
        running = self._running
        busy = running or self._erp_running
        can_edit = not busy
        for widget in (self.add_one_button, self.add_parent_button, self.add_kind, self.add_project):
            widget.setEnabled(can_edit)
        for key, card in self.kind_cards.items():
            card.setEnabled(can_edit and (key == kinds.AUTO or kinds.find(key).ready))
        self.platform.set_enabled_for_run(not running)
        self.clear_button.setEnabled(can_edit and bool(self._dirs))
        self.table.setEnabled(not self._erp_running)          # 넣는 중에는 다른 줄로 옮기지 않게
        unread = self._unread_rows()
        self.read_button.setEnabled(can_edit and bool(unread) and self._available is True)
        self.read_button.setVisible(running or bool(unread))      # 읽을 것이 없으면 AI 줄은 상태만
        self.read_button.setText("읽는 중…" if running else f"{len(unread)}건 내용 읽기" if unread else "내용 읽기")
        if not busy:
            self._stopping = False
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(busy and not self._stopping)      # 한 번 멈춘 뒤 다음 작업에서 다시 눌리게
        self.open_button.setVisible(not self._browser_open)
        self.open_button.setEnabled(not self._browser_busy)
        self.row_kind.setEnabled(can_edit and 0 <= self._current < len(self._dirs))
        self.row_project.setEnabled(can_edit and not self._browser_busy and 0 <= self._current < len(self._dirs))
        self.row_action.setEnabled(can_edit and 0 <= self._current < len(self._dirs))
        dry = self.dry_run.isChecked()
        is_sch = kinds.uses_roster(self._kind(self._current)) and 0 <= self._current < len(self._dirs)
        is_card = self._kind(self._current) == kinds.CARD and 0 <= self._current < len(self._dirs)
        reattach = self._reattaching(self._current)
        if reattach:
            # ② 의 할 일이 '첨부만 다시 올리기' — 큰 단추가 그것을 한다(_fill → _reattach). 명단은 체크한 사람 수, 일반 · 세금계산서는 한 줄.
            # 미리 보기는 브라우저 없이 표만. 카드 줄은 아직 할 수 없다(결제 건마다 증빙 창이 다르다 — 할 일 칸 자체를 숨긴다)
            job = self._jobs[self._current] if self._current < len(self._jobs) else None
            count = job.count_text() if job is not None else "1줄"
            can = (job is None or bool(job.chosen())) and not busy and not self._browser_busy and (dry or self._browser_open)
            self.fill_button.setEnabled(can)
            self.fill_button.setText(f"미리 보기 (첨부 · {count})" if dry else f"첨부만 다시 올리기 ({count})")
            self.fill_button.setToolTip("ERP 에 있는 이 폴더의 청구서(임시저장 · 보완요청)를 찾아 열고 줄마다 첨부문서를 지운 뒤 폴더의 지금 파일을 올려 [저장] 합니다."
                                        if dry or self._browser_open else "먼저 [브라우저 열기] 로 ERP 를 열고 로그인하세요. 그 청구서는 앱이 결의서내역에서 엽니다.")
            self.sheet_button.setEnabled(job is not None and self._browser_open and not busy and not self._browser_busy)
        elif is_card:
            # 미리 보기는 브라우저 없이. 넣기는 고른 청구서(비목) 하나의 남은 결제 건 — 카드청구 화면은 앱이 [카드청구](#P11)로 띄운다(session.fill_card)
            job = self._cards[self._current]
            index = self.card_panel.chosen_sheet() if job is not None else -1
            sheet = job.sheets[index] if job is not None and index >= 0 else None
            left = [i for i in sheet.items if i.status != "saved"] if sheet else []
            if dry:
                self.fill_button.setEnabled(bool(left) and not busy)
                self.fill_button.setText(f"미리 보기 (결제 {len(left)}건)")
                self.fill_button.setToolTip("고른 청구서의 결제 건마다 ERP 에 넣을 값을 표로 봅니다. 브라우저는 필요 없습니다.")
            else:
                self.fill_button.setEnabled(bool(left) and not busy and not self._browser_busy and self._browser_open)
                self.fill_button.setText(f"ERP 에 넣기 (결제 {len(left)}건)")
                self.fill_button.setToolTip("" if self._browser_open else
                                            "먼저 [브라우저 열기] 로 ERP 를 열고 로그인하세요. 카드청구 화면은 앱이 띄웁니다.")
        elif is_sch:
            job = self._jobs[self._current]
            chosen = len(job.chosen()) if job is not None else 0
            self.fill_button.setEnabled(chosen > 0 and not busy and not self._browser_busy and (dry or self._browser_open))
            count = job.count_text() if job is not None else "0명"
            self.fill_button.setText(f"미리 보기 ({count})" if dry else f"ERP 에 넣기 ({count})")
            self.fill_button.setToolTip("" if dry or self._browser_open else "먼저 [브라우저 열기] 로 ERP 를 열고 새 청구서 화면을 띄우세요.")
            self.sheet_button.setEnabled(job is not None and self._browser_open and not busy and not self._browser_busy)
        elif self._kind(self._current) == kinds.TAXBILL and 0 <= self._current < len(self._dirs):
            # 세금계산서 — 읽은 세금계산서 폴더를 모두 하나씩 이어 넣는다(조회에 안 뜨면 건너뜀). 미리 보기는 브라우저 없이
            rows = self._taxbill_rows(self._current)
            self.fill_button.setEnabled(bool(rows) and not busy and not self._browser_busy and (dry or self._browser_open))
            self.fill_button.setText(f"미리 보기 (세금계산서 {len(rows)}건)" if dry else f"ERP 에 넣기 (세금계산서 {len(rows)}건)")
            self.fill_button.setToolTip("읽은 세금계산서 폴더를 하나씩 일반청구 탭에 넣고 [저장] 합니다 — 조회 팝업에 안 뜨는 폴더는 건너뜁니다."
                                        if dry or self._browser_open else "먼저 [브라우저 열기] 로 ERP 를 열고 로그인하세요. 새 청구서는 앱이 띄웁니다.")
        else:
            has_row = 0 <= self._current < len(self._dirs) and self._status[self._current] in ("read", "filled", "saved")
            self.fill_button.setEnabled(has_row and self._browser_open and not self._browser_busy and not busy)
            self.fill_button.setText("미리 보기" if dry else "ERP 에 채우기")
            self.fill_button.setToolTip("" if self._browser_open else
                                        "일반 줄은 미리 보기도 ERP 작성 화면을 봅니다 — 먼저 [브라우저 열기] 로 새 청구서 화면을 띄우세요.")
        self.sheet_button.setVisible(is_sch)
        # 채운 뒤의 단추들(입금처 · 세금계산서 · 임시저장)은 새 청구서에 넣을 때만 — 첨부만 다시 올리는 줄에는 뜻이 없다
        filled = (not is_sch and not reattach and self._kind(self._current) != kinds.TAXBILL and 0 <= self._current < len(self._dirs)
                  and self._status[self._current] in ("filled", "saved"))
        self.save_button.setVisible(filled)
        self.save_button.setEnabled(filled and self._browser_open and not self._browser_busy and not running)
        self.payee_button.setVisible(filled)
        self.payee_button.setEnabled(filled and self._browser_open and not self._browser_busy and not running)
        from ...claims import taxbill
        is_taxbill = filled and taxbill.wanted(self._data[self._current])
        self.taxbill_button.setVisible(is_taxbill)
        self.taxbill_button.setEnabled(is_taxbill and self._browser_open and not self._browser_busy and not running)
        # AI 로 읽는 것은 일반 폴더뿐 — 읽을 일반 폴더가 남았거나 일반 줄을 고른 때만(명단 · 카드 줄을 볼 때는 표에 자리를)
        self.ai_bar.setVisible(running or bool(unread) or kinds.uses_ai(self._kind(self._current)) and 0 <= self._current < len(self._dirs))
        self.progress_label.setVisible(busy and bool(self.progress_label.text()))
        self._sync_put_state()
        self._sync_flow()

    def _ready(self, row: int) -> bool:
        """그 줄을 ERP 에 넣을 차례인지 — 일반은 AI 로 읽은 뒤, 명단 · 카드는 폴더를 읽어 두었으면."""
        if not 0 <= row < len(self._dirs):
            return False
        kind = self._kind(row)
        if kind == kinds.CARD:
            return self._cards[row] is not None
        if kinds.uses_roster(kind):
            return self._jobs[row] is not None
        return self._status[row] not in ("waiting", "running", "failed", "skipped", "stopped")

    def _sync_flow(self) -> None:
        """할 차례인 단계만 — 폴더가 없으면 ① 만, 넣으면 ② 가(① 은 '지출 N건' 으로 접힘), 고른 줄을 넣을 수 있으면 ③ 이 떠오른다."""
        stage = claim_stage(bool(self._dirs), self._ready(self._current), self._kind_picked)
        keep = ("check",) + (("add",) if self._folders_open or self._kind_open else ()) + (("kind",) if self._kind_open else ())
        states = flow_states(CLAIM_ORDER, stage, keep_open=keep)
        where = self._guide_where if self._guide_where and states.get(self._guide_where) != HIDDEN else stage
        chosen = self.add_kind.currentData() or kinds.AUTO
        summaries = {"kind": "자동 (폴더 모양으로)" if chosen == kinds.AUTO else kinds.name_of(chosen), "add": f"지출 {len(self._dirs)}건"}
        for key, step in self.steps.items():
            step.set_state(states[key], summaries.get(key))
            note = self._guide if key == where else ""
            if key == "check" and self._backend_note and self.ai_bar.isVisibleTo(self):
                note = (self._backend_note + ("\n" + note if note else ""))
            step.set_note(note)
        if 0 <= self._current < len(self._dirs):
            # 제목에 고른 지출을 — 줄을 하나 더 쓰면 ② 의 표 · 칸이 그만큼 좁아진다
            name = os.path.basename(self._dirs[self._current])
            self.step_put.title.setText(f"{'첨부만 다시 올리세요' if self._reattaching(self._current) else 'ERP 에 넣으세요'} — {name}")
            project = self._projects[self._current] if self._current < len(self._projects) else ""
            self.step_put.title.setToolTip(f"{name} · {kinds.name_of(self._kind(self._current))}" + (f" · 과제 {project}" if project else ""))
        self.step_add.edit_button.setEnabled(not self.is_running())
        self.step_kind.edit_button.setEnabled(not self.is_running())
        for key, card in self.kind_cards.items():
            # [바꾸기] 로 다시 편 ① 에도 지금 고른 종류가 보이게 — 다시 고르지 않고 폴더를 넣으면 그 종류로 들어간다
            card.set_selected(key == chosen and (self._kind_picked or chosen != kinds.AUTO))
        self.clear_button.setVisible(bool(self._dirs))       # 단계가 오른쪽 것을 다시 보이게 하므로 그 뒤에
        self.stop_button.setVisible(self.is_running())
        self.area.filler.setVisible(states["check"] == HIDDEN and not self.log_card.isVisible())

    def _sync_put_state(self) -> None:
        """③ 오른쪽의 브라우저 상태 — 로그인은 사람이 한다."""
        sites = getattr(self.browser, "sites", {}) or {}
        if not self._browser_open:
            self.browser_state.set_status("브라우저 닫힘", "neutral")
        elif sites.get("erp_login"):
            self.browser_state.set_status("ERP 로그인됨", "success")
        else:
            self.browser_state.set_status("로그인 기다리는 중", "warning")

    def _open_folders(self) -> None:
        if self.is_running():
            return
        self._folders_open = True
        self._sync_flow()

    def _open_kinds(self) -> None:
        """① [바꾸기] — 폴더가 없으면 ① 로 돌아가고, 있으면 ① 을 펼쳐 다른 종류의 폴더를 더 넣게 한다(넣은 폴더의 종류는 ③ 오른쪽 칸에서)."""
        if self.is_running():
            return
        if self._dirs:
            self._kind_open = True
        else:
            self._kind_picked = False
        self._sync_flow()

    def _choose_kind(self, key: str) -> None:
        """① 의 카드 — 다음에 넣는 폴더의 청구 종류. 고르면 ① 이 접히고 ② (폴더 넣기)가 떠오른다."""
        if self.is_running():
            return
        index = self.add_kind.findData(key)
        if index < 0:
            return
        self.add_kind.setCurrentIndex(index)
        self._kind_picked = True
        self._kind_open = False
        if self._dirs:
            self._folders_open = True          # 폴더가 있으면 ② 를 펼친 채 — 고른 종류로 폴더를 더 넣는다
        self._set_guide(GUIDE_ADD)

    def _set_state(self, text: str, status: str, guide: str | None = None, where: str = "") -> None:
        """머리의 상태 배지 + 단계 아래 한 줄. where 가 비면 지금 단계에, 'check' 면 ② 에(AI 읽기 안내)."""
        self.state_pill.set_status(text, status)
        if guide is not None:
            self._set_guide(guide, where)

    def _set_guide(self, guide: str, where: str = "") -> None:
        self._guide = guide
        self._guide_where = where
        self._sync_flow()

    def _set_progress(self, done: int, total: int) -> None:
        self.progress_label.setText(f"{done} / {total}" if total else "")

    def _set_status(self, row: int, status: str) -> None:
        if row >= len(self._status):
            return
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self.table.setItem(row, COL_STATUS, item)

    def _refresh_row(self, row: int) -> None:
        data = self._data[row]
        job = self._jobs[row] if row < len(self._jobs) else None
        if job is not None:
            # 장학금 — 적요는 대표적요, 금액은 넣을 사람 합계, 입금처 칸에는 사람 수
            chosen = job.chosen()
            data = {"summary": job.main_summary or "(대표적요 없음)",
                    "amount": sum(job.people[i].amount or 0 for i in chosen),
                    "payeeName": ("학생 " if job.spec.payroll else "사람 ") + job.count_text(chosen)
                                 + (f" / 명단 {job.count_text(list(range(len(job.people))))}"
                                                                        if len(chosen) != len(job.people) else "")}
        cards = self._cards[row] if row < len(self._cards) else None
        if cards is not None:
            names = ", ".join(s.code for s in cards.sheets if s.code) or "비목 모름"
            data = {"summary": (f"카드 청구서 {len(cards.sheets)}개 ({names})" if len(cards.sheets) != 1 else
                                cards.sheets[0].main_summary or "(비목 모름)"),
                    "amount": cards.total, "payeeName": f"결제 {len(cards.items)}건"}
        kind_item = QTableWidgetItem(kinds.name_of(self._kind(row)))
        project = self._projects[row] if row < len(self._projects) else ""
        kind_item.setToolTip(kinds.name_of(self._kind(row)) + " — " + kinds.find(self._kind(row)).hint
                             + (f"\nERP 과제: {navigate.label_of(project)}" if project else ""))
        self.table.setItem(row, COL_KIND, kind_item)
        for col, value in ((COL_SUMMARY, data.get("summary", "")), (COL_AMOUNT, _money(data.get("amount"))),
                           (COL_PAYEE, data.get("payeeName", ""))):
            item = QTableWidgetItem(str(value))
            item.setToolTip(str(value))
            if col == COL_AMOUNT:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, col, item)

    def is_running(self) -> bool:
        return self._running or self._erp_running

    def resumable(self) -> tuple[bool, str]:
        if self._running:
            remaining = sum(1 for s in self._status if s in ("waiting", "running"))
            return True, f"읽는 중 · 남은 {remaining}건"
        if self._erp_running:
            return True, "명단 청구(장학금 등)를 ERP 에 넣는 중"
        return False, ""

    # ── 폴더 목록 ────────────────────────────────────────────────────────
    def add_folder(self, path: str, kind: str | None = None) -> bool:
        """폴더 하나를 목록에 넣는다. kind 를 안 주면 위의 '청구 종류' 칸(자동이면 폴더 모양)으로 정한다."""
        path = os.path.abspath(path)
        if not os.path.isdir(path) or path in self._dirs or self._running or self._erp_running:
            return False
        chosen = kind or self.add_kind.currentData() or kinds.AUTO
        try:
            kind = kinds.resolve(chosen, path)
        except ValueError as error:
            QMessageBox.information(self, "청구 종류", str(error))
            return False
        self._kind_picked = True
        self._kind_open = False
        if chosen == kinds.GENERAL and kind == kinds.PERSONAL:
            self._append_log(f"'{os.path.basename(path)}' — 지급내역 엑셀이 있어 개인 지급(기타)으로 넣습니다(표 위에서 바꿀 수 있습니다)")
        self._dirs.append(path)
        self._status.append("waiting")
        self._data.append(schema.normalize(kinds.fixed_values(kind)))      # 세금계산서 종류는 읽기 전에도 증빙구분이 보이게
        self._problems.append([])
        self._kinds.append(kind)
        self._jobs.append(None)
        self._cards.append(None)
        self._projects.append(str(self.add_project.currentData() or self._last_project()))
        self._actions.append(ACTION_FILL)
        row = self.table.rowCount()
        self.table.setRowCount(row + 1)
        name = QTableWidgetItem(f"{os.path.basename(path)}  ·  {os.path.dirname(path)}")
        name.setToolTip(path)
        self.table.setItem(row, COL_DIR, name)
        self._set_status(row, "waiting")
        if kinds.uses_roster(kind):
            self._load_scholarship(row)
        elif kind == kinds.CARD:
            self._load_card(row)
        self._refresh_row(row)
        self._set_progress(self._done_count, len(self._dirs))
        if self._current < 0:
            self.table.selectRow(row)
        self._sync_buttons()
        return True

    def _add_one(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "지출 자료가 들어 있는 폴더 선택")
        if path:
            self.add_folder(path)

    def _add_parent(self) -> None:
        parent = QFileDialog.getExistingDirectory(self, "여러 지출 폴더가 들어 있는 '상위' 폴더 선택")
        if not parent:
            return
        subs = [os.path.join(parent, x) for x in sorted(os.listdir(parent)) if os.path.isdir(os.path.join(parent, x))]
        if not subs:
            QMessageBox.information(self, "안내", "선택한 폴더 안에 하위 폴더가 없습니다.")
            return
        for sub in subs:
            self.add_folder(sub)

    def _clear(self) -> None:
        if self._running:
            return
        if self._erp_running:
            return
        self._dirs, self._status, self._data, self._problems = [], [], [], []
        self._kinds, self._jobs, self._cards, self._projects, self._actions = [], [], [], [], []
        self._current = -1
        self._done_count = 0
        self._folders_open = False
        self._kind_open = False                # 고른 청구 종류는 남긴다 — 같은 종류의 폴더를 다시 넣는 일이 많다
        self.table.setRowCount(0)
        self._set_progress(0, 0)
        self._set_state("준비", "neutral", GUIDE_START)
        self._show_form(-1)
        self._sync_buttons()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not self._running and not self._erp_running and any(os.path.isdir(u.toLocalFile()) for u in event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_drop_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)
        if sum(1 for u in event.mimeData().urls() if self.add_folder(u.toLocalFile())):
            event.acceptProposedAction()

    def _set_drop_active(self, on: bool) -> None:
        self.drop_zone.setProperty("active", on)
        self.drop_zone.style().unpolish(self.drop_zone)
        self.drop_zone.style().polish(self.drop_zone)

    # ── 오른쪽 칸 ───────────────────────────────────────────────────────
    def _on_row_selected(self) -> None:
        rows = {item.row() for item in self.table.selectedItems()}
        self._current = min(rows) if rows else -1
        self._show_form(self._current)
        self._sync_buttons()

    def _show_form(self, row: int) -> None:
        kind = self._kind(row)
        self._loading_form = True
        self.row_kind.blockSignals(True)
        self.row_kind.setCurrentIndex(max(self.row_kind.findData(kind), 0))
        self.row_kind.blockSignals(False)
        self._show_row_project(row)
        self._show_row_action(row)
        if kind == kinds.CARD and 0 <= row < len(self._cards):
            self.form_stack.setCurrentWidget(self.card_scroll)
            self.card_panel.set_job(self._cards[row])
            self.form_card.title_label.setText("카드 청구")
            self.form_card.hint_label.setText("비목마다 청구서 하나 · 결제 건마다 한 줄입니다. 고칠 것은 폴더 이름이나 파일 — 고친 뒤 [다시 읽기].")
            self._set_wide_form(True)
            self.form_card.setEnabled(True)
            self._loading_form = False
            if not self.is_running():
                self._set_guide(GUIDE_CARD)
            return
        if kinds.uses_roster(kind) and 0 <= row < len(self._jobs):
            self.form_stack.setCurrentWidget(self.scholarship_scroll)
            self.scholarship_panel.set_job(self._jobs[row])
            self.form_card.title_label.setText(f"{kinds.name_of(kind)} 청구")
            personal = kind == kinds.PERSONAL
            self.form_card.hint_label.setText(
                "사람마다 일반청구 탭에 입금처 · 증빙 기타 · 청구구분 (90) 기타로 넣고 [저장] 합니다. 빼고 싶은 사람은 체크를 푸세요." if personal else
                "학생마다 인건비 탭에 넣고 [저장] 합니다. 빼고 싶은 학생은 체크를 푸세요.")
            self._set_wide_form(True)
            self.form_card.setEnabled(True)
            self._loading_form = False
            if not self.is_running():
                self._set_guide(GUIDE_REATTACH if self._reattaching(row) else GUIDE_PERSONAL if personal else
                                GUIDE_SCHOLARSHIP_AUTO if settings.load().auto_new_sheet else GUIDE_SCHOLARSHIP)
            return
        self.form_stack.setCurrentIndex(0)
        self.form_card.title_label.setText("청구 내용")
        self.form_card.hint_label.setText("읽은 값입니다. 틀린 곳은 여기서 고치세요 — ERP 에는 이 값이 들어갑니다.")
        self._set_wide_form(False)
        data = self._data[row] if 0 <= row < len(self._data) else schema.normalize({})
        for key, widget in self.inputs.items():
            value = data.get(key)
            text = "" if value is None else str(value)
            if isinstance(widget, QComboBox):
                index = widget.findText(text)
                widget.setCurrentIndex(index if index >= 0 else 0)
                if index < 0 and text:
                    widget.setItemText(0, text)      # 보기에 없는 값은 그대로 보여 사람이 고치게
            else:
                widget.setText(text)
        self.attachments_label.setText(" · ".join(data.get("attachments") or []) or "—")
        self.notes_label.setText(data.get("notes") or "—")
        self._loading_form = False
        self.form_card.setEnabled(0 <= row < len(self._data))
        self._show_problems(row)
        if 0 <= row < len(self._dirs) and not self.is_running():
            self._set_guide(GUIDE_REATTACH if self._reattaching(row) else
                            GUIDE_TAXBILL if self._ready(row) and self._kind(row) == kinds.TAXBILL else
                            GUIDE_READ if self._ready(row) else GUIDE_UNREAD)

    def _show_problems(self, row: int) -> None:
        found = self._problems[row] if 0 <= row < len(self._problems) else []
        self.problems_label.setText(("확인: " + " · ".join(found)) if found else "")
        self.problems_label.setVisible(bool(found))

    def _form_changed(self, key: str) -> None:
        if self._loading_form or not (0 <= self._current < len(self._data)):
            return
        widget = self.inputs[key]
        text = widget.currentText() if isinstance(widget, QComboBox) else widget.text()
        raw = dict(self._data[self._current])
        raw[key] = text
        self._data[self._current] = schema.normalize(raw)
        self._problems[self._current] = schema.problems(self._data[self._current])
        self._refresh_row(self._current)
        self._show_problems(self._current)
        self._sync_buttons()

    # ── AI 플랫폼 ───────────────────────────────────────────────────────
    def _on_platform(self, status: ai.Status) -> None:
        """설정에서 고른 플랫폼의 상태(ui/ai_status.py). 읽는 중에는 쓰던 플랫폼 그대로 간다."""
        if self._running:
            return
        self._backend_key = status.key
        self._backend_state = status.state
        self._available = None if status.state == ai.CHECKING else status.usable
        if status.state in (ai.MISSING, ai.ERROR):
            self._backend_note = (NO_BACKEND if status.key == claude_cli.ClaudeCliBackend.key and status.state == ai.MISSING
                                  else status.note or "AI 플랫폼을 확인하지 못했습니다. [다시 확인] 을 눌러 보세요.")
        else:
            self._backend_note = ""
        self._sync_buttons()

    def _open_rules(self) -> None:
        rules.load_rules()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(settings.claims_rules_path())))

    # ── 읽기 ────────────────────────────────────────────────────────────
    def _read_all(self) -> None:
        if self._running or self._available is not True:
            return
        rows = self._unread_rows()
        # '지급내역' 엑셀이 있는 폴더는 명단 청구(장학금 · 혁신인재지원금)일 가능성이 크다 — 그 종류는 AI 없이 엑셀에서 바로 읽는다.
        # 일반으로 두면 AI 가 그 엑셀을 찍은 PDF 까지 읽어 사용량이 많이 든다(담당자 요청 2026-10-19: 원본이 엑셀이면 엑셀을 먼저).
        rosters = [i for i in rows if kinds.roster_excels(self._dirs[i])]
        if rosters:
            names = "\n".join(f"· {os.path.basename(self._dirs[i])} — {kinds.roster_excels(self._dirs[i])[0]}" for i in rosters[:6])
            answer = QMessageBox.question(
                self, "지급내역 엑셀이 있는 폴더",
                f"아래 {len(rosters)}개 폴더에는 지급내역 엑셀이 있습니다.\n{names}\n\n"
                "장학금 · 혁신인재지원금이면 오른쪽 칸의 '종류' 를 바꾸세요 — AI 없이 엑셀에서 바로 읽습니다.\n"
                "[예] 이 폴더들은 AI 로 읽지 않고 건너뜀 · [아니요] 그래도 AI 로 읽기",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                rows = [i for i in rows if i not in rosters]
        if not rows:
            return
        if self._backend_state == ai.NO_LOGIN:
            if QMessageBox.question(self, "로그인 확인", claude_cli.LOGIN_HELP,
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        if QMessageBox.question(
                self, "내용 읽기",
                f"지출 {len(rows)}건의 자료가 '{ai.label_of(self._backend_key)}' 로 전송되어 값을 뽑습니다.\n"
                "ERP 에는 아직 아무것도 넣지 않습니다.\n\n시작할까요?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._running = True
        self._pending_rows = rows
        self._done_count = 0
        for row in rows:
            self._set_status(row, "waiting")
        self._set_progress(0, len(rows))
        self._folders_open = False
        self._set_state("읽는 중", "info", "폴더 하나에 수십 초에서 몇 분이 걸립니다. 다른 탭으로 가도 작업은 이어집니다.", "check")
        self._sync_buttons()
        self.busy_changed.emit(True)
        self.extractor.run([self._dirs[i] for i in rows], self._backend_key, [kinds.fixed_values(self._kinds[i]) for i in rows])

    def _stop(self) -> None:
        self._stopping = True
        if self._erp_running:
            self.browser.request_stop()
            self.stop_button.setEnabled(False)
            self._set_state("멈추는 중", "warning", "지금 넣는 건(학생 · 결제 건)까지 마치고 멈춥니다…")
            return
        self.extractor.request_stop()
        self.stop_button.setEnabled(False)
        self._set_state("멈추는 중", "warning", "지금 읽는 폴더를 마치면 멈춥니다…", "check")

    def _row_of(self, index: int) -> int:
        return self._pending_rows[index] if index < len(self._pending_rows) else -1

    def _on_started(self, index: int) -> None:
        row = self._row_of(index)
        if row >= 0:
            self._set_status(row, "running")
            self.table.scrollToItem(self.table.item(row, COL_STATUS))

    def _advance(self) -> None:
        self._done_count += 1
        self._set_progress(self._done_count, len(self._pending_rows))

    def _on_done(self, index: int, result) -> None:
        row = self._row_of(index)
        if row < 0:
            return
        if result.ok:
            self._data[row] = result.data
            self._problems[row] = list(result.problems)
            self._set_status(row, "read")
            self._refresh_row(row)
            if row == self._current:
                self._show_form(row)
        else:
            self._set_status(row, "failed")
            cell = QTableWidgetItem("⚠ " + result.info)
            cell.setToolTip(result.info)
            self.table.setItem(row, COL_SUMMARY, cell)
        self._advance()

    def _on_skipped(self, index: int, _kind: str) -> None:
        row = self._row_of(index)
        if row >= 0:
            self._set_status(row, "skipped")
            self.table.setItem(row, COL_SUMMARY, QTableWidgetItem("⚠ 앞의 오류로 건너뜀"))
        self._advance()

    def _on_stopped(self, index: int) -> None:
        row = self._row_of(index)
        if row >= 0:
            self._set_status(row, "stopped")
        self._advance()

    def _on_finished(self, stop: str, ok_count: int, fail_count: int) -> None:
        self._running = False
        self._on_platform(self.platform.status())       # 읽는 동안 바뀐 설정·로그인 상태를 이제 반영
        self.busy_changed.emit(False)
        summary = f"읽음 {ok_count}건 · 실패 {fail_count}건"
        if stop == "login":
            name = ai.short_label(self._backend_key)
            self._set_state("로그인 필요", "danger", summary + f" — {name} 로그인이 풀려 남은 폴더를 건너뛰었습니다. "
                            "위쪽 AI 단추에서 로그인한 뒤 다시 읽으세요.", "check")
            status = ai_status.instance()
            status.mark(self._backend_key, ai.NO_LOGIN, "작업 중 로그인이 풀렸습니다")
            if QMessageBox.question(
                    self, "로그인이 풀렸습니다",
                    f"{name} 로그인이 풀려 있어 지출 자료를 읽지 못했습니다.\n\n지금 로그인 창을 열까요?\n"
                    "(로그인을 마치면 위쪽 AI 단추가 '로그인됨' 으로 바뀝니다. 그 뒤 [내용 읽기] 를 다시 누르시면 됩니다.)",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                status.login(self, self._backend_key)
        elif stop == "limit":
            self._set_state("한도 초과", "danger", summary + " — 한도가 풀린 뒤 [내용 읽기] 를 다시 누르세요.", "check")
        elif stop == "balance":
            self._set_state("잔액 부족", "danger", summary + " — 결제 상태를 확인한 뒤 다시 읽으세요.", "check")
        elif fail_count:
            self._set_state("일부 실패", "danger", summary + ". 실패한 건은 표의 사유를 확인하세요.", "check")
        else:
            self._set_state("읽음", "success", summary + ". " + GUIDE_READ)

    # ── ERP 에 채우기 ────────────────────────────────────────────────────
    def _fill(self) -> None:
        row = self._current
        if self._action(row) == ACTION_REATTACH:
            self._reattach(row)
            return
        if self._kind(row) == kinds.TAXBILL:
            self._fill_taxbill(row)
            return
        if self._kind(row) == kinds.CARD:
            if self.dry_run.isChecked():
                self._preview_card(row)
            else:
                self._fill_card(row)
            return
        if kinds.uses_roster(self._kind(row)):
            self._fill_scholarship(row)
            return
        if not (0 <= row < len(self._data)) or not self._browser_open or self._browser_busy:
            return
        data = self._data[row]
        found = schema.problems(data)
        missing = [f for f in found if f.endswith("없음") and "계좌번호" not in f]
        if missing:
            QMessageBox.warning(self, "값이 모자랍니다", "오른쪽 칸을 채운 뒤 다시 누르세요.\n\n· " + "\n· ".join(missing))
            return
        dry_run = self.dry_run.isChecked()
        test = self.test_mode.isChecked()
        project = self._projects[row] if row < len(self._projects) else self._last_project()
        # 같은 청구서가 이미 있는지는 넣을 때 ERP 결의서내역에서 본다(session._duplicate_check) — 앱 기록은 그것을 못 읽을 때만
        # (담당자 요청 2026-10-19: 앱에 넣은 이력보다 실제 ERP 내역이 먼저)
        lines = "\n".join("· " + line for line in schema.summary_lines(data))
        warn = ("\n\n확인: " + " · ".join(found)) if found else ""
        where = (f"ERP 과제: {navigate.label_of(project)}\n"
                 + ("시험 — 적요 앞에 [시험] 을 붙이고, ERP 의 같은 청구서 확인을 건너뜁니다. 끝나면 ERP 에서 지우세요.\n" if test else ""))
        answer = QMessageBox.question(
            self, "미리 보기" if dry_run else "ERP 에 채우기",
            (("무엇을 넣을지 확인만 합니다. ERP 에는 넣지 않습니다.\n\n" if dry_run
              else "그 과제의 결의서내역에 적요가 같은 청구서가 있는지 먼저 보고, 새 청구서 작성 화면에 아래 값을 넣습니다. "
                   "입금처·첨부·저장·신청은 직접 합니다.\n\n" + where + "\n")
             + lines + warn + "\n\n진행할까요?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        self._fill_row = row
        self._fill_test = test
        self.browser.fill_claim(dict(data), dry_run, project_no=project, folder=self._dirs[row], test_mode=test)

    def _on_claim_filled(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        row = getattr(self, "_fill_row", -1)
        self.ask_banner.hide()
        if report.blocked:
            self._set_state("넣지 않음", "warning", report.blocked)
            QMessageBox.warning(self, "채우지 못했습니다", report.blocked)
            self._sync_buttons()
            return
        if report.dry_run:
            QMessageBox.information(self, "미리 보기", text + "\n\n실제로 넣으려면 '미리 보기만' 체크를 풀고 다시 누르세요.")
            return
        if 0 <= row < len(self._dirs) and report.ok:
            if not getattr(self, "_fill_test", False):         # 시험으로 넣은 것은 기록하지 않는다
                record.remember(self._dirs[row], self._data[row], kind=self._kind(row))
            self._set_status(row, "filled")
            payee_ok = report.payee is not None and report.payee.ok
            payee_done = payee_ok and report.payee.picked
            taxbill_ok = report.taxbill is not None and report.taxbill.ok
            if payee_done:
                guide = "입금처까지 들어갔습니다. 첨부를 넣고 값을 확인한 뒤 앱의 [임시저장] 을 누르세요."
            elif payee_ok:
                guide = "입금처 팝업에서 거래처를 고르고 [확인] 을 누른 뒤, 첨부를 넣고 앱의 [임시저장] 을 누르세요."
            elif taxbill_ok and not report.taxbill.picked:
                guide = "세금계산서 팝업에서 계산서를 고르고 [확인] 을 누른 뒤 [입금처 찾기] 를 누르세요."
            else:
                guide = "ERP 화면에서 입금처(돋보기)·첨부를 넣고 값을 확인한 뒤 앱의 [임시저장] 을 누르세요."
            self._set_state("채움", "success", guide)
        else:
            if 0 <= row < len(self._dirs):
                self._set_status(row, "filled")
            self._set_state("일부 못 채움", "warning", "채우지 못한 칸은 ERP 에서 직접 넣은 뒤 [임시저장] 을 누르세요. 자세한 내용은 [진행 기록].")
        QMessageBox.information(self, "ERP 에 채움", text)
        self._sync_buttons()

    def _save_draft(self) -> None:
        row = self._current
        if not (0 <= row < len(self._dirs)) or not self._browser_open or self._browser_busy:
            return
        answer = QMessageBox.question(
            self, "임시저장",
            "ERP 화면에 입금처·첨부를 넣으셨나요?\n\n앱이 ERP 의 [저장] 을 눌러 임시저장합니다. "
            "[신청] 은 누르지 않습니다 — 검토한 뒤 직접 누르세요.\n\n진행할까요?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer != QMessageBox.Yes:
            return
        self._save_row = row
        self.browser.save_claim_draft()

    def _search_payee(self) -> None:
        row = self._current
        if not (0 <= row < len(self._dirs)) or not self._browser_open or self._browser_busy:
            return
        from ...claims import payee
        query = payee.query_for(self._data[row])
        if not query:
            QMessageBox.warning(self, "입금처 찾기", "오른쪽 칸의 입금처(거래처 이름)가 비어 있습니다.")
            return
        self.browser.search_payee(dict(self._data[row]))

    def _search_taxbill(self) -> None:
        row = self._current
        if not (0 <= row < len(self._dirs)) or not self._browser_open or self._browser_busy:
            return
        from ...claims import taxbill
        if not taxbill.query_for(self._data[row]):
            QMessageBox.warning(self, "세금계산서 찾기", "오른쪽 칸의 사업자등록번호(또는 입금처 이름)가 비어 있습니다.")
            return
        self.browser.search_taxbill(dict(self._data[row]))

    def _on_taxbill_searched(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        if report.ok:
            self._set_state("세금계산서 조회", "success",
                            "계산서가 들어갔습니다. 이어서 [입금처 찾기] 를 누르세요." if report.picked
                            else "팝업 목록에서 계산서를 고르고 [확인] 을 누른 뒤 [입금처 찾기] 를 누르세요.")
            QMessageBox.information(self, "세금계산서 찾기", text)
        else:
            self._set_state("세금계산서 못 찾음", "warning", report.note or "증빙 [선택] 을 직접 눌러 골라 주세요.")
            QMessageBox.warning(self, "세금계산서 찾기", text)
        self._sync_buttons()

    def _on_payee_searched(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        if report.ok:
            self._set_state("입금처 검색", "success",
                            "입금처가 들어갔습니다. 첨부를 넣고 [임시저장] 을 누르세요." if report.picked
                            else "팝업 목록에서 거래처를 고르고 [확인] 을 누른 뒤 [임시저장] 을 누르세요.")
            QMessageBox.information(self, "입금처 찾기", text)
        else:
            self._set_state("입금처 못 찾음", "warning", report.note or "돋보기를 직접 눌러 입금처를 골라 주세요.")
            QMessageBox.warning(self, "입금처 찾기", text)
        self._sync_buttons()

    def _on_claim_saved(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        row = getattr(self, "_save_row", -1)
        if report.ok:
            if 0 <= row < len(self._dirs):
                self._set_status(row, "saved")
            self._set_state("임시저장", "success", "ERP 에서 임시저장된 청구서를 검토한 뒤 [신청] 을 직접 누르세요.")
            QMessageBox.information(self, "임시저장", text)
        else:
            self._set_state("임시저장 안 됨", "warning", report.note or "ERP 알림을 확인하세요.")
            QMessageBox.warning(self, "임시저장 안 됨", text)
        self._sync_buttons()

    # ── 청구 종류 · 장학금 ──────────────────────────────────────────────
    def _load_scholarship(self, row: int, excel: str | None = None) -> None:
        """장학금 폴더를 읽는다(명단 엑셀 · 공통/개별증빙). AI 를 쓰지 않으니 넣자마자 끝난다."""
        old = self._jobs[row]
        job = sch.load_job(self._dirs[row], excel=excel, kind=self._kinds[row])
        if old is not None:
            sch.keep_edits(job, old)                # 다시 읽어도 담당자가 고친 값 · 넣어서 체크를 푼 사람은 남긴다
        self._jobs[row] = job
        self._problems[row] = job.problems()
        self._set_status(row, "read" if job.people and not any("합계" in p for p in self._problems[row])
                         else "problem" if job.people else "failed")
        self._append_log(f"{job.spec.name} 폴더 읽음: " + " / ".join(job.summary_lines()))
        for problem in self._problems[row]:
            self._append_log("  확인: " + problem)

    def _load_card(self, row: int) -> None:
        """카드 결제 기간 폴더를 읽는다(영수증 PDF 글자 · 회의록 · 물품 표 — AI 없음)."""
        job = card_mod.load_job(self._dirs[row])
        card_erp.restore(job)                      # 전에 넣은 결제 건 · 결의번호(_청구입력기록.json) — 다시 누르면 남은 것만
        self._cards[row] = job
        self._problems[row] = job.problems()
        self._set_status(row, "read" if job.items and not self._problems[row] else "problem" if job.items else "failed")
        self._append_log("카드 폴더 읽음: " + " / ".join(job.summary_lines()))
        for problem in self._problems[row]:
            self._append_log("  확인: " + problem)

    def _reload_card(self) -> None:
        row = self._current
        if not (0 <= row < len(self._cards)) or self._kinds[row] != kinds.CARD or self._erp_running:
            return
        self._load_card(row)
        self._refresh_row(row)
        self._show_form(row)
        self._sync_buttons()

    def _card_members(self, job) -> list:
        """참여연구원 명단 — 미리 보기용(넣을 때는 브라우저 스레드가 다시 읽는다)."""
        path = part_mod.find_file(str(getattr(settings.load(), "participants_file", "") or ""), job.folder, os.path.dirname(job.folder))
        return part_mod.read(path) if path else []

    def _card_rows(self, job, sheet, results) -> list[ReportRow]:
        by_index = {r.index: r for r in results}
        rows = []
        for index, item in enumerate(sheet.items):
            result = by_index.get(index)
            if result is None:
                if item.status != "saved":
                    continue
                status, tone, note = "저장됨", "success", "전에 넣음"
            else:
                status, tone = {"saved": ("저장됨", "success"), "skipped": ("건너뜀", "neutral"), "stopped": ("멈춤", "danger"),
                                "planned": ("넣을 것", "info")}.get(result.status, ("—", "neutral"))
                if result.status == "saved" and result.review:
                    status, tone = "저장·확인", "warning"
                elif result.status == "planned" and (item.blocking() or result.review):
                    status, tone = "확인 필요", "warning"
                note = " / ".join(([result.note] if result.note and result.status != "saved" else []) + result.review)
            rows.append(ReportRow(status, tone, [f"{item.used:%m-%d}" if item.used else "?", item.title, _money(item.amount) or "모름",
                                                 item.req_div_name or "?", note],
                                  detail=item_detail(item, job.folder, result), tips={1: item.title, 4: note}, right=(2,)))
        return rows

    def _preview_card(self, row: int) -> None:
        job = self._cards[row] if 0 <= row < len(self._cards) else None
        index = self.card_panel.chosen_sheet()
        if job is None or index < 0:
            return
        sheet = job.sheets[index]
        report = card_erp.run(None, None, job, sheet, lambda _m: None, ask=lambda _m: False, dry_run=True,
                              members=self._card_members(job), test_mode=self.test_mode.isChecked())
        self.card_panel.set_plans(index, report.results)
        show_report(self, title="미리 보기", heading=f"ERP 에 넣지 않았습니다 — 카드 {sheet.main_summary or '(비목 모름)'}", tone="info",
                    summary=[f"대표적요: {report.summary}", f"결제 {len(report.results)}건 · {sum(i.amount or 0 for i in sheet.items if i.status != 'saved'):,}원"]
                            + ([f"결의번호 {sheet.req_cnt} 에 이어서" ] if sheet.req_cnt else []),
                    columns=CARD_COLUMNS, rows=self._card_rows(job, sheet, report.results),
                    notes=job.problems() + [f"읽지 않음: {s}" for s in job.skipped],
                    footer="줄을 고르면 아래에 ERP 에 넣을 값(회의록등록 창 · 참석자 · 첨부)이 보입니다. 실제로 넣으려면 '미리 보기만' 체크를 풀고 "
                           "[ERP 에 넣기] 를 누르세요.")

    def _fill_card(self, row: int) -> None:
        job = self._cards[row] if 0 <= row < len(self._cards) else None
        index = self.card_panel.chosen_sheet()
        if job is None or index < 0 or self._erp_running or self._browser_busy or not self._browser_open:
            return
        sheet = job.sheets[index]
        left = [i for i in sheet.items if i.status != "saved"]
        hard = ([] if sheet.code else ["이 청구서의 비목을 모릅니다 — 결제 건 폴더 이름 앞에 비목명을 적으세요"]) + \
               [f"{i.name}: " + " · ".join(i.blocking()) for i in left if i.blocking()]
        if hard:
            QMessageBox.warning(self, "넣기 전에 고칠 것", "\n".join("· " + p for p in hard) + "\n\n고친 뒤 [다시 읽기] 를 누르세요.")
            return
        test = self.test_mode.isChecked()
        plan = card_erp.run(None, None, job, sheet, lambda _m: None, ask=lambda _m: False, dry_run=True,
                            members=self._card_members(job), test_mode=test)
        self.card_panel.set_plans(index, plan.results)
        project = self._projects[row] if row < len(self._projects) else self._last_project()
        if not show_report(
                self, title="ERP 에 넣기", tone="warning",
                heading=f"결제 건 하나씩 넣고 [저장](임시저장) 합니다 — {len(left)}건 · [신청] 은 누르지 않습니다",
                summary=[f"대표적요: {plan.summary}", f"ERP 과제: {navigate.label_of(project)}"]
                        + ([f"결의번호 {sheet.req_cnt} 에 이어서 넣습니다"] if sheet.req_cnt else [])
                        + (["시험 — 대표적요 앞에 [시험]. 시험 청구서를 ERP 에서 지우기 전까지 그 결제 건은 미청구 카드내역에서 빠집니다."] if test else []),
                columns=CARD_COLUMNS, rows=self._card_rows(job, sheet, plan.results), notes=job.problems(),
                footer=("결의서내역에서 대표적요가 같은 청구서를 먼저 찾고, 이어 넣는 것이 아니면 결의서내역의 [카드청구] 로 새 카드청구 화면을 앱이 띄웁니다. "
                        "미청구 카드내역 [조회] · 결제 건 고르기 · 비목 · 청구구분 · 회의록등록 창(시간 · 장소 · 목적 · 내용 · 외부참석자) · 첨부 · [저장] 은 "
                        "앱이, 참여인력 · 내부참석자와 소모성물품 [등록] 은 노란 띠가 뜨면 사람이 넣습니다."),
                accept_text=f"ERP 에 넣기 (결제 {len(left)}건)"):
            return
        self._erp_row = row
        self._erp_sheet = index
        self._erp_running = True
        self.card_panel.set_locked(True)
        self._set_status(row, "erp")
        self.busy_changed.emit(True)
        self._set_state("넣는 중", "info", "브라우저를 건드리지 말고 기다리세요. 앱이 물으면 위의 노란 띠를 따르세요.")
        self.browser.fill_card(job, index, dry_run=False, project_no=project, test_mode=test)
        self._sync_buttons()

    def _on_card_item(self, index: int, status: str, note: str) -> None:
        if self._current == self._erp_row:
            self.card_panel.set_item_status(self._erp_sheet, index, status, note)

    def _on_card_done(self, report) -> None:
        self._append_log("\n".join(report.lines()))
        self.ask_banner.hide()
        row = self._erp_row
        was_running = self._erp_running
        self._erp_running = False
        self.card_panel.set_locked(False)
        self.stop_button.setEnabled(True)
        if was_running:
            self.busy_changed.emit(False)
        job = self._cards[row] if 0 <= row < len(self._cards) else None
        index = self._erp_sheet
        sheet = job.sheets[index] if job is not None and 0 <= index < len(job.sheets) else None
        if report.blocked and not report.results:
            if 0 <= row < len(self._status):
                self._set_status(row, "read")
            self._set_state("넣지 못함", "warning", report.blocked)
            QMessageBox.warning(self, "넣지 못했습니다", report.blocked)
            self._sync_buttons()
            return
        left = [i for i in sheet.items if i.status != "saved"] if sheet else []
        if 0 <= row < len(self._status):
            self._set_status(row, "partial" if report.stopped and report.saved else "saved" if report.saved and not left else
                             "partial" if report.saved else "read")
        if self._current == row and job is not None:
            self.card_panel.set_job(job)
            for r in report.results:
                self.card_panel.set_item_status(index, r.index, "review" if r.status == "saved" and r.review else r.status, r.note)
        if 0 <= row < len(self._dirs):
            self._refresh_row(row)
        review = report.review_items()
        for item in review:
            self._append_log("신청 전 확인: " + item)
        check = f" 신청 전 확인할 것 {len(review)}건 — 결과 창과 [진행 기록] 에 있습니다." if review else ""
        more = [s for s in (job.sheets if job else []) if any(i.status != "saved" for i in s.items)]
        nxt = (f" 남은 청구서 {len(more)}개 — 다음 것은 ERP 에서 새 카드청구 화면을 띄운 뒤 '넣을 청구서' 를 고르고 다시 누르세요."
               if more and not left else "")
        if report.stopped:
            self._set_state("멈춤", "warning", f"결제 {report.saved}건을 임시저장했습니다. 고친 뒤 다시 누르면 남은 건만 넣습니다." + check)
        elif review:
            self._set_state("확인 필요", "warning", f"결제 {report.saved}건을 임시저장했습니다." + check + " ERP 에서 고친 뒤 [신청] 을 직접 누르세요." + nxt)
        else:
            self._set_state("임시저장", "success", f"결제 {report.saved}건을 임시저장했습니다. ERP 에서 검토하고 [신청] 을 직접 누르세요." + nxt)
        alerts = [f"{m} (×{report.messages.count(m)})" if report.messages.count(m) > 1 else m for m in dict.fromkeys(report.messages)]
        if sheet is not None:
            show_report(self, title="카드청구", tone="warning" if report.stopped or review else "success",
                        heading=f"임시저장 결제 {report.saved}건" + (" — 중간에 멈췄습니다" if report.stopped else "")
                                + (f" · 신청 전 확인할 것 {len(review)}건" if review else ""),
                        summary=[f"대표적요: {report.summary}"] + ([f"결의번호 {report.req_cnt}"] if report.req_cnt else [])
                                + ([report.blocked] if report.blocked else []),
                        columns=CARD_COLUMNS, rows=self._card_rows(job, sheet, report.results),
                        notes=review or alerts, notes_title="신청 전 확인할 것" if review else "ERP 알림",
                        footer="ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다." + nxt)
        self._sync_buttons()

    def _row_kind_changed(self, _index: int) -> None:
        row = self._current
        if self._loading_form or not (0 <= row < len(self._dirs)) or self._running or self._erp_running:
            return
        kind = self.row_kind.currentData()
        if kind == self._kinds[row] or not kinds.find(kind).ready:
            return
        before = self._kinds[row]
        self._kinds[row] = kind
        self._cards[row] = None
        if kind == kinds.CARD and row < len(self._actions):
            self._actions[row] = ACTION_FILL          # 카드 줄은 첨부만 다시 올리기를 아직 못 한다
        if kinds.uses_ai(before) and kinds.uses_ai(kind) and self._status[row] not in ("waiting", "running", "failed", "skipped", "stopped"):
            # 일반 ↔ 세금계산서 — AI 로 읽은 값은 그대로 두고 종류가 정한 값(증빙구분)만 맞춘다. 다시 읽지 않는다
            self._data[row].update(kinds.fixed_values(kind))
            self._problems[row] = schema.problems(self._data[row])
            self._set_status(row, "read")
        elif kinds.uses_roster(kind):
            self._load_scholarship(row)
        elif kind == kinds.CARD:
            self._jobs[row] = None
            self._load_card(row)
        else:
            # 일반으로 바꾸면 AI 로 다시 읽어야 한다
            self._jobs[row] = None
            self._data[row] = schema.normalize(kinds.fixed_values(kind))
            self._problems[row] = []
            self._set_status(row, "waiting")
        self._refresh_row(row)
        self._show_form(row)
        self._sync_buttons()

    def _on_panel_changed(self) -> None:
        row = self._current
        if 0 <= row < len(self._jobs) and self._jobs[row] is not None:
            self._problems[row] = self._jobs[row].problems()
            self._refresh_row(row)
        self._sync_buttons()

    def _reload_scholarship(self, excel: str) -> None:
        row = self._current
        if not (0 <= row < len(self._jobs)) or not kinds.uses_roster(self._kinds[row]) or self._erp_running:
            return
        self._load_scholarship(row, excel=excel or None)
        self._refresh_row(row)
        self._show_form(row)
        self._sync_buttons()

    # ── 세금계산서 이어 넣기 ────────────────────────────────────────────
    def _taxbill_rows(self, first: int) -> list[int]:
        """넣을 세금계산서 폴더 — 읽은 것 중 아직 임시저장하지 않은 줄. 고른 줄부터, 그다음 위에서 아래로."""
        rows = [r for r in range(len(self._dirs)) if self._kind(r) == kinds.TAXBILL and self._ready(r) and self._status[r] != "saved"]
        return ([first] if first in rows else []) + [r for r in rows if r != first]

    def _taxbill_items(self, rows: list[int]) -> list[taxbill_run.TaxbillItem]:
        return [taxbill_run.TaxbillItem(r, self._dirs[r], dict(self._data[r]),
                                        self._projects[r] if r < len(self._projects) else self._last_project()) for r in rows]

    @staticmethod
    def _taxbill_table(report, items) -> list[ReportRow]:
        return [ReportRow(status, tone, cells, detail=detail, tips={1: cells[1]}, right=(2, 4))
                for status, tone, cells, detail in taxbill_run.table_rows(report, items)]

    def _fill_taxbill(self, row: int) -> None:
        rows = self._taxbill_rows(row)
        if not rows or self._erp_running or self._browser_busy:
            return
        items = self._taxbill_items(rows)
        dry = self.dry_run.isChecked()
        test = self.test_mode.isChecked()
        plan = taxbill_run.plan(items)
        notes = [f"{item.name}: {p}" for item in items for p in item.problems()]
        projects = sorted({navigate.label_of(item.project_no) for item in items})
        summary = [f"세금계산서 폴더 {len(items)}개 · ERP 과제: " + " · ".join(projects)]
        if dry:
            self._set_state("미리 봄", "info", "폴더마다 넣을 값은 [진행 기록] 에도 있습니다. 실제로 넣으려면 '미리 보기만' 체크를 풀고 다시 누르세요.")
            self._append_log("\n".join(plan.lines()))
            show_report(self, title="미리 보기", tone="info",
                        heading=f"ERP 에 넣지 않았습니다 — 세금계산서 폴더 {len(items)}개를 이렇게 넣습니다",
                        summary=summary, columns=TAXBILL_COLUMNS, rows=self._taxbill_table(plan, items), notes=notes,
                        footer="실제로 넣으려면 '미리 보기만' 체크를 풀고 [ERP 에 넣기] 를 누르세요.")
            return
        if not self._browser_open:
            return
        hard = [f"{item.name}: {p}" for item in items for p in item.problems() if not p.startswith("첨부할 파일")]
        if hard:
            QMessageBox.warning(self, "넣기 전에 고칠 것", "오른쪽 칸을 채운 뒤 다시 누르세요.\n\n· " + "\n· ".join(hard))
            return
        if test:
            summary.append("시험 — 적요 앞에 [시험] 을 붙이고 ERP 의 같은 청구서 확인 · 기록을 건너뜁니다. 끝나면 ERP 에서 지우세요.")
        if not show_report(
                self, title="ERP 에 넣기", tone="warning",
                heading=f"폴더마다 새 청구서에 넣고 [저장](임시저장) 합니다 — 세금계산서 {len(items)}건 · [신청] 은 누르지 않습니다",
                summary=summary, columns=TAXBILL_COLUMNS, rows=self._taxbill_table(plan, items), notes=notes,
                footer=("폴더마다: 결의서내역에 같은 적요의 청구서가 있는지 보고 → 새 청구서 → 비목 · 증빙 '세금계산서' → 조회 팝업(승인번호 → 사업자번호 · 수신메일) → "
                        "뜨면 골라 [확인] → 금액 · 적요 → (노란 띠) 청구종류 · 증빙 창은 사람이 → 입금처 → 첨부 → [저장] → 다음 폴더. "
                        "조회에 안 뜨면(본부 등록 전) 그 폴더는 건너뛰고 다음 폴더로 갑니다."),
                accept_text=f"ERP 에 넣기 (세금계산서 {len(items)}건)"):
            return
        self._erp_row = row
        self._erp_running = True
        self.busy_changed.emit(True)
        self._set_state("넣는 중", "info", "브라우저를 건드리지 말고 기다리세요. 앱이 물으면 위의 노란 띠를 따르세요.")
        self.browser.fill_taxbill_claims(items, dry_run=False, test_mode=test)
        self._sync_buttons()

    def _on_taxbill_item(self, row: int, status: str, note: str) -> None:
        if not (0 <= row < len(self._dirs)):
            return
        shown = {"erp": "erp", "saved": "saved", "missing": "missing", "failed": "problem", "stopped": "read", "waiting": "read"}.get(status, "read")
        self._set_status(row, shown)
        if note:
            item = self.table.item(row, COL_STATUS)
            if item is not None:
                item.setToolTip(note)
        self._refresh_row(row)

    def _on_taxbill_run_done(self, report) -> None:
        self._append_log("\n".join(report.lines()))
        self.ask_banner.hide()
        was_running = self._erp_running
        self._erp_running = False
        self.stop_button.setEnabled(True)
        if was_running:
            self.busy_changed.emit(False)
        if report.blocked and not report.results:
            self._set_state("넣지 못함", "warning", report.blocked)
            QMessageBox.warning(self, "넣지 못했습니다", report.blocked)
            self._sync_buttons()
            return
        items = self._taxbill_items([r.row for r in report.results if 0 <= r.row < len(self._dirs)])
        review = report.review_items()
        for line in review:
            self._append_log("신청 전 확인: " + line)
        head = report.lines()[0]
        tone = "warning" if report.stopped or report.missing or report.count("failed") else "success"
        self._set_state("멈춤" if report.stopped else "넣음", tone,
                        head + ". ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요." + (" 건너뛴 폴더는 세금계산서가 등록된 뒤 다시 넣으세요." if report.missing else ""))
        show_report(self, title="ERP 에 넣기 결과", tone=tone, heading=head, summary=([report.blocked] if report.blocked else []),
                    columns=TAXBILL_COLUMNS, rows=self._taxbill_table(report, items), notes=review, notes_title="신청 전 확인할 것",
                    footer="ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다."
                           + (" '세금계산서 없음' 폴더는 본부가 등록한 뒤 [ERP 에 넣기] 를 다시 누르면 그것만 넣습니다." if report.missing else ""))
        self._sync_buttons()

    def _is_pending_roster(self, r: int) -> bool:
        """아직 넣지 않은 명단 폴더(장학금 · 혁신인재지원금) — 읽음 상태이고 넣을 사람이 있는 것."""
        job = self._jobs[r] if 0 <= r < len(self._jobs) else None
        return job is not None and kinds.uses_roster(self._kinds[r]) and self._status[r] == "read" and bool(job.chosen())

    def _next_roster_row(self, after: int) -> int | None:
        """다음에 넣을 명단 폴더 — 아래 줄부터, 그다음 위 줄."""
        order = list(range(after + 1, len(self._dirs))) + list(range(0, max(after, 0)))
        return next((r for r in order if self._is_pending_roster(r)), None)

    def _start_next(self, row: int, previous) -> None:
        """한 폴더를 끝내면 다음 폴더로 — 담당자 요청(2026-10-14). 새 청구서는 사람이 띄우고, 앱은 그 화면이 새 것인지 넣기 전에 본다."""
        if self._erp_running or not (0 <= row < len(self._jobs)):
            return
        self.table.selectRow(row)
        self._fill_scholarship(row, previous=previous)

    def _fill_scholarship(self, row: int, previous=None) -> None:
        if not (0 <= row < len(self._jobs)) or self._jobs[row] is None or self._erp_running or self._browser_busy:
            return
        self.scholarship_panel.apply_options()
        job = self._jobs[row]
        dry = self.dry_run.isChecked()
        job.project_no = self._projects[row] if row < len(self._projects) else self._last_project()
        job.test_mode = self.test_mode.isChecked()
        problems = job.problems()
        if not dry:
            if not self._browser_open:
                return
            # 넣기를 막는 것만(17절): 대표적요 없음 · 지급예정년월 꼴 · 표의 합계 불일치 · 사람 없음 · 비목 없음(개인 지급).
            # '…대표적요를 확인하세요' 같은 알림 글은 막지 않는다 — 전에는 '대표적요' 글자만 봐서 대표적요를 적은 뒤에도 막혔다
            hard = [p for p in problems if p.startswith(("대표적요가 비어", "지급예정년월", "비목")) or "표의 합계" in p or "사람이 없" in p]
            if hard:
                QMessageBox.warning(self, "넣기 전에 고칠 것", "\n".join("· " + p for p in hard))
                return
            # 개별증빙을 학생에게 못 붙였으면 따로 묻는다 — 확인 창 아래 '확인할 것' 한 줄로만 보여 공통증빙만 붙은 채 저장됐다
            # (담당자 실제 시험 2026-10-19: 파일 이름이 소학회명이라 6명 모두 개별증빙 없이 저장)
            if job.unmatched and QMessageBox.warning(
                    self, "개별증빙이 붙지 않습니다",
                    f"개별증빙 {len(job.unmatched)}개는 어느 학생 것인지 몰라 붙이지 않습니다.\n"
                    + "\n".join("· " + os.path.basename(f) for f in job.unmatched[:6])
                    + (f"\n· … 외 {len(job.unmatched) - 6}개" if len(job.unmatched) > 6 else "")
                    + "\n\n파일 이름(또는 하위 폴더 이름)에 학생 이름이나 명단의 소학회명이 있어야 합니다. "
                      "고친 뒤 [다시 읽기] 를 누르세요.\n\n그래도 이대로(그 파일 없이) 넣을까요?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
            # 같은 청구서가 이미 있는지는 넣을 때 ERP 결의서내역에서 본다(session._duplicate_check, 담당자 요청 2026-10-19) —
            # 앱 기록(sch.record_warning)은 결의서내역을 못 읽을 때만 노란 띠로 묻는다
        # 미리 보기는 ERP 를 건드리지 않으니 바로 결과 표를 보인다. 실제로 넣을 때만 같은 표로 한 번 더 묻는다.
        # 폴더마다 청구서 하나 — 앞 폴더를 끝내고 이어지는 폴더면 새 청구서를 띄우라고 먼저 말한다(앱은 넣기 전에 화면이 새 것인지 본다)
        waiting = [r for r in range(len(self._dirs)) if r != row and self._is_pending_roster(r)]
        if previous is not None:
            heading = f"다음 폴더 — {job.spec.name} {job.count_text()}을 새 청구서에 넣습니다 · [신청] 은 누르지 않습니다"
            footer = ((f"앞 폴더의 청구서(결의번호 {previous.req_cnt or '?'})는 그대로 두고, 앱이 결의서내역의 [일반청구] 로 새 청구서를 "
                       "띄워 넣습니다. 여기서 그만하려면 [취소].") if settings.load().auto_new_sheet else
                      (f"앞 폴더의 청구서(결의번호 {previous.req_cnt or '?'})는 그대로 두고, ERP 에서 새 청구서(결의서내역 → [일반청구])를 "
                       "띄운 뒤 누르세요. 여기서 그만하려면 [취소]."))
        else:
            heading = (f"{'학생' if job.spec.payroll else '사람'} 한 명씩 넣고 [저장](임시저장) 합니다 — {job.count_text()} · "
                       "[신청] 은 누르지 않습니다")
            footer = ("앱이 확신하지 못하는 단계에서는 멈추고 위의 노란 띠로 묻습니다. "
                      + ("새 청구서 작성 화면이 없거나 다른 청구서가 떠 있으면 앱이 결의서내역의 [일반청구] 로 새로 띄웁니다."
                         if settings.load().auto_new_sheet else "브라우저에 새 청구서 작성 화면이 떠 있어야 합니다.")
                      + (f" 이 폴더를 끝내면 남은 명단 폴더 {len(waiting)}개도 하나씩 이어서 묻습니다." if waiting else ""))
        if not dry and not show_report(
                self, title="ERP 에 넣기", tone="warning", heading=heading,
                summary=job.summary_lines(), columns=SCH_COLUMNS,
                rows=scholarship_rows(job, [sch.plan_person(job, i) for i in job.chosen()]), notes=problems,
                footer=footer, accept_text=f"ERP 에 넣기 ({job.count_text()})"):
            return
        self._erp_row = row
        if not dry:
            self._erp_running = True
            self.scholarship_panel.set_locked(True)
            self._set_status(row, "erp")
            self.busy_changed.emit(True)
            self._set_state("넣는 중", "info", "브라우저를 건드리지 말고 기다리세요. 앱이 물으면 위의 노란 띠를 따르세요.")
        self.browser.fill_scholarship(job, dry_run=dry)
        self._sync_buttons()

    def _answer(self, ok: bool) -> None:
        self.ask_banner.hide()
        self.reattach_now_button.hide()
        self.browser.answer_relogin(ok)
        self._sync_buttons()
        if ok:
            self._set_state("넣는 중", "info", "이어서 넣습니다.")

    def _answer_reattach(self) -> None:
        """중복 확인 띠의 [첨부만 다시 올리기](담당자 2026-10-23 "보완요청 와서 첨부문서 수정해야 한다고 … 그냥 장학금 청구하는 것처럼 파일만 다시 올려달라고") —
        넣기를 멈추고(새 청구서를 띄우지 않는다) 넣기가 끝나면(_on_sch_done) 같은 폴더로 첨부만 다시 올리기를 확인 창 없이 시작한다 — 할 일은 띠에 적혀 있다."""
        self._reattach_pending = self._erp_row
        if 0 <= self._erp_row < len(self._actions):
            self._actions[self._erp_row] = ACTION_REATTACH        # 다음부터 ③ 의 큰 단추도 첨부만 다시 올리기
            if self._current == self._erp_row:
                self._show_row_action(self._erp_row)
        self._set_state("첨부 다시 올리기로", "info", "넣기를 멈추고 그 청구서의 첨부만 다시 올립니다.")
        self._answer(False)

    def _reattach_possible(self, row: int) -> bool:
        return 0 <= row < len(self._dirs) and self._kind(row) != kinds.CARD and self._ready(row)

    def _on_sch_ask(self, message: str) -> None:
        self.ask_text.setText(message)
        # 명단 청구(장학금 · 혁신인재 · 개인 지급)의 중복 확인 띠에서만 — 일반 · 세금계산서의 넣기(_on_claim_filled)는 이 길을 잇지 않는다
        self.reattach_now_button.setVisible(reattach_mod.REATTACH_CHOICE in message and self._reattach_possible(self._erp_row)
                                            and 0 <= self._erp_row < len(self._jobs) and self._jobs[self._erp_row] is not None)
        self.ask_banner.show()
        self._sync_buttons()
        self._set_state("확인 필요", "warning", "위의 노란 띠를 따른 뒤 [계속] 을 누르세요.")
        self.attention.emit()
        self.window().raise_()
        self.window().activateWindow()

    def _on_sch_person(self, index: int, status: str, note: str) -> None:
        if self._current == self._erp_row:
            self.scholarship_panel.set_person_status(index, status, note)

    def _on_sch_done(self, report) -> None:
        text = "\n".join(report.lines())
        self._append_log(text)
        self.ask_banner.hide()
        self.reattach_now_button.hide()
        row = self._erp_row
        pending, self._reattach_pending = self._reattach_pending, -1
        was_running = self._erp_running
        self._erp_running = False
        self.scholarship_panel.set_locked(False)
        self.stop_button.setEnabled(True)
        if was_running:
            self.busy_changed.emit(False)
        job = self._jobs[row] if 0 <= row < len(self._jobs) else None
        if report.dry_run:
            if self._current == row:
                self.scholarship_panel.mark_planned(r.index for r in report.results)
            self._set_state("미리 봄", "info", "학생마다 넣을 값은 [진행 기록] 에도 있습니다. 실제로 넣으려면 '미리 보기만' 체크를 풀고 다시 누르세요.")
            if job is None:
                QMessageBox.information(self, "미리 보기", "\n".join(report.lines()[:40]))
            else:
                show_report(self, title="미리 보기", tone="info",
                            heading=f"ERP 에 넣지 않았습니다 — 이렇게 넣습니다 ({job.count_text([r.index for r in report.results])})",
                            summary=job.summary_lines(), columns=SCH_COLUMNS, rows=scholarship_rows(job, report.results),
                            notes=job.problems(),
                            footer="실제로 넣으려면 '미리 보기만' 체크를 풀고 [ERP 에 넣기] 를 누르세요.")
        elif report.blocked:
            if 0 <= row < len(self._status):
                self._set_status(row, "read")
            if pending == row and self._reattach_possible(row):
                # 중복 확인 띠에서 [첨부만 다시 올리기] — 멈춘 까닭 창을 띄우지 않고 바로 그 청구서의 첨부만 다시 올린다
                self._append_log("노란 띠의 [첨부만 다시 올리기] — 새 청구서에 넣지 않고 ERP 에 있는 그 청구서의 첨부만 다시 올립니다")
                self._reattach(row=row, force=True)
                return
            self._set_state("화면 없음", "warning", report.blocked)
            QMessageBox.warning(self, "넣지 못했습니다", report.blocked)
        else:
            saved = [r.index for r in report.results if r.status == "saved"]
            # 이미 청구내역에 있어 건너뛴 사람도 체크를 푼다 — 다시 눌러도 넣지 않을 사람이다(기록은 '앱이 저장한 사람' 만)
            done = saved + [r.index for r in report.results if r.status == "present"]
            if saved and job is not None and not job.test_mode:      # 시험으로 넣은 것은 기록하지 않는다
                try:
                    sch.record_job(job, report)
                except Exception as error:  # noqa: BLE001 — 기록을 못 남겨도 저장된 학생의 체크는 풀어야 다시 넣지 않는다
                    self._append_log("채운 기록을 남기지 못했습니다: %s" % (str(error).splitlines()[0] if str(error) else type(error).__name__))
            # 다 넣었으면(멈추지 않았으면) 남은 명단 폴더로 이어 간다 — 담당자 요청(2026-10-14) '하나를 끝내고 다음으로'
            nxt = self._next_roster_row(row) if saved and not report.stopped else None
            if 0 <= row < len(self._status):
                self._set_status(row, "partial" if report.stopped and done else "saved" if done else "read")
            if self._current == row:
                for r in report.results:
                    self.scholarship_panel.set_person_status(r.index, "review" if r.review else r.status, r.note)
                self.scholarship_panel.uncheck_saved(done)
            elif job is not None:
                for index in done:
                    job.selected[index] = False
            if 0 <= row < len(self._dirs):
                self._refresh_row(row)
            # 저장은 했지만 [신청] 전에 ERP 에서 고칠 것(소득구분 · 공제) — 담당자 결정(2026-10-14): 멈추지 않고 여기서 알린다
            review = report.review_items()
            for item in review:
                self._append_log("신청 전 확인: " + item)
            # 넣기를 마친 뒤 청구내역 표를 다시 읽어 명단과 맞춘 것(sheet_check) — 확인할 것은 같은 목록에 붙인다
            if report.check is not None:
                review = review + ["청구내역 대조: " + item for item in report.check.problems]
            check = f" 신청 전 확인할 것 {len(review)}건 — 결과 창과 [진행 기록] 에 있습니다." if review else ""
            all_present = bool(report.present) and not saved and not report.stopped
            if report.present and not all_present:
                check = f" 이미 청구내역에 있던 {report.present}명은 넣지 않았습니다." + check
            if all_present:
                self._set_state("이미 있음", "info", "넣을 사람이 모두 이 청구서의 청구내역에 이미 있어 넣지 않았습니다." + check)
            elif report.stopped:
                self._set_state("멈춤", "warning", f"{report.saved}명까지 임시저장했습니다. 남은 학생만 체크돼 있으니 고친 뒤 다시 누르면 이어집니다." + check)
            elif review:
                self._set_state("확인 필요", "warning", f"{report.saved}명을 임시저장했습니다." + check + " ERP 에서 고친 뒤 [신청] 을 직접 누르세요.")
            else:
                self._set_state("임시저장", "success", f"{report.saved}명을 임시저장했습니다." + check + " ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요.")
            if job is None:
                QMessageBox.information(self, "명단 청구", "\n".join(report.lines()[:40]))
            else:
                saved_text = (job.count_text(saved) if saved else "0명") + (f" · 이미 있어 건너뜀 {report.present}명" if report.present else "")
                # 같은 ERP 알림이 파일마다 되풀이된다('파일명의 특수문자는 제거됩니다.') — 한 줄로 모아 몇 번인지만
                alerts = [f"{m} (×{report.messages.count(m)})" if report.messages.count(m) > 1 else m
                          for m in dict.fromkeys(report.messages)]
                show_report(self, title=f"{job.spec.name} 청구", tone="warning" if report.stopped or review else "success",
                            heading=f"임시저장 {saved_text}" + (" — 중간에 멈췄습니다" if report.stopped else "")
                                    + (f" · 신청 전 확인할 것 {len(review)}건" if review else ""),
                            summary=[f"대표적요: {job.main_summary}", f"지급예정년월: {job.pay_ym}"]
                                    + ([f"신청 전 대조: {report.check.heading()}"] if report.check is not None else [])
                                    + (["ERP 알림: " + " · ".join(alerts)] if alerts and review else []),
                            columns=SCH_COLUMNS, rows=scholarship_rows(job, report.results),
                            notes=review or alerts, notes_title="신청 전 확인할 것" if review else "ERP 알림",
                            footer="ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다."
                                   + (" 위 '신청 전 확인할 것' 을 먼저 고치세요." if review else "")
                                   + (" 이 창을 닫으면 다음 폴더로 넘어갑니다." if nxt is not None else ""))
            if nxt is not None and job is not None:
                QTimer.singleShot(0, lambda: self._start_next(nxt, job))
        self._sync_buttons()

    # ── 첨부만 다시 올리기 ─────────────────────────────────────────────
    def _reattach(self, row: int | None = None, force: bool = False) -> None:
        """고른 폴더의 청구서가 ERP 에 이미 있을 때(임시저장 · 보완요청) — 청구내역 줄마다 첨부문서를 지우고 폴더의 지금 파일을 다시 올려 [저장].
        담당자 요청 2026-10-23. 값은 넣지 않는다. 미리 보기는 표만(브라우저 없이).
        force 는 중복 확인 띠의 [첨부만 다시 올리기] 에서 — 그 줄(row)로, '미리 보기만' 과 상관없이 실제로, 확인 창 없이(띠에서 이미 골랐다). 넣기가 막 멈춘 뒤라
        브라우저 바쁨 표시가 아직 남아 있어도 명령은 줄을 서므로 보낸다."""
        row = self._current if row is None else row
        if not (0 <= row < len(self._dirs)) or self._erp_running or (self._browser_busy and not force):
            return
        kind = self._kind(row)
        project = self._projects[row] if row < len(self._projects) else self._last_project()
        job = self._jobs[row] if row < len(self._jobs) else None
        if job is not None:
            self.scholarship_panel.apply_options()
            job.project_no = project
        plan = reattach_mod.plan_for(kind, self._dirs[row], self._data[row] if row < len(self._data) else {}, job=job, project_no=project)
        dry = self.dry_run.isChecked() and not force
        if plan.problems and (not dry or not plan.rows):
            QMessageBox.warning(self, "첨부를 다시 올리기 전에 고칠 것", "\n".join("· " + p for p in plan.problems))
            return
        if not dry:
            if not self._browser_open:
                return
            if not force and not show_report(
                    self, title="첨부만 다시 올리기", tone="warning",
                    heading=f"청구내역 줄마다 첨부문서를 모두 지우고 다시 올려 [저장] 합니다 — {len(plan.rows)}줄 · [신청] 은 누르지 않습니다",
                    summary=plan.summary_lines(), columns=REATTACH_COLUMNS,
                    rows=reattach_rows(reattach_mod.run(None, None, plan, lambda _m: None, dry_run=True)), notes=plan.problems,
                    footer="앱이 그 과제의 결의서내역에서 대표적요가 같은 임시저장 · 보완요청 청구서를 찾아 [상세조회/변경] 으로 엽니다. "
                           "줄 다시 열기 · '삭제' 가 기대대로 안 되면 멈추고 위의 노란 띠로 묻습니다. 지운 첨부는 되돌리지 못합니다.",
                    accept_text=f"첨부만 다시 올리기 ({len(plan.rows)}줄)"):
                return
        self._erp_row = row
        if not dry:
            self._erp_running = True
            self.scholarship_panel.set_locked(True)
            self._set_status(row, "erp")
            self.busy_changed.emit(True)
            self._set_state("첨부 다시 올리는 중", "info", "브라우저를 건드리지 말고 기다리세요. 앱이 물으면 위의 노란 띠를 따르세요.")
        self.browser.reattach_files(plan, dry_run=dry)
        self._sync_buttons()

    def _on_reattach_row(self, index: int, status: str, note: str) -> None:
        if self._current == self._erp_row and 0 <= self._erp_row < len(self._jobs) and self._jobs[self._erp_row] is not None:
            shown = {"saved": "saved", "failed": "failed", "stopped": "stopped", "erp": "running"}.get(status, "waiting")
            self.scholarship_panel.set_person_status(index, shown, note)

    def _on_reattach_done(self, report) -> None:
        self._append_log("\n".join(report.lines()))
        self.ask_banner.hide()
        row = self._erp_row
        was_running = self._erp_running
        self._erp_running = False
        self.scholarship_panel.set_locked(False)
        self.stop_button.setEnabled(True)
        if was_running:
            self.busy_changed.emit(False)
        plan = report.plan
        summary = plan.summary_lines() if plan is not None else None
        if report.dry_run:
            self._set_state("미리 봄", "info", "줄마다 지우고 올릴 파일은 표와 [진행 기록] 에 있습니다. 실제로 하려면 '미리 보기만' 체크를 풀고 "
                                             "④ 의 [첨부만 다시 올리기] 를 누르세요.")
            show_report(self, title="첨부만 다시 올리기 — 미리 보기", tone="info",
                        heading=f"ERP 에 넣지 않았습니다 — 이렇게 합니다 ({len(report.results)}줄)",
                        summary=summary, columns=REATTACH_COLUMNS, rows=reattach_rows(report), notes=plan.problems if plan else None,
                        footer="실제로 하려면 '미리 보기만' 체크를 풀고 [첨부만 다시 올리기] 를 누르세요.")
        elif report.blocked:
            if 0 <= row < len(self._status):
                self._set_status(row, "read")
            self._set_state("하지 못함", "warning", report.blocked)
            QMessageBox.warning(self, "첨부를 다시 올리지 못했습니다", report.blocked)
        else:
            saved = report.saved
            review = report.review_items()
            if 0 <= row < len(self._status):
                self._set_status(row, "saved" if saved and not report.stopped else "problem" if report.stopped else "read")
            if saved and not report.stopped:
                self._set_state("첨부 다시 올림", "success", f"{saved}줄의 첨부를 다시 올려 [저장] 했습니다. ERP 에서 확인하고 [신청] 은 직접 누르세요."
                                + (f" 신청 전 확인할 것 {len(review)}건 — 결과 창에 있습니다." if review else ""))
            elif report.stopped:
                self._set_state("멈춤", "warning", f"{saved}줄까지 저장하고 멈췄습니다 — 결과 창의 까닭을 보고 다시 누르면 남은 줄을 합니다.")
            else:
                self._set_state("한 줄도 안 됨", "warning", "첨부를 다시 올린 줄이 없습니다 — 결과 창의 까닭을 보세요.")
            show_report(self, title="첨부만 다시 올리기 — 결과", tone="success" if saved and not report.stopped else "warning",
                        heading=f"첨부를 다시 올려 저장한 줄 {saved}/{len(report.results)}"
                                + (f" · 결의번호 {report.req_cnt}" if report.req_cnt else "") + (f" ({report.state})" if report.state else "")
                                + (" · 멈춤" if report.stopped else ""),
                        summary=summary, columns=REATTACH_COLUMNS, rows=reattach_rows(report),
                        notes=review or report.messages, notes_title="신청 전 확인할 것" if review else "ERP 알림",
                        footer="ERP 에서 청구내역의 첨부를 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다.")
        self._sync_buttons()

    def _check_sheet(self) -> None:
        row = self._current
        job = self._jobs[row] if 0 <= row < len(self._jobs) else None
        if job is None or not self._browser_open:
            return
        self._sheet_row = row
        self._set_state("대조 중", "info", "ERP 작성 화면의 청구내역 표를 읽어 명단과 맞추는 중입니다 (읽기만 합니다).")
        self.browser.check_sheet(job)

    def _on_sheet_checked(self, check) -> None:
        row = getattr(self, "_sheet_row", -1)
        job = self._jobs[row] if 0 <= row < len(self._jobs) else None
        name = job.spec.name if job is not None else "명단"
        if not check.read:
            self._set_state("대조 못 함", "warning", "작성 화면을 찾지 못했습니다. 넣은 청구서(작성 화면)를 띄운 뒤 다시 누르세요.")
            QMessageBox.warning(self, "청구내역 대조", "ERP 작성 화면(청구내역 표)을 찾지 못했습니다.\n"
                                "결의서내역에서 넣은 청구서를 열어 작성 화면을 띄운 뒤 다시 누르세요.")
            return
        if check.problems:
            self._set_state("확인 필요", "warning", f"청구내역 대조 — 확인할 것 {len(check.problems)}건. 고친 뒤 [신청] 을 직접 누르세요.")
        else:
            self._set_state("대조 맞음", "success", check.heading() + ". ERP 에서 검토하고 [신청] 을 직접 누르세요.")
        show_report(self, title="청구내역 대조", tone="warning" if check.problems else "success",
                    heading=f"{name} — {check.heading()}",
                    summary=[f"대표적요: {job.main_summary}"] if job is not None else None,
                    columns=[("결과", 104), ("내용", None)], rows=sheet_check_rows(check),
                    notes=check.problems, notes_title="신청 전 확인할 것",
                    footer="읽기만 했습니다 — ERP 에서 아무것도 누르지 않았습니다. [삭제] · [신청] 은 직접 하세요.")

    # ── 신호 ────────────────────────────────────────────────────────────
    def _append_log(self, text: str) -> None:
        self.log_view.appendPlainText(text)

    def _on_extract_busy(self, busy: bool, message: str) -> None:
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()

    def _on_browser_busy(self, busy: bool, message: str) -> None:
        self._browser_busy = busy
        # 받기 화면을 한 번도 안 열었으면 상태줄이 비어 있었다 — 팝업에서 고르기를 기다리는 안내(최대 3분)가 안 보였다
        if message:
            self.window().statusBar().showMessage(message)
        elif not busy:
            self.window().statusBar().clearMessage()
        self._sync_buttons()

    def _on_browser_opened(self) -> None:
        self._browser_open = True
        self._sync_buttons()

    def _on_browser_state(self, alive: bool) -> None:
        self._browser_open = alive
        self._sync_buttons()

    def _on_extract_error(self, message: str) -> None:
        """AI 읽기 스레드의 오류 — 브라우저 쪽 상태는 건드리지 않는다."""
        self._running = False
        self._on_platform(self.platform.status())
        self.busy_changed.emit(self.is_running())
        self._set_state("오류", "danger")
        self._sync_buttons()
        warn(self, "문제가 생겼습니다", message, "일반청구", "자세한 내용은 머리의 [진행 기록] 과 로그 파일에 있습니다.")

    def _on_browser_failed(self, owner: str, message: str) -> None:
        """브라우저 스레드의 오류 — 이 화면이 넣은 명령의 것만. 받기 화면의 오류로 AI 읽기 상태가 풀리던 것을 막는다."""
        if owner != "claim":
            return
        if self._erp_running:
            self._erp_running = False
            self.ask_banner.hide()
            self.scholarship_panel.set_locked(False)
            self.card_panel.set_locked(False)
            if 0 <= self._erp_row < len(self._status):
                self._set_status(self._erp_row, "partial")
        self.busy_changed.emit(self.is_running())
        self._set_state("오류", "danger")
        self._sync_buttons()
        warn(self, "문제가 생겼습니다", message, "일반청구", "자세한 내용은 머리의 [진행 기록] 과 로그 파일에 있습니다.")

    def resizeEvent(self, event) -> None:  # noqa: N802
        """창이 낮으면 머리 · 끌어다 놓기 칸을 줄여 목록과 학생 표에 자리를 준다 — 1366×768 노트북(창 안쪽 ~690)에서
        학생 표가 한 줄 반만 보였다(2026-10-14 점검). 탭 이름이 이미 '일반청구' 라 제목은 접어도 된다."""
        super().resizeEvent(event)
        height = self.height()
        self.page_desc.setVisible(height >= 600)
        low = height < 720
        self.head_art.setVisible(not low)
        self.head_title.setVisible(not low)
        self.drop_art.setVisible(not low)
        # ③ 까지 한 화면에 두면 ② 의 칸이 좁다 — 흔한 창(1320×860)에서도 설명 줄은 접어 학생 표 · 값 칸에 자리를 준다
        self.form_card.hint_label.setVisible(height >= 860)

    def shutdown(self) -> None:
        if self._erp_running:
            self.browser.request_stop()
        self.extractor.shutdown()
        if self._owns_browser:
            self.browser.shutdown()
