"""규칙 엔진.

규칙의 메타데이터(제목·등급·문구·설정값)는 rules/*.yaml 에 있고, 판정 로직은
checks/ 에 규칙 ID로 등록된 함수가 담당한다. 담당자는 YAML 만 고쳐도
등급·문구·한도를 바꿀 수 있고, 새 규칙을 켜고 끌 수 있다.

신뢰도 처리가 이 엔진의 핵심이다. 검사 함수가 `ctx.require()` 로 필드를 꺼낼 때
값이 없거나 신뢰도가 낮으면 NeedsReview 가 올라오고, 엔진은 판정 대신
REVIEW(판독 불가)를 남긴다. 손글씨·스캔 서류에서 오탐이 쏟아지지 않게 하는 장치다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

from .config import load_overrides
from .models import (
    CONFIDENCE_THRESHOLD,
    Document,
    DocumentSet,
    Finding,
    ReviewResult,
    Severity,
    Source,
    Value,
)

RULES_DIR = Path(__file__).resolve().parent.parent.parent / "rules"

# 지출종류 → 전용 규칙 파일
RULE_FILES = {
    "근로장학금": "scholarship.yaml",
    "혁신인재지원금": "innovation.yaml",
    "출장비": "travel.yaml",
}


class NotApplicable(Exception):
    """이 지출종류·하위유형에는 해당하지 않는 규칙. 결과에 남기지 않는다."""


class NeedsReview(Exception):
    """판정에 필요한 값을 믿을 수 없다. 사람이 확인해야 한다."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Rule:
    id: str
    layer: str
    title: str
    severity: Severity
    message: str
    fix: str
    scope: str = "document_set"
    enabled: bool = True
    enabled_if: str | None = None
    params: dict = field(default_factory=dict)
    overridden: tuple[str, ...] = ()      # 사용자가 앱에서 고친 항목

    def apply_override(self, values: dict) -> None:
        """사용자 오버라이드를 얹는다. 판정 로직은 코드에 있으므로 건드리지 않는다."""
        changed = []
        for key, value in values.items():
            if key == "severity":
                self.severity = Severity(value)
            elif key in ("enabled", "message", "fix", "title"):
                setattr(self, key, value)
            else:
                continue
            changed.append(key)
        self.overridden = tuple(changed)

    @classmethod
    def from_yaml(cls, data: dict) -> "Rule":
        return cls(
            id=data["id"],
            layer=data.get("layer", "L1"),
            title=data.get("title", ""),
            severity=Severity(data.get("severity", "WARN")),
            message=data.get("message", ""),
            fix=data.get("fix", ""),
            scope=data.get("scope", "document_set"),
            enabled_if=data.get("enabled_if"),
            params=data.get("params") or {},
        )


@dataclass
class RuleSet:
    rules: list[Rule]
    settings: dict[str, Any]
    required_documents: list[dict]
    subtypes: dict[str, Any]


def load_ruleset(expense_type: str, subtype: str | None = None,
                 apply_overrides: bool = True) -> RuleSet:
    """공통 규칙 + 지출종류 전용 규칙을 합쳐 돌려준다.

    배포본 YAML 위에 사용자가 앱에서 고친 값을 덮어 얹는다. 배포본 파일 자체는
    건드리지 않으므로 자동 업데이트와 충돌하지 않는다(config.py 참고).
    """
    rules: list[Rule] = []
    settings: dict[str, Any] = {}
    required: list[dict] = []
    subtypes: dict[str, Any] = {}

    for filename in ("common.yaml", RULE_FILES[expense_type]):
        data = yaml.safe_load((RULES_DIR / filename).read_text(encoding="utf-8"))
        rules.extend(Rule.from_yaml(item) for item in data.get("rules", []))
        settings.update(data.get("settings") or {})
        required.extend(data.get("required_documents") or [])
        subtypes.update(data.get("subtypes") or {})

    if subtype and subtype in subtypes:
        required.extend(subtypes[subtype].get("required_documents") or [])

    if apply_overrides:
        # 우선순위: 배포본 < 구글시트(팀 공용, 캐시만 읽음) < 앱에서 직접 수정(개인)
        from . import sheets

        sheet = sheets.cached_overrides()
        local = load_overrides()
        for rule in rules:
            merged = {**sheet["rules"].get(rule.id, {}), **local["rules"].get(rule.id, {})}
            rule.apply_override(merged)
        settings.update(sheet["settings"].get(expense_type, {}))
        settings.update(local["settings"].get(expense_type, {}))

    return RuleSet(rules=rules, settings=settings, required_documents=required, subtypes=subtypes)


