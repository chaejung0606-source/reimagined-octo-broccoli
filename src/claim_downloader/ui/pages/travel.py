"""출장증빙자료 만들기 — 폴더 하나를 고르면 출장신청서를 검토해 출장자를 정리하고, 출장자별로 증빙을 확인해 '<이름> 출장증빙_yy.mm.dd.pdf' 를 만든다.

담당자 2026-10-27(첫 판) · 2026-11-10(지금 짜임, CLAUDE.md 28절):
    "1단계에는 출장증빙을 만들 폴더만 선택하고" · "어플에서 출장신청서를 검토 후 출장자를 정리, 그 다음 출장자별 증빙을 확인하고 정리" ·
    "출장증빙 파일명은 이름_체류증빙, 이름_하이패스 증빙, 이름_숙박비 증빙, 이름_대중교통 증빙" ·
    "하이패스가 있으면 자차를 이용한건데 이 경우 네이버지도 최단거리 사진과 KM정보를 출장증빙 양식에 적어야 함" ·
    "네이버지도 경로검색은 백그라운드에서 자동으로" · "목적지가 불분명해서 검색이 되지 않을경우 … 해당 출장자의 출장목적지를 입력해달라고 입력하는 박스".
    ① 폴더 → ② 출장신청서 검토 · 출장자(출장자 · 기간 · 출발지 · 출장지, 목적지가 분명하지 않으면 출장자마다 입력 칸) →
    ③ 출장자별 증빙(출장자마다 확인 표 · 항목별 증빙 표에 출장자 칸 · 하이패스가 있는 출장자의 네이버 지도 최단거리 가는 길 · 오는 길 · 총 km) →
    ④ 출장자마다 만들기.
신청서 읽기는 travel/application.py, 쪽 짜임 · 확인은 travel/model.py(Qt 없음), 그리기는 travel/render.py, 네이버 지도는 travel/navermap.py
(브라우저 스레드 · 앱 브라우저의 네이버 지도 탭 — ui/worker.py). ERP 는 쓰지 않는다. 덮어쓰지 않는다.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import settings
from ...travel import application, fuels, model, navermap
from ..art import Art
from ..tokens import COLORS
from ..travel_fuel_card import fuel_box
from ..travel_preview import MAKE as PREVIEW_MAKE
from ..travel_preview import PreviewPanel, TravelPreview
from ..flow import CURRENT, DONE, HIDDEN, OPEN, FlowArea, FlowStep
from ..log_button import LogSendButton
from ..widgets import Pill, WrapLabel, muted_label

FILE_FILTER = "증빙 파일 (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.webp)"
REGIONS = ("자동(출장지로)",) + tuple(model.LODGING_CAPS)

# 항목마다 표의 칸 — 마지막 칸 '출장자' 는 출장자가 둘 이상일 때만 보인다(담당자 2026-11-10 "출장자 구분하고")
# 체류 · 숙박의 '출장지' 칸은 출장지가 여러 곳일 때만 보인다(담당자 2026-10-27 "출장지가 한군데가 아닌 경우도 있습니다")
COLUMNS = {
    model.STAY: ("파일", "일자", "출장지", "가맹점 지역", "출장자"),
    model.PUBLIC: ("파일", "일자", "금액(원)", "이동편", "출발지", "목적지", "출장자"),
    model.TOLL: ("파일", "이용일자", "금액(원)", "출장자"),
    model.LODGING: ("파일", "입실일", "결제금액(원)", "박 수", "출장지", "출장자"),
    model.OTHER: ("파일", "일자", "내용", "출장자"),
}
PLACE_COL = {model.STAY: 2, model.LODGING: 4}
# 대중교통 증빙마다 꼭 있어야 할 칸 — 비어 있으면 칸을 칠해 확인을 부탁한다(담당자 2026-11-10 "불분명한 경우 확인요청하기")
PUBLIC_NEEDED = {2: "금액", 3: "이동편", 4: "출발지", 5: "목적지"}
SHOP_COL = 3              # 체류 영수증 가맹점의 시 · 군 — 출장지와 같아야 한다(담당자 2026-11-10)
NEEDED = {model.PUBLIC: PUBLIC_NEEDED, model.STAY: {SHOP_COL: "가맹점 지역"}}
UNCLEAR_ROLE = Qt.UserRole + 7


class _UnclearDelegate(QStyledItemDelegate):
    """확인할 칸을 칠하고 '확인 필요' 를 옅게 — 테마의 표 칸 규칙(::item)이 칸 배경색을 덮어서 칸마다 직접 칠한다."""

    def paint(self, painter, option, index) -> None:
        if index.data(UNCLEAR_ROLE):
            painter.save()
            painter.fillRect(option.rect, QColor(COLORS["warning_bg"]))
            if not str(index.data() or "").strip():
                painter.setPen(QColor(COLORS["warning"]))
                painter.drawText(option.rect.adjusted(8, 0, -8, 0), Qt.AlignVCenter | Qt.AlignLeft, "확인 필요")
            painter.restore()
        super().paint(painter, option, index)
HINTS = {
    model.STAY: "일자별 체류 영수증 — 출장이 7일 이하면 한 쪽부터 칸으로 나눠 담되, 영수증 글자가 작아지면 다음 쪽으로 넘겨 크게 둡니다. 8일 이상이면 일자마다 한 쪽. "
                "'가맹점 지역' 은 영수증 가맹점 주소의 시 · 군 — 출장지와 같은 시 · 군이어야 합니다(그림 영수증은 앱이 못 읽어 칠해 둡니다).",
    model.PUBLIC: "승차권 · 영수증 하나가 증빙 하나 — 일자별로 묶어 증빙마다 이동편 · 출발지 → 목적지 · 금액, 일자 합계와 실비 합계를 적습니다. "
                  "칠해진 칸은 앱이 못 읽은 것이니 확인해 적어 주세요.",
    model.TOLL: "하이패스 이용내역 — 하이패스가 있으면 자차입니다. 이용일자별로 묶어 그날 금액을 적고, 아래(자리가 모자라면 다음 쪽)에 네이버 지도 최단거리가 붙습니다.",
    model.LODGING: "숙박 영수증 — 숙박기간과 지원금액을 적습니다. 상한을 넘으면 지원금액은 상한금액입니다.",
    model.OTHER: "출장비 증빙 넷이 아닌데 파일 이름 앞에 이름이 붙은 것(참가확인서 · 공문 등) — 출장증빙 끝에 '기타 증빙' 으로 붙습니다. 일자는 없어도 됩니다.",
}
PEOPLE_COLUMNS = ("출장자", "체류", "대중교통", "하이패스", "숙박", "기타", "자차 최단거리", "확인할 것")
ROUTE_COLUMNS = ("출장자", "구간", "출발 → 목적지", "km", "지도 그림", "상태")
NAMING = "'이름_체류증빙' · '이름_하이패스 증빙' · '이름_숙박비 증빙' · '이름_대중교통 증빙'"
FUELS = model.FUELS


def _parse_day(text: str, year: int) -> date | None:
    return model.guess_day(text.strip(), year) if text.strip() else None


def _parse_int(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


def _parse_km(text: str) -> float | None:
    cleaned = "".join(ch for ch in (text or "") if ch.isdigit() or ch == ".")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


class EvidenceTable(QTableWidget):
    """항목 하나의 증빙 표 — 파일을 끌어다 놓거나 [파일 넣기]. 일자 · 금액 · 출장자는 짐작해 채우고 사람이 고친다."""

    changed = Signal()

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(0, len(COLUMNS[kind]), parent)
        self.kind = kind
        self.person_col = len(COLUMNS[kind]) - 1
        self.paths: list[Path] = []
        self.parts: list[int | None] = []          # 줄마다 PDF 의 몇 번째 영수증인지(하이패스 '총 N 건' 인쇄를 영수증마다 한 줄로)
        self.year = lambda: date.today().year      # 화면이 출장 시작일의 해로 바꿔 끼운다 — '0528' 같은 이름의 해
        self.places = lambda: []                   # 화면이 출장지 목록으로 바꿔 끼운다 — 파일 경로로 출장지를 짐작
        self.people = lambda: []                   # 화면이 출장자 목록으로 바꿔 끼운다 — 파일 이름 '이름_…' 으로 출장자를 짐작
        self.setHorizontalHeaderLabels(COLUMNS[kind])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.columnCount()):
            self.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setColumnHidden(self.person_col, True)
        if kind in NEEDED:
            self.setItemDelegate(_UnclearDelegate(self))
            for col in NEEDED[kind]:                   # 비어 있어도 '확인 필요' 가 보이는 폭
                self.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
                self.setColumnWidth(col, 104)
        self.itemChanged.connect(self._on_item)

    def _on_item(self, _item) -> None:
        self.mark_unclear()
        self.changed.emit()

    def mark_unclear(self) -> int:
        """대중교통 증빙의 빈 금액 · 출발지 · 목적지 칸, 체류 증빙의 빈 가맹점 지역 칸을 칠한다 — 칠한 줄 수."""
        if self.kind not in NEEDED:
            return 0
        rows = 0
        self.blockSignals(True)
        for row in range(self.rowCount()):
            missing = False
            for col, label in NEEDED[self.kind].items():
                item = self.item(row, col)
                if item is None:
                    item = QTableWidgetItem("")
                    self.setItem(row, col, item)
                empty = not item.text().strip()
                missing = missing or empty
                item.setData(UNCLEAR_ROLE, empty)
                item.setToolTip(f"{label}을(를) 확인해 적어 주세요" if empty else "")
            rows += missing
        self.blockSignals(False)
        return rows

    def add_files(self, paths: list[Path], year: int) -> None:
        self.blockSignals(True)
        for path in paths:
            if path in self.paths or path.suffix.lower() not in model.FILE_SUFFIXES:
                continue
            for ev in self._receipts(path, year):
                self._add_row(ev)
        self.blockSignals(False)
        self.mark_unclear()
        self.changed.emit()

    def _receipts(self, path: Path, year: int) -> list[model.Evidence]:
        """하이패스 인쇄 PDF 에 영수증이 여럿이면(일자 · 금액 수와 영수증 상자 수가 같을 때만) 영수증마다 한 줄 — 이용일자별로 묶이게."""
        if self.kind == model.TOLL and path.suffix.lower() == ".pdf":
            found = model.hipass_receipts(model.pdf_text(path, pages=50))
            if len(found) > 1:
                from ...travel import render
                if len(render.load_images(path)) == len(found):
                    return [model.Evidence(path=path, day=day, amount=amount, part=i) for i, (day, amount) in enumerate(found)]
        return [model.guess(path, year, route=self.kind == model.PUBLIC, stay=self.kind == model.STAY)]

    def _add_row(self, ev: model.Evidence) -> None:
        path = ev.path
        self.paths.append(path)
        self.parts.append(ev.part)
        row = self.rowCount()
        self.insertRow(row)
        name = QTableWidgetItem(path.name + (f" ({ev.part + 1}번째 영수증)" if ev.part is not None else ""))
        name.setFlags(name.flags() & ~Qt.ItemIsEditable)
        name.setToolTip(str(path))
        self.setItem(row, 0, name)
        self.setItem(row, 1, QTableWidgetItem(ev.day.isoformat() if ev.day else ""))
        if self.kind == model.OTHER:
            self.setItem(row, 2, QTableWidgetItem(model.other_label(path, self.people())))
        elif self.kind != model.STAY:
            self.setItem(row, 2, QTableWidgetItem(f"{ev.amount:,}" if ev.amount is not None else ""))
        if self.kind in PLACE_COL:
            self.setItem(row, PLACE_COL[self.kind], QTableWidgetItem(model.match_place(str(path), self.places())))
        if self.kind == model.PUBLIC:
            self.setItem(row, 3, QTableWidgetItem(model.mode_of(str(path))))
            self.setItem(row, 4, QTableWidgetItem(ev.origin))
            self.setItem(row, 5, QTableWidgetItem(ev.goal))
        elif self.kind == model.LODGING:
            self.setItem(row, 3, QTableWidgetItem("1"))
        elif self.kind == model.STAY:
            self.setItem(row, SHOP_COL, QTableWidgetItem(ev.shop_region))
        self.setItem(row, self.person_col, QTableWidgetItem(model.person_of(path, self.people())))

    def show_places(self, places: list[str]) -> None:
        """출장지가 여러 곳이면 출장지 칸을 보이고, 비어 있는 줄은 파일 경로로 다시 짐작한다."""
        if self.kind not in PLACE_COL:
            return
        col = PLACE_COL[self.kind]
        self.setColumnHidden(col, len(places) < 2)
        self.blockSignals(True)
        for row, path in enumerate(self.paths):
            item = self.item(row, col)
            if item is None or not item.text().strip():
                self.setItem(row, col, QTableWidgetItem(model.match_place(str(path), places)))
        self.blockSignals(False)

    def show_people(self, names: list[str]) -> None:
        """출장자가 둘 이상이면 출장자 칸을 보이고, 비어 있는 줄은 파일 이름('이름_…')으로 다시 짐작한다."""
        self.setColumnHidden(self.person_col, len(names) < 2)
        self.blockSignals(True)
        for row, path in enumerate(self.paths):
            item = self.item(row, self.person_col)
            if item is None or not item.text().strip() or (len(names) == 1 and item.text().strip() != names[0]):
                self.setItem(row, self.person_col, QTableWidgetItem(model.person_of(path, names)))
        self.blockSignals(False)

    def remove_selected(self) -> None:
        for row in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(row)
            del self.paths[row]
            del self.parts[row]
        self.changed.emit()

    def clear_all(self) -> None:
        self.setRowCount(0)
        self.paths.clear()
        self.parts.clear()
        self.changed.emit()

    def evidence(self, year: int) -> list[model.Evidence]:
        out = []
        for row, path in enumerate(self.paths):
            cell = lambda col, row=row: (self.item(row, col).text() if self.item(row, col) else "")  # noqa: E731
            ev = model.Evidence(path=path, day=_parse_day(cell(1), year), part=self.parts[row], person=cell(self.person_col).strip(),
                                ref=(self.kind, row))
            if self.kind == model.OTHER:
                ev.label = cell(2).strip()
            elif self.kind != model.STAY:
                ev.amount = _parse_int(cell(2))
            if self.kind in PLACE_COL:
                ev.place = cell(PLACE_COL[self.kind]).strip()
            if self.kind == model.PUBLIC:
                ev.mode = cell(3).strip()
                ev.origin, ev.goal = cell(4).strip(), cell(5).strip()
            elif self.kind == model.LODGING:
                ev.nights = max(1, _parse_int(cell(3)) or 1)
            elif self.kind == model.STAY:
                ev.shop_region = cell(SHOP_COL).strip()
            out.append(ev)
        return out

    # 끌어다 놓기
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = []
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                paths += sorted(p for p in path.rglob("*") if p.is_file())
            elif path.is_file():
                paths.append(path)
        self.add_files(paths, self.year())
        event.acceptProposedAction()


class FolderList(QListWidget):
    """① 의 폴더 목록 — 폴더 여러 개를 끌어다 놓을 수 있다. 체크한 폴더를 차례로 한다."""

    dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMinimumHeight(84)
        self.setMaximumHeight(200)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.dropped.emit([p for p in paths if p.is_dir()])
        event.acceptProposedAction()


class TravelPage(QWidget):
    def __init__(self, parent: QWidget | None = None, worker=None):
        super().__init__(parent)
        self.setObjectName("page")
        self.browser = worker                    # 네이버 지도 최단거리를 찾는 브라우저 스레드(app.session_worker) — 없으면 처음 쓸 때 만든다
        self._owns_browser = False
        self._stage = "folder"                   # folder → review → files(③ · ④ 함께)
        self._made: list[Path] = []
        self._apps: list[Path] = []              # 읽은 출장신청서 파일
        self._scan = model.Scan()
        self._done_folders: set[str] = set()     # 출장증빙을 만든 폴더(여러 폴더를 차례로 할 때)
        self._review: application.Application | None = None
        self._goal_of: dict[str, str] = {}       # 출장자마다 출장목적지(신청서 목적지가 분명하지 않아 사람이 적은 것)
        self._ask_reason: dict[str, str] = {}    # 출장자마다 목적지를 묻는 까닭(네이버 지도에서 못 찾음 등)
        self._fuel_of: dict[str, str] = {}       # 자차 출장자마다 연료 종류(담당자 2026-11-10 "자차의 경우 연료 종류도 증빙에 입력")
        self._route_checked = False              # 자차 경로(출발지 · 경유지 · 목적지 · 연료)를 사람이 확인했는지 — 바뀌면 다시 확인
        self._routes: dict[tuple, dict] = {}     # (출장자, 구간 번호) → {origin, goal, label, km, image, status}
        self._searching: set = set()
        self._auto_routes = True                 # ③ 이 열리면 저절로 찾는다 — 한 번 찾은 구간은 다시 찾지 않는다
        self.tables: dict[str, EvidenceTable] = {}
        self._log = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        self.step_folder = self._build_folder()
        self.step_info = self._build_info()
        self.step_files = self._build_files()
        self.step_make = self._build_make()
        self.step_preview = self._build_preview()
        self.area = FlowArea()
        self.area.add(self.step_folder)
        self.area.add(self.step_info)
        self.area.add(self.step_files, 1)
        self.area.add(self.step_make)
        self.area.add(self.step_preview)
        layout.addWidget(self.area, 1)
        if self.browser is not None:
            self.browser.routes_found.connect(self._on_routes)
        self._sync()

    # ── 기록 · 브라우저 ────────────────────────────────────────────────────
    def log(self, message: str) -> None:
        if self._log is None:
            from ...session import file_logger
            self._log = file_logger(lambda _m: None)
        self._log(message)

    def _worker(self):
        if self.browser is None:
            from ..worker import SessionWorker
            self.browser = SessionWorker()
            self._owns_browser = True
            self.browser.routes_found.connect(self._on_routes)
        return self.browser

    # ── 구성 ────────────────────────────────────────────────────────────
    def _build_head(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("travel", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("출장증빙자료 만들기")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label("폴더를 고르면 출장신청서로 출장자를 정리하고, 출장자별로 증빙을 확인해 '<이름> 출장증빙_yy.mm.dd.pdf' 를 만듭니다."))
        head.addLayout(texts, 1)
        self.state_pill = Pill("준비", "neutral")
        head.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        head.addWidget(LogSendButton("출장증빙자료 만들기"), 0, Qt.AlignVCenter)
        return head

    def _build_folder(self) -> FlowStep:
        """① 폴더만 — 담당자 2026-11-10 "1단계에는 출장증빙을 만들 폴더만 선택하고" · "여러 폴더를 선택할 수 있도록".
        넣은 폴더들은 차례로 하나씩 ② → ③ → ④ 를 거친다(폴더마다 출장신청서 · 출장자 · 증빙이 다르다)."""
        step = FlowStep("1", "출장증빙을 만들 폴더를 고르세요",
                        f"보통 '출장비 지급(…)' 폴더 — 출장신청서와 증빙 파일({NAMING})이 든 폴더. 여러 개면 모두 넣으세요(끌어다 놓아도 됩니다) — "
                        "차례로 하나씩 만들고, 만든 출장증빙은 그 폴더에 둡니다.")
        self.folder_edit = QLineEdit()           # 지금 하는 폴더(화면에는 목록으로 보인다)
        self.folder_edit.hide()
        self.folder_list = FolderList()
        self.folder_list.dropped.connect(lambda paths: self._add_folders(paths, start=True))
        self.folder_list.itemChanged.connect(lambda _item: self._sync())
        self.folder_list.itemDoubleClicked.connect(lambda item: self.load_folder(item.data(Qt.UserRole)))
        step.add(self.folder_list)
        row = QHBoxLayout()
        add = QPushButton("폴더 추가")
        add.setObjectName("primary")
        add.clicked.connect(self._pick_folder)
        parent = QPushButton("상위 폴더에서 여러 개")
        parent.setToolTip("고른 폴더 바로 아래에서 출장신청서나 증빙 파일이 든 폴더를 모두 넣습니다")
        parent.clicked.connect(self._pick_parent)
        drop = QPushButton("고른 줄 빼기")
        drop.setObjectName("ghost")
        drop.clicked.connect(self._drop_folders)
        self.start_button = QPushButton("")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_folders)
        row.addWidget(add)
        row.addWidget(parent)
        row.addWidget(drop)
        row.addStretch(1)
        row.addWidget(self.start_button)
        step.add_layout(row)
        self.folder_note = muted_label("")
        step.add(self.folder_note)
        step.edit.connect(lambda: self._go("folder"))
        return step

    # ── 여러 폴더 ──────────────────────────────────────────────────────────
    def _add_folders(self, paths, start: bool = False) -> int:
        """폴더들을 목록에 더한다(체크된 채, 이미 있으면 그대로). start 면 넣은 것이 하나뿐이고 하던 폴더가 없을 때 바로 시작."""
        known = {self.folder_list.item(i).data(Qt.UserRole) for i in range(self.folder_list.count())}
        added = 0
        self.folder_list.blockSignals(True)
        for path in paths:
            path = Path(path)
            if not path.is_dir() or str(path) in known:
                continue
            item = QListWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setData(Qt.UserRole, str(path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.folder_list.addItem(item)
            known.add(str(path))
            added += 1
        self.folder_list.blockSignals(False)
        self._mark_folders()
        if start and len(self._folders()) == 1 and not self.folder_edit.text().strip():
            self.load_folder(self._folders()[0])
        self._sync()
        return added

    def _folders(self, checked: bool = True) -> list[str]:
        return [self.folder_list.item(i).data(Qt.UserRole) for i in range(self.folder_list.count())
                if not checked or self.folder_list.item(i).checkState() == Qt.Checked]

    def _pick_parent(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "출장 폴더들이 든 상위 폴더", self.folder_edit.text() or "")
        if not path:
            return
        found = [d for d in sorted(Path(path).iterdir()) if d.is_dir() and model.looks_like_trip(d)]
        added = self._add_folders(found)
        self.folder_note.setText(f"'{Path(path).name}' 아래에서 출장 폴더 {added}개를 넣었습니다 — 만들지 않을 폴더는 체크를 푸세요."
                                 if found else f"'{Path(path).name}' 바로 아래에 출장신청서나 증빙 파일이 든 폴더가 없습니다.")

    def _drop_folders(self) -> None:
        current = self.folder_edit.text().strip()
        for item in self.folder_list.selectedItems():
            if item.data(Qt.UserRole) == current:
                continue                          # 지금 하는 폴더는 빼지 않는다
            self.folder_list.takeItem(self.folder_list.row(item))
        self._sync()

    def _start_folders(self) -> None:
        current = self.folder_edit.text().strip()
        if current and current not in self._done_folders:
            self._go("review")
            return
        nxt = self._next_folder(from_start=not current)
        if nxt:
            self.load_folder(nxt)

    def _next_folder(self, from_start: bool = False) -> str:
        """다음에 할 폴더 — 체크된 것 중 아직 만들지 않은 것, 지금 폴더 다음부터(없으면 처음부터)."""
        folders = self._folders()
        current = self.folder_edit.text().strip()
        if not from_start and current in folders:
            folders = folders[folders.index(current) + 1:] + folders[:folders.index(current)]
        return next((f for f in folders if f not in self._done_folders and (from_start or f != current)), "")

    def _mark_folders(self) -> None:
        """목록에 지금 하는 폴더(굵게) · 만든 폴더(✓)를 표시."""
        current = self.folder_edit.text().strip()
        self.folder_list.blockSignals(True)
        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            path = item.data(Qt.UserRole)
            name = Path(path).name
            item.setText(("✓ " if path in self._done_folders else "") + name + ("  — 지금" if path == current else ""))
            font = item.font()
            font.setBold(path == current)
            item.setFont(font)
        self.folder_list.blockSignals(False)

    def _build_info(self) -> FlowStep:
        """② 출장신청서 검토 · 출장자 정리."""
        step = FlowStep("2", "출장신청서 검토 · 출장자", "앱이 출장신청서에서 읽은 값입니다. 틀린 곳은 고치세요 — 출장자가 여럿이면 쉼표로.")
        self.review_label = WrapLabel("")
        self.review_label.setObjectName("body")
        step.add(self.review_label)
        # 신청서에 출장이 여럿이면 — 저장 폴더 이름의 날짜로 고른 출장, 사람이 바꿀 수 있다(담당자 2026-11-10)
        self.trip_row = QWidget()
        trip_line = QHBoxLayout(self.trip_row)
        trip_line.setContentsMargins(0, 0, 0, 0)
        trip_line.addWidget(QLabel("신청서의 출장"))
        self.trip_box = QComboBox()
        self.trip_box.currentIndexChanged.connect(self._on_trip_choice)
        trip_line.addWidget(self.trip_box, 1)
        self.trip_row.hide()
        step.add(self.trip_row)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 홍길동 — 여러 명이면 쉼표로: 홍길동, 김철수")
        today = QDate.currentDate()
        self.start_edit = QDateEdit(today)
        self.end_edit = QDateEdit(today)
        for edit in (self.start_edit, self.end_edit):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
            edit.dateChanged.connect(self._on_dates)
        # 출발지는 늘 사업단 자리로 채워 둔다(담당자 2026-10-27) — 다른 곳에서 떠나는 출장만 고친다
        self.origin_edit = QLineEdit(settings.load().travel_origin)
        self.origin_edit.setPlaceholderText("예: 강원대학교 춘천캠퍼스")
        self.origin_edit.textChanged.connect(self._on_route_inputs)
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("예: 연세대학교 원주캠퍼스 — 여러 곳이면 다닌 차례대로 쉼표로")
        self.dest_edit.textChanged.connect(self._on_places)
        self.region_box = QComboBox()
        self.region_box.addItems(REGIONS)
        self.region_box.currentIndexChanged.connect(self._on_region)
        self.cap_spin = QSpinBox()
        self.cap_spin.setRange(0, 1_000_000)
        self.cap_spin.setSingleStep(10_000)
        self.cap_spin.setSuffix(" 원")
        self.cap_spin.setGroupSeparatorShown(True)
        self.people_spin = QSpinBox()
        self.people_spin.setRange(1, 20)
        self.people_spin.setSuffix(" 명")
        rows = (("출장자", self.name_edit), ("출장기간", self._pair(self.start_edit, "~", self.end_edit)),
                ("출발지", self.origin_edit), ("출장지(목적지)", self.dest_edit))
        for i, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(widget, i, 1)
        step.add_layout(grid)
        step.add(self._build_goal_box())
        step.add(self._build_car_box())
        buttons = QHBoxLayout()
        self.app_button = QPushButton("출장신청서 열기")
        self.app_button.setObjectName("ghost")
        self.app_button.clicked.connect(lambda: self._apps and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._apps[0]))))
        buttons.addWidget(self.app_button)
        buttons.addStretch(1)
        self.info_next = QPushButton("다음 — 출장자별 증빙 확인")
        self.info_next.setObjectName("primary")
        self.info_next.clicked.connect(lambda: self._go("files"))
        buttons.addWidget(self.info_next)
        step.add_layout(buttons)
        step.edit.connect(lambda: self._go("review"))
        self.name_edit.textChanged.connect(self._on_people)
        return step

    def _build_goal_box(self) -> QWidget:
        """출장목적지 입력 칸 — 신청서 목적지가 분명하지 않거나 네이버 지도에서 찾지 못하면 그 출장자의 목적지를 묻는다
        (담당자 2026-11-10 "해당 출장자의 출장목적지를 입력해달라고 입력하는 박스 생성해서 요청하기"). 길찾기가 필요한 출장자(하이패스 · 자차)만."""
        self.goal_box = QFrame()
        self.goal_box.setObjectName("notice")
        rows = QVBoxLayout(self.goal_box)
        rows.setContentsMargins(14, 10, 14, 10)
        rows.setSpacing(6)
        self.goal_note = WrapLabel("")
        self.goal_note.setObjectName("noticeText")
        rows.addWidget(self.goal_note)
        self.goal_rows = QGridLayout()
        self.goal_rows.setHorizontalSpacing(8)
        rows.addLayout(self.goal_rows)
        self.goal_edits: dict[str, QLineEdit] = {}
        self.goal_box.hide()
        return self.goal_box

    def _build_car_box(self) -> QWidget:
        """자차 경로 확인 — 하이패스(자차) 증빙이 있으면 출발지 · 경유지 · 목적지와 연료를 꼭 확인해야 ③ 으로 넘어간다
        (담당자 2026-11-10 "자차 증빙이 있는 경우에는 출발지와 목적지, 경유지가 있는지 필수로 확인하고 넘어가기" ·
        "경유지가 있는 경우 어플 사용자가 경유지를 추가할 수 있도록" · "자차의 경우 연료 종류도 증빙에 입력")."""
        self.car_box = QFrame()
        self.car_box.setObjectName("notice")
        rows = QVBoxLayout(self.car_box)
        rows.setContentsMargins(14, 10, 14, 10)
        rows.setSpacing(6)
        self.car_note = WrapLabel("")
        self.car_note.setObjectName("noticeText")
        rows.addWidget(self.car_note)
        self.via_rows = QVBoxLayout()
        self.via_rows.setSpacing(4)
        rows.addLayout(self.via_rows)
        self.via_edits: list[QLineEdit] = []
        add = QPushButton("경유지 추가")
        add.setToolTip("들른 곳이 있으면 다닌 차례대로 더하세요 — 경유지가 있으면 구간마다 지도 그림과 거리를 넣습니다")
        add.clicked.connect(lambda: self._add_via(""))
        rows.addWidget(add, 0, Qt.AlignLeft)
        self.fuel_rows = QGridLayout()
        self.fuel_rows.setHorizontalSpacing(8)
        rows.addLayout(self.fuel_rows)
        self.fuel_boxes: dict[str, QComboBox] = {}
        self.route_summary = WrapLabel("")
        self.route_summary.setObjectName("body")
        rows.addWidget(self.route_summary)
        self.route_ok = QCheckBox("출발지 · 경유지 · 목적지와 연료를 확인했습니다")
        self.route_ok.toggled.connect(self._on_route_ok)
        rows.addWidget(self.route_ok)
        self.car_box.hide()
        return self.car_box

    def _add_via(self, text: str) -> None:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(8)
        edit = QLineEdit(text)
        edit.setPlaceholderText("경유지 — 예: 원주시청")
        edit.textChanged.connect(self._on_route_inputs)
        drop = QPushButton("빼기")
        drop.setObjectName("ghost")
        line.addWidget(QLabel(f"경유지 {len(self.via_edits) + 1}"))
        line.addWidget(edit, 1)
        line.addWidget(drop)
        self.via_rows.addWidget(row)
        self.via_edits.append(edit)
        drop.clicked.connect(lambda: self._drop_via(row, edit))
        self._on_route_inputs()

    def _drop_via(self, row: QWidget, edit: QLineEdit) -> None:
        if edit in self.via_edits:
            self.via_edits.remove(edit)
        row.deleteLater()
        self._on_route_inputs()

    def _vias(self) -> list[str]:
        return [e.text().strip() for e in self.via_edits if e.text().strip()]

    def _sync_fuel_rows(self, drivers: list[str]) -> None:
        for name in list(self.fuel_boxes):
            if name not in drivers:
                box = self.fuel_boxes.pop(name)
                box.parentWidget().deleteLater() if box.parentWidget() is not self.car_box else box.deleteLater()
        for name in drivers:
            if name in self.fuel_boxes:
                continue
            # 설정의 '출장 차량 연료' 에 그 이름이 있으면 미리 고른다(이름으로 사람을 구별 — 담당자 2026-11-10)
            saved = model.parse_fuels(settings.load().travel_fuels).get(name, "")
            if saved and not self._fuel_of.get(name):
                self._fuel_of[name] = saved
            # 보기는 ERP 출장 교통비 창의 '연비/전비/수소' 보기(travel/fuels.py — 화면 구조 기록에서)
            box = fuel_box(fuels.options()[0], self._fuel_of.get(name, ""))
            box.currentIndexChanged.connect(lambda _i, n=name, b=box: self._set_fuel(n, b.currentData() or ""))
            holder = QWidget()
            line = QHBoxLayout(holder)
            line.setContentsMargins(0, 0, 0, 0)
            line.addWidget(QLabel(f"{name} 차량 연료" if name != "출장자" else "차량 연료"))
            line.addWidget(box)
            line.addStretch(1)
            self.fuel_rows.addWidget(holder, self.fuel_rows.rowCount(), 0)
            self.fuel_boxes[name] = box

    def _set_fuel(self, name: str, fuel: str, recheck: bool = True) -> None:
        self._fuel_of[name] = fuel
        if fuel and name != "출장자":
            # 고른 연료는 설정에도 남긴다 — 다음 출장에 그 사람이 자차면 미리 골라 둔다
            fuels = model.parse_fuels(settings.load().travel_fuels)
            if fuels.get(name) != fuel:
                fuels[name] = fuel
                settings.update(travel_fuels=model.format_fuels(fuels))
        if recheck:
            self._uncheck_route()
        # 확인 칸 · '아직 빈 것' 줄도 다시 — 전에는 연료를 골라도 그대로라 확인 칸이 꺼진 채 눌리지 않았다(담당자 2026-11-10 "체크가 안됩니다")
        self._sync_car_box()
        self._sync()

    def _uncheck_route(self) -> None:
        """자차 경로가 바뀌면 다시 확인받는다."""
        if self._route_checked:
            self._route_checked = False
            self.route_ok.blockSignals(True)
            self.route_ok.setChecked(False)
            self.route_ok.blockSignals(False)

    def _on_route_ok(self, on: bool) -> None:
        self._route_checked = bool(on)
        self._sync()

    def _car_missing(self) -> list[str]:
        """자차 경로 확인에서 아직 빈 것 — 이것이 있으면 확인 칸을 켤 수 없다."""
        drivers = self._drivers()
        if not drivers:
            return []
        out = []
        if not self.origin_edit.text().strip():
            out.append("출발지")
        need = self._needs_goal()
        if need:
            out.append("출장목적지(" + ", ".join(need) + ")")
        elif not all(self._goal(n) or len(self._places()) > 1 for n in drivers):
            out.append("목적지")
        missing_fuel = [n for n in drivers if not self._fuel_of.get(n)]
        if missing_fuel:
            out.append("연료" + (f"({', '.join(missing_fuel)})" if len(drivers) > 1 else ""))
        return out

    def _sync_car_box(self) -> None:
        drivers = self._drivers()
        self.car_box.setVisible(bool(drivers))
        if not drivers:
            return
        self._sync_fuel_rows(drivers)
        missing = self._car_missing()
        who = ", ".join(n for n in drivers if n != "출장자")
        self.car_note.setText(f"자차 경로 확인 — 하이패스 증빙이 있어 자차입니다{f'({who})' if who else ''}. 출발지 · 경유지(있을 때만 [경유지 추가]) · "
                              "목적지와 차량 연료를 확인해야 다음으로 넘어갑니다. 경유지가 없으면 지도 그림 하나(오는 길은 같은 거리)입니다.")
        lines = []
        for name in drivers:
            legs = self._legs_for(name)
            path = " → ".join([legs[0][0] or "?"] + [b or "?" for _, b, _ in legs])
            if len(legs) == 1:
                path += f" → {legs[0][0] or '?'}"
            lines.append((f"{name}: " if len(drivers) > 1 or name != "출장자" else "") + path)
        self.route_summary.setText("경로: " + " / ".join(lines) + (f"\n아직 빈 것: {', '.join(missing)}" if missing else ""))
        self.route_ok.setEnabled(not missing)
        self.route_ok.setToolTip(f"먼저 채우세요: {', '.join(missing)}" if missing else "")
        if missing:
            self._uncheck_route()

    @staticmethod
    def _pair(*items) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for item in items:
            row.addWidget(QLabel(item) if isinstance(item, str) else item, 1 if isinstance(item, QLineEdit) else 0)
        row.addStretch(0)
        return box

    def _build_files(self) -> FlowStep:
        step = FlowStep("3", "출장자별 증빙 확인", f"폴더의 증빙을 출장자마다 나눴습니다(파일 이름 {NAMING}). 출장자마다 확인할 것을 보고, "
                        "틀린 곳은 아래 표에서 고치세요 — 출장자 칸에 '공통' 이라 적으면 모두의 출장증빙에 들어갑니다.")
        self.people_table = QTableWidget(0, len(PEOPLE_COLUMNS))
        self.people_table.setHorizontalHeaderLabels(PEOPLE_COLUMNS)
        self.people_table.verticalHeader().hide()
        self.people_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.people_table.horizontalHeader().setSectionResizeMode(len(PEOPLE_COLUMNS) - 1, QHeaderView.Stretch)
        for col in range(len(PEOPLE_COLUMNS) - 1):
            self.people_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.people_table.setMinimumHeight(90)
        step.add(self.people_table)
        top = QHBoxLayout()
        rescan = QPushButton("폴더에서 다시 읽기")
        rescan.setToolTip("표를 비우고 폴더의 증빙 파일을 다시 나눠 넣습니다")
        rescan.clicked.connect(self._rescan)
        top.addWidget(rescan)
        self.scan_note = muted_label("")
        top.addWidget(self.scan_note, 1)
        step.add_layout(top)
        for kind in model.KINDS:
            table = EvidenceTable(kind)
            table.changed.connect(self._on_evidence)
            table.year = self._year
            table.places = self._places
            table.people = self._names
            self.tables[kind] = table
            head = QHBoxLayout()
            # 체류만 늘 있고 교통비 · 숙박은 출장마다 있을 수도 없을 수도 있다(담당자 2026-10-27 "숙박은 있을 수도 있고 없을 수도")
            name = QLabel(model.KIND_NAMES[kind] + ("" if kind == model.STAY else " (있을 때만)"))
            name.setObjectName("cardTitle")
            head.addWidget(name, 0, Qt.AlignVCenter)
            head.addWidget(muted_label(HINTS[kind]), 1, Qt.AlignVCenter)
            add = QPushButton("파일 넣기")
            add.clicked.connect(lambda _=False, k=kind: self._add_files(k))
            remove = QPushButton("고른 줄 빼기")
            remove.setObjectName("ghost")
            remove.clicked.connect(table.remove_selected)
            head.addWidget(add)
            head.addWidget(remove)
            step.add_layout(head)
            step.add(table)
            if kind == model.TOLL:
                step.add(self._build_route())
            if kind == model.LODGING:
                step.add(self._build_lodging())
        self._on_places()
        return step

    def _build_lodging(self) -> QWidget:
        """숙박 상한 칸 — 숙박 영수증을 넣었을 때만 보인다(담당자 2026-10-27)."""
        self.lodging_box = QWidget()
        rows = QVBoxLayout(self.lodging_box)
        rows.setContentsMargins(0, 0, 0, 6)
        rows.setSpacing(4)
        rows.addWidget(self._pair("숙박 상한 지역", self.region_box, "1박 상한", self.cap_spin, "공동숙박", self.people_spin))
        self.cap_note = muted_label("")
        rows.addWidget(self.cap_note)
        self.lodging_box.hide()
        return self.lodging_box

    def _build_route(self) -> QWidget:
        """자차(하이패스가 있는 출장자) — 네이버 지도 최단거리(거리우선) 그림과 가는 길 · 오는 길 km. 앱이 앱 브라우저의 네이버 지도 탭에서 저절로 찾는다(네이버가 보안문자를 물으면 그 창에서 사람이 입력)."""
        self.route_box = QWidget()
        rows = QVBoxLayout(self.route_box)
        rows.setContentsMargins(0, 0, 0, 6)
        rows.setSpacing(6)
        title = QLabel("자차 이동경로 — 네이버 지도 최단거리")
        title.setObjectName("cardTitle")
        rows.addWidget(title)
        rows.addWidget(muted_label("하이패스가 있는 출장자는 자차입니다. 앱이 네이버 지도에서 출발지 → 출장목적지의 거리우선 경로를 찾아 지도 그림과 km 를 "
                                   "채웁니다(화면에 브라우저가 뜨지 않습니다). 목적지가 하나면 그림 하나 — 오는 길은 같은 거리로 적고, 경유지가 있으면 "
                                   "구간마다 그림과 거리. km 는 표에서 고칠 수 있습니다."))
        self.route_table = QTableWidget(0, len(ROUTE_COLUMNS))
        self.route_table.setHorizontalHeaderLabels(ROUTE_COLUMNS)
        self.route_table.verticalHeader().hide()
        self.route_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.route_table.horizontalHeader().setSectionResizeMode(len(ROUTE_COLUMNS) - 1, QHeaderView.Stretch)
        for col in range(len(ROUTE_COLUMNS) - 1):
            self.route_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.route_table.setMinimumHeight(90)
        self.route_table.itemChanged.connect(self._on_route_edited)
        rows.addWidget(self.route_table)
        buttons = QHBoxLayout()
        self.route_find = QPushButton("최단거리 다시 찾기")
        self.route_find.setToolTip("못 찾은 구간(또는 고른 줄)을 네이버 지도에서 다시 찾습니다 — 앱 브라우저의 네이버 지도 탭에서")
        self.route_find.clicked.connect(lambda: self._find_routes(force=True))
        manual = QPushButton("브라우저에서 직접")
        manual.setToolTip("자동으로 못 찾으면 — 앱 브라우저에 네이버 지도 길찾기를 열어 거리우선 경로를 직접 띄운 뒤 [지금 화면 찍기]")
        manual.clicked.connect(lambda: self._worker().open_site("navermap"))
        shoot = QPushButton("지금 화면 찍기 → 고른 줄")
        shoot.setToolTip("앱 브라우저에 띄운 네이버 지도 길찾기 화면을 찍어 고른 구간의 그림으로 넣고 km 를 읽습니다")
        shoot.clicked.connect(self._capture_route)
        pick = QPushButton("지도 그림 고르기 → 고른 줄")
        pick.setObjectName("ghost")
        pick.clicked.connect(self._pick_map)
        for button in (self.route_find, manual, shoot, pick):
            buttons.addWidget(button)
        buttons.addStretch(1)
        rows.addLayout(buttons)
        self.total_label = QLabel("총 이동경로 —")
        self.total_label.setObjectName("body")
        rows.addWidget(self.total_label)
        self.route_box.hide()
        return self.route_box

    def _build_make(self) -> FlowStep:
        step = FlowStep("4", "출장자마다 출장증빙 만들기", "출장자마다 '<이름> 출장증빙_yy.mm.dd.pdf' 를 폴더에 만듭니다. 같은 이름이 있으면 덮어쓰지 않고 _2.")
        self.plan_label = WrapLabel("")
        self.plan_label.setObjectName("body")
        step.add(self.plan_label)
        self.problem_label = WrapLabel("")
        self.problem_label.setObjectName("muted")
        step.add(self.problem_label)
        row = QHBoxLayout()
        self.make_button = QPushButton("출장증빙 PDF 만들기")
        self.make_button.setObjectName("primary")
        self.make_button.clicked.connect(lambda: self._make())
        self.open_button = QPushButton("파일 열기")
        self.open_button.clicked.connect(lambda: self._made and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._made[0]))))
        self.folder_button = QPushButton("폴더 열기")
        self.folder_button.setObjectName("ghost")
        self.folder_button.clicked.connect(lambda: self._made and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._made[0].parent))))
        row.addWidget(self.make_button)
        row.addWidget(self.open_button)
        row.addWidget(self.folder_button)
        row.addStretch(1)
        # 여러 폴더를 넣었으면 — 이 폴더를 만든 뒤 다음 폴더로(담당자 2026-11-10 "여러 폴더를 선택할 수 있도록")
        self.next_button = QPushButton("")
        self.next_button.clicked.connect(lambda: self._next_folder() and self.load_folder(self._next_folder()))
        row.addWidget(self.next_button)
        step.add_layout(row)
        self.result_label = WrapLabel("")
        self.result_label.setObjectName("body")
        step.add(self.result_label)
        return step

    def _build_preview(self) -> FlowStep:
        """⑤ 미리 보기 — 만들 PDF 와 같은 쪽을 앱 안에서(담당자 2026-11-10 "5단계로 미리보기를 넣어주세요"). 확인할 곳을 칠하고 눌러 고친다(ui/travel_preview.py)."""
        step = FlowStep("5", "미리 보기 · 고치기", "만들 출장증빙(PDF 와 같은 쪽)입니다. 확인이 필요한 곳은 칠해져 있습니다 — 눌러서 오른쪽 칸에서 고치세요.")
        self.preview_panel = PreviewPanel(self)
        self.preview_panel.setMinimumHeight(780)
        self.preview_panel.edited.connect(self._on_preview_edit)
        step.add(self.preview_panel)
        self.preview_note = WrapLabel("")
        self.preview_note.setObjectName("muted")
        self.preview_note.hide()
        step.add(self.preview_note)
        # 표를 고칠 때마다 다시 그리면 느리다 — 잠깐 모아서 한 번
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(350)
        self._preview_timer.timeout.connect(self._refresh_preview)
        return step

    def _refresh_preview(self) -> None:
        if self._stage == "files" and not self.step_preview.isHidden():
            self.preview_panel.refresh(keep=True)

    def _on_preview_edit(self) -> None:
        if self._made:
            self.preview_note.setText("고친 내용은 ④ [출장증빙 PDF 만들기] 를 다시 눌러야 PDF 에 들어갑니다.")
            self.preview_note.show()

    # ── ① 폴더 → ② 출장신청서 검토 ─────────────────────────────────────────
    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "출장증빙을 만들 폴더(출장비 지급 폴더)", self.folder_edit.text() or "")
        if path:
            self._add_folders([path], start=True)

    def load_folder(self, folder: str) -> None:
        """폴더를 고르면 — 출장신청서를 먼저 검토하고(출장자 · 기간 · 출장지) 증빙 파일을 출장자 · 항목별로 나눈다(담당자 2026-11-10)."""
        path = Path(folder) if folder else None
        if path is None or not path.is_dir():
            QMessageBox.warning(self, "출장증빙", f"폴더가 없습니다:\n{folder}")
            return
        self.folder_edit.setText(str(path))
        self._add_folders([path])
        self._mark_folders()
        self._apps = application.find(path)
        apps = [application.read(p) for p in self._apps]
        # 신청서에 출장이 여럿이면 저장 폴더 이름의 날짜로 고른다(담당자 2026-11-10)
        merged = application.select(application.merge(apps), path)
        self._review = merged
        scan = model.scan_folder(path, merged.travelers if merged else None)
        self._scan = scan
        self._made = []
        self.result_label.setText("")
        self.origin_edit.setText(settings.load().travel_origin)
        self.trip_box.blockSignals(True)
        self.trip_box.clear()
        for trip in (merged.trips if merged else []):
            self.trip_box.addItem(trip.label())
        self.trip_box.setCurrentIndex(merged.chosen if merged else 0)
        self.trip_box.blockSignals(False)
        self.trip_row.setVisible(bool(merged and len(merged.trips) > 1))
        names = self._fill_info(merged, scan)
        self._fill_from_scan(scan)
        self.review_label.setText(self._review_text(merged, names, scan))
        if merged:
            self.log(application.log_line(merged, self._apps))
            for app in apps:
                if app.shape and (merged.start is None or not merged.places):
                    # 못 읽은 칸이 있으면 그 신청서의 글 모양(이름 · 곳은 □) — 기록을 받아 읽는 꼴을 넓힌다
                    self.log(f"출장신청서 글 모양 — {app.path.name} (칸 이름 · 숫자만, 다른 글자는 □):")
                    for line in app.shape:
                        self.log("  | " + line)
        else:
            self.log(f"출장신청서 없음: {path.name} — 증빙 파일 이름으로 출장자 {len(names)}명")
        self._go("review")

    def _fill_info(self, app: application.Application | None, scan: model.Scan) -> list[str]:
        """신청서(고른 출장)의 출장자 · 기간 · 출발지 · 출장지를 칸에 — 신청서에 출장자가 없으면 증빙 파일 이름으로."""
        scanned = [p for files in scan.files.values() for p in files]
        names = list(app.travelers) if app and app.travelers else model.names_in_files(scanned)
        self._goal_of.clear()
        self._ask_reason.clear()
        self._routes.clear()
        self.name_edit.setText(", ".join(names))
        if app and app.start:
            self.start_edit.setDate(QDate(app.start.year, app.start.month, app.start.day))
            end = app.end or app.start
            self.end_edit.setDate(QDate(end.year, end.month, end.day))
        if app and app.origin:
            self.origin_edit.setText(app.origin)
        self.dest_edit.setText(app.destination if app else "")
        return names

    def _on_trip_choice(self, index: int) -> None:
        """'신청서의 출장' 을 바꾸면 그 출장의 기간 · 출장지 · 출장자로 다시 채운다(증빙 파일은 그대로 — 출장자 칸만 다시 짐작)."""
        app = self._review
        if app is None or not app.trips or index < 0:
            return
        application.apply_trip(app, index)
        self.origin_edit.setText(settings.load().travel_origin)
        names = self._fill_info(app, self._scan)
        for table in self.tables.values():
            table.show_people(self._names())
        self.review_label.setText(self._review_text(app, names, self._scan))
        self.log(application.log_line(app, self._apps))
        self._sync()

    def _fill_from_scan(self, scan: model.Scan) -> None:
        for table in self.tables.values():
            table.clear_all()
        for kind, paths in scan.files.items():
            self.tables[kind].add_files(paths, self._year())
        for kind, table in self.tables.items():
            table.show_people(self._names())
        # 폴더에 이미 둔 지도 그림('… 지도 가는 길' · '… 오는 길') — 자차 출장자가 한 명이면 그 사람 구간으로
        self._scan_maps = [p for p in scan.route_maps if p] or ([scan.route_map] if scan.route_map else [])
        added = sum(len(p) for p in scan.files.values())
        lines = [f"{model.KIND_NAMES[k]} {len(p)}개" for k, p in scan.files.items() if p]
        note = f"폴더에서 증빙 {added}개를 넣었습니다" + (f" — {' · '.join(lines)}" if lines else "")
        if scan.unsorted:
            names = ", ".join(p.name for p in scan.unsorted[:6]) + (" …" if len(scan.unsorted) > 6 else "")
            note += f". 이름으로 항목을 못 정해 넣지 않은 파일 {len(scan.unsorted)}개: {names} — 필요하면 그 항목의 [파일 넣기]"
        self.scan_note.setText(note)

    def _review_text(self, app: application.Application | None, names: list[str], scan: model.Scan) -> str:
        if app is None:
            from_files = f" 증빙 파일 이름에서 출장자 {len(names)}명({', '.join(names)})을 읽었습니다." if names else ""
            return ("출장신청서를 찾지 못했습니다 — 파일 이름에 '출장신청' 이 든 PDF(또는 .hwpx)를 이 폴더에 두면 읽습니다." + from_files
                    + " 출장 정보를 직접 적어 주세요.")
        lines = [f"출장신청서 {', '.join(p.name for p in self._apps)} 를 읽었습니다 — 찾은 칸: {', '.join(app.found) or '없음'}."]
        if app.travelers:
            lines.append(f"출장자 {len(app.travelers)}명: {', '.join(app.travelers)}")
        if app.purpose:
            lines.append(f"출장목적: {app.purpose}")
        in_files = [n for n in model.names_in_files(p for files in scan.files.values() for p in files) if n not in names]
        if in_files:
            lines.append(f"증빙 파일에는 신청서에 없는 이름이 있습니다: {', '.join(in_files)} — 출장자를 확인하세요")
        lines += [f"확인: {n}" for n in app.notes]
        return "\n".join(lines)

    # ── 출장자 · 목적지 ──────────────────────────────────────────────────
    def _names(self) -> list[str]:
        return model.split_names(self.name_edit.text())

    def _places(self) -> list[str]:
        return model.split_places(self.dest_edit.text())

    def _on_people(self) -> None:
        for table in self.tables.values():
            table.show_people(self._names())
        self._on_route_inputs()

    def _on_places(self) -> None:
        places = self._places()
        for table in self.tables.values():
            table.show_places(places)
        self._on_region()
        self._on_route_inputs()

    def _on_dates(self) -> None:
        if self.end_edit.date() < self.start_edit.date():
            self.end_edit.setDate(self.start_edit.date())
        self._sync()

    def _drivers(self) -> list[str]:
        """하이패스가 있는 출장자 — 자차(담당자 2026-11-10 "하이패스가 있으면 자차를 이용한건데"). '공통' 하이패스면 모두."""
        tolls = self.tables[model.TOLL].evidence(self._year()) if model.TOLL in self.tables else []
        if not tolls:
            return []
        names = self._names()
        if len(names) <= 1:
            return names[:1] or ["출장자"]
        whose = {e.person.strip() for e in tolls}
        return [n for n in names if n in whose or model.SHARED in whose]

    def _goal(self, name: str) -> str:
        """그 출장자의 출장목적지 — 사람이 적은 것, 없으면 출장지 칸(하나일 때)."""
        own = self._goal_of.get(name, "").strip()
        if own:
            return own
        places = self._places()
        return places[0] if len(places) == 1 else ""

    def _stops(self, name: str) -> list[str]:
        """자차의 들른 곳 차례 — 경유지([경유지 추가]) 다음 목적지(그 출장자의 목적지, 없으면 출장지 칸의 곳들)."""
        places = self._places()
        goals = [self._goal_of[name]] if self._goal_of.get(name, "").strip() else (places if len(places) > 1 else [self._goal(name)])
        return self._vias() + goals

    def _legs_for(self, name: str) -> list[tuple[str, str, str]]:
        """찾을 구간 — 목적지가 하나면 가는 길 하나(오는 길은 같은 거리로 본다 — 담당자 2026-11-10 "출발지와 목적지가 동일한 경우는 1개만"),
        경유지가 있으면 출발지 → 경유지 → 목적지 → 출발지 구간마다 지도 · 거리("경유지가 있는 경우에만 이동별 지도사진 및 이동거리 입력")."""
        origin = self.origin_edit.text().strip()
        stops = self._stops(name)
        if len(stops) > 1:
            path = [origin, *stops, origin]
            return [(a, b, f"구간 {i + 1}") for i, (a, b) in enumerate(zip(path, path[1:]))]
        return [(origin, stops[0] if stops else "", "가는 길(오는 길도 같은 거리)")]

    def _needs_goal(self) -> dict[str, str]:
        """목적지를 물어야 할 출장자 → 까닭. 자차 출장자만(길찾기에 목적지가 있어야 한다)."""
        out = {}
        places = self._places()
        for name in self._drivers():
            if self._goal_of.get(name, "").strip():
                if name in self._ask_reason:
                    out[name] = self._ask_reason[name]
                continue
            if name in self._ask_reason:
                out[name] = self._ask_reason[name]
            elif len(places) > 1:
                vague = [p for p in places if application.vague_place(p)]
                if vague:
                    out[name] = application.vague_place(vague[0])
            else:
                why = application.vague_place(places[0] if places else "")
                if why:
                    out[name] = why
        return out

    def _sync_goal_box(self) -> None:
        need = self._needs_goal()
        for name in list(self.goal_edits):
            if name not in need:
                edit = self.goal_edits.pop(name)
                label = self.goal_rows.itemAtPosition(self._goal_row(edit), 0)
                if label is not None and label.widget() is not None:
                    label.widget().deleteLater()
                edit.deleteLater()
        for name in need:
            if name in self.goal_edits:
                continue
            row = self.goal_rows.rowCount()
            label = QLabel(f"{name} 출장목적지")
            edit = QLineEdit(self._goal_of.get(name, ""))
            edit.setPlaceholderText("네이버 지도에서 찾을 곳 — 예: 연세대학교 원주캠퍼스")
            edit.editingFinished.connect(lambda n=name, e=edit: self._set_goal(n, e.text()))
            self.goal_rows.addWidget(label, row, 0)
            self.goal_rows.addWidget(edit, row, 1)
            self.goal_edits[name] = edit
        if need:
            reasons = "\n".join(f"· {name}: {why}" for name, why in need.items())
            self.goal_note.setText("출장목적지를 입력해 주세요 — 하이패스가 있어 자차라 네이버 지도에서 최단거리를 찾아야 합니다.\n" + reasons)
        self.goal_box.setVisible(bool(need))

    def _goal_row(self, edit: QLineEdit) -> int:
        for row in range(self.goal_rows.rowCount()):
            item = self.goal_rows.itemAtPosition(row, 1)
            if item is not None and item.widget() is edit:
                return row
        return -1

    def _set_goal(self, name: str, text: str) -> None:
        text = text.strip()
        if text == self._goal_of.get(name, ""):
            return
        self._goal_of[name] = text
        if text:
            self._ask_reason.pop(name, None)
        # 목적지가 바뀌면 그 출장자의 구간은 다시 찾는다
        for key in [k for k in self._routes if k[0] == name]:
            self._routes.pop(key)
        self._on_route_inputs()
        if self._stage == "files" and text:
            self._find_routes()

    # ── ③ 증빙 · 자차 ──────────────────────────────────────────────────
    def _year(self) -> int:
        return self.start_edit.date().year()

    def _add_files(self, kind: str) -> None:
        start = self.folder_edit.text() or ""
        files, _ = QFileDialog.getOpenFileNames(self, f"{model.KIND_NAMES[kind]} 증빙 파일", start, FILE_FILTER)
        if files:
            self.tables[kind].add_files([Path(f) for f in files], self._year())

    def _rescan(self) -> None:
        folder = self.folder_edit.text().strip()
        if folder and Path(folder).is_dir():
            self._fill_from_scan(model.scan_folder(Path(folder), self._names()))
            self._on_route_inputs()

    def _on_evidence(self) -> None:
        self._on_route_inputs()

    def _on_route_inputs(self) -> None:
        """출장자 · 출발지 · 목적지 · 하이패스가 바뀌면 자차 구간 표를 다시 짠다 — 찾아 둔 구간은(출발 · 목적지가 같으면) 남긴다."""
        if not hasattr(self, "route_table"):
            return
        keep = {}
        for name in self._drivers():
            for i, (origin, goal, label) in enumerate(self._legs_for(name)):
                old = self._routes.get((name, i))
                if old and old["origin"] == origin and old["goal"] == goal:
                    keep[(name, i)] = old
                else:
                    keep[(name, i)] = {"origin": origin, "goal": goal, "label": label, "km": None, "image": "", "status": ""}
        # 폴더에 둔 지도 그림 — 자차 출장자가 한 명이면 그 사람의 구간 차례로
        maps = getattr(self, "_scan_maps", [])
        drivers = self._drivers()
        if maps and len(drivers) == 1:
            for i, path in enumerate(maps):
                route = keep.get((drivers[0], i))
                if route is not None and not route["image"] and path:
                    route["image"], route["status"] = str(path), "폴더의 지도 그림"
        changed = {k: (v["origin"], v["goal"]) for k, v in keep.items()} != {k: (v["origin"], v["goal"]) for k, v in self._routes.items()}
        self._routes = keep
        if changed:
            self._uncheck_route()
        self._fill_route_table()
        self._sync_goal_box()
        self._sync_car_box()
        self._sync()

    def _fill_route_table(self) -> None:
        table = self.route_table
        table.blockSignals(True)
        table.setRowCount(0)
        self._route_keys = sorted(self._routes)
        for key in self._route_keys:
            route = self._routes[key]
            row = table.rowCount()
            table.insertRow(row)
            cells = [key[0], route["label"], f"{route['origin'] or '?'} → {route['goal'] or '?'}",
                     f"{route['km']:g}" if route["km"] is not None else "", Path(route["image"]).name if route["image"] else "",
                     "찾는 중…" if key in self._searching else route["status"]]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col != 3:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 4 and route["image"]:
                    item.setToolTip(route["image"])
                table.setItem(row, col, item)
        table.blockSignals(False)
        self.route_box.setVisible(bool(self._routes) or bool(self.tables[model.TOLL].paths))
        totals = []
        for name in sorted({k[0] for k in self._routes}):
            kms = [self._routes[k]["km"] for k in self._route_keys if k[0] == name]
            if kms and all(v is not None for v in kms):
                # 목적지가 하나면 가는 길 하나만 찾는다 — 오는 길은 같은 거리(Trip.route_legs)
                legs = kms if len(kms) > 1 else kms * 2
                parts = f"가는 길 {model.km(kms[0])} · 오는 길 {model.km(kms[0])} · " if len(kms) == 1 else ""
                totals.append(f"{name}: {parts}총 이동경로 {model.km(sum(legs))}")
        self.total_label.setText(" · ".join(totals) or "총 이동경로 — (구간 km 를 찾으면 채워집니다)")

    def _on_route_edited(self, item: QTableWidgetItem) -> None:
        if item.column() != 3 or item.row() >= len(self._route_keys):
            return
        route = self._routes[self._route_keys[item.row()]]
        route["km"] = _parse_km(item.text())
        route["status"] = "직접 적음" if route["km"] is not None else route["status"]
        self._fill_route_table()
        self._sync()

    def _selected_route(self):
        rows = sorted({i.row() for i in self.route_table.selectedIndexes()})
        if rows and rows[0] < len(self._route_keys):
            return self._route_keys[rows[0]]
        return None

    def _find_routes(self, force: bool = False) -> None:
        """찾지 못한 구간(force 면 고른 줄 또는 그림 · km 가 빈 구간 모두)을 앱 브라우저의 네이버 지도 탭에서 찾는다(담당자 2026-11-10 "백그라운드에서 자동으로" — 보이지 않는 브라우저는 네이버가 보안문자로 막았다)."""
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir() or not self._routes:
            return
        chosen = self._selected_route() if force else None
        keys = []
        for key, route in sorted(self._routes.items()):
            if key in self._searching or not route["origin"] or not route["goal"]:
                continue
            if chosen is not None and key != chosen:
                continue
            target = route["goal"] if route["goal"] != self.origin_edit.text().strip() else route["origin"]
            if application.vague_place(target) and not self._goal_of.get(key[0]):
                continue            # 목적지가 분명하지 않으면 먼저 묻는다(_sync_goal_box)
            if chosen is None and route["image"] and route["km"] is not None:
                continue
            if not force and route["status"].startswith("못 찾음"):
                continue
            keys.append(key)
        if not keys:
            return
        legs = [(self._routes[k]["origin"], self._routes[k]["goal"], f"{k[0]} {self._routes[k]['label']}") for k in keys]
        self._searching.update(keys)
        self._fill_route_table()
        self.log(f"네이버 지도 최단거리 찾기 {len(keys)}구간 (앱 브라우저의 네이버 지도 탭 — 보안문자가 뜨면 그 창에서 입력해 주세요)")
        self._worker().find_routes(legs, folder, keys)

    def _on_routes(self, found) -> None:
        failed = []
        for key, result in found:
            self._searching.discard(key)
            route = self._routes.get(key)
            if route is None:
                continue
            if result.ok:
                route["image"] = result.image
                if result.km is not None:
                    route["km"] = result.km
                route["status"] = "찾음(거리우선)" if result.km is not None else (result.note or "그림만 찍음")
            else:
                route["status"] = "못 찾음 — " + (result.note or "까닭 모름")
                if result.need_place:
                    # 목적지가 검색되지 않으면 그 출장자의 출장목적지를 묻는다(담당자 2026-11-10)
                    self._ask_reason[key[0]] = f"네이버 지도에서 '{result.need_place}' 를 찾지 못했습니다"
                    self._goal_of.pop(key[0], None)
                else:
                    failed.append(result.note or "까닭 모름")
        self._fill_route_table()
        self._sync_goal_box()
        if self._needs_goal() and self._stage == "files":
            self.goal_box.show()
            self._go("review")
            QMessageBox.information(self, "출장목적지", "네이버 지도에서 목적지를 찾지 못한 출장자가 있습니다.\n\n"
                                    "② 의 칸에 그 출장자의 출장목적지(기관 · 건물 이름)를 입력해 주세요 — 입력하면 다시 찾습니다.")
        elif failed and self._stage == "files":
            # 목적지 이름 탓이 아닌 실패(출발지부터 못 찾음 · 길찾기 화면이 안 뜸)는 목적지를 묻지 않고 사람이 할 길을 알린다(담당자 2026-11-10
            # "목적지가 검색이 안된다고 하는데 둘다 검색이 됩니다" — 그때는 출발지부터 앱의 검색이 비어 왔는데 목적지를 물었다)
            QMessageBox.information(self, "네이버 지도 최단거리", "앱이 네이버 지도 최단거리를 찾지 못했습니다.\n\n" + "\n".join(dict.fromkeys(failed))[:600] +
                                    "\n\n[브라우저에서 직접] 으로 네이버 지도 길찾기에서 출발지 · 목적지를 넣고 '거리우선' 경로를 띄운 뒤, "
                                    "자차 이동경로 표에서 그 줄을 고르고 [지금 화면 찍기 → 고른 줄] 을 누르세요.\n"
                                    "그 길찾기의 출발지 · 목적지는 앱이 기억해 다음부터는 저절로 찾습니다.")
        self._sync()

    def _capture_route(self) -> None:
        key = self._selected_route()
        folder = self.folder_edit.text().strip()
        if key is None or not folder:
            QMessageBox.information(self, "지금 화면 찍기", "자차 이동경로 표에서 넣을 줄(구간)을 먼저 고르세요.")
            return
        self._searching.add(key)
        self._fill_route_table()
        self._worker().capture_route(folder, f"{key[0]} {self._routes[key]['label']}", key)

    def _pick_map(self) -> None:
        key = self._selected_route()
        if key is None:
            QMessageBox.information(self, "지도 그림 고르기", "자차 이동경로 표에서 넣을 줄(구간)을 먼저 고르세요.")
            return
        path, _ = QFileDialog.getOpenFileName(self, "네이버 지도 최단거리 그림", self.folder_edit.text() or "", "그림 (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self._routes[key]["image"], self._routes[key]["status"] = path, "그림 고름"
            self._fill_route_table()
            self._sync()

    def _on_region(self) -> None:
        places = self._places()
        auto = self.region_box.currentIndex() == 0
        # 출장지가 여러 곳이고 지역을 고르지 않았으면 숙박 영수증마다 그 출장지로 상한을 정한다 — 1박 상한 칸 하나로는 못 적는다
        per_place = auto and len(places) > 1
        self.cap_spin.setEnabled(not per_place)
        if per_place:
            caps = " · ".join(f"{p} {model.won(model.LODGING_CAPS[model.lodging_region(p)])}" for p in places)
            self.cap_note.setText(f"숙박 상한(1박, 공무원 여비 규정 별표 2)은 영수증마다 그 출장지로 정합니다: {caps}. "
                                  "결제액이 넘으면 지원금액은 상한금액입니다. 한 기준으로 하려면 지역을 고르세요.")
            self._sync()
            return
        region = model.lodging_region(places[0] if places else "") if auto else self.region_box.currentText()
        cap = model.LODGING_CAPS[region]
        self.cap_spin.setValue(cap)
        self.cap_note.setText(f"숙박 상한: {region} 1박 {model.won(cap)}(공무원 여비 규정 별표 2) — 결제액이 넘으면 지원금액은 상한금액입니다. "
                              "기준이 다르면 1박 상한 칸을 고치세요.")
        self._sync()

    # ── 단계 ────────────────────────────────────────────────────────────
    def _go(self, stage: str) -> None:
        self._stage = stage
        self._sync()
        if stage == "files" and self._auto_routes:
            QTimer.singleShot(0, self._find_routes)

    def base_trip(self) -> model.Trip:
        """출장자 모두의 증빙이 든 출장 하나 — 출장자마다 나누는 것은 trips()."""
        year = self._year()
        region = "" if self.region_box.currentIndex() == 0 else self.region_box.currentText()
        return model.Trip(
            name=", ".join(self._names()),
            start=self.start_edit.date().toPython(), end=self.end_edit.date().toPython(),
            origin=self.origin_edit.text().strip(), destination=self.dest_edit.text().strip(),
            region=region, lodging_cap=(self.cap_spin.value() or None) if self.cap_spin.isEnabled() else None,
            people=self.people_spin.value(),
            stay=self.tables[model.STAY].evidence(year), public=self.tables[model.PUBLIC].evidence(year),
            tolls=self.tables[model.TOLL].evidence(year), lodging=self.tables[model.LODGING].evidence(year),
            other=self.tables[model.OTHER].evidence(year),
            place_regions=self._place_regions(model.split_places(self.dest_edit.text())),
        )

    @staticmethod
    def _place_regions(places: list[str]) -> dict:
        """출장지 글에 시 · 군이 없으면 네이버 지도에서 찾아 기억해 둔 그곳 주소의 시 · 군(settings.travel_places) — 체류 가맹점 지역을 견주려고."""
        missing = [p for p in places if not model.region_of(p)]
        if not missing:
            return {}
        import json
        import re
        try:
            known = json.loads(settings.load().travel_places or "{}")
        except ValueError:
            return {}
        out = {}
        for place in missing:
            for key in (navermap.norm(place), navermap.norm(re.sub(r"\([^)]*\)", " ", place))):
                hit = known.get(key) if isinstance(known, dict) else None
                region = model.region_of(hit.get("address", "")) if isinstance(hit, dict) else ""
                if region:
                    out[place] = region
                    break
        return out

    def trips(self) -> list[model.Trip]:
        """출장자마다 출장 — 그 사람 증빙 · '공통' 증빙과, 자차면 그 사람 구간의 지도 · km."""
        names = self._names()
        base = self.base_trip()
        out = []
        for name in names or [""]:
            trip = model.for_traveler(base, name, names)
            driver = name or "출장자"
            keys = sorted(k for k in self._routes if k[0] == driver)
            if keys and trip.tolls:
                trip.legs = [self._routes[k]["km"] for k in keys]
                trip.route_maps = [Path(self._routes[k]["image"]) if self._routes[k]["image"] else None for k in keys]
                stops = self._stops(driver)
                trip.route_stops = stops if len(stops) > 1 else []
                trip.fuel = self._fuel_of.get(driver, "")
            out.append(trip)
        return out

    def trip(self) -> model.Trip:
        """출장자가 한 명일 때의 출장(전 판과 같은 이름) — 여럿이면 첫 사람."""
        return self.trips()[0]

    def _sync(self) -> None:
        if not hasattr(self, "make_button"):
            return
        folder = self.folder_edit.text().strip()
        has_folder = bool(folder) and Path(folder).is_dir()
        if not has_folder and self._stage != "folder":
            self._stage = "folder"
        names = self._names()
        stage = self._stage
        folders = self._folders()
        many = len(folders) > 1
        where = f" ({folders.index(folder) + 1}/{len(folders)})" if many and folder in folders else ""
        self.step_folder.set_state(DONE if stage != "folder" else CURRENT,
                                   (f"폴더 {len(folders)}개 · 지금 " if many else "") + (Path(folder).name if folder else "") + where)
        nxt = self._next_folder(from_start=not folder)
        if not folder:
            label = f"{len(folders)}개 폴더 차례로 시작" if many else "이 폴더로 시작"
        elif folder not in self._done_folders:
            label = f"계속 — {Path(folder).name}"           # ① 로 돌아와 폴더를 더 넣었으면 하던 폴더부터 마친다
        else:
            label = f"다음 폴더로 — {Path(nxt).name}" if nxt else "모두 만들었습니다"
        self.start_button.setVisible(bool(folders))
        self.start_button.setEnabled(bool(folders) and label != "모두 만들었습니다")
        self.start_button.setText(label)
        self.folder_list.setToolTip("체크한 폴더를 차례로 합니다 — 두 번 누르면 그 폴더로 바로 갑니다" if many else "")
        start, end = self.start_edit.date().toPython(), self.end_edit.date().toPython()
        who = names[0] + (f" 외 {len(names) - 1}명" if len(names) > 1 else "") if names else "출장자 없음"
        self.step_info.set_state(HIDDEN if stage == "folder" else CURRENT if stage == "review" else DONE,
                                 f"{who} · {start:%m-%d}~{end:%m-%d} · {self.dest_edit.text().strip() or '출장지 없음'}")
        car_ready = not self._drivers() or (self._route_checked and not self._car_missing())
        self.info_next.setEnabled(bool(names) and car_ready)
        self.info_next.setToolTip("" if car_ready else "자차 경로 확인 — 출발지 · 경유지 · 목적지와 연료를 확인하고 확인 칸을 켜세요")
        self.app_button.setVisible(bool(self._apps))
        files = stage == "files"
        self.step_files.set_state(OPEN if files else HIDDEN)
        self.step_make.set_state(OPEN if files else HIDDEN)
        self.step_preview.set_state(OPEN if files else HIDDEN)
        if files and hasattr(self, "_preview_timer"):
            self._preview_timer.start()
        self.lodging_box.setVisible(bool(self.tables[model.LODGING].paths))
        self.route_find.setEnabled(bool(self._routes))
        trips = self.trips()
        base = self.base_trip()
        self._fill_people(trips)
        problems = model.traveler_problems(base, names)
        for trip in trips:
            problems += [(f"{trip.name}: " if len(trips) > 1 else "") + p for p in model.problems(trip)
                         if not (len(trips) > 1 and p.startswith("증빙 파일이 하나도"))]
        problems = list(dict.fromkeys(problems))
        ready = [t for t in trips if not model.blocking(t)]
        pages = sum(len(model.pages(t)) for t in ready)
        self.plan_label.setText(f"만들 출장증빙 {len(ready)}개({', '.join(t.name for t in ready) or '없음'}) · 쪽 {pages}개"
                                "(증빙 PDF 가 여러 쪽이면 더 늘 수 있음)")
        self.problem_label.setText("\n".join(f"· {p}" for p in problems[:14]) + (f"\n· … 외 {len(problems) - 14}개" if len(problems) > 14 else ""))
        self.make_button.setText(f"출장증빙 PDF 만들기 ({len(ready)}명)" if len(ready) > 1 else "출장증빙 PDF 만들기")
        self.make_button.setEnabled(files and bool(ready))
        after = self._next_folder() if folder else ""
        self.next_button.setVisible(bool(after))
        self.next_button.setText(f"다음 폴더 — {Path(after).name}" if after else "")
        self.next_button.setObjectName("primary" if folder in self._done_folders else "")
        self.next_button.style().unpolish(self.next_button)
        self.next_button.style().polish(self.next_button)
        self.open_button.setVisible(bool(self._made))
        self.folder_button.setVisible(bool(self._made))
        if not self._made:
            self.state_pill.set_status({"folder": "준비", "review": "신청서 검토"}.get(stage, "증빙 확인"), "neutral")

    def _fill_people(self, trips: list[model.Trip]) -> None:
        """출장자별 증빙 확인 표 — 항목별 개수와 확인할 것(model.review)."""
        table = self.people_table
        table.setRowCount(0)
        drivers = set(self._drivers())
        for trip in trips:
            row = table.rowCount()
            table.insertRow(row)
            nights = sum(e.nights for e in trip.lodging)
            route = "—"
            if trip.name in drivers or (len(trips) == 1 and drivers):
                kms = [v for v in trip.legs if v]
                route = (f"{len([m for m in trip.route_maps if m])}장 · {model.km(sum(kms))}" if kms else "아직") if trip.tolls else "—"
            review = model.review(trip)
            cells = [trip.name or "(이름 없음)", f"{len(trip.stay)}개", f"{len(trip.public)}개", f"{len(trip.tolls)}개",
                     f"{nights}박" if trip.lodging else "—", f"{len(trip.other)}개" if trip.other else "—", route,
                     " / ".join(review) or "확인할 것 없음"]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(row, col, item)

    # ── 미리 보기에서 고치기(ui/travel_preview.py 가 부른다) ────────────────
    def open_preview(self, make: bool = False, name: str = "") -> int:
        dialog = TravelPreview(self, self, name=name, make_text="이대로 만들기" if make else "")
        result = dialog.exec()
        self._sync()
        return result

    def apply_edit(self, ref: tuple, values: dict) -> None:
        """미리 보기에서 고친 값을 그 증빙의 표 줄에 적는다 — 표가 원본이다."""
        kind, row = ref
        table = self.tables.get(kind)
        if table is None or row >= table.rowCount():
            return
        cols = {"day": 1}
        if kind == model.OTHER:
            cols["label"] = 2
        elif kind != model.STAY:
            cols["amount"] = 2
        if kind == model.PUBLIC:
            cols.update(mode=3, origin=4, goal=5)
        if kind == model.LODGING:
            cols["nights"] = 3
        if kind == model.STAY:
            cols["shop_region"] = SHOP_COL
        if kind in PLACE_COL:
            cols["place"] = PLACE_COL[kind]
        changed = []
        table.blockSignals(True)
        for key, value in values.items():
            col = cols.get(key)
            if col is None:
                continue
            text = str(value).strip()
            if key == "day" and text:
                day = _parse_day(text, self._year())
                text = day.isoformat() if day else text
            elif key == "amount":
                number = _parse_int(text)
                text = f"{number:,}" if number is not None else ""
            item = table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                table.setItem(row, col, item)
            if item.text() != text:
                item.setText(text)
                changed.append(key)
        table.blockSignals(False)
        table.mark_unclear()
        if changed:
            self.log(f"미리 보기에서 고침: {model.KIND_NAMES.get(kind, kind)} {row + 1}번째 줄 — {', '.join(changed)}")
        self._sync()

    def route_rows(self, driver: str) -> list[tuple]:
        """자차 출장자의 구간들 — (열쇠, 구간 이름, '출발 → 목적지', km)."""
        return [(key, route["label"], f"{route['origin'] or '?'} → {route['goal'] or '?'}", route["km"])
                for key, route in sorted(self._routes.items()) if key[0] == driver]

    def fuel_of(self, driver: str) -> str:
        return self._fuel_of.get(driver, "")

    def apply_route(self, driver: str, kms: dict, fuel: str) -> None:
        """미리 보기에서 고친 구간 km · 연료 — 사람이 미리 보기를 보고 고친 것이라 자차 경로 확인은 풀지 않는다."""
        for key, value in kms.items():
            route = self._routes.get(key)
            if route is not None and route["km"] != value:
                route["km"] = value
                route["status"] = "직접 적음" if value is not None else route["status"]
        if fuel and fuel != self._fuel_of.get(driver, ""):
            box = self.fuel_boxes.get(driver)
            if box is not None:
                box.blockSignals(True)
                if box.findData(fuel) < 0:
                    box.addItem(fuel, fuel)
                box.setCurrentIndex(box.findData(fuel))
                box.blockSignals(False)
            self._set_fuel(driver, fuel, recheck=False)
        self._fill_route_table()
        self._sync()

    # ── ④ 만들기 ────────────────────────────────────────────────────────
    def _make(self, confirmed: bool = False) -> None:
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self, "출장증빙 만들기", f"저장할 폴더가 없습니다:\n{folder}")
            return
        names = self._names()
        trips = [t for t in self.trips() if not model.blocking(t)]
        problems = model.traveler_problems(self.base_trip(), names)
        for trip in trips:
            problems += [(f"{trip.name}: " if len(trips) > 1 else "") + p for p in model.problems(trip) + model.review(trip)]
        if problems and not confirmed:
            # 확인할 것이 있으면 묻는 글 대신 미리 보기 — 칠한 곳을 눌러 고친 뒤 [이대로 만들기](담당자 2026-11-10)
            first = next((t.name for t in trips if model.problems(t) or model.review(t)), "")
            if self.open_preview(make=True, name=first) != PREVIEW_MAKE:
                return
            trips = [t for t in self.trips() if not model.blocking(t)]
        from ...travel import render
        made, lines = [], []
        for trip in trips:
            out = model.output_path(folder, trip.name, trip.start)
            try:
                count = render.render(model.pages(trip), out)
            except Exception as exc:  # 그림 파일 · 폴더 권한 등
                lines.append(f"✗ {trip.name}: 만들지 못했습니다 — {exc}")
                continue
            made.append(out)
            support = sum(model.lodging_support(e, trip.cap(e), trip.people)[0] for e in trip.lodging)
            lines.append(f"✓ {out.name} — {count}쪽" + (f" · 숙박 지원금액 {model.won(support)}" if trip.lodging else ""))
            self.log(f"출장증빙 만듦: {out.name} — {count}쪽")
        self._made = made
        if made:
            self.preview_note.hide()
            lines.append(f"저장한 곳: {folder}")
            self.state_pill.set_status("만듦", "success")
            self._done_folders.add(str(folder))
            self._mark_folders()
            after = self._next_folder()
            if after:
                lines.append(f"다음 폴더: {Path(after).name} — 아래 [다음 폴더] 를 누르세요")
        self.result_label.setText("\n".join(lines))
        self._sync()

    def shutdown(self) -> None:
        if self._owns_browser and self.browser is not None:
            self.browser.shutdown()
