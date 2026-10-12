"""앱 아이콘 생성기 — 화면 디자인과 같은 입체 그림으로 창·바로가기 아이콘을 만든다.

흰 둥근 판 위에 '트레이와 펜' 입체 그림(사이드바 로고와 같은 것)을 올린다.
판 테두리는 옅은 라벤더, 아래로 넓고 옅은 그림자를 깐다(theme 토큰과 같은 색).

입체 그림은 흰 바탕에 맞춰 만든 에셋이라(tools/make_art.py) 판 안쪽은 반드시 흰색이어야
한다. 판에 그라데이션을 넣으면 그림 둘레에 흰 사각이 드러난다.

작은 크기(16·24·32)는 입체 그림이 뭉개져 무엇인지 알아볼 수 없다. 그래서 같은 판 위에
라벤더 트레이와 아래 화살표를 평면으로 그린다 — 색과 모양은 큰 아이콘과 맞춘다.

결과물은 저장소에 함께 커밋되므로 보통은 다시 돌릴 일이 없다. 디자인을 바꿀 때만:

    python tools/make_icon.py

생성 파일:
    src/claim_downloader/ui/assets/icon.png   (256px)
    src/claim_downloader/ui/assets/icons/icon-<크기>.png  (창 아이콘용, 크기별)
    src/claim_downloader/ui/assets/icon.ico   (16~256px, 윈도우 바로가기·작업 표시줄용)
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ASSETS = Path(__file__).resolve().parents[1] / "src" / "claim_downloader" / "ui" / "assets"
ART = ASSETS / "art" / "tray-pen.png"

# ui/tokens.py 와 맞춘다
WHITE = (255, 255, 255, 255)
RIM = (217, 207, 245, 255)          # 라벤더(#C9B8EF)를 흰색 쪽으로 옅게
PRIMARY = (109, 91, 208, 255)       # #6D5BD0
LAVENDER = (201, 184, 239, 255)     # #C9B8EF
SHADOW = (35, 42, 52)

SS = 4                              # 4배로 그려 줄여서 가장자리를 매끈하게
SMALL = (16, 24, 32)


def _box(big: int) -> tuple[tuple[int, int, int, int], int, int]:
    """판의 바깥 상자 · 모서리 반지름 · 테두리 두께."""
    inset = round(big * 0.055)
    box = (inset, inset, big - inset, big - inset - round(big * 0.02))
    return box, round(big * 0.24), max(SS, round(big * 0.012))


def _plate(size: int) -> Image.Image:
    """그림자 + 흰 둥근 판 + 라벤더 테두리. size 는 최종 한 변."""
    big = size * SS
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    box, radius, rim = _box(big)

    if size > max(SMALL):
        shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rounded_rectangle(
            (box[0], box[1] + round(big * 0.03), box[2], box[3] + round(big * 0.03)),
            radius, fill=SHADOW + (46,))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(big * 0.025)))

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(box, radius, fill=RIM)
    draw.rounded_rectangle((box[0] + rim, box[1] + rim, box[2] - rim, box[3] - rim),
                           radius - rim, fill=WHITE)
    return canvas


def _large(size: int) -> Image.Image:
    canvas = _plate(size)
    big = canvas.width
    art = Image.open(ART).convert("RGBA")
    side = round(big * 0.76)
    art = art.resize((side, side), Image.LANCZOS)
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    layer.paste(art, ((big - side) // 2, (big - side) // 2 - round(big * 0.012)))
    # 그림의 흰 사각 바탕이 판의 둥근 모서리 밖으로 삐져나오지 않게 판 안쪽 모양으로 자른다
    box, radius, rim = _box(big)
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (box[0] + rim, box[1] + rim, box[2] - rim, box[3] - rim), radius - rim, fill=255)
    layer.putalpha(ImageChops.darker(layer.getchannel("A"), mask))
    canvas.alpha_composite(layer)
    return canvas.resize((size, size), Image.LANCZOS)


def _small(size: int) -> Image.Image:
    """평면 판: 라벤더 트레이 + 내려받기 화살표."""
    canvas = _plate(size)
    big = canvas.width
    draw = ImageDraw.Draw(canvas)
    u = big / 16
    # 트레이
    draw.rounded_rectangle((3.2 * u, 9.0 * u, 12.8 * u, 12.6 * u), 1.2 * u, fill=LAVENDER)
    draw.rectangle((5.6 * u, 9.0 * u, 10.4 * u, 10.4 * u), fill=WHITE)
    # 화살표
    w = max(SS, round(1.5 * u))
    draw.line((8 * u, 3.4 * u, 8 * u, 8.4 * u), fill=PRIMARY, width=w)
    draw.polygon([(5.4 * u, 6.4 * u), (10.6 * u, 6.4 * u), (8 * u, 9.2 * u)], fill=PRIMARY)
    return canvas.resize((size, size), Image.LANCZOS)


def draw_icon(size: int) -> Image.Image:
    return _small(size) if size in SMALL else _large(size)


def main() -> None:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = {s: draw_icon(s) for s in sizes}
    frames[256].save(ASSETS / "icon.png")
    # 창 제목줄·작업 표시줄은 Qt 가 크기별 그림을 골라 쓴다(ui/app.py). 256 하나만 주면 16px 가 뭉개진다.
    (ASSETS / "icons").mkdir(exist_ok=True)
    for s in sizes:
        frames[s].save(ASSETS / "icons" / f"icon-{s}.png")
    # ICO 는 크기마다 따로 그린 그림을 담는다. 큰 그림 하나를 줄이게 두면 16px 가 뭉개진다.
    frames[256].save(ASSETS / "icon.ico", format="ICO", sizes=[(s, s) for s in sizes],
                     append_images=[frames[s] for s in sizes if s != 256])
    print("만들었습니다:", ASSETS / "icon.png", ASSETS / "icon.ico")


if __name__ == "__main__":
    main()