# ── 검사 함수 등록 ────────────────────────────────────────────────────────

CheckFn = Callable[["Context"], Any]
CHECKS: dict[str, CheckFn] = {}


def check(rule_id: str) -> Callable[[CheckFn], CheckFn]:
    def register(func: CheckFn) -> CheckFn:
        CHECKS[rule_id] = func
        return func

    return register


@dataclass
class Fail:
    """검사 실패 1건. params 는 message/fix 템플릿에 채워진다."""

    params: dict = field(default_factory=dict)
    sources: list[Source] = field(default_factory=list)


# ── 검사 컨텍스트 ─────────────────────────────────────────────────────────

class Context:
    """검사 함수가 문서 집합을 다루는 창구."""

    def __init__(self, document_set: DocumentSet, settings: dict[str, Any]):
        self.docs = document_set
        self.settings = settings

    # -- 필드 접근 --------------------------------------------------------
    def value(self, path: str) -> Value | None:
        return self.docs.get(path)

    def get(self, path: str, default: Any = None) -> Any:
        found = self.docs.get(path)
        return found.value if found is not None and found.is_present else default

    def require(self, *paths: str) -> Any:
        """값을 꺼내되, 없거나 신뢰도가 낮으면 REVIEW 로 넘긴다."""
        results = []
        for path in paths:
            found = self.docs.get(path)
            if found is None or not found.is_present:
                raise NeedsReview(f"'{self._label(path)}' 값을 찾지 못했습니다")
            if found.confidence < CONFIDENCE_THRESHOLD:
                raise NeedsReview(f"'{self._label(path)}' 의 판독 신뢰도가 낮습니다")
            results.append(found.value)
        return results[0] if len(results) == 1 else tuple(results)

    def number_setting(self, name: str, default: Any = None) -> float:
        """숫자 설정값. 담당자가 화면에서 직접 입력하는 값이라 검증하고 꺼낸다.

        '삼십' 처럼 숫자가 아닌 값이 들어오면 판정하지 않고 REVIEW 로 넘긴다.
        그대로 int() 에 넘기면 '검사 중 오류' 만 남아 무엇이 문제인지 알 수 없다.
        """
        raw = self.settings.get(name, default)
        if isinstance(raw, bool) or raw is None:
            raise NeedsReview(f"기준값 '{name}' 이 설정되어 있지 않습니다")
        try:
            return float(raw)
        except (TypeError, ValueError):
            raise NeedsReview(f"기준값 '{name}' 에 숫자가 아닌 값이 들어 있습니다: {raw}")

    def requires_doc(self, doc_type: str) -> bool:
        """이 지출종류(하위유형 포함)가 요구하는 서류인지."""
        return any(item["key"] == doc_type for item in getattr(self, "required_documents", []))

    def has_doc(self, *doc_types: str) -> bool:
        return bool(self.docs.available_types & set(doc_types))

    def doc(self, doc_type: str) -> Document | None:
        return self.docs.first(doc_type)

    def sources(self, *paths: str) -> list[Source]:
        found = []
        for path in paths:
            value = self.docs.get(path)
            if value is not None and value.source is not None:
                found.append(value.source)
        return found

    @staticmethod
    def _label(path: str) -> str:
        from .classify import DOC_LABELS

        doc_type, _, field_name = path.partition(".")
        return f"{DOC_LABELS.get(doc_type, doc_type)}의 {field_name}"


# ── 문구 포매팅 ───────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"\{([^{}]+)\}")


