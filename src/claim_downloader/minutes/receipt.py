"""회의록 아래 '기타' 칸에 카드 사용 영수증 그림을 붙인다 — 담당자 2026-11-11 "회의록 생성할때 자료중 카드사용영수증이 있으면
회의록 아래에 기타칸을 추가하고 영수증을 첨부해주세요".

hwpx.py 는 글자 하나 바꾸지 않는 파일이라(CLAUDE.md 13절) 만든 .hwpx 를 **뒤에서 고친다**: 표 맨 아래에 줄을 더하고
(왼쪽 '기타' 라벨은 영수증 수만큼 세로로 합침 · 오른쪽 두 칸을 합친 칸에 '카드 사용 영수증' 한 줄 + 그림), 그림은 BinData/ 에 넣어
content.hpf 에 올린다(한컴이 저장한 파일처럼 isEmbeded="1" · header 의 binDataList 는 두지 않는다). 영수증 하나가 줄 하나라
쪽이 넘어가도 줄 단위로 넘어간다. 고치다 실패하면 원래 회의록은 그대로 둔다(임시 파일에 쓰고 다 되면 바꿔치기).

영수증은 파일 이름으로 찾는다(영수증 · 매출전표 · 전표 · 카드 · 결제 · receipt — 회의록 · 서명부 · 공문 · 사진 … 이 든 이름은 빼고).
이름에 그런 말이 없는 PDF 는 글자에 승인번호 · 가맹점 같은 말이 둘 이상 있으면 영수증으로 본다. '기타' · '업로드' 폴더는 보지 않는다
(카드 결제 건 폴더의 '기타' 는 증빙이 아닌 파일을 모아 두는 곳 — 19절).

그림은 앱의 PySide6 로 읽는다 — 휴대폰 사진의 회전(EXIF)을 바로 세우고, PDF 는 쪽을 그려 영수증 상자 · 여백을 잘라 내고(출장증빙과 같은
travel.render.load_images), 긴 변 1600점 JPEG 로 줄인다. Qt 가 없으면(CI) JPEG · PNG 는 그대로 넣고 PDF 는 넣지 않는다.
"""
from __future__ import annotations

import os
import re
import struct
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .hwpx import HWPX_TBL_W, _hwpx_char_id, _hwpx_p, _hwpx_tc
from .logbook import log

EXTRA_LABEL = "기타"
CAPTION = "카드 사용 영수증"
RECEIPT_WORDS = ("영수증", "매출전표", "전표", "카드", "결제", "receipt")
NOT_RECEIPT_WORDS = ("회의록", "서명부", "공문", "계획", "결과", "사진", "구매의뢰", "명단", "뉴스")
TEXT_WORDS = ("승인번호", "카드번호", "가맹점", "결제금액", "승인금액", "매출전표", "영수증", "카드종류")
IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
SKIP_DIRS = ("기타", "업로드")
MAX_DEPTH = 3
MAX_PICTURES = 8            # 여러 쪽 PDF 가 회의록을 수십 쪽으로 늘리지 않게
MAX_PER_FILE = 4

# 단위 HWPUNIT(1/7200 인치). 오른쪽 칸 = 표 너비 - 왼쪽 라벨 칸(hwpx._hwpx_section_xml 과 같은 셈), 칸 안 여백 510 × 2.
_LABEL_W = int(round(HWPX_TBL_W * 1900 / 9200.0))
_CELL_W = HWPX_TBL_W - _LABEL_W
_INNER_W = _CELL_W - 1020
PIC_MAX_W = 34000           # 약 12cm
PIC_MAX_H = 45000           # 약 15.9cm — A4 본문(약 21.7cm) 안에 줄 하나가 들어가게
PX_TO_HU = 150              # 작은 그림을 너무 키우지 않게(96 DPI 의 두 배까지)
RH = 1700                   # hwpx.py 의 기본 행 높이
LONG_SIDE = 1600            # 넣을 그림의 긴 변(점)


@dataclass
class Picture:
    data: bytes
    ext: str                # jpg · png
    width: int              # 점
    height: int
    source: str = ""        # 원본 파일(기록용 — 이름은 남기지 않는다)


# ── 영수증 찾기 ───────────────────────────────────────────────────────────
def _receipt_name(name: str) -> bool:
    low = name.lower()
    return any(w in low for w in RECEIPT_WORDS) and not any(w in name for w in NOT_RECEIPT_WORDS)


