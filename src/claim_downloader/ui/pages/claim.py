"""일반청구 화면 — 명단 청구(장학금 · 혁신인재지원금)와 카드청구 폴더를 넣어 ERP 작성 화면에 넣고 임시저장까지. [신청] 은 사람이.

폴더마다 **청구 종류**를 고른다(claims/kinds.py) — 장학금(명단 엑셀 + 공통/개별증빙, 오른쪽 칸이 학생 표로 바뀌고 [ERP 에 넣기] 가
학생마다 인건비 탭에 넣고 저장) · 혁신인재지원금(장학금과 같은 흐름, 비목만 다름) · 카드(결제 기간 폴더를 비목마다 청구서로 나눠 결제 건마다 넣음).
그 밖의 종류(자동 · 일반(AI 읽기) · 세금계산서 · 개인 지급 · 출장비)는 2026-10-28 담당자 요청으로 걷어냈다
("일반청구에서는 장학금, 혁신인재지원금, 카드만 사용할게요 그외 기능은 삭제해주세요") — 코드는 git 이력에만 있다.

할 차례인 단계만 위에서 아래로 떠오른다(ui/flow.py, 담당자 요청 2026-10-21 — "클릭해야 하는 이동 순서대로 하나 둘 떠오르게"):
    ① 청구 종류(카드 — 담당자 2026-10-26 "1단계에서 청구종류를 선택") → ② 지출 폴더 넣기(과제 · 끌어다 놓기)
    → ③ 내용 확인(목록 | 고른 줄의 명단 · 결제 건 · 할 일)
    → ④ ERP 에 넣기(브라우저 · [미리 보기]/[ERP 에 넣기] · [청구내역 대조]) → ERP 에서 사람이 검토하고 [신청]

담당자 결정(2026-10-13): 내역 작성 후 임시저장까지 앱이, 그 뒤는 사람이. 기본은 '미리 보기만'(dry-run) — 체크를
풀어야 실제로 넣는다. 신청·삭제·초기화는 코드가 절대 누르지 않는다(claims/form.py). 넣기 전에 그 폴더의 과제(폴더마다 고름)의
ERP 결의서내역에서 대표적요가 같은 청구서를 찾아 있으면 묻는다 — 앱 기록(claims/record.py)은 결의서내역을 못 읽을 때만(담당자 요청 2026-10-19).
[시험] 을 켜면 대표적요 앞에 [시험] 을 붙이고 그 확인과 기록을 건너뛴다(이미 올린 폴더로 시험).

브라우저는 청구서 받기와 같은 스레드(app.session_worker)를 쓴다 — ERP 로그인은 한 번이면 된다.
"""
from __future__ import annotations

import html
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

from ... import ai, navigate, settings, work_folders
from ...claims import card as card_mod
from ...claims import card_ai
from ...claims import card_erp
from ...claims import checks
from ...claims import participants as part_mod
from ...claims import kinds
from ...claims import reattach as reattach_mod
from ...claims import scholarship as sch
from .. import ai_status, folder_picker, project_box
from ..art import Art
from ..log_button import LogSendButton, warn
from ..flow import HIDDEN, ChoiceCard, FlowArea, FlowStep
from ..flowlogic import CLAIM_ORDER, claim_stage, flow_states
from .. import result_store
from ..report_dialog import ReportRow, entry_report, report_to_data, show_report
from ..widgets import Card, Pill, PillDelegate, WrapLabel, muted_label
from ..worker import SessionWorker
from .card import CardPanel, item_detail, item_html, review_of
from .scholarship import ScholarshipPanel

COLUMNS = [("상태", 96), ("종류", 108), ("지출 (폴더)", 200), ("적요", 280), ("청구액", 110), ("입금처", None)]
COL_STATUS, COL_KIND, COL_DIR, COL_SUMMARY, COL_AMOUNT, COL_PAYEE = 0, 1, 2, 3, 4, 5

ROW_STATUS = {
    "waiting": ("대기", "neutral"),
    "read": ("읽음", "success"),
    "failed": ("실패", "danger"),
    "saved": ("임시저장", "success"),
    "problem": ("확인 필요", "warning"),
    "erp": ("넣는 중", "info"),
    "partial": ("일부 저장", "warning"),
    "ai": ("AI 읽는 중", "info"),          # 카드: 영수증 그림 · 회의록 PDF 를 AI 로 읽는 중(claims/card_ai.py)
}

GUIDE_START = "청구 종류(장학금 · 혁신인재지원금 · 카드)를 고르세요. 그다음 지출 폴더를 넣으면 명단 · 결제 건이 바로 나옵니다."
GUIDE_ADD = "과제를 확인하고 지출 폴더를 넣으세요. 폴더 1개 = 청구 1건 — 넣은 뒤에도 ③ 의 오른쪽 칸 위에서 폴더마다 종류를 바꿀 수 있습니다."
GUIDE_SCHOLARSHIP = ("학생 표를 확인한 뒤, 브라우저에서 결의서내역 → [일반청구] 로 새 청구서 화면을 띄우고 [ERP 에 넣기] 를 누르세요. "
                     "인건비 탭은 앱이 누릅니다.")
# 새 청구서를 앱이 띄울 때(설정 auto_new_sheet, 기본) — 사람은 로그인만 하면 된다
GUIDE_SCHOLARSHIP_AUTO = ("학생 표와 위의 과제를 확인한 뒤 [ERP 에 넣기] 를 누르세요. 그 과제의 결의서내역에 같은 청구서가 있는지 보고, "
                          "새 청구서 · 인건비 탭은 앱이 띄웁니다. 이미 올린 폴더로 시험하려면 [시험] 을 켜세요.")
GUIDE_CARD = ("비목마다 청구서로 나눠 읽었습니다. 사용일 · 금액 · 청구구분을 확인하고, 틀리면 폴더 이름이나 파일을 고친 뒤 [다시 읽기]. "
              "넣을 때는 '넣을 청구서' 를 고르고 [ERP 에 넣기] — 카드청구 화면은 앱이 결의서내역의 [카드청구] 로 띄웁니다.")
GUIDE_REATTACH = ("'할 일' 이 첨부만 다시 올리기입니다 — 위의 과제가 그 청구서가 있는 과제인지 확인한 뒤 ④ 의 [첨부만 다시 올리기] 를 누르세요. "
                  "앱이 그 과제의 결의서내역에서 대표적요가 같은 임시저장 · 보완요청 청구서를 찾아 열고, 청구내역 줄마다 첨부문서를 지운 뒤 폴더의 지금 파일을 "
                  "올려 [저장] 합니다. 청구내역 값은 넣지 않고 [신청] 은 직접. '미리 보기만' 이면 표로만 봅니다.")


def _money(value) -> str:
    return f"{value:,}" if isinstance(value, int) else ""


# 장학금 미리 보기 · 넣기 확인 · 결과 창의 표 (ui/report_dialog.py) — 사람마다 한 줄
# 카드 결제 건 표 — 왼쪽은 좁게(건명이 늘어남), 확인할 것 · 넣을 값은 오른쪽 넓은 칸에(ReportDialog side_detail, 담당자 2026-11-11)
CARD_COLUMNS = [("상태", 92), ("사용일", 68), ("구분", 52), ("건명", None), ("금액", 84), ("확인", 52)]
CARD_STRETCH = 3
# 확인할 것은 표 위 한 칸에만(번호 · 무게 · 무엇 · 어디서 · 할 일) — 표의 '확인' 칸은 그 번호만 가리킨다(담당자 2026-11-11)
NEXT_FOLDER_NOTE = " 이 창을 닫으면 다음 폴더로 넘어갑니다."
SCH_COLUMNS = [("상태", 100), ("No", 44), ("이름", 150), ("학번", 100), ("청구액", 88), ("개별 적요", None), ("첨부", 56), ("확인", 84)]
SCH_STRETCH = 5
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


