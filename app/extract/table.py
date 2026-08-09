"""표 재조립 — 단어 좌표로 행·열을 다시 세운다.

docs/01-sample-analysis.md §4 가 지적한 문제: 지급내역·근무상황부는 텍스트로 뽑으면
셀 순서가 뒤엉켜 이름/학번이 표 하단으로 몰린다. `page.extract_text()` 대신 단어별
bbox 를 y 좌표로 묶어 행을 만들고, x 좌표로 정렬하면 원래 표에 가깝게 복원된다.

좌표 정보가 없으면(pypdf 폴백 등) 그냥 텍스트 줄을 쓴다. 이때 신뢰도는 호출부에서
`Confidence.TABLE_REBUILD` 대신 그대로 두면 된다.
"""
from __future__ import annotations

from typing import Any, Sequence

from ..models import Document, Page

#: 같은 행으로 볼 y 좌표 오차(pt). 한글 서식의 행 높이는 보통 12~20pt 다.
ROW_TOLERANCE = 4.0


def rows_from_words(page: Page, tolerance: float = ROW_TOLERANCE) -> list[list[dict[str, Any]]]:
    """단어들을 y 좌표로 묶어 행 목록을 만든다. 각 행은 x 순으로 정렬된다."""
    if not page.words:
        return []
    words = [w for w in page.words if str(w.get("text", "")).strip()]
    words.sort(key=lambda w: (round(float(w.get("top", 0.0)), 1), float(w.get("x0", 0.0))))

    rows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_top: float | None = None
    for word in words:
        top = float(word.get("top", 0.0))
        if current_top is None or abs(top - current_top) <= tolerance:
            current.append(word)
            current_top = top if current_top is None else (current_top + top) / 2
        else:
            rows.append(sorted(current, key=lambda w: float(w.get("x0", 0.0))))
            current = [word]
            current_top = top
    if current:
        rows.append(sorted(current, key=lambda w: float(w.get("x0", 0.0))))
    return rows


def row_text(row: Sequence[dict[str, Any]], gap: float = 6.0) -> str:
    """행의 단어들을 붙여 한 줄로. 칸 사이가 벌어졌으면 공백을 여러 개 넣는다."""
    parts: list[str] = []
    previous_x1: float | None = None
    for word in row:
        text = str(word.get("text", ""))
        x0 = float(word.get("x0", 0.0))
        if previous_x1 is not None:
            parts.append("  " if x0 - previous_x1 > gap else " ")
        parts.append(text)
        previous_x1 = float(word.get("x1", x0))
    return "".join(parts)


def table_lines(document: Document) -> list[str]:
    """좌표 기반으로 복원한 줄 목록. 좌표가 없으면 일반 텍스트 줄을 돌려준다."""
    lines: list[str] = []
    for page in document.pages:
        rows = rows_from_words(page)
        if rows:
            lines.extend(row_text(row) for row in rows)
        else:
            lines.extend(page.lines)
    return lines


def cells(row: Sequence[dict[str, Any]], gap: float = 6.0) -> list[tuple[float, str]]:
    """행을 셀 단위로 자른다. (셀 시작 x 좌표, 텍스트)."""
    out: list[tuple[float, str]] = []
    buffer: list[str] = []
    start_x: float | None = None
    previous_x1: float | None = None
    for word in row:
        text = str(word.get("text", ""))
        x0 = float(word.get("x0", 0.0))
        if previous_x1 is not None and x0 - previous_x1 > gap:
            out.append((start_x or 0.0, " ".join(buffer)))
            buffer = []
            start_x = None
        if start_x is None:
            start_x = x0
        buffer.append(text)
        previous_x1 = float(word.get("x1", x0))
    if buffer:
        out.append((start_x or 0.0, " ".join(buffer)))
    return out


def find_header(rows: list[list[dict[str, Any]]], labels: Sequence[str],
                min_hits: int = 2) -> int | None:
    """열 이름이 들어 있는 행의 인덱스를 찾는다."""
    for index, row in enumerate(rows):
        text = row_text(row).replace(" ", "")
        hits = sum(1 for label in labels if label.replace(" ", "") in text)
        if hits >= min_hits:
            return index
    return None


def align_to_columns(header_cells: list[tuple[float, str]],
                     data_cells: list[tuple[float, str]],
                     tolerance: float = 25.0) -> dict[str, str]:
    """머리행의 x 좌표에 데이터 셀을 맞춰 `열 이름 → 값` 으로 만든다."""
    mapping: dict[str, list[str]] = {label: [] for _, label in header_cells}
    for x, text in data_cells:
        best_label: str | None = None
        best_distance = tolerance
        for header_x, label in header_cells:
            distance = abs(x - header_x)
            if distance < best_distance:
                best_distance = distance
                best_label = label
        if best_label is not None:
            mapping[best_label].append(text)
    return {label: " ".join(values).strip() for label, values in mapping.items() if values}
