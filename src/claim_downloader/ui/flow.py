"""단계 흐름 — 업무 화면을 '할 차례인 것만 보이게' 쌓는 틀. 담당자 요청 2026-10-21.

담당자: "업무카드를 열면 모든 기능들이 다 펼쳐져 있어 어디부터 클릭해야 하는지 헷갈림. 클릭해야 하는 순서대로 버튼 및 기능이 하나 둘
떠올라서 순서대로 선택하게" · "모든 업무카드 — 사용자 입장 및 진행순서 생각해서 구조 다시 배치".

- 단계는 위에서 아래로 쌓인다. 아직 차례가 아닌 단계는 **보이지 않는다**('hidden') — 앞 단계를 마치면 그 아래에 떠오른다(옅게 나타남).
- 지금 할 단계는 라벤더 테두리('current'), 마친 단계는 한 줄로 접혀 고른 값을 보인다('done') — [바꾸기] 를 누르면 다시 펼친다(edit 신호).
- 표처럼 계속 봐야 하는 단계는 펼친 채 둔다('open' — 테두리만 보통).
상태는 화면이 정한다 — 이 틀은 모양만 맡는다(어느 단계가 끝났는지는 업무마다 다르다).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
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
        self.steps = QVBoxLayout(body)
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
