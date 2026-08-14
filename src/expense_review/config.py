"""앱 설정과 사용자 규칙 오버라이드.

규칙 파일(`rules/*.yaml`)은 **배포본**이다. 자동 업데이트가 이 파일을 덮어쓴다.
그래서 사용자가 앱에서 고친 내용은 여기에 따로 저장한다.

    rules/*.yaml        ← Claude 가 갱신 (git pull)
    ~/.expense-review/  ← 사용자가 앱에서 고친 것 (업데이트해도 유지)

이렇게 나누지 않으면, 담당자가 등급이나 한도를 고쳐 둔 상태에서 업데이트가
오면 충돌이 나거나 수정 내용이 조용히 날아간다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

APP_DIR_NAME = ".expense-review"

# 사용자가 앱에서 고칠 수 있는 규칙 항목. 판정 로직은 코드에 있으므로 건드리지 않는다.
EDITABLE_RULE_FIELDS = ("severity", "enabled", "message", "fix", "title")


def config_dir() -> Path:
    """설정 저장 위치. 환경변수로 바꿀 수 있어 테스트가 사용자 홈을 건드리지 않는다."""
    override = os.environ.get("EXPENSE_REVIEW_HOME")
    base = Path(override) if override else Path.home() / APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def _overrides_path() -> Path:
    return config_dir() / "rule-overrides.yaml"


def _settings_path() -> Path:
    return config_dir() / "settings.json"


# ── 규칙 오버라이드 ───────────────────────────────────────────────────────

def load_overrides() -> dict[str, Any]:
    """{'rules': {규칙ID: {필드: 값}}, 'settings': {지출종류: {키: 값}}}"""
    path = _overrides_path()
    if not path.exists():
        return {"rules": {}, "settings": {}}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {"rules": {}, "settings": {}}
    data.setdefault("rules", {})
    data.setdefault("settings", {})
    return data


def save_overrides(data: dict[str, Any]) -> None:
    _overrides_path().write_text(
        "# 앱에서 고친 검토 기준입니다. 업데이트를 받아도 이 파일은 유지됩니다.\n"
        "# 되돌리려면 해당 항목을 지우거나 앱에서 '기본값으로' 를 누르세요.\n\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def set_rule_override(rule_id: str, field: str, value: Any) -> None:
    if field not in EDITABLE_RULE_FIELDS:
        raise ValueError(f"편집할 수 없는 항목입니다: {field}")
    data = load_overrides()
    data["rules"].setdefault(rule_id, {})[field] = value
    save_overrides(data)


def clear_rule_override(rule_id: str) -> None:
    data = load_overrides()
    data["rules"].pop(rule_id, None)
    save_overrides(data)


def set_setting_override(expense_type: str, key: str, value: Any) -> None:
    data = load_overrides()
    data["settings"].setdefault(expense_type, {})[key] = value
    save_overrides(data)


def clear_setting_override(expense_type: str, key: str) -> None:
    data = load_overrides()
    if expense_type in data["settings"]:
        data["settings"][expense_type].pop(key, None)
    save_overrides(data)


# ── 앱 설정 ───────────────────────────────────────────────────────────────

DEFAULT_SETTINGS: dict[str, Any] = {
    "auto_update_check": True,     # 시작할 때 새 버전이 있는지 확인
    "auto_update_apply": False,    # 확인만 하고, 적용은 사용자가 누른다
    "last_folder": "",
    "theme": "y2k",                # y2k | galaxy | cozy | studio
    "sheet_url": "",               # 기준값 구글시트 (링크 공유 또는 웹 게시)
    "sheet_log_url": "",           # 검토 기록 Apps Script 웹훅
    "sheet_log_enabled": False,    # 검토 후 요약을 기록 시트로 전송
}


def load_settings() -> dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(DEFAULT_SETTINGS)
    return {**DEFAULT_SETTINGS, **stored}


def save_settings(settings: dict[str, Any]) -> None:
    _settings_path().write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def update_setting(key: str, value: Any) -> dict[str, Any]:
    settings = load_settings()
    settings[key] = value
    save_settings(settings)
    return settings
