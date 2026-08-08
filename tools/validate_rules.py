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

RULES_DIR = Path(__file__).resolve().parent.parent / "rules"

REQUIRED_KEYS = ("id", "layer", "title", "severity", "message", "fix")
LAYERS = ("L0", "L1", "L2", "L3")
SEVERITIES = ("ERROR", "WARN", "REVIEW", "INFO")


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