def review_notes(results) -> list:
    """넣은 뒤의 '신청 전 확인'(PersonResult.review) — 그 학생 줄을 가리키는 확인할 것으로."""
    out = []
    for r in results:
        for item in r.review:
            out.append(checks.Note(f"{r.index + 1}. {r.name} — {item}", what=f"{r.name} — {item}", person=r.index,
                                   where="ERP 작성 화면 청구내역 — 이 학생 줄",
                                   todo="ERP 에서 그 줄의 ○ 를 눌러 열고 고친 뒤 [저장] — 그다음 [신청] 은 직접"))
    return out


def check_notes(problems) -> list:
    """신청 전 대조(sheet_check)의 문제 — 청구내역 표를 다시 읽어 명단과 맞춘 것."""
    return [checks.Note("청구내역 대조: " + item, what=item, where="ERP 작성 화면 청구내역 표(신청 전 대조)",
                        todo="ERP 청구내역에서 그 줄을 보고 고친 뒤 [신청]") for item in problems]


def run_notes(results) -> list:
    """넣다가 못 넣은 · 멈춘 · 이미 있던 학생의 까닭 — 전에는 표 끝 칸에 있었다. 이제 확인할 것은 표 위 칸에만 둔다."""
    out = []
    for r in results:
        if not r.note or r.review:
            continue
        who = r.name + (f"({r.course})" if r.course else "")
        if r.status in ("failed", "stopped"):
            out.append(checks.Note(f"{r.index + 1}. {r.name} — {r.note}", level=checks.FIX if r.status == "failed" else checks.CHECK,
                                   what=f"{who} — {'넣지 못함' if r.status == 'failed' else '멈춤'}: {r.note}", person=r.index,
                                   where="ERP 작성 화면 — 이 학생을 넣던 중",
                                   todo="까닭을 고친 뒤 [ERP 에 넣기] 를 다시 누르면 넣지 못한 사람만 넣습니다"))
        elif r.status == "present":
            out.append(checks.Note(f"{r.index + 1}. {r.name} — {r.note}", level=checks.INFO, what=f"{who} — {r.note}", person=r.index,
                                   where="ERP 작성 화면 청구내역", todo="할 일 없음 — 두 번 넣지 않았습니다"))
    return out


def scholarship_view(job, results, notes=()) -> tuple[list, list[ReportRow]]:
    """확인할 것(표 위 한 칸 — 고칠 것 → 확인 → 참고 차례로 번호)과 사람마다 표 한 줄. 표의 '확인' 칸은 위 칸의 번호만 가리키고,
    첨부 파일 목록 · 진행 단계는 그 칸에 마우스를 올리면 보인다 — 아래 '자세히' 칸은 두지 않는다(담당자 2026-11-11
    "확인필요 세부사항은 목록 위에서만 보여지도록 해주세요. 아래 박스로 되어있는건 삭제")."""
    ordered = checks.ordered(list(notes) + run_notes(results) + [n for r in results for n in r.notes])
    numbers: dict[int, list[int]] = {}
    for n, note in enumerate(ordered, 1):
        if note.person is not None:
            numbers.setdefault(note.person, []).append(n)
    rows = []
    for r in results:
        mine = [ordered[n - 1] for n in numbers.get(r.index, [])]
        status, tone = SCH_STATUS.get(r.status, (r.status, "neutral"))
        if r.status == "planned" and any(n.level != checks.INFO for n in mine):
            status, tone = "확인 필요", "warning"
        if r.status == "saved" and r.review:
            status, tone = SCH_STATUS["review"]
        main = job.main_summary if job is not None else ""
        # 줄마다 앞의 대표적요는 같다 — 줄을 가르는 뒷부분(_이름 · (이름_교과목))이 보이게 앞을 줄인다
        shown = "…" + r.summary[len(main):] if main and r.summary.startswith(main) and r.summary != main else r.summary
        base = job.folder if job is not None else ""
        files = [f"[{'공통' if i < r.common_count else '개별'}] " + (os.path.relpath(path, base) if base else os.path.basename(path))
                 for i, path in enumerate(r.files)]
        who = r.name + (f" · {r.course}" if r.course else "")
        tip_who = who + (f"\n학번 {r.student_no}" if r.student_no else "")
        if r.status != "planned" and r.lines:
            tip_who += "\n진행:\n" + "\n".join("  " + line for line in r.lines)
        mark = ("위 " + " · ".join(str(n) for n in numbers.get(r.index, []))) if r.index in numbers else ""
        if mine and all(n.level == checks.INFO for n in mine):
            mark += " (참고)"
        personal = len(r.files) - r.common_count
        rows.append(ReportRow(status, tone, [str(r.index + 1), who, r.student_no or "—", _money(r.amount) or "—",
                                             shown, f"{len(r.files)}개", mark],
                              tips={1: tip_who, 4: r.summary,
                                    5: f"첨부 {len(r.files)}개 (공통 {r.common_count} · 개별 {personal})\n" + "\n".join(files),
                                    6: "\n".join(f"{ordered[n - 1].level_name} — {ordered[n - 1].what}" for n in numbers.get(r.index, []))
                                       or "확인할 것 없음"},
                              right=(3, 5), key=r.index))
    return ordered, rows


