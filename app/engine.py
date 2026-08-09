"""규칙 엔진 — docs/04-architecture.md §4.

    for rule in rules(expense_type):
        if not enabled: continue
        vals = resolve(rule.requires)
        if any(v.confidence < 0.85): → REVIEW (판독 불가)
        ok, computed = evaluate(rule, vals)
        if not ok: → Finding(severity, message, fix, anchors)

세 가지를 지키는 것이 이 엔진의 전부다.

1. **못 읽은 값으로 판정하지 않는다.** 미추출·저신뢰면 🔵 판독 불가로 올린다.
2. **공란은 판정한다.** 칸을 찾았는데 비어 있는 것은 위반이다 (총 이동경로 공란).
3. **정답을 계산해 둔다.** `fix` 가 "412km 를 기재하세요" 라고 말할 수 있어야 한다.
"""
from __future__ import annotations

import ast
import re
from typing import Any, Iterable

from . import expr as expr_mod
from . import privacy
from .checks import CHECKS
from .context import CheckResult, RuleContext
from .extract import extract_case
from .fields import FieldIndex
from .models import (
    MISSING,
    Case,
    Confidence,
    Field,
    Finding,
    Namespace,
    ReviewResult,
    Source,
    Status,
    format_value,
)
from .rules import Rule, RuleSet, load_ruleset

#: `scope:` → (지역 변수 이름, 기본 목록 경로들)
SCOPE_SOURCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "each_row": ("row", ("worklog.rows", "attach1_worklog.rows", "worklog_handwrite.rows")),
    "each_receipt": ("receipt", ("receipts",)),
    "each_member": ("member", ("form7_1_report.members",)),
    "each_stay_page": ("stay", ("trip_evidence.stay_dates",)),
}

#: 필드 색인이 아니라 문맥에서 오는 이름들
_CONTEXT_ROOTS = {"settings", "subtype", "expense_type", "params"}

#: 이 단계에서 아직 만들지 않는 값들. '못 읽었다'(🔵)가 아니라 '아직 안 본다'(⚪)다.
_LATER_PHASE_ROOTS = {
    "claim": "여비 산정 결과(claim.*)는 담당자 입력 항목입니다 — 5단계에서 다룹니다",
}

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")


# ------------------------------------------------------------------ 진입점

def review_case(case: Case, overrides: dict[str, Any] | None = None,
                mask_level: str = "basic") -> ReviewResult:
    """검토 건 하나를 끝까지 돌린다."""
    ruleset = load_ruleset(case.expense_type, case.subtype, overrides)
    index = extract_case(case)
    ctx = RuleContext(case=case, ruleset=ruleset, index=index,
                      base_scope=_base_scope(case, ruleset, index))

    findings: list[Finding] = []
    for rule in ruleset.rules:
        findings.extend(evaluate_rule(rule, ctx))

    if mask_level != "off":
        for finding in findings:
            _mask_finding(finding, mask_level)
    return ReviewResult(case=case, findings=findings)


def _base_scope(case: Case, ruleset: RuleSet, index: FieldIndex) -> dict[str, Any]:
    return index.scope({
        "settings": Namespace(ruleset.settings, label="settings"),
        "subtype": case.subtype,
        "expense_type": case.expense_type,
    })


def _mask_finding(finding: Finding, level: str) -> None:
    finding.message = privacy.mask(finding.message, level)
    finding.fix = privacy.mask(finding.fix, level)
    finding.evidence = [privacy.mask(item, level) for item in finding.evidence]
    finding.reason = privacy.mask(finding.reason, level)


# --------------------------------------------------------------- 규칙 평가

def evaluate_rule(rule: Rule, ctx: RuleContext) -> list[Finding]:
    if not rule.enabled:
        return [_finding(rule, ctx, Status.SKIPPED, reason="규칙이 비활성 상태입니다")]

    disabled = _enabled_if_reason(rule, ctx)
    if disabled is not None:
        return [_finding(rule, ctx, Status.SKIPPED, reason=disabled)]

    if rule.is_check:
        return _evaluate_check(rule, ctx)
    if rule.expr:
        return _evaluate_expr(rule, ctx)
    return [_finding(rule, ctx, Status.SKIPPED, reason="expr 또는 check 가 없습니다")]


