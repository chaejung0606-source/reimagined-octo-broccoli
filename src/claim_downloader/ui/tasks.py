"""업무 목록 — 홈 카드 · 하단 독 · 작업 탭 · [+] 메뉴가 모두 이 표 하나를 읽는다.

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
    art: str                # ui/art.py 의 업무 의미 이름 (큰 입체 그림)
    icon: str               # ui/icons.py 의 선 아이콘 (탭처럼 작은 곳)
    accent: str             # 아이콘 둘레 장식 색 (tokens.COLORS 의 키)
    page: str               # 'module:Class' — ui/pages/ 아래
    ready: bool             # False 면 준비 중 — 기능 미리보기만. 실행 버튼을 두지 않는다
    dock: bool = True       # 하단 독에 두는지 (설정·업데이트는 상단 메뉴에서)


TASKS: tuple[Task, ...] = (
    # 이름은 담당자 지정 2026-10-22 ("청구서 받기 업무카드 제목을 증빙 다운로드로") — 청구서 외에 구매요청(계약) 서류도 받을 자리라서. id 는 그대로 download
    Task("download", "증빙 다운로드", "ERP 청구서 등 증빙 서류를 확인하고 파일로 보관합니다.",
         "receive", "download", "mint", "download:DownloadPage", ready=True),
    Task("meeting", "회의록 생성", "회의 자료 폴더에서 정산용 회의록(.hwpx)을 만듭니다.",
         "meeting", "book", "lavender", "minutes:MinutesPage", ready=True),
    # 장학금 · 카드 · 출장비는 따로 두지 않고 일반청구 화면에서 폴더마다 '청구 종류' 로 고른다(담당자 제안 2026-10-14, claims/kinds.py)
    Task("claim", "일반청구", "지출 폴더마다 청구 종류(일반 · 장학금 …)를 골라 ERP 일반청구 화면에 채우고 임시저장합니다. 신청은 직접.",
         "claim", "document-check", "peach", "claim:ClaimPage", ready=True),
    # 담당자 요청 2026-10-21 — 교내 주차 등록 사이트. 1단계는 앱 브라우저로 열고 자동 로그인 · 직접 입력, 앱 입력은 실측 뒤(parking.py)
    Task("parking", "주차등록", "교내 주차 등록 사이트를 앱 브라우저로 열고 자동으로 로그인합니다.",
         "parking", "car", "sky", "parking:ParkingPage", ready=True),
    # 담당자 요청 2026-10-21 — 업무마다 있던 [화면 구조 저장] 을 한 업무로(ERP · 주차등록 사이트를 골라 실측, diagnose.py)
    Task("structure", "화면 구조 저장", "ERP · 주차등록 사이트에 띄운 화면의 칸 · 단추를 읽어 파일로 남깁니다(새 화면 자동화 전 실측).",
         "structure", "layout", "cyan", "structure:StructurePage", ready=True),
)

# 상단 메뉴에서 여는 화면. 독·홈 카드·[+] 메뉴에는 두지 않는다.
UTILITIES: tuple[Task, ...] = (
    Task("settings", "설정", "저장 폴더 · 파일 이름 형식 · AI 플랫폼(로그인) · 일반청구 · 바로가기 · 기록", "settings", "sliders", "lavender",
         "settings:SettingsPage", ready=True, dock=False),
    Task("updates", "업데이트", "기능 갱신 확인·적용", "upload", "gear", "sky",
         "updates:UpdatesPage", ready=True, dock=False),
)

HOME_ID = "home"
HOME_ICON = "home"


def find(task_id: str) -> Task:
    for task in TASKS + UTILITIES:
        if task.id == task_id:
            return task
    raise KeyError(task_id)
