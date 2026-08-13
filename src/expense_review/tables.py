"""표 좌표 재조립.

지급내역·근무상황부는 텍스트를 그냥 뽑으면 셀 순서가 뒤엉킨다. 이름·학번이
표 하단으로 밀려 나오는 식이다(docs/01 §4). 단어별 좌표로 행을 다시 묶는다.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 같은 행으로 볼 세로 허용 오차(pt). 폰트 높이보다 작게 잡는다.
ROW_TOLERANCE = 4.0
# 이 간격 미만으로 붙어 있는 숫자 토큰은 한 값이 쪼개진 것으로 본다.
# 예: '240,000' 이 '2' + '40,000' 으로 잘려 나온다.
NUMBER_JOIN_GAP = 2.5

_NUMERIC_RE = re.compile(r"^[\d,]+$")


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float


def extract_words(path: Path, page_index: int = 0) -> list[Word]:
    import pdfplumber

    data = path.read_bytes()
    marker = data.find(b"%PDF-")
    if marker > 0:  # 헤더 손상 파일 복구 (pdfio 와 같은 처리)
        data = data[marker:]
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if page_index >= len(pdf.pages):
                return []
            words = pdf.pages[page_index].extract_words()
    except Exception as exc:
        logger.debug("%s: 단어 좌표 추출 실패 — %s", path.name, exc)
        return []
    return [Word(w["text"], w["x0"], w["x1"], w["top"]) for w in words]


def group_rows(words: list[Word], tolerance: float = ROW_TOLERANCE) -> list[list[Word]]:
    """세로 위치가 비슷한 단어를 한 행으로 묶는다."""
    rows: dict[int, list[Word]] = {}
    for word in words:
        rows.setdefault(round(word.top / tolerance), []).append(word)
    return [
        sorted(rows[key], key=lambda w: w.x0)
        for key in sorted(rows)
    ]


def join_split_numbers(row: list[Word]) -> list[Word]:
    """붙어 있는 숫자 토큰을 하나로 합친다. '2' + '40,000' → '240,000'"""
    if not row:
        return row
    merged = [row[0]]
    for word in row[1:]:
        previous = merged[-1]
        if (
            _NUMERIC_RE.match(previous.text)
            and _NUMERIC_RE.match(word.text)
            and word.x0 - previous.x1 < NUMBER_JOIN_GAP
        ):
            merged[-1] = Word(previous.text + word.text, previous.x0, word.x1, previous.top)
        else:
            merged.append(word)
    return merged


def row_texts(path: Path, page_index: int = 0) -> list[list[str]]:
    """페이지를 '행 = 셀 문자열 목록' 으로 돌려준다."""
    rows = group_rows(extract_words(path, page_index))
    return [[w.text for w in join_split_numbers(row)] for row in rows]