def format_template(template: str, context: Context, params: dict) -> str:
    """'{trip_evidence.dist_total}' 같은 점 표기 토큰을 실제 값으로 채운다."""

    def replace(match: re.Match) -> str:
        token = match.group(1).strip()
        if token in params:
            return _render(params[token])
        if "." in token:
            value = context.value(token)
            if value is not None:
                return str(value)
        if token.startswith("settings."):
            return _render(context.settings.get(token.split(".", 1)[1]))
        return "(없음)"

    return _TOKEN_RE.sub(replace, template)


def _render(value: Any) -> str:
    if value is None:
        return "(없음)"
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_render(item) for item in value)
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


# ── 실행 ──────────────────────────────────────────────────────────────────

def evaluate(document_set: DocumentSet, ruleset: RuleSet) -> ReviewResult:
    settings = {**ruleset.settings, **document_set.settings}
    context = Context(document_set, settings)
    context.required_documents = ruleset.required_documents  # type: ignore[attr-defined]
    context.subtype = document_set.subtype  # type: ignore[attr-defined]

    result = ReviewResult(
        expense_type=document_set.expense_type,
        owner=document_set.owner,
        documents=list(document_set.documents),
    )

    for rule in ruleset.rules:
        if not _is_enabled(rule, settings):
            result.skipped_rules.append(f"{rule.id} (규정값 미설정)")
            continue

        checker = CHECKS.get(rule.id)
        if checker is None:
            result.skipped_rules.append(f"{rule.id} (미구현)")
            continue

        try:
            outcome = checker(context)
        except NotApplicable:
            result.skipped_rules.append(f"{rule.id} (해당 없음)")
            continue
        except NeedsReview as exc:
            result.findings.append(_finding(rule, context, Severity.REVIEW, {"reason": exc.reason}))
            continue
        except Exception as exc:  # 한 규칙의 오류가 전체 검토를 막지 않게 한다
            result.findings.append(
                _finding(rule, context, Severity.REVIEW, {"reason": f"검사 중 오류: {exc}"})
            )
            continue

        for failure in _as_failures(outcome):
            result.findings.append(
                _finding(rule, context, rule.severity, failure.params, failure.sources)
            )

    for document in document_set.documents:
        for note in document.notes:
            result.findings.append(
                Finding(
                    rule_id="-", title="추출 안내", severity=Severity.REVIEW, layer="L1",
                    message=f"{document.name}: {note}", fix="", sources=[document.source()],
                    owner=document_set.owner,
                )
            )

    return result


def _as_failures(outcome: Any) -> Iterable[Fail]:
    if outcome is None:
        return []
    if isinstance(outcome, Fail):
        return [outcome]
    if isinstance(outcome, dict):
        return [Fail(outcome)]
    if isinstance(outcome, (list, tuple)):
        found = []
        for item in outcome:
            found.extend(_as_failures(item))
        return found
    return []


def _finding(rule: Rule, context: Context, severity: Severity,
             params: dict, sources: list[Source] | None = None) -> Finding:
    if severity is Severity.REVIEW:
        message = f"{rule.title} — 판정 보류: {params.get('reason', '값을 확인할 수 없습니다')}"
        fix = "해당 항목을 원본에서 직접 확인해 주세요."
    else:
        message = format_template(rule.message, context, params)
        fix = format_template(rule.fix, context, params)

    return Finding(
        rule_id=rule.id, title=rule.title, severity=severity, layer=rule.layer,
        message=message, fix=fix, sources=sources or [], owner=context.docs.owner,
    )


def _is_enabled(rule: Rule, settings: dict[str, Any]) -> bool:
    """`enabled_if: "settings.max_hours_per_day != null"` 같은 단순 조건만 지원한다."""
    if not rule.enabled:
        return False
    if not rule.enabled_if:
        return True

    match = re.fullmatch(r"settings\.(\w+)\s*(!=|==)\s*(null|true|false)", rule.enabled_if.strip())
    if not match:
        return True  # 해석할 수 없는 조건은 켜 둔다
    name, operator, literal = match.groups()
    actual = settings.get(name)
    expected = {"null": None, "true": True, "false": False}[literal]
    return (actual != expected) if operator == "!=" else (actual == expected)
