"""단계 흐름 — 업무 화면을 '할 차례인 것만 보이게' 쌓는 틀. 담당자 요청 2026-10-21.

담당자: "업무카드를 열면 모든 기능들이 다 펼쳐져 있어 어디부터 클릭해야 하는지 헷갈림. 클릭해야 하는 순서대로 버튼 및 기능이 하나 둘
떠올라서 순서대로 선택하게" · "모든 업무카드 — 사용자 입장 및 진행순서 생각해서 구조 다시 배치".

- 단계는 위에서 아래로 쌓인다. 아직 차례가 아닌 단계는 **보이지 않는다**('hidden') — 앞 단계를 마치면 그 아래에 떠오른다(옅게 나타남).
- 지금 할 단계는 라벤더 테두리('current'), 마친 단계는 한 줄로 접혀 고른 값을 보인다('done') — [바꾸기] 를 누르면 다시 펼친다(edit 신호).
- 표처럼 계속 봐야 하는 단계는 펼친 채 둔다('open' — 테두리만 보통).
상태는 화면이 정한다 — 이 틀은 모양만 맡는다(어느 단계가 끝났는지는 업무마다 다르다).
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from .flowlogic import CURRENT, DONE, HIDDEN, OPEN, flow_states  # noqa: F401 — 화면이 여기서 함께 가져다 쓴다
from .widgets import ElideLabel, WrapLabel, fit_to_text


class FlowStep(QFrame):
    """단계 하나 — 번호 · 제목 · (접혔을 때) 고른 값 한 줄 · [바꾸기] / (펼쳤을 때) 안내 한 줄 · 내용."""

    edit = Signal()

    def __init__(self, number: str, title: str, hint: str = "", editable: bool = True, parent: QWidget | None = None):
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
        self.edit_button = QPushButton("바꾸기")
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

