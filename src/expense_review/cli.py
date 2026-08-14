"""명령줄 인터페이스.

  expense-review <폴더> --type 출장비 [--roster 지급내역.pdf]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .report import to_markdown, to_text
from .review import EXPENSE_TYPES, review_folder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="expense-review", description="지출 서류를 기준에 따라 검토합니다."
    )
    parser.add_argument("path", type=Path, help="검토할 폴더 또는 파일")
    parser.add_argument("--type", required=True, choices=EXPENSE_TYPES, help="지출종류")
    parser.add_argument("--subtype", choices=("TA", "SUPPORTERS"), help="근로장학금 하위 유형")
    parser.add_argument("--owner", help="제출자 성명 (기본값: 폴더명)")
    parser.add_argument("--roster", type=Path, help="지급내역 파일 (폴더 밖에 있을 때)")
    parser.add_argument("--markdown", type=Path, help="수정 요청서를 마크다운 파일로 저장")
    parser.add_argument("--show-skipped", action="store_true", help="자동 검사하지 않은 규칙도 표시")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.ERROR,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not args.verbose:
        # pypdf 는 손상 PDF마다 경고를 stdout 으로 쏟는다. 결과 화면을 가린다.
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)

    if not args.path.exists():
        print(f"경로를 찾을 수 없습니다: {args.path}", file=sys.stderr)
        return 2

    # 사람별로 나누는 일은 review_folder 가 알아서 한다.
    results = review_folder(args.path, args.type, args.subtype, args.roster)

    for result in results:
        print(to_text(result, show_skipped=args.show_skipped))
        print("─" * 72)

    if args.markdown:
        args.markdown.write_text(to_markdown(results), encoding="utf-8")
        print(f"수정 요청서를 저장했습니다: {args.markdown}")

    has_error = any(result.counts.get(severity) for result in results
                    for severity in result.counts if severity.name == "ERROR")
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
