"""사용자 오버라이드 테스트.

핵심 요구: 앱에서 고친 기준이 **배포본 YAML 을 건드리지 않아야** 한다.
그래야 자동 업데이트(git pull)와 충돌하지 않는다.
"""
from __future__ import annotations

import pytest

from expense_review import config
from expense_review.engine import RULES_DIR, load_ruleset
from expense_review.models import Severity


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """사용자 홈 대신 임시 폴더를 쓴다."""
    monkeypatch.setenv("EXPENSE_REVIEW_HOME", str(tmp_path / "home"))
    yield


def _rule(expense_type: str, rule_id: str):
    return {rule.id: rule for rule in load_ruleset(expense_type).rules}[rule_id]


def test_override_changes_severity_without_touching_shipped_yaml():
    shipped = (RULES_DIR / "travel.yaml").read_text(encoding="utf-8")
    assert _rule("출장비", "R-TRV-008").severity is Severity.WARN

    config.set_rule_override("R-TRV-008", "severity", "ERROR")

    assert _rule("출장비", "R-TRV-008").severity is Severity.ERROR
    assert (RULES_DIR / "travel.yaml").read_text(encoding="utf-8") == shipped


def test_override_marks_which_fields_were_edited():
    config.set_rule_override("R-TRV-008", "message", "직접 고친 문구")
    rule = _rule("출장비", "R-TRV-008")
    assert rule.message == "직접 고친 문구"
    assert "message" in rule.overridden


def test_clearing_override_restores_shipped_default():
    original = _rule("출장비", "R-TRV-008").message
    config.set_rule_override("R-TRV-008", "message", "임시 문구")
    config.clear_rule_override("R-TRV-008")
    assert _rule("출장비", "R-TRV-008").message == original


def test_disabling_a_rule_is_honoured():
    config.set_rule_override("R-TRV-008", "enabled", False)
    assert _rule("출장비", "R-TRV-008").enabled is False


def test_setting_a_limit_enables_the_rule_that_needed_it():
    """규정값이 없어 꺼져 있던 L3 규칙은 값을 넣으면 켜져야 한다."""
    from expense_review.engine import _is_enabled

    ruleset = load_ruleset("출장비")
    rule = {r.id: r for r in ruleset.rules}["R-TRV-027"]      # 자가용 여비 산정
    assert ruleset.settings["km_rate"] is None
    assert not _is_enabled(rule, ruleset.settings)

    config.set_setting_override("출장비", "km_rate", 300)

    ruleset = load_ruleset("출장비")
    assert ruleset.settings["km_rate"] == 300
    assert _is_enabled({r.id: r for r in ruleset.rules}["R-TRV-027"], ruleset.settings)


def test_only_whitelisted_fields_can_be_overridden():
    """판정 로직에 해당하는 항목은 앱에서 바꿀 수 없어야 한다."""
    with pytest.raises(ValueError):
        config.set_rule_override("R-TRV-008", "expr", "1 == 1")


def test_settings_roundtrip():
    config.update_setting("auto_update_check", False)
    assert config.load_settings()["auto_update_check"] is False
    config.update_setting("auto_update_check", True)
    assert config.load_settings()["auto_update_check"] is True
