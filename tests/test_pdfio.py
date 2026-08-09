"""PDF 입출력 — 손상 헤더 복구와 CP949 zip.

docs/04-architecture.md §3 이 지적한 실제 사례를 그대로 재현한다.
"""
import io
import zipfile
from pathlib import Path

import pytest

from app.pdfio import (
    collect_files,
    decode_zip_name,
    extract_zip,
    read_pdf,
    repair_pdf_bytes,
)


def make_pdf(text: str = "HELLO EXPENSE REVIEW") -> bytes:
    """검증용 PDF 한 장. reportlab 이 없으면 테스트를 건너뛴다."""
    canvas_mod = pytest.importorskip("reportlab.pdfgen.canvas")
    buffer = io.BytesIO()
    pdf = canvas_mod.Canvas(buffer)
    pdf.drawString(72, 720, text)
    pdf.save()
    return buffer.getvalue()


def test_reads_a_normal_pdf(tmp_path: Path):
    path = tmp_path / "정상.pdf"
    path.write_bytes(make_pdf())
    pages, error = read_pdf(path)
    assert error == ""
    assert "HELLO EXPENSE REVIEW" in pages[0].text


def test_repairs_a_broken_header(tmp_path: Path):
    """전자결재 출력본 일부는 앞에 잡다한 바이트가 붙어 `invalid pdf header` 로 열리지 않는다.

    (샘플: `이성재/국내 출장신청서 (3건).pdf` — 헤더가 `Handy` 로 시작)
    """
    path = tmp_path / "손상.pdf"
    path.write_bytes(b"HandyGarbageBytes" + make_pdf())

    assert repair_pdf_bytes(path.read_bytes()).startswith(b"%PDF")
    pages, error = read_pdf(path)
    assert error == ""
    assert "HELLO EXPENSE REVIEW" in pages[0].text


def test_unreadable_file_reports_an_error(tmp_path: Path):
    path = tmp_path / "깨진.pdf"
    path.write_bytes(b"not a pdf at all")
    pages, error = read_pdf(path)
    assert pages == []
    assert error


def test_image_file_is_deferred_to_ocr(tmp_path: Path):
    from app.pdfio import load_document_pages

    path = tmp_path / "영수증.jpg"
    path.write_bytes(b"\xff\xd8\xff")
    pages, error = load_document_pages(path)
    assert pages == []
    assert "OCR" in error


def test_cp949_zip_filenames_are_restored():
    """한국에서 만든 zip 은 CP949 로 압축돼 파일명이 깨진다.

    zipfile 은 UTF-8 플래그가 없으면 cp437 로 디코드해 두므로 되돌려 다시 읽는다.
    (파이썬 zipfile 로는 UTF-8 플래그 없는 아카이브를 만들 수 없어 디코더를 직접 검증한다.)
    """
    name = "근무상황부_권석재.pdf"
    info = zipfile.ZipInfo(name.encode("cp949").decode("cp437"))
    info.flag_bits &= ~0x800
    assert decode_zip_name(info) == name

    # UTF-8 플래그가 있으면 그대로 쓴다.
    utf8_info = zipfile.ZipInfo(name)
    utf8_info.flag_bits |= 0x800
    assert decode_zip_name(utf8_info) == name


def test_collect_files_walks_folders_and_archives(tmp_path: Path):
    root = tmp_path / "이성재"
    root.mkdir()
    (root / "출장증빙.pdf").write_bytes(make_pdf())
    (root / "메모.txt").write_text("검토 대상 아님", encoding="utf-8")

    inner = tmp_path / "묶음.zip"
    with zipfile.ZipFile(inner, "w") as zf:
        zf.writestr("하이패스.pdf", make_pdf())
    (root / "묶음.zip").write_bytes(inner.read_bytes())

    found = {p.name for p in collect_files(root, workdir=tmp_path / "작업")}
    assert found == {"출장증빙.pdf", "하이패스.pdf"}


def test_zip_slip_is_ignored(tmp_path: Path):
    archive = tmp_path / "악성.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../탈출.pdf", make_pdf())
    written = extract_zip(archive, tmp_path / "대상")
    assert written == []
