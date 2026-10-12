"""사용자 설정과 기록 파일 위치.

설정과 기록은 앱 폴더가 아니라 `~/.claim-downloader/` 에 둔다. 앱 폴더는
자동 업데이트(git pull)가 갈아엎는 곳이라, 거기 두면 업데이트가 막히거나
기록이 날아갈 수 있다.

    ~/.claim-downloader/
      config.json      저장 폴더 · 파일명 형식 등
      _받은기록.json    받은 문서번호 (이어받기 · 중복 방지의 기준)
      _보관목록.json    보관 PDF 경로 → 문서번호 캐시 (지우면 다시 전체 스캔)
      _실행로그.txt     실행 로그. 문제가 생기면 여기부터 본다.

개인 경로를 기본값으로 넣지 않는다. 동료에게 그대로 공유할 수 있어야 한다.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path

APP_DIR_NAME = ".claim-downloader"
ERP_URL = "https://knu-icf.kangwon.ac.kr/rderp_layoutMain.act"


@dataclass
class Settings:
    out_root: str = ""             # 비목 폴더(01. 인건비 …)가 바로 아래 있는 폴더
    excel_path: str = ""           # 누락 검토용 ERP 청구내역 엑셀. 비우면 건너뜀
    name_date_first: bool = True   # False 면 옛 매크로 형식 '0N_(YYMMDD) …'
    wait_sec: float = 2.0          # 건당 여유(초)
    freeze_reload: bool = True     # 상세화면 멈춤 시 새로고침 후 이어받기
    auto_update_check: bool = True


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


def load() -> Settings:
    """설정 파일이 없거나 깨져 있으면 기본값. 모르는 키·틀린 형은 버린다.

    메모장으로 고친 파일 하나 때문에 앱이 뜨지 않으면 담당자는 손쓸 방법이 없다.
    """
    settings = Settings()
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
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
        elif isinstance(default, float):
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                setattr(settings, field.name, float(value))
        elif isinstance(value, str):
            setattr(settings, field.name, value)
    return settings


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