def _pdf_looks_like_receipt(path: str) -> bool:
    try:
        from pypdf import PdfReader
        reader = PdfReader(path)
        text = "".join((page.extract_text() or "") for page in reader.pages[:2])
    except Exception:  # noqa: BLE001 — 못 읽는 PDF 는 영수증으로 보지 않는다
        return False
    flat = re.sub(r"\s+", "", text)
    return sum(1 for w in TEXT_WORDS if w in flat) >= 2


def find_receipts(meeting_dir: str | Path) -> list[str]:
    """회의 폴더(하위 폴더 포함 · '기타' · '업로드' 빼고)에서 카드 영수증 파일들 — 이름 차례."""
    base = str(meeting_dir)
    out: list[str] = []
    for root, dirs, files in os.walk(base):
        depth = os.path.relpath(root, base).count(os.sep) + (0 if root == base else 1)
        dirs[:] = sorted(d for d in dirs if d.strip() not in SKIP_DIRS and depth < MAX_DEPTH)
        for name in sorted(files):
            path = os.path.join(root, name)
            suffix = os.path.splitext(name)[1].lower()
            if suffix in IMAGE_SUFFIXES and _receipt_name(name):
                out.append(path)
            elif suffix == ".pdf" and not any(w in name for w in NOT_RECEIPT_WORDS):
                if _receipt_name(name) or _pdf_looks_like_receipt(path):
                    out.append(path)
    return out


# ── 그림 읽기 ─────────────────────────────────────────────────────────────
def _png_size(data: bytes) -> tuple[int, int] | None:
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + length
    return None


