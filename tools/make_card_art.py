"""(보관용) 카드청구 입체 그림을 도형으로 그리던 도구.

2026-10-12 담당자가 원본 그림 파일을 보내 와 assets/art/card-receipt.png 는 그 원본이다.
이 도구는 원본을 다시 받지 못할 때를 위해 남겨 둔다. 지금은 돌리지 않는다.

원래 설명:
카드청구 입체 그림 만들기 — 담당자가 보낸 참고 그림(흰 영수증 뒤에 놓인 흰 카드)을 도형으로 옮긴다.

    python tools/make_card_art.py

담당자의 원본 PNG 는 채팅에 그림으로만 와서 파일을 받지 못했다. 그래서 같은 구성을 그린다.
  - 뒤: 위가 살짝 말리고 오른쪽 위 모서리가 접힌 흰 영수증, 회색 줄 두 개, 왼쪽으로 기울어짐
  - 앞: 둥근 흰 카드, 라벤더 → 하늘 → 민트로 흐르는 띠, 라벤더 IC 칩, 짧은 줄 두 개
  - 왼쪽 위에서 오는 빛, 가장자리에 라벤더·피치 반사광, 아래로 넓고 옅은 그림자
흰 바탕 사각 캔버스 + 가장자리 투명 풀기 — tools/make_art.py 로 만든 다른 그림과 같은 규격.

원본 파일을 받으면 assets/art/card-receipt.png 를 그 파일로 바꾸기만 하면 된다(정사각, 흰 바탕).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui" / "assets" / "art"
SIDE = 200
SS = 4
FEATHER = 0.06

WHITE = (255, 255, 255)
PAPER = (250, 250, 250)
PAPER_SIDE = (222, 224, 230)
CARD_SIDE = (214, 218, 228)
LINE = (214, 217, 224)
CHIP = (206, 190, 243)
CHIP_SIDE = (176, 158, 226)
CHIP_LINE = (236, 229, 252)
LAVENDER = (196, 184, 244)
SKY = (158, 214, 246)
MINT = (176, 240, 206)
RIM_L = (214, 204, 250)
RIM_R = (255, 226, 206)
SHADOW = (49, 65, 110)


def _blur_shadow(size, box, radius, blur, alpha, dy):
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle((box[0], box[1] + dy, box[2], box[3] + dy), radius,
                                            fill=SHADOW + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _gradient(w, h, stops):
    """가로 그라데이션. stops = [(위치 0~1, (r,g,b)), ...]"""
    xs = np.linspace(0, 1, w)
    cols = np.zeros((w, 3))
    for i in range(len(stops) - 1):
        p0, c0 = stops[i]
        p1, c1 = stops[i + 1]
        m = (xs >= p0) & (xs <= p1)
        t = ((xs[m] - p0) / max(p1 - p0, 1e-6))[:, None]
        cols[m] = np.array(c0) * (1 - t) + np.array(c1) * t
    rgb = np.repeat(cols[None, :, :], h, axis=0).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, np.full((h, w, 1), 255, np.uint8)]), "RGBA")


def _rounded_mask(size, box, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius, fill=255)
    return mask


def draw() -> Image.Image:
    big = SIDE * SS
    u = big / 100
    canvas = Image.new("RGBA", (big, big), WHITE + (255,))

    # ── 뒤: 영수증 ──────────────────────────────────────────────────
    paper = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pd = ImageDraw.Draw(paper)
    pbox = (26 * u, 18 * u, 70 * u, 70 * u)
    pr = 5 * u
    pd.rounded_rectangle((pbox[0], pbox[1] + 1.6 * u, pbox[2] + 1.0 * u, pbox[3] + 1.6 * u), pr, fill=PAPER_SIDE)  # 두께
    pd.rounded_rectangle(pbox, pr, fill=PAPER)
    # 위쪽 말림 — 윗부분을 조금 밝은 띠와 그 아래 옅은 그늘로
    pd.rounded_rectangle((pbox[0], pbox[1], pbox[2], pbox[1] + 7 * u), pr, fill=WHITE)
    pd.rectangle((pbox[0] + 0.5 * u, pbox[1] + 6.5 * u, pbox[2] - 0.5 * u, pbox[1] + 8.5 * u), fill=(238, 239, 243))
    # 오른쪽 위 접힌 모서리
    fold = 10 * u
    pd.polygon([(pbox[2] - fold, pbox[1]), (pbox[2], pbox[1] + fold), (pbox[2], pbox[1])], fill=WHITE)
    pd.polygon([(pbox[2] - fold, pbox[1]), (pbox[2] - fold, pbox[1] + fold), (pbox[2], pbox[1] + fold)],
               fill=(232, 233, 238))
    for i, (x0, x1) in enumerate([(33, 56), (33, 48)]):
        y = pbox[1] + 15 * u + i * 7 * u
        pd.rounded_rectangle((x0 * u, y, x1 * u, y + 2.6 * u), 1.3 * u, fill=LINE)
    angle = 10
    center = ((pbox[0] + pbox[2]) / 2, (pbox[1] + pbox[3]) / 2)
    canvas.alpha_composite(_blur_shadow(big, pbox, pr, 4 * u, 40, int(4 * u))
                           .rotate(angle, resample=Image.BICUBIC, center=center))
    canvas.alpha_composite(paper.rotate(angle, resample=Image.BICUBIC, center=center))

    # ── 앞: 카드 ────────────────────────────────────────────────────
    card = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cbox = (30 * u, 42 * u, 90 * u, 86 * u)
    cr = 7 * u
    # 반사광: 왼쪽은 라벤더, 오른쪽 아래는 피치 — 카드보다 조금 큰 테두리를 깔고 카드로 덮는다
    cd.rounded_rectangle((cbox[0] - 1.2 * u, cbox[1] - 0.6 * u, cbox[2] + 1.2 * u, cbox[3] + 1.2 * u), cr, fill=RIM_R)
    cd.rounded_rectangle((cbox[0] - 1.2 * u, cbox[1] - 0.6 * u, cbox[0] + 30 * u, cbox[3] + 1.2 * u), cr, fill=RIM_L)
    cd.rounded_rectangle((cbox[0], cbox[1] + 1.4 * u, cbox[2] + 0.8 * u, cbox[3] + 1.4 * u), cr, fill=CARD_SIDE)  # 두께
    cd.rounded_rectangle(cbox, cr, fill=WHITE)
    # 띠: 라벤더 → 하늘 → 민트
    stripe_h = int(11 * u)
    stripe = _gradient(int(cbox[2] - cbox[0]) + 2, stripe_h, [(0, LAVENDER), (0.5, SKY), (1, MINT)])
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    layer.paste(stripe, (int(cbox[0]), int(cbox[1] + 12 * u)))
    layer.putalpha(ImageChops.darker(layer.getchannel("A"), _rounded_mask(big, cbox, cr)))
    card.alpha_composite(layer)
    # 띠 아래 얇은 그늘(두께감)
    cd = ImageDraw.Draw(card)
    cd.rectangle((cbox[0] + 0.6 * u, cbox[1] + 12 * u + stripe_h, cbox[2] - 0.6 * u, cbox[1] + 12 * u + stripe_h + 1.2 * u),
                 fill=(236, 238, 244))
    # IC 칩
    chip = (cbox[0] + 8 * u, cbox[1] + 27 * u, cbox[0] + 21 * u, cbox[1] + 37 * u)
    cd.rounded_rectangle((chip[0], chip[1] + 0.9 * u, chip[2] + 0.6 * u, chip[3] + 0.9 * u), 2.4 * u, fill=CHIP_SIDE)
    cd.rounded_rectangle(chip, 2.4 * u, fill=CHIP)
    w = max(2, int(0.7 * u))
    cd.line([(chip[0] + 6 * u, chip[1]), (chip[0] + 6 * u, chip[3])], fill=CHIP_LINE, width=w)
    cd.line([(chip[0], chip[1] + 3.4 * u), (chip[2], chip[1] + 3.4 * u)], fill=CHIP_LINE, width=w)
    cd.line([(chip[0], chip[1] + 6.6 * u), (chip[2], chip[1] + 6.6 * u)], fill=CHIP_LINE, width=w)
    # 짧은 줄 두 개
    for x0, x1 in ((58, 69), (72, 84)):
        y = cbox[1] + 31 * u
        cd.rounded_rectangle((cbox[0] + (x0 - 30) * u, y, cbox[0] + (x1 - 30) * u, y + 2.4 * u), 1.2 * u, fill=LINE)
    angle = -7
    center = ((cbox[0] + cbox[2]) / 2, (cbox[1] + cbox[3]) / 2)
    canvas.alpha_composite(_blur_shadow(big, cbox, cr, 6 * u, 54, int(6 * u))
                           .rotate(angle, resample=Image.BICUBIC, center=center))
    canvas.alpha_composite(card.rotate(angle, resample=Image.BICUBIC, center=center))

    rgb = np.asarray(canvas.convert("RGB")).astype(np.uint8)
    gy, gx = np.mgrid[0:big, 0:big]
    edge = np.minimum.reduce([gy, gx, big - 1 - gy, big - 1 - gx]).astype(float)
    alpha = (np.clip(edge / (big * FEATHER), 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA").resize((SIDE, SIDE), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw().save(OUT / "card-receipt.png", optimize=True)
    print("만들었습니다:", OUT / "card-receipt.png")
