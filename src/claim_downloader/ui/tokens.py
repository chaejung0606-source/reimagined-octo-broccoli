"""디자인 토큰.

따뜻한 화이트 바탕 위에 흰 카드, 라벤더 강조색 하나, 장식용 파스텔 넷.
색·모서리·그림자·글자 크기는 전부 여기 한 곳에 있다. 화면 코드에는 값을 직접
적지 않는다.

Qt 를 들여오지 않는다. 그래야 PySide6 가 없는 CI 에서도 대비 검사
(tests/test_tokens.py)를 돌릴 수 있다.
"""
from __future__ import annotations

COLORS: dict[str, str] = {
    # 면
    "bg":            "#F4F5F3",   # 앱 바탕 — 따뜻한 화이트
    "surface":       "#FFFFFF",   # 카드 · 입력창
    "surface_alt":   "#F8F9F7",   # 표 머리 · 읽기 전용 · 비활성
    "hover":         "#F3F4F1",   # 메뉴·행에 마우스가 올라갔을 때

    # 글자
    "text":          "#242831",
    "text_muted":    "#59616E",
    # 원래 #6C7480 이었으나 앱 바탕(#F4F5F3) 위에서 4.32:1 로 AA(4.5) 미달이라 한 단계 낮췄다.
    "text_faint":    "#656D79",
    "on_primary":    "#FFFFFF",

    # 선
    "border":        "#DCE1E6",
    "border_strong": "#C5CCD4",   # 입력창 호버
    "divider":       "#E9ECEF",

    # 강조 — 버튼·선택·포커스에만
    "primary":       "#6D5BD0",
    "primary_hover": "#5B49BA",
    "selection":     "#F0ECFC",

    # 장식용 파스텔 — 배경·그래픽에만. 글자색으로 쓰지 않는다
    "lavender":      "#C9B8EF",
    "mint":          "#BCE5CF",
    "cyan":          "#A9DFEC",
    "peach":         "#F4C7AD",

    # 상태 — 글자색(진하게)과 배지 바탕(옅게)을 짝으로. 색만으로 알리지 않고 글자를 함께 쓴다
    "success":       "#16794A", "success_bg": "#E6F4EC",
    "warning":       "#9A5B00", "warning_bg": "#FDF1E2",
    "danger":        "#B42339", "danger_bg":  "#FCEBEE",
    "info":          "#1E6FB8", "info_bg":    "#E7F1FA",
    "neutral":       "#59616E", "neutral_bg": "#F1F2F0",
}

RADIUS = {"control": 8, "card": 16, "hero": 20}

# 카드 그림자: 0 2px 5px rgba(35,42,52,.025), 0 10px 28px rgba(35,42,52,.045)
# Qt 의 QGraphicsDropShadowEffect 는 한 겹만 그릴 수 있어 두 겹을 한 겹으로 합쳐 근사한다.
SHADOW_RGB = (35, 42, 52)
SHADOW = {
    "card":  {"blur": 28, "dy": 8, "alpha": 0.06},
    "modal": {"blur": 32, "dy": 8, "alpha": 0.12},
}

FONT_FAMILY = '"Pretendard", "Pretendard Variable", "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif'
FONT_SIZE = {
    "title": 26,      # 페이지 제목
    "section": 16,    # 카드 제목
    "body": 14,
    "small": 13,      # 보조 문구
    "caption": 12,    # 표 머리 · 배지
    "kpi": 28,
}


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG 대비. 일반 글자는 4.5 이상이어야 한다."""
    a, b = sorted((_luminance(fg), _luminance(bg)))
    return (b + 0.05) / (a + 0.05)
