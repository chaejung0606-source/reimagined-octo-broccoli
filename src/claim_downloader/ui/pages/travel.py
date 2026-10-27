"""출장증빙자료 만들기 — 담당자 요청 2026-10-27 ("출장증빙자료 만들기 업무카드 추가해주세요"). 아직 준비 중.

출장비 청구에 붙이는 '출장 증빙'(담당자의 `출장 증빙 양식.xlsx` — 시트 자차 교통비 · 대중교통 교통비 · 체류 · 기타 · 차량정보를 찍어
'* 교통비 증빙' · '* 체류 증빙' 쪽으로 만든 `<이름> 출장증빙.pdf`, CLAUDE.md 14절 '출장비')을 앱이 만들 자리다.
양식 파일과 담당자가 지금 하는 차례를 받기 전이라 무엇을 채울지 정하지 않았다 — 추측으로 만들지 않는다.
그래서 이 화면에는 실행 버튼이 없다(tasks.py 의 ready=False, 5절 '동작하지 않는 생성 · 저장 버튼을 만들지 않는다').
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..art import Art
from ..widgets import EmptyState, Pill, fit_to_text, muted_label

# 최종 결과물은 '출장비 지급(…)' 폴더마다 있는 '<이름> 출장증빙.pdf'(담당자 2026-10-27 "출장증빙(이름) 파일이 최종적으로 나와야 하는 출장증빙자료")
PLAN = ("출장비 지급 폴더(출장신청서 · 영수증 · 출장 증빙 양식)를 넣으면 "
        "출장자마다 '<이름> 출장증빙.pdf'(교통비 · 체류 증빙)를 그 폴더에 만들 예정입니다. "
        "지금 손으로 만드신 출장증빙 PDF 와 출장 증빙 양식 엑셀을 보고 그 모양대로 만듭니다.")


class TravelPage(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 30)          # 아래 26px 이상 — 접힌 독이 마지막 줄을 가리지 않게
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(12)
        head.addWidget(Art("travel", 52), 0, Qt.AlignVCenter)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        title = QLabel("출장증빙자료 만들기")
        title.setObjectName("pageTitle")
        texts.addWidget(title)
        texts.addWidget(muted_label("출장비 청구에 붙일 교통비 · 체류 증빙을 만듭니다."))
        head.addLayout(texts, 1)
        head.addWidget(fit_to_text(Pill("준비 중", "neutral")), 0, Qt.AlignVCenter)
        layout.addLayout(head)

        layout.addWidget(EmptyState("travel", "준비 중인 업무입니다", PLAN), 1)
