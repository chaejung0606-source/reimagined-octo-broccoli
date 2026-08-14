"""앱 아이콘 생성기 — 퍼플 갤럭시 테마.

딥 퍼플 별하늘 바탕에 라벤더 서류 한 장과 체크 배지를 그린다.
결과물은 저장소에 함께 커밋되므로 보통은 다시 돌릴 일이 없다.
디자인을 바꿀 때만 실행한다:

    python tools/make_icon.py

생성 파일:
    src/expense_review/ui/assets/icon.png   (256px, 창 아이콘용)
    src/expense_review/ui/assets/icon.ico   (16~256px, 윈도우 바로가기용)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# 갤럭시 팔레트 (src/expense_review/ui/theme.py 와 맞춘다)
BG_TOP = (43, 39, 80)        # #2B2750
BG_BOTTOM = (68, 62, 124)    # #443E7C
NEBULA = (75, 68, 136)       # #4B4488
PAPER = (228, 225, 255)      # #E4E1FF
PAPER_LINE = (143, 135, 232) # #8F87E8
BADGE_A = (108, 99, 200)     # #6C63C8
BADGE_B = (143, 135, 232)    # #8F87E8
WHITE = (255, 255, 255)

# 별 배치는 고정값으로 둔다 — 돌릴 때마다 아이콘이 달라지면 곤란하다.
STARS = [  # (x, y, r, alpha)  0~1 좌표
    (0.14, 0.12, 0.012, 235), (0.30, 0.07, 0.007, 150), (0.86, 0.10, 0.009, 200),
    (0.76, 0.20, 0.014, 245), (0.08, 0.38, 0.008, 160), (0.92, 0.42, 0.007, 140),
    (0.12, 0.80, 0.010, 190), (0.88, 0.82, 0.012, 220), (0.46, 0.10, 0.006, 120),
    (0.62, 0.06, 0.008, 170), (0.05, 0.58, 0.006, 120), (0.94, 0.62, 0.008, 150),
]
SIZE = 1024
SS = 4  # 슈퍼샘플링 배율 — PIL 도형은 안티앨리어싱이 없어 크게 그려 줄인다


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    image = Image.new("RGB", (size, size))
    for y in range(size):
        t = y / (size - 1)
        row = tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        image.paste(Image.new("RGB", (size, 1), row), (0, y))
    return image


def draw_icon(size: int = SIZE) -> Image.Image:
    big = size * SS
    base = _vertical_gradient(big, BG_TOP, BG_BOTTOM).convert("RGBA")
    draw = ImageDraw.Draw(base, "RGBA")

    # 성운 — 모서리 쪽에 옅은 보라 글로우
    for cx, cy, radius, alpha in ((0.85, 0.12, 0.55, 60), (0.12, 0.88, 0.50, 46)):
        glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        gdraw = ImageDraw.Draw(glow)
        r = big * radius
        gdraw.ellipse((big * cx - r, big * cy - r, big * cx + r, big * cy + r),
                      fill=NEBULA + (alpha,))
        glow = glow.filter(ImageFilter.GaussianBlur(big * 0.12))
        base = Image.alpha_composite(base, glow)
    draw = ImageDraw.Draw(base, "RGBA")

    # 별
    for x, y, r, alpha in STARS:
        px, py, pr = x * big, y * big, r * big
        draw.ellipse((px - pr, py - pr, px + pr, py + pr), fill=WHITE + (alpha,))
        if r >= 0.010:  # 큰 별에는 십자 빛
            arm = pr * 3.2
            width = max(2, int(pr * 0.5))
            draw.line((px - arm, py, px + arm, py), fill=WHITE + (alpha // 2,), width=width)
            draw.line((px, py - arm, px, py + arm), fill=WHITE + (alpha // 2,), width=width)

    # 서류 — 가운데 라벤더 시트, 오른쪽 위 접힌 귀
    left, top = big * 0.28, big * 0.20
    right, bottom = big * 0.72, big * 0.80
    fold = big * 0.12
    corner = big * 0.035
    sheet = [
        (left + corner, top), (right - fold, top), (right, top + fold),
        (right, bottom - corner), (right - corner, bottom),
        (left + corner, bottom), (left, bottom - corner), (left, top + corner),
    ]
    # 그림자
    shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).polygon(
        [(x + big * 0.012, y + big * 0.018) for x, y in sheet], fill=(16, 12, 40, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(big * 0.015))
    base = Image.alpha_composite(base, shadow)
    draw = ImageDraw.Draw(base, "RGBA")

    draw.polygon(sheet, fill=PAPER + (255,))
    draw.polygon([(right - fold, top), (right, top + fold),
                  (right - fold, top + fold)], fill=PAPER_LINE + (160,))

    # 서류 줄 — 검토 항목 느낌
    line_x0, line_x1 = left + big * 0.07, right - big * 0.07
    for i, ratio in enumerate((0.34, 0.44, 0.54)):
        y = big * ratio
        draw.rounded_rectangle(
            (line_x0, y, line_x1 - (big * 0.05 if i == 2 else 0), y + big * 0.030),
            radius=big * 0.015, fill=PAPER_LINE + (200,))

    # 체크 배지 — 서류 오른쪽 아래에 겹친다
    bx, by, br = big * 0.66, big * 0.72, big * 0.155
    badge = _vertical_gradient(int(br * 2), BADGE_A, BADGE_B).convert("RGBA")
    mask = Image.new("L", badge.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, badge.size[0], badge.size[1]), fill=255)
    ring = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse(
        (bx - br - big * 0.014, by - br - big * 0.014,
         bx + br + big * 0.014, by + br + big * 0.014), fill=BG_TOP + (255,))
    base = Image.alpha_composite(base, ring)
    base.paste(badge, (int(bx - br), int(by - br)), mask)
    draw = ImageDraw.Draw(base, "RGBA")

    # 체크 표시
    width = int(br * 0.30)
    points = [(bx - br * 0.45, by + br * 0.02),
              (bx - br * 0.10, by + br * 0.38),
              (bx + br * 0.50, by - br * 0.34)]
    draw.line(points, fill=WHITE + (255,), width=width, joint="curve")
    for point in points:  # 끝을 둥글게
        draw.ellipse((point[0] - width / 2, point[1] - width / 2,
                      point[0] + width / 2, point[1] + width / 2), fill=WHITE + (255,))

    # 둥근 사각형으로 오려낸다 (반경 22% — 갤럭시 카드 라운드와 맞춘 비율)
    cut = Image.new("L", (big, big), 0)
    ImageDraw.Draw(cut).rounded_rectangle((0, 0, big, big), radius=big * 0.22, fill=255)
    base.putalpha(cut)

    return base.resize((size, size), Image.LANCZOS)


def main() -> None:
    assets = Path(__file__).resolve().parents[1] / "src" / "expense_review" / "ui" / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    icon = draw_icon()
    icon.resize((256, 256), Image.LANCZOS).save(assets / "icon.png")
    icon.resize((256, 256), Image.LANCZOS).save(
        assets / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"저장: {assets / 'icon.png'}, {assets / 'icon.ico'}")


if __name__ == "__main__":
    main()
