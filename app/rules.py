"""규칙 로더 — `rules/*.yaml` 를 읽어 지출종류별 규칙 묶음을 만든다.

규칙은 코드가 아니라 데이터다. 담당자가 YAML 을 직접 고쳐 지침 개정을 따라갈 수 있어야
하므로, 로더는 없는 키를 관대하게 넘기고 값 검증은 `tools/validate_rules.py` 에 맡긴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

import yaml

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

#: 지출종류 → 전용 규칙 파일
RULE_FILES = {
    "근로장학금": "scholarship.yaml",
    "혁신인재지원금": "innovation.yaml",
    "출장비": "travel.yaml",
}

COMMON_FILE = "common.yaml"


@dataclass(frozen=True)
class RequiredDocument:
    key: str
    label: str
    optional: bool = False
    provided_by: str = ""      # `staff` = 사업단이 작성하는 서류 (제출자 책임 아님)
    once_only: bool = False


@dataclass
class Rule:
    id: str
    layer: str
    title: str
    severity: str
    message: str = ""
    fix: str = ""
    expr: str | None = None
    check: str | None = None
    params: dict[str, Any] = dc_field(default_factory=dict)
    requires: list[str] = dc_field(default_factory=list)
    scope: str = ""                  # each_row / each_receipt / each_member / each_stay_page / batch
    enabled: bool = True
    enabled_if: str | None = None
    applies_to: list[str] = dc_field(default_factory=list)
    only_subtypes: list[str] = dc_field(default_factory=list)
    source_file: str = ""

    @property
    def is_check(self) -> bool:
        return bool(self.check)


@dataclass
class RuleSet:
    expense_type: str
    subtype: str | None
    rules: list[Rule]
    settings: dict[str, Any]
    required_documents: list[RequiredDocument]
    subtype_label: str = ""

    def by_id(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"규칙 파일이 없습니다: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"규칙 파일 형식이 올바르지 않습니다: {path}")
    return data


def _to_rule(raw: dict[str, Any], source_file: str) -> Rule:
    return Rule(
        id=str(raw.get("id", "")),
        layer=str(raw.get("layer", "")),
        title=str(raw.get("title", "")),
        severity=str(raw.get("severity", "WARN")).upper(),
        message=str(raw.get("message", "")),
        fix=str(raw.get("fix", "")),
        expr=raw.get("expr"),
        check=raw.get("check"),
        params=dict(raw.get("params") or {}),
        requires=[str(r) for r in (raw.get("requires") or [])],
        scope=str(raw.get("scope", "")),
        enabled=bool(raw.get("enabled", True)),
        enabled_if=raw.get("enabled_if"),
        applies_to=[str(a) for a in (raw.get("applies_to") or [])],
        only_subtypes=[str(s) for s in (raw.get("only_subtypes") or [])],
        source_file=source_file,
    )


def _to_required(raw: dict[str, Any]) -> RequiredDocument:
    return RequiredDocument(
        key=str(raw.get("key", "")),
        label=str(raw.get("label", raw.get("key", ""))),
        optional=bool(raw.get("optional", False)),
        provided_by=str(raw.get("provided_by", "")),
        once_only=bool(raw.get("once_only", False)),
    )


def load_ruleset(expense_type: str, subtype: str | None = None,
                 overrides: dict[str, Any] | None = None,
                 rules_dir: Path | None = None) -> RuleSet:
    """공통 규칙 + 지출종류 전용 규칙을 합쳐 돌려준다.

    ``overrides`` 는 지침 수치(한도·단가 등)를 바깥에서 주입하는 통로다.
    L3 규칙은 이 값이 채워져야 `enabled_if` 를 통과한다.
    """
    directory = rules_dir or RULES_DIR
    if expense_type not in RULE_FILES:
        raise ValueError(f"알 수 없는 지출종류입니다: {expense_type}")

    common = _load_yaml(directory / COMMON_FILE)
    specific = _load_yaml(directory / RULE_FILES[expense_type])

    rules: list[Rule] = [_to_rule(r, COMMON_FILE) for r in (common.get("rules") or [])]
    rules += [_to_rule(r, RULE_FILES[expense_type]) for r in (specific.get("rules") or [])]

    # `applies_to` 가 있으면 해당 지출종류에만 적용한다.
    rules = [r for r in rules if not r.applies_to or expense_type in r.applies_to]
    # `only_subtypes` 는 하위 유형 전용 규칙. TA 에는 근무일지(서포터즈 서류)가 아예
    # 없으므로, 이 구분이 없으면 없는 서류를 찾다가 🔵 판독 불가만 잔뜩 쌓인다.
    if subtype is not None:
        rules = [r for r in rules if not r.only_subtypes or subtype in r.only_subtypes]

    settings: dict[str, Any] = {}
    settings.update(common.get("settings") or {})
    settings.update(specific.get("settings") or {})

    required_raw = specific.get("required_documents") or []
    subtype_label = ""
    subtypes = specific.get("subtypes") or {}
    if subtypes:
        if subtype is None:
            raise ValueError(
                f"{expense_type} 은 하위 유형이 필요합니다: {', '.join(subtypes)}"
            )
        if subtype not in subtypes:
            raise ValueError(
                f"알 수 없는 하위 유형입니다: {subtype} (가능: {', '.join(subtypes)})"
            )
        block = subtypes[subtype] or {}
        subtype_label = str(block.get("label", subtype))
        required_raw = block.get("required_documents") or required_raw
        settings.update(block.get("settings") or {})

    if overrides:
        settings.update({k: v for k, v in overrides.items() if v is not None})

    return RuleSet(
        expense_type=expense_type,
        subtype=subtype,
        rules=rules,
        settings=settings,
        required_documents=[_to_required(r) for r in required_raw],
        subtype_label=subtype_label,
    )


def load_settings_file(path: Path) -> dict[str, Any]:
    """지침 수치를 담은 별도 YAML(예: `강원대 여비규정.yaml`)을 읽는다."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"설정 파일 형식이 올바르지 않습니다: {path}")
    return data.get("settings", data)