def _enabled_if_reason(rule: Rule, ctx: RuleContext) -> str | None:
    if not rule.enabled_if:
        return None
    try:
        if expr_mod.evaluate(rule.enabled_if, ctx.scope()):
            return None
    except (expr_mod.ExprError, expr_mod.MissingValueError):
        return f"활성 조건을 확인할 수 없습니다: {rule.enabled_if}"
    return "규정값이 설정되지 않아 검사하지 않았습니다 (지침 수치 입력 후 자동 활성화)"


# ---- check 기반 ------------------------------------------------------

def _evaluate_check(rule: Rule, ctx: RuleContext) -> list[Finding]:
    checker = CHECKS.get(rule.check or "")
    if checker is None:
        return [_finding(rule, ctx, Status.UNSUPPORTED,
                         reason=f"검사기 '{rule.check}' 가 아직 구현되지 않았습니다")]

    try:
        outcome = checker(ctx, rule)
    except Exception as exc:  # 검사기 하나가 죽어도 나머지 검토는 계속한다
        return [_finding(rule, ctx, Status.REVIEW,
                         reason=f"검사 중 오류가 발생했습니다: {exc}")]

    results = outcome if isinstance(outcome, list) else [outcome]
    findings: list[Finding] = []
    for result in results:
        findings.append(_finding_from_check(rule, ctx, result))
    return findings


def _finding_from_check(rule: Rule, ctx: RuleContext, result: CheckResult) -> Finding:
    if result.ok:
        return _finding(rule, ctx, Status.PASS, scope_label=result.label)

    status = result.status or _severity(rule)
    extras = dict(result.extras)
    extras.setdefault("reason", result.reason)
    scope = ctx.scope()

    if status in (Status.UNSUPPORTED, Status.SKIPPED):
        return _finding(rule, ctx, status, reason=result.reason,
                        evidence=result.evidence, anchors=result.anchors,
                        scope_label=result.label)
    if status is Status.REVIEW:
        return _finding(rule, ctx, status, reason=result.reason,
                        evidence=result.evidence, anchors=result.anchors,
                        scope_label=result.label)

    return _finding(
        rule, ctx, status,
        message=_render(rule.message, scope, extras),
        fix=_render(rule.fix, scope, extras),
        evidence=result.evidence,
        anchors=result.anchors,
        reason=result.reason,
        scope_label=result.label,
    )


# ---- expr 기반 -------------------------------------------------------

def _evaluate_expr(rule: Rule, ctx: RuleContext) -> list[Finding]:
    items = _scope_items(rule, ctx)
    if items is None:
        return [_finding(rule, ctx, Status.REVIEW,
                         reason=f"'{rule.scope}' 대상 목록을 읽지 못했습니다")]
    if rule.scope == "batch":
        return [_finding(rule, ctx, Status.UNSUPPORTED,
                         reason="묶음 모드(여러 사람 동시 검토)는 5단계 기능입니다")]

    findings: list[Finding] = []
    for local_name, item, label in items:
        locals_ = {local_name: item} if local_name else {}
        findings.append(_evaluate_once(rule, ctx, locals_, label))
    return _collapse(findings)


def _collapse(findings: list[Finding]) -> list[Finding]:
    """같은 사유로 반복된 🔵/🟢 결과를 한 줄로 접는다.

    영수증이 9건이면 `가맹점 소재지를 읽지 못했습니다` 가 9번 뜬다. 사람이 읽을
    수 없는 결과는 없는 것과 같으므로, 사유가 같으면 건수만 남긴다.
    (🔴/🟡 은 각각이 고쳐야 할 항목이므로 접지 않는다.)
    """
    if len(findings) <= 1:
        return findings

    collapsed: list[Finding] = []
    seen: dict[tuple[Status, str], Finding] = {}
    counts: dict[tuple[Status, str], int] = {}
    for finding in findings:
        if finding.status in (Status.ERROR, Status.WARN):
            collapsed.append(finding)
            continue
        key = (finding.status, finding.reason)
        counts[key] = counts.get(key, 0) + 1
        if key not in seen:
            seen[key] = finding
            collapsed.append(finding)

    for key, finding in seen.items():
        if counts[key] > 1:
            finding.scope_label = f"{counts[key]}건"
    return collapsed


