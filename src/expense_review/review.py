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


# 지급대상자를 특정할 수 없는 서류. 여러 사람이 함께 실리므로 한 명에게
# 귀속시킬 수 없고, 모든 지급건의 대사 상대가 된다.
SHARED_DOC_TYPES = {"roster", "member_list", "payment_list"}


def _identity(document) -> tuple[str | None, str]:
    """이 서류가 누구 것인지. (묶음 키, 표시용 이름)

    학번이 성명보다 낫다 — 동명이인이 갈리고, 표기 흔들림이 없다.
    둘 다 없으면 누구 것인지 모르는 서류다.
    """
    student_id = document.fields.get("student_id")
    name = None
    for field_name in ("name", "applicant"):
        candidate = document.fields.get(field_name)
        if candidate is not None and candidate.is_present:
            name = str(candidate.value).replace(" ", "")
            break

    if student_id is not None and student_id.is_present:
        digits = "".join(ch for ch in str(student_id.value) if ch.isdigit())
        if digits:
            return digits, name or digits
    if name:
        return f"name:{name}", name
    return None, ""


def group_by_person(documents: list) -> list[tuple[str, list]]:
    """서류를 지급대상자별로 묶는다.

    한 폴더에 여러 사람의 서류가 섞여 있을 때 이것을 하지 않으면, 서로 다른
    사람의 성명·학번·계좌·주민등록번호를 '불일치'로 판정한다. 실제로 아홉 명의
    개인정보를 한 명 것으로 통일하라는 수정 요청이 나갔다.

    **다른 사람끼리 값이 다른 것은 오류가 아니다.** 대사는 같은 사람의 서류
    안에서만 한다.
    """
    keyed: dict[str, list] = {}
    labels: dict[str, str] = {}
    shared: list = []

    for document in documents:
        if (document.contains or set()) & SHARED_DOC_TYPES or document.doc_type in SHARED_DOC_TYPES:
            shared.append(document)
            continue
        key, label = _identity(document)
        if key is None:
            shared.append(document)
            continue
        keyed.setdefault(key, []).append(document)
        labels.setdefault(key, label)

    if len(keyed) <= 1:
        label = next(iter(labels.values()), "")
        return [(label, list(documents))]

    # 지급대상자를 특정할 수 없는 서류(지급내역 등)는 모든 지급건의 대사 상대가 된다.
    return [(labels[key], docs + shared) for key, docs in keyed.items()]


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


def review_folder(
    root: Path,
    expense_type: str,
    subtype: str | None = None,
    roster: Path | None = None,
) -> list[ReviewResult]:
    """폴더를 지급건 단위로 나눠 검토한다.

    묶는 방법은 두 가지이고, 폴더 모양을 보고 저절로 정해진다.

      하위 폴더가 있으면   폴더 하나 = 지급대상자 한 명
      파일만 있으면        서류에서 읽은 학번·성명으로 사람을 갈라 묶는다

    사용자가 '한 명씩'과 '여러 명'을 직접 골라야 했을 때, 여러 명의 서류를
    한 명으로 검토해 서로 다른 사람의 개인정보를 통일하라는 요청이 나갔다.
    고르지 않아도 되게 만드는 편이 안전하다.
    """
    if expense_type not in EXPENSE_TYPES:
        raise ValueError(f"지원하지 않는 지출종류입니다: {expense_type}")

    subdirectories = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    if subdirectories:
        return [
            review(directory, expense_type, directory.name, subtype, roster)
            for directory in subdirectories
        ]

    documents = [extract(load_and_classify(path)) for path in collect_files(root)]
    if roster:
        documents.append(extract(load_and_classify(roster)))

    ruleset = load_ruleset(expense_type, subtype)
    results = []
    for label, group in group_by_person(documents):
        document_set = DocumentSet(
            expense_type=expense_type, documents=group,
            owner=label or root.name, subtype=subtype,
        )
        results.append(evaluate(document_set, ruleset))
    return results


def review_batch(
    root: Path,
    expense_type: str,
    subtype: str | None = None,
    roster: Path | None = None,
) -> list[ReviewResult]:
    """예전 이름. review_folder 를 쓴다."""
    return review_folder(root, expense_type, subtype, roster)
