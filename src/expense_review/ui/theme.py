"""디자인 토큰과 스타일시트.

테마는 두 가지다.

  cozy  — 크림색 바탕에 깅엄 체크, 딸기빛 포인트, 통통한 라운드.
          귀여운 인형 스티커 콜라주 분위기(기본값).
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

        # 마스코트·스티커
        "fur":           "#7C5438",
        "fur_dark":      "#674229",
        "face":          "#F2DDC2",
        "ink":           "#3B2A1D",
        "nose":          "#3B2A1D",
        "blush":         "#F0AFA6",
        "accent":        "#D6564E",
        "berry":         "#C0435C",
        "mint":          "#9CCFB4",
        "butter":        "#F2D384",
        "sky":           "#9FBEE3",
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

        "fur":           "#5A6488",
        "fur_dark":      "#464E6C",
        "face":          "#E4E9F6",
        "ink":           "#1B2340",
        "nose":          "#1B2340",
        "blush":         "#B9C2E8",
        "accent":        "#3B4BC8",
        "berry":         "#E5484D",
        "mint":          "#2ECFBB",
        "butter":        "#F5A524",
        "sky":           "#93A6F5",
    },
}

DEFAULT_THEME = "cozy"

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


_refresh_derived()


def card_shadow(widget: QWidget, blur: int = 26, alpha: int = 30, dy: int = 6) -> None:
    """카드에 옅은 그림자. '떠 있는 카드' 느낌을 만든다."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    base = QColor(COLORS["text"])
    effect.setColor(QColor(base.red(), base.green(), base.blue(), alpha))
    widget.setGraphicsEffect(effect)


def stylesheet() -> str:
    c = COLORS
    radius = RADIUS
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
    background: {c['surface']};
    border: 1px solid {c['border']};
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
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 12px;
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
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 13px;
    padding: 8px 15px;
    font-size: 12px;
    font-weight: 700;
    min-height: 17px;
}}
QPushButton:hover    {{ border-color: {c['indigo']}; color: {c['indigo']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; border-color: {c['border']}; }}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['indigo']}, stop:1 {c['blue']});
    border: none;
    color: {c['on_dark']};
    font-size: 13px;
    font-weight: 800;
    padding: 11px 20px;
}}
QPushButton#primary:hover    {{ background: {c['blue']}; }}
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
QPushButton#ghost:hover {{ color: {c['indigo']}; border-color: {c['indigo']}; }}

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