def _evaluate_once(rule: Rule, ctx: RuleContext, locals_: dict[str, Any],
                   label: str) -> Finding:
    used, reason, status = _resolve_requires(rule, ctx, locals_)
    anchors = _dedupe(f.source for f in used if f.source)
    if reason is not None:
        return _finding(rule, ctx, status or Status.REVIEW, reason=reason,
                        anchors=anchors, scope_label=label)

    scope = _scope_with_aliases(rule, ctx, locals_)
    try:
        result = expr_mod.evaluate(rule.expr or "", scope)
    except expr_mod.MissingValueError as exc:
        return _finding(rule, ctx, Status.REVIEW, reason=str(exc),
                        anchors=anchors, scope_label=label)
    except expr_mod.ExprError as exc:
        return _finding(rule, ctx, Status.REVIEW,
                        reason=f"규칙을 평가하지 못했습니다: {exc}",
                        anchors=anchors, scope_label=label)

    if result:
        return _finding(rule, ctx, Status.PASS, scope_label=label)

    extras = _expr_extras(rule, scope)
    return _finding(
        rule, ctx, _severity(rule),
        message=_render(rule.message, scope, extras),
        fix=_render(rule.fix, scope, extras),
        evidence=_evidence(rule, ctx, used, locals_),
        anchors=anchors,
        scope_label=label,
    )


def _scope_with_aliases(rule: Rule, ctx: RuleContext,
                        locals_: dict[str, Any]) -> dict[str, Any]:
    """`requires` 에 적힌 필드의 마지막 조각을 짧은 이름으로도 쓸 수 있게 한다.

    R-TRV-008 의 `abs(dist_out - dist_back) / max(...)` 처럼 규칙 본문이 접두어를
    생략하고 쓰는 경우가 있다. requires 에 전체 경로가 있으니 그대로 이어 준다.
    """
    scope = ctx.scope(locals_)
    for path in rule.requires:
        base = path.split("[]")[0]
        leaf = base.rsplit(".", 1)[-1]
        if "." not in base or leaf in scope:
            continue
        field, reason = _lookup(ctx, base)
        if field is not None and reason is None:
            scope[leaf] = field.resolved
    return scope


def _scope_items(rule: Rule, ctx: RuleContext) -> list[tuple[str, Any, str]] | None:
    """반복 대상 목록. 반복이 없는 규칙은 한 번만 도는 목록을 돌려준다."""
    if rule.scope in ("", "batch"):
        return [("", None, "")]

    spec = SCOPE_SOURCES.get(rule.scope)
    if spec is None:
        return None
    local_name, default_paths = spec

    path = _scope_path_from_requires(rule) or _first_available(ctx, default_paths)
    if path is None:
        return None

    field = ctx.index.best(path)
    if field is None or field.is_missing:
        return None
    values = list(field.value or [])

    items: list[tuple[str, Any, str]] = []
    for value in values:
        if rule.scope == "each_stay_page" and not isinstance(value, Namespace):
            value = Namespace({"date": value}, label=format_value(value))
        label = value.label if isinstance(value, Namespace) and value.label else format_value(value)
        items.append((local_name, value, str(label)))
    return items


def _scope_path_from_requires(rule: Rule) -> str | None:
    """`worklog.rows[].hours` 같은 requires 에서 반복 대상 목록 경로를 읽는다."""
    for path in rule.requires:
        if "[]" in path:
            base = path.split("[]")[0]
            if "." in base:
                return base
    return None


def _first_available(ctx: RuleContext, paths: Iterable[str]) -> str | None:
    for path in paths:
        field = ctx.index.best(path)
        if field is not None and not field.is_missing:
            return path
    return None


# --------------------------------------------------------- requires 해석

def _resolve_requires(
    rule: Rule, ctx: RuleContext, locals_: dict[str, Any]
) -> tuple[list[Field], str | None, Status | None]:
    """필요한 값이 다 있는지 본다.

    하나라도 못 읽었거나 신뢰도가 임계값(0.85) 미만이면 판정하지 않고 🔵 로 올린다.
    **공란은 통과시킨다** — 칸이 비어 있다는 사실 자체가 규칙의 판정 대상이다.
    """
    used: list[Field] = []
    for path in rule.requires:
        base, _, key = path.partition("[].")
        root = base.split(".")[0]

        if root in locals_:
            reason = _check_local(locals_[root], base, key, path)
            if reason:
                return used, reason, None
            continue
        if root in _CONTEXT_ROOTS:
            continue
        if root in _LATER_PHASE_ROOTS:
            return used, _LATER_PHASE_ROOTS[root], Status.UNSUPPORTED

        field, reason = _lookup(ctx, base)
        if field is not None:
            used.append(field)
        if reason is not None:
            return used, reason, None
        assert field is not None
        if field.is_low_confidence:
            return used, (f"{_readable(base)} 의 판독 신뢰도가 낮습니다 "
                          f"({field.confidence:.2f} < {Confidence.THRESHOLD})"), None
        if key and rule.scope not in SCOPE_SOURCES:
            # 반복 규칙은 지금 보고 있는 행만 확인하면 된다. 여기서 전체 행을
            # 검사하면 행 하나가 비어도 규칙 전체가 🔵 로 덮인다.
            reason = _check_list_key(field, key, path)
            if reason:
                return used, reason, None
    return used, None, None


