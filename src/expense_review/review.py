"""폴더 하나를 읽어 검토 결과를 만드는 파이프라인.

  파일 수집 → 분류 → 필드 추출 → 규칙 평가
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import checks  # noqa: F401  (규칙 판정 함수 등록)
from .classify import load_and_classify
from .engine import evaluate, load_ruleset
from .extractors import extract
from .models import DocumentSet, ReviewResult

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".pdf", ".png", ".jpg", ".jpeg", ".hwp", ".hwpx", ".tif", ".tiff"}
EXPENSE_TYPES = ("근로장학금", "혁신인재지원금", "출장비")


def collect_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def build_document_set(
    paths: list[Path],
    expense_type: str,
    owner: str | None = None,
    subtype: str | None = None,
    extra_documents: list = (),
) -> DocumentSet:
    documents = [extract(load_and_classify(path)) for path in paths]
    documents.extend(extra_documents)
    return DocumentSet(
        expense_type=expense_type, documents=documents, owner=owner, subtype=subtype
    )


def review(
    root: Path,
    expense_type: str,
    owner: str | None = None,
    subtype: str | None = None,
    roster: Path | None = None,
) -> ReviewResult:
    """폴더 하나(제출자 1인분)를 검토한다.

    지급내역은 사업단이 따로 보관하는 마스터 문서라, 제출자 폴더 밖에 있을 수 있어
    `roster` 로 따로 받는다.
    """
    if expense_type not in EXPENSE_TYPES:
        raise ValueError(f"지원하지 않는 지출종류입니다: {expense_type}")

    paths = collect_files(root)
    extra = [extract(load_and_classify(roster))] if roster else []
    document_set = build_document_set(paths, expense_type, owner, subtype, extra)

    ruleset = load_ruleset(expense_type, subtype)
    return evaluate(document_set, ruleset)


def review_batch(
    root: Path,
    expense_type: str,
    subtype: str | None = None,
    roster: Path | None = None,
) -> list[ReviewResult]:
    """하위 폴더마다 제출자가 나뉘어 있는 묶음을 한 번에 검토한다."""
    subdirectories = sorted(p for p in root.iterdir() if p.is_dir())
    if not subdirectories:
        return [review(root, expense_type, root.name, subtype, roster)]
    return [
        review(directory, expense_type, directory.name, subtype, roster)
        for directory in subdirectories
    ]
