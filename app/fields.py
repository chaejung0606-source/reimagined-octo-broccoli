"""필드 색인 — 여러 서류에서 나온 같은 이름의 필드를 한자리에 모은다.

규칙은 `person.name` 하나만 보지만, 실제로는 서류 5장에 각각 적혀 있다.
- 표현식 평가에는 **가장 믿을 만한 값 하나**가 필요하고 (`best`),
- 교차 대사(R-CMN-003~009)에는 **서류별 값 전부**가 필요하다 (`entries`).

두 쓰임을 같은 색인이 감당한다.
"""
from __future__ import annotations

from typing import Any, Iterable

from .models import (
    Document,
    Field,
    FieldStatus,
    MISSING,
    Namespace,
    build_namespace,
)

#: 상태 우선순위 — 값이 있는 것 > 공란 > 미추출
_STATUS_RANK = {
    FieldStatus.PRESENT: 0,
    FieldStatus.BLANK: 1,
    FieldStatus.MISSING: 2,
}

#: 여러 서류에 흩어진 값을 하나로 모으는 방법이 '아무거나 하나' 가 아닌 경우.
#: 작성일은 서류마다 다르다 — 묶음의 작성일은 그 중 **가장 나중**이 맞다.
#: (추천서는 근로 시작 전에, 근무상황부는 근로가 끝난 뒤에 쓴다.)
_AGGREGATORS = {
    "submission.date": max,
}


class FieldIndex:
    """`경로 → (문서, 필드)` 목록."""

    def __init__(self) -> None:
        self._by_path: dict[str, list[tuple[Document | None, Field]]] = {}

    # -- 적재 -----------------------------------------------------------
    def add(self, document: Document | None, field: Field) -> None:
        self._by_path.setdefault(field.path, []).append((document, field))

    def add_many(self, document: Document | None, fields: dict[str, Field]) -> None:
        for field in fields.values():
            self.add(document, field)

    # -- 조회 -----------------------------------------------------------
    def paths(self) -> list[str]:
        return list(self._by_path)

    def entries(self, path: str) -> list[tuple[Document | None, Field]]:
        return list(self._by_path.get(path, []))

    def present_entries(self, path: str) -> list[tuple[Document | None, Field]]:
        return [(d, f) for d, f in self.entries(path) if f.status is FieldStatus.PRESENT]

    def best(self, path: str) -> Field | None:
        """이 경로에서 가장 믿을 만한 값 하나."""
        candidates = self._by_path.get(path)
        if not candidates:
            return None
        ranked = sorted(
            candidates,
            key=lambda pair: (_STATUS_RANK[pair[1].status], -pair[1].confidence),
        )
        aggregate = _AGGREGATORS.get(path)
        if aggregate is not None:
            present = [f for _, f in ranked if f.status is FieldStatus.PRESENT]
            if present:
                try:
                    return aggregate(present, key=lambda f: f.value)
                except TypeError:
                    pass
        return ranked[0][1]

    def value(self, path: str) -> Any:
        field = self.best(path)
        return MISSING if field is None else field.resolved

    def has(self, path: str) -> bool:
        return path in self._by_path

    def documents_for(self, path: str) -> list[Document]:
        return [d for d, _ in self.entries(path) if d is not None]

    # -- 표현식 스코프 ---------------------------------------------------
    def namespace(self) -> Namespace:
        flat = {path: self.value(path) for path in self._by_path}
        return build_namespace(flat)

    def scope(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """표현식 평가용 최상위 이름 사전."""
        scope = self.namespace().as_dict()
        if extra:
            scope.update(extra)
        return scope

    def merge(self, other: "FieldIndex") -> None:
        for path, entries in other._by_path.items():
            self._by_path.setdefault(path, []).extend(entries)

    def __contains__(self, path: object) -> bool:
        return path in self._by_path

    def __len__(self) -> int:
        return len(self._by_path)

    def __repr__(self) -> str:
        return f"FieldIndex({len(self._by_path)} paths)"


def distinct_values(entries: Iterable[tuple[Document | None, Field]],
                    normalizer=None) -> dict[Any, list[str]]:
    """`값 → 그 값을 담고 있는 서류 이름들`. 교차 대사 메시지에 그대로 쓴다."""
    groups: dict[Any, list[str]] = {}
    for document, field in entries:
        if field.status is not FieldStatus.PRESENT:
            continue
        value = normalizer(field.value) if normalizer else field.value
        if value is None:
            continue
        label = str(document) if document is not None else "(집계)"
        groups.setdefault(value, []).append(label)
    return groups
