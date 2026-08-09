"""PDF 읽기 — 텍스트 레이어 추출과 손상 파일 폴백.

docs/04-architecture.md §3 이 지적한 실제 사례를 그대로 다룬다.

- 전자결재 출력본 일부는 헤더가 깨져 있다 (`invalid pdf header: b'Handy'`).
  → `%PDF` 시그니처를 찾아 앞을 잘라내고 다시 연다. 그래도 안 되면 pypdf(strict=False).
- zip 이 CP949 로 압축되어 파일명이 깨진다. → utf-8 → cp437→cp949 폴백.

OCR 은 4단계 작업이므로 여기서는 하지 않는다. 텍스트 레이어가 없는 문서는
`Document.readable == False` 로 남겨 두고, 규칙 엔진이 🔵 판독 불가로 올린다.
"""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

from .models import Page

log = logging.getLogger(__name__)

PDF_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".heic"}
ARCHIVE_SUFFIXES = {".zip"}
#: 검토 대상이 될 수 있는 확장자 전체
SUPPORTED_SUFFIXES = PDF_SUFFIXES | IMAGE_SUFFIXES

_PDF_SIGNATURE = b"%PDF"


# --------------------------------------------------------------- 손상 복구

def repair_pdf_bytes(data: bytes) -> bytes | None:
    """헤더가 깨진 PDF 를 되살린다.

    전자결재 시스템이 앞에 잡다한 바이트를 붙여 내보내는 경우가 있어
    (`Handy...`), `%PDF` 시그니처 위치부터 잘라내면 대개 열린다.
    시그니처가 아예 없으면 표준 헤더를 앞에 붙여 본다.
    """
    index = data.find(_PDF_SIGNATURE)
    if index > 0:
        return data[index:]
    if index < 0 and b"obj" in data[:4096]:
        return b"%PDF-1.4\n" + data
    return None


def _pages_from_pdfplumber(stream: io.BytesIO | Path) -> list[Page]:
    import pdfplumber

    pages: list[Page] = []
    with pdfplumber.open(stream) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # 한 페이지가 깨져도 나머지는 살린다
                log.debug("페이지 %d 텍스트 추출 실패: %s", number, exc)
                text = ""
            try:
                words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            except Exception:
                words = []
            try:
                images = len(page.images or [])
            except Exception:
                images = 0
            pages.append(Page(number=number, text=text, words=words, images=images))
    return pages


def _pages_from_pypdf(data: bytes) -> list[Page]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=False)
    pages: list[Page] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            log.debug("pypdf 페이지 %d 추출 실패: %s", number, exc)
            text = ""
        pages.append(Page(number=number, text=text))
    return pages


def read_pdf(path: Path) -> tuple[list[Page], str]:
    """PDF → (페이지 목록, 오류 메시지).

    오류 메시지가 비어 있지 않으면 그 파일은 이 단계에서 내용을 볼 수 없다.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        return [], f"파일을 읽을 수 없습니다: {exc}"

    attempts: list[tuple[str, bytes]] = [("원본", data)]
    repaired = repair_pdf_bytes(data)
    if repaired is not None:
        attempts.append(("헤더 복구본", repaired))

    errors: list[str] = []
    for label, payload in attempts:
        try:
            pages = _pages_from_pdfplumber(io.BytesIO(payload))
            if pages:
                if label != "원본":
                    log.info("%s: %s 으로 열었습니다.", path.name, label)
                return pages, ""
        except Exception as exc:
            errors.append(f"pdfplumber({label}): {exc}")
        try:
            pages = _pages_from_pypdf(payload)
            if pages:
                log.info("%s: pypdf(strict=False) / %s 로 열었습니다.", path.name, label)
                return pages, ""
        except Exception as exc:
            errors.append(f"pypdf({label}): {exc}")

    return [], "PDF 를 열지 못했습니다 — " + " / ".join(errors[:2])


# ------------------------------------------------------------------- 수집

def decode_zip_name(info: zipfile.ZipInfo) -> str:
    """CP949 로 압축된 zip 의 파일명을 되살린다.

    zipfile 은 UTF-8 플래그가 없으면 cp437 로 디코드해 둔다.
    한국에서 만든 zip 은 대부분 cp949 이므로 되돌려 다시 디코드한다.
    """
    if info.flag_bits & 0x800:
        return info.filename
    for encoding in ("cp949", "euc-kr", "utf-8"):
        try:
            return info.filename.encode("cp437").decode(encoding)
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return info.filename


def extract_zip(archive: Path, dest: Path) -> list[Path]:
    """zip 을 풀고 풀린 파일 경로를 돌려준다. 파일명 인코딩을 보정한다."""
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = decode_zip_name(info)
            target = dest / name
            # zip slip 방지: 압축 파일이 바깥 경로를 가리키면 무시한다.
            try:
                target.resolve().relative_to(dest.resolve())
            except ValueError:
                log.warning("zip 항목이 대상 폴더를 벗어납니다, 건너뜁니다: %s", name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
            written.append(target)
    return written


def collect_files(root: Path, workdir: Path | None = None) -> list[Path]:
    """폴더(또는 단일 파일/zip) 아래의 검토 대상 파일을 모은다.

    zip 은 ``workdir`` 에 풀어서 함께 반환한다. ``workdir`` 를 주지 않으면
    zip 옆에 ``<이름>_unzipped`` 폴더를 만든다.
    """
    root = Path(root)
    found: list[Path] = []

    def visit(path: Path) -> None:
        suffix = path.suffix.lower()
        if suffix in ARCHIVE_SUFFIXES:
            target = (workdir or path.parent) / f"{path.stem}_unzipped"
            for extracted in extract_zip(path, target):
                visit(extracted)
            return
        if suffix in SUPPORTED_SUFFIXES:
            found.append(path)

    if root.is_file():
        visit(root)
    else:
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                visit(path)

    # 중복 경로 제거(같은 zip 을 두 번 풀지 않도록)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def load_document_pages(path: Path) -> tuple[list[Page], str]:
    """확장자에 따라 페이지를 만든다. 이미지는 이 단계에서 내용을 읽지 않는다."""
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return read_pdf(path)
    if suffix in IMAGE_SUFFIXES:
        return [], "이미지 파일입니다 — 내용 판독은 OCR 단계(4단계)에서 처리합니다."
    return [], f"지원하지 않는 형식입니다: {suffix}"