def _raw_picture(path: str) -> Picture | None:
    """Qt 없이 — JPEG · PNG 를 그대로(크기는 머리에서 읽음)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    for ext, size in (("png", _png_size(data)), ("jpg", _jpeg_size(data))):
        if size and size[0] > 0 and size[1] > 0:
            return Picture(data, ext, size[0], size[1], path)
    return None


def _qt_ready() -> bool:
    try:
        from PySide6.QtCore import QCoreApplication
    except ImportError:
        return False
    return QCoreApplication.instance() is not None


def _qt_pictures(path: str) -> list[Picture]:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QColor, QImage, QImageReader, QPainter

    from ..travel.render import load_images, trim
    if path.lower().endswith(".pdf"):
        images = load_images(Path(path))          # 쪽마다 영수증 상자(있으면) · 여백 자르기
    else:
        reader = QImageReader(path)
        reader.setAutoTransform(True)             # 휴대폰 사진의 회전(EXIF) — QImage(경로) 는 무시한다
        image = reader.read()
        images = [] if image.isNull() else [trim(image)]
    out = []
    for image in images[:MAX_PER_FILE]:
        if image.isNull() or image.width() < 8 or image.height() < 8:
            continue
        if max(image.width(), image.height()) > LONG_SIDE:
            image = image.scaled(LONG_SIDE, LONG_SIDE, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        flat = QImage(image.size(), QImage.Format_RGB32)    # 투명한 곳은 흰 바탕(JPEG 에는 투명이 없다)
        flat.fill(QColor("white"))
        painter = QPainter(flat)
        painter.drawImage(0, 0, image)
        painter.end()
        raw = QByteArray()
        buffer = QBuffer(raw)
        buffer.open(QIODevice.WriteOnly)
        flat.save(buffer, "JPG", 85)
        buffer.close()
        if raw.size():
            out.append(Picture(bytes(raw.data()), "jpg", flat.width(), flat.height(), path))
    return out


def load_pictures(paths: list[str]) -> tuple[list[Picture], list[str]]:
    """영수증 파일들 → 넣을 그림들 · 넣지 못한 까닭(파일 이름 없이)."""
    pictures: list[Picture] = []
    skipped: list[str] = []
    qt = _qt_ready()
    for path in paths:
        if len(pictures) >= MAX_PICTURES:
            skipped.append(f"그림이 {MAX_PICTURES}장을 넘어 나머지는 넣지 않음")
            break
        got: list[Picture] = []
        try:
            if qt:
                got = _qt_pictures(path)
            elif not path.lower().endswith(".pdf"):
                one = _raw_picture(path)
                got = [one] if one else []
            else:
                skipped.append("PDF 영수증은 그림으로 바꿀 수 없어(화면 없이 실행) 넣지 않음")
                continue
        except Exception as error:  # noqa: BLE001 — 그림 하나가 회의록을 막지 않게
            log(f"영수증 그림을 읽지 못함({os.path.splitext(path)[1]}): {type(error).__name__}: {error}")
        if not got:
            skipped.append(f"읽지 못한 영수증 파일({os.path.splitext(path)[1]})")
        pictures += got[:MAX_PICTURES - len(pictures)]
    return pictures, skipped


# ── .hwpx 고치기 ──────────────────────────────────────────────────────────
def fit(width: int, height: int) -> tuple[int, int]:
    """점 크기 → 칸 안에 들어갈 HWPUNIT 크기(비율 그대로)."""
    scale = min(PIC_MAX_W / width, PIC_MAX_H / height, PX_TO_HU)
    return max(1, int(width * scale)), max(1, int(height * scale))


def _pic_xml(item_id: str, width: int, height: int, number: int) -> str:
    """한 줄에 놓이는(글자처럼 취급) 그림 — python-hwpx 가 한컴 파일에서 본 모양과 같은 차례 · 속성."""
    oid = 1900000000 + number
    ident = 'e1="1" e2="0" e3="0" e4="0" e5="1" e6="0"'
    return (f'<hp:pic id="{oid}" zOrder="{number}" numberingType="PICTURE" textWrap="TOP_AND_BOTTOM"'
            f' textFlow="BOTH_SIDES" lock="0" dropcapstyle="None" href="" groupLevel="0" instid="{oid}" reverse="0">'
            f'<hp:offset x="0" y="0"/><hp:orgSz width="{width}" height="{height}"/>'
            f'<hp:curSz width="{width}" height="{height}"/><hp:flip horizontal="0" vertical="0"/>'
            f'<hp:rotationInfo angle="0" centerX="{width // 2}" centerY="{height // 2}" rotateimage="1"/>'
            f'<hp:renderingInfo><hc:transMatrix {ident}/><hc:scaMatrix {ident}/><hc:rotMatrix {ident}/></hp:renderingInfo>'
            f'<hp:imgRect><hc:pt0 x="0" y="0"/><hc:pt1 x="{width}" y="0"/><hc:pt2 x="{width}" y="{height}"/>'
            f'<hc:pt3 x="0" y="{height}"/></hp:imgRect>'
            f'<hp:imgClip left="0" right="{width}" top="0" bottom="{height}"/>'
            '<hp:inMargin left="0" right="0" top="0" bottom="0"/>'
            f'<hp:imgDim dimwidth="{width}" dimheight="{height}"/>'
            f'<hc:img binaryItemIDRef="{item_id}" bright="0" contrast="0" effect="REAL_PIC" alpha="0"/>'
            '<hp:effects/>'
            f'<hp:sz width="{width}" widthRelTo="ABSOLUTE" height="{height}" heightRelTo="ABSOLUTE" protect="0"/>'
            '<hp:pos treatAsChar="1" affectLSpacing="0" flowWithText="1" allowOverlap="0" holdAnchorAndSO="0"'
            ' vertRelTo="PARA" horzRelTo="COLUMN" vertAlign="TOP" horzAlign="LEFT" vertOffset="0" horzOffset="0"/>'
            '<hp:outMargin left="0" right="0" top="0" bottom="0"/><hp:shapeComment/></hp:pic>')


def _pic_paragraph(pic: str, height: int) -> str:
    return ('<hp:p id="0" paraPrIDRef="1" styleIDRef="0" pageBreak="0" columnBreak="0" merged="0">'
            f'<hp:run charPrIDRef="{_hwpx_char_id(False, 22)}">{pic}</hp:run>'
            f'<hp:linesegarray><hp:lineseg textpos="0" vertpos="0" vertsize="{height}" textheight="{height}"'
            f' baseline="{int(height * 0.85)}" spacing="600" horzpos="0" horzsize="{_INNER_W}" flags="393216"/>'
            '</hp:linesegarray></hp:p>')


def extra_rows(start_row: int, sizes: list[tuple[str, int, int]]) -> tuple[str, int]:
    """'기타' 줄들의 XML · 더한 높이. sizes = [(그림 id, 너비, 높이), …] — 그림 하나가 줄 하나."""
    label = _hwpx_char_id(True, 22)
    body = _hwpx_char_id(False, 22)
    rows, total = "", 0
    count = len(sizes)
    for i, (item_id, width, height) in enumerate(sizes):
        caption = CAPTION + (f" ({i + 1}/{count})" if count > 1 else "")
        row_h = height + RH + 400
        cells = []
        if i == 0:
            cells.append(_hwpx_tc(_hwpx_p(EXTRA_LABEL, label, 1), 0, start_row, 1, count, _LABEL_W, RH, shade=True))
        paras = _hwpx_p(caption, body, 0) + _pic_paragraph(_pic_xml(item_id, width, height, i + 1), height)
        cells.append(_hwpx_tc(paras, 1, start_row + i, 2, 1, _CELL_W, row_h))
        rows += "<hp:tr>" + "".join(cells) + "</hp:tr>"
        total += row_h
    return rows, total


def _add_rows(section: str, pictures: list[tuple[str, int, int]]) -> str:
    start = section.find("<hp:tbl ")
    end = section.rfind("</hp:tbl>")
    first_row = section.find("<hp:tr>", start)
    if start < 0 or end < 0 or first_row < 0 or section.count("<hp:tbl ") != 1:
        raise ValueError("회의록 표를 찾지 못함")
    head = section[start:first_row]
    rows_now = re.search(r'rowCnt="(\d+)"', head)
    size = re.search(r'(<hp:sz width="\d+" widthRelTo="ABSOLUTE" height=")(\d+)(")', head)
    if not rows_now or not size:
        raise ValueError("회의록 표의 줄 수 · 높이를 읽지 못함")
    count = int(rows_now.group(1))
    rows, added = extra_rows(count, pictures)
    head = head.replace(rows_now.group(0), f'rowCnt="{count + len(pictures)}"', 1)
    head = head.replace(size.group(0), f"{size.group(1)}{int(size.group(2)) + added}{size.group(3)}", 1)
    return section[:start] + head + section[first_row:end] + rows + section[end:]


MEDIA = {"jpg": "image/jpeg", "png": "image/png"}


def attach(hwpx_path: str | Path, meeting_dir: str | Path) -> int:
    """만든 회의록(.hwpx)에 회의 폴더의 카드 영수증을 '기타' 칸으로 붙인다. 돌려주는 값은 붙인 그림 수(없으면 0, 회의록은 그대로)."""
    paths = find_receipts(meeting_dir)
    if not paths:
        return 0
    pictures, skipped = load_pictures(paths)
    for why in dict.fromkeys(skipped):
        log("회의록 '기타' 칸: " + why)
    if not pictures:
        return 0
    hwpx_path = str(hwpx_path)
    with zipfile.ZipFile(hwpx_path) as z:
        entries = [(info, z.read(info.filename)) for info in z.infolist()]
    parts = {info.filename: data for info, data in entries}
    used = set(parts)
    items: list[tuple[str, str, Picture]] = []          # (id, 경로, 그림)
    n = 0
    for picture in pictures:
        n += 1
        while f"BinData/image{n}.{picture.ext}" in used:
            n += 1
        items.append((f"image{n}", f"BinData/image{n}.{picture.ext}", picture))
    sizes = [(item_id, *fit(p.width, p.height)) for item_id, _href, p in items]
    section = _add_rows(parts["Contents/section0.xml"].decode("utf-8"), sizes)
    hpf = parts["Contents/content.hpf"].decode("utf-8")
    if "</opf:manifest>" not in hpf:
        raise ValueError("content.hpf 에 manifest 가 없음")
    hpf = hpf.replace("</opf:manifest>", "".join(
        f'<opf:item id="{item_id}" href="{href}" media-type="{MEDIA[p.ext]}" isEmbeded="1"/>'
        for item_id, href, p in items) + "</opf:manifest>", 1)
    manifest = parts.get("META-INF/manifest.xml", b"").decode("utf-8")
    if "</odf:manifest>" in manifest:
        manifest = manifest.replace("</odf:manifest>", "".join(
            f'<odf:file-entry full-path="{href}" media-type="{MEDIA[p.ext]}"/>'
            for _id, href, p in items) + "</odf:manifest>", 1)
    changed = {"Contents/section0.xml": section.encode("utf-8"), "Contents/content.hpf": hpf.encode("utf-8")}
    if manifest:
        changed["META-INF/manifest.xml"] = manifest.encode("utf-8")
    folder = os.path.dirname(os.path.abspath(hwpx_path))
    fd, tmp = tempfile.mkstemp(prefix=".회의록_", suffix=".hwpx", dir=folder)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for info, data in entries:
                data = changed.get(info.filename, data)
                if info.filename == "mimetype":        # 첫 항목 · 무압축(hwpx.py 와 같이)
                    z.writestr(zipfile.ZipInfo("mimetype"), data, compress_type=zipfile.ZIP_STORED)
                else:
                    z.writestr(info.filename, data)
            for _id, href, picture in items:          # JPEG · PNG 는 더 줄지 않는다
                z.writestr(href, picture.data, compress_type=zipfile.ZIP_STORED)
        os.replace(tmp, hwpx_path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    log(f"회의록 '기타' 칸에 카드 영수증 {len(items)}장을 붙였습니다 (영수증 파일 {len(paths)}개)")
    return len(items)
