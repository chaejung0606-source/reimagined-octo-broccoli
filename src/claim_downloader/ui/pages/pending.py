"""아직 기능이 없는 업무의 진입 화면 — 회의록 생성 · 일반청구 · 카드청구.

할 수 있는 것만 보인다. 생성·저장·제출 버튼을 두지 않는다. 동작하지 않는 버튼이
있으면 담당자는 눌러 보고 앱이 고장 난 줄 안다.

화면 구조(입력 영역 / 결과 영역, 청구 내용 / 증빙 / 진행 상태)는 미리 잡아 두어,
기능이 들어올 때 자리를 다시 짜지 않아도 된다. 업무 규칙·ERP 제출 동작은 아직
정해지지 않았으므로 여기서 임의로 만들지 않는다(docs/roadmap.md).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..art import Art
from ..tasks import Task
from ..widgets import Card, EmptyState, PageHeader, Pill, WrapLabel


def _notice(text: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("notice")
    row = QHBoxLayout(frame)
    row.setContentsMargins(16, 10, 16, 10)
    row.setSpacing(10)
    row.addWidget(Pill("준비 중", "info"), 0, Qt.AlignTop)
    label = WrapLabel(text)
    label.setObjectName("noticeText")
    row.addWidget(label, 1)
    return frame


class PendingPage(QWidget):
    """준비 중 업무의 공통 뼈대. 하위 클래스가 본문 구조만 채운다."""

    task: Task
    notice: str = ""

    def __init__(self, task: Task, parent: QWidget | None = None):
        super().__init__(parent)
        self.task = task
        self.setObjectName("page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("pageBody")
        scroll.setWidget(body)
        outer.addWidget(scroll)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(16)
        header = PageHeader(f"업무  ›  {task.name}", task.name, task.description)
        header.add_action(Art(task.art, 56))
        layout.addWidget(header)
        layout.addWidget(_notice(self.notice))
        self.build(layout)
        layout.addStretch(1)

    def build(self, layout: QVBoxLayout) -> None:  # noqa: D401
        raise NotImplementedError

    def _three_parts(self, layout: QVBoxLayout, art: str, *parts: str) -> None:
        """청구 내용 / 증빙 / 진행 상태 — 세 칸을 나란히. 첫 칸이 넓다."""
        row = QHBoxLayout()
        row.setSpacing(16)
        for i, (title, hint) in enumerate(zip(parts[0::2], parts[1::2])):
            card = Card(title, hint)
            if i == 0:
                card.add(EmptyState(art, "아직 작성할 수 없습니다", "기능이 준비되면 여기서 작성합니다."), 1)
            else:
                placeholder = QLabel("—")
                placeholder.setObjectName("muted")
                placeholder.setAlignment(Qt.AlignCenter)
                placeholder.setMinimumHeight(160)
                card.add(placeholder, 1)
            row.addWidget(card, 2 if i == 0 else 1)
        layout.addLayout(row, 1)


class MeetingPage(PendingPage):
    notice = ("회의록 생성은 아직 준비 중입니다. 왼쪽에 회의 내용을 넣고 오른쪽에서 정리된 회의록을 "
              "받게 될 자리입니다. 지금은 입력도 생성도 되지 않습니다.")

    def build(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(16)
        left = Card("회의 내용", "녹취·메모를 붙여 넣는 곳")
        self.source = QPlainTextEdit()
        self.source.setPlaceholderText("준비 중입니다.")
        self.source.setEnabled(False)
        self.source.setMinimumHeight(260)
        left.add(self.source, 1)
        right = Card("회의록", "정리된 결과가 나오는 곳")
        result = EmptyState("meeting", "아직 만들 수 없습니다", "기능이 준비되면 여기에 회의록이 나옵니다.")
        right.add(result, 1)
        row.addWidget(left, 1)
        row.addWidget(right, 1)
        layout.addLayout(row, 1)


class ClaimPage(PendingPage):
    notice = ("일반청구 작성은 아직 준비 중입니다. 먼저 ERP 의 일반청구 화면 구조를 실측한 뒤 "
              "'자동 입력 → 화면에 요약 → 사람이 확인하고 제출' 구조로 만듭니다. 제출은 언제나 사람이 합니다.")

    def build(self, layout: QVBoxLayout) -> None:
        self._three_parts(layout, "claim", "청구 내용", "적요 · 금액 · 비목 · 입금처",
                          "증빙", "증빙 파일 목록", "진행 상태", "작성 → 확인 → 제출(사람)")


class CardPage(PendingPage):
    notice = ("카드청구 작성은 아직 준비 중입니다. 카드 사용 내역 형식이 정해지면 일반청구와 같은 "
              "'자동 입력 → 화면에 요약 → 사람이 확인하고 제출' 구조로 만듭니다.")

    def build(self, layout: QVBoxLayout) -> None:
        self._three_parts(layout, "card", "카드 사용 내역", "일자 · 가맹점 · 금액",
                          "증빙", "영수증 · 증빙 파일", "진행 상태", "정리 → 확인 → 제출(사람)")
