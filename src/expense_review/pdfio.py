"""PDF 텍스트 추출.

전자결재 출력물 일부는 헤더가 손상돼(`invalid pdf header: b'Handy'`) 표준
파서로 열리지 않는다. 실제로 `이성재/국내 출장신청서 (3건).pdf` 가 그렇다.
그래서 파서를 여러 단계로 폴백한다.

  1) pypdf(strict=False)
  2) pdfplumber
  3) 헤더 복구 후 재시도 — 파일 앞부분의 쓰레기를 잘라내고 %PDF 부터 읽는다

세 단계가 모두 실패하면 페이지 텍스트 없이 Document 를 돌려준다. 이 경우
필드가 비어 있으므로 규칙 엔진이 자동으로 REVIEW(판독 불가)로 처리한다.
OCR 폴백은 4단계에서 붙인다.
"""
from __future__ import annotations

import io
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# 이미지 스캔 PDF 는 페이지당 글자가 거의 없다. OCR 이 필요하다는 신호.
MIN_CHARS_PER_PAGE = 20

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp"}


class ExtractionError(RuntimeError):
    pass


def _with_pypdf(data: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    return [(page.extract_text() or "") for page in reader.pages]


def _with_pdfplumber(data: bytes) -> list[str]:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(page.extract_text() or "") for page in pdf.pages]


def _repair_header(data: bytes) -> bytes | None:
    """파일 앞에 붙은 쓰레기를 잘라내고 %PDF 시그니처부터 시작하게 만든다."""
    index = data.find(b"%PDF-")
    if index <= 0:
        return None
    return data[index:]


def extract_pages(path: Path) -> tuple[list[str], list[str]]:
    """페이지별 텍스트와, 추출 중 발생한 경고 목록을 돌려준다."""
    notes: list[str] = []
    data = path.read_bytes()

    attempts: list[tuple[str, bytes]] = [("원본", data)]
    repaired = _repair_header(data)
    if repaired is not None:
        attempts.append(("헤더 복구", repaired))

    for label, payload in attempts:
        for parser_name, parser in (("pypdf", _with_pypdf), ("pdfplumber", _with_pdfplumber)):
            try:
                pages = parser(payload)
            except Exception as exc:  # 파서마다 예외 종류가 제각각이라 넓게 잡는다
                logger.debug("%s: %s(%s) 실패 — %s", path.name, parser_name, label, exc)
                continue
            if any(page.strip() for page in pages):
                if label != "원본":
                    notes.append(f"PDF 헤더가 손상되어 복구 후 읽었습니다 ({parser_name}).")
                return pages, notes
            # 텍스트가 비었지만 페이지 수는 얻었다 — 스캔본일 가능성
            if pages:
                notes.append(
                    f"텍스트 레이어가 없습니다({len(pages)}페이지). 스캔 문서로 보이며 OCR이 필요합니다."
                )
                return pages, notes

    notes.append("PDF를 열 수 없습니다. 파일이 손상되었을 수 있습니다.")
    return [], notes


def load_document(path: Path):
    """파일 하나를 Document 로 읽어들인다. 이미지는 페이지 없이 표시만 해 둔다."""
    from .models import Document

    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return Document(
            path=path,
            pages=[],
            notes=["이미지 파일입니다. 텍스트 추출은 OCR 단계(4단계)에서 지원합니다."],
        )
    if suffix == ".pdf":
        pages, notes = extract_pages(path)
        return Document(path=path, pages=pages, notes=notes)
    if suffix in {".hwp", ".hwpx"}:
        return Document(path=path, pages=[], notes=["한글(HWP) 파일은 아직 읽지 않습니다."])

    return Document(path=path, pages=[], notes=[f"지원하지 않는 형식입니다({suffix})."])


def is_scanned(document) -> bool:
    """텍스트가 거의 없는 스캔 문서인지."""
    if not document.pages:
        return True
    total = sum(len(page.strip()) for page in document.pages)
    return total < MIN_CHARS_PER_PAGE * max(len(document.pages), 1)


_WS_RE = re.compile(r"[ \t]+")


def flatten(text: str) -> str:
    """줄바꿈으로 잘린 항목을 한 줄로 붙인다.

    한글 서식 PDF 는 글자 단위로 줄바꿈되는 경우가 많다. 예를 들어
    '근로장학생\\n근무상황부' 처럼 나오므로, 라벨을 찾으려면 붙여야 한다.
    """
    return _WS_RE.sub("", text.replace("\n", ""))
