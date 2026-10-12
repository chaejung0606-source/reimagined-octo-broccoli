"""카드청구 입체 그림 만들기 — 참고 이미지에 없는 오브젝트라 새로 그린다.

    python tools/make_card_art.py

참고 이미지의 다른 오브젝트와 같은 약속으로 그린다.
  - 흰 무광 몸체, 왼쪽 위에서 오는 빛(위·왼쪽 면이 밝고 아래·오른쪽이 살짝 어둡다)
  - 부드러운 접촉 그림자(아래로 조금 치우친 넓고 옅은 그림자)
  - 포인트는 파스텔 블루·시안 하나와 작은 라벤더 칩
  - 흰 바탕에 맞춘 사각 캔버스 + 가장자리 투명 풀기 (tools/make_art.py 와 같은 규격)

구성: 영수증 종이 한 장이 뒤에 비스듬히 서 있고, 그 앞에 둥근 모서리의 카드가 놓인다.
카드 위에는 옅은 블루 띠와 작은 라벤더 칩(IC 칩 자리), 영수증에는 짧은 회색 줄 몇 개.

4배로 그려서 줄인다. 결과는 저장소에 커밋되므로 보통은 다시 돌릴 일이 없다.
원본 수준의 3D 렌더가 아니라 평면 도구로 흉내 낸 것이다 — 더 나은 원본이 생기면
같은 이름(card-receipt.png)으로 바꿔 넣기만 하면 된다.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui" / "assets" / "art"
SIDE = 200
SS = 4
FEATHER = 0.06

WHITE = (255, 255, 255, 255)
PAPER = (247, 247, 246, 255)
PAPER_SHADE = (226, 228, 230, 255)
CARD_SHADE = (222, 225, 229, 255)
STRIPE_A = (169, 223, 236)        # 시안 #A9DFEC
STRIPE_B = (196, 212, 248)        # 옅은 블루
CHIP = (201, 184, 239, 255)       # 라벤더 #C9B8EF
LINE = (205, 209, 214, 255)
SHADOW = (35, 42, 52)


def _shadow(size: int, box, radius: int, blur: float, alpha: int, dy: int) -> Image.Image:
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(
        (box[0], box[1] + dy, box[2], box[3] + dy), radius, fill=SHADOW + (alpha,))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def _gradient_rect(w: int, h: int, left, right) -> Image.Image:
    """왼쪽 → 오른쪽 가로 그라데이션 띠."""
    x = np.linspace(0, 1, w)[None, :, None]
    rgb = (np.array(left)[None, None, :] * (1 - x) + np.array(right)[None, None, :] * x)
    rgb = np.repeat(rgb, h, axis=0).astype(np.uint8)
    alpha = np.full((h, w, 1), 255, np.uint8)
    return Image.fromarray(np.concatenate([rgb, alpha], axis=2), "RGBA")


def draw() -> Image.Image:
    big = SIDE * SS
    u = big / 100
    canvas = Image.new("RGBA", (big, big), WHITE)

    # ── 뒤의 영수증 종이 (살짝 기울여 세움) ─────────────────────────────
    paper = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pd = ImageDraw.Draw(paper)
    pbox = (30 * u, 14 * u, 76 * u, 66 * u)
    pd.rounded_rectangle(pbox, 4 * u, fill=PAPER)
    # 아래·오른쪽 가장자리의 어두운 면(두께)
    pd.rounded_rectangle((pbox[0] + 1.5 * u, pbox[1] + 1.5 * u, pbox[2], pbox[3]), 4 * u,
                         outline=PAPER_SHADE, width=max(2, int(0.9 * u)))
    for i, (x0, x1) in enumerate([(38, 62), (38, 56), (38, 66), (38, 52)]):
        y = 23 * u + i * 6.5 * u
        pd.rounded_rectangle((x0 * u, y, x1 * u, y + 2.2 * u), 1.1 * u, fill=LINE)
    paper = paper.rotate(-7, resample=Image.BICUBIC, center=(53 * u, 40 * u))
    canvas.alpha_composite(_shadow(big, pbox, int(4 * u), 3 * u, 34, int(3 * u))
                           .rotate(-7, resample=Image.BICUBIC, center=(53 * u, 40 * u)))
    canvas.alpha_composite(paper)

    # ── 앞의 카드 ─────────────────────────────────────────────────────
    cbox = (18 * u, 44 * u, 82 * u, 84 * u)
    radius = int(6 * u)
    canvas.alpha_composite(_shadow(big, cbox, radius, 4.5 * u, 44, int(5 * u)))
    card = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle(cbox, radius, fill=WHITE)
    # 빛: 왼쪽 위는 흰색 그대로, 아래·오른쪽 가장자리에 옅은 그늘
    cd.rounded_rectangle((cbox[0] + 1.2 * u, cbox[1] + 1.2 * u, cbox[2], cbox[3]), radius,
                         outline=CARD_SHADE, width=max(2, int(1.0 * u)))
    # 블루 띠 (상단) — 둥근 모서리에 맞춰 마스크로 자른다
    stripe = _gradient_rect(int(cbox[2] - cbox[0]), int(9 * u), STRIPE_A, STRIPE_B)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(cbox, radius, fill=255)
    stripe_layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    stripe_layer.paste(stripe, (int(cbox[0]), int(cbox[1] + 7 * u)))
    stripe_layer.putalpha(ImageChops.darker(stripe_layer.getchannel("A"), mask))
    card.alpha_composite(stripe_layer)
    # 라벤더 칩
    chip = (cbox[0] + 8 * u, cbox[1] + 21 * u, cbox[0] + 20 * u, cbox[1] + 30 * u)
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle(chip, 2.2 * u, fill=CHIP)
    cd.rounded_rectangle((chip[0] + 0.8 * u, chip[1] + 0.8 * u, chip[2], chip[3]), 2.2 * u,
                         outline=(182, 164, 226, 255), width=max(2, int(0.6 * u)))
    # 카드 번호 자리 — 짧은 회색 토막 넷
    for i in range(4):
        x = cbox[0] + 8 * u + i * 13.5 * u
        cd.rounded_rectangle((x, cbox[3] - 11 * u, x + 10 * u, cbox[3] - 8.6 * u), 1.2 * u, fill=LINE)
    canvas.alpha_composite(card)

    # 참고 에셋과 같은 가장자리 투명 풀기
    rgb = np.asarray(canvas.convert("RGB")).astype(np.uint8)
    gy, gx = np.mgrid[0:big, 0:big]
    edge = np.minimum.reduce([gy, gx, big - 1 - gy, big - 1 - gx]).astype(float)
    alpha = (np.clip(edge / (big * FEATHER), 0, 1) * 255).astype(np.uint8)
    out = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    return out.resize((SIDE, SIDE), Image.LANCZOS)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw().save(OUT / "card-receipt.png", optimize=True)
    print("만들었습니다:", OUT / "card-receipt.png")
