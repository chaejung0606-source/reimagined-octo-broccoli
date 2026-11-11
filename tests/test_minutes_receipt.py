"""회의록 아래 '기타' 칸에 카드 영수증 그림 붙이기(minutes/receipt.py) — 담당자 2026-11-11.

hwpx.py 는 그대로 두고 만든 .hwpx 를 뒤에서 고치므로, 고친 뒤에도 한글이 여는 규칙(격자 · mimetype 첫 항목 무압축 · id 참조)이
지켜지는지를 본다. 그림은 코드로 만든 작은 PNG · JPEG(실제 영수증 아님). 한글에서 여는 확인은 담당자가 한다.
"""
from __future__ import annotations

import base64
import re
import struct
import zipfile
import zlib
from pathlib import Path
from xml.dom import minidom

import pytest

from claim_downloader.claims import card
from claim_downloader.minutes import hwpx, process, receipt

from test_minutes import FakeBackend, _grid, sample

# 30×60 회색 JPEG(PIL 로 만들어 둔 것) — CI 에는 Qt · PIL 이 없어 그대로 넣는다
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABQODxIPDRQSEBIXFRQYHjIhHhwcHj0sLiQySUBMS0dARkVQWnNiUFVtVkVGZIhlbXd7gYKBTmCNl4x9lnN+gXz/"
    "2wBDARUXFx4aHjshITt8U0ZTfHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHx8fHz/wAARCAA8AB4DASIAAhEBAxEB/8QA"
    "HwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkK"
    "FhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXG"
    "x8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAEC"
    "AxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOE"
    "hYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDdooooAKKK"
    "KACiiigAooooAKKKKACiiigAooooAKKKKAP/2Q==")