def _lookup(ctx: RuleContext, path: str) -> tuple[Field | None, str | None]:
    """색인에서 값을 찾는다. 없으면 상위 경로의 객체 속성으로 한 번 더 들어간다.

    `worklog.period.start` 는 평면 필드가 아니라 `worklog.period`(Period)의 속성이다.
    이 폴백이 없으면 멀쩡히 읽은 값을 '미추출' 로 오판한다.
    """
    field = ctx.index.best(path)
    if field is not None and not field.is_missing:
        return field, None
    if field is not None:
        return field, f"{_readable(path)} 을(를) 서류에서 읽지 못했습니다"

    parts = path.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        base = ctx.index.best(".".join(parts[:cut]))
        if base is None or base.is_missing:
            continue
        value: Any = base.value
        for attribute in parts[cut:]:
            try:
                value = expr_mod.safe_getattr(value, attribute)
            except expr_mod.ExprError:
                value = MISSING
                break
        if value is MISSING:
            return base, f"{_readable(path)} 을(를) 읽지 못했습니다"
        return base, None
    return None, f"{_readable(path)} 을(를) 서류에서 읽지 못했습니다"


def _check_local(item: Any, base: str, key: str, path: str) -> str | None:
    attribute = key or (base.split(".", 1)[1] if "." in base else "")
    if not attribute:
        return None
    value = item[attribute] if isinstance(item, Namespace) else getattr(item, attribute, MISSING)
    if value is MISSING:
        return f"{_readable(path)} 을(를) 읽지 못했습니다"
    return None


def _check_list_key(field: Field, key: str, path: str) -> str | None:
    values = field.value or []
    if not values:
        return f"{_readable(field.path)} 에 행이 없습니다"
    for item in values:
        value = item[key] if isinstance(item, Namespace) else None
        if value is MISSING:
            return f"{_readable(path)} 을(를) 읽지 못한 행이 있습니다"
    return None


_READABLE_NAMES = {
    "trip_evidence.dist_total": "총 이동경로",
    "trip_evidence.dist_out": "출발지→도착지 거리",
    "trip_evidence.dist_back": "도착지→출발지 거리",
    "trip_evidence.transport_amount": "교통비 증빙 금액",
    "trip_evidence.stay_dates": "체류 증빙 일자",
    "trip_evidence.map_distance": "지도 캡처 거리",
    "trip_request.period": "출장기간",
    "trip_request.trips": "출장 건",
    "trip_request.destination": "출장지",
    "trip_request.allowance_eligible": "여비지급대상여부",
    "worklog.total_hours": "총 근로시간",
    "worklog.rows": "근로일자 표",
    "worklog.period": "근로기간",
    "roster.amount": "지급내역 금액",
    "roster.hours": "지급내역 시간",
    "roster.unit_price": "지급내역 단가",
    "claim_form.amount": "청구금액",
    "person.rrn": "주민등록번호",
    "person.account_no": "계좌번호",
    "bankbook.holder": "통장 예금주",
    "bankbook.account_no": "통장 사본 계좌번호",
    "enrollment_cert.issued_at": "재학증명서 발급일",
    "submission.date": "서류 작성일",
    "period.start": "활동/출장 시작일",
    "period.end": "활동/출장 종료일",
    "worklog.period.start": "근로 시작일",
    "worklog.period.end": "근로 종료일",
    "form1_recommendation.operating_period": "강의 운영일",
    "form1_recommendation.professor": "담당교수",
    "worklog.approver": "근무상황부 확인자",
    "club.advisor": "지도교수",
    "club.name": "소학회명",
    "receipt.merchant_address": "영수증 가맹점 소재지",
    "receipt.datetime": "영수증 일시",
    "receipt.card_no": "영수증 카드번호",
    "receipt.items": "영수증 품목",
    "receipt.stated_total": "영수증 표기 총액",
    "transport_receipts": "교통비 영수증",
    "stay_receipts": "체류 영수증",
    "monthly_report.hours": "활동 결과 보고서 활동시간",
    "monthly_report.photos": "활동사진",
    "form8_application.amount": "신청서 지원금액",
    "form7_1_report.members": "팀원 명단",
}


