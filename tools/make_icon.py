"""앱 아이콘 생성기 — 담당자가 고른 디자인(2026-10-12)을 그대로 그린다.

흰 무광 둥근 판 위에 파스텔 타일 넷. 타일마다 흰 선 그림 하나.
  왼쪽 위   라벤더  내려받기(트레이 + 아래 화살표)  → 청구서 받기
  오른쪽 위 민트    펼친 책                         → 회의록 생성
  왼쪽 아래 피치    체크 표시가 있는 문서            → 일반청구
  오른쪽 아래 블루  카드                            → 카드청구

assets/icon-source.png 가 있으면 그것을 원본으로 쓴다. 지금 원본은 2026-10-14 담당자가 보낸 새 디자인
(흰 입체 둥근 판 위에 라벤더 'C' + 민트 점, 바탕 투명)에서 옅은 바닥 그림자와 바깥 여백을 잘라 판이 꽉 차게 한 것이다
(비율·색은 그대로, 판 안쪽 알파 253 은 255 로 채움 — 작업 표시줄 바탕이 비치지 않게). 아래 도형 그리기(타일 넷)는
그 파일이 없을 때의 대비책으로 남은 옛 디자인이다.

디자인을 바꿀 때만 돌린다:

    python tools/make_icon.py

생성 파일:
    src/claim_downloader/ui/assets/icon.png             (256px)
    src/claim_downloader/ui/assets/icon.ico             (16~256px, 창 아이콘 · 옛 바로가기)
    src/claim_downloader/ui/assets/<settings.SHORTCUT_ICON> (icon.ico 와 같은 그림 — 바로가기 · 작업 표시줄 고정용)

디자인을 바꾸면 settings.SHORTCUT_ICON 의 이름부터 바꾼다 — 윈도우가 아이콘을 파일 경로로 저장해 두어서, 같은 이름이면
작업 표시줄에 고정할 때 옛 그림이 뜬다(2026-10-14). 옛 이름의 파일은 지운다(옛 바로가기는 icon.ico 를 본다).
    src/claim_downloader/ui/assets/icons/icon-<크기>.png (창 아이콘 · 상단 바 로고, 크기별)
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from claim_downloader.settings import SHORTCUT_ICON  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui" / "assets"
SOURCE = ASSETS / "icon-source.png"      # 원본 PNG 가 있으면 이것을 쓴다

SS = 4
SIZES = [16, 24, 32, 48, 64, 128, 256]

PLATE = (248, 247, 245)
PLATE_EDGE = (224, 222, 218)
SHADOW = (35, 42, 52)
TILES = {                      # (윗면, 아래쪽 두께 면)
    "lavender": ((190, 168, 238), (160, 138, 220)),
    "mint":     ((150, 222, 186), (116, 192, 156)),
    "peach":    ((248, 178, 140), (230, 150, 112)),
    "sky":      ((116, 196, 236), (82, 166, 212)),
}
GLYPH = (255, 255, 255)
GLYPH_SHADE = (120, 110, 150)   # 선 아래 옅은 그늘 — 타일마다 색이 달라 중간 보라회색으로


def _plate(canvas: Image.Image) -> None:
    big = canvas.width
    inset = round(big * 0.07)
    box = (inset, inset, big - inset, big - inset)
    radius = round(big * 0.23)
    # 바닥 그림자
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + round(big * 0.035), box[2], box[3] + round(big * 0.035)), radius,
        fill=SHADOW + (44,))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.03)))
    # 둘레 반사광 — 왼쪽 라벤더, 위 민트·노랑, 오른쪽 피치 (판보다 조금 크게 깔고 판으로 덮는다)
    rim = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    grow = round(big * 0.012)
    rbox = (box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow)
    rd.rounded_rectangle(rbox, radius + grow, fill=(255, 220, 200, 255))          # 피치 (바탕)
    rd.rounded_rectangle((rbox[0], rbox[1], (rbox[0] + rbox[2]) / 2, rbox[3]), radius + grow,
                         fill=(214, 200, 250, 255))                                 # 왼쪽 라벤더
    rd.rounded_rectangle((rbox[0] + big * 0.3, rbox[1], rbox[2] - big * 0.25, rbox[1] + big * 0.3),
                         radius + grow, fill=(200, 242, 216, 255))                  # 위 민트
    rim = rim.filter(ImageFilter.GaussianBlur(big * 0.008))
    rim.putalpha(ImageChops.darker(rim.getchannel("A"), _mask(big, rbox, radius + grow)))
    canvas.alpha_composite(rim)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=PLATE_EDGE + (255,))
    # 윗면: 아래 가장자리에 두께가 살짝 보이게 2% 덜 내려 그린다
    draw.rounded_rectangle((box[0], box[1], box[2], box[3] - round(big * 0.02)), radius, fill=PLATE + (255,))


def _mask(size: int, box, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    return mask


def _tile(canvas: Image.Image, box, color) -> None:
    big = canvas.width
    radius = round((box[2] - box[0]) * 0.28)
    top, side = color
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + big * 0.015, box[2], box[3] + big * 0.015), radius, fill=SHADOW + (44,))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.012)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=side + (255,))
    draw.rounded_rectangle((box[0], box[1], box[2], box[3] - big * 0.012), radius, fill=top + (255,))
    # 왼쪽 위 하이라이트 — 흰색을 옅게 흐려 얹는다 (무광 클레이의 둥근 느낌)
    glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    w = box[2] - box[0]
    gd.ellipse((box[0] + w * 0.08, box[1] + w * 0.06, box[0] + w * 0.62, box[1] + w * 0.42), fill=(255, 255, 255, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(w * 0.12))
    glow.putalpha(ImageChops.darker(glow.getchannel("A"), _mask(big, box, radius)))
    canvas.alpha_composite(glow)
    # 아래쪽 살짝 어두운 면
    shade = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shade).ellipse((box[0] + w * 0.1, box[3] - w * 0.3, box[2] - w * 0.05, box[3] + w * 0.1),
                                  fill=side + (70,))
    shade = shade.filter(ImageFilter.GaussianBlur(w * 0.12))
    shade.putalpha(ImageChops.darker(shade.getchannel("A"), _mask(big, box, radius)))
    canvas.alpha_composite(shade)


def _glyphs(canvas: Image.Image, tiles: dict) -> None:
    """타일 안 흰 선 그림. 선 굵기는 타일 폭의 8.5%, 끝은 둥글게. 선 아래 옅은 그늘로 도톰하게."""
    draw = ImageDraw.Draw(canvas)

    def pen(box):
        return max(2, round((box[2] - box[0]) * 0.085))

    def u(box, x, y):
        w = box[2] - box[0]
        return (box[0] + w * x, box[1] + w * y)

    def stroke(box, points, close=False):
        w = pen(box)
        pts = list(points) + ([points[0]] if close else [])
        dy = w * 0.22
        for color, off in ((GLYPH_SHADE, dy), (GLYPH, 0)):
            moved = [(x, y + off) for x, y in pts]
            draw.line(moved, fill=color, width=w, joint="curve")
            for p in moved:                 # 둥근 끝
                draw.ellipse((p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2), fill=color)

    # 내려받기
    b = tiles["lavender"]
    stroke(b, [u(b, .5, .22), u(b, .5, .58)])
    stroke(b, [u(b, .36, .45), u(b, .5, .6), u(b, .64, .45)])
    stroke(b, [u(b, .26, .62), u(b, .26, .76), u(b, .74, .76), u(b, .74, .62)])

    # 펼친 책
    b = tiles["mint"]
    stroke(b, [u(b, .22, .28), u(b, .47, .34), u(b, .47, .76), u(b, .22, .70)], close=True)
    stroke(b, [u(b, .78, .28), u(b, .53, .34), u(b, .53, .76), u(b, .78, .70)], close=True)
    stroke(b, [u(b, .60, .46), u(b, .71, .43)])
    stroke(b, [u(b, .60, .57), u(b, .71, .54)])

    # 체크 문서
    b = tiles["peach"]
    stroke(b, [u(b, .30, .22), u(b, .58, .22), u(b, .72, .36), u(b, .72, .78), u(b, .30, .78)], close=True)
    stroke(b, [u(b, .58, .22), u(b, .58, .36), u(b, .72, .36)])
    stroke(b, [u(b, .40, .56), u(b, .48, .64), u(b, .62, .48)])

    # 카드
    b = tiles["sky"]
    w = pen(b)
    cw = b[2] - b[0]
    for color, off in ((GLYPH_SHADE, w * 0.22), (GLYPH, 0)):
        draw.rounded_rectangle((b[0] + cw * .22, b[1] + cw * .32 + off, b[0] + cw * .78, b[1] + cw * .68 + off),
                               round(cw * .07), outline=color, width=w)
    stroke(b, [u(b, .22, .44), u(b, .78, .44)])
    stroke(b, [u(b, .32, .58), u(b, .44, .58)])


def draw_icon(size: int) -> Image.Image:
    if SOURCE.exists():
        return Image.open(SOURCE).convert("RGBA").resize((size, size), Image.LANCZOS)
    big = size * SS
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    _plate(canvas)
    # 타일 격자: 판 안쪽을 2×2 로 나눈다
    inner0, inner1 = big * 0.165, big * 0.835
    gap = big * 0.035
    half = (inner1 - inner0 - gap) / 2
    boxes = {}
    for name, (r, c) in {"lavender": (0, 0), "mint": (0, 1), "peach": (1, 0), "sky": (1, 1)}.items():
        x0 = inner0 + c * (half + gap)
        y0 = inner0 + r * (half + gap) - big * 0.01
        boxes[name] = (x0, y0, x0 + half, y0 + half)
        _tile(canvas, boxes[name], TILES[name])
    _glyphs(canvas, boxes)
    return canvas.resize((size, size), Image.LANCZOS)


def main() -> None:
    frames = {s: draw_icon(s) for s in SIZES}
    frames[256].save(ASSETS / "icon.png")
    # ICO 는 크기마다 따로 그린 그림을 담는다. 큰 그림 하나를 줄이게 두면 16px 가 뭉개진다.
    for name in ("icon.ico", SHORTCUT_ICON):
        frames[256].save(ASSETS / name, format="ICO", sizes=[(s, s) for s in SIZES],
                         append_images=[frames[s] for s in SIZES if s != 256])
    for old in ASSETS.glob("icon-*.ico"):          # 옛 디자인의 바로가기용 파일
        if old.name != SHORTCUT_ICON:
            old.unlink()
    (ASSETS / "icons").mkdir(exist_ok=True)
    for s in SIZES:
        frames[s].save(ASSETS / "icons" / f"icon-{s}.png")
    print("만들었습니다:", ASSETS / "icon.png", ASSETS / "icon.ico", ASSETS / SHORTCUT_ICON)


if __name__ == "__main__":
    main()
