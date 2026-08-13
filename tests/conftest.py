"""실제 서류 없이 규칙을 검증하기 위한 도우미.

검토 대상 PDF에는 주민등록번호·계좌번호가 들어 있어 저장소에 넣을 수 없다.
그래서 추출 결과(필드)를 직접 만들어 규칙만 시험한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from expense_review import checks  # noqa: F401  (규칙 판정 함수 등록)
from expense_review.engine import evaluate, load_ruleset
from expense_review.models import CONFIDENCE, Document, DocumentSet, Value


def make_document(doc_type: str, filename: str | None = None, **fields) -> Document:
    document = Document(
        path=Path(filename or f"{doc_type}.pdf"),
        doc_type=doc_type,
        contains={doc_type},
        pages=["(테스트)"],
        page_types=[doc_type],
    )
    document.fields = {
        key: value if isinstance(value, Value) else Value(value, CONFIDENCE["pdf_text"], document.source(1))
        for key, value in fields.items()
    }
    return document


def run(expense_type: str, documents: list[Document], owner: str | None = None,
        subtype: str | None = None):
    document_set = DocumentSet(
        expense_type=expense_type, documents=documents, owner=owner, subtype=subtype
    )
    return evaluate(document_set, load_ruleset(expense_type, subtype))


def ids(result) -> set[str]:
    """ERROR/WARN 로 확정된 규칙 ID만. REVIEW(판독 보류)는 제외한다."""
    from expense_review.models import Severity

    return {
        finding.rule_id for finding in result.findings
        if finding.severity in (Severity.ERROR, Severity.WARN)
    }


@pytest.fixture
def helpers():
    return type("Helpers", (), {"make_document": staticmethod(make_document),
                                "run": staticmethod(run), "ids": staticmethod(ids)})