def png(width: int, height: int) -> bytes:
    raw = b"".join(b"\x00" + b"\xc8\xc8\xc8" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.fixture
def no_qt(monkeypatch):
    monkeypatch.setattr(receipt, "_qt_ready", lambda: False)


def meeting(tmp_path: Path, files: dict[str, bytes]) -> Path:
    folder = tmp_path / "261012_(17)_운영회의"
    for name, data in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return folder


def built(tmp_path: Path, folder: Path) -> Path:
    out = folder / "2026-10-12 월 운영회의.hwpx"
    hwpx.build_hwpx(sample(), str(out))
    return out


def test_finds_receipts_by_name_and_skips_other_files(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt, "_pdf_looks_like_receipt", lambda path: path.endswith("명세.pdf"))
    folder = meeting(tmp_path, {
        "1012 영수증.jpg": JPEG, "카드매출전표.PNG": png(4, 4), "회의 사진.jpg": JPEG, "서명부.pdf": b"%PDF",
        "회의록.pdf": b"%PDF", "공문.pdf": b"%PDF", "결제 명세.pdf": b"%PDF", "자료.pdf": b"%PDF",
        "기타/영수증.jpg": JPEG, "업로드/영수증.jpg": JPEG, "증빙/receipt_1.jpeg": JPEG})
    found = [Path(p).relative_to(folder).as_posix() for p in receipt.find_receipts(folder)]
    assert found == ["1012 영수증.jpg", "결제 명세.pdf", "카드매출전표.PNG", "증빙/receipt_1.jpeg"]


def test_header_sizes_without_qt():
    assert receipt._jpeg_size(JPEG) == (30, 60)
    assert receipt._png_size(png(7, 3)) == (7, 3)
    assert receipt._jpeg_size(b"not a jpeg") is None


def test_fit_keeps_ratio_inside_cell():
    w, h = receipt.fit(1200, 3000)                 # 긴 영수증 — 높이에 맞춤
    assert h == receipt.PIC_MAX_H and abs(w / h - 0.4) < 0.01
    w, h = receipt.fit(4000, 3000)                 # 가로 사진 — 폭에 맞춤
    assert w == receipt.PIC_MAX_W and w <= receipt._INNER_W
    w, h = receipt.fit(30, 60)                     # 작은 그림은 두 배 크기까지만
    assert (w, h) == (30 * receipt.PX_TO_HU, 60 * receipt.PX_TO_HU)


def test_attach_adds_extra_rows_with_pictures(tmp_path, no_qt):
    folder = meeting(tmp_path, {"1012 영수증.jpg": JPEG, "1012 카드전표.png": png(40, 20), "회의 사진.jpg": JPEG})
    out = built(tmp_path, folder)
    rows_before, _ = _grid(out)
    with zipfile.ZipFile(out) as z:
        height_before = int(re.search(r'<hp:tbl .*?<hp:sz width="\d+" widthRelTo="ABSOLUTE" height="(\d+)"',
                                      z.read("Contents/section0.xml").decode()).group(1))

    assert receipt.attach(out, folder) == 2

    rows, cols = _grid(out)                       # 격자에 겹침 · 빈칸 없음, rowCnt == 줄 수
    assert (rows, cols) == (rows_before + 2, 3)
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        assert infos[0].filename == "mimetype" and infos[0].compress_type == zipfile.ZIP_STORED
        names = z.namelist()
        assert "BinData/image1.jpg" in names and "BinData/image2.png" in names
        assert z.read("BinData/image1.jpg") == JPEG
        section = z.read("Contents/section0.xml").decode("utf-8")
        hpf = z.read("Contents/content.hpf").decode("utf-8")
        manifest = z.read("META-INF/manifest.xml").decode("utf-8")
        header = z.read("Contents/header.xml").decode("utf-8")
        for part in ("Contents/section0.xml", "Contents/content.hpf", "META-INF/manifest.xml", "Contents/header.xml"):
            minidom.parseString(z.read(part))     # 모두 바른 XML
    height = int(re.search(r'<hp:tbl .*?<hp:sz width="\d+" widthRelTo="ABSOLUTE" height="(\d+)"', section).group(1))
    assert height > height_before
    # 그림이 가리키는 id 가 content.hpf 에 내장 그림으로 있다
    refs = re.findall(r'binaryItemIDRef="([^"]+)"', section)
    assert refs == ["image1", "image2"]
    for ref, href, media in (("image1", "BinData/image1.jpg", "image/jpeg"), ("image2", "BinData/image2.png", "image/png")):
        assert f'<opf:item id="{ref}" href="{href}" media-type="{media}" isEmbeded="1"/>' in hpf
        assert f'full-path="{href}"' in manifest
    # '기타' 라벨은 왼쪽 칸 하나(영수증 수만큼 세로로 합침), 오른쪽에 '카드 사용 영수증 (1/2)'
    assert section.count("<hp:t>기타</hp:t>") == 1
    assert "<hp:t>카드 사용 영수증 (1/2)</hp:t>" in section and "<hp:t>카드 사용 영수증 (2/2)</hp:t>" in section
    assert re.search(r'<hp:cellAddr colAddr="0" rowAddr="%d"/><hp:cellSpan colSpan="1" rowSpan="2"/>' % rows_before, section)
    # 그림 크기는 비율 그대로(JPEG 30×60 → 세로가 가로의 두 배)
    first = re.search(r'<hp:pic .*?<hp:sz width="(\d+)" widthRelTo="ABSOLUTE" height="(\d+)"', section)
    assert int(first.group(2)) == 2 * int(first.group(1))
    # header 는 그대로 — 한컴이 저장한 파일처럼 binDataList 를 두지 않는다
    assert "binDataList" not in header


def test_card_flow_still_reads_minutes_without_extra_rows(tmp_path, no_qt):
    folder = meeting(tmp_path, {"1012 영수증.jpg": JPEG})
    out = built(tmp_path, folder)
    before = card.read_minutes(str(out))
    receipt.attach(out, folder)
    after = card.read_minutes(str(out))
    assert after.content == before.content and after.attendees == before.attendees
    assert not any("영수증" in p or p == "기타" for p in after.content)
    assert (after.amount, after.place, after.agenda, after.start, after.end) == \
        (before.amount, before.place, before.agenda, before.start, before.end)


def test_no_receipt_leaves_minutes_untouched(tmp_path, no_qt):
    folder = meeting(tmp_path, {"회의 사진.jpg": JPEG, "자료.txt": b"x"})
    out = built(tmp_path, folder)
    data = out.read_bytes()
    assert receipt.attach(out, folder) == 0
    assert out.read_bytes() == data


def test_pdf_receipt_without_qt_is_skipped_not_broken(tmp_path, no_qt):
    folder = meeting(tmp_path, {"1012 영수증.pdf": b"%PDF-1.4"})
    out = built(tmp_path, folder)
    data = out.read_bytes()
    assert receipt.attach(out, folder) == 0
    assert out.read_bytes() == data


def test_process_meeting_reports_receipts_and_survives_failure(tmp_path, no_qt, monkeypatch):
    folder = meeting(tmp_path, {"1012 영수증.jpg": JPEG, "자료.txt": b"x"})
    result = process.process_meeting(folder, FakeBackend(), "r")
    assert result.ok and result.receipts == 1
    _grid(Path(result.info))

    def broken(*_args):
        raise ValueError("고장")
    monkeypatch.setattr(process, "attach_receipts", broken)
    again = process.process_meeting(folder, FakeBackend(), "r")
    assert again.ok and again.receipts == 0                # 붙이다 실패해도 회의록은 남는다
    _grid(Path(again.info))
    assert not list(folder.glob(".회의록_*"))              # 임시 파일이 남지 않는다


def test_upright_exif_photo_with_qt(tmp_path, monkeypatch):
    """휴대폰 사진은 EXIF 회전으로 눕혀 저장된다 — 바로 세워 넣는다(QImage(경로) 는 회전을 무시한다)."""
    pytest.importorskip("PySide6")
    pil = pytest.importorskip("PIL.Image")
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])
    folder = tmp_path / "회의"
    folder.mkdir()
    image = pil.new("RGB", (400, 200), "white")
    for x in range(40, 360):                       # 여백 자르기가 지우지 않게 가운데에 내용
        for y in range(40, 160):
            image.putpixel((x, y), (30, 30, 30))
    exif = pil.Exif()
    exif[0x0112] = 6                               # 90° 돌려 보라
    image.save(folder / "영수증.jpg", exif=exif.tobytes())
    pictures, skipped = receipt.load_pictures([str(folder / "영수증.jpg")])
    assert not skipped and len(pictures) == 1
    assert pictures[0].ext == "jpg" and pictures[0].height > pictures[0].width
