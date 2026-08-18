"""앱 아이콘 생성기.

민트→아쿠아 그라데이션 위에 흰 서류 한 장과 체크 배지를 그린다.
앱 화면과 같은 색 체계를 쓴다 (theme.py 의 primary / accent).
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

# src/expense_review/ui/theme.py 의 primary / accent 와 맞춘다
BG_TOP = (61, 214, 196)      # 민트
BG_BOTTOM = (42, 159, 224)   # 아쿠아
NEBULA = (190, 245, 240)
PAPER = (255, 255, 255)      # 흰 서류
PAPER_LINE = (168, 205, 224)
BADGE_A = (255, 255, 255)    # 체크 배지 — 흰 원
BADGE_B = (240, 251, 253)
WHITE = (255, 255, 255)
CHROME = (255, 255, 255)

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

    # 윗면 라디얼 하이라이트 — 플라스틱이 빛을 받는 자리
    glow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(glow)
    r = big * 0.62
    gdraw.ellipse((big * 0.5 - r, big * 0.02 - r, big * 0.5 + r, big * 0.02 + r),
                  fill=NEBULA + (86,))
    glow = glow.filter(ImageFilter.GaussianBlur(big * 0.10))
    base = Image.alpha_composite(base, glow)

    # 아랫면 안쪽 그림자 — 두께가 생긴다
    shade = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shade)
    for i in range(int(big * 0.30)):
        alpha = int(52 * (i / (big * 0.30)) ** 2)
        sdraw.line((0, big - i, big, big - i), fill=(6, 14, 46, alpha))
    base = Image.alpha_composite(base, shade)
    draw = ImageDraw.Draw(base, "RGBA")

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
    draw.line(points, fill=BG_BOTTOM + (255,), width=width, joint="curve")
    for point in points:  # 끝을 둥글게
        draw.ellipse((point[0] - width / 2, point[1] - width / 2,
                      point[0] + width / 2, point[1] + width / 2), fill=BG_BOTTOM + (255,))

    # 유광 반사 — 윗면을 덮는 넓은 흰 타원
    shine = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(shine).ellipse(
        (-big * 0.18, -big * 0.52, big * 1.18, big * 0.40), fill=WHITE + (40,))
    shine = shine.filter(ImageFilter.GaussianBlur(big * 0.012))
    base = Image.alpha_composite(base, shine)

    # 크롬 림 — 바깥 테두리. 위는 하양, 아래는 회색
    rim = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(rim)
    width = int(big * 0.016)
    rdraw.rounded_rectangle((width / 2, width / 2, big - width / 2, big - width / 2),
                            radius=big * 0.22, outline=CHROME + (255,), width=width)
    # 위에서 아래로 갈수록 흐려지게 — 아래쪽 테두리는 그늘이 져야 금속처럼 보인다
    fade = Image.new("L", (big, big), 0)
    fdraw = ImageDraw.Draw(fade)
    for y in range(big):
        fdraw.line((0, y, big, y), fill=int(255 - 150 * (y / big)))
    rim.putalpha(Image.composite(rim.getchannel("A"),
                                 Image.new("L", (big, big), 0), fade))
    base = Image.alpha_composite(base, rim)

    # 둥근 사각형으로 오려낸다
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
