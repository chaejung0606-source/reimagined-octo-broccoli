#!/usr/bin/env python3
"""rules/*.yaml 규칙 정의 검증.

규칙 파일은 담당자가 직접 손대는 것을 전제로 하므로, 문법·필수항목·ID 중복을
저장 시점에 걸러 준다. 실행: python3 tools/validate_rules.py
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

REQUIRED_KEYS = ("id", "layer", "title", "severity", "message", "fix")
LAYERS = ("L0", "L1", "L2", "L3")
SEVERITIES = ("ERROR", "WARN", "REVIEW", "INFO")
EXPENSE_TYPES = ("근로장학금", "혁신인재지원금", "출장비")
SUBTYPES = ("TA", "SUPPORTERS")

try:                                    # 앱이 있으면 검사기 이름과 표현식까지 검증한다
    from app.checks import CHECKS
    from app.engine import SCOPE_SOURCES
    from app.expr import ExprError, parse
except Exception:                       # 규칙만 손볼 때는 앱 없이도 돌아가야 한다
    CHECKS = None
    SCOPE_SOURCES = None
    parse = None
    ExprError = Exception


def validate(path: Path, errors: list[str]) -> Counter:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = doc.get("rules") or []
    seen: set[str] = set()

    for rule in rules:
        rid = rule.get("id", "<id 없음>")
        for key in REQUIRED_KEYS:
            if not rule.get(key):
                errors.append(f"{path.name} :: {rid} :: '{key}' 누락")
        if rid in seen:
            errors.append(f"{path.name} :: {rid} :: ID 중복")
        seen.add(rid)
        if rule.get("layer") not in LAYERS:
            errors.append(f"{path.name} :: {rid} :: layer '{rule.get('layer')}' 은 {LAYERS} 중 하나여야 함")
        if rule.get("severity") not in SEVERITIES:
            errors.append(f"{path.name} :: {rid} :: severity '{rule.get('severity')}' 은 {SEVERITIES} 중 하나여야 함")
        # 판정 방법은 expr(표현식) 또는 check(내장 검사기) 중 하나로 반드시 지정한다.
        if not (rule.get("expr") or rule.get("check")):
            errors.append(f"{path.name} :: {rid} :: expr 또는 check 가 필요함")

        for expense_type in rule.get("applies_to") or []:
            if expense_type not in EXPENSE_TYPES:
                errors.append(f"{path.name} :: {rid} :: applies_to '{expense_type}' 은 "
                              f"{EXPENSE_TYPES} 중 하나여야 함")
        for subtype in rule.get("only_subtypes") or []:
            if subtype not in SUBTYPES:
                errors.append(f"{path.name} :: {rid} :: only_subtypes '{subtype}' 은 "
                              f"{SUBTYPES} 중 하나여야 함")

        # 아래는 앱이 함께 있을 때만. 규칙 파일이 앱보다 앞서 나가는 걸 막는다.
        check = rule.get("check")
        if check and CHECKS is not None and check not in CHECKS:
            errors.append(f"{path.name} :: {rid} :: '{check}' 검사기가 구현되어 있지 않음 "
                          f"(app/checks.py 에 @register('{check}') 필요)")

        scope = rule.get("scope")
        if scope and SCOPE_SOURCES is not None and scope not in SCOPE_SOURCES and scope != "batch":
            errors.append(f"{path.name} :: {rid} :: scope '{scope}' 을 엔진이 모릅니다 "
                          f"(가능: {', '.join(SCOPE_SOURCES)}, batch)")

        for key in ("expr", "enabled_if"):
            source = rule.get(key)
            if source and parse is not None:
                try:
                    parse(source)
                except ExprError as exc:
                    errors.append(f"{path.name} :: {rid} :: {key} 문법 오류 — {exc}")

    return Counter(r.get("layer") for r in rules)


def main() -> int:
    errors: list[str] = []
    total = Counter()

    for path in sorted(RULES_DIR.glob("*.yaml")):
        counts = validate(path, errors)
        total += counts
        n = sum(counts.values())
        layers = "  ".join(f"{lv}={counts[lv]}" for lv in LAYERS)
        print(f"{path.name:22} {n:3}건   {layers}")

    print(f"{'합계':20} {sum(total.values()):3}건   " + "  ".join(f"{lv}={total[lv]}" for lv in LAYERS))

    if errors:
        print("\n검증 실패:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    print("\n검증 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
