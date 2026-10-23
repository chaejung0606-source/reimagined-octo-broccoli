"""사용자 설정과 기록 파일 위치.

설정과 기록은 앱 폴더가 아니라 `~/.claim-downloader/` 에 둔다. 앱 폴더는
자동 업데이트(git pull)가 갈아엎는 곳이라, 거기 두면 업데이트가 막히거나
기록이 날아갈 수 있다.

    ~/.claim-downloader/
      config.json      저장 폴더 · 파일명 형식 등
      _받은기록.json    받은 문서번호 (이어받기 · 중복 방지의 기준)
      _보관목록.json    보관 PDF 경로 → 문서번호 캐시 (지우면 다시 전체 스캔)
      _실행로그.txt     실행 로그. 문제가 생기면 여기부터 본다. 회의록 생성 기록도 여기에.
      회의록규칙.txt    회의록 작성 규칙 (minutes/rules.py). 기본값 파일과 쌍으로.
      _과제목록.json    로그인 뒤 과제현황에서 읽은 과제(설정의 과제 고르기)
      _화면구조.txt     진단 모드 결과 — 열린 ERP 화면의 입력 요소 (새 화면 실측용) · _화면구조_모음.txt 저장할 때마다 쌓은 것
      일반청구규칙.txt  일반청구 추출 규칙 (claims/rules.py) · _청구입력기록.json 채운 폴더 기록
      장학금규칙.txt    장학금 청구 대표적요·행 적요 규칙 (claims/scholarship.py)
      혁신인재지원금규칙.txt  혁신인재지원금 청구 규칙 (같은 모양, 대표적요 03_)
      _주차로그인.json  주차등록 사이트 자동 로그인(아이디 · 윈도우 DPAPI 로 감싼 비밀번호) — parking.py. ERP 로그인은 어디에도 두지 않는다
      _공무확인증관리대장.json  주차 공무확인증 구입 · 배부(사용자 · 내용 · 차량번호) — parking_ledger.py. 엑셀로 받을 수 있다
      _공무확인증잔량기록.json  사이트에서 본 공무확인증 보유 잔량과 그 때 — 적용금액 0 인 사용이 차감되는지 가린다(parking_ledger.drain_study)

개인 경로를 기본값으로 넣지 않는다. 동료에게 그대로 공유할 수 있어야 한다.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_DIR_NAME = ".claim-downloader"
# 윈도우 작업 표시줄이 창과 바로가기를 한 단추로 묶는 이름. 앱(ui/app.py)과 바로가기(tools/create_shortcut.py)가
# 같은 값을 써야 고정한 바로가기와 실행 중인 창이 하나로 보인다. 바꾸면 담당자가 다시 고정해야 한다.
APP_USER_MODEL_ID = "Kangwon.COSS.WorkDesk"
# 바로가기(바탕화면 · 시작 메뉴 · 작업 표시줄 고정)가 가리키는 아이콘 파일. 윈도우는 아이콘 그림을 **파일 경로로** 저장해 두고
# 파일 내용이 바뀌어도 다시 읽지 않는다 — 2026-10-14 아이콘을 바꾼 뒤 바탕화면 바로가기는 새 그림인데 작업 표시줄에 고정하면
# 옛 그림이 떴다. 그래서 디자인을 바꿀 때마다 이 이름을 바꾼다(tools/make_icon.py 가 icon.ico 와 같은 그림으로 이 파일도 만든다).
SHORTCUT_ICON = "icon-20261014.ico"
ERP_URL = "https://knu-icf.kangwon.ac.kr/rderp_layoutMain.act"
# 로그인 뒤 앱이 여는 과제 — 담당자 지정(2026-10-19). 다른 과제는 설정에서 고른다(과제기간에 오늘이 든 과제만 보인다, navigate.choices).
DEFAULT_PROJECT_NO = "202408470003"


@dataclass
class Settings:
    out_root: str = ""             # 비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더
    # 구매요청(계약) 서류를 둘 폴더 — 비우면 '<저장 폴더>/구매요청(계약) 서류'. 용량이 커서(담당자 추정 200GB) 다른 드라이브를 고를 수 있다.
    # 처음엔 구글 드라이브를 권했으나 무료 15GB 가 다 차 그 기능을 없애고 네이버 MYBOX 를 쓴다(담당자 2026-10-22). 23절
    purchase_root: str = ""
    excel_path: str = ""           # 누락 검토용 ERP 청구내역 엑셀. 비우면 건너뜀
    # 기본은 비목 번호를 앞에 붙인다 '0N_(YYMMDD) …'. 담당자가 이 형식으로 받기를 원했다.
    # True 면 '(YYMMDD) …' — 2026년도 기존 보관본 형식.
    name_date_first: bool = False
    wait_sec: float = 2.0          # 건당 여유(초)
    freeze_reload: bool = True     # 상세화면 멈춤 시 새로고침 후 이어받기
    # 받기 화면에서 브라우저를 연 뒤 결의서내역 목록이 보이면 [목록 읽기] 를 저절로 — 읽기만 한다(2026-10-15 추가 기능)
    auto_read_list: bool = True
    # 로그인하면 메인화면 과제현황에서 이 과제를 열고 과제정보 → 청구서 탭(결의서내역)까지 앱이 간다(담당자 허락 2026-10-19, navigate.py)
    auto_open_project: bool = True
    # 마지막으로 고른 ERP 과제 — 과제는 일반청구 화면에서 폴더마다 고르고(담당자 2026-10-19), 로그인 뒤 이동 · 과제 없는 폴더가 이것을 쓴다
    project_no: str = DEFAULT_PROJECT_NO
    # 증빙 다운로드 ② 의 과제 체크(과제 폴더가 있을 때, 22절) — 'all' 모두 체크(폴더가 늘면 그것도) · 'some' 여럿(download_projects, 쉼표로) ·
    # 'one' 과제 하나(project_no). 담당자 요청 2026-10-21 "여러개 과제를 선택해서 연속적으로" · 2026-10-22 "체크체크해서 단일이나 복수"
    download_scope: str = "all"
    download_projects: str = ""
    # 명단 폴더를 넣을 때 다른(저장된) 청구서가 떠 있으면 결의서 목록의 [일반청구] 로 새 청구서를 앱이 띄운다(담당자 허락 2026-10-19).
    # 카드청구도 [카드청구](#P11)로 같이(담당자 허락 2026-10-20)
    auto_new_sheet: bool = True
    # ERP 를 이 분 동안 쓰지 않거나(마우스 · 키보드 · 앱의 일 없음) 로그아웃 없이 ERP 창 · 앱을 닫으면 앱이 ERP [로그아웃] 을 누른다
    # (담당자 요청 2026-10-21, logout.py). 분은 config.json 에서 바꾼다 — 0 이면 '쓰지 않음' 로그아웃만 끈다
    auto_logout: bool = True
    auto_logout_minutes: int = 30
    # 홈의 '처음 쓰시나요?' 안내를 닫았는지 — 동료 PC 에 처음 깔았을 때만 보이게(사용자 메뉴에서 다시 볼 수 있다)
    welcome_dismissed: bool = False
    auto_update_check: bool = True
    # 회의록 생성 (minutes/). 이메일은 Claude 로그인 화면에 미리 채워 넣는 용도 — 비밀번호는 없다.
    claude_email: str = ""
    minutes_backend: str = "claude-cli"   # 회의록 생성에 쓸 AI 플랫폼 — minutes/backends 의 key (설정 → AI 플랫폼)
    claim_backend: str = "claude-cli"     # 일반청구 [내용 읽기] 에 쓸 AI 플랫폼 — claims/extract 의 key (ai.py)
    minutes_model: str = ""               # 비우면 백엔드의 기본 모델
    # 일반청구 팝업(입금처·세금계산서)에서 결과가 하나로 확실하면 앱이 골라 [확인]까지 누른다. 애매하면 사람(담당자 결정 2026-10-13).
    claim_auto_pick: bool = True
    # 세금계산서 조회 팝업의 '계산서수신메일' — 목록에 산학협력단 전체 계산서가 다 떠서 내 메일로 걸러야 내 건만 보인다
    # (담당자 설명 2026-10-13). 사용자별 값이라 코드에 두지 않는다. 비우면 메일 없이 사업자번호로만 조회한다.
    taxbill_email: str = ""
    # 카드청구 회의비의 참석자를 참여인력 · 내부참석자로 가를 ERP '참여연구원 현황표'(엑셀 · PDF). 실명 · 직번이 든 사용자 파일이라
    # 위치만 둔다. 비우면 카드 폴더 · 그 위 폴더에서 이름에 '참여연구원' 이 든 파일을 찾는다(claims/participants.find_file)
    participants_file: str = ""
    # 주차등록 사이트(parking.py) — 담당자 요청 2026-10-21. 로그인 정보는 여기가 아니라 _주차로그인.json(비밀번호는 윈도우 DPAPI 로 감쌈)에
    parking_url: str = "https://traffic.kangwon.ac.kr/login"
    parking_auto_login: bool = True        # 로그인 정보가 있으면 사이트를 열 때 한 번 자동 로그인(담당자 허락 2026-10-21)
    parking_product: str = ""              # 마지막으로 고른 할인권 상품(남은 수를 뗀 이름) — 앱의 [등록](parking_link.py)
    parking_products: str = ""             # 사이트에서 본 할인권 상품 보기(줄마다 하나, 남은 수 포함) — 화면의 고르기 칸을 채운다
    parking_left: int = -1                 # 마지막으로 읽은 사이트 보유 잔량(공무확인증) — 관리대장 처음 수량을 셈한다(-1 = 아직 못 읽음)
    parking_left_at: str = ""              # 그 잔량을 읽은 때(MM-DD HH:MM)
    parking_free_rule: str = ""            # 적용금액 0 인 사용이 차감되는지 — "all"(차감됨) · "paid"(차감 안 됨) · ""(아직 모름). parking_ledger.drain_study
    parking_free_rule_at: str = ""         # 그렇게 정한 때(MM-DD HH:MM)
    parking_free_note: str = ""            # 그 분석의 지금 상태 한 줄(관리대장 잔여 상자에 보임)


def data_dir() -> Path:
    """환경변수로 바꿀 수 있어 테스트가 사용자 홈을 건드리지 않는다."""
    override = os.environ.get("CLAIM_DOWNLOADER_HOME")
    base = Path(override) if override else Path.home() / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return data_dir() / "config.json"


def done_path() -> Path:
    return data_dir() / "_받은기록.json"


def archive_cache_path() -> Path:
    return data_dir() / "_보관목록.json"


def log_path() -> Path:
    return data_dir() / "_실행로그.txt"


def parking_ledger_path() -> Path:
    """공무확인증 관리대장(parking_ledger.py) — 사용자 이름 · 차량번호가 있어 저장소 · 배포에서 뺀다."""
    return data_dir() / "_공무확인증관리대장.json"


def parking_readings_path() -> Path:
    """사이트에서 본 공무확인증 보유 잔량과 그 때 — 적용금액 0 인 사용이 차감되는지 날이 지나며 가린다(parking_ledger.drain_study)."""
    return data_dir() / "_공무확인증잔량기록.json"


def parking_sheet_path() -> Path:
    """공무확인증 관리대장의 구글 시트 연동(parking_sheet.py) — 웹 앱 주소 · 토큰. 그 둘이면 시트를 읽고 쓸 수 있어 저장소 · 배포에서 뺀다."""
    return data_dir() / "_구글시트연동.json"


def progress_path() -> Path:
    """다운로드 현황(progress.py) — 결의서 · 구매요구 건마다 받았는지. 대표적요 · 대표건명(사람 이름이 들 수 있음)이 있어 저장소 · 배포에서 뺀다."""
    return data_dir() / "_증빙현황.json"


def skip_path() -> Path:
    """받지 않는 결의서(skiplist.py) — 청구서출력이 없어 받을 수 없는 결의서. 대표적요(사람 이름이 들 수 있음)가 있어 저장소 · 배포에서 뺀다."""
    return data_dir() / "_받지않는결의서.json"


def structure_path() -> Path:
    """진단 모드(diagnose.py)가 남기는 화면 구조. 계좌번호 같은 값이 섞일 수 있어 저장소·배포에서 뺀다."""
    return data_dir() / "_화면구조.txt"


def projects_path() -> Path:
    """메인화면 과제현황에서 마지막으로 읽은 과제 목록(과제번호 · 과제명 · 기간) — 설정의 과제 고르기 칸이 쓴다."""
    return data_dir() / "_과제목록.json"


def structure_book_path() -> Path:
    """[화면 구조 저장] 을 누를 때마다 차례로 쌓는 모음 — 메뉴 이동처럼 화면 여러 개를 실측할 때 마지막에 이 파일 하나만 보내면 된다."""
    return data_dir() / "_화면구조_모음.txt"


def claims_rules_path() -> Path:
    """일반청구 추출 규칙 (claims/rules.py). 회의록 규칙과 같은 방식의 쌍."""
    return data_dir() / "일반청구규칙.txt"


def claims_rules_base_path() -> Path:
    return data_dir() / "일반청구규칙.기본값.txt"


def scholarship_rules_path() -> Path:
    """장학금 청구 적요 규칙 (claims/scholarship.py). 일반청구 규칙과 같은 방식의 쌍."""
    return data_dir() / "장학금규칙.txt"


def scholarship_rules_base_path() -> Path:
    return data_dir() / "장학금규칙.기본값.txt"


def innovation_rules_path() -> Path:
    """혁신인재지원금 청구 적요 규칙 — 장학금과 같은 모양, 대표적요의 비목 번호만 03."""
    return data_dir() / "혁신인재지원금규칙.txt"


def innovation_rules_base_path() -> Path:
    return data_dir() / "혁신인재지원금규칙.기본값.txt"


def personal_rules_path() -> Path:
    """개인 지급(일반청구 탭 · 증빙 기타) 적요 규칙 — 장학금과 같은 모양, 대표적요의 바탕이 지급 공문 제목."""
    return data_dir() / "개인지급규칙.txt"


def personal_rules_base_path() -> Path:
    return data_dir() / "개인지급규칙.기본값.txt"


def claim_record_path() -> Path:
    """ERP 에 채운 지출 폴더의 기록 — 같은 건을 두 번 채우지 않게 묻는 근거."""
    return data_dir() / "_청구입력기록.json"


def minutes_rules_path() -> Path:
    """담당자가 고쳐 쓰는 회의록 작성 규칙. 저장만 하면 다음 [작업 시작] 부터 반영된다."""
    return data_dir() / "회의록규칙.txt"


def minutes_rules_base_path() -> Path:
    """마지막으로 써 준 기본 규칙 — 위 파일을 담당자가 고쳤는지 판단하는 기준."""
    return data_dir() / "회의록규칙.기본값.txt"


def load() -> Settings:
    """설정 파일이 없거나 깨져 있으면 기본값. 모르는 키·틀린 형은 버린다.

    메모장으로 고친 파일 하나 때문에 앱이 뜨지 않으면 담당자는 손쓸 방법이 없다.
    """
    settings = Settings()
    try:
        # utf-8-sig — 메모장이 'UTF-8(BOM)' 으로 저장하면 앞에 BOM 이 붙어 json 이 못 읽고 설정이 모두 기본값으로 돌아갔다(2026-10-14 점검)
        text = config_path().read_text(encoding="utf-8-sig")
    except OSError:
        return settings
    except ValueError:                          # UTF-8 이 아님(메모장 'ANSI') — 한글 윈도우 기본 인코딩으로 한 번 더
        try:
            text = config_path().read_text(encoding="cp949")
        except (OSError, ValueError):
            _keep_broken()
            return settings
    try:
        data = json.loads(text)
    except ValueError:
        _keep_broken()
        return settings
    if not isinstance(data, dict):
        return settings
    for field in fields(Settings):
        if field.name not in data:
            continue
        value = data[field.name]
        default = getattr(settings, field.name)
        if isinstance(default, bool):
            if isinstance(value, bool):
                setattr(settings, field.name, value)
        elif isinstance(default, int):            # 자동 로그아웃 분 — 메모장에서 30.0 으로 적어도 받는다
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                setattr(settings, field.name, int(value))
        elif isinstance(default, float):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                setattr(settings, field.name, float(value))
        elif isinstance(value, str):
            setattr(settings, field.name, value)
    return settings


def _keep_broken() -> None:
    """읽지 못한 설정 파일은 다음 저장이 기본값으로 덮어쓰기 전에 옆에 남겨 둔다(config.json.읽지못함) — 담당자가 고친 경로를 되살릴 수 있게."""
    path = config_path()
    keep = path.with_name(path.name + ".읽지못함")
    try:
        if path.exists() and not keep.exists():
            keep.write_bytes(path.read_bytes())
    except OSError:
        pass


def save(settings: Settings) -> None:
    config_path().write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")


def update(**changes) -> Settings:
    settings = load()
    for key, value in changes.items():
        if not hasattr(settings, key):
            raise KeyError(key)
        setattr(settings, key, value)
    save(settings)
    return settings
