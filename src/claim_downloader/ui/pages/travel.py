"""출장증빙자료 만들기 — 폴더 하나를 고르면 출장신청서를 검토해 출장자를 정리하고, 출장자별로 증빙을 확인해 '<이름> 출장증빙_yy.mm.dd(-dd).pdf' 를 만든다.

담당자 2026-10-27(첫 판) · 2026-11-10(지금 짜임, CLAUDE.md 28절):
    "1단계에는 출장증빙을 만들 폴더만 선택하고" · "어플에서 출장신청서를 검토 후 출장자를 정리, 그 다음 출장자별 증빙을 확인하고 정리" ·
    "출장증빙 파일명은 이름_체류증빙, 이름_하이패스 증빙, 이름_숙박비 증빙, 이름_대중교통 증빙" ·
    "하이패스가 있으면 자차를 이용한건데 이 경우 네이버지도 최단거리 사진과 KM정보를 출장증빙 양식에 적어야 함" ·
    "네이버지도 경로검색은 백그라운드에서 자동으로" · "목적지가 불분명해서 검색이 되지 않을경우 … 해당 출장자의 출장목적지를 입력해달라고 입력하는 박스".
    ① 폴더 → ② 출장신청서 검토 · 출장자(출장자 · 기간 · 출발지 · 출장지, 목적지가 분명하지 않으면 출장자마다 입력 칸) →
    ③ 출장자별 증빙(출장자마다 확인 표 · 항목별 증빙 표에 출장자 칸 · 하이패스가 있는 출장자의 네이버 지도 최단거리 가는 길 · 오는 길 · 총 km) →
    ④ 미리 보기 · 고치기 → ⑤ 출장자마다 만들기(담당자 2026-11-10 — PDF 만들기가 마지막 단계).
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
    QApplication,
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
from ...travel import ai_read, application, fuels, model, navermap
from .. import folder_picker
from ..art import Art
from ..tokens import COLORS
from ..travel_fuel_card import fuel_box
from ..travel_preview import MAKE as PREVIEW_MAKE
from ..travel_preview import PreviewPanel, TravelPreview
from ..flow import CURRENT, DONE, HIDDEN, OPEN, FlowArea, FlowStep, RestartButton
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
AMOUNT_KINDS = (model.PUBLIC, model.TOLL, model.LODGING)      # 셋째 칸(2)이 금액인 표
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
# ② 출장 그룹 — 신청서의 출장마다(담당자 2026-11-16 "출장신청서를 근거로 출장 그룹을 나누어서 출장자, 기간, 목적지, 차량연료를 2단계에서 선택")
GROUP_COLUMNS = ("만들기", "출장 그룹", "출장자", "출장기간", "출장지", "차량 연료")
NO_CAR_TEXT = "해당없음 (동승 · 자차 아님)"
PEOPLE_COLUMNS = ("출장자", "체류", "대중교통", "하이패스", "숙박", "기타", "자차 최단거리", "확인할 증빙", "확인할 것")
PEOPLE_SPAN = 7           # 앞 일곱 칸(출장자 · 개수 · 자차)은 그 사람의 확인할 것 줄들을 합쳐 한 칸
REF_ROLE = Qt.UserRole + 8
AUTO_ROLE = Qt.UserRole + 9      # 체류 일자 칸에 앱이 파일 이름의 차례 번호로 적은 값 — 사람이 고치면(값이 다르면) 다시 덮어쓰지 않는다
ROUTE_COLUMNS = ("출장자", "구간", "출발 → 목적지", "km", "지도 그림", "상태")
NAMING = "'이름_체류증빙' · '이름_하이패스 증빙' · '이름_숙박비 증빙' · '이름_대중교통 증빙'"
FUELS = model.FUELS


def _parse_day(text: str, year: int) -> date | None:
    return model.guess_day(text.strip(), year) if text.strip() else None


def _parse_int(text: str) -> int | None:
    """금액 · 박 수 칸 — '4100+4100' 같은 셈도 받는다(model.amount_of)."""
    return model.amount_of(text)


def _parse_km(text: str) -> float | None:
    cleaned = "".join(ch for ch in (text or "") if ch.isdigit() or ch == ".")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


class _Block(QWidget):
    """줄바꿈 글이 든 묶음(자차 이동경로 · 숙박 상한) — 지금 폭에서 잰 높이를 그냥 최소 높이로 알린다. 폭에 따라 높이가 바뀌는
    칸(heightForWidth)이 단계 안에 있으면 Qt 가 단계에 그보다 낮은 칸을 주고 위의 표(③ 출장자별 표)를 눌러 줄과 겹쳤다(2026-11-16)."""

    _last = -1

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return False

    def _height(self) -> int:
        layout = self.layout()
        if layout is None:
            return 0
        width = self.width() if self.width() > 100 else 900
        return layout.totalHeightForWidth(width) if layout.hasHeightForWidth() else layout.totalMinimumSize().height()

    def minimumSizeHint(self):  # noqa: N802
        hint = super().minimumSizeHint()
        hint.setHeight(self._height())
        return hint

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        hint.setHeight(self._height())
        return hint

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        height = self._height()
        if height != self._last:
            self._last = height
            self.updateGeometry()


class _FitTable(QTableWidget):
    """줄이 다 보이는 높이를 바라는 표 — 자리가 모자라면 최소 높이까지 줄고 안에서 스크롤한다(최소 높이를 크게 잡으면 단계 칸이
    그만큼 못 줄 때 아래 줄과 겹쳤다)."""

    want = 0

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        if self.want:
            hint.setHeight(self.want)
        return hint


class EvidenceTable(QTableWidget):
    """항목 하나의 증빙 표(보이지 않는 값 그릇 — 2026-11-16 ③ 은 출장자별 표 하나). 일자 · 금액 · 출장자는 짐작해 채우고 미리 보기에서 고친다."""

    changed = Signal()

    def __init__(self, kind: str, parent: QWidget | None = None):
        super().__init__(0, len(COLUMNS[kind]), parent)
        self.kind = kind
        self.person_col = len(COLUMNS[kind]) - 1
        self.paths: list[Path] = []
        self.parts: list[int | None] = []          # 줄마다 PDF 의 몇 번째 영수증인지(하이패스 '총 N 건' 인쇄를 영수증마다 한 줄로)
        self.orders: list[int | None] = []         # 체류 증빙 파일 이름 끝의 차례 번호('체류 증빙2' → 2) — 일자를 못 읽었을 때 출장 N일째로
        self.keys: list[str] = []                  # 줄마다 영수증 승인번호(같은 영수증이 두 파일에 있으면 한 번만 — model.dedupe)
        self.ai_rows: list[bool] = []              # 줄마다 AI(Claude Code)가 그림 · 스캔 영수증에서 읽은 값이 들었는지
        self.year = lambda: date.today().year      # 화면이 출장 시작일의 해로 바꿔 끼운다 — '0528' 같은 이름의 해
        self.places = lambda: []                   # 화면이 출장지 목록으로 바꿔 끼운다 — 파일 경로로 출장지를 짐작
        self.people = lambda: []                   # 화면이 출장자 목록으로 바꿔 끼운다 — 파일 이름 맨 앞의 이름으로 출장자를 짐작
        self.root = lambda: None                   # 출장 폴더 — 위 폴더 이름으로 짐작할 때 그 아래만(윈도우 사용자 폴더 이름이 출장자가 되지 않게)
        self.period_of = lambda person: (None, None)   # 화면이 그 출장자 그룹의 (시작일, 끝날)로 바꿔 끼운다 — 차례 번호를 일자로
        self.setHorizontalHeaderLabels(COLUMNS[kind])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, self.columnCount()):
            self.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setMinimumHeight(110)
        self.setColumnHidden(self.person_col, True)
        if kind in NEEDED:
            self.setItemDelegate(_UnclearDelegate(self))
            for col in NEEDED[kind]:                   # 비어 있어도 '확인 필요' 가 보이는 폭
                self.horizontalHeader().setSectionResizeMode(col, QHeaderView.Interactive)
                self.setColumnWidth(col, 104)
        self.itemChanged.connect(self._on_item)

    def _on_item(self, item) -> None:
        shown = ""
        if item is not None and item.column() == 1 and item.text().strip():
            # 일자는 어떻게 적어도('20261020' · '2026.10.20' · '10.20') 2026-10-20 꼴로 고쳐 보인다(담당자 2026-11-10)
            day = _parse_day(item.text(), self.year())
            shown = day.isoformat() if day is not None else ""
        elif item is not None and item.column() == 2 and self.kind in AMOUNT_KINDS and item.text().strip():
            # 금액 칸은 엑셀처럼 셈도 — '4100+4100' 을 적으면 8,200 으로(담당자 2026-11-10)
            number = _parse_int(item.text())
            shown = f"{number:,}" if number is not None else ""
        if shown and item.text() != shown:
            self.blockSignals(True)
            item.setText(shown)
            self.blockSignals(False)
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
                # 상자를 못 나누면 한 줄 — 첫 이용일 · 합계(전에는 글의 첫 날짜 · 첫 금액만 들어가 다른 날의 통행료가 빠졌다)
                ev = model.guess(path, year)
                days = [d for d, _ in found if d]
                ev.day = min(days) if days else ev.day
                ev.amount = sum(a for _, a in found)
                return [ev]
        return [model.guess(path, year, route=self.kind == model.PUBLIC, stay=self.kind == model.STAY)]

    def _add_row(self, ev: model.Evidence) -> None:
        path = ev.path
        self.paths.append(path)
        self.parts.append(ev.part)
        self.orders.append(model.stay_order(path.stem) if self.kind == model.STAY and ev.day is None else None)
        self.keys.append(ev.receipt_key)
        self.ai_rows.append(False)
        row = self.rowCount()
        self.insertRow(row)
        name = QTableWidgetItem(model.shown_name(path, self.root()) + (f" ({ev.part + 1}번째 영수증)" if ev.part is not None else ""))
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
        self.setItem(row, self.person_col, QTableWidgetItem(model.person_of(path, self.people(), self.root())))

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
                self.setItem(row, self.person_col, QTableWidgetItem(model.person_of(path, names, self.root())))
        self.blockSignals(False)

    def clear_all(self) -> None:
        self.setRowCount(0)
        self.paths.clear()
        self.parts.clear()
        self.orders.clear()
        self.keys.clear()
        self.ai_rows.clear()
        self.changed.emit()

    def sync(self, paths: list[Path], year: int, changed: set) -> tuple[int, int]:
        """폴더를 다시 읽은 대로 맞춘다 — 없어진 파일 · 바뀐 파일(changed)의 줄은 빼고, 새 파일 · 바뀐 파일은 다시 짐작해 넣는다.
        그대로인 파일의 줄은 사람이 고친 값(일자 · 금액 …)을 그대로 둔다. (뺀 줄, 넣은 파일)."""
        keep = set(paths) - set(changed)
        drop = [row for row, path in enumerate(self.paths) if path not in keep]
        self.blockSignals(True)
        for row in reversed(drop):
            self.removeRow(row)
            del self.paths[row], self.parts[row], self.orders[row], self.keys[row], self.ai_rows[row]
        self.blockSignals(False)
        new = [p for p in paths if p not in self.paths]
        if new:
            self.add_files(new, year)
        elif drop:
            self.mark_unclear()
            self.changed.emit()
        return len(drop), len(new)

    # 항목마다 AI 로 채울 칸(칸 번호 → 읽은 값의 이름) — 비어 있는 칸만 채운다
    AI_CELLS = {
        model.STAY: {1: "date", SHOP_COL: "address"},
        model.PUBLIC: {1: "date", 2: "amount", 3: "mode", 4: "origin", 5: "goal"},
        model.TOLL: {1: "date", 2: "amount"},
        model.LODGING: {1: "date", 2: "amount", 3: "nights"},
    }

    def ai_wanted(self) -> list[Path]:
        """AI 로 읽을 파일 — 꼭 있어야 할 칸이 빈 줄(하이패스 '총 N 건' 의 영수증 한 장 줄은 PDF 글자로 이미 읽음)."""
        cells = self.AI_CELLS.get(self.kind)
        if not cells:
            return []
        out = []
        for row, path in enumerate(self.paths):
            if self.parts[row] is not None or path in out:
                continue
            cols = [c for c in cells if c != 3 or self.kind != model.LODGING]     # 박 수는 기본 1 이 들어 있다
            if any(not (self.item(row, c).text().strip() if self.item(row, c) else "") for c in cols):
                out.append(path)
        return out

    def apply_ai(self, path: Path, found: dict) -> int:
        """AI 가 읽은 값(ai_read.summary)으로 그 파일 줄의 빈 칸만 채운다 — 파일 이름 · PDF 글자 · 차례 번호 · 사람이 적은 값이 먼저.
        채운 칸 수."""
        cells = self.AI_CELLS.get(self.kind, {})
        if not found or not cells:
            return 0
        split = self._split_tolls(path, found)
        if split:
            return split
        count = 0
        self.blockSignals(True)
        for row, own in enumerate(self.paths):
            if own != path or self.parts[row] is not None:
                continue
            if found.get("approvalNo") and not self.keys[row]:
                self.keys[row] = found["approvalNo"]
            for col, key in cells.items():
                item = self.item(row, col)
                if item is None:
                    item = QTableWidgetItem("")
                    self.setItem(row, col, item)
                value = found.get(key)
                if key == "nights" and self.kind == model.LODGING:
                    if not value or item.text().strip() not in ("", "1"):
                        continue
                elif item.text().strip() or not value:
                    continue
                if key == "amount":
                    text = f"{value:,}"
                elif key == "address":
                    text = model.region_of(str(value))
                else:
                    text = str(value)
                if not text or item.text().strip() == text:
                    continue
                item.setText(text)
                days = found.get("days") or []
                if key == "date" and len(days) > 1:
                    item.setToolTip(f"영수증에서 AI(Claude Code)가 읽은 값 — 한 파일에 이용일자가 여럿({' · '.join(days)})이라 첫 날로 적었습니다. "
                                    "영수증마다 파일을 나누면 일자별로 묶입니다")
                else:
                    item.setToolTip("영수증에서 AI(Claude Code)가 읽은 값 — 다르면 고치세요")
                count += 1
            if count:
                self.ai_rows[row] = True
        self.blockSignals(False)
        if count:
            self.mark_unclear()
            self.changed.emit()
        return count

    def _split_tolls(self, path: Path, found: dict) -> int:
        """하이패스 영수증 여러 장이 든 그림 · 스캔 파일을 AI 가 읽었으면 영수증마다 한 줄로 나눈다(담당자 2026-11-16 — 10월 29일 · 30일 영수증이
        한 그림에 있어 일자를 하나로 못 정해 비워 두었다). 그림의 영수증 상자 수와 AI 가 읽은 영수증 수가 같고, 영수증마다 일자가 있고,
        그 파일 줄의 일자가 비었을 때만(사람이 적은 일자는 둔다). 상자 i 는 AI 가 보이는 차례로 읽은 i 번째 영수증. 채운 칸 수(못 나누면 0)."""
        receipts = found.get("receipts") or []
        if self.kind != model.TOLL or len(receipts) < 2 or not all(r.get("date") for r in receipts):
            return 0
        rows = [row for row, own in enumerate(self.paths) if own == path]
        if len(rows) != 1 or self.parts[rows[0]] is not None:
            return 0
        row = rows[0]
        day = self.item(row, 1)
        if day is not None and day.text().strip():
            return 0
        try:
            from ...travel import render
            boxes = len(render.receipt_images(path))
        except Exception:  # noqa: BLE001 — 그림을 못 읽으면 나누지 않는다(한 줄 그대로)
            boxes = 0
        if boxes != len(receipts):
            return 0
        person = self.item(row, self.person_col)
        person = person.text() if person is not None else ""
        self.blockSignals(True)
        self.removeRow(row)
        del self.paths[row], self.parts[row], self.orders[row], self.keys[row], self.ai_rows[row]
        count = 0
        tip = "영수증에서 AI(Claude Code)가 읽은 값 — 다르면 고치세요"
        for i, receipt in enumerate(receipts):
            self._add_row(model.Evidence(path=path, day=model.guess_day(receipt["date"], date.today().year),
                                         amount=receipt.get("amount"), part=i))
            new = self.rowCount() - 1
            self.ai_rows[new] = True
            self.item(new, self.person_col).setText(person)
            for col in (1, 2):
                item = self.item(new, col)
                if item is not None and item.text().strip():
                    item.setToolTip(tip)
                    count += 1
        self.blockSignals(False)
        self.mark_unclear()
        self.changed.emit()
        return count

    def apply_orders(self) -> int:
        """일자를 못 읽은 체류 증빙(그림 영수증)에 파일 이름의 차례 번호로 일자를 적는다 — '체류 증빙1' 은 출장 첫날, '체류 증빙2' 는 둘째 날
        (담당자 2026-11-16 "체류일자가 여러일자의 경우 1,2,3,4로 순서를 나누겠음"). 그 출장자 그룹의 기간으로 셈하고, 기간을 넘는 번호는 적지 않는다.
        사람이 일자를 고쳤으면(앱이 적은 값과 다르면) 덮어쓰지 않는다. 적은 줄 수."""
        if self.kind != model.STAY:
            return 0
        count = 0
        self.blockSignals(True)
        for row, order in enumerate(self.orders):
            if not order:
                continue
            item = self.item(row, 1)
            if item is None:
                item = QTableWidgetItem("")
                self.setItem(row, 1, item)
            text = item.text().strip()
            if text and text != (item.data(AUTO_ROLE) or ""):
                continue                               # 사람이 적은 일자
            person = self.item(row, self.person_col)
            start, end = self.period_of(person.text().strip() if person else "")
            day = model.order_day(order, start, end)
            shown = day.isoformat() if day else ""
            if item.text() != shown:
                item.setText(shown)
            item.setData(AUTO_ROLE, shown)
            item.setToolTip(f"파일 이름의 차례 번호 {order} → 출장 {order}일째" if day else "")
            count += bool(day)
        self.blockSignals(False)
        return count

    def evidence(self, year: int) -> list[model.Evidence]:
        out = []
        for row, path in enumerate(self.paths):
            cell = lambda col, row=row: (self.item(row, col).text() if self.item(row, col) else "")  # noqa: E731
            ev = model.Evidence(path=path, day=_parse_day(cell(1), year), part=self.parts[row], person=cell(self.person_col).strip(),
                                ref=(self.kind, row), receipt_key=self.keys[row], ai=self.ai_rows[row])
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
        self._stage = "folder"                   # folder → review → files(③ · ④ 미리 보기 · ⑤ 만들기 함께)
        self._made: list[Path] = []
        self._apps: list[Path] = []              # 읽은 출장신청서 파일
        self._scan = model.Scan()
        self._sig: dict = {}                     # 훑은 증빙 파일의 (고친 때, 크기) — 앱으로 돌아올 때 폴더가 바뀌었는지 본다
        self._ai_worker = None                   # 그림 · 스캔 영수증을 AI 로 읽는 뒤 스레드(ui/travel_ai_worker.py) — 처음 쓸 때 만든다
        self._ai_tried: set = set()              # 이번에 AI 로 읽으라고 맡긴 (파일, 서명) — 실패해도 [폴더에서 다시 읽기] 전에는 다시 맡기지 않는다
        self._ai_running = 0                     # 맡긴 묶음 수(끝나면 줄어듦)
        self._ai_filled = 0
        self._done_folders: set[str] = set()     # 출장증빙을 만든 폴더(여러 폴더를 차례로 할 때)
        self._review: application.Application | None = None
        self._goal_of: dict[str, str] = {}       # 출장자마다 출장목적지(신청서 목적지가 분명하지 않아 사람이 적은 것)
        self._ask_reason: dict[str, str] = {}    # 출장자마다 목적지를 묻는 까닭(네이버 지도에서 못 찾음 등)
        self._fuel_of: dict[str, str] = {}       # 출장자마다 차량 연료 — 사람이 고른 것(담당자 2026-11-10 · 11-16 '해당없음' = 동승)
        self._groups: list[dict] = []            # 출장 그룹 — {names, start, end, dest, vias, on, origin}(담당자 2026-11-16)
        self._group_i = 0                        # ② 의 칸(출장자 · 기간 · 출장지 · 경유지)이 보여 주는 그룹
        self._loading_group = False
        self._extra: list[str] = []              # 신청서에 없는데 증빙 파일 이름 맨 앞에서 읽어 더한 출장자
        self._route_checked = False              # 자차 경로(출발지 · 경유지 · 목적지 · 연료)를 사람이 확인했는지 — 바뀌면 다시 확인
        self._routes: dict[tuple, dict] = {}     # (출장자, 구간 번호) → {origin, goal, label, km, image, status}
        self._searching: set = set()
        self._pending_route: tuple | None = None   # 네이버 지도 창에 띄워 두고 사람의 확인을 기다리는 구간 — [이 경로로 찍기] 가 찍는다
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
        # 미리 보기 · 고치기 → 만들기 차례 — PDF 만들기가 마지막 단계(담당자 2026-11-10 "4단계와 5단계 스위치해주세요")
        self.area.add(self.step_preview)
        self.area.add(self.step_make)
        layout.addWidget(self.area, 1)
        if self.browser is not None:
            self.browser.routes_found.connect(self._on_routes)
        self._sync()

    # ── 기록 · 브라우저 ────────────────────────────────────────────────────
    def log(self, message: str) -> None:
        """기록에는 출장자 이름을 남기지 않는다(28절) — 글에 이름을 넣지 않고, 그래도 섞이면(신청서 · 폴더 이름) 아는 이름을 가린다."""
        if self._log is None:
            from ...session import file_logger
            self._log = file_logger(lambda _m: None)
        self._log(self._mask_names(str(message)))

    def _known_names(self) -> set[str]:
        names = set(self._all_people())
        app = self._review
        if app is not None:
            names.update(app.travelers)
            for trip in app.trips:
                names.update(trip.travelers)
        return {n.strip() for n in names if n and len(n.strip()) >= 2 and n.strip() != "출장자"}

    def _mask_names(self, text: str) -> str:
        from ...share_log import mask_name
        for name in sorted(self._known_names(), key=len, reverse=True):      # '김민수' 를 '김민' 보다 먼저
            text = text.replace(name, mask_name(name))
        return text

    def _who(self, name: str) -> str:
        """기록에 쓰는 출장자 표시 — '출장자 N'(② 의 출장자 칸 차례). 이름 대신 쓴다."""
        names = self._names()
        return f"출장자 {names.index(name) + 1}" if name in names else "출장자"

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
        texts.addWidget(muted_label("폴더를 고르면 출장신청서로 출장자를 정리하고, 출장자별로 증빙을 확인해 '<이름> 출장증빙_yy.mm.dd.pdf'(여러 날이면 _yy.mm.dd-dd) 를 만듭니다."))
        head.addLayout(texts, 1)
        self.state_pill = Pill("준비", "neutral")
        head.addWidget(self.state_pill, 0, Qt.AlignVCenter)
        head.addWidget(LogSendButton("출장증빙자료 만들기"), 0, Qt.AlignVCenter)
        return head

    def _build_folder(self) -> FlowStep:
        """① 폴더만 — 담당자 2026-11-10 "1단계에는 출장증빙을 만들 폴더만 선택하고" · "여러 폴더를 선택할 수 있도록".
        넣은 폴더들은 차례로 하나씩 ② → ③ → ④ 미리 보기 → ⑤ 만들기를 거친다(폴더마다 출장신청서 · 출장자 · 증빙이 다르다)."""
        step = FlowStep("1", "출장증빙을 만들 폴더를 고르세요",
                        f"보통 '출장비 지급(…)' 폴더 — 출장신청서와 증빙 파일({NAMING})이 든 폴더. 여러 개면 모두 넣으세요(끌어다 놓아도 됩니다) — "
                        "차례로 하나씩 만들고, 만든 출장증빙은 그 폴더에 둡니다.")
        self.folder_edit = QLineEdit()           # 지금 하는 폴더(화면에는 목록으로 보인다)
        self.folder_edit.hide()
        self.folder_list = FolderList()
        self.folder_list.dropped.connect(lambda paths: self._add_folders(paths, start=True))
        self.folder_list.itemChanged.connect(lambda _item: self._sync())
        self.folder_list.itemDoubleClicked.connect(lambda item: self._reload(item.data(Qt.UserRole)))
        self.folder_list.setToolTip("두 번 누르면 그 폴더를 처음부터 다시 읽습니다")
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
        drop.setToolTip("목록에서 고른 폴더를 뺍니다 — 지금 하던 폴더면 읽은 것도 비웁니다(폴더의 파일은 그대로)")
        drop.clicked.connect(self._drop_folders)
        # 폴더의 파일을 고친 뒤 처음부터 — 출장신청서 · 출장자 · 증빙을 다시 읽는다(담당자 2026-11-16 "폴더 내 파일을 수정해가지고
        # 다시 만들기를 시작하려고 하는데 … 다시 시작할 수 있는 기능이 없네요")
        self.reload_button = QPushButton("처음부터 다시 읽기")
        self.reload_button.setToolTip("폴더의 파일을 고쳤으면 — 출장신청서 · 출장자 · 증빙을 처음부터 다시 읽습니다(② 에서 고친 값은 지워집니다)")
        self.reload_button.clicked.connect(lambda: self._reload(self.folder_edit.text().strip()))
        self.start_button = QPushButton("")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start_folders)
        row.addWidget(add)
        row.addWidget(parent)
        row.addWidget(drop)
        row.addStretch(1)
        row.addWidget(self.reload_button)
        row.addWidget(self.start_button)
        step.add_layout(row)
        self.folder_note = muted_label("")
        step.add(self.folder_note)
        step.edit.connect(lambda: self._go("folder"))
        return step

    # ── 여러 폴더 ──────────────────────────────────────────────────────────
    @staticmethod
    def _trip_root() -> str:
        """폴더 고르기 창이 처음 여는 곳 — 출장비 폴더(model.trip_root). 하던 폴더 안이 아니라 늘 그 폴더에서(담당자 2026-11-10)."""
        return model.trip_root(settings.load().travel_root, folder_picker.desktops())

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
        path = QFileDialog.getExistingDirectory(self, "출장 폴더들이 든 상위 폴더", self._trip_root())
        if not path:
            return
        found = [d for d in sorted(Path(path).iterdir())
                 if d.is_dir() and not model.skip_part(Path(d.name) / "x") and model.looks_like_trip(d)]   # '기타' 폴더는 출장 폴더가 아니다
        added = self._add_folders(found)
        self.folder_note.setText(f"'{Path(path).name}' 아래에서 출장 폴더 {added}개를 넣었습니다 — 만들지 않을 폴더는 체크를 푸세요."
                                 if found else f"'{Path(path).name}' 바로 아래에 출장신청서나 증빙 파일이 든 폴더가 없습니다.")

    def _drop_folders(self) -> None:
        """고른 줄을 뺀다 — 고른 줄이 없으면 지금 줄. 지금 하던 폴더를 빼면 읽은 것(출장자 · 증빙 · 경로)도 비운다(폴더의 파일은 그대로)."""
        items = self.folder_list.selectedItems() or ([self.folder_list.currentItem()] if self.folder_list.currentItem() else [])
        if not items:
            QMessageBox.information(self, "고른 줄 빼기", "뺄 폴더를 목록에서 먼저 누르세요.")
            return
        current = self.folder_edit.text().strip()
        dropped_current = False
        for item in items:
            path = item.data(Qt.UserRole)
            dropped_current = dropped_current or path == current
            self._done_folders.discard(path)
            self.folder_list.takeItem(self.folder_list.row(item))
        if dropped_current:
            self._clear_current()
        self._mark_folders()
        self._sync()

    def _clear_current(self) -> None:
        """지금 폴더에서 읽은 것을 모두 비운다 — 다시 고르거나 다시 읽을 때 앞 폴더의 출장자 · 증빙 · 경로가 섞이지 않게."""
        self.folder_edit.setText("")
        self._review, self._apps, self._scan, self._sig = None, [], model.Scan(), {}
        self._groups, self._group_i, self._extra = [], 0, []
        self._fuel_of.clear()
        self._goal_of.clear()
        self._ask_reason.clear()
        self._routes.clear()
        self._searching.clear()
        self._pending_route = None
        self._made = []
        self._loading_group = True
        try:
            self.name_edit.setText("")
            self.dest_edit.setText("")
            for edit in list(self.via_edits):
                self._drop_via(edit.parentWidget(), edit)
        finally:
            self._loading_group = False
        for table in self.tables.values():
            table.clear_all()
        self._forget_pictures()
        self.review_label.setText("")
        self.result_label.setText("")
        self.ai_note.setText("")
        self.ai_note.hide()
        self._uncheck_route()
        self._stage = "folder"
        if hasattr(self, "route_table"):
            self._on_route_inputs()

    def _restart_question(self) -> str:
        """[새로 시작] 을 누르면 묻는 글 — 아직 출장증빙을 만들지 않은 폴더가 목록에서 빠질 때만(다 만들었으면 묻지 않는다)."""
        left = [f for f in self._folders(checked=False) if f not in self._done_folders]
        if not left:
            return ""
        return (f"아직 출장증빙을 만들지 않은 폴더 {len(left)}개가 목록에서 빠지고, 읽은 출장신청서 · 출장자 · ③ ④ 에서 고친 값이 사라집니다.\n"
                "폴더의 파일과 이미 만든 출장증빙 PDF 는 그대로입니다.\n\n"
                "목록을 비우고 ① 폴더 고르기부터 새로 시작할까요?")

    def start_over(self) -> None:
        """⑤ [새로 시작] — 폴더 목록 · 읽은 것 · 만든 표시를 모두 비우고 ① 부터(담당자 2026-11-16). 폴더의 파일 · 만든 PDF 는 그대로.
        뒤에서 도는 AI 읽기 · 네이버 지도 찾기의 결과는 표 · 구간이 비어 있어 들어오지 않는다(_on_ai_done · _on_routes)."""
        self._clear_current()
        self.folder_list.clear()
        self._done_folders.clear()
        self._ai_tried.clear()
        self.folder_note.setText("")
        self.route_notice.hide()
        self._mark_folders()
        self._go("folder")
        self.area.to_top()

    def _forget_pictures(self) -> None:
        """미리 보기가 기억해 둔 증빙 그림을 잊는다 — 같은 이름의 파일을 고쳤으면 새 그림으로 그리게."""
        if hasattr(self, "preview_panel"):
            self.preview_panel._cache.clear()
            self.preview_panel._needs.clear()
            self.preview_panel._selected = ()

    def _reload(self, folder: str) -> None:
        """그 폴더를 처음부터 다시 읽는다 — 출장신청서 · 출장자 · 증빙 · 경로를 비우고 ② 부터(만든 표시도 지운다)."""
        if not folder:
            QMessageBox.information(self, "처음부터 다시 읽기", "다시 읽을 폴더를 목록에서 먼저 고르세요.")
            return
        self._done_folders.discard(folder)
        self._clear_current()
        self.log("출장 폴더를 처음부터 다시 읽습니다")
        self.load_folder(folder)

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
        step.add(self._build_groups())
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
        # 차량 연료 — 출장자마다, 동승 · 대중교통이면 '해당없음'(담당자 2026-11-16 "동승하는 경우가 있어 해당없음 옵션을 추가해
        # 해당없음을 선택하면 자차 증빙 없어도 됨"). 하이패스가 없는 사람은 처음부터 해당없음, 있는 사람은 설정의 연료(없으면 고르기)
        fuel_holder = QWidget()
        fuel_col = QVBoxLayout(fuel_holder)
        fuel_col.setContentsMargins(0, 0, 0, 0)
        fuel_col.setSpacing(4)
        self.fuel_rows = QGridLayout()
        self.fuel_rows.setHorizontalSpacing(8)
        self.fuel_rows.setVerticalSpacing(4)
        fuel_col.addLayout(self.fuel_rows)
        fuel_col.addWidget(muted_label("자차로 간 사람만 연료를 고르세요 — 동승했거나 대중교통이면 '해당없음'(자차 증빙이 없어도 됩니다)."))
        self.fuel_boxes: dict[str, QComboBox] = {}
        rows = (("출장자", self.name_edit), ("출장기간", self._pair(self.start_edit, "~", self.end_edit)),
                ("출발지", self.origin_edit), ("출장지(목적지)", self.dest_edit), ("차량 연료", fuel_holder))
        for i, (label, widget) in enumerate(rows):
            grid.addWidget(QLabel(label), i, 0, Qt.AlignTop if widget is fuel_holder else Qt.AlignVCenter)
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

    def _build_groups(self) -> QWidget:
        """출장 그룹 표 — 신청서의 출장(기간 · 출장지가 같은 사람들)마다 한 줄. 줄을 고르면 아래 칸이 그 그룹을 보이고 고친다.
        '만들기' 를 끈 그룹은 출장증빙을 만들지 않는다. 그룹이 하나면 표는 숨기고 [출장 그룹 추가] 만."""
        self.group_box = QWidget()
        column = QVBoxLayout(self.group_box)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self.group_note = WrapLabel("")
        self.group_note.setObjectName("muted")
        column.addWidget(self.group_note)
        table = QTableWidget(0, len(GROUP_COLUMNS))
        table.setHorizontalHeaderLabels(GROUP_COLUMNS)
        table.verticalHeader().hide()
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = table.horizontalHeader()
        for col in range(len(GROUP_COLUMNS)):
            header.setSectionResizeMode(col, QHeaderView.Stretch if col in (2, 4) else QHeaderView.ResizeToContents)
        table.itemSelectionChanged.connect(self._on_group_pick)
        table.itemChanged.connect(self._on_group_check)
        self.group_table = table
        column.addWidget(table)
        line = QHBoxLayout()
        add = QPushButton("출장 그룹 추가")
        add.setObjectName("ghost")
        add.setToolTip("기간이나 출장지가 다른 사람이 있으면 그룹을 더해 그 사람들을 옮기세요 — 고른 그룹의 기간 · 출장지로 시작합니다")
        add.clicked.connect(self._add_group)
        self.group_drop = QPushButton("고른 그룹 빼기")
        self.group_drop.setObjectName("ghost")
        self.group_drop.clicked.connect(self._drop_group)
        line.addWidget(add)
        line.addWidget(self.group_drop)
        line.addStretch(1)
        column.addLayout(line)
        return self.group_box

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
        self.via_rows.setContentsMargins(0, 0, 0, 0)
        self.via_rows.setSpacing(4)
        self.via_edits: list[QLineEdit] = []
        self.via_holder = QWidget()                 # 경유지 칸 묶음 — 고른 그룹에 자차 출장자가 없으면 숨긴다
        self.via_holder.setLayout(self.via_rows)
        rows.addWidget(self.via_holder)
        self.via_add = QPushButton("경유지 추가")
        self.via_add.setToolTip("들른 곳이 있으면 다닌 차례대로 더하세요 — 경유지가 있으면 구간마다 지도 그림과 거리를 넣습니다")
        self.via_add.clicked.connect(lambda: self._add_via(""))
        rows.addWidget(self.via_add, 0, Qt.AlignLeft)
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
        if not self._loading_group:
            self._on_route_inputs()

    def _drop_via(self, row: QWidget, edit: QLineEdit) -> None:
        if edit in self.via_edits:
            self.via_edits.remove(edit)
        row.setParent(None)
        row.deleteLater()
        if not self._loading_group:
            self._on_route_inputs()

    def _vias(self) -> list[str]:
        return [e.text().strip() for e in self.via_edits if e.text().strip()]

    def _sync_fuel_rows(self) -> None:
        """② 의 '차량 연료' — 고른 그룹의 출장자마다 연료 고르기 칸(보기는 ERP 출장 교통비 창의 '연비/전비/수소' + 해당없음)."""
        names = self._group_names(self._group()) or []
        if list(self.fuel_boxes) != names:
            for box in self.fuel_boxes.values():
                holder = box.parentWidget()
                holder.setParent(None)
                holder.deleteLater()
            self.fuel_boxes.clear()
            for row, name in enumerate(names):
                box = fuel_box(fuels.options()[0], "")
                box.addItem(NO_CAR_TEXT, model.NO_CAR)
                box.setToolTip("동승했거나 대중교통이면 해당없음 — 자차 증빙(하이패스 · 이동경로)이 없어도 됩니다")
                box.currentIndexChanged.connect(lambda _i, n=name, b=box: self._set_fuel(n, b.currentData() or ""))
                holder = QWidget()
                line = QHBoxLayout(holder)
                line.setContentsMargins(0, 0, 0, 0)
                line.setSpacing(8)
                line.addWidget(QLabel(name))
                line.addWidget(box)
                line.addStretch(1)
                self.fuel_rows.addWidget(holder, row, 0)
                self.fuel_boxes[name] = box
        for name, box in self.fuel_boxes.items():
            fuel = self._fuel(name)
            if box.currentData() != fuel:
                box.blockSignals(True)
                if fuel and box.findData(fuel) < 0:
                    box.addItem(fuel, fuel)
                box.setCurrentIndex(max(box.findData(fuel), 0))
                box.blockSignals(False)

    def _has_tolls(self, name: str) -> bool:
        """그 사람 앞으로 된 하이패스 증빙이 있는지(출장자가 한 명이면 하이패스가 있기만 하면, '공통' 하이패스도)."""
        tolls = self.tables[model.TOLL].evidence(self._year()) if model.TOLL in self.tables else []
        if not tolls:
            return False
        if len(self._all_people()) <= 1:
            return True
        return any(e.person.strip() in (name, model.SHARED) for e in tolls)

    def _fuel(self, name: str) -> str:
        """그 사람의 차량 연료 — 사람이 고른 것, 아니면 하이패스가 있으면 설정의 연료(없으면 '' = 고르기), 없으면 해당없음."""
        if name in self._fuel_of:
            return self._fuel_of[name]
        if self._has_tolls(name):
            saved = model.parse_fuels(settings.load().travel_fuels).get(name, "") if name != "출장자" else ""
            if saved:
                self._fuel_of[name] = saved                # 설정의 '출장 차량 연료' 에서 이름으로 미리 고름(담당자 2026-11-10)
            return saved
        return model.NO_CAR

    def _set_fuel(self, name: str, fuel: str, recheck: bool = True) -> None:
        self._fuel_of[name] = fuel
        if fuel and fuel != model.NO_CAR and name != "출장자":
            # 고른 연료는 설정에도 남긴다 — 다음 출장에 그 사람이 자차면 미리 골라 둔다('해당없음' 은 그 출장만의 것이라 남기지 않는다)
            fuels = model.parse_fuels(settings.load().travel_fuels)
            if fuels.get(name) != fuel:
                fuels[name] = fuel
                settings.update(travel_fuels=model.format_fuels(fuels))
        if recheck:
            self._uncheck_route()
        # 해당없음이면 자차에서 빠진다 — 구간 · 확인 칸 · '아직 빈 것' 줄도 다시(담당자 2026-11-10 "체크가 안됩니다")
        self._on_route_inputs()

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
        drivers, undecided = self._drivers(), self._undecided()
        out = []
        if drivers:
            if not self.origin_edit.text().strip():
                out.append("출발지")
            need = self._needs_goal()
            if need:
                out.append("출장목적지(" + ", ".join(need) + ")")
            elif not all(self._goal(n) or len(self._places_of(n)) > 1 for n in drivers):
                out.append("목적지")
        if undecided:
            out.append("연료" + (f"({', '.join(undecided)})" if len(self._names()) > 1 else ""))
        return out

    def _sync_car_box(self) -> None:
        drivers, undecided = self._drivers(), self._undecided()
        self.car_box.setVisible(bool(drivers or undecided))
        if not (drivers or undecided):
            return
        missing = self._car_missing()
        who = ", ".join(n for n in drivers if n != "출장자")
        mine = [n for n in drivers if n in self._group_names(self._group())] if len(self._groups) > 1 else drivers
        self.via_holder.setVisible(bool(mine))
        self.via_add.setVisible(bool(mine))
        if len(self._groups) > 1:
            others = sorted({i + 1 for i, g in enumerate(self._groups) for n in drivers if n in g["names"]} - {self._group_i + 1})
            group = (f" 경유지는 고른 출장 그룹({self._group_i + 1})의 것입니다." if mine else
                     f" 고른 출장 그룹({self._group_i + 1})에는 자차 출장자가 없습니다")
            group += f" — 자차 출장자가 있는 그룹({', '.join(map(str, others))})은 위 표에서 고르면 경유지를 고칩니다." if others else ""
        else:
            group = ""
        ask = (f"하이패스 증빙이 있는데 차량 연료를 안 고른 사람({', '.join(n for n in undecided if n != '출장자') or '출장자'}) — "
               "자차였으면 연료를, 동승했으면 '해당없음' 을 고르세요. " if undecided else "")
        lead = (f"자차 경로 확인 — 차량 연료를 고른 사람{f'({who})' if who else ''}이 자차입니다. 출발지 · 경유지(있을 때만 [경유지 추가]) · "
                "목적지를 확인해야 다음으로 넘어갑니다. 경유지가 없으면 지도 그림 하나(오는 길은 같은 거리)입니다. " if drivers else "")
        self.car_note.setText(ask + lead + group)
        lines = []
        for name in drivers:
            legs = self._legs_for(name)
            path = " → ".join([legs[0][0] or "?"] + [b or "?" for _, b, _ in legs])
            if len(legs) == 1:
                path += f" → {legs[0][0] or '?'}"
            lines.append((f"{name}: " if len(drivers) > 1 or name != "출장자" else "") + path)
        self.route_summary.setText(("경로: " + " / ".join(lines) if lines else "") + (f"\n아직 빈 것: {', '.join(missing)}" if missing else ""))
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
        """③ 출장자별 증빙 확인 — 출장자마다 증빙 수와 확인할 것(증빙마다 한 줄) 표 하나(담당자 2026-11-16 "그 아래 체류, 대중교통, 자차,
        기타 확인하는 표는 필요없음(쓸데없는 중복내용임)" · "확인해야 한다면 세부내용을 확인할 것 칸을 확인할게 있는 증빙별로 행을 나눠서" ·
        "증빙별 파일넣기 기능 필요없음"). 항목별 증빙 표(EvidenceTable)는 값을 담아 두는 곳으로만 남기고 보이지 않는다 — 고치기는 ④ 미리 보기에서."""
        step = FlowStep("3", "출장자별 증빙 확인", "폴더의 증빙을 파일 이름 맨 앞의 이름으로 출장자마다 나눴습니다. 확인할 것은 증빙마다 한 줄 — "
                        "두 번 누르면 ④ 미리 보기에서 그 증빙을 고칩니다. 다른 사람 것으로 나뉜 파일은 이름 맨 앞의 출장자 이름을 고치고(모두의 것이면 "
                        "'공통_…') [폴더에서 다시 읽기].")
        self.people_table = _FitTable(0, len(PEOPLE_COLUMNS))
        self.people_table.setHorizontalHeaderLabels(PEOPLE_COLUMNS)
        self.people_table.verticalHeader().hide()
        self.people_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.people_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.people_table.setWordWrap(True)
        self.people_table.horizontalHeader().setSectionResizeMode(len(PEOPLE_COLUMNS) - 1, QHeaderView.Stretch)
        for col in range(len(PEOPLE_COLUMNS) - 1):
            self.people_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.people_table.setMinimumHeight(140)
        self.people_table.cellDoubleClicked.connect(self._on_people_row)
        step.add(self.people_table)
        top = QHBoxLayout()
        rescan = QPushButton("폴더에서 다시 읽기")
        rescan.setToolTip("폴더의 증빙 파일을 다시 읽어 출장자 · 항목별로 나눕니다(파일 이름을 고친 뒤)")
        rescan.clicked.connect(self._rescan)
        top.addWidget(rescan)
        self.scan_note = muted_label("")
        top.addWidget(self.scan_note, 1)
        step.add_layout(top)
        # 그림 · 스캔 영수증을 AI 로 읽는 중 · 읽은 결과 한 줄(담당자 2026-11-16 KTX 영수증 "결제금액 및 일자, 이동편, 출발지 목적지 정보 다있음")
        self.ai_note = WrapLabel("")
        self.ai_note.setObjectName("muted")
        self.ai_note.hide()
        step.add(self.ai_note)
        # 항목별 증빙 표 — 보이지 않는 값 그릇(일자 · 금액 · 출장자 …). 미리 보기에서 고친 값이 여기에 적힌다(apply_edit)
        self._tables_holder = QWidget(self)
        self._tables_holder.hide()
        holder = QVBoxLayout(self._tables_holder)
        for kind in model.KINDS:
            table = EvidenceTable(kind)
            table.changed.connect(self._on_evidence)
            table.year = self._year
            table.places = self._all_places
            table.people = self._all_people
            table.root = self._root
            table.period_of = self._period_of
            self.tables[kind] = table
            holder.addWidget(table)
        step.add(self._build_route())
        step.add(self._build_lodging())
        self._on_places()
        return step

    def _root(self) -> Path | None:
        folder = self.folder_edit.text().strip() if hasattr(self, "folder_edit") else ""
        return Path(folder) if folder else None

    def _period_of(self, person: str) -> tuple:
        """그 출장자 그룹의 (시작일, 끝날) — 공통 · 모르는 사람이면 고른 그룹."""
        group = self._group_of(person) if person and person != model.SHARED else self._group()
        if group is None:
            return None, None
        return group.get("start"), group.get("end") or group.get("start")

    def _build_lodging(self) -> QWidget:
        """숙박 상한 칸 — 숙박 영수증을 넣었을 때만 보인다(담당자 2026-10-27)."""
        self.lodging_box = _Block()
        rows = QVBoxLayout(self.lodging_box)
        rows.setSizeConstraint(QVBoxLayout.SetNoConstraint)
        rows.setContentsMargins(0, 0, 0, 6)
        rows.setSpacing(4)
        rows.addWidget(self._pair("숙박 상한 지역", self.region_box, "1박 상한", self.cap_spin, "공동숙박", self.people_spin))
        self.cap_note = muted_label("")
        rows.addWidget(self.cap_note)
        self.lodging_box.hide()
        return self.lodging_box

    def _build_route(self) -> QWidget:
        """자차(하이패스가 있는 출장자) — 네이버 지도 최단거리(거리우선) 그림과 가는 길 · 오는 길 km. 앱이 앱 브라우저의 네이버 지도 탭에서 저절로 찾는다(네이버가 보안문자를 물으면 그 창에서 사람이 입력)."""
        self.route_box = _Block()
        rows = QVBoxLayout(self.route_box)
        rows.setSizeConstraint(QVBoxLayout.SetNoConstraint)
        rows.setContentsMargins(0, 0, 0, 6)
        rows.setSpacing(6)
        title = QLabel("자차 이동경로 — 네이버 지도 최단거리")
        title.setObjectName("cardTitle")
        rows.addWidget(title)
        rows.addWidget(muted_label("② 에서 차량 연료를 고른 출장자만 자차로 찾습니다. 앱이 앱 브라우저의 네이버 지도 창에 출발지 → 출장목적지 길찾기를 띄웁니다. "
                                   "그 창에서 목적지가 맞는지 보고(틀리면 그 창에서 다시 고르고 길찾기) [이 경로로 찍기 · 거리 넣기] 를 누르면, 앱이 "
                                   "'거리우선' 을 골라 화면을 찍고 km 를 넣습니다. 목적지가 하나면 그림 하나 — 오는 길은 같은 거리, 경유지가 있으면 구간마다. "
                                   "출발지 → 목적지가 같은 사람은 한 번 찍은 것을 같이 씁니다 — 목적지 글이 달라 따로 잡히면 두 사람의 줄을 함께 고르고 [같은 경로 적용]."))
        self.route_table = QTableWidget(0, len(ROUTE_COLUMNS))
        self.route_table.setHorizontalHeaderLabels(ROUTE_COLUMNS)
        self.route_table.verticalHeader().hide()
        self.route_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.route_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.route_table.horizontalHeader().setSectionResizeMode(len(ROUTE_COLUMNS) - 1, QHeaderView.Stretch)
        for col in range(len(ROUTE_COLUMNS) - 1):
            self.route_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.route_table.setMinimumHeight(90)
        self.route_table.itemChanged.connect(self._on_route_edited)
        rows.addWidget(self.route_table)
        # 확인 기다림 안내 — 네이버 지도 창에 길찾기를 띄웠으니 보고 찍으라고(담당자 2026-11-10 "사용자가 목적지를 확인하거나 틀리면 재설정")
        self.route_notice = WrapLabel("")
        self.route_notice.setObjectName("noticeText")
        self.route_notice.setStyleSheet(f"background: {COLORS['warning_bg']}; border: 1px solid {COLORS['warning']}; border-radius: 8px; padding: 8px 10px;")
        self.route_notice.hide()
        rows.addWidget(self.route_notice)
        buttons = QHBoxLayout()
        self.route_find = QPushButton("최단거리 다시 찾기")
        self.route_find.setToolTip("못 찾은 구간(또는 고른 줄)을 네이버 지도에서 다시 찾습니다 — 앱 브라우저의 네이버 지도 탭에서")
        self.route_find.clicked.connect(lambda: self._find_routes(force=True))
        manual = QPushButton("네이버 지도 창 열기")
        manual.setToolTip("앱 브라우저에 네이버 지도 길찾기를 엽니다 — 직접 출발지 · 목적지를 넣고 길찾기를 누른 뒤 [이 경로로 찍기 · 거리 넣기]")
        manual.clicked.connect(lambda: self._worker().open_site("navermap"))
        shoot = QPushButton("이 경로로 찍기 · 거리 넣기")
        shoot.setObjectName("primary")
        shoot.setToolTip("네이버 지도 창의 길찾기를 '거리우선' 으로 골라 찍고 km 를 넣습니다 — 확인 기다리는 구간(없으면 고른 줄)에")
        shoot.clicked.connect(self._capture_route)
        self.route_shoot = shoot
        pick = QPushButton("지도 그림 고르기 → 고른 줄")
        pick.setObjectName("ghost")
        pick.clicked.connect(self._pick_map)
        same = QPushButton("같은 경로 적용")
        same.setToolTip("지도 · km 가 있는 출장자의 줄과 없는 출장자의 줄을 함께 고르고 누르면 같은 경로 · 지도 그림을 넣습니다 — 신청서가 달라도 같은 곳에 간 사람")
        same.clicked.connect(self._apply_same_route)
        self.route_same = same
        for button in (self.route_find, manual, shoot, same, pick):
            buttons.addWidget(button)
        buttons.addStretch(1)
        rows.addLayout(buttons)
        self.total_label = QLabel("총 이동경로 —")
        self.total_label.setObjectName("body")
        rows.addWidget(self.total_label)
        self.route_box.hide()
        return self.route_box

    def _build_make(self) -> FlowStep:
        # 단계 이름 '출장증빙 내보내기'(담당자 2026-11-16) — 출장자가 여럿이면 사람마다 PDF 를 따로 만들어 폴더에 둔다
        step = FlowStep("5", "출장증빙 내보내기", "출장자마다 PDF 를 따로 만들어 폴더에 저장합니다 — '<이름> 출장증빙_26.11.12.pdf', "
                        "여러 날이면 '<이름> 출장증빙_26.11.12-13.pdf'. 같은 이름이 있으면 덮어쓰지 않고 _2.")
        self.restart_button = RestartButton(self.start_over, self._restart_question)
        step.add_side(self.restart_button)
        self.plan_label = WrapLabel("")
        self.plan_label.setObjectName("body")
        step.add(self.plan_label)
        self.problem_label = WrapLabel("")
        self.problem_label.setObjectName("muted")
        step.add(self.problem_label)
        row = QHBoxLayout()
        self.make_button = QPushButton("출장증빙 내보내기")
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
        """④ 미리 보기 — 만들 PDF 와 같은 쪽을 앱 안에서(담당자 2026-11-10 "5단계로 미리보기를 넣어주세요" → 같은 날 "4단계와 5단계 스위치 · 출장증빙 PDF 만들기가 마지막 단계로"). 확인할 곳을 칠하고 눌러 고친다(ui/travel_preview.py)."""
        step = FlowStep("4", "미리 보기 · 고치기", "만들 출장증빙(PDF 와 같은 쪽)입니다. 확인이 필요한 곳은 칠해져 있습니다 — 눌러서 오른쪽 칸에서 고치세요.")
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
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self._on_app_state)
        return step

    def _refresh_preview(self) -> None:
        if self._stage == "files" and not self.step_preview.isHidden():
            self.preview_panel.refresh(keep=True)

    def _on_preview_edit(self) -> None:
        if self._made:
            self.preview_note.setText("고친 내용은 ⑤ [출장증빙 내보내기] 를 다시 눌러야 PDF 에 들어갑니다.")
            self.preview_note.show()

    # ── ① 폴더 → ② 출장신청서 검토 ─────────────────────────────────────────
    def _pick_folder(self) -> None:
        """출장비 지급 폴더를 여러 개 골라 넣는다 — Ctrl · Shift 로 여러 개(담당자 2026-11-11 "폴더 여러개 선택가능하도록")."""
        paths = folder_picker.pick_folders(self, "출장증빙을 만들 폴더(출장비 지급 폴더) — Ctrl · Shift 로 여러 개", self._trip_root())
        if paths:
            self._add_folders(paths, start=True)

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
        listed = [n for t in (merged.trips if merged else []) for n in t.travelers] + (merged.travelers if merged else [])
        scan = model.scan_folder(path, list(dict.fromkeys(listed)) or None)
        # 파일 이름 맨 앞의 이름(신청서에 없는 사람)도 출장자 — 그 이름으로 한 번 더 훑어 '이름 참가확인서' 같은 기타 증빙도 그 사람 것으로
        found = model.names_in_files((p for files in scan.files.values() for p in files), root=path)
        if [n for n in found if n not in listed]:
            scan = model.scan_folder(path, list(dict.fromkeys(listed + found)))
        self._scan = scan
        self._made = []
        self.result_label.setText("")
        self.origin_edit.setText(settings.load().travel_origin)
        self._fuel_of.clear()
        names = self._fill_info(merged, scan)
        self._fill_from_scan(scan)
        self.review_label.setText(self._review_text(merged, names, scan))
        on = [g for g in self._groups if g["on"]]
        self.log(f"출장 그룹 {len(self._groups)}개 · 만들 그룹 {len(on)}개 · 출장자 {len(self._names())}명"
                 + (f" · 파일 이름에서 더한 출장자 {len(self._extra)}명" if self._extra else ""))
        if merged:
            self.log(application.log_line(merged, self._apps))
            for app in apps:
                if app.shape:
                    # 신청서의 글 모양(이름 · 곳은 □) — 늘 남긴다: 읽은 값이 틀린 때(출장지 '대상여부' · '목', 2026-11-16)도 기록으로 고치게
                    self.log(f"출장신청서 글 모양 — {app.path.name} (칸 이름 · 숫자만, 다른 글자는 □):")
                    for line in app.shape:
                        self.log("  | " + line)
        else:
            self.log(f"출장신청서 없음: {path.name} — 증빙 파일 이름으로 출장자 {len(names)}명")
        self._go("review")

    def _fill_info(self, app: application.Application | None, scan: model.Scan) -> list[str]:
        """신청서의 출장마다 출장 그룹(출장자 · 기간 · 출장지)을 짜고 고른 출장의 그룹을 칸에 — 담당자 2026-11-16
        "출장신청서를 근거로 출장 그룹을 나누어서" · "파일제목 맨앞에 있는 이름으로 출장자 구분" · "한폴더에 있는 여러명 한번에".
        폴더 이름의 날짜로 고른 출장은 늘 만들고, 다른 출장은 그 출장의 사람이 이 폴더에 증빙(파일 이름 맨 앞 이름)이 있을 때만 만든다.
        신청서에 없는데 파일 이름 맨 앞에 있는 사람은 고른 출장의 그룹에 더한다(사람이 표에서 옮긴다). 신청서가 없으면 파일 이름으로."""
        scanned = [p for files in scan.files.values() for p in files]
        root = Path(self.folder_edit.text().strip()) if self.folder_edit.text().strip() else None
        in_files = model.names_in_files(scanned, root=root)
        self._goal_of.clear()
        self._ask_reason.clear()
        self._routes.clear()
        today = self.start_edit.date().toPython(), self.end_edit.date().toPython()
        groups: list[dict] = []
        chosen = 0
        if app and app.trips:
            chosen = max(0, min(app.chosen, len(app.trips) - 1))
            for i, trip in enumerate(app.trips):
                names = list(trip.travelers) if trip.travelers else (list(app.travelers) if i == chosen else [])
                groups.append({"names": names, "start": trip.start, "end": trip.end or trip.start,
                               "dest": ", ".join(trip.places), "vias": [], "on": i == chosen,
                               "from": f"신청서 {i + 1}번째 출장" if len(app.trips) > 1 else "신청서"})
            taken = set(groups[chosen]["names"])
            for group in groups:
                if not group["on"] and set(group["names"]) & (set(in_files) - taken):
                    group["on"] = True
                    taken |= set(group["names"])
        elif app:
            groups.append({"names": list(app.travelers), "start": app.start, "end": app.end or app.start,
                           "dest": app.destination, "vias": [], "on": True, "from": "신청서"})
        else:
            groups.append({"names": [], "start": today[0], "end": today[1], "dest": "", "vias": [], "on": True, "from": ""})
        for group in groups:
            if group["start"] is None:
                group["start"], group["end"] = today
        everyone = {n for g in groups for n in g["names"]}
        self._extra = [n for n in in_files if n not in everyone]
        groups[chosen]["names"] += self._extra
        if app is not None:
            # 신청서는 있는데 거기에 없는 사람 — 그 사람의 기간은 신청서가 모르므로 증빙 일자에 맞춘다(trips · model.fit_period).
            # 신청서가 아예 없으면 기간은 사람이 ② 에 적는다(오늘 날짜에 맞춰 넓히지 않게)
            groups[chosen]["extra"] = list(self._extra)
        self._groups = groups
        self._group_i = chosen
        if app and app.origin:
            self.origin_edit.setText(app.origin)
        self._load_group(chosen)
        self._fill_group_table()
        return self._names()

    @staticmethod
    def _file_sig(scan: model.Scan) -> dict:
        """훑은 파일들의 (고친 때, 크기) — 폴더의 파일이 바뀌었는지 볼 때."""
        out = {}
        for path in [p for files in scan.files.values() for p in files] + [p for p in scan.route_maps if p] + [scan.route_map]:
            if path is None:
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            out[path] = (st.st_mtime_ns, st.st_size)
        return out

    def _where_note(self, scan: model.Scan) -> str:
        """하위 폴더에서 읽은 증빙 · '기타' 같은 폴더라 빼 둔 파일 — 담당자가 보는 폴더 밖의 파일이 섞이면 어디인지 알게(2026-11-16)."""
        root = self._root()
        if root is None:
            return ""
        nested: dict[str, int] = {}
        for path in [p for files in scan.files.values() for p in files]:
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            if len(rel.parts) > 1:
                key = "/".join(rel.parts[:-1])
                nested[key] = nested.get(key, 0) + 1
        out = ""
        if nested:
            where = ", ".join(f"'{k}' {n}개" for k, n in list(nested.items())[:5]) + (" …" if len(nested) > 5 else "")
            out += f". 하위 폴더의 증빙도 넣었습니다({where}) — 넣지 않을 파일은 '기타' 폴더로 옮기세요"
        if scan.skipped:
            out += f". '기타' 같은 폴더 · 숨은 파일 {len(scan.skipped)}개는 넣지 않았습니다"
        return out

    def _fill_from_scan(self, scan: model.Scan, changed: set | None = None) -> None:
        """훑은 증빙을 표에 — changed 가 None 이면 처음부터(표를 비우고), 아니면 폴더가 바뀐 만큼만 맞춘다(그대로인 파일의 고친 값은 둔다)."""
        sig = self._file_sig(scan)
        merged = changed is not None
        dropped = added_new = 0
        for kind, paths in scan.files.items():
            if merged:
                d, a = self.tables[kind].sync(paths, self._year(), changed)
                dropped, added_new = dropped + d, added_new + a
            else:
                self.tables[kind].clear_all()
                self.tables[kind].add_files(paths, self._year())
        self._sig = sig
        for kind, table in self.tables.items():
            table.show_people(self._all_people())
        self.tables[model.STAY].apply_orders()
        # 폴더에 이미 둔 지도 그림('… 지도 가는 길' · '… 오는 길') — 자차 출장자가 한 명이면 그 사람 구간으로
        self._scan_maps = [p for p in scan.route_maps if p] or ([scan.route_map] if scan.route_map else [])
        added = sum(len(p) for p in scan.files.values())
        lines = [f"{model.KIND_NAMES[k]} {len(p)}개" for k, p in scan.files.items() if p]
        note = f"폴더에서 증빙 {added}개를 넣었습니다" + (f" — {' · '.join(lines)}" if lines else "")
        if merged and (dropped or added_new):
            note = f"폴더의 파일이 바뀌어 다시 맞췄습니다(뺀 줄 {dropped} · 새로 읽은 파일 {added_new}) — " + note
        note += self._where_note(scan)
        QTimer.singleShot(0, self._ai_start)
        if scan.unsorted:
            names = ", ".join(p.name for p in scan.unsorted[:6]) + (" …" if len(scan.unsorted) > 6 else "")
            note += f". 이름으로 항목을 못 정해 넣지 않은 파일 {len(scan.unsorted)}개: {names} — 넣을 파일이면 파일 이름에 항목(체류 · 대중교통 · 하이패스 · 숙박)을 넣고 [폴더에서 다시 읽기]"
        self.scan_note.setText(note)

    def _review_text(self, app: application.Application | None, names: list[str], scan: model.Scan) -> str:
        extra = (f"증빙 파일 이름 맨 앞에서 신청서에 없는 출장자 {len(self._extra)}명({', '.join(self._extra)})을 읽어 "
                 f"{'출장 그룹 ' + str(self._group_i + 1) + '에' if len(self._groups) > 1 else '출장자에'} 더했습니다 — 아니면 출장자 칸에서 지우세요."
                 if self._extra else "")
        if app is None:
            from_files = f" 증빙 파일 이름 맨 앞에서 출장자 {len(names)}명({', '.join(names)})을 읽었습니다." if names else ""
            return ("출장신청서를 찾지 못했습니다 — 파일 이름에 '출장신청' 이 든 PDF(또는 .hwpx)를 이 폴더에 두면 읽습니다." + from_files
                    + " 출장 정보를 직접 적어 주세요.")
        lines = [f"출장신청서 {', '.join(p.name for p in self._apps)} 를 읽었습니다 — 찾은 칸: {', '.join(app.found) or '없음'}."]
        if len(self._groups) > 1:
            on = [i + 1 for i, g in enumerate(self._groups) if g["on"]]
            lines.append(f"출장 그룹 {len(self._groups)}개 — 만들 그룹: {', '.join(map(str, on))}. 출장자 {len(names)}명: {', '.join(names)}")
        elif names:
            lines.append(f"출장자 {len(names)}명: {', '.join(names)}")
        if app.purpose:
            lines.append(f"출장목적: {app.purpose}")
        if extra:
            lines.append(extra)
        lines += [f"확인: {n}" for n in app.notes]
        return "\n".join(lines)

    # ── 출장자 · 목적지 ──────────────────────────────────────────────────
    def _names(self) -> list[str]:
        return model.split_names(self.name_edit.text())

    def _places(self) -> list[str]:
        return model.split_places(self.dest_edit.text())

    # ── 출장 그룹(담당자 2026-11-16) ─────────────────────────────────────
    def _group(self) -> dict | None:
        return self._groups[self._group_i] if 0 <= self._group_i < len(self._groups) else None

    @staticmethod
    def _group_names(group: dict | None) -> list[str]:
        return list(group["names"]) if group else []

    def _included(self) -> list[dict]:
        """만들 그룹 — '만들기' 를 켠 그룹(하나도 없으면 고른 그룹)."""
        on = [g for g in self._groups if g["on"]]
        return on or ([self._group()] if self._group() else [])

    def _all_people(self) -> list[str]:
        """모든 그룹의 출장자 — 증빙 표의 출장자 칸 · 파일 이름으로 나누기에 쓴다('만들기' 를 끈 그룹의 사람 증빙도 그 사람 것으로)."""
        if not self._groups:
            return model.split_names(self.name_edit.text())
        return list(dict.fromkeys(n for g in self._groups for n in g["names"]))

    def _names(self) -> list[str]:
        """만들 출장자 — '만들기' 를 켠 그룹의 사람들(차례대로)."""
        if not self._groups:
            return model.split_names(self.name_edit.text())
        return list(dict.fromkeys(n for g in self._included() for n in g["names"]))

    def _group_of(self, name: str) -> dict | None:
        return next((g for g in self._included() if name in g["names"]), None) or self._group()

    def _places(self) -> list[str]:
        """고른 그룹의 출장지(② 의 칸)."""
        return model.split_places(self.dest_edit.text())

    def _places_of(self, name: str) -> list[str]:
        group = self._group_of(name)
        return model.split_places(group["dest"]) if group else self._places()

    def _all_places(self) -> list[str]:
        """만들 그룹의 출장지 모두 — 증빙 표의 출장지 칸(여러 곳이면 보인다) · 숙박 상한."""
        if not self._groups:
            return self._places()
        return list(dict.fromkeys(p for g in self._included() for p in model.split_places(g["dest"])))

    def _vias_of(self, name: str) -> list[str]:
        group = self._group_of(name)
        if group is None or group is self._group():
            return self._vias()
        return [v for v in group.get("vias", []) if v]

    def _store_group(self) -> None:
        """② 의 칸 → 고른 그룹."""
        group = self._group()
        if group is None or self._loading_group:
            return
        group["names"] = model.split_names(self.name_edit.text())
        group["start"], group["end"] = self.start_edit.date().toPython(), self.end_edit.date().toPython()
        group["dest"] = self.dest_edit.text().strip()
        group["vias"] = self._vias()

    def _load_group(self, index: int) -> None:
        """고른 그룹 → ② 의 칸(출장자 · 기간 · 출장지 · 경유지 · 차량 연료)."""
        if not self._groups:
            return
        self._group_i = max(0, min(index, len(self._groups) - 1))
        group = self._groups[self._group_i]
        self._loading_group = True
        try:
            self.name_edit.setText(", ".join(group["names"]))
            if group.get("start"):
                start, end = group["start"], group.get("end") or group["start"]
                self.start_edit.setDate(QDate(start.year, start.month, start.day))
                self.end_edit.setDate(QDate(end.year, end.month, end.day))
            self.dest_edit.setText(group.get("dest", ""))
            for edit in list(self.via_edits):
                self._drop_via(edit.parentWidget(), edit)
            for via in group.get("vias", []):
                self._add_via(via)
        finally:
            self._loading_group = False
        self._on_people()
        self._on_places()

    def _fill_group_table(self) -> None:
        table = self.group_table
        table.blockSignals(True)
        table.setRowCount(0)
        for i, group in enumerate(self._groups):
            table.insertRow(i)
            on = QTableWidgetItem("")
            on.setFlags((on.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            on.setCheckState(Qt.Checked if group["on"] else Qt.Unchecked)
            on.setToolTip("끄면 이 그룹은 출장증빙을 만들지 않습니다")
            start, end = group.get("start"), group.get("end")
            period = (f"{start:%Y-%m-%d}" + (f" ~ {end:%m-%d}" if end and end != start else "")) if start else "기간 모름"
            fuel = " · ".join(f"{n} {self._fuel(n) or '고르기'}" for n in group["names"])
            cells = [on, QTableWidgetItem(f"{i + 1}" + (f" · {group['from']}" if group.get("from") else "")),
                     QTableWidgetItem(", ".join(group["names"]) or "(출장자 없음)"), QTableWidgetItem(period),
                     QTableWidgetItem(group.get("dest") or "(출장지 없음)"), QTableWidgetItem(fuel)]
            for col, item in enumerate(cells):
                if col:
                    item.setToolTip(item.text())
                table.setItem(i, col, item)
        table.selectRow(self._group_i)
        table.blockSignals(False)
        many = len(self._groups) > 1
        table.setVisible(many)
        if many:
            height = table.horizontalHeader().height() + sum(table.rowHeight(r) for r in range(table.rowCount())) + 4
            table.setFixedHeight(min(height, 220))
        self.group_drop.setEnabled(many)
        on = sum(1 for g in self._groups if g["on"])
        self.group_note.setText(
            f"출장 그룹 {len(self._groups)}개(만들 그룹 {on}개) — 신청서의 출장(기간 · 출장지)마다 나눴습니다. 줄을 고르면 아래 칸에서 출장자 · 기간 · "
            "출장지 · 차량 연료를 고칩니다. 증빙은 파일 이름 맨 앞의 이름으로 그 사람 것이 됩니다." if many else
            "출장자마다 기간이나 출장지가 다르면 [출장 그룹 추가] 로 나누세요. 증빙은 파일 이름 맨 앞의 이름으로 그 사람 것이 됩니다.")

    def _on_group_pick(self) -> None:
        rows = sorted({i.row() for i in self.group_table.selectedIndexes()})
        if not rows or rows[0] == self._group_i or rows[0] >= len(self._groups):
            return
        self._store_group()
        self._load_group(rows[0])
        self._after_groups()

    def _on_group_check(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.row() >= len(self._groups):
            return
        self._groups[item.row()]["on"] = item.checkState() == Qt.Checked
        self._after_groups()

    def _add_group(self) -> None:
        """고른 그룹의 기간 · 출장지로 새 그룹 — 출장자는 비워 두고 사람이 옮긴다."""
        self._store_group()
        base = self._group() or {}
        self._groups.append({"names": [], "start": base.get("start"), "end": base.get("end"), "dest": base.get("dest", ""),
                             "vias": [], "on": True, "from": "추가"})
        self._load_group(len(self._groups) - 1)
        self._after_groups()
        self.name_edit.setFocus()

    def _drop_group(self) -> None:
        if len(self._groups) <= 1:
            return
        del self._groups[self._group_i]
        self._load_group(min(self._group_i, len(self._groups) - 1))
        self._after_groups()

    def _after_groups(self) -> None:
        """그룹이 바뀌면 — 증빙 표의 출장자 · 출장지 칸, 자차 구간, 표를 다시."""
        for table in self.tables.values():
            table.show_people(self._all_people())
            table.show_places(self._all_places())
        self._on_route_inputs()

    def _on_people(self) -> None:
        self._store_group()
        for table in self.tables.values():
            table.show_people(self._all_people())
        self._on_route_inputs()

    def _on_places(self) -> None:
        self._store_group()
        places = self._all_places()
        for table in self.tables.values():
            table.show_places(places)
        self._on_region()
        self._on_route_inputs()

    def _on_dates(self) -> None:
        if self.end_edit.date() < self.start_edit.date():
            self.end_edit.setDate(self.start_edit.date())
        self._store_group()
        if model.STAY in getattr(self, "tables", {}):
            self.tables[model.STAY].apply_orders()       # 체류 증빙의 차례 번호 일자는 출장 시작일로 셈한다
        if hasattr(self, "group_table") and self._groups:
            self._fill_group_table()
        self._sync()

    def _drivers(self) -> list[str]:
        """자차 출장자 — 차량 연료를 고른 사람(담당자 2026-11-16 "자차 이동경로는 연료를 선택한 출장자만 검색하도록").
        '해당없음'(동승 · 대중교통)이나 아직 안 고른 사람은 아니다. 길찾기 · 자차 확인은 이 사람들만."""
        return [n for n in (self._names() or ["출장자"]) if self._fuel(n) not in ("", model.NO_CAR)]

    def _undecided(self) -> list[str]:
        """하이패스 증빙이 있는데 차량 연료를 아직 안 고른 사람 — 자차면 연료, 동승이면 '해당없음' 을 골라야 ③ 으로 간다."""
        return [n for n in (self._names() or ["출장자"]) if self._fuel(n) == ""]

    def _goal(self, name: str) -> str:
        """그 출장자의 출장목적지 — 사람이 적은 것, 없으면 출장지 칸(하나일 때)."""
        own = self._goal_of.get(name, "").strip()
        if own:
            return own
        places = self._places_of(name)
        return places[0] if len(places) == 1 else ""

    def _stops(self, name: str) -> list[str]:
        """자차의 들른 곳 차례 — 경유지([경유지 추가]) 다음 목적지(그 출장자의 목적지, 없으면 출장지 칸의 곳들)."""
        places = self._places_of(name)
        goals = [self._goal_of[name]] if self._goal_of.get(name, "").strip() else (places if len(places) > 1 else [self._goal(name)])
        return self._vias_of(name) + goals

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
        for name in self._drivers():
            places = self._places_of(name)
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

    def _rescan(self, quiet: bool = False) -> bool:
        """증빙 파일만 다시 읽는다(② 에서 고친 출장자 · 기간 · 출장지는 그대로) — 폴더에서 없어진 파일은 빼고, 새 파일 · 고친 파일은 다시 읽고,
        그대로인 파일은 ③ · ④ 에서 고친 값을 둔다. 파일 이름 맨 앞에 새 사람이 생겼으면 고른 그룹에 더한다.
        quiet 면(앱으로 돌아올 때 · 만들기 전) 바뀐 것이 없으면 아무것도 하지 않는다 — 담당자 2026-11-16: 폴더에서 파일을 고친 뒤에도 옛 파일이
        미리 보기에 남아 같은 영수증이 두 번 보였다. 바뀌었으면 True."""
        folder = self.folder_edit.text().strip()
        if not folder or not Path(folder).is_dir():
            return False
        scan = model.scan_folder(Path(folder), self._all_people())
        old = getattr(self, "_sig", {})
        sig = self._file_sig(scan)
        if quiet and sig == old:
            return False
        changed = {p for p, v in sig.items() if p in old and old[p] != v}
        gone = [p for p in old if p not in sig]
        if not quiet:
            self._ai_tried.clear()                # 사람이 다시 읽으라고 했다 — 못 읽었던 그림 영수증도 다시 맡긴다
        self._forget_pictures()
        new = [n for n in model.names_in_files((p for files in scan.files.values() for p in files), root=Path(folder))
               if n not in self._all_people()]
        if new and self._group() is not None:
            self._group()["names"] += new
            if self._apps:
                self._group()["extra"] = self._group().get("extra", []) + new
            self._extra += new
            self._load_group(self._group_i)
            scan = model.scan_folder(Path(folder), self._all_people())
            self.log(f"폴더를 다시 읽어 파일 이름에서 출장자 {len(new)}명을 더했습니다")
        self._scan = scan
        self._fill_from_scan(scan, changed)
        fresh = [p for p in self._file_sig(scan) if p not in old]
        if quiet:
            self.log(f"폴더의 파일이 바뀌어 증빙을 다시 맞췄습니다 — 새 파일 {len(fresh)} · 고친 파일 {len(changed)} · 없어진 파일 {len(gone)}")
        self._on_route_inputs()
        return True

    # ── 그림 · 스캔 영수증 AI 읽기 ────────────────────────────────────────
    def _ai_start(self) -> None:
        """꼭 있어야 할 칸이 빈 증빙을 AI 로 읽는다 — 전에 읽은 것(캐시)은 바로 넣고, 남은 것만 뒤 스레드에 맡긴다."""
        wanted: list[tuple[str, str]] = []
        filled = 0
        for kind, table in self.tables.items():
            for path in table.ai_wanted():
                cached = ai_read.lookup(path)
                if cached is not None:
                    filled += table.apply_ai(path, ai_read.summary(kind, cached))
                    continue
                mark = (ai_read.file_key(path), ai_read.signature(path))
                if mark not in self._ai_tried:
                    wanted.append((str(path), kind))
        if filled:
            self.log(f"출장 AI 읽기: 전에 읽은 그림 영수증으로 빈 칸 {filled}개를 채웠습니다")
        if not wanted:
            return
        if not ai_read.available():
            self.ai_note.setText(f"그림 · 스캔 영수증 {len(wanted)}개는 앱이 글자를 못 읽습니다 — 이 PC 에 Claude Code 가 없어 AI 로도 못 읽었습니다. "
                                 "④ 미리 보기에서 빈 칸을 적어 주세요.")
            self.ai_note.show()
            return
        for path, _kind in wanted:
            self._ai_tried.add((ai_read.file_key(path), ai_read.signature(path)))
        if self._ai_worker is None:
            from ..travel_ai_worker import TravelAiWorker
            self._ai_worker = TravelAiWorker()
            self._ai_worker.log.connect(self.log)
            self._ai_worker.started.connect(self._on_ai_started)
            self._ai_worker.done.connect(self._on_ai_done)
            self._ai_worker.finished.connect(self._on_ai_finished)
        if not self._ai_running:
            self._ai_filled = 0
        self._ai_running += 1
        self.ai_note.setText(f"그림 · 스캔 영수증 {len(wanted)}개를 AI(Claude Code)로 읽는 중입니다 — 몇십 초씩 걸립니다. 읽는 대로 빈 칸을 채웁니다.")
        self.ai_note.show()
        self._ai_worker.run(wanted)

    def _on_ai_started(self, number: int, total: int) -> None:
        self.ai_note.setText(f"그림 · 스캔 영수증을 AI(Claude Code)로 읽는 중 — {number}/{total}번째부터(몇십 초씩 걸립니다). 읽는 대로 빈 칸을 채웁니다.")
        self.ai_note.show()

    def _on_ai_done(self, results: dict) -> None:
        for path, data in results.items():
            for kind, table in self.tables.items():
                if Path(path) in table.paths:
                    self._ai_filled += table.apply_ai(Path(path), ai_read.summary(kind, data))

    def _on_ai_finished(self, stopped: str) -> None:
        self._ai_running = max(0, self._ai_running - 1)
        if self._ai_running:
            return
        if not self.folder_edit.text().strip():
            self.ai_note.hide()                 # [새로 시작] · 폴더를 뺀 뒤 끝난 읽기 — 비운 화면에 앞 폴더의 소식을 띄우지 않는다
            return
        if stopped in ("login", "limit", "balance"):
            reason = {"login": "Claude 로그인이 풀려", "limit": "Claude 사용 한도에 걸려", "balance": "Claude 잔액이 모자라"}[stopped]
            self.ai_note.setText(f"{reason} 그림 · 스캔 영수증을 다 읽지 못했습니다 — 위쪽 AI 단추에서 확인한 뒤 ③ [폴더에서 다시 읽기] 를 누르세요. "
                                 "못 읽은 칸은 ④ 미리 보기에서 적어도 됩니다.")
        elif stopped:
            self.ai_note.setText(f"그림 · 스캔 영수증 일부를 AI 로 읽지 못했습니다({stopped}) — ④ 미리 보기에서 빈 칸을 적거나 ③ [폴더에서 다시 읽기].")
        else:
            self.ai_note.setText(f"그림 · 스캔 영수증을 AI(Claude Code)로 읽어 빈 칸 {self._ai_filled}개를 채웠습니다 — ④ 미리 보기에서 맞는지 보세요"
                                 "(칸에 마우스를 올리면 'AI 가 읽은 값').")
        self.ai_note.show()

    def _check_folder(self) -> None:
        """앱으로 돌아오거나 화면을 다시 열면 폴더의 파일이 바뀌었는지 본다(③ 이후만)."""
        if self._stage == "files" and self.isVisible():
            self._rescan(quiet=True)

    def _on_app_state(self, state) -> None:
        if state == Qt.ApplicationActive:
            QTimer.singleShot(150, self._check_folder)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._check_folder)

    def _on_evidence(self) -> None:
        self._on_route_inputs()

    def _on_route_inputs(self) -> None:
        """출장자 · 출발지 · 목적지 · 하이패스가 바뀌면 자차 구간 표를 다시 짠다 — 찾아 둔 구간은(출발 · 목적지가 같으면) 남긴다."""
        if not hasattr(self, "route_table") or self._loading_group:
            return
        self._store_group()
        self.tables[model.STAY].apply_orders()          # 그룹 기간이 바뀌었으면 차례 번호 일자도(아래 _sync 가 미리 보기를 다시 그린다)
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
        self._sync_fuel_rows()
        if self._groups:
            self._fill_group_table()
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
        self.route_box.setVisible(bool(self._routes))          # 차량 연료를 고른 출장자(자차)가 있을 때만
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
        pairs = set()
        for key, route in sorted(self._routes.items()):
            if key in self._searching or not route["origin"] or not route["goal"]:
                continue
            if chosen is None and self._share_route(key):
                continue            # 같은 출발지 → 목적지를 이미 찍은 출장자가 있으면 그것을 쓴다
            if chosen is not None and key != chosen:
                continue
            target = route["goal"] if route["goal"] != self.origin_edit.text().strip() else route["origin"]
            if application.vague_place(target) and not self._goal_of.get(key[0]):
                continue            # 목적지가 분명하지 않으면 먼저 묻는다(_sync_goal_box)
            if chosen is None and route["image"] and route["km"] is not None:
                continue
            if not force and route["status"].startswith("못 찾음"):
                continue
            pair = (route["origin"], route["goal"])
            if chosen is None and pair in pairs:
                continue            # 같은 길은 한 번만 찾는다 — 찾으면 _on_routes 가 나눠 준다
            pairs.add(pair)
            keys.append(key)
        if not keys:
            return
        # 기록에 남는 이름표는 '출장자 N 가는 길'(이름 없음), 지도 그림 파일 이름에는 출장자 이름을 넣는다(폴더에 출장자가 여럿일 때 가리게)
        legs = [(self._routes[k]["origin"], self._routes[k]["goal"], f"{self._who(k[0])} {self._routes[k]['label']}",
                 f"{k[0]} {self._routes[k]['label']}") for k in keys]
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
            if result.pending:
                route["status"] = "확인 기다림 — 네이버 지도 창"
                self._pending_route = key
                continue
            if result.deferred:
                route["status"] = "차례 기다림"
                continue
            if result.ok:
                route["image"] = result.image
                if result.km is not None:
                    route["km"] = result.km
                route["status"] = "찍음(거리우선)" if result.km is not None else (result.note or "그림만 찍음")
                for other in [k for k in self._routes if k != key]:
                    self._share_route(other)
                if key == self._pending_route:
                    self._pending_route = None
                    # 다음 구간(경유지가 있을 때)을 이어 띄운다 — 창이 하나라 한 구간씩
                    if any(not r["image"] or r["km"] is None for k, r in self._routes.items() if k != key):
                        QTimer.singleShot(0, self._find_routes)
            else:
                route["status"] = "못 찾음 — " + (result.note or "까닭 모름")
                if result.need_place:
                    # 목적지가 검색되지 않으면 그 출장자의 출장목적지를 묻는다(담당자 2026-11-10)
                    self._ask_reason[key[0]] = f"네이버 지도에서 '{result.need_place}' 를 찾지 못했습니다"
                    self._goal_of.pop(key[0], None)
                else:
                    failed.append(result.note or "까닭 모름")
        self._fill_route_table()
        self._show_route_notice(found)
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
                                    "\n\n[네이버 지도 창 열기] 로 길찾기에서 출발지 · 목적지를 넣고 길찾기를 누른 뒤, "
                                    "자차 이동경로 표에서 그 줄을 고르고 [이 경로로 찍기 · 거리 넣기] 를 누르세요.\n"
                                    "그 길찾기의 출발지 · 목적지는 앱이 기억해 다음부터는 저절로 찾습니다.")
        self._sync()

    def _show_route_notice(self, found) -> None:
        """확인 기다리는 구간이 있으면 무엇을 하라는지 한 줄 — 네이버 지도 창을 보고 [이 경로로 찍기 · 거리 넣기]."""
        key = self._pending_route if self._pending_route in self._routes else None
        if key is None:
            self.route_notice.hide()
            return
        route = self._routes[key]
        note = next((r.note for k, r in found if k == key and r.pending), "") or navermap.CONFIRM_NOTE
        who = f"{key[0]} · " if key[0] != "출장자" else ""
        self.route_notice.setText(f"{who}{route['label']}: {route['origin'] or '?'} → {route['goal'] or '?'}\n{note}\n"
                                  "앱이 그 화면을 '거리우선' 으로 골라 찍고 km 를 넣습니다 — 오는 길은 같은 거리로 적습니다.")
        self.route_notice.show()

    def _capture_route(self) -> None:
        key = self._pending_route if self._pending_route in self._routes else self._selected_route()
        folder = self.folder_edit.text().strip()
        if key is None or not folder:
            QMessageBox.information(self, "이 경로로 찍기", "자차 이동경로 표에서 넣을 줄(구간)을 먼저 고르세요.")
            return
        self._searching.add(key)
        self._fill_route_table()
        self._worker().capture_route(folder, f"{self._who(key[0])} {self._routes[key]['label']}", key,
                                     shot=f"{key[0]} {self._routes[key]['label']}")

    def _share_route(self, key: tuple) -> bool:
        """출발지 · 목적지가 같은 구간을 다른 출장자가 이미 찍었으면 그 지도 · km 를 이 구간에(신청서가 달라도 같은 곳에 간 사람들).
        이 구간에 지도 · km 가 다 있으면 손대지 않는다. 나눠 받았으면 True."""
        route = self._routes.get(key)
        if route is None or (route["image"] and route["km"] is not None):
            return False
        for other, done in self._routes.items():
            if other[0] != key[0] and done["image"] and done["km"] is not None and \
                    (done["origin"], done["goal"]) == (route["origin"], route["goal"]):
                route["image"], route["km"] = done["image"], done["km"]
                route["status"] = "같은 경로 적용"
                return True
        return False

    def _apply_same_route(self) -> None:
        """자차 이동경로 표에서 지도 · km 가 있는 출장자의 줄과 없는 출장자의 줄을 함께 고르면 같은 경로를 넣는다(담당자 2026-11-16
        "출장신청서가 달라도 목적지가 같은경우 … 경로 및 사진이 있는 출장자와 없는 출장자를 선택하면 경로 및 사진이 똑같이 적용되도록")."""
        rows = sorted({i.row() for i in self.route_table.selectedIndexes()})
        keys = [self._route_keys[r] for r in rows if r < len(self._route_keys)]
        drivers = list(dict.fromkeys(k[0] for k in keys))
        done = lambda n: all(self._routes[k]["image"] and self._routes[k]["km"] is not None  # noqa: E731
                             for k in self._routes if k[0] == n)
        sources = [n for n in drivers if done(n)]
        targets = [n for n in drivers if n not in sources]
        if not sources or not targets:
            QMessageBox.information(self, "같은 경로 적용", "자차 이동경로 표에서 지도 · km 가 있는 출장자의 줄과 없는 출장자의 줄을 함께 고르세요"
                                    "(Ctrl 을 누른 채 누르면 여러 줄).")
            return
        source = sources[0]
        legs = sorted(k for k in self._routes if k[0] == source)
        skipped = []
        for name in targets:
            if len(self._legs_for(name)) == 1 and len(legs) == 1:
                self._goal_of[name] = self._routes[legs[0]]["goal"]      # 목적지 글이 달라도 같은 곳 — 그 사람의 목적지도 맞춘다
                self._ask_reason.pop(name, None)
        self._on_route_inputs()
        for name in targets:
            mine = sorted(k for k in self._routes if k[0] == name)
            if len(mine) != len(legs):
                skipped.append(name)
                continue
            for key, src in zip(mine, legs):
                self._routes[key].update(image=self._routes[src]["image"], km=self._routes[src]["km"], status="같은 경로 적용")
        self.log(f"같은 경로 적용: {self._who(source)} → {', '.join(self._who(n) for n in targets if n not in skipped)}")
        self._fill_route_table()
        self._sync()
        if skipped:
            QMessageBox.information(self, "같은 경로 적용", f"구간 수(경유지)가 달라 넣지 못했습니다: {', '.join(skipped)}")

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
        places = self._all_places()
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
        """출장자 모두의 증빙이 든 출장 하나(고른 그룹의 기간 · 출장지) — 출장자마다 나누는 것은 trips()."""
        return self._group_trip(self._group())

    def _group_trip(self, group: dict | None) -> model.Trip:
        """그룹 하나의 출장 — 그 그룹의 기간 · 출장지와 표의 증빙 모두(사람마다 나누기는 model.for_traveler)."""
        year = self._year()
        region = "" if self.region_box.currentIndex() == 0 else self.region_box.currentText()
        if group is None or group is self._group():
            start, end, dest = self.start_edit.date().toPython(), self.end_edit.date().toPython(), self.dest_edit.text().strip()
        else:
            start, end, dest = group.get("start"), group.get("end"), group.get("dest", "")
        return model.Trip(
            name=", ".join(self._names()),
            start=start, end=end,
            origin=self.origin_edit.text().strip(), destination=dest,
            region=region, lodging_cap=(self.cap_spin.value() or None) if self.cap_spin.isEnabled() else None,
            people=self.people_spin.value(),
            stay=self.tables[model.STAY].evidence(year), public=self.tables[model.PUBLIC].evidence(year),
            tolls=self.tables[model.TOLL].evidence(year), lodging=self.tables[model.LODGING].evidence(year),
            other=self.tables[model.OTHER].evidence(year),
            place_regions=self._place_regions(model.split_places(dest)),
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
        """출장자마다 출장 — 만들 그룹마다 그 그룹의 기간 · 출장지로, 그 사람 증빙 · '공통' 증빙과, 자차면 그 사람 구간의 지도 · km.
        한 사람이 두 그룹에 있거나 그룹이 여럿일 때의 '공통' 증빙은 그 그룹의 기간 안 것만(model.keep_period)."""
        people = self._all_people()
        groups = self._included() if self._groups else [None]
        seen: dict[str, int] = {}
        for group in groups:
            for name in self._group_names(group):
                seen[name] = seen.get(name, 0) + 1
        out = []
        for group in groups:
            base = self._group_trip(group)
            names = self._group_names(group) if group is not None else self._names()
            for name in names or [""]:
                fuel = self._fuel(name or "출장자")
                trip = model.for_traveler(base, name, people, fuel=fuel)
                if len(groups) > 1:
                    model.keep_period(trip, base.start, base.end, shared_only=seen.get(name, 0) <= 1)
                if group is not None and name and name in group.get("extra", ()):
                    # 신청서에 없이 이 그룹에 더한 출장자 — 그 사람의 기간은 신청서가 모르므로 증빙 일자에 맞춘다(사람이 다른 그룹으로 옮겨 기간을 적었으면 그 기간)
                    model.fit_period(trip)
                driver = name or "출장자"
                keys = sorted(k for k in self._routes if k[0] == driver)
                if keys and fuel not in ("", model.NO_CAR):
                    trip.legs = [self._routes[k]["km"] for k in keys]
                    trip.route_maps = [Path(self._routes[k]["image"]) if self._routes[k]["image"] else None for k in keys]
                    stops = self._stops(driver)
                    trip.route_stops = stops if len(stops) > 1 else []
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
        self.reload_button.setVisible(bool(folder))
        self.start_button.setText(label)
        self.folder_list.setToolTip("체크한 폴더를 차례로 합니다 — 두 번 누르면 그 폴더로 바로 갑니다" if many else "")
        start, end = self.start_edit.date().toPython(), self.end_edit.date().toPython()
        who = names[0] + (f" 외 {len(names) - 1}명" if len(names) > 1 else "") if names else "출장자 없음"
        groups = self._included() if self._groups else []
        summary = (f"출장 그룹 {len(groups)}개 · {who}" if len(groups) > 1 else
                   f"{who} · {start:%m-%d}~{end:%m-%d} · {self.dest_edit.text().strip() or '출장지 없음'}")
        self.step_info.set_state(HIDDEN if stage == "folder" else CURRENT if stage == "review" else DONE, summary)
        car_ready = not (self._drivers() or self._undecided()) or (self._route_checked and not self._car_missing())
        empty = [str(i + 1) for i, g in enumerate(self._groups) if g["on"] and not g["names"]]
        self.info_next.setEnabled(bool(names) and car_ready and not empty)
        self.info_next.setToolTip(f"출장자가 없는 출장 그룹({', '.join(empty)}) — 출장자를 적거나 '만들기' 를 끄세요" if empty else
                                  "" if car_ready else "자차 경로 확인 — 출발지 · 경유지 · 목적지와 연료를 확인하고 확인 칸을 켜세요")
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
        problems = model.traveler_problems(base, self._all_people())
        for trip in trips:
            problems += [(f"{trip.name}: " if len(trips) > 1 else "") + p for p in model.problems(trip)
                         if not (len(trips) > 1 and p.startswith("증빙 파일이 하나도"))]
        problems = list(dict.fromkeys(problems))
        ready = [t for t in trips if not model.blocking(t)]
        pages = sum(len(model.pages(t)) for t in ready)
        self.plan_label.setText(f"만들 출장증빙 {len(ready)}개({', '.join(t.name for t in ready) or '없음'}) · 쪽 {pages}개"
                                "(증빙 PDF 가 여러 쪽이면 더 늘 수 있음)")
        self.problem_label.setText("\n".join(f"· {p}" for p in problems[:14]) + (f"\n· … 외 {len(problems) - 14}개" if len(problems) > 14 else ""))
        self.make_button.setText(f"출장증빙 내보내기 ({len(ready)}명 · PDF {len(ready)}개)" if len(ready) > 1 else "출장증빙 내보내기")
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
        """출장자별 증빙 확인 표 — 사람마다 항목별 개수 한 칸(합친 칸)과 확인할 것을 증빙마다 한 줄(model.checks).
        누구 것인지 모르는 증빙은 맨 아래 '확인 필요' 줄로."""
        table = self.people_table
        table.clearSpans()
        table.setRowCount(0)
        drivers = set(self._drivers())
        twice = {t.name for t in trips if sum(1 for o in trips if o.name == t.name) > 1}
        for index, trip in enumerate(trips):
            nights = sum(e.nights for e in trip.lodging)
            route = "—"
            if trip.name in drivers or (len(trips) == 1 and drivers):
                kms = [v for v in trip.legs if v]
                route = f"{len([m for m in trip.route_maps if m])}장 · {model.km(sum(kms))}" if kms else "아직"
            label = (trip.name or "(이름 없음)") + (f" ({trip.start:%m-%d})" if trip.name in twice and trip.start else "")
            heads = [label, f"{len(trip.stay)}개", f"{len(trip.public)}개", f"{len(trip.tolls)}개",
                     f"{nights}박" if trip.lodging else "—", f"{len(trip.other)}개" if trip.other else "—", route]
            items = model.checks(trip, self._root()) or [((), "", "확인할 것 없음")]
            first = table.rowCount()
            for ref, where, text in items:
                row = table.rowCount()
                table.insertRow(row)
                for col, cell in ((len(heads), where), (len(heads) + 1, text)):
                    item = QTableWidgetItem(cell)
                    item.setToolTip(cell)
                    item.setData(REF_ROLE, (index, ref))
                    if ref or where:
                        item.setForeground(QColor(COLORS["warning"]) if col == len(heads) + 1 else QColor(COLORS["text"]))
                    table.setItem(row, col, item)
            root = self._root()
            files = {1: trip.stay, 2: trip.public, 3: trip.tolls, 4: trip.lodging, 5: trip.other}
            for col, text in enumerate(heads):
                item = QTableWidgetItem(text)
                listed = files.get(col) or []
                # 어떤 파일을 읽었는지 — 담당자 2026-11-16 "폴더에 체류증빙이 1,2 각각 하나씩 밖에 없는데 계속 2개로 나오네요"
                item.setToolTip("\n".join(dict.fromkeys(model.shown_name(e.path, root) for e in listed)) if listed else text)
                item.setData(REF_ROLE, (index, ()))
                table.setItem(first, col, item)
                if len(items) > 1:
                    table.setSpan(first, col, len(items), 1)
        loose = model.traveler_problems(self.base_trip(), self._all_people())
        for text in loose:
            row = table.rowCount()
            table.insertRow(row)
            for col, cell in ((0, "확인 필요"), (PEOPLE_SPAN, "누구 것인지"), (PEOPLE_SPAN + 1, text + " — 파일 이름 맨 앞에 출장자 이름을 붙이고 [폴더에서 다시 읽기]")):
                item = QTableWidgetItem(cell)
                item.setToolTip(cell)
                item.setForeground(QColor(COLORS["warning"]))
                table.setItem(row, col, item)
            table.setSpan(row, 0, 1, PEOPLE_SPAN)
        table.resizeRowsToContents()
        rows = sum(table.rowHeight(r) for r in range(table.rowCount()))
        table.want = min(max(140, table.horizontalHeader().height() + rows + 6), 520)
        table.setFixedHeight(table.want)

    def _on_people_row(self, row: int, col: int) -> None:
        """표의 줄을 두 번 누르면 ④ 미리 보기에서 그 출장자 · 그 증빙을 연다."""
        item = self.people_table.item(row, col) or self.people_table.item(row, PEOPLE_SPAN + 1)
        data = item.data(REF_ROLE) if item is not None else None
        if not data:
            return
        index, ref = data
        self.preview_panel.show_trip(index, ref)
        self.area.ensureWidgetVisible(self.step_preview, 0, 40)

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

    # ── ⑤ 만들기 ────────────────────────────────────────────────────────
    def _make(self, confirmed: bool = False) -> None:
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self, "출장증빙 만들기", f"저장할 폴더가 없습니다:\n{folder}")
            return
        if self._rescan(quiet=True) and confirmed:
            confirmed = False                     # 확인한 뒤 폴더의 파일이 바뀌었다 — 바뀐 것으로 다시 보게
        trips = [t for t in self.trips() if not model.blocking(t)]
        problems = model.traveler_problems(self.base_trip(), self._all_people())
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
            out = model.output_path(folder, trip.name, trip.start, trip.end)
            try:
                count = render.render(model.pages(trip), out)
            except Exception as exc:  # 그림 파일 · 폴더 권한 등
                lines.append(f"✗ {trip.name}: 만들지 못했습니다 — {exc}")
                continue
            made.append(out)
            support = sum(model.lodging_support(e, trip.cap(e), trip.people)[0] for e in trip.lodging)
            lines.append(f"✓ {out.name} — {count}쪽" + (f" · 숙박 지원금액 {model.won(support)}" if trip.lodging else ""))
            # 파일 이름(<이름> 출장증빙_…)은 화면에만 — 기록에는 출장자 차례 · 출장 시작일 · 쪽 수(28절 '기록에는 이름을 남기지 않는다')
            day = model.date_stamp(trip.start, trip.end) or "날짜 없음"
            self.log(f"출장증빙 만듦: {self._who(trip.name)} · {day} — {count}쪽")
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
