"""출장증빙자료 만들기 — 지원 항목별 증빙을 넣고 출장 정보 · 경로를 적으면 '<이름> 출장증빙_yy.mm.dd.pdf' 를 만든다. 담당자 2026-10-27, CLAUDE.md 28절.

담당자: "지원항목별로 증빙 자료를 넣고 출장지 등 경로를 입력했을 때 출장증빙 파일이 나왔으면 좋겠습니다".
    ① 출장 정보(출장자 · 기간 · 출발지 · 출장지(여러 곳이면 쉼표로) · 저장할 폴더) → ② 항목별 증빙(체류 · 대중교통 · 자차 하이패스 · 숙박 — 파일마다 일자 · 금액,
    교통비 · 숙박은 있을 때만 — 숙박 상한 칸은 숙박 영수증을 넣었을 때만 보인다) ·
    이동경로(자차) → ③ 만들기.
쪽 짜임 · 숙박 지원금액은 travel/model.py(Qt 없음), 그리기는 travel/render.py. ERP · 브라우저는 쓰지 않는다 — 폴더의 파일만 읽고 새 PDF 하나를 쓴다(덮어쓰지 않음).
자차 이동경로의 거리 · 지도는 지금은 담당자가 넣는다(네이버 지도 캡처 · km). 앱이 찾아오는 것은 실측 뒤(28절).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import settings
from ...travel import model
from ..art import Art
from ..flow import CURRENT, DONE, HIDDEN, OPEN, FlowArea, FlowStep
from ..log_button import LogSendButton
from ..widgets import Pill, WrapLabel, muted_label

FILE_FILTER = "증빙 파일 (*.pdf *.jpg *.jpeg *.png *.bmp *.gif *.webp)"
REGIONS = ("자동(출장지로)",) + tuple(model.LODGING_CAPS)

# 항목마다 표의 칸 — 마지막 칸은 항목마다 뜻이 다르다(대중교통 이동편 · 숙박 박 수)
# 체류 · 숙박의 '출장지' 칸은 출장지가 여러 곳일 때만 보인다(담당자 2026-10-27 "출장지가 한군데가 아닌 경우도 있습니다")
COLUMNS = {
    model.STAY: ("파일", "일자", "출장지"),
    model.PUBLIC: ("파일", "일자", "금액(원)", "이동편"),
    model.TOLL: ("파일", "이용일자", "금액(원)"),
    model.LODGING: ("파일", "입실일", "결제금액(원)", "박 수", "출장지"),
}
PLACE_COL = {model.STAY: 2, model.LODGING: 4}
HINTS = {
    model.STAY: "일자별 체류 영수증 — 출장이 7일 이하면 한 쪽을 칸으로 나눠 담고, 8일 이상이면 일자마다 한 쪽입니다.",
    model.PUBLIC: "승차권 · 영수증 — 일자와 이동편(열차 · 고속버스 …)마다 한 쪽입니다. 같은 날이라도 이동편이 바뀌면 다른 쪽.",
    model.TOLL: "하이패스 이용내역 — 이용일자별로 묶어 그날 금액을 적고, 아래에 이동경로가 붙습니다.",
    model.LODGING: "숙박 영수증 — 숙박기간과 지원금액을 적습니다. 상한을 넘으면 지원금액은 상한금액입니다.",
}


def _parse_day(text: str, year: int) -> date | None:
    return model.guess_day(text.strip(), year) if text.strip() else None


def _parse_int(text: str) -> int | None:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None


class EvidenceTable(QTableWidget):
    """항목 하나의 증빙 표 — 파일을 끌어다 놓거나 [파일 넣기]. 일자 · 금액은 짐작해 채우고 사람이 고친다."""

    changed = Signal()

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(0, len(COLUMNS[kind]), parent)
        self.kind = kind
        self.paths: list[Path] = []
        self.year = lambda: date.today().year      # 화면이 출장 시작일의 해로 바꿔 끼운다 — '0528' 같은 이름의 해
        self.places = lambda: []                   # 화면이 출장지 목록으로 바꿔 끼운다 — 파일 경로로 출장지를 짐작
        self.setHorizontalHeaderLabels(COLUMNS[kind])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.columnCount()):
            self.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setAcceptDrops(True)
        self.setMinimumHeight(120)
        self.itemChanged.connect(lambda _item: self.changed.emit())

    def add_files(self, paths: list[Path], year: int) -> None:
        self.blockSignals(True)
        for path in paths:
            if path in self.paths or path.suffix.lower() not in model.FILE_SUFFIXES:
                continue
            ev = model.guess(path, year)
            self.paths.append(path)
            row = self.rowCount()
            self.insertRow(row)
            name = QTableWidgetItem(path.name)
            name.setFlags(name.flags() & ~Qt.ItemIsEditable)
            name.setToolTip(str(path))
            self.setItem(row, 0, name)
            self.setItem(row, 1, QTableWidgetItem(ev.day.isoformat() if ev.day else ""))
            if self.kind != model.STAY:
                self.setItem(row, 2, QTableWidgetItem(f"{ev.amount:,}" if ev.amount is not None else ""))
            if self.kind in PLACE_COL:
                self.setItem(row, PLACE_COL[self.kind], QTableWidgetItem(model.match_place(str(path), self.places())))
            if self.kind == model.PUBLIC:
                self.setItem(row, 3, QTableWidgetItem(model.mode_of(str(path))))
            elif self.kind == model.LODGING:
                self.setItem(row, 3, QTableWidgetItem("1"))
        self.blockSignals(False)
        self.changed.emit()

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

    def remove_selected(self) -> None:
        for row in sorted({i.row() for i in self.selectedIndexes()}, reverse=True):
            self.removeRow(row)
            del self.paths[row]
        self.changed.emit()

    def clear_all(self) -> None:
        self.setRowCount(0)
        self.paths.clear()
        self.changed.emit()

    def evidence(self, year: int) -> list[model.Evidence]:
        out = []
        for row, path in enumerate(self.paths):
            cell = lambda col, row=row: (self.item(row, col).text() if self.item(row, col) else "")  # noqa: E731
            ev = model.Evidence(path=path, day=_parse_day(cell(1), year))
            if self.kind != model.STAY:
                ev.amount = _parse_int(cell(2))
            if self.kind in PLACE_COL:
                ev.place = cell(PLACE_COL[self.kind]).strip()
            if self.kind == model.PUBLIC:
                ev.mode = cell(3).strip()
            elif self.kind == model.LODGING:
                ev.nights = max(1, _parse_int(cell(3)) or 1)
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


class TravelPage(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._info_done = False
        self._made: Path | None = None
        self.tables: dict[str, EvidenceTable] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(12)
        layout.addLayout(self._build_head())
        self.step_info = self._build_info()
        self.step_files = self._build_files()
        self.step_make = self._build_make()
        self.area = FlowArea()
        self.area.add(self.step_info)
        self.area.add(self.step_files, 1)
        self.area.add(self.step_make)
        layout.addWidget(self.area, 1)
        self._sync()

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
        texts.addWidget(muted_label("지원 항목별 증빙을 넣고 출장 정보를 적으면 '<이름> 출장증빙_yy.mm.dd.pdf' 를 만듭니다 (체류 → 교통비 → 숙박)."))
        head.addLayout(texts, 1)
        self.state_pill = Pill("준비", "neutral")
        head.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        head.addWidget(LogSendButton("출장증빙자료 만들기"), 0, Qt.AlignVCenter)
        return head

    def _build_info(self) -> FlowStep:
        step = FlowStep("1", "출장 정보", "출장자 · 기간 · 출발지 · 출장지와 만든 파일을 둘 폴더(보통 '출장비 지급(…)' 폴더)를 적으세요.")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("예: 홍길동")
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
        self.dest_edit = QLineEdit()
        self.dest_edit.setPlaceholderText("예: 삼척 — 여러 곳이면 다닌 차례대로 쉼표로: 삼척, 강릉")
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
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("만든 출장증빙을 둘 폴더")
        folder_button = QPushButton("폴더 고르기")
        folder_button.clicked.connect(self._pick_folder)
        rows = (
            ("출장자", self.name_edit), ("출장기간", self._pair(self.start_edit, "~", self.end_edit)),
            ("출발지", self.origin_edit), ("출장지", self.dest_edit),
            ("저장할 폴더", self._pair(self.folder_edit, folder_button)),
        )
        for i, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), i, 0)
            grid.addWidget(widget, i, 1)
        step.add_layout(grid)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.info_next = QPushButton("다음")
        self.info_next.setObjectName("primary")
        self.info_next.clicked.connect(self._info_finished)
        buttons.addWidget(self.info_next)
        step.add_layout(buttons)
        step.edit.connect(self._edit_info)
        for edit in (self.name_edit, self.folder_edit):
            edit.textChanged.connect(self._sync)
        return step

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
        step = FlowStep("2", "지원 항목별 증빙", "항목마다 파일을 넣고(끌어다 놓기 · [파일 넣기]) 일자 · 금액을 확인하세요. "
                        "출장 폴더에 '체류' · '대중교통' · '하이패스' · '숙박' 하위 폴더가 있으면 [폴더에서 한꺼번에] 로 나눠 넣습니다.")
        top = QHBoxLayout()
        scan = QPushButton("폴더에서 한꺼번에")
        scan.clicked.connect(self._scan)
        top.addWidget(scan)
        top.addStretch(1)
        step.add_layout(top)
        for kind in (model.STAY, model.PUBLIC, model.TOLL, model.LODGING):
            table = EvidenceTable(kind)
            table.changed.connect(self._sync)
            table.year = self._year
            table.places = self._places
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
        step.add(self._build_lodging())
        self._on_places()
        return step

    def _build_lodging(self) -> QWidget:
        """숙박 상한 칸 — 숙박 영수증을 넣었을 때만 보인다. 전에는 ① 출장 정보에 있어 숙박이 늘 있어야 하는 것처럼 보였다(담당자 2026-10-27)."""
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
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 6)
        self.map_edit = QLineEdit()
        self.map_edit.setPlaceholderText("네이버 지도 길찾기 캡처(가장 짧은 거리 경로)")
        self.map_edit.textChanged.connect(self._sync)
        map_button = QPushButton("지도 그림 고르기")
        map_button.clicked.connect(self._pick_map)
        # 구간마다 km 칸 — 출장지가 하나면 가는 길 · 오는 길, 여러 곳이면 출발지 → 출장지들 → 출발지 구간마다(_on_places 가 다시 만든다)
        self.leg_spins: list[QDoubleSpinBox] = []
        self.legs_box = QWidget()
        self.legs_row = QHBoxLayout(self.legs_box)
        self.legs_row.setContentsMargins(0, 0, 0, 0)
        self.legs_row.setSpacing(8)
        self.total_label = QLabel("총 이동경로 0km")
        grid.addWidget(QLabel("이동경로(자차)"), 0, 0)
        grid.addWidget(self._pair(self.map_edit, map_button), 0, 1)
        grid.addWidget(self.legs_box, 1, 1)
        grid.addWidget(muted_label("거리 · 지도는 지금은 직접 넣습니다 — 앱이 네이버 지도에서 찾아오는 것은 준비 중입니다."), 2, 1)
        return box

    def _build_make(self) -> FlowStep:
        step = FlowStep("3", "출장증빙 만들기", "확인할 것을 보고 [만들기] 를 누르세요. 같은 이름의 파일이 있으면 덮어쓰지 않고 _2 를 붙입니다.")
        self.plan_label = WrapLabel("")
        self.plan_label.setObjectName("body")
        step.add(self.plan_label)
        self.problem_label = WrapLabel("")
        self.problem_label.setObjectName("muted")
        step.add(self.problem_label)
        row = QHBoxLayout()
        self.make_button = QPushButton("출장증빙 PDF 만들기")
        self.make_button.setObjectName("primary")
        self.make_button.clicked.connect(self._make)
        self.open_button = QPushButton("파일 열기")
        self.open_button.clicked.connect(lambda: self._made and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._made))))
        self.folder_button = QPushButton("폴더 열기")
        self.folder_button.setObjectName("ghost")
        self.folder_button.clicked.connect(lambda: self._made and QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._made.parent))))
        row.addWidget(self.make_button)
        row.addWidget(self.open_button)
        row.addWidget(self.folder_button)
        row.addStretch(1)
        step.add_layout(row)
        self.result_label = WrapLabel("")
        self.result_label.setObjectName("body")
        step.add(self.result_label)
        return step

    # ── 출장 정보 ────────────────────────────────────────────────────────
    def _on_dates(self) -> None:
        if self.end_edit.date() < self.start_edit.date():
            self.end_edit.setDate(self.start_edit.date())
        self._sync()

    def _places(self) -> list[str]:
        return model.split_places(self.dest_edit.text())

    def _on_places(self) -> None:
        places = self._places()
        for table in self.tables.values():
            table.show_places(places)
        self._build_legs(places)
        self._on_region()

    def _build_legs(self, places: list[str]) -> None:
        if len(places) <= 1:
            names = ["출발지→도착지", "도착지→출발지"]
        else:
            stops = ["출발지", *places, "출발지"]
            names = [f"{a}→{b}" for a, b in zip(stops, stops[1:])]
        old = [spin.value() for spin in self.leg_spins]
        if len(old) == len(names) and [self.legs_row.itemAt(i * 2).widget().text() for i in range(len(names))] == names:
            return
        while self.legs_row.count():
            item = self.legs_row.takeAt(0)
            if item.widget() is not None and item.widget() is not self.total_label:
                item.widget().deleteLater()
        self.leg_spins = []
        for i, name in enumerate(names):
            spin = QDoubleSpinBox()
            spin.setRange(0, 3000)
            spin.setDecimals(1)
            spin.setSuffix(" km")
            if i < len(old):
                spin.setValue(old[i])
            spin.valueChanged.connect(self._sync)
            self.legs_row.addWidget(QLabel(name))
            self.legs_row.addWidget(spin)
            self.leg_spins.append(spin)
        if len(places) <= 1:
            self.leg_spins[1].setSpecialValueText("가는 길과 같음")      # 0 이면 오는 길 = 가는 길(왕복 같은 경로)
        self.legs_row.addWidget(self.total_label)
        self.legs_row.addStretch(1)

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

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "만든 출장증빙을 둘 폴더(출장비 지급 폴더)")
        if path:
            self.folder_edit.setText(path)

    def _info_finished(self) -> None:
        self._info_done = True
        self._sync()

    def _edit_info(self) -> None:
        self._info_done = False
        self._sync()

    # ── 증빙 ────────────────────────────────────────────────────────────
    def _year(self) -> int:
        return self.start_edit.date().year()

    def _add_files(self, kind: str) -> None:
        start = self.folder_edit.text() or ""
        files, _ = QFileDialog.getOpenFileNames(self, f"{model.KIND_NAMES[kind]} 증빙 파일", start, FILE_FILTER)
        if files:
            self.tables[kind].add_files([Path(f) for f in files], self._year())

    def _pick_map(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "이동경로 지도 그림", self.folder_edit.text() or "", "그림 (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.map_edit.setText(path)

    def _scan(self) -> None:
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            folder = QFileDialog.getExistingDirectory(self, "출장 폴더(하위 폴더 '체류' · '대중교통' · '하이패스' · '숙박')")
            if not folder:
                return
            if not self.folder_edit.text().strip():
                self.folder_edit.setText(folder)
        found = model.scan_folder(Path(folder))
        for kind, paths in found.files.items():
            self.tables[kind].add_files(paths, self._year())
        if found.route_map and not self.map_edit.text():
            self.map_edit.setText(str(found.route_map))
        added = sum(len(p) for p in found.files.values())
        lines = [f"{model.KIND_NAMES[k]} {len(p)}개" for k, p in found.files.items() if p]
        message = f"{added}개를 넣었습니다" + (f" — {' · '.join(lines)}" if lines else "") + "."
        if found.unsorted:
            names = ", ".join(p.name for p in found.unsorted[:8]) + (" …" if len(found.unsorted) > 8 else "")
            message += f"\n\n이름으로 항목을 정하지 못해 넣지 않은 파일 {len(found.unsorted)}개: {names}\n필요하면 그 항목의 [파일 넣기] 로 넣으세요."
        QMessageBox.information(self, "폴더에서 넣기", message)

    # ── 만들기 ──────────────────────────────────────────────────────────
    def trip(self) -> model.Trip:
        year = self._year()
        region = "" if self.region_box.currentIndex() == 0 else self.region_box.currentText()
        map_text = self.map_edit.text().strip()
        return model.Trip(
            name=self.name_edit.text().strip(),
            start=self.start_edit.date().toPython(), end=self.end_edit.date().toPython(),
            origin=self.origin_edit.text().strip(), destination=self.dest_edit.text().strip(),
            region=region, lodging_cap=(self.cap_spin.value() or None) if self.cap_spin.isEnabled() else None,
            people=self.people_spin.value(),
            stay=self.tables[model.STAY].evidence(year), public=self.tables[model.PUBLIC].evidence(year),
            tolls=self.tables[model.TOLL].evidence(year), lodging=self.tables[model.LODGING].evidence(year),
            route_map=Path(map_text) if map_text else None,
            legs=[spin.value() or None for spin in self.leg_spins],
        )

    def _sync(self) -> None:
        if not hasattr(self, "make_button"):
            return
        self.lodging_box.setVisible(bool(self.tables[model.LODGING].paths))
        legs = [v for _, v in self.trip().route_legs() if v] if self.leg_spins else []
        self.total_label.setText(f"총 이동경로 {model.km(sum(legs))}")
        info_ready = bool(self.name_edit.text().strip() and self.folder_edit.text().strip())
        self.info_next.setEnabled(info_ready)
        done = self._info_done and info_ready
        name = self.name_edit.text().strip()
        start, end = self.start_edit.date().toPython(), self.end_edit.date().toPython()
        self.step_info.set_state(DONE if done else CURRENT,
                                 f"{name} · {start:%m-%d}~{end:%m-%d} · {self.dest_edit.text().strip() or '출장지 없음'}")
        self.step_files.set_state(OPEN if done else HIDDEN)
        self.step_make.set_state(OPEN if done else HIDDEN)
        trip = self.trip()
        plan = model.pages(trip)
        counts = [f"{model.KIND_NAMES[k]} {len(t.paths)}개" for k, t in self.tables.items() if t.paths]
        self.plan_label.setText(f"쪽 {len(plan)}개(증빙 PDF 가 여러 쪽이면 더 늘 수 있음) — " + (" · ".join(counts) or "증빙 없음"))
        problems = model.problems(trip)
        self.problem_label.setText("\n".join(f"· {p}" for p in problems[:12]) + (f"\n· … 외 {len(problems) - 12}개" if len(problems) > 12 else ""))
        self.make_button.setEnabled(done and not model.blocking(trip))
        self.open_button.setVisible(self._made is not None)
        self.folder_button.setVisible(self._made is not None)
        if self._made is None:
            self.state_pill.set_status("작성 중" if done else "준비", "neutral")

    def _make(self) -> None:
        trip = self.trip()
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self, "출장증빙 만들기", f"저장할 폴더가 없습니다:\n{folder}")
            return
        problems = [p for p in model.problems(trip) if p not in model.blocking(trip)]
        if problems:
            answer = QMessageBox.question(self, "출장증빙 만들기", "확인할 것이 있습니다:\n\n" + "\n".join(problems[:10])
                                          + "\n\n그래도 만들까요?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        from ...travel import render
        out = model.output_path(folder, trip.name, trip.start)
        try:
            count = render.render(model.pages(trip), out)
        except Exception as exc:  # 그림 파일 · 폴더 권한 등
            QMessageBox.warning(self, "출장증빙 만들기", f"만들지 못했습니다: {exc}")
            return
        self._made = out
        support = sum(model.lodging_support(e, trip.cap(e), trip.people)[0] for e in trip.lodging)
        lines = [f"✓ {out.name} — {count}쪽", f"저장한 곳: {out.parent}"]
        if trip.lodging:
            lines.append(f"숙박 지원금액 합계 {model.won(support)}")
        self.result_label.setText("\n".join(lines))
        self.state_pill.set_status("만듦", "success")
        self._sync()
