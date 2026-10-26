"""단계 흐름 — 업무 화면을 '할 차례인 것만 보이게' 쌓는 틀. 담당자 요청 2026-10-21.

담당자: "업무카드를 열면 모든 기능들이 다 펼쳐져 있어 어디부터 클릭해야 하는지 헷갈림. 클릭해야 하는 순서대로 버튼 및 기능이 하나 둘
떠올라서 순서대로 선택하게" · "모든 업무카드 — 사용자 입장 및 진행순서 생각해서 구조 다시 배치".

- 단계는 위에서 아래로 쌓인다. 아직 차례가 아닌 단계는 **보이지 않는다**('hidden') — 앞 단계를 마치면 그 아래에 떠오른다(옅게 나타남).
- 지금 할 단계는 라벤더 테두리('current'), 마친 단계는 **작은 네모로 줄어 한 줄에 나란히** 놓인다('done' — 번호 · 제목 · 고른 값 · [바꾸기],
  담당자 2026-10-26 "이전에 진행 완료된 단계들을 굳이 저렇게 가로줄을 다 차지않고 네모박스로 줄여서 컴팩하게 … 같은 행에") — [바꾸기] 를 누르면 다시 펼친다(edit 신호).
  줄 폭이 모자라면 다음 줄로 넘어간다(`_StepsLayout`). 전에는 마친 단계마다 폭을 다 쓰는 한 줄이라 지금 단계가 아래로 밀렸다.
- 표처럼 계속 봐야 하는 단계는 펼친 채 둔다('open' — 테두리만 보통).
상태는 화면이 정한다 — 이 틀은 모양만 맡는다(어느 단계가 끝났는지는 업무마다 다르다).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from .art import Art
from .flowlogic import CURRENT, DONE, HIDDEN, OPEN, flow_states  # noqa: F401 — 화면이 여기서 함께 가져다 쓴다
from .widgets import ElideLabel, Pill, WrapLabel, fit_to_text, muted_label


class FlowStep(QFrame):
    """단계 하나 — 번호 · 제목 · (접혔을 때) 고른 값 한 줄 · [바꾸기] / (펼쳤을 때) 안내 한 줄 · 내용."""

    edit = Signal()

    def __init__(self, number: str, title: str, hint: str = "", editable: bool = True, edit_text: str = "바꾸기",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("card")
        self.state = HIDDEN
        self._editable = editable
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 14, 18, 14)
        self._outer = outer
        outer.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(10)
        # 번호 · 제목 · 상태 배지는 글자만큼만 — 제목 줄의 남는 폭은 아래 spacer(또는 고른 값 줄)가 받는다
        self.number = fit_to_text(QLabel(number))
        self.number.setObjectName("stepNo")
        self.number.setAlignment(Qt.AlignCenter)
        head.addWidget(self.number, 0, Qt.AlignVCenter)
        self.title = fit_to_text(QLabel(title))
        self.title.setObjectName("cardTitle")
        head.addWidget(self.title, 0, Qt.AlignVCenter)
        self.summary = ElideLabel("")
        self.summary.setObjectName("muted")
        head.addWidget(self.summary, 1, Qt.AlignVCenter)
        self.spacer = QWidget()               # 펼쳤을 때(고른 값 줄이 없을 때) 오른쪽 것들을 끝으로 민다
        self.spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        head.addWidget(self.spacer, 1)
        self.side = QHBoxLayout()            # 펼쳤을 때 제목 줄 오른쪽에 얹는 것(상태 배지 등)
        self.side.setSpacing(8)
        head.addLayout(self.side)
        self.edit_button = QPushButton(edit_text)
        self.edit_button.setObjectName("ghost")
        self.edit_button.clicked.connect(self.edit.emit)
        head.addWidget(self.edit_button, 0, Qt.AlignVCenter)
        outer.addLayout(head)
        self.hint = WrapLabel(hint)
        self.hint.setObjectName("muted")
        self.hint.setVisible(bool(hint))
        outer.addWidget(self.hint)
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(10)
        outer.addWidget(self.body, 1)
        # 지금 무엇이 일어나는지 · 다음에 무엇을 하면 되는지 한 줄(화면의 _set_state 가 지금 단계에 쓴다)
        self.note = WrapLabel("")
        self.note.setObjectName("body")
        self.note.hide()
        outer.addWidget(self.note)
        self._anim = None
        self.hide()
        self._apply()

    # ── 내용 ─────────────────────────────────────────────────────────
    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_layout(self, layout, stretch: int = 0) -> None:
        self.body_layout.addLayout(layout, stretch)

    def add_side(self, widget: QWidget) -> None:
        self.side.addWidget(widget, 0, Qt.AlignVCenter)

    def set_hint(self, text: str) -> None:
        self.hint.setText(text)
        self.hint.setVisible(bool(text) and self.state != DONE)

    def set_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text) and self.state != DONE)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)
        self.summary.setToolTip(text)

    # ── 상태 ─────────────────────────────────────────────────────────
    def set_state(self, state: str, summary: str | None = None) -> None:
        if summary is not None:
            self.set_summary(summary)
        appearing = self.state == HIDDEN and state != HIDDEN
        self.state = state
        self._apply()
        if state == HIDDEN:
            self.hide()
        else:
            self.show()
            if appearing:
                self._fade_in()

    def _apply(self) -> None:
        done = self.state == DONE
        # 접힌 단계는 작은 네모(한 줄)라 여백을 줄인다 — 아래 단계(표 · 칸)에 자리를 주고 한 줄에 여럿이 놓이게
        self._outer.setContentsMargins(12 if done else 18, 6 if done else 14, 12 if done else 18, 6 if done else 14)
        self.setObjectName({CURRENT: "cardCurrent", DONE: "cardDone"}.get(self.state, "card"))
        self.number.setObjectName("stepNoDone" if done else "stepNo")
        self.summary.setVisible(done)
        self.spacer.setVisible(not done)
        self.edit_button.setVisible(done and self._editable)
        self.hint.setVisible(bool(self.hint.text()) and not done)
        self.body.setVisible(not done)
        self.note.setVisible(bool(self.note.text()) and not done)
        for i in range(self.side.count()):
            widget = self.side.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(not done)
        for widget in (self, self.number):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.number.updateGeometry()
        self.updateGeometry()             # 접히거나 펼쳐지면 단계 레이아웃(_StepsLayout)이 줄을 다시 짠다

    def _fade_in(self) -> None:
        """앞 단계를 마치면 다음 단계가 옅게 떠오른다(0.22초). 끝나면 효과를 떼어 표 · 입력 칸 그리기에 끼어들지 않게 한다."""
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        self._anim = anim
        anim.start()



class ChoiceCard(QFrame):
    """단계 ① 의 '무엇을' 고르는 카드 — 그림 · 이름 · 한 줄 설명(· 상태 배지). 누르거나 Space/Enter 로 고른다.
    고르면 그 단계가 접히고 다음 단계가 떠오른다 — [다음] 을 따로 누르지 않는다(한 번 더 누를 일을 줄인다)."""

    chosen = Signal(str)

    def __init__(self, key: str, name: str, description: str, art: str, pill: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("card")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(name)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)
        row.addWidget(Art(art, 46), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(name)
        title.setObjectName("cardTitle")
        texts.addWidget(title)
        desc = muted_label(description)
        desc.setWordWrap(True)
        texts.addWidget(desc)
        row.addLayout(texts, 1)
        self.state = Pill("", "neutral") if pill else None
        if self.state is not None:
            row.addWidget(self.state, 0, Qt.AlignVCenter)

    def set_selected(self, on: bool) -> None:
        self.setObjectName("cardCurrent" if on else "card")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.isEnabled():
            self.chosen.emit(self.key)
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter) and self.isEnabled():
            self.chosen.emit(self.key)
            return
        super().keyPressEvent(event)


# 마친 단계(네모)의 고른 값 칸 — 줄 폭이 모자랄 때 이만큼은 남기고(글자가 더 길면) 나머지는 '…' 으로 줄인다
CHIP_SUMMARY_LEAST = 80


class _StepsLayout(QLayout):
    """단계를 쌓는 레이아웃 — 마친 단계(DONE 인 FlowStep)가 연달아 있으면 **작은 네모로 줄여 한 줄에 나란히**, 그 밖(지금 단계 · 펼친 단계 ·
    기록 · 채움)은 폭을 다 쓰는 줄. 담당자 2026-10-26 "이전에 진행 완료된 단계들을 굳이 저렇게 가로줄을 다 차지않고 네모박스로 줄여서 컴팩하게 ·
    같은 행에" — 전에는 QVBoxLayout 이라 마친 단계도 한 줄씩 폭을 다 써 지금 단계(표)가 아래로 밀렸다.

    네모의 폭은 번호 · 제목 · [바꾸기] 에 고른 값 글자만큼(`want`) — 한 줄에 다 안 들어가면 글자가 긴 네모부터 줄여(`least` 까지, 요약은 '…')
    맞추고, 그래도 안 되면 다음 줄로 넘긴다. 높이는 QVBoxLayout 처럼 — 줄마다 바라는 높이를 주고 남는 높이는 stretch 를 준 줄(표 · 기록 · 채움)이
    나눠 받으며, 모자라면 바라는 높이와 최소 높이 사이에서 줄인다.

    높이를 폭에 맞춰 셈하지 않는다고 알린다(`hasHeightForWidth` False) — 줄바꿈 글자(WrapLabel)가 들어 있으면 스크롤 칸이 '그 폭에서 바라는 높이'
    (표 · 칸의 넉넉한 높이)로 안을 키워, 자리가 남는데도 ③ 이 화면 아래로 밀려 스크롤해야 보였다(일반청구, 2026-10-21). 최소 높이만 지키고 남는
    높이는 stretch 를 준 단계(표)가 받는다 — 최소 높이도 안 들어갈 때만 스크롤된다. 네모 줄의 줄바꿈 수만은 마지막으로 자리를 잡은 폭으로 센다."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._items: list[tuple[QWidgetItem, int]] = []     # (항목, stretch)
        self._width = 0                                      # 마지막으로 자리를 잡은 폭 — 네모 줄의 줄바꿈을 셈할 때
        self._shape: tuple = ()                              # 마지막 네모 줄 모양(줄 수) — 바뀌면 바깥(스크롤 칸)에 최소 높이를 다시 알린다

    # ── QLayout 규약 ──────────────────────────────────────────────────
    def addItem(self, item) -> None:  # noqa: N802
        self._items.append((item, 0))

    def addWidget(self, widget: QWidget, stretch: int = 0) -> None:  # noqa: N802
        self.insertWidget(len(self._items), widget, stretch)

    def insertWidget(self, index: int, widget: QWidget, stretch: int = 0) -> None:  # noqa: N802
        self.addChildWidget(widget)
        if index < 0 or index > len(self._items):
            index = len(self._items)
        self._items.insert(index, (QWidgetItem(widget), stretch))
        self.invalidate()

    def setStretchFactor(self, widget: QWidget, stretch: int) -> bool:  # noqa: N802
        for i, (item, _old) in enumerate(self._items):
            if item.widget() is widget:
                self._items[i] = (item, stretch)
                self.invalidate()
                return True
        return False

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index][0] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)[0]
        return None

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return False

    # ── 줄 짜기 ──────────────────────────────────────────────────────
    @staticmethod
    def _is_chip(item) -> bool:
        widget = item.widget()
        return isinstance(widget, FlowStep) and widget.state == DONE

    def _rows(self) -> list[tuple[str, list, int]]:
        """보이는 항목을 줄로 묶는다 — 연달아 마친 단계는 한 묶음('chips'), 나머지는 저마다 한 줄('full')."""
        rows: list[tuple[str, list, int]] = []
        chips: list = []
        for item, stretch in self._items:
            if item.isEmpty():                # 숨은 단계
                continue
            if self._is_chip(item):
                chips.append(item)
                continue
            if chips:
                rows.append(("chips", chips, 0))
                chips = []
            rows.append(("full", [item], stretch))
        if chips:
            rows.append(("chips", chips, 0))
        return rows

    @staticmethod
    def _chip_widths(item) -> tuple[int, int, int]:
        """마친 단계 네모가 바라는 폭(고른 값 글자를 다 보이게) · 줄여도 되는 최소 폭 · 높이."""
        step = item.widget()
        hint = item.sizeHint()               # 고른 값 칸(ElideLabel, Ignored)은 최소 폭으로만 셈된다
        text = step.summary.text()
        # 고른 값 칸은 바라는 폭에 최소 폭(10)으로 들어 있다 — 글자 폭에서 그만큼을 빼고 여유 6px
        text_w = max(0, QFontMetrics(step.summary.font()).horizontalAdvance(text) - 10 + 6) if text else 0
        return hint.width() + text_w, hint.width() + min(text_w, CHIP_SUMMARY_LEAST), hint.height()

    def _chip_lines(self, items: list, width: int, spacing: int) -> list[tuple[list[tuple], int]]:
        """네모들을 줄에 앉힌다 — [(그 줄의 [(항목, 폭)], 줄 높이)]. 최소 폭으로 줄을 나누고, 줄마다 남는 폭은 글자가 더 긴 네모부터 나눠 준다."""
        sizes = [(item, *self._chip_widths(item)) for item in items]
        lines: list[list[tuple]] = []
        line: list[tuple] = []
        used = 0
        for size in sizes:
            least = min(size[2], width)
            if line and used + spacing + least > width:
                lines.append(line)
                line, used = [], 0
            line.append(size)
            used += (spacing if len(line) > 1 else 0) + least
        if line:
            lines.append(line)
        placed: list[tuple[list[tuple], int]] = []
        line_h = max(size[3] for size in sizes)      # 네모 높이는 묶음 안에서 같게 — [바꾸기] 가 없는 네모가 혼자 남아도 낮아지지 않게
        for line in lines:
            widths = [min(size[2], width) for size in line]
            extra = [max(0, min(size[1], width) - w) for size, w in zip(line, widths)]
            spare = width - sum(widths) - spacing * (len(line) - 1)
            # 남는 폭은 공평하게 — 바라는 만큼만 받고 남은 것은 아직 모자란 네모가 다시 나눈다
            pending = [i for i, e in enumerate(extra) if e > 0]
            while spare > 0 and pending:
                share = spare // len(pending)
                if share <= 0:
                    break
                still = []
                for i in pending:
                    give = min(share, extra[i])
                    widths[i] += give
                    extra[i] -= give
                    spare -= give
                    if extra[i] > 0:
                        still.append(i)
                pending = still
            placed.append(([(size[0], w) for size, w in zip(line, widths)], line_h))
        return placed

    def _measure(self, width: int):
        """줄마다 (종류, 내용, 바라는 높이, 최소 높이, stretch)."""
        spacing = max(0, self.spacing())
        rows = []
        for kind, items, stretch in self._rows():
            if kind == "chips":
                lines = self._chip_lines(items, width, spacing)
                height = sum(h for _l, h in lines) + spacing * (len(lines) - 1)
                rows.append((kind, lines, height, height, 0))
            else:
                item = items[0]
                if item.hasHeightForWidth():
                    hint_h, min_h = item.heightForWidth(width), item.minimumHeightForWidth(width)
                else:
                    hint_h, min_h = item.sizeHint().height(), item.minimumSize().height()
                rows.append((kind, items, max(hint_h, min_h), min_h, stretch))
        return rows

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        area = rect.marginsRemoved(self.contentsMargins())
        width = max(0, area.width())
        spacing = max(0, self.spacing())
        self._width = width
        rows = self._measure(width)
        if not rows:
            return
        heights = [row[2] for row in rows]
        total = sum(heights) + spacing * (len(rows) - 1)
        if area.height() >= total:
            extra = area.height() - total
            stretched = [i for i, row in enumerate(rows) if row[4] > 0]
            weight = sum(rows[i][4] for i in stretched)
            given = 0
            for n, i in enumerate(stretched):
                share = extra - given if n == len(stretched) - 1 else extra * rows[i][4] // weight
                heights[i] += share
                given += share
        else:
            deficit = total - area.height()
            room = [row[2] - row[3] for row in rows]
            total_room = sum(room)
            if total_room > 0:
                cut = min(deficit, total_room)
                for i, r in enumerate(room):
                    if r > 0:
                        heights[i] -= min(r, cut * r // total_room)
        y = area.top()
        shape = []
        for row, height in zip(rows, heights):
            if row[0] == "chips":
                shape.append(len(row[1]))
                for line, line_h in row[1]:
                    x = area.left()
                    for item, w in line:
                        item.setGeometry(QRect(x, y, w, line_h))
                        x += w + spacing
                    y += line_h + spacing
                y -= spacing
            else:
                row[1][0].setGeometry(QRect(area.left(), y, width, height))
                y += height
            y += spacing
        shape_now = (width, tuple(shape))
        if shape_now != self._shape:
            # 네모 줄의 줄 수가 바뀌면 최소 높이도 바뀐다 — 스크롤 칸이 다시 묻게(한 번 더 자리를 잡으면 모양이 같아 멈춘다)
            self._shape = shape_now
            parent = self.parentWidget()
            if parent is not None:
                parent.updateGeometry()

    def _size(self, want_hint: bool) -> QSize:
        spacing = max(0, self.spacing())
        margins = self.contentsMargins()
        width = self._width or 0
        w = h = 0
        rows = self._rows()
        for n, (kind, items, _stretch) in enumerate(rows):
            if kind == "chips":
                if width > 0:
                    lines = self._chip_lines(items, width, spacing)
                    h += sum(lh for _l, lh in lines) + spacing * (len(lines) - 1)
                else:
                    h += max(self._chip_widths(item)[2] for item in items)
                w = max(w, max(self._chip_widths(item)[1] for item in items))
            else:
                size = items[0].sizeHint() if want_hint else items[0].minimumSize()
                w = max(w, size.width())
                h += size.height()
            if n:
                h += spacing
        return QSize(w + margins.left() + margins.right(), h + margins.top() + margins.bottom())

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._size(True)

    def minimumSize(self) -> QSize:  # noqa: N802
        return self._size(False)


class FlowArea(QScrollArea):
    """단계들을 담는 스크롤 칸 — 창이 낮으면(1024×640) 칸을 눌러 겹치게 하지 않고 아래로 넘긴다.
    다 들어가면 스크롤 막대 없이 그대로이고, stretch 를 준 단계(표)가 남는 높이를 받는다. 마지막에 filler 가 있어
    표 단계가 아직 안 보일 때 단계들이 위쪽에 모여 있다."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        body.setObjectName("pageBody")
        self.steps = _StepsLayout(body)
        self.steps.setContentsMargins(0, 0, 0, 0)
        self.steps.setSpacing(12)
        self.filler = QWidget()
        self.filler.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.steps.addWidget(self.filler, 1)
        self.setWidget(body)

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self.steps.insertWidget(self.steps.indexOf(self.filler), widget, stretch)

    def show_to(self, widget: QWidget) -> None:
        """떠오른 단계가 창 아래에 있으면 보이는 곳까지 내린다 — 자리가 잡힌 뒤에."""
        QTimer.singleShot(0, lambda: self.ensureWidgetVisible(widget, 0, 12))
