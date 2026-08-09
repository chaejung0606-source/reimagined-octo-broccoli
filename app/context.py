"""규칙 평가에 필요한 문맥과 내장 검사기의 반환 형식."""
from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from typing import Any

from .fields import FieldIndex
from .models import Case, Namespace, Source, Status
from .rules import RuleSet


@dataclass
class RuleContext:
    """규칙 하나를 평가할 때 쓰는 모든 것."""

    case: Case
    ruleset: RuleSet
    index: FieldIndex
    base_scope: dict[str, Any] = dc_field(default_factory=dict)

    def scope(self, locals_: dict[str, Any] | None = None) -> dict[str, Any]:
        scope = dict(self.base_scope)
        if locals_:
            scope.update(locals_)
        return scope

    @property
    def settings(self) -> dict[str, Any]:
        return self.ruleset.settings

    def setting(self, name: str, default: Any = None) -> Any:
        return self.ruleset.settings.get(name, default)

    def param(self, params: dict[str, Any], name: str, default: Any = None) -> Any:
        """규칙 params 값을 읽는다. `settings.xxx` 참조는 설정값으로 바꿔 준다."""
        value = params.get(name, default)
        if isinstance(value, str) and value.startswith("settings."):
            return self.setting(value.split(".", 1)[1], default)
        return value


@dataclass
class CheckResult:
    """내장 검사기 하나의 판정.

    ``ok=False`` 면 규칙에 적힌 severity 로 올라가고, ``status`` 를 지정하면 그것이 이긴다.
    ``extras`` 는 message/fix 템플릿의 `{missing}` `{values}` 같은 자리를 채운다.
    """

    ok: bool
    extras: dict[str, Any] = dc_field(default_factory=dict)
    anchors: list[Source] = dc_field(default_factory=list)
    evidence: list[str] = dc_field(default_factory=list)
    label: str = ""
    status: Status | None = None
    reason: str = ""


def unsupported(reason: str) -> CheckResult:
    """이 단계에서 판정할 수 없는 검사 (OCR·Vision·묶음 모드 필요)."""
    return CheckResult(ok=False, status=Status.UNSUPPORTED, reason=reason)


def review(reason: str, evidence: list[str] | None = None,
           anchors: list[Source] | None = None) -> CheckResult:
    """판정 보류 — 사람이 직접 대조해야 한다."""
    return CheckResult(ok=False, status=Status.REVIEW, reason=reason,
                       evidence=evidence or [], anchors=anchors or [])


def ok(**extras: Any) -> CheckResult:
    return CheckResult(ok=True, extras=extras)


def failed(evidence: list[str] | None = None, anchors: list[Source] | None = None,
           label: str = "", **extras: Any) -> CheckResult:
    return CheckResult(ok=False, extras=extras, evidence=evidence or [],
                       anchors=anchors or [], label=label)


def as_namespace(value: Any) -> Namespace | None:
    return value if isinstance(value, Namespace) else None
