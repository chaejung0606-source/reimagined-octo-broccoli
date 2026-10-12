"""입체 그림 에셋 만들기 — 참고 이미지에서 오브젝트를 하나씩 잘라 낸다.

    python tools/make_art.py <참고 이미지.png>

결과물(src/claim_downloader/ui/assets/art/*.png)은 저장소에 함께 커밋되므로
보통은 다시 돌릴 일이 없다. 더 좋은 원본을 받으면 같은 파일 이름으로 바꿔
넣기만 하면 된다(ui/art.py 가 이름으로 찾는다).

참고 이미지(5×3 격자, 바탕 #F1F1F1)를 이렇게 처리한다.

  1. 격자 칸마다 그림자까지 넉넉히 잘라 낸다.
  2. 오브젝트 몸체(그림자 제외)의 중심을 정사각 캔버스 가운데에 놓고, 몸체의 긴 변이
     캔버스의 1/1.3 이 되게 한다. 원본마다 여백이 달라 파일 크기만 맞추면 화면에서
     크기가 들쭉날쭉해 보이기 때문이다.
  3. 바탕 회색을 흰색으로 맞춘다(채널마다 255/바탕). 바탕은 칸마다 테두리에서 다시 잰다 —
     참고 이미지는 가장자리로 갈수록 1~4 정도 밝아져, 한 값으로 맞추면 흰 카드 위에서
     옅은 사각 테두리가 남는다. 잡음까지 덮도록 바탕보다 2 낮은 값을 흰색으로 둔다.
     배경을 '지우면' 흰 오브젝트와 반투명 그림자까지 같이 지워진다. 그래서 지우지 않고, 앱에서 이 그림을 언제나
     흰 면 위에만 놓는다. 흰 면 위에서는 경계가 보이지 않는다.
  4. 가장자리 6% 를 투명하게 풀어, 혹시 흰 면이 아닌 곳에 놓여도 사각 경계가
     날카롭게 보이지 않게 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui" / "assets" / "art"

# 참고 이미지 3번(1083×646)의 격자 — 열·행의 픽셀 범위
COLS = [(6, 176), (236, 409), (445, 627), (676, 846), (906, 1077)]
ROWS = [(16, 179), (240, 414), (464, 630)]
NAMES = [
    ["envelope", "signed-doc", "doc-users", "keyboard-mouse", "panels"],
    [None, "folder-papers", "chat-bubbles", "book-pen", "tray-pen"],
    ["chat-mention", "folder-heart", "send-tray", "monitor-lock", "dial"],
]
PAD = 24            # 그림자가 잘리지 않게 칸 밖으로 더 잘라 낼 폭
BODY_RATIO = 1.30   # 캔버스 한 변 / 몸체 긴 변
FEATHER = 0.06


def extract(src: Path) -> None:
    a = np.asarray(Image.open(src).convert("RGB")).astype(float)
    OUT.mkdir(parents=True, exist_ok=True)
    for r, (y0, y1) in enumerate(ROWS):
        for c, (x0, x1) in enumerate(COLS):
            name = NAMES[r][c]
            if not name:
                continue
            ys, ye = max(0, y0 - PAD), min(a.shape[0], y1 + PAD)
            xs, xe = max(0, x0 - PAD), min(a.shape[1], x1 + PAD)
            cell = a[ys:ye, xs:xe]
            ring = np.concatenate([cell[:6].reshape(-1, 3), cell[-6:].reshape(-1, 3),
                                   cell[:, :6].reshape(-1, 3), cell[:, -6:].reshape(-1, 3)])
            local = np.median(ring, axis=0)
            dev = np.abs(cell - local).max(2)

            yy, xx = np.where(dev > 3)                    # 그림자까지
            by0, by1, bx0, bx1 = yy.min(), yy.max() + 1, xx.min(), xx.max() + 1
            cy, cx = np.where(dev > 12)                   # 몸체만
            cy0, cy1, cx0, cx1 = cy.min(), cy.max() + 1, cx.min(), cx.max() + 1

            side = int(max(cy1 - cy0, cx1 - cx0) * BODY_RATIO)
            side = max(side, by1 - by0 + 8, bx1 - bx0 + 8)
            canvas = np.ones((side, side, 3)) * local
            oy = int(round(side / 2 - (cy0 + cy1) / 2))
            ox = int(round(side / 2 - (cx0 + cx1) / 2))
            sub = cell[by0:by1, bx0:bx1]
            canvas[by0 + oy:by0 + oy + sub.shape[0], bx0 + ox:bx0 + ox + sub.shape[1]] = sub

            rgb = np.clip(canvas * (255.0 / (local - 2)), 0, 255)
            gy, gx = np.mgrid[0:side, 0:side]
            edge = np.minimum.reduce([gy, gx, side - 1 - gy, side - 1 - gx]).astype(float)
            alpha = np.clip(edge / (side * FEATHER), 0, 1) * 255
            Image.fromarray(np.dstack([rgb, alpha]).astype(np.uint8), "RGBA").save(
                OUT / f"{name}.png", optimize=True)
            print(f"{name:15s} {side}px")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    extract(Path(sys.argv[1]))
