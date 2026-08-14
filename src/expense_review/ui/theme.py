"""디자인 토큰과 스타일시트.

테마는 세 가지다.

  y2k    — 아이보리 바탕에 유광 플라스틱 컨트롤(기본값).
           2000년대 전자기기 느낌 — 크롬 림·유광 반사·안쪽 그림자.
  galaxy — 딥 퍼플 별하늘 바탕에 반투명 유리 카드.
  cozy   — 크림색 바탕에 깅엄 체크, 딸기빛 포인트, 통통한 라운드.
  studio — 청회색 바탕에 남색 그라데이션. 차분한 대시보드.

색은 COLORS 딕셔너리를 **제자리에서 갱신**한다. 다른 모듈이
`from .theme import COLORS` 로 같은 객체를 들고 있으므로, 테마를 바꾸면
다시 임포트하지 않아도 따라온다.

Qt 스타일시트에는 box-shadow 가 없어 그림자는 QGraphicsDropShadowEffect 로 준다.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# ── 팔레트 ────────────────────────────────────────────────────────────────

PALETTES: dict[str, dict[str, str]] = {
    "y2k": {
        "label": "유광 플라스틱",
        # 2000년대 초 전자기기 느낌 — 아이보리 바탕에 유광 플라스틱 컨트롤.
        # 색면·반사·안쪽 그림자는 스타일시트로 안 되므로 glossy.py 가 직접 그린다.
        # 여기 값은 '무슨 색인가'만 정하고, '어떻게 빛나는가'는 그쪽에 있다.
        "bg":            "#E7DCC6",   # 따뜻한 아이보리
        "gingham":       "#FFFBF0",   # 가운데를 밝히는 빛
        "pearl":         "#EBE5DA",   # 크림빛 플라스틱 (기본 버튼·패널)
        "surface":       "#F6F2E9",
        "surface_hi":    "#FFFDF8",
        "surface_alt":   "#EDE7DA",
        "border":        "#CFC7B6",
        "border_strong": "#A9A08C",

        "text":          "#221F2E",
        "text_muted":    "#5E5869",
        "text_faint":    "#7E7689",

        "navy":          "#2A3566",   # 사이드바 — 짙은 남색 플라스틱
        "indigo":        "#3A55B8",
        "blue":          "#4A7BE0",
        "blue_soft":     "#9CBCF2",
        "teal":          "#1F8E86",
        "teal_soft":     "#7FD3C8",

        "error":         "#C7332F",
        "warn":          "#E08A1E",
        "review":        "#3A6BC4",
        "pass":          "#2E9E6B",

        "on_dark":       "#FFFFFF",
        "on_dark_muted": "#EDF1FF",
        "shadow":        "#5A5140",
        "shadow_boost":  "1.5",
        "radius":        "22",

        "card_top":      "#FFFDF8",
        "card_mid":      "#F8F4EB",
        "card_bottom":   "#EFE9DC",
        "card_border":   "#CFC7B6",
        "card_rim":      "#FFFFFF",
        "btn_top":       "#FFFDF8",
        "btn_mid":       "#F4EFE4",
        "btn_bottom":    "#E4DCCC",
        "btn_border":    "#A9A08C",
        "btn_rim":       "#FFFFFF",
    },
    "galaxy": {
        "label": "퍼플 갤럭시",
        # 어두운 보랏빛 바탕 위에 '반투명 유리판'을 얹은 화면.
        # 카드 배경에 알파를 주면 뒤의 별하늘이 비쳐, 색만 칠한 것과 달리
        # 깊이가 생긴다. 테두리는 밝게 둬서 유리 모서리에 빛이 걸린 느낌을 낸다.
        "bg":            "#17112E",
        "gingham":       "#6B4FCF",   # 배경 성운(bloom) 톤
        "surface":       "#2E2552",
        "surface_hi":    "#3D3168",
        "surface_alt":   "#453873",
        "border":        "#514296",
        "border_strong": "#8F6FE0",

        "text":          "#F4F0FF",
        "text_muted":    "#C4B9F0",
        "text_faint":    "#8B7FC4",

        "navy":          "#150F2C",   # 사이드바 그라데이션
        "indigo":        "#7B5CE6",
        "blue":          "#A98BFF",
        "blue_soft":     "#C9B6FF",
        "teal":          "#D9CBFF",
        "teal_soft":     "#EFE8FF",

        "error":         "#FF8A93",
        "warn":          "#FFCB6B",
        "review":        "#9DBEFF",
        "pass":          "#7BE0B8",

        "on_dark":       "#FFFFFF",
        "on_dark_muted": "#CFC4FA",
        "shadow":        "#3A1370",   # 검정 대신 짙은 보라 — 어두운 배경에서 헤일로로 읽힌다
        "shadow_boost":  "2.1",       # 그림자를 진하게 (유리판이 떠 보이도록)
        "glow":          "#8F6FE0",   # 강조 버튼에 두르는 네온 헤일로
        "radius":        "26",

        # 유리판 — 알파값이 핵심이다. 불투명하게 바꾸면 깊이가 사라진다.
        "bloom":         "#B06AE8",   # 배경 번짐에 섞는 분홍빛
        "card_top":      "rgba(160, 140, 235, 0.50)",
        "card_mid":      "rgba(104, 88, 172, 0.34)",
        "card_bottom":   "rgba(44, 35, 80, 0.68)",
        "card_border":   "rgba(198, 182, 255, 0.26)",
        "card_rim":      "rgba(255, 255, 255, 0.44)",   # 윗면 반사선
        "btn_top":       "rgba(168, 150, 238, 0.44)",
        "btn_mid":       "rgba(112, 96, 186, 0.34)",
        "btn_bottom":    "rgba(60, 50, 112, 0.56)",
        "btn_border":    "rgba(190, 172, 255, 0.34)",
        "btn_rim":       "rgba(255, 255, 255, 0.38)",
    },
    "cozy": {
        "label": "포근한 체크",
        "bg":            "#FBF4E6",   # 크림
        "gingham":       "#D6564E",   # 체크 줄무늬
        "surface":       "#FFFCF5",
        "surface_alt":   "#F7EFE0",
        "border":        "#EADFCB",
        "border_strong": "#D9C7AC",

        "text":          "#4A3728",   # 따뜻한 갈색 먹
        "text_muted":    "#8C7460",
        "text_faint":    "#B3A08C",

        "navy":          "#8C4A3F",   # 사이드바 그라데이션 (구운 벽돌빛)
        "indigo":        "#C0564C",
        "blue":          "#D6564E",
        "blue_soft":     "#E8A49C",
        "teal":          "#7FBFA3",
        "teal_soft":     "#B6DCC7",

        "error":         "#D14343",
        "warn":          "#E0913A",
        "review":        "#6D93C9",
        "pass":          "#6FAE86",

        "on_dark":       "#FFF8EC",
        "on_dark_muted": "#F0CFC4",
        "shadow":        "#4A3527",
        "radius":        "20",
        "surface_hi":    "#FFFCF5",

        "card_top":      "#FFFCF5",
        "card_mid":      "#FFFCF5",
        "card_bottom":   "#FFFCF5",
        "card_border":   "#EADFCB",
        "card_rim":      "#EADFCB",
        "btn_top":       "#FFFCF5",
        "btn_mid":       "#FBF6EB",
        "btn_bottom":    "#F7EFE0",
        "btn_border":    "#D9C7AC",
        "btn_rim":       "#D9C7AC",
    },
    "studio": {
        "label": "차분한 대시보드",
        "bg":            "#EDF0F7",
        "gingham":       "#C3CDE4",
        "surface":       "#FFFFFF",
        "surface_alt":   "#F6F8FC",
        "border":        "#E2E8F4",
        "border_strong": "#CBD5EA",

        "text":          "#141B34",
        "text_muted":    "#6B7490",
        "text_faint":    "#9AA3B8",

        "navy":          "#1E2A78",
        "indigo":        "#3B4BC8",
        "blue":          "#2E4BFF",
        "blue_soft":     "#93A6F5",
        "teal":          "#2ECFBB",
        "teal_soft":     "#7BE3D6",

        "error":         "#E5484D",
        "warn":          "#F5A524",
        "review":        "#3E8BFF",
        "pass":          "#2ECFBB",

        "on_dark":       "#FFFFFF",
        "on_dark_muted": "#B9C2E8",
        "shadow":        "#141B34",
        "radius":        "20",
        "surface_hi":    "#FFFFFF",

        "card_top":      "#FFFFFF",
        "card_mid":      "#FFFFFF",
        "card_bottom":   "#FFFFFF",
        "card_border":   "#E2E8F4",
        "card_rim":      "#E2E8F4",
        "btn_top":       "#FFFFFF",
        "btn_mid":       "#FBFCFE",
        "btn_bottom":    "#F6F8FC",
        "btn_border":    "#CBD5EA",
        "btn_rim":       "#CBD5EA",
    },
}

DEFAULT_THEME = "y2k"

# 다른 모듈이 참조하는 객체. 제자리에서 갱신한다.
COLORS: dict[str, str] = dict(PALETTES[DEFAULT_THEME])

SEVERITY_STYLE: dict[str, dict[str, str]] = {}

# 차트 계열색
CHART_SERIES: list[str] = []

RADIUS = 20
FONT_FAMILY = '"Pretendard", "Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif'

_current_theme = DEFAULT_THEME


def _refresh_derived() -> None:
    SEVERITY_STYLE.clear()
    SEVERITY_STYLE.update({
        "ERROR":  {"color": COLORS["error"],  "label": "수정 필요", "icon": "●"},
        "WARN":   {"color": COLORS["warn"],   "label": "확인 요망", "icon": "●"},
        "REVIEW": {"color": COLORS["review"], "label": "판독 불가", "icon": "●"},
        "PASS":   {"color": COLORS["pass"],   "label": "이상 없음", "icon": "●"},
        "INFO":   {"color": COLORS["text_muted"], "label": "참고", "icon": "●"},
    })
    CHART_SERIES[:] = [COLORS["indigo"], COLORS["teal"], COLORS["blue_soft"], COLORS["navy"]]


def set_theme(name: str) -> str:
    """테마를 바꾸고 새 스타일시트를 돌려준다."""
    global _current_theme
    if name not in PALETTES:
        name = DEFAULT_THEME
    _current_theme = name
    COLORS.clear()
    COLORS.update(PALETTES[name])
    _refresh_derived()
    return stylesheet()


def current_theme() -> str:
    return _current_theme


def is_cozy() -> bool:
    return _current_theme == "cozy"


def is_galaxy() -> bool:
    return _current_theme == "galaxy"


def is_y2k() -> bool:
    return _current_theme == "y2k"


_refresh_derived()


def card_shadow(widget: QWidget, blur: int = 26, alpha: int = 30, dy: int = 6) -> None:
    """카드에 옅은 그림자. '떠 있는 카드' 느낌을 만든다."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    base = QColor(COLORS.get("shadow", COLORS["text"]))
    # 테마별 배율. 호출부가 정한 상대적 세기(카드 > 타일 > 파일카드)는 지키면서
    # 어두운 테마에서만 전체적으로 진해진다.
    boost = float(COLORS.get("shadow_boost", "1"))
    effect.setColor(QColor(base.red(), base.green(), base.blue(),
                           min(255, round(alpha * boost))))
    widget.setGraphicsEffect(effect)