class ClaimPage(QWidget):
    busy_changed = Signal(bool)
    attention = Signal()            # 노란 띠에서 사람을 기다림 — 다른 탭에 있으면 이 화면으로(app._wire)

    def __init__(self, parent: QWidget | None = None, worker: SessionWorker | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self.setAcceptDrops(True)
        self.browser = worker if worker is not None else SessionWorker()
        self._owns_browser = worker is None
        self._dirs: list[str] = []
        self._status: list[str] = []
        self._problems: list[list[str]] = []
        self._kinds: list[str] = []                      # 폴더마다 청구 종류 (kinds.SCHOLARSHIP · INNOVATION · CARD)
        self._jobs: list[sch.Job | None] = []            # 장학금 폴더의 명단 · 증빙
        self._cards: list[card_mod.CardJob | None] = []  # 카드 결제 기간 폴더 — 비목마다 청구서 · 결제 건
        self._projects: list[str] = []                   # 폴더마다 ERP 과제번호 — 폴더를 넣을 때 고른다(담당자 2026-10-19)
        self._actions: list[str] = []                    # 폴더마다 할 일(ACTION_FILL · ACTION_REATTACH) — ② 오른쪽 칸 위에서 고른다
        self._erp_running = False                        # ERP 에 넣는 중 (브라우저 스레드)
        self._stopping = False
        self._erp_row = -1
        self._erp_sheet = 0                              # 카드: 넣는 중인 청구서(비목) 번호
        self._browser_busy = False
        self._reattach_pending = -1     # 중복 확인 띠에서 [첨부만 다시 올리기] 를 누른 줄 — 넣기가 멈추면 그 폴더로 첨부만 다시 올린다
        # 카드: 영수증 그림 · 회의록 PDF 를 AI 로 읽기(claims/card_ai.py) — 스레드는 처음 필요할 때 만든다
        self._card_ai_worker = None
        self._ai_reading: set[str] = set()                         # 읽는 중인 결제 건 폴더(card_ai.folder_key)
        self._ai_results: dict[str, tuple[str, dict | str]] = {}  # 이번 실행에서 읽은 것 · 못 읽은 까닭 — (파일 서명, 결과)
        self._ai_missing_told = False
        self._ai_retry_on_login = False          # 로그인이 풀려 못 읽은 결제 건 — 로그인되면(위쪽 AI 단추가 초록) 저절로 다시 맡긴다
        self._browser_open = False
        self._current = -1
        self._loading_form = False

        self._guide = GUIDE_START
        self._guide_where = ""                           # 안내를 둘 단계 — 비면 지금 단계
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

        ai_status.instance().changed.connect(self._on_ai_status)

        b = self.browser
        b.log.connect(self._append_log)
        b.busy.connect(self._on_browser_busy)
        b.browser_opened.connect(self._on_browser_opened)
        b.browser_state.connect(self._on_browser_state)
        b.scholarship_person.connect(self._on_sch_person)
        b.scholarship_ask.connect(self._on_sch_ask)
        b.scholarship_done.connect(self._on_sch_done)
        b.sheet_checked.connect(self._on_sheet_checked)
        b.card_item.connect(self._on_card_item)
        b.card_done.connect(self._on_card_done)
        b.reattach_row.connect(self._on_reattach_row)
        b.reattach_done.connect(self._on_reattach_done)
        b.projects_read.connect(self._refresh_projects)
        b.failed.connect(self._on_browser_failed)
        b.sites_changed.connect(lambda _sites: self._sync_put_state())

        self._show_form(-1)
        self._sync_buttons()

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        """머리 — 그림 · 제목 · 한 줄 설명 / 오른쪽에 지금 상태 · [멈추기] · [진행 기록] · [도구].
        [멈추기] 는 ERP 에 넣는 동안 늘 보이는 자리에 둔다(단계는 스크롤될 수 있다)."""
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
            "지출 폴더마다 청구 종류(장학금 · 혁신인재지원금 · 카드)를 고르면 ERP 작성 화면에 넣고 임시저장까지 합니다. "
            "[신청] 은 직접 합니다.")
        texts.addWidget(self.page_desc)
        head.addLayout(texts, 1)
        self.state_pill = Pill("준비", "neutral")
        head.addWidget(self.state_pill, 0, Qt.AlignVCenter)
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
    def _kind_box() -> QComboBox:
        """청구 종류 고르기 칸 — 장학금 · 혁신인재지원금 · 카드."""
        box = QComboBox()
        for kind in kinds.KINDS:
            box.addItem(kind.name, kind.key)
            box.setItemData(box.count() - 1, kind.hint, Qt.ToolTipRole)
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
        고른 값은 숨은 고르기 칸(add_kind)에 두어 폴더를 넣는 코드(add_folder)가 읽는다. 종류는 셋뿐이다(2026-10-28)."""
        step = FlowStep("1", "청구 종류를 고르세요", "이번에 넣을 지출 폴더가 어떤 청구인지 고르세요.")
        step.edit.connect(self._open_kinds)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        self.kind_cards: dict[str, ChoiceCard] = {}
        columns = len(kinds.KINDS)
        for i, kind in enumerate(kinds.KINDS):
            card = ChoiceCard(kind.key, kind.name, kind.brief or kind.hint, kind.art)
            card.setToolTip(kind.hint)
            card.chosen.connect(self._choose_kind)
            self.kind_cards[kind.key] = card
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
        self.add_kind = self._kind_box()
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
        """③ 내용 확인 — 지출 목록(왼쪽)에서 한 줄을 고르면 오른쪽에 그 청구의 명단 · 결제 건."""
        step = FlowStep("3", "내용을 확인하세요", editable=False)
        self.clear_button = QPushButton("목록 비우기")
        self.clear_button.setObjectName("ghost")
        self.clear_button.clicked.connect(self._clear)
        step.add_side(self.clear_button)
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
        """명단 · 카드는 오른쪽 표가 넓어야 해서 왼쪽 목록과 폭을 바꾼다."""
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
        card = Card("청구 내용", "지출 목록에서 한 줄을 고르세요.", margins=(16, 14, 16, 12))
        # 고른 폴더의 청구 종류 · ERP 과제 — 넣은 뒤에도 여기서 바꾼다(바꾸면 아래 칸이 그 종류의 칸으로).
        # 머리 줄 오른쪽에 두면 설명 글이 좁은 칸에 여러 줄로 접혀 칸이 길어졌다 — 설명 아래 한 줄로.
        choose = QHBoxLayout()
        choose.setSpacing(8)
        kind_label = QLabel("종류")
        kind_label.setObjectName("fieldLabel")
        choose.addWidget(kind_label, 0, Qt.AlignVCenter)
        self.row_kind = self._kind_box()
        self.row_kind.setToolTip("이 지출 폴더의 청구 종류")
        self.row_kind.currentIndexChanged.connect(self._row_kind_changed)
        kind_label.setBuddy(self.row_kind)
        choose.addWidget(self.row_kind, 0, Qt.AlignVCenter)
        choose.addStretch(1)
        card.add_layout(choose)
        # 할 일 — 새 청구서에 넣기 / 첨부만 다시 올리기. 보기 글이 길어 종류 줄에 같이 두면 좁은 오른쪽 칸에서 잘린다 — 줄 하나를 따로
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
        # 아무 줄도 고르지 않았을 때 — 일반(AI 읽기) 값 칸은 그 종류와 함께 걷어냈다(2026-10-28)
        self.empty_form = muted_label("지출 목록에서 한 줄을 고르면 그 폴더의 학생 명단이나 카드 결제 건이 여기에 보입니다.")
        self.empty_form.setWordWrap(True)
        self.empty_form.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.form_stack.addWidget(self.empty_form)
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
        """④ ERP 에 넣기 — 고른 지출 하나. 브라우저(로그인은 사람) · 미리 보기/시험 · [미리 보기]/[ERP 에 넣기] ·
        넣은 뒤 할 것([청구내역 대조]). [신청] 은 끝까지 사람."""
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
        self.test_mode.setToolTip("이미 올린 폴더로 시험할 때 켭니다. 대표적요 앞에 [시험] 을 붙여 넣고,\n"
                                  "ERP 결의서내역의 같은 청구서 확인과 앱의 넣은 기록 남기기를 건너뜁니다.\n"
                                  "시험으로 임시저장한 청구서는 ERP 에서 직접 지우세요. 앱을 다시 켜면 꺼집니다.")
        self.test_mode.toggled.connect(lambda _c: self._sync_buttons())
        options.addWidget(self.test_mode)
        # 팝업(소득자 · 국적)에서 결과가 하나로 확실하면 앱이 골라 [확인] 까지 — 애매하면 사람 (담당자 결정 2026-10-13)
        self.auto_pick = QCheckBox("팝업 자동 선택")
        self.auto_pick.setChecked(bool(settings.load().claim_auto_pick))
        self.auto_pick.setToolTip("소득자 · 국적 팝업에서 학번 · 국적이 맞는 결과가 하나뿐이면 앱이 고르고 [확인] 까지 누릅니다.\n"
                                  "여러 개이거나 정보가 모자라면 고르지 않고 두므로 직접 고르세요.")
        self.auto_pick.toggled.connect(lambda on: settings.update(claim_auto_pick=bool(on)))
        options.addWidget(self.auto_pick)
        self.fill_button = QPushButton("ERP 에 넣기")
        self.fill_button.setObjectName("primary")
        self.fill_button.clicked.connect(self._fill)
        # 명단 줄 — [신청] 전에 ERP 청구내역 표를 다시 읽어 명단과 맞춰 본다(읽기만). 넣기를 마치면 저절로도 한 번 한다.
        self.sheet_button = QPushButton("청구내역 대조")
        self.sheet_button.setToolTip("ERP 작성 화면의 청구내역 표를 읽어 명단과 맞춰 봅니다 — 두 번 들어간 사람 · 빠진 사람 · 다른 금액 ·\n"
                                     "명단에 없는 줄 · 합계와 공제합계. 읽기만 하고 아무것도 누르지 않습니다.")
        self.sheet_button.clicked.connect(self._check_sheet)
        # 첨부만 다시 올리기(임시저장 · 보완요청 청구서, 담당자 2026-10-23)는 따로 단추가 아니라 ② 의 '할 일' 로 고르고 fill_button 이 한다(_fill → _reattach)
        # 결과 창을 닫은 뒤에도 다시 본다 — 담당자 2026-11-11 "한번 닫으면 다시 내용을 확인할 수 없습니다". 폴더마다 최근 결과(result_store)
        self.result_button = QPushButton("결과 다시 보기")
        self.result_button.setToolTip("이 폴더를 ERP 에 넣은 결과 창(신청 전 확인할 것 · 넣은 값)을 다시 띄웁니다. 앱을 다시 켜도 남아 있습니다.")
        self.result_button.clicked.connect(self._reopen_result)
        # 다 넣은 카드 청구서를 처음부터 다시 — ERP 에서 그 청구서를 지운 뒤(담당자 2026-11-11: 결제 11건을 다 넣자 [ERP 에 넣기 (결제 0건)] 이
        # 꺼져 다시 넣을 길이 없었다). 앱의 저장 기록만 지운다 — ERP 청구서는 지우지 않는다
        self.card_reset_button = QPushButton("다시 넣기 — 저장 기록 지우기")
        self.card_reset_button.setToolTip("이 청구서의 결제 건을 ERP 에 임시저장했다는 앱 기록을 지워 처음부터 다시 넣게 합니다.\n"
                                          "먼저 ERP 결의서내역에서 그 청구서를 지우세요 — 앱은 ERP 청구서를 지우지 않습니다.")
        self.card_reset_button.clicked.connect(self._reset_card_sheet)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.open_button = QPushButton("브라우저 열기")
        self.open_button.setToolTip("앱이 연 브라우저에서 ERP 에 로그인하세요 — 결의서내역 · 새 청구서 화면은 앱이 띄웁니다")
        self.open_button.clicked.connect(lambda: self.browser.open_browser(scan=False, owner="claim"))
        row.addWidget(self.open_button)
        for button in (self.fill_button, self.sheet_button, self.result_button, self.card_reset_button):
            row.addWidget(button)
        row.addStretch(1)
        row.addLayout(options)
        step.add_layout(row)
        return step

    # ── 상태 ────────────────────────────────────────────────────────────
    def _kind(self, row: int) -> str:
        return self._kinds[row] if 0 <= row < len(self._kinds) else ""

    def _action(self, row: int) -> str:
        return self._actions[row] if 0 <= row < len(self._actions) else ACTION_FILL

    def _reattaching(self, row: int) -> bool:
        """그 줄의 할 일이 '첨부만 다시 올리기' 이고 할 수 있는 상태(카드가 아니고 폴더를 읽어 둠)인지."""
        return self._action(row) == ACTION_REATTACH and self._reattach_possible(row)

    def _sync_buttons(self) -> None:
        busy = self._erp_running
        can_edit = not busy
        for widget in (self.add_one_button, self.add_parent_button, self.add_kind, self.add_project):
            widget.setEnabled(can_edit)
        for card in self.kind_cards.values():
            card.setEnabled(can_edit)
        self.clear_button.setEnabled(can_edit and bool(self._dirs))
        self.table.setEnabled(not self._erp_running)          # 넣는 중에는 다른 줄로 옮기지 않게
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
            # ② 의 할 일이 '첨부만 다시 올리기' — 큰 단추가 그것을 한다(_fill → _reattach). 명단은 체크한 사람 수.
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
            done = [i for i in sheet.items if i.status == "saved"] if sheet else []
            if sheet is not None and done and not left:
                self.fill_button.setEnabled(False)
                self.fill_button.setText(f"ERP 에 넣기 (결제 {len(left)}건)")
                self.fill_button.setToolTip(f"이 청구서의 결제 {len(done)}건은 모두 ERP 에 임시저장했습니다"
                                            + (f"(결의번호 {sheet.req_cnt})" if sheet.req_cnt else "")
                                            + " — 같은 결제 건을 두 번 넣지 않게 꺼 두었습니다.\n처음부터 다시 넣으려면 ERP 에서 그 청구서를 지운 뒤 "
                                              "[다시 넣기 — 저장 기록 지우기] 를 누르세요.")
            elif dry:
                self.fill_button.setEnabled(bool(left) and not busy)
                self.fill_button.setText(f"미리 보기 (결제 {len(left)}건)")
                self.fill_button.setToolTip("고른 청구서의 결제 건마다 ERP 에 넣을 값을 표로 봅니다. 브라우저는 필요 없습니다.")
            else:
                reading = job is not None and self._card_ai_busy(job)
                self.fill_button.setEnabled(bool(left) and not busy and not self._browser_busy and self._browser_open and not reading)
                self.fill_button.setText(f"ERP 에 넣기 (결제 {len(left)}건)")
                self.fill_button.setToolTip("AI 가 영수증 · 회의록을 읽는 중입니다 — 끝나면 누를 수 있습니다." if reading else
                                            "" if self._browser_open else
                                            "먼저 [브라우저 열기] 로 ERP 를 열고 로그인하세요. 카드청구 화면은 앱이 띄웁니다.")
        elif is_sch:
            job = self._jobs[self._current]
            chosen = len(job.chosen()) if job is not None else 0
            self.fill_button.setEnabled(chosen > 0 and not busy and not self._browser_busy and (dry or self._browser_open))
            count = job.count_text() if job is not None else "0명"
            self.fill_button.setText(f"미리 보기 ({count})" if dry else f"ERP 에 넣기 ({count})")
            self.fill_button.setToolTip("" if dry or self._browser_open else "먼저 [브라우저 열기] 로 ERP 를 열고 새 청구서 화면을 띄우세요.")
            self.sheet_button.setEnabled(job is not None and self._browser_open and not busy and not self._browser_busy)
        else:
            self.fill_button.setEnabled(False)
            self.fill_button.setText("미리 보기" if dry else "ERP 에 넣기")
            self.fill_button.setToolTip("지출 목록에서 넣을 폴더를 고르세요.")
        self.sheet_button.setVisible(is_sch)
        card_sheet = self._card_sheet()
        self.card_reset_button.setVisible(bool(is_card and card_sheet is not None and any(i.status == "saved" for i in card_sheet.items)))
        self.card_reset_button.setEnabled(not busy and not self._browser_busy)
        results = self._results(self._current)
        self.result_button.setVisible(bool(results))
        self.result_button.setEnabled(not busy)
        self.result_button.setText("결과 다시 보기" + (f" ({len(results)})" if len(results) > 1 else ""))
        self._sync_put_state()
        self._sync_flow()

    def _ready(self, row: int) -> bool:
        """그 줄을 ERP 에 넣을 차례인지 — 명단 · 카드 폴더를 읽어 두었으면."""
        if not 0 <= row < len(self._dirs):
            return False
        kind = self._kind(row)
        if kind == kinds.CARD:
            return self._cards[row] is not None
        if kinds.uses_roster(kind):
            return self._jobs[row] is not None
        return False

    def _sync_flow(self) -> None:
        """할 차례인 단계만 — 폴더가 없으면 ① 만, 넣으면 ② 가(① 은 '지출 N건' 으로 접힘), 고른 줄을 넣을 수 있으면 ③ 이 떠오른다."""
        stage = claim_stage(bool(self._dirs), self._ready(self._current), self._kind_picked)
        keep = ("check",) + (("add",) if self._folders_open or self._kind_open else ()) + (("kind",) if self._kind_open else ())
        states = flow_states(CLAIM_ORDER, stage, keep_open=keep)
        where = self._guide_where if self._guide_where and states.get(self._guide_where) != HIDDEN else stage
        chosen = self.add_kind.currentData() or ""
        summaries = {"kind": kinds.name_of(chosen), "add": f"지출 {len(self._dirs)}건"}
        for key, step in self.steps.items():
            step.set_state(states[key], summaries.get(key))
            step.set_note(self._guide if key == where else "")
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
            card.set_selected(key == chosen and self._kind_picked)
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
        """머리의 상태 배지 + 단계 아래 한 줄. where 가 비면 지금 단계에."""
        self.state_pill.set_status(text, status)
        if guide is not None:
            self._set_guide(guide, where)

    def _set_guide(self, guide: str, where: str = "") -> None:
        self._guide = guide
        self._guide_where = where
        self._sync_flow()

    def _set_status(self, row: int, status: str) -> None:
        if row >= len(self._status):
            return
        self._status[row] = status
        text, tone = ROW_STATUS[status]
        item = QTableWidgetItem(text)
        item.setData(PillDelegate.ROLE, tone)
        self.table.setItem(row, COL_STATUS, item)

    def _refresh_row(self, row: int) -> None:
        data: dict = {}
        job = self._jobs[row] if row < len(self._jobs) else None
        if job is not None:
            # 장학금 — 적요는 대표적요, 금액은 넣을 사람 합계, 입금처 칸에는 사람 수
            chosen = job.chosen()
            data = {"summary": job.main_summary or "(대표적요 없음)",
                    "amount": sum(job.people[i].amount or 0 for i in chosen),
                    "payeeName": "학생 " + job.count_text(chosen)
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
        return self._erp_running or bool(self._ai_reading)

    def resumable(self) -> tuple[bool, str]:
        if self._erp_running:
            return True, "일반청구(장학금 · 카드 등)를 ERP 에 넣는 중"
        return False, ""

    # ── 폴더 목록 ────────────────────────────────────────────────────────
    def add_folder(self, path: str, kind: str | None = None) -> bool:
        """폴더 하나를 목록에 넣는다. kind 를 안 주면 ① 에서 고른 청구 종류로 — 고르지 않았으면 먼저 고르게 한다
        (전에는 '자동' 이 폴더 모양으로 정했다. 2026-10-28 종류가 셋이 되며 걷어냈다)."""
        path = os.path.abspath(path)
        if not os.path.isdir(path) or path in self._dirs or self._erp_running:
            return False
        if kind is None and not self._kind_picked:
            QMessageBox.information(self, "청구 종류", "먼저 ① 에서 청구 종류(장학금 · 혁신인재지원금 · 카드)를 고르세요.")
            return False
        chosen = kind or self.add_kind.currentData()
        try:
            kind = kinds.resolve(chosen, path)
        except ValueError as error:
            QMessageBox.information(self, "청구 종류", str(error))
            return False
        self._kind_picked = True
        self._kind_open = False
        self._dirs.append(path)
        self._status.append("waiting")
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
        if self._current < 0:
            self.table.selectRow(row)
        self._sync_buttons()
        return True

    def _start_dir(self) -> str:
        """폴더 고르기 창이 처음 여는 곳 — 카드면 바탕화면 '★★지출진행' 안의 '2. 카드'(설정 card_root 가 있으면 그것, 담당자 2026-11-11
        "카드청구에서 폴더고를때 바로 아래 폴더가 뜨도록"). 그 밖의 종류는 운영체제가 고른 곳."""
        if self.add_kind.currentData() == kinds.CARD:
            return folder_picker.work_root(work_folders.CARD, settings.load().card_root)
        return ""

    def _kind_ready(self) -> bool:
        """폴더를 고르기 전에 ① 의 청구 종류부터 — 여러 폴더를 고른 뒤 폴더마다 같은 알림이 뜨지 않게."""
        if self._kind_picked:
            return True
        QMessageBox.information(self, "청구 종류", "먼저 ① 에서 청구 종류(장학금 · 혁신인재지원금 · 카드)를 고르세요.")
        return False

    def _add_one(self) -> None:
        """폴더를 여러 개 골라 넣는다 — Ctrl · Shift 로 여러 개(담당자 2026-11-11 "폴더 여러개 선택가능하도록")."""
        if self._erp_running or not self._kind_ready():
            return
        title = ("카드 청구서 폴더 고르기 — 기간 폴더 안의 '03_[비목명] …' 폴더, Ctrl · Shift 로 여러 개" if self.add_kind.currentData() == kinds.CARD
                 else "지출 자료가 들어 있는 폴더 고르기 — Ctrl · Shift 로 여러 개")
        for path in folder_picker.pick_folders(self, title, self._start_dir()):
            self.add_folder(path)

    def _add_parent(self) -> None:
        if self._erp_running or not self._kind_ready():
            return
        parent = QFileDialog.getExistingDirectory(self, "여러 지출 폴더가 들어 있는 '상위' 폴더 선택", self._start_dir())
        if not parent:
            return
        subs = [os.path.join(parent, x) for x in sorted(os.listdir(parent)) if os.path.isdir(os.path.join(parent, x))]
        if not subs:
            QMessageBox.information(self, "안내", "선택한 폴더 안에 하위 폴더가 없습니다.")
            return
        for sub in subs:
            self.add_folder(sub)

    def _clear(self) -> None:
        if self._erp_running:
            return
        self._dirs, self._status, self._problems = [], [], []
        self._kinds, self._jobs, self._cards, self._projects, self._actions = [], [], [], [], []
        self._current = -1
        self._folders_open = False
        self._kind_open = False                # 고른 청구 종류는 남긴다 — 같은 종류의 폴더를 다시 넣는 일이 많다
        self.table.setRowCount(0)
        self._set_state("준비", "neutral", GUIDE_START)
        self._show_form(-1)
        self._sync_buttons()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if not self._erp_running and any(os.path.isdir(u.toLocalFile()) for u in event.mimeData().urls()):
            event.acceptProposedAction()
            self._set_drop_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_drop_active(False)
        if not self._kind_ready():
            return
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
            self.form_card.hint_label.setText("학생마다 인건비 탭에 넣고 [저장] 합니다. 빼고 싶은 학생은 체크를 푸세요.")
            self._set_wide_form(True)
            self.form_card.setEnabled(True)
            self._loading_form = False
            if not self.is_running():
                self._set_guide(GUIDE_REATTACH if self._reattaching(row) else
                                GUIDE_SCHOLARSHIP_AUTO if settings.load().auto_new_sheet else GUIDE_SCHOLARSHIP)
            return
        self.form_stack.setCurrentWidget(self.empty_form)
        self.form_card.title_label.setText("청구 내용")
        self.form_card.hint_label.setText("지출 목록에서 한 줄을 고르세요.")
        self._set_wide_form(False)
        self.form_card.setEnabled(False)
        self._loading_form = False

    # ── 멈추기 · 넣기 ────────────────────────────────────────────────────
    def _stop(self) -> None:
        if not self._erp_running:
            return
        self._stopping = True
        self.browser.request_stop()
        self.stop_button.setEnabled(False)
        self._set_state("멈추는 중", "warning", "지금 넣는 건(학생 · 결제 건)까지 마치고 멈춥니다…")

    def _fill(self) -> None:
        row = self._current
        if self._action(row) == ACTION_REATTACH:
            self._reattach(row)
            return
        if self._kind(row) == kinds.CARD:
            if self.dry_run.isChecked():
                self._preview_card(row)
            else:
                self._fill_card(row)
            return
        if kinds.uses_roster(self._kind(row)):
            self._fill_scholarship(row)

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

    def _load_card(self, row: int, quiet: bool = False) -> None:
        """카드 폴더를 읽는다(영수증 PDF 글자 · 회의록 · 물품 표). 글자로 못 읽는 증빙(영수증 사진 · 회의록 PDF)은 AI 로 읽도록 뒤 스레드에
        맡기고(card_ai), 끝나면 이 폴더를 다시 읽는다 — 그때는 AI 가 읽어 둔 것(캐시)을 쓴다."""
        job = card_mod.load_job(self._dirs[row], ai_lookup=self._ai_lookup)
        card_erp.restore(job)                      # 전에 넣은 결제 건 · 결의번호(_청구입력기록.json) — 다시 누르면 남은 것만
        self._queue_card_ai(job)
        self._cards[row] = job
        self._problems[row] = job.problems()
        self._set_status(row, "ai" if self._card_ai_busy(job) else
                         "read" if job.items and not self._problems[row] else "problem" if job.items else "failed")
        if quiet:
            return
        self._append_log("카드 폴더 읽음: " + " / ".join(job.summary_lines()))
        for item in job.items:                     # 회의록 PDF 를 글자로 읽었나 · 못 읽었으면 그 글 모양(이름 · 내용은 가림)
            for line in item.read_log:
                self._append_log(f"  {item.name}: {line}" if not line.startswith("    ") else line)
        for problem in self._problems[row]:
            self._append_log("  확인: " + problem)

    # ── 카드: AI 로 읽기 ──────────────────────────────────────────────────
    def _ai_lookup(self, folder: str, files: list[str]) -> dict | None:
        """card.read_item 이 결제 건마다 부른다 — 읽는 중 · 이번에 읽은 것 · 못 읽은 까닭 · 전에 읽어 둔 것(캐시) 차례로."""
        key = card_ai.folder_key(folder)
        if key in self._ai_reading:
            return {"reading": True}
        held = self._ai_results.get(key)
        if held is not None and held[0] == card_ai.signature(folder, files):
            return held[1] if isinstance(held[1], dict) else {"failed": held[1]}
        return card_ai.lookup(folder, files)

    def _card_ai_busy(self, job) -> bool:
        return any(card_ai.folder_key(item.folder) in self._ai_reading for item in job.items)

    def _queue_card_ai(self, job) -> None:
        """금액을 모르거나 회의 내용이 빈 결제 건을 AI 에 맡긴다(card_ai.needs). 이미 읽었거나 읽는 중이면 하지 않는다."""
        items = card_ai.pending(job)
        if not items:
            return
        platform = ai_status.instance().for_use("minutes")
        if platform.state == ai.MISSING:
            if not self._ai_missing_told:
                self._ai_missing_told = True
                self._append_log(f"카드: 금액 · 회의 내용을 모르는 결제 {len(items)}건 — 영수증 사진 · 회의록 PDF 는 AI(Claude Code)로 읽는데 "
                                 "이 PC 에서 쓸 수 없습니다(위쪽 AI 단추). 폴더 이름 끝에 '45,000원' 처럼 금액을 적어도 됩니다.")
            return
        for item in items:
            self._ai_reading.add(card_ai.folder_key(item.folder))
            item.ai_read = True
            item.notes.append(card_mod.AI_READING_NOTE)
        if self._card_ai_worker is None:
            from ..card_ai_worker import CardAiWorker
            self._card_ai_worker = CardAiWorker()
            self._card_ai_worker.log.connect(self._append_log)
            self._card_ai_worker.started.connect(self._on_card_ai_started)
            self._card_ai_worker.done.connect(self._on_card_ai_done)
            self._card_ai_worker.finished.connect(self._on_card_ai_finished)
        self._append_log(f"카드: 결제 {len(items)}건의 영수증 사진 · 회의록을 AI(Claude Code)로 읽습니다 — 건마다 수십 초. 끝나면 저절로 다시 읽습니다.")
        self._card_ai_worker.run([(item.folder, list(item.files)) for item in items])

    def _status_line(self, text: str = "") -> None:
        """창 아래 상태 줄 — 화면이 큰 창 안에 있을 때만(시험에서는 화면 하나가 창이다)."""
        bar = getattr(self.window(), "statusBar", None)
        if bar is None:
            return
        if text:
            bar().showMessage(text)
        else:
            bar().clearMessage()

    def _on_card_ai_started(self, _folder: str, number: int, total: int) -> None:
        self._status_line(f"카드 영수증 · 회의록을 AI 로 읽는 중 ({number}/{total})")

    def _on_card_ai_done(self, folder: str, result) -> None:
        key = card_ai.folder_key(folder)
        self._ai_reading.discard(key)
        files = card_mod._files_under(folder)
        self._ai_results[key] = (card_ai.signature(folder, files), result)
        for row, job in enumerate(self._cards):
            if job is None or not any(card_ai.folder_key(item.folder) == key for item in job.items):
                continue
            if self._erp_running and row == self._erp_row:
                continue                            # 넣는 중인 청구서는 바꾸지 않는다 — 끝난 뒤 [다시 읽기]
            sheet = self.card_panel.chosen_sheet() if row == self._current else -1
            self._load_card(row, quiet=True)
            self._refresh_row(row)
            if row == self._current:
                self._show_form(row)
                if 0 <= sheet < self.card_panel.sheet_box.count():
                    self.card_panel.sheet_box.setCurrentIndex(sheet)     # 보던 청구서 그대로
            if not self._card_ai_busy(self._cards[row]):
                self._append_log("카드 폴더 다시 읽음(AI 가 읽은 것으로): " + " / ".join(self._cards[row].summary_lines()))
                for problem in self._problems[row]:
                    self._append_log("  확인: " + problem)
        self._sync_buttons()

    def _on_card_ai_finished(self, fatal: str) -> None:
        self._status_line()
        if fatal == "login":
            # 담당자 PC 2026-11-11 16:24 — Claude Code 가 로그인돼 있지 않아 첫 건에서 멈췄고, 회의 시각 · 장소가 빈 채 남았다.
            # 기록 한 줄만으로는 몰라서 회의록 생성처럼 바로 묻고, 로그인되면 못 읽은 건을 저절로 다시 맡긴다(_on_ai_status)
            status = ai_status.instance()
            key = ai.chosen("minutes")
            status.mark(key, ai.NO_LOGIN, "카드 영수증 읽기에서 로그인이 풀림")
            self._ai_retry_on_login = True
            self._append_log("카드: Claude Code 로그인이 풀려 있어 영수증 사진 · 회의록을 읽지 못했습니다 — 로그인하면 저절로 다시 읽습니다.")
            if QMessageBox.question(
                    self, "Claude 로그인이 필요합니다",
                    f"{ai.short_label(key)} 에 로그인돼 있지 않아 영수증 사진 · 회의록 PDF 를 읽지 못했습니다.\n"
                    "(그래서 금액 · 회의 시각 · 장소가 비어 있습니다.)\n\n지금 로그인 창을 열까요?\n"
                    "로그인을 마치면 위쪽 AI 단추가 '로그인됨' 으로 바뀌고, 앱이 못 읽은 결제 건을 저절로 다시 읽습니다.",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
                status.login(self, key)
        elif fatal:
            self._append_log("카드: AI 로 다 읽지 못했습니다 — 위쪽 AI 단추에서 한도를 확인한 뒤 카드 패널의 [다시 읽기] 를 누르세요.")

    def _on_ai_status(self) -> None:
        """로그인이 풀려 못 읽은 결제 건이 있으면, 위쪽 AI 단추가 '로그인됨' 이 되는 대로 다시 맡긴다."""
        if not self._ai_retry_on_login or ai_status.instance().for_use("minutes").state != ai.OK:
            return
        self._ai_retry_on_login = False
        failed = {key for key, (_sig, result) in self._ai_results.items() if isinstance(result, str)}
        for key in failed:
            self._ai_results.pop(key, None)
        rows = [row for row, job in enumerate(self._cards)
                if job is not None and any(card_ai.folder_key(item.folder) in failed for item in job.items)
                and not (self._erp_running and row == self._erp_row)]
        if not rows:
            return
        self._append_log("카드: Claude 로그인이 확인돼 못 읽은 결제 건을 다시 읽습니다.")
        for row in rows:
            sheet = self.card_panel.chosen_sheet() if row == self._current else -1
            self._load_card(row, quiet=True)
            self._refresh_row(row)
            if row == self._current:
                self._show_form(row)
                if 0 <= sheet < self.card_panel.sheet_box.count():
                    self.card_panel.sheet_box.setCurrentIndex(sheet)
        self._sync_buttons()

    def _reload_card(self) -> None:
        row = self._current
        if not (0 <= row < len(self._cards)) or self._kinds[row] != kinds.CARD or self._erp_running:
            return
        job = self._cards[row]
        for item in job.items if job is not None else []:
            key = card_ai.folder_key(item.folder)
            if isinstance(self._ai_results.get(key, (None, {}))[1], str):
                self._ai_results.pop(key, None)    # 못 읽었던 것은 [다시 읽기] 때 다시 맡긴다(로그인 · 한도를 고친 뒤)
        self._load_card(row)
        self._refresh_row(row)
        self._show_form(row)
        self._sync_buttons()

    def _card_members(self, job, row: int = -1) -> list:
        """참여인력 명단 — 미리 보기용(넣을 때는 브라우저 스레드가 다시 읽는다). 지난번 넣을 때 기억해 둔 그 과제의 ERP 참여인력 목록이 먼저,
        그다음 설정의 참여연구원 명단 파일(session.card_members 와 같은 차례)."""
        path = part_mod.find_file(str(getattr(settings.load(), "participants_file", "") or ""), job.folder, os.path.dirname(job.folder))
        project = self._projects[row] if 0 <= row < len(self._projects) and self._projects[row] else self._last_project()
        from_erp, _at = part_mod.remembered(project)
        return part_mod.merged(from_erp, part_mod.read(path) if path else [])

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
                note = result.note if result.note and result.status != "saved" else ""
            review = review_of(item, result)
            count = f"{len(review)}건" if review else "—"
            rows.append(ReportRow(status, tone, [f"{item.used:%m-%d}" if item.used else "?", f"({item.req_div})" if item.req_div else "?",
                                                 item.title, _money(item.amount) or "모름", count],
                                  detail=item_detail(item, job.folder, result),
                                  html=(f"<p><b>{html.escape(note)}</b></p>" if note else "") + item_html(item, job.folder, result),
                                  tips={1: item.req_div_name, 2: item.title, 4: "\n".join(review) or "확인할 것 없음"}, right=(3, 4)))
        return rows

    def _preview_card(self, row: int) -> None:
        job = self._cards[row] if 0 <= row < len(self._cards) else None
        index = self.card_panel.chosen_sheet()
        if job is None or index < 0:
            return
        sheet = job.sheets[index]
        report = card_erp.run(None, None, job, sheet, lambda _m: None, ask=lambda _m: False, dry_run=True,
                              members=self._card_members(job, row), test_mode=self.test_mode.isChecked())
        self.card_panel.set_plans(index, report.results)
        show_report(self, title="미리 보기", heading=f"ERP 에 넣지 않았습니다 — 카드 {sheet.main_summary or '(비목 모름)'}", tone="info",
                    summary=[f"대표적요: {report.summary}", f"결제 {len(report.results)}건 · {sum(i.amount or 0 for i in sheet.items if i.status != 'saved'):,}원"]
                            + ([f"결의번호 {sheet.req_cnt} 에 이어서" ] if sheet.req_cnt else []),
                    columns=CARD_COLUMNS, rows=self._card_rows(job, sheet, report.results), side_detail=True, stretch=CARD_STRETCH,
                    detail_title="고른 결제 건 — 확인할 것 · ERP 에 넣을 값 · 읽은 곳",
                    notes=job.problems() + [f"읽지 않음: {s}" for s in job.skipped],
                    footer="왼쪽에서 결제 건을 고르면 오른쪽에 확인할 것 · ERP 에 넣을 값(칠한 줄이 볼 값) · 읽은 곳이 보입니다. 실제로 넣으려면 '미리 보기만' 체크를 풀고 "
                           "[ERP 에 넣기] 를 누르세요.")

    def _fill_card(self, row: int) -> None:
        job = self._cards[row] if 0 <= row < len(self._cards) else None
        index = self.card_panel.chosen_sheet()
        if job is None or index < 0 or self._erp_running or self._browser_busy or not self._browser_open:
            return
        sheet = job.sheets[index]
        left = [i for i in sheet.items if i.status != "saved"]
        hard = ([] if sheet.code else ["이 청구서의 비목을 모릅니다 — 청구서 폴더 이름을 '03_[비목명] …' 처럼 비목 번호로 시작하게 하세요"]) + \
               [f"{i.name}: " + " · ".join(i.blocking()) for i in left if i.blocking()]
        if hard:
            QMessageBox.warning(self, "넣기 전에 고칠 것", "\n".join("· " + p for p in hard) + "\n\n고친 뒤 [다시 읽기] 를 누르세요.")
            return
        test = self.test_mode.isChecked()
        plan = card_erp.run(None, None, job, sheet, lambda _m: None, ask=lambda _m: False, dry_run=True,
                            members=self._card_members(job, row), test_mode=test)
        self.card_panel.set_plans(index, plan.results)
        project = self._projects[row] if row < len(self._projects) else self._last_project()
        if not show_report(
                self, title="ERP 에 넣기", tone="warning",
                heading=f"결제 건 하나씩 넣고 [저장](임시저장) 합니다 — {len(left)}건 · [신청] 은 누르지 않습니다",
                summary=[f"대표적요: {plan.summary}", f"ERP 과제: {navigate.label_of(project)}"]
                        + ([f"결의번호 {sheet.req_cnt} 에 이어서 넣습니다"] if sheet.req_cnt else [])
                        + (["시험 — 대표적요 앞에 [시험]. 시험 청구서를 ERP 에서 지우기 전까지 그 결제 건은 미청구 카드내역에서 빠집니다."] if test else []),
                columns=CARD_COLUMNS, rows=self._card_rows(job, sheet, plan.results), notes=job.problems(),
                side_detail=True, stretch=CARD_STRETCH, detail_title="고른 결제 건 — 확인할 것 · ERP 에 넣을 값 · 읽은 곳",
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
        check = f" 신청 전 확인할 것 {len(review)}건 — 결과 창([결과 다시 보기])과 [진행 기록] 에 있습니다." if review else ""
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
            self._show_result(row, title="카드청구", tone="warning" if report.stopped or review else "success",
                        heading=f"임시저장 결제 {report.saved}건" + (" — 중간에 멈췄습니다" if report.stopped else "")
                                + (f" · 신청 전 확인할 것 {len(review)}건" if review else ""),
                        summary=[f"대표적요: {report.summary}"] + ([f"결의번호 {report.req_cnt}"] if report.req_cnt else [])
                                + ([report.blocked] if report.blocked else []),
                        columns=CARD_COLUMNS, rows=self._card_rows(job, sheet, report.results),
                        side_detail=True, stretch=CARD_STRETCH, detail_title="고른 결제 건 — 확인할 것 · ERP 에 넣은 값 · 읽은 곳",
                        notes=review or alerts, notes_title="신청 전 확인할 것" if review else "ERP 알림",
                        footer="ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다." + nxt)
        self._sync_buttons()

    # ── 카드 청구서 다시 넣기 ─────────────────────────────────────────────
    def _card_sheet(self):
        """지금 고른 줄이 카드면 카드 패널에서 고른 청구서(없으면 None)."""
        row = self._current
        if not (0 <= row < len(self._cards)) or self._kind(row) != kinds.CARD:
            return None
        job = self._cards[row]
        index = self.card_panel.chosen_sheet() if job is not None else -1
        return job.sheets[index] if job is not None and 0 <= index < len(job.sheets) else None

    def _reset_card_sheet(self) -> None:
        row = self._current
        sheet = self._card_sheet()
        if sheet is None or self._erp_running:
            return
        job = self._cards[row]
        done = sum(1 for i in sheet.items if i.status == "saved")
        number = f"결의번호 {sheet.req_cnt}" if sheet.req_cnt else "그 청구서"
        box = QMessageBox(QMessageBox.Warning, "다시 넣기 — 저장 기록 지우기",
                          f"'{sheet.main_summary}' 의 결제 {done}건을 ERP 에 임시저장했다는 앱 기록을 지웁니다.\n\n"
                          f"먼저 ERP 결의서내역에서 {number} 을(를) 지우셨나요? 앱은 ERP 청구서를 지우지 않습니다.\n"
                          "지우지 않고 다시 넣으면 그 결제 건은 미청구 카드내역에 없어(ERP 가 뺍니다) 넣지 못하고 결제 건마다 묻고,\n"
                          "넣기 전 결의서내역 확인에서 같은 대표적요의 청구서를 알립니다.", parent=self)
        forget = box.addButton("기록 지우기", QMessageBox.AcceptRole)
        box.addButton("취소", QMessageBox.RejectRole)
        box.setDefaultButton(box.buttons()[-1])
        box.exec()
        if box.clickedButton() is not forget:
            return
        count = card_erp.forget_sheet(job, sheet)
        self._append_log(f"카드청구 저장 기록을 지웠습니다 — 결제 {count}건을 다시 넣을 수 있습니다 ({number})")
        if 0 <= row < len(self._status):
            self._set_status(row, "read")
        self.card_panel.set_job(job)
        self._refresh_row(row)
        self._set_state("다시 넣기", "info", f"결제 {count}건을 다시 넣을 수 있습니다. ERP 에서 그 청구서를 지웠는지 확인하고 [ERP 에 넣기] 를 누르세요.")
        self._sync_buttons()

    # ── 결과 창 다시 보기 ───────────────────────────────────────────────
    def _results(self, row: int) -> list[dict]:
        return result_store.entries(self._dirs[row]) if 0 <= row < len(self._dirs) else []

    def _show_result(self, row: int, **kwargs) -> None:
        """넣은 뒤의 결과 창 — 띄우기 전에 그 폴더의 결과로 남긴다(닫은 뒤 [결과 다시 보기] 로 다시 본다)."""
        if 0 <= row < len(self._dirs):
            kept = dict(kwargs)
            # 장학금 결과의 '이 창을 닫으면 다음 폴더로 넘어갑니다' 는 그때만의 말 — 다시 볼 때는 뺀다
            kept["footer"] = str(kept.get("footer", "")).replace(NEXT_FOLDER_NOTE, "")
            why = result_store.save(self._dirs[row], str(kwargs.get("title", "")), str(kwargs.get("heading", "")), report_to_data(kept))
            if why:
                self._append_log("결과 창을 남기지 못했습니다(앱을 켜 둔 동안은 다시 볼 수 있음): " + why)
        show_report(self, **kwargs)
        self._sync_buttons()

    def _reopen_result(self) -> None:
        results = self._results(self._current)
        if not results:
            return
        if len(results) == 1:
            self._open_result(results[0])
            return
        menu = QMenu(self.result_button)
        for entry in results:
            menu.addAction(f"{entry.get('when', '')} · {entry.get('title', '')} — {entry.get('heading', '')}"[:110],
                           lambda e=entry: self._open_result(e))
        menu.exec(self.result_button.mapToGlobal(self.result_button.rect().bottomLeft()))

    def _open_result(self, entry: dict) -> None:
        try:
            show_report(self, **entry_report(entry))
        except Exception as error:  # noqa: BLE001 — 옛 판이 남긴 모양이 달라도 앱은 그대로
            QMessageBox.warning(self, "결과 다시 보기", "남겨 둔 결과를 띄우지 못했습니다: "
                                + (str(error).splitlines()[0][:120] if str(error) else type(error).__name__))

    def _row_kind_changed(self, _index: int) -> None:
        row = self._current
        if self._loading_form or not (0 <= row < len(self._dirs)) or self._erp_running:
            return
        kind = self.row_kind.currentData()
        if not kind or kind == self._kinds[row]:
            return
        self._kinds[row] = kind
        self._cards[row] = None
        if kind == kinds.CARD and row < len(self._actions):
            self._actions[row] = ACTION_FILL          # 카드 줄은 첨부만 다시 올리기를 아직 못 한다
        if kinds.uses_roster(kind):
            self._load_scholarship(row)
        else:
            self._jobs[row] = None
            self._load_card(row)
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
            # 넣기를 막는 것만(17절): 대표적요 없음 · 지급예정년월 꼴 · 표의 합계 불일치 · 사람 없음.
            # '…대표적요를 확인하세요' 같은 알림 글은 막지 않는다 — 전에는 '대표적요' 글자만 봐서 대표적요를 적은 뒤에도 막혔다
            hard = [p for p in problems if checks.as_note(p).level == checks.FIX]
            if hard:
                QMessageBox.warning(self, "넣기 전에 고칠 것", "\n\n".join(
                    f"· {checks.as_note(p).what}" + (f"\n   어디서: {checks.as_note(p).where}" if checks.as_note(p).where else "")
                    + (f"\n   할 일: {checks.as_note(p).todo}" if checks.as_note(p).todo else "") for p in hard))
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
            heading = (f"학생 한 명씩 넣고 [저장](임시저장) 합니다 — {job.count_text()} · "
                       "[신청] 은 누르지 않습니다")
            footer = ("앱이 확신하지 못하는 단계에서는 멈추고 위의 노란 띠로 묻습니다. "
                      + ("새 청구서 작성 화면이 없거나 다른 청구서가 떠 있으면 앱이 결의서내역의 [일반청구] 로 새로 띄웁니다."
                         if settings.load().auto_new_sheet else "브라우저에 새 청구서 작성 화면이 떠 있어야 합니다.")
                      + (f" 이 폴더를 끝내면 남은 명단 폴더 {len(waiting)}개도 하나씩 이어서 묻습니다." if waiting else ""))
        if not dry:
            notes, rows = scholarship_view(job, [sch.plan_person(job, i) for i in job.chosen()], problems)
            if not show_report(self, title="ERP 에 넣기", tone="warning", heading=heading,
                               summary=job.summary_lines(), columns=SCH_COLUMNS, stretch=SCH_STRETCH, rows=rows, notes=notes,
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
        # 명단 청구(장학금 · 혁신인재지원금)의 중복 확인 띠에서만 — 카드 넣기는 이 길을 잇지 않는다
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
                notes, rows = scholarship_view(job, report.results, job.problems())
                show_report(self, title="미리 보기", tone="info",
                            heading=f"ERP 에 넣지 않았습니다 — 이렇게 넣습니다 ({job.count_text([r.index for r in report.results])})",
                            summary=job.summary_lines(), columns=SCH_COLUMNS, stretch=SCH_STRETCH, rows=rows, notes=notes,
                            footer="첨부 파일 목록은 '첨부' 칸에 마우스를 올리면 보입니다. "
                                   "실제로 넣으려면 '미리 보기만' 체크를 풀고 [ERP 에 넣기] 를 누르세요.")
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
            check = f" 신청 전 확인할 것 {len(review)}건 — 결과 창([결과 다시 보기])과 [진행 기록] 에 있습니다." if review else ""
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
                # 넣은 뒤 볼 것 — 학생 줄의 '신청 전 확인' + 청구내역 대조. 표의 '확인' 칸 번호가 위 칸과 맞게 한 번에 번호를 매긴다
                notes, rows = scholarship_view(job, report.results, review_notes(report.results)
                                               + (check_notes(report.check.problems) if report.check is not None else []))
                self._show_result(row, title=f"{job.spec.name} 청구", tone="warning" if report.stopped or review else "success",
                            heading=f"임시저장 {saved_text}" + (" — 중간에 멈췄습니다" if report.stopped else "")
                                    + (f" · 신청 전 확인할 것 {len(review)}건" if review else ""),
                            summary=[f"대표적요: {job.main_summary}", f"지급예정년월: {job.pay_ym}"]
                                    + ([f"신청 전 대조: {report.check.heading()}"] if report.check is not None else [])
                                    + (["ERP 알림: " + " · ".join(alerts)] if alerts and review else []),
                            columns=SCH_COLUMNS, stretch=SCH_STRETCH, rows=rows,
                            notes=notes or alerts, notes_title="신청 전 확인할 것" if notes else "ERP 알림",
                            footer="ERP 에서 청구내역을 검토하고 [신청] 을 직접 누르세요 — 앱은 누르지 않습니다."
                                   + (" 위 '신청 전 확인할 것' 을 먼저 고치세요." if review else "")
                                   + (NEXT_FOLDER_NOTE if nxt is not None else ""))
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
        plan = reattach_mod.plan_for(kind, self._dirs[row], job=job, project_no=project)
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
                                + (f" 신청 전 확인할 것 {len(review)}건 — 결과 창([결과 다시 보기])에 있습니다." if review else ""))
            elif report.stopped:
                self._set_state("멈춤", "warning", f"{saved}줄까지 저장하고 멈췄습니다 — 결과 창의 까닭을 보고 다시 누르면 남은 줄을 합니다.")
            else:
                self._set_state("한 줄도 안 됨", "warning", "첨부를 다시 올린 줄이 없습니다 — 결과 창의 까닭을 보세요.")
            self._show_result(row, title="첨부만 다시 올리기 — 결과", tone="success" if saved and not report.stopped else "warning",
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

    def _on_browser_failed(self, owner: str, message: str) -> None:
        """브라우저 스레드의 오류 — 이 화면이 넣은 명령의 것만(받기 화면의 오류는 그 화면이 받는다)."""
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
        # ④ 까지 한 화면에 두면 ③ 의 칸이 좁다 — 흔한 창(1320×860)에서도 설명 줄은 접어 학생 표 · 결제 건 표에 자리를 준다
        self.form_card.hint_label.setVisible(height >= 860)

    def shutdown(self) -> None:
        if self._card_ai_worker is not None:
            self._card_ai_worker.shutdown()
        if self._erp_running:
            self.browser.request_stop()
        if self._owns_browser:
            self.browser.shutdown()
