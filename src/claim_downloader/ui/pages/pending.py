"""아직 기능이 없는 업무의 미리보기 화면 — 회의록 생성 · 일반청구 · 카드청구.

준비 중 안내는 위에 한 번만. 입력 칸은 비활성(점선 테두리·연한 글자)으로 두어 쓸 수
있는 것처럼 보이지 않게 한다. 생성·저장·제출 버튼은 없다.

화면 구조(입력 / 결과, 청구 내용 / 증빙 / 진행 상태)만 미리 잡아 둔다. 업무 규칙과
ERP 제출 동작은 아직 정해지지 않았으므로 여기서 만들지 않는다(docs/roadmap.md).
이 화면을 열어 본 것은 '이어서 할 작업'으로 기록하지 않는다.
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
from ..widgets import Card, Pill, WrapLabel


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


def _placeholder(art: str, text: str) -> QWidget:
    """결과 자리 — 작은 그림 한 장과 한 줄."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 12, 0, 12)
    layout.setSpacing(8)
    layout.addStretch(1)
    layout.addWidget(Art(art, 64), 0, Qt.AlignHCenter)
    label = QLabel(text)
    label.setObjectName("muted")
    label.setAlignment(Qt.AlignCenter)
    layout.addWidget(label)
    layout.addStretch(1)
    box.setMinimumHeight(180)
    return box


class PendingPage(QWidget):
    """준비 중 업무의 공통 뼈대. 하위 클래스가 본문 구조만 채운다."""

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
        layout.setContentsMargins(24, 20, 24, 28)
        layout.setSpacing(14)
        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art(task.art, 48), 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(task.name)
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        desc = QLabel(task.description)
        desc.setObjectName("pageDesc")
        texts.addWidget(desc)
        head.addLayout(texts, 1)
        layout.addLayout(head)
        layout.addWidget(_notice(self.notice))
        self.build(layout)
        layout.addStretch(1)

    def build(self, layout: QVBoxLayout) -> None:
        raise NotImplementedError


class MeetingPage(PendingPage):
    notice = ("회의록 생성은 준비 중인 기능의 미리보기입니다. 입력 형식과 결과 형식이 정해지면 "
              "왼쪽에 회의 내용을 넣고 오른쪽에서 회의록을 받게 됩니다.")

    def build(self, layout: QVBoxLayout) -> None:
        row = QHBoxLayout()
        row.setSpacing(14)
        left = Card("회의 내용", "녹취·메모를 붙여 넣는 곳")
        source = QPlainTextEdit()
        source.setPlaceholderText("비활성 — 기능이 준비되면 입력할 수 있습니다")
        source.setEnabled(False)
        source.setMinimumHeight(220)
        left.add(source, 1)
        right = Card("회의록")
        right.add(_placeholder("meeting", "생성된 회의록이 여기에 표시됩니다"), 1)
        row.addWidget(left, 1)
        row.addWidget(right, 1)
        layout.addLayout(row, 1)


class ClaimPage(PendingPage):
    notice = ("일반청구 작성은 준비 중인 기능의 미리보기입니다. 먼저 ERP 의 일반청구 화면 구조를 실측한 뒤 "
              "'자동 입력 → 화면에 요약 → 사람이 확인하고 제출' 구조로 만듭니다. 제출은 언제나 사람이 합니다.")

    def build(self, layout: QVBoxLayout) -> None:
        self._three_parts(layout, "claim", ("청구 내용", "적요 · 금액 · 비목 · 입금처", "작성한 청구가 여기에 표시됩니다"),
                          ("증빙", "증빙 파일 목록"), ("진행 상태", "작성 → 확인 → 제출(사람)"))


class CardPage(PendingPage):
    notice = ("카드청구 작성은 준비 중인 기능의 미리보기입니다. 카드 사용 내역 형식이 정해지면 일반청구와 같은 "
              "'자동 입력 → 화면에 요약 → 사람이 확인하고 제출' 구조로 만듭니다.")

    def build(self, layout: QVBoxLayout) -> None:
        self._three_parts(layout, "card", ("카드 사용 내역", "일자 · 가맹점 · 금액", "정리한 사용 내역이 여기에 표시됩니다"),
                          ("증빙", "영수증 · 증빙 파일"), ("진행 상태", "정리 → 확인 → 제출(사람)"))


def _three_parts(self: PendingPage, layout: QVBoxLayout, art: str, first, *rest) -> None:
    """청구 내용 / 증빙 / 진행 상태 — 세 칸을 나란히. 첫 칸이 넓고 그림이 있다."""
    row = QHBoxLayout()
    row.setSpacing(14)
    title, hint, text = first
    card = Card(title, hint)
    card.add(_placeholder(art, text), 1)
    row.addWidget(card, 2)
    for title, hint in rest:
        card = Card(title, hint)
        empty = QLabel("—")
        empty.setObjectName("muted")
        empty.setAlignment(Qt.AlignCenter)
        empty.setMinimumHeight(120)
        card.add(empty, 1)
        row.addWidget(card, 1)
    layout.addLayout(row, 1)


PendingPage._three_parts = _three_parts