def neon_glow(widget: QWidget, blur: int = 30, alpha: int = 150) -> None:
    """강조 요소 뒤에 깔리는 네온 헤일로.

    그림자를 아래로 내리지 않고 사방으로 퍼뜨리면 '빛난다'로 읽힌다.
    glow 색이 없는 테마(밝은 배경)에서는 평범한 그림자로 물러난다.
    """
    accent = COLORS.get("glow")
    if accent is None:
        card_shadow(widget, blur=18, alpha=28, dy=4)
        return
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 0)
    color = QColor(accent)
    effect.setColor(QColor(color.red(), color.green(), color.blue(), alpha))
    widget.setGraphicsEffect(effect)


def stylesheet() -> str:
    c = COLORS
    radius = int(c.get("radius", str(RADIUS)))
    return f"""
* {{
    font-family: {FONT_FAMILY};
    color: {c['text']};
}}

QMainWindow {{ background: {c['bg']}; }}
QWidget#page {{ background: transparent; }}

/* ── 사이드바 ─────────────────────────────────────────── */
QWidget#sidebar {{
    background: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
                stop:0 {c['navy']}, stop:1 {c['indigo']});
    border-top-right-radius: {radius + 6}px;
    border-bottom-right-radius: {radius + 6}px;
}}
QLabel#brand {{
    color: {c['on_dark']};
    font-size: 17px;
    font-weight: 800;
    padding: 6px 20px 2px 20px;
}}
QLabel#brandSub {{
    color: {c['on_dark_muted']};
    font-size: 11px;
    padding: 0 20px 14px 20px;
}}
QPushButton#navItem {{
    background: transparent;
    border: none;
    border-radius: 14px;
    color: {c['on_dark_muted']};
    font-size: 13px;
    font-weight: 700;
    padding: 11px 16px;
    text-align: left;
    margin: 3px 12px;
}}
QPushButton#navItem:hover {{
    background: rgba(255, 255, 255, 0.13);
    color: {c['on_dark']};
}}
QPushButton#navItem:checked {{
    background: rgba(255, 255, 255, 0.22);
    color: {c['on_dark']};
}}
QLabel#versionLabel {{
    color: {c['on_dark_muted']};
    font-size: 10px;
    padding: 8px 20px 16px 20px;
}}

/* ── 카드 ─────────────────────────────────────────────── */
QFrame#card {{
    /* 반투명 유리판. 뒤의 별하늘이 비쳐 보여야 깊이가 생긴다.
       위가 밝은 그라데이션 + 밝은 테두리(림 라이트)로 모서리에 빛을 건다. */
    background: qlineargradient(x1:0, y1:0, x2:0.25, y2:1,
                stop:0 {c['card_top']}, stop:0.42 {c['card_mid']},
                stop:1 {c['card_bottom']});
    border: 1px solid {c['card_border']};
    border-top: 1px solid {c['card_rim']};
    border-radius: {radius}px;
}}
QFrame#cardAccent {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['navy']}, stop:1 {c['indigo']});
    border: none;
    border-radius: {radius}px;
}}
QFrame#cardTeal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['teal']}, stop:1 {c['teal_soft']});
    border: none;
    border-radius: {radius}px;
}}
QLabel#cardTitle {{ font-size: 13px; font-weight: 800; color: {c['text']}; }}
QLabel#cardHint  {{ font-size: 11px; color: {c['text_muted']}; }}

QLabel#statValue        {{ font-size: 30px; font-weight: 800; color: {c['text']}; }}
QLabel#statValueError   {{ font-size: 30px; font-weight: 800; color: {c['error']}; }}
QLabel#statValueWarn    {{ font-size: 30px; font-weight: 800; color: {c['warn']}; }}
QLabel#statValueReview  {{ font-size: 30px; font-weight: 800; color: {c['review']}; }}
QLabel#statLabel        {{ font-size: 11px; font-weight: 700; color: {c['text_muted']}; }}
QLabel#statValueDark    {{ font-size: 30px; font-weight: 800; color: {c['on_dark']}; }}
QLabel#statLabelDark    {{ font-size: 11px; font-weight: 700; color: {c['on_dark_muted']}; }}
QLabel#statCaption      {{ font-size: 11px; color: {c['text_faint']}; }}

QLabel#pageTitle   {{ font-size: 21px; font-weight: 800; }}
QLabel#pageSub     {{ font-size: 12px; color: {c['text_muted']}; }}
QLabel#sectionHead {{ font-size: 13px; font-weight: 800; }}

/* ── 입력 ─────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: qlineargradient(x1:0, y1:0, x2:0.3, y2:1,
                stop:0 {c['btn_top']}, stop:1 {c['btn_bottom']});
    color: {c['text']};
    border: 1px solid {c['btn_border']};
    border-radius: 14px;
    padding: 8px 12px;
    font-size: 12px;
    selection-background-color: {c['indigo']};
    selection-color: {c['on_dark']};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {c['indigo']};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 12px;
    padding: 5px;
    selection-background-color: {c['surface_alt']};
    selection-color: {c['text']};
}}

QPushButton {{
    /* 알약 모양 유리 버튼. radius 를 높이의 절반보다 크게 줘서 양끝이 둥글다. */
    background: qlineargradient(x1:0, y1:0, x2:0.25, y2:1,
                stop:0 {c['btn_top']}, stop:0.5 {c['btn_mid']},
                stop:1 {c['btn_bottom']});
    border: 1px solid {c['btn_border']};
    border-top: 1px solid {c['btn_rim']};
    border-radius: 18px;
    padding: 8px 17px;
    font-size: 12px;
    font-weight: 700;
    min-height: 17px;
}}
QPushButton:hover    {{ border-color: {c['border_strong']}; color: {c['teal_soft']}; }}
QPushButton:pressed  {{ padding-top: 10px; padding-bottom: 6px; background: {c['btn_bottom']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; border-color: {c['border']}; }}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['indigo']}, stop:1 {c['blue']});
    /* 밝은 테두리 한 줄이 네온 링처럼 읽힌다 */
    border: 1px solid {c['btn_border']};
    border-radius: 20px;
    color: {c['on_dark']};
    font-size: 13px;
    font-weight: 800;
    padding: 11px 22px;
}}
QPushButton#primary:hover    {{ background: {c['blue']}; color: {c['on_dark']}; }}
QPushButton#primary:pressed  {{ padding-top: 13px; padding-bottom: 9px; background: {c['indigo']}; }}
QPushButton#primary:disabled {{ background: {c['border_strong']}; color: {c['surface']}; }}

QPushButton:checked {{
    background: {c['indigo']};
    border-color: {c['indigo']};
    color: {c['on_dark']};
}}
QPushButton:checked:hover {{ color: {c['on_dark']}; }}

QPushButton#ghost {{
    background: transparent;
    border: 1px solid {c['border_strong']};
    color: {c['text_muted']};
}}
QPushButton#ghost:hover {{ color: {c['teal_soft']}; border-color: {c['border_strong']}; background: {c['surface_alt']}; }}

QCheckBox {{ font-size: 12px; spacing: 7px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    background: {c['surface']};
}}
QCheckBox::indicator:checked {{
    background: {c['indigo']};
    border-color: {c['indigo']};
}}

/* ── 목록·표 ──────────────────────────────────────────── */
QTreeWidget, QListWidget, QTableWidget {{
    background: transparent;
    border: none;
    font-size: 12px;
    outline: none;
}}
QTreeWidget::item, QListWidget::item {{
    padding: 7px 4px;
    border-radius: 10px;
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {c['surface_alt']};
    color: {c['text']};
}}
QTreeWidget::branch {{ background: transparent; }}
QTreeWidget::branch:selected {{ background: {c['surface_alt']}; }}
QHeaderView {{ background: transparent; }}
QHeaderView::section {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {c['border']};
    color: {c['text_muted']};
    font-size: 11px;
    font-weight: 800;
    padding: 8px 4px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{
    background: {c['border_strong']}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['blue_soft']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{
    background: {c['border_strong']}; border-radius: 4px; min-width: 30px;
}}

QSplitter::handle {{ background: transparent; width: 12px; }}

QStatusBar {{ background: transparent; color: {c['text_muted']}; font-size: 11px; }}
QToolTip {{
    background: {c['navy']};
    color: {c['on_dark']};
    border: none;
    border-radius: 8px;
    padding: 6px 9px;
    font-size: 11px;
}}
"""