def _readable(path: str) -> str:
    if path in _READABLE_NAMES:
        return f"{_READABLE_NAMES[path]}({path})"
    return path


# ------------------------------------------------------------ 메시지 조립

def _severity(rule: Rule) -> Status:
    try:
        return Status(rule.severity)
    except ValueError:
        return Status.WARN


def _expr_extras(rule: Rule, scope: dict[str, Any]) -> dict[str, Any]:
    """`{computed}` 와 집합 비교의 `{missing}` 을 채운다."""
    extras: dict[str, Any] = {}
    computed = expr_mod.compute(rule.expr or "", scope)
    if computed is not None:
        extras["computed"] = computed

    difference = _set_difference(rule.expr or "", scope)
    if difference is not None:
        extras["missing"] = difference
    return extras


def _set_difference(source: str, scope: dict[str, Any]) -> list[Any] | None:
    """`set(A) <= set(B)` 형태에서 B 에 없는 A 의 원소를 뽑는다.

    R-TRV-004(체류 증빙 누락일)와 R-INN-012(보고서에만 있는 활동일)가 이 형태다.
    """
    try:
        tree = ast.parse(expr_mod.preprocess(source), mode="eval")
    except SyntaxError:
        return None
    node = tree.body
    if not isinstance(node, ast.Compare) or len(node.ops) != 1:
        return None
    if not isinstance(node.ops[0], ast.LtE):
        return None
    try:
        left = expr_mod.evaluate(ast.unparse(node.left), scope)
        right = expr_mod.evaluate(ast.unparse(node.comparators[0]), scope)
    except (expr_mod.ExprError, expr_mod.MissingValueError):
        return None
    if not isinstance(left, (set, frozenset)) or not isinstance(right, (set, frozenset)):
        return None
    return sorted(left - right, key=str)


def _render(template: str, scope: dict[str, Any], extras: dict[str, Any]) -> str:
    """`{경로}` 자리를 채운다.

    extras 에 있으면 그것을, 없으면 표현식으로 평가한다. 둘 다 안 되면 `?` 로 둔다 —
    메시지 하나 때문에 검토 전체가 멈추면 안 된다.
    """
    if not template:
        return ""

    def replace(match: re.Match) -> str:
        name = match.group(1).strip()
        if name in extras:
            return format_value(extras[name])
        try:
            value = expr_mod.evaluate(name, scope)
        except (expr_mod.ExprError, expr_mod.MissingValueError):
            return "?"
        return format_value(None if value is MISSING else value)

    return _PLACEHOLDER_RE.sub(replace, template)


def _dedupe(sources: Iterable[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for source in sources:
        key = str(source)
        if key not in seen:
            seen.add(key)
            out.append(source)
    return out


def _evidence(rule: Rule, ctx: RuleContext, used: list[Field],
              locals_: dict[str, Any]) -> list[str]:
    """검출값 — 규칙이 실제로 본 값을 그대로 보여 준다."""
    lines: list[str] = []
    for field in used:
        line = f"{_readable(field.path)} = {field.display()}"
        if line not in lines:
            lines.append(line)
    for name, item in locals_.items():
        if isinstance(item, Namespace):
            lines.append(f"{name}: {item}")
    return lines


def _finding(rule: Rule, ctx: RuleContext, status: Status, *, message: str = "",
             fix: str = "", evidence: list[str] | None = None,
             anchors: list[Source] | None = None, reason: str = "",
             scope_label: str = "") -> Finding:
    return Finding(
        rule_id=rule.id,
        layer=rule.layer,
        title=rule.title,
        status=status,
        message=message or (rule.title if status in (Status.ERROR, Status.WARN) else ""),
        fix=fix,
        evidence=list(evidence or []),
        anchors=list(anchors or []),
        reason=reason,
        scope_label=scope_label,
    )
