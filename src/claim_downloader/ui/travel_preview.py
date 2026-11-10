"""출장증빙 미리 보기 — 만들 PDF 와 똑같이 짠 쪽을 앱 안에서 보이고, 확인이 필요한 증빙을 칠해 눌러서 바로 고친다.

담당자 2026-11-10 "확인필요한 건은 어플내에서 증빙양식 미리보기 처럼 나오는데 확인이 필요한 부분을 직접 편집할 수 있게 설정".
쪽 그림 · 누를 자리는 travel/render.preview(PDF 와 같은 짜임 — render 와 한 코드), 확인할 칸은 travel/model.unclear · route_unclear.
고친 값은 출장증빙 화면(ui/pages/travel.py)의 증빙 표 · 이동경로 표에 적고(그쪽이 원본) 미리 보기를 다시 그린다.
칠하지 않은 증빙도 눌러 고칠 수 있다. [이대로 만들기] 는 확인할 것이 남아 있어도 만든다(사람이 보고 누른 것).
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..travel import fuels, model
from .tokens import COLORS
from .travel_fuel_card import fuel_box
from .widgets import Pill, WrapLabel

MAKE = 2                 # 대화창 결과 — [이대로 만들기]
PAGE_GAP = 14
SIDE_WIDTH = 360
MODE_NAMES = tuple(name for name, _ in model.MODES)


def _flag_style() -> str:
    return f"background: {COLORS['warning_bg']}; border: 1px solid {COLORS['warning']};"


class PageView(QWidget):
    """쪽 그림 한 장 — 누를 자리(Hit)를 겹쳐 그리고, 확인할 증빙은 칠하고 '확인 필요' 꼬리표를 단다."""

    clicked = Signal(object)

    def __init__(self, image: QImage, hits: list, flagged: dict, page_size, parent: QWidget | None = None):
        super().__init__(parent)
        self.image = image
        self.hits = hits
        self.flagged = flagged            # ref → 확인할 칸 이름들
        self.page_size = page_size
        self.selected: tuple = ()
        self.setMouseTracking(True)

    def set_width(self, width: int) -> None:
        self.setFixedSize(width, int(width * self.image.height() / max(1, self.image.width())))

    def _rect(self, hit) -> QRectF:
        s = self.width() / self.page_size.width()
        r = hit.rect
        return QRectF(r.x() * s, r.y() * s, r.width() * s, r.height() * s)

    def hit_at(self, pos):
        found = [h for h in self.hits if self._rect(h).contains(pos)]
        order = {"cell": 0, "bar": 1, "head": 2}
        found.sort(key=lambda h: (order.get(h.where, 3), h.rect.width() * h.rect.height()))
        return found[0] if found else None

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(self.rect(), self.image)
        warn = QColor(COLORS["warning"])
        fill = QColor(warn)
        fill.setAlpha(38)
        font = QFont(self.font())
        font.setPixelSize(12)
        font.setBold(True)
        p.setFont(font)
        tagged = set()
        for hit in self.hits:
            rect = self._rect(hit).adjusted(1, 1, -1, -1)
            fields = self.flagged.get(hit.ref)
            if fields:
                p.fillRect(rect, fill)
                p.setPen(QPen(warn, 2.5))
                p.drawRect(rect)
                key = (hit.ref, hit.where)
                if key not in tagged:
                    tagged.add(key)
                    text = "확인 필요 · " + " · ".join(fields)
                    width = min(rect.width(), p.fontMetrics().horizontalAdvance(text) + 14)
                    tag = QRectF(rect.left(), rect.top(), width, 20)
                    p.fillRect(tag, QColor(COLORS["warning_bg"]))
                    p.setPen(warn)
                    p.drawText(tag.adjusted(6, 0, -4, 0), Qt.AlignVCenter | Qt.AlignLeft,
                               p.fontMetrics().elidedText(text, Qt.ElideRight, int(width - 10)))
            if self.selected and hit.ref == self.selected:
                p.setPen(QPen(QColor(COLORS["primary"]), 3.5))
                p.drawRect(rect.adjusted(-2, -2, 2, 2))
        p.end()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self.setCursor(Qt.PointingHandCursor if self.hit_at(event.position()) else Qt.ArrowCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        hit = self.hit_at(event.position())
        if hit is not None and event.button() == Qt.LeftButton:
            self.clicked.emit(hit)


class TravelPreview(QDialog):
    """source 는 출장증빙 화면(TravelPage) — trips() · year() · apply_edit(ref, 값) · route_rows(사람) · apply_route(사람, km, 연료) · fuel_of(사람)."""

    def __init__(self, parent: QWidget | None, source, name: str = "", make_text: str = "이대로 만들기"):
        super().__init__(parent)
        self.setWindowTitle("출장증빙 미리 보기")
        self.setSizeGripEnabled(True)
        self.source = source
        self._cache: dict = {}            # 증빙 파일 → 쪽 그림(고칠 때마다 다시 읽지 않게)
        self._needs: dict = {}
        self._views: list[PageView] = []
        self._hits: list = []
        self._flagged: dict = {}
        self._selected: tuple = ()
        self._editor_fields: dict = {}
        self._trip: model.Trip | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(Pill("미리 보기", "info"), 0, Qt.AlignVCenter)
        title = QLabel("출장증빙 미리 보기 — 칠한 곳을 눌러 바로 고치세요")
        title.setObjectName("cardTitle")
        head.addWidget(title, 1)
        self.person_box = QComboBox()
        self.person_box.currentIndexChanged.connect(lambda _i: self.refresh(keep=False))
        head.addWidget(self.person_box)
        layout.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(14)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        holder = QWidget()
        holder.setObjectName("previewPages")
        self.pages_layout = QVBoxLayout(holder)
        self.pages_layout.setContentsMargins(0, 0, 0, 0)
        self.pages_layout.setSpacing(PAGE_GAP)
        self.scroll.setWidget(holder)
        body.addWidget(self.scroll, 1)

        side = QWidget()
        side.setFixedWidth(SIDE_WIDTH)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)
        self.todo_label = QLabel("")
        self.todo_label.setObjectName("cardTitle")
        side_layout.addWidget(self.todo_label)
        self.todo_list = QListWidget()
        self.todo_list.setWordWrap(True)
        self.todo_list.itemClicked.connect(lambda item: self._select(item.data(Qt.UserRole)))
        side_layout.addWidget(self.todo_list)
        self.notes_label = WrapLabel("")
        self.notes_label.setObjectName("muted")
        side_layout.addWidget(self.notes_label)
        self.editor = QFrame()
        self.editor.setObjectName("card")
        self.editor_layout = QVBoxLayout(self.editor)
        self.editor_layout.setContentsMargins(14, 12, 14, 12)
        self.editor_layout.setSpacing(8)
        side_layout.addWidget(self.editor)
        side_layout.addStretch(1)
        body.addWidget(side)
        layout.addLayout(body, 1)

        foot = QHBoxLayout()
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        foot.addWidget(self.status_label, 1)
        self.make_button = QPushButton(make_text)
        self.make_button.setObjectName("primary")
        self.make_button.setAutoDefault(False)
        self.make_button.clicked.connect(lambda: self.done(MAKE))
        self.make_button.setVisible(bool(make_text))
        close = QPushButton("닫기")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        foot.addWidget(self.make_button)
        foot.addWidget(close)
        layout.addLayout(foot)

        trips = source.trips()
        self.person_box.blockSignals(True)
        for trip in trips:
            self.person_box.addItem(trip.name or "출장자")
        index = next((i for i, t in enumerate(trips) if t.name == name), 0)
        self.person_box.setCurrentIndex(index)
        self.person_box.blockSignals(False)
        self.person_box.setVisible(len(trips) > 1)
        self._fit_to_screen()
        self.refresh(keep=False)

    # ── 크기 ────────────────────────────────────────────────────────────
    def _fit_to_screen(self) -> None:
        screen = self.screen() or (self.parent().screen() if self.parent() is not None else None)
        area = screen.availableGeometry() if screen is not None else None
        width = min(1280, int(area.width() * 0.92)) if area else 1180
        height = min(980, int(area.height() * 0.88)) if area else 820
        self.resize(width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, self._fit_pages)          # 자식들의 자리가 정해진 뒤에

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._after_show)

    def _after_show(self) -> None:
        self._fit_pages()
        if self._selected:
            self._scroll_to(self._selected)

    def _fit_pages(self) -> None:
        width = max(320, self.scroll.viewport().width() - 6)
        for view in self._views:
            view.set_width(width)
        if self.scroll.widget() is not None and self.scroll.widget().layout() is not None:
            self.scroll.widget().layout().activate()

    def _scroll_to(self, ref: tuple) -> None:
        """그 증빙이 있는 자리로 — 쪽들의 자리가 정해진 뒤에 셈한다."""
        def go() -> None:
            self._fit_pages()
            hit = next((h for h in sorted(self._hits, key=lambda h: (h.page, h.rect.top())) if h.ref == ref), None)
            if hit is not None and hit.page < len(self._views):
                view = self._views[hit.page]
                self.scroll.verticalScrollBar().setValue(max(0, view.y() + int(view._rect(hit).top()) - 40))
        QTimer.singleShot(0, go)

    # ── 그리기 ──────────────────────────────────────────────────────────
    def trip(self) -> model.Trip | None:
        trips = self.source.trips()
        if not trips:
            return None
        return trips[max(0, min(self.person_box.currentIndex(), len(trips) - 1))]

    def refresh(self, keep: bool = True) -> None:
        """출장증빙 화면의 지금 값으로 쪽을 다시 짜 그린다 — keep 이면 보던 자리 · 고른 증빙을 그대로."""
        from ..travel import render
        position = self.scroll.verticalScrollBar().value() if keep else 0
        trip = self.trip()
        self._trip = trip
        for view in self._views:
            view.deleteLater()
        self._views = []
        while self.pages_layout.count():
            item = self.pages_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if trip is None:
            return
        self._flagged = {e.ref: model.unclear(trip, kind, e) for kind, e in model.evidence_of(trip) if e.ref}
        self._flagged[model.route_key(trip)] = model.route_unclear(trip)
        self._flagged = {ref: fields for ref, fields in self._flagged.items() if fields}
        pages = model.pages(trip)
        images, hits = render.preview(pages, cache=self._cache, needs=self._needs) if pages else ([], [])
        self._hits = hits
        for i, image in enumerate(images):
            label = QLabel(f"{i + 1}쪽")
            label.setObjectName("muted")
            self.pages_layout.addWidget(label)
            view = PageView(image, [h for h in hits if h.page == i], self._flagged, render.PAGE_SIZE)
            view.selected = self._selected
            view.clicked.connect(lambda hit: self._select(hit.ref, scroll=False))
            self.pages_layout.addWidget(view)
            self._views.append(view)
        if not images:
            empty = QLabel("만들 쪽이 없습니다 — 증빙을 넣어 주세요.")
            empty.setObjectName("muted")
            self.pages_layout.addWidget(empty)
        self.pages_layout.addStretch(1)
        self._fit_pages()
        self._fill_todo(trip)
        if keep:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(position))
        if not (keep and self._selected and self._select(self._selected, scroll=False)):
            first = self._first_flagged()
            if first and not self._selected:
                self._select(first, scroll=True)
            elif not self._selected:
                self._show_editor_hint()

    def _first_flagged(self) -> tuple:
        for hit in sorted(self._hits, key=lambda h: (h.page, h.rect.top(), h.rect.left())):
            if hit.ref in self._flagged:
                return hit.ref
        return ()

    def _page_of(self, ref: tuple) -> int | None:
        pages = [h.page for h in self._hits if h.ref == ref]
        return min(pages) if pages else None

    def _fill_todo(self, trip: model.Trip) -> None:
        self.todo_list.clear()
        count = 0
        for ref, fields in sorted(self._flagged.items(), key=lambda kv: (self._page_of(kv[0]) or 0)):
            page = self._page_of(ref)
            where = f"{page + 1}쪽 · " if page is not None else ""
            if ref and ref[0] == "route":
                text = f"{where}자차 이동경로 — {' · '.join(fields)}"
            else:
                ev = self._evidence(ref)
                text = f"{where}{model.KIND_NAMES.get(ref[0], '')} · {ev.path.name if ev else ''} — {' · '.join(fields)}"
            item = QListWidgetItem(text)
            item.setToolTip(text)
            item.setData(Qt.UserRole, ref)
            self.todo_list.addItem(item)
            count += 1
        self.todo_label.setText(f"확인할 것 {count}건" if count else "확인할 것 없음")
        self.todo_list.setVisible(bool(count))
        if count:
            line = self.todo_list.fontMetrics().lineSpacing()
            self.todo_list.setFixedHeight(min(4, count) * (2 * line + 8) + 6)       # 한 건이 두 줄로 접혀도 넷까지 보이게
        notes = [r for r in model.review(trip) if not r.startswith(("대중교통 증빙", "하이패스가 있어 자차")) and "출장기간 밖" not in r]
        self.notes_label.setText("\n".join(f"· {n}" for n in notes))
        self.notes_label.setVisible(bool(notes))
        self.status_label.setText(f"쪽 {len(self._views)}개 · 확인할 것 {count}건 남음" if count else f"쪽 {len(self._views)}개 · 확인할 것 없음")

    # ── 고르기 · 고치기 ─────────────────────────────────────────────────
    def _evidence(self, ref: tuple) -> model.Evidence | None:
        if self._trip is None:
            return None
        return next((e for _, e in model.evidence_of(self._trip) if e.ref == ref), None)

    def _select(self, ref: tuple, scroll: bool = True) -> bool:
        if not ref:
            return False
        is_route = ref[0] == "route"
        if not is_route and self._evidence(ref) is None:
            self._selected = ()
            self._show_editor_hint()
            return False
        self._selected = ref
        for view in self._views:
            view.selected = ref
            view.update()
        if scroll:
            self._scroll_to(ref)
        self._build_editor(ref)
        return True

    def _clear_editor(self) -> None:
        self._editor_fields = {}
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
            elif item.layout() is not None:
                _drop_layout(item.layout())

    def _show_editor_hint(self) -> None:
        self._clear_editor()
        hint = WrapLabel("쪽에서 증빙을 누르면 여기서 일자 · 금액 · 출발지 · 목적지 같은 값을 고칠 수 있습니다.")
        hint.setObjectName("muted")
        self.editor_layout.addWidget(hint)

    def _build_editor(self, ref: tuple) -> None:
        self._clear_editor()
        flagged = self._flagged.get(ref, [])
        if ref[0] == "route":
            self._build_route_editor(ref, flagged)
            return
        ev = self._evidence(ref)
        kind = ref[0]
        title = QLabel(f"{model.KIND_NAMES.get(kind, '')} 증빙")
        title.setObjectName("cardTitle")
        self.editor_layout.addWidget(title)
        name = WrapLabel(ev.path.name + (f" ({ev.part + 1}번째 영수증)" if ev.part is not None else ""))
        name.setObjectName("muted")
        self.editor_layout.addWidget(name)
        form = QFormLayout()
        form.setSpacing(6)
        trip = self._trip

        def line(key: str, label: str, value: str, placeholder: str = "", flags: tuple = ()) -> None:
            edit = QLineEdit(value)
            edit.setPlaceholderText(placeholder or "확인 필요")
            if any(f in flagged for f in flags or (label,)):
                edit.setStyleSheet(_flag_style())
            edit.returnPressed.connect(self._apply)
            form.addRow(label, edit)
            self._editor_fields[key] = edit

        line("day", "입실일" if kind == model.LODGING else "일자", ev.day.isoformat() if ev.day else "", "예: 2026-11-10",
             ("일자", "일자(출장기간 밖)"))
        if kind == model.OTHER:
            line("label", "내용", ev.label, "예: 참가확인서", ("내용",))
        elif kind != model.STAY:
            line("amount", "금액(원)", f"{ev.amount:,}" if ev.amount is not None else "", "예: 8,400", ("금액",))
        if kind == model.PUBLIC:
            mode = QComboBox()
            mode.setEditable(True)
            mode.addItems(("",) + MODE_NAMES)
            mode.setCurrentText(ev.mode)
            if "이동편" in flagged:
                mode.setStyleSheet(_flag_style())
            form.addRow("이동편", mode)
            self._editor_fields["mode"] = mode
            line("origin", "출발지", ev.origin, "예: 춘천", ("출발지",))
            line("goal", "목적지", ev.goal, "예: 서울", ("목적지",))
        if kind == model.LODGING:
            nights = QSpinBox()
            nights.setRange(1, 60)
            nights.setSuffix(" 박")
            nights.setValue(max(1, ev.nights))
            form.addRow("박 수", nights)
            self._editor_fields["nights"] = nights
        if kind in (model.STAY, model.LODGING) and trip is not None and len(trip.places) > 1:
            place = QComboBox()
            place.addItems([""] + trip.places)
            place.setCurrentText(trip.place_of(ev) or ev.place)
            if "출장지" in flagged:
                place.setStyleSheet(_flag_style())
            form.addRow("출장지", place)
            self._editor_fields["place"] = place
        self.editor_layout.addLayout(form)
        self._editor_buttons(ev.path)

    def _build_route_editor(self, ref: tuple, flagged: list[str]) -> None:
        driver = ref[1]
        title = QLabel("자차 이동경로 · 연료")
        title.setObjectName("cardTitle")
        self.editor_layout.addWidget(title)
        form = QFormLayout()
        form.setSpacing(6)
        rows = self.source.route_rows(driver)
        kms = {}
        for key, label, way, km in rows:
            edit = QLineEdit(f"{km:g}" if km is not None else "")
            edit.setPlaceholderText("km — 확인 필요")
            edit.setToolTip(way)
            if km is None and "km" in flagged:
                edit.setStyleSheet(_flag_style())
            edit.returnPressed.connect(self._apply)
            form.addRow(f"{label} (km)", edit)
            kms[key] = edit
        self._editor_fields["kms"] = kms
        fuel = fuel_box(fuels.options()[0], self.source.fuel_of(driver))
        if "연료" in flagged:
            fuel.setStyleSheet(_flag_style())
        form.addRow("차량 연료", fuel)
        self._editor_fields["fuel"] = fuel
        self.editor_layout.addLayout(form)
        if not rows:
            note = WrapLabel("이동경로 구간이 아직 없습니다 — 출장증빙 화면 ② 에서 자차 경로(출발지 · 목적지)를 확인하면 생깁니다.")
            note.setObjectName("muted")
            self.editor_layout.addWidget(note)
        if "지도 그림" in flagged:
            note = WrapLabel("네이버 지도 최단거리 그림이 없습니다 — 출장증빙 화면 ③ 의 이동경로에서 [최단거리 다시 찾기] 나 [지도 그림 고르기].")
            note.setObjectName("muted")
            self.editor_layout.addWidget(note)
        self._editor_buttons(None)

    def _editor_buttons(self, path) -> None:
        row = QHBoxLayout()
        apply = QPushButton("고치기")
        apply.setObjectName("primary")
        apply.setAutoDefault(False)
        apply.clicked.connect(self._apply)
        row.addWidget(apply)
        if path is not None:
            original = QPushButton("원본 열기")
            original.setObjectName("ghost")
            original.setAutoDefault(False)
            original.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
            row.addWidget(original)
        row.addStretch(1)
        self.editor_layout.addLayout(row)

    def values(self) -> dict:
        """지금 고치는 칸의 값 — 시험에서도 쓴다."""
        out = {}
        for key, widget in self._editor_fields.items():
            if key == "kms":
                out[key] = {k: _km(edit.text()) for k, edit in widget.items()}
            elif isinstance(widget, QLineEdit):
                out[key] = widget.text().strip()
            elif isinstance(widget, QSpinBox):
                out[key] = widget.value()
            elif isinstance(widget, QComboBox):
                out[key] = (widget.currentData() or "") if key == "fuel" else widget.currentText().strip()
        return out

    def _apply(self) -> None:
        if not self._selected:
            return
        values = self.values()
        if self._selected[0] == "route":
            self.source.apply_route(self._selected[1], values.get("kms", {}), values.get("fuel", ""))
        else:
            self.source.apply_edit(self._selected, values)
        self.refresh(keep=True)
        # 고친 증빙이 더는 확인할 것이 아니면 다음 확인할 것으로
        if self._selected not in self._flagged:
            nxt = self._first_flagged()
            if nxt:
                self._select(nxt, scroll=True)


def _km(text: str) -> float | None:
    cleaned = "".join(ch for ch in (text or "") if ch.isdigit() or ch == ".")
    try:
        return float(cleaned) if cleaned else None
    except ValueError:
        return None


def _drop_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().deleteLater()
        elif item.layout() is not None:
            _drop_layout(item.layout())

