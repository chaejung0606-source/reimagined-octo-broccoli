"""디자인 토큰.

맑은 화이트 바탕 위에 흰 표면, 라벤더 강조색 하나, 장식용 파스텔 넷.
색·모서리·그림자·글자 크기는 전부 여기 한 곳에 있다. 화면 코드에는 값을 직접
적지 않는다.

Qt 를 들여오지 않는다. 그래야 PySide6 가 없는 CI 에서도 대비 검사
(tests/test_design.py)를 돌릴 수 있다.
"""
from __future__ import annotations

COLORS: dict[str, str] = {
    # 면
    "bg":            "#FAFBFF",   # 앱 바탕 — 맑은 화이트
    "surface":       "#FFFFFF",   # 작업 표면 · 카드 · 입력창
    "surface_alt":   "#F5F7FF",   # 표 머리 · 읽기 전용 · 비활성
    "tabbar":        "#F1F4FB",   # 작업 탭 줄 바탕
    "hover":         "#F3F5FC",   # 메뉴·행에 마우스가 올라갔을 때

    # 글자
    "text":          "#202638",
    "text_muted":    "#4D5870",
    # 제안값 #66718A 는 탭 줄(#F1F4FB)·선택 바탕 위에서 4.5:1 에 못 미쳐 한 단계 진하게
    "text_faint":    "#5E6981",
    "on_primary":    "#FFFFFF",

    # 선
    "border":        "#DFE5F1",
    "border_strong": "#C9D2E3",   # 입력창 호버
    "divider":       "#EDF1F8",

    # 강조 — 버튼·선택·포커스에만. 옅은 바탕 위 글자로는 primary_hover 를 쓴다(대비)
    "primary":       "#7058E8",
    "primary_hover": "#6048D3",
    "selection":     "#F0EBFF",

    # 장식용 파스텔 — 테두리·배지·그래픽에만. 글자색으로 쓰지 않는다
    "lavender":      "#C9B8EF",
    "mint":          "#BCE5CF",
    "cyan":          "#A9DFEC",
    "peach":         "#F4C7AD",
    "sky":           "#C4D4F8",
    "lavender_bg":   "#F0EBFF",
    "mint_bg":       "#EAFBF5",
    "cyan_bg":       "#EBF8FF",
    "peach_bg":      "#FFF2EB",
    "sky_bg":        "#EEF2FC",

    # 상태 — 글자색(진하게)과 배지 바탕(옅게)을 짝으로. 색만으로 알리지 않고 글자를 함께 쓴다
    "success":       "#16794A", "success_bg": "#E6F4EC",
    "warning":       "#9A5B00", "warning_bg": "#FDF1E2",
    "danger":        "#B42339", "danger_bg":  "#FCEBEE",
    "info":          "#1E6FB8", "info_bg":    "#E7F1FA",
    "neutral":       "#4D5870", "neutral_bg": "#EEF1F7",
}

RADIUS = {"control": 8, "card": 16, "hero": 18, "tab": 10, "dock": 22}

# 그림자: 0 3px 12px rgba(49,65,110,.035). 카드는 테두리가 기본이고 그림자는 홈 대표 카드·독에만.
SHADOW_RGB = (49, 65, 110)
SHADOW = {
    "card":  {"blur": 12, "dy": 3, "alpha": 0.035},
    "hero":  {"blur": 18, "dy": 4, "alpha": 0.06},
    "modal": {"blur": 32, "dy": 8, "alpha": 0.12},
}

# 폰트는 앱에 묶어 둔다(assets/fonts, app.py 가 시작할 때 등록). 설치 안 된 PC 에서도 같은 글씨.
FONT_FAMILY = '"Pretendard", "Noto Sans KR", "Malgun Gothic", sans-serif'
FONT_SIZE = {
    "title": 25,      # 페이지 제목 700
    "section": 16,    # 영역 제목 600
    "card": 15,       # 카드 제목 600
    "body": 14,       # 본문·입력창·버튼 400~500
    "table": 13,
    "nav": 13,        # 탭·독 500
    "small": 13,      # 보조 설명
    "caption": 12,
    "kpi": 27,        # 요약 숫자 600
}
LINE_HEIGHT = 1.55


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(fg: str, bg: str) -> float:
    """WCAG 대비. 일반 글자는 4.5 이상이어야 한다."""
    a, b = sorted((_luminance(fg), _luminance(bg)))
    return (b + 0.05) / (a + 0.05)
