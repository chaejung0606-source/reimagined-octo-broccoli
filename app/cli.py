"""명령줄 진입점.

    python -m app review 서류폴더 --type 출장비
    python -m app review 강옥일 --type 근로장학금 --subtype SUPPORTERS --format md
    python -m app classify 서류폴더 --type 혁신인재지원금
    python -m app dump 파일.pdf            # 추출된 원문 확인 (패턴 조정용)

GUI(PySide6)는 이 계층 위에 얹는다. 검토 로직은 전부 여기까지에서 끝나 있으므로
화면은 `review_case()` 결과를 그리기만 하면 된다.
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
from pathlib import Path

from . import EXPENSE_TYPES, SUBTYPES, __version__
from .classify import classify_all, needs_confirmation
from .engine import review_case
from .models import Case, Status
from .pdfio import collect_files, load_document_pages
from .privacy import LEVELS
from .report import (
    render_classification,
    render_json,
    render_markdown,
    render_text,
)
from .rules import load_ruleset, load_settings_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app",
        description="지출 서류 자동 검토 — 파일 분류 → L0 완비성 → L1 계산 → L2 교차 대사",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="진행 로그 출력")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("path", type=Path, help="서류 폴더 / 파일 / zip")
        p.add_argument("--type", dest="expense_type", required=True,
                       choices=EXPENSE_TYPES, help="지출종류")
        p.add_argument("--subtype", choices=("TA", "SUPPORTERS"),
                       help="근로장학금 하위 유형")

    review = sub.add_parser("review", help="서류를 검토하고 수정할 부분을 정리한다")
    add_common(review)
    review.add_argument("--settings", type=Path,
                        help="지침 수치 YAML (L3 한도 규칙 활성화)")
    review.add_argument("--format", dest="output_format", default="text",
                        choices=("text", "md", "json"))
    review.add_argument("--out", type=Path, help="결과를 파일로 저장")
    review.add_argument("--mask", default="basic", choices=LEVELS,
                        help="개인정보 마스킹 단계 (기본 basic)")
    review.add_argument("--show-pass", action="store_true", help="이상 없는 항목도 표시")
    review.add_argument("--person", default="", help="대상자 표시용 이름")

    classify = sub.add_parser("classify", help="파일이 무슨 서류인지만 판정한다")
    add_common(classify)

    dump = sub.add_parser("dump", help="추출된 원문을 그대로 출력한다 (패턴 조정용)")
    dump.add_argument("path", type=Path)
    dump.add_argument("--max-chars", type=int, default=4000)

    rules = sub.add_parser("rules", help="적용될 규칙 목록을 보여 준다")
    rules.add_argument("--type", dest="expense_type", required=True, choices=EXPENSE_TYPES)
    rules.add_argument("--subtype", choices=("TA", "SUPPORTERS"))
    rules.add_argument("--settings", type=Path)

    return parser


def _require_subtype(expense_type: str, subtype: str | None) -> str | None:
    if expense_type not in SUBTYPES:
        return None
    if subtype is None:
        raise SystemExit(
            f"{expense_type} 은 --subtype 이 필요합니다: {', '.join(SUBTYPES[expense_type])}"
        )
    return subtype


def _collect(path: Path) -> tuple[list[Path], tempfile.TemporaryDirectory | None]:
    if not path.exists():
        raise SystemExit(f"경로를 찾을 수 없습니다: {path}")
    workdir = tempfile.TemporaryDirectory(prefix="expense-review-")
    files = collect_files(path, workdir=Path(workdir.name))
    if not files:
        workdir.cleanup()
        raise SystemExit(f"검토할 파일이 없습니다: {path}")
    return files, workdir


def cmd_review(args: argparse.Namespace) -> int:
    subtype = _require_subtype(args.expense_type, args.subtype)
    files, workdir = _collect(args.path)
    try:
        documents = classify_all(files, args.expense_type, subtype)
        case = Case(
            expense_type=args.expense_type,
            subtype=subtype,
            person_label=args.person,
            root=args.path,
            documents=documents,
        )
        overrides = load_settings_file(args.settings) if args.settings else None
        result = review_case(case, overrides=overrides, mask_level=args.mask)

        if args.output_format == "json":
            text = render_json(result)
        elif args.output_format == "md":
            text = render_markdown(result)
        else:
            text = render_text(result, show_pass=args.show_pass)

        unsure = needs_confirmation(documents)
        if unsure and args.output_format == "text":
            text += "\n[확인 필요] 아래 파일은 서류 종류를 자신 있게 판정하지 못했습니다.\n"
            for document in unsure:
                text += (f"  - {document.file.name} → 추정 [{document.kind}] "
                         f"확신도 {document.kind_confidence:.2f}\n")
            text += "  `--type`/`--subtype` 을 확인하거나 파일명을 서류 이름에 맞춰 주세요.\n"

        if args.out:
            args.out.write_text(text, encoding="utf-8")
            print(f"저장했습니다: {args.out}")
        else:
            print(text)
        return 1 if result.count(Status.ERROR) else 0
    finally:
        workdir.cleanup()


def cmd_classify(args: argparse.Namespace) -> int:
    subtype = _require_subtype(args.expense_type, args.subtype)
    files, workdir = _collect(args.path)
    try:
        documents = classify_all(files, args.expense_type, subtype)
        print(render_classification(documents))
        unsure = needs_confirmation(documents)
        if unsure:
            print(f"확인 필요 {len(unsure)}건 — 위 목록에서 확신도가 낮은 항목을 확인하세요.")
        return 0
    finally:
        workdir.cleanup()


def cmd_dump(args: argparse.Namespace) -> int:
    files, workdir = _collect(args.path)
    try:
        for file in files:
            pages, error = load_document_pages(file)
            print("=" * 72)
            print(file)
            if error:
                print(f"  ! {error}")
            for page in pages:
                print(f"--- p.{page.number} ({len(page.text)}자, 이미지 {page.images}개) ---")
                print(page.text[: args.max_chars])
            print()
        return 0
    finally:
        workdir.cleanup()


def cmd_rules(args: argparse.Namespace) -> int:
    subtype = _require_subtype(args.expense_type, args.subtype)
    overrides = load_settings_file(args.settings) if args.settings else None
    ruleset = load_ruleset(args.expense_type, subtype, overrides)

    print(f"{args.expense_type}" + (f" ({subtype})" if subtype else ""))
    print(f"규칙 {len(ruleset.rules)}건")
    print()
    print("필수 서류:")
    for required in ruleset.required_documents:
        tags = []
        if required.optional:
            tags.append("선택")
        if required.provided_by:
            tags.append(required.provided_by)
        suffix = f" ({', '.join(tags)})" if tags else ""
        print(f"  - [{required.key}] {required.label}{suffix}")
    print()
    print("설정값:")
    for key, value in ruleset.settings.items():
        mark = "미설정" if value is None else value
        print(f"  {key}: {mark}")
    print()
    for rule in ruleset.rules:
        kind = f"check:{rule.check}" if rule.is_check else "expr"
        gate = f"  [조건: {rule.enabled_if}]" if rule.enabled_if else ""
        print(f"  {rule.id}  {rule.layer}  {rule.severity:5}  {rule.title}  ({kind}){gate}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    handlers = {
        "review": cmd_review,
        "classify": cmd_classify,
        "dump": cmd_dump,
        "rules": cmd_rules,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
