"""앱 아이콘 생성기 — 담당자가 고른 디자인(2026-10-12)을 그대로 그린다.

흰 무광 둥근 판 위에 파스텔 타일 넷. 타일마다 흰 선 그림 하나.
  왼쪽 위   라벤더  내려받기(트레이 + 아래 화살표)  → 청구서 받기
  오른쪽 위 민트    펼친 책                         → 회의록 생성
  왼쪽 아래 피치    체크 표시가 있는 문서            → 일반청구
  오른쪽 아래 블루  카드                            → 카드청구

담당자가 보낸 이미지는 화면 미리 보기로만 받아 파일이 없다. 그래서 같은 구성을 도형으로
다시 그렸다. 도형이라 16px 까지 깨끗하게 줄어드는 장점이 있다. 원본 PNG 를 받으면
assets/icon-source.png 로 두면(투명 배경 권장) 그 그림을 대신 쓴다.

디자인을 바꿀 때만 돌린다:

    python tools/make_icon.py

생성 파일:
    src/claim_downloader/ui/assets/icon.png             (256px)
    src/claim_downloader/ui/assets/icon.ico             (16~256px, 바로가기·작업 표시줄)
    src/claim_downloader/ui/assets/icons/icon-<크기>.png (창 아이콘 · 상단 바 로고, 크기별)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui" / "assets"
SOURCE = ASSETS / "icon-source.png"      # 원본 PNG 가 있으면 이것을 쓴다

SS = 4
SIZES = [16, 24, 32, 48, 64, 128, 256]

PLATE = (248, 247, 245)
PLATE_EDGE = (224, 222, 218)
SHADOW = (35, 42, 52)
TILES = {                      # (윗면, 아래쪽 두께 면)
    "lavender": ((196, 178, 236), (168, 148, 218)),
    "mint":     ((160, 220, 190), (126, 194, 162)),
    "peach":    ((246, 190, 158), (230, 160, 124)),
    "sky":      ((118, 200, 230), (86, 170, 208)),
}
GLYPH = (255, 255, 255)


def _plate(canvas: Image.Image) -> None:
    big = canvas.width
    inset = round(big * 0.07)
    box = (inset, inset, big - inset, big - inset)
    radius = round(big * 0.23)
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + round(big * 0.035), box[2], box[3] + round(big * 0.035)), radius,
        fill=SHADOW + (46,))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.03)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=PLATE_EDGE + (255,))
    # 윗면: 아래 가장자리에 두께가 살짝 보이게 2% 덜 내려 그린다
    draw.rounded_rectangle((box[0], box[1], box[2], box[3] - round(big * 0.02)), radius, fill=PLATE + (255,))


def _tile(canvas: Image.Image, box, color) -> None:
    big = canvas.width
    radius = round((box[2] - box[0]) * 0.28)
    top, side = color
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + big * 0.015, box[2], box[3] + big * 0.015), radius, fill=SHADOW + (40,))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.012)))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=side + (255,))
    draw.rounded_rectangle((box[0], box[1], box[2], box[3] - big * 0.012), radius, fill=top + (255,))


def _glyphs(canvas: Image.Image, tiles: dict) -> None:
    """타일 안 흰 선 그림. 선 굵기는 타일 폭의 7%, 끝은 둥글게."""
    draw = ImageDraw.Draw(canvas)

    def pen(box):
        return max(2, round((box[2] - box[0]) * 0.07))

    def u(box, x, y):
        w = box[2] - box[0]
        return (box[0] + w * x, box[1] + w * y)

    def stroke(box, points, close=False):
        w = pen(box)
        pts = list(points) + ([points[0]] if close else [])
        draw.line(pts, fill=GLYPH, width=w, joint="curve")
        for p in pts:                       # 둥근 끝
            draw.ellipse((p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2), fill=GLYPH)

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
    draw.rounded_rectangle((b[0] + cw * .22, b[1] + cw * .32, b[0] + cw * .78, b[1] + cw * .68),
                           round(cw * .07), outline=GLYPH, width=w)
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
    frames[256].save(ASSETS / "icon.ico", format="ICO", sizes=[(s, s) for s in SIZES],
                     append_images=[frames[s] for s in SIZES if s != 256])
    (ASSETS / "icons").mkdir(exist_ok=True)
    for s in SIZES:
        frames[s].save(ASSETS / "icons" / f"icon-{s}.png")
    print("만들었습니다:", ASSETS / "icon.png", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
