"""업무 목록 — 홈 카드 · 하단 독 · 작업 탭이 모두 이 표 하나를 읽는다.

새 업무를 더할 때는 여기에 한 줄 넣고 화면 클래스를 연결하면 된다. 탐색 구조를
따로 손대지 않는다.

Qt 를 들여오지 않는다. 그래야 PySide6 가 없는 CI 에서도 이 표를 검사할 수 있다
(tests/test_tasks.py). 화면 클래스는 이름으로 적어 두고 app.py 가 늦게 불러온다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Task:
    id: str
    name: str
    description: str        # 홈 카드 한두 줄
    art: str                # ui/art.py 의 업무 의미 이름
    accent: str             # 아이콘 주변 장식 색 (tokens.COLORS 의 키)
    page: str               # 'module:Class' — ui/pages/ 아래
    ready: bool             # False 면 준비 중 — 실행 버튼을 두지 않는다
    dock: bool = True       # 하단 독에 두는지 (설정·업데이트는 상단 메뉴에서)


TASKS: tuple[Task, ...] = (
    Task("download", "청구서 받기", "ERP 청구서를 확인하고 파일로 보관합니다.",
         "receive", "mint", "download:DownloadPage", ready=True),
    Task("meeting", "회의록 생성", "회의 내용을 정리해 회의록을 작성합니다.",
         "meeting", "lavender", "pending:MeetingPage", ready=False),
    Task("claim", "일반청구", "일반 지출 청구를 작성하고 관리합니다.",
         "claim", "peach", "pending:ClaimPage", ready=False),
    Task("card", "카드청구", "카드 사용 내역과 증빙을 정리합니다.",
         "card", "sky", "pending:CardPage", ready=False),
)

# 상단 메뉴에서 여는 화면. 독·홈 카드에는 두지 않는다.
UTILITIES: tuple[Task, ...] = (
    Task("settings", "설정", "저장 폴더 · 파일 이름 형식", "settings", "lavender",
         "settings:SettingsPage", ready=True, dock=False),
    Task("updates", "업데이트", "기능 갱신 확인·적용", "upload", "sky",
         "updates:UpdatesPage", ready=True, dock=False),
)

HOME_ID = "home"


def find(task_id: str) -> Task:
    for task in TASKS + UTILITIES:
        if task.id == task_id:
            return task
    raise KeyError(task_id)
