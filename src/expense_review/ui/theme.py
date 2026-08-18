"""디자인 토큰과 스타일시트.

민트 · 스카이블루 계열의 밝은 대시보드. 아주 연한 그라데이션 바탕 위에
흰 카드가 떠 있고, 그림자는 존재를 알릴 정도로만 옅게 넣는다.

색·라운드·그림자 값은 전부 여기 한 곳에 있다. 화면 코드에는 색을 직접
적지 않는다 — 한 곳만 고치면 화면 전체가 따라오게 하려는 것이다.

Qt 스타일시트에는 box-shadow 가 없어 그림자는 QGraphicsDropShadowEffect 로 준다.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# ── 색 ───────────────────────────────────────────────────────────────────
# 다른 모듈이 `from .theme import COLORS` 로 이 객체를 그대로 들고 쓴다.
COLORS: dict[str, str] = {
    # 바탕 — 민트에서 하늘색을 지나 연한 남보라로 아주 옅게 흐른다
    "bg":            "#EDF6F8",
    "grad_mint":     "#E4F6F1",
    "grad_cyan":     "#E7F2FC",
    "grad_blue":     "#EDEFFD",

    # 면
    "surface":       "#FFFFFF",   # 카드
    "surface_alt":   "#F3F9FC",   # 목록 선택·연한 강조
    "surface_hi":    "#FFFFFF",
    "border":        "#E4EDF4",   # 실선은 얇고 옅게
    "border_strong": "#CFDEE9",

    # 글자
    "text":          "#16243C",   # 다크 네이비
    "text_muted":    "#5D7387",   # 그레이 블루
    "text_faint":    "#93A7B9",

    # 포인트 — Primary 는 민트→아쿠아 그라데이션으로 쓴다
    "primary":       "#2BC9BC",
    "primary_deep":  "#17A79C",
    "accent":        "#31B4EC",   # 아쿠아 / 시안
    "accent_deep":   "#1E90D2",
    "secondary":     "#8AA4F8",   # 페리윙클
    "navy":          "#16243C",

    # 그래프 계열 (Primary/Secondary 안에서만 고른다)
    "chart_1":       "#2BC9BC",
    "chart_2":       "#31B4EC",
    "chart_3":       "#8AA4F8",
    "chart_4":       "#B7E4DC",

    # 판정 — 파스텔로 낮춘 채도. 빨강도 눈을 찌르지 않게 한다
    "error":         "#EE6A82",
    "warn":          "#F2A950",
    "review":        "#5C9DF5",
    "pass":          "#2BC9A0",

    "on_dark":       "#FFFFFF",
    "on_dark_muted": "#D6EEF6",

    "shadow":        "#1B4A66",   # 푸른 기가 도는 그림자
    "shadow_boost":  "0.75",      # 은은하게

    "radius":        "20",
    "radius_lg":     "24",
    "radius_pill":   "999",
}

# 이전 이름을 쓰는 자리가 남아 있어 별칭을 둔다.
COLORS["indigo"] = COLORS["accent_deep"]
COLORS["blue"] = COLORS["accent"]
COLORS["blue_soft"] = "#A9D9F5"
COLORS["teal"] = COLORS["primary"]
COLORS["teal_soft"] = "#A9E7E0"
COLORS["pearl"] = COLORS["surface"]
COLORS["center_light"] = COLORS["grad_cyan"]

SEVERITY_STYLE: dict[str, dict[str, str]] = {}

# 차트 계열색
CHART_SERIES: list[str] = []

RADIUS = 20
FONT_FAMILY = '"Pretendard", "Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif'


def _fill_derived() -> None:
    """COLORS 에서 파생되는 표를 채운다. 모듈을 읽을 때 한 번 돈다."""
    SEVERITY_STYLE.update({
        "ERROR":  {"color": COLORS["error"],  "label": "수정 필요", "icon": "●"},
        "WARN":   {"color": COLORS["warn"],   "label": "확인 요망", "icon": "●"},
        "REVIEW": {"color": COLORS["review"], "label": "판독 불가", "icon": "●"},
        "PASS":   {"color": COLORS["pass"],   "label": "이상 없음", "icon": "●"},
        "INFO":   {"color": COLORS["text_muted"], "label": "참고", "icon": "●"},
    })
    CHART_SERIES[:] = [COLORS["chart_1"], COLORS["chart_2"],
                       COLORS["chart_3"], COLORS["chart_4"]]


_fill_derived()


def card_shadow(widget: QWidget, blur: int = 30, alpha: int = 26, dy: int = 8) -> None:
    """카드가 바탕에서 살짝 떠 보이게 하는 그림자.

    윤곽선을 더 그리는 대신 그림자로 층을 만든다. 선이 많아지면 화면이
    답답해지기 때문이다. 그래서 기본값이 넓고 옅다.
    """
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    base = QColor(COLORS["shadow"])
    boost = float(COLORS["shadow_boost"])
    effect.setColor(QColor(base.red(), base.green(), base.blue(),
                           min(255, round(alpha * boost))))
    widget.setGraphicsEffect(effect)


def stylesheet() -> str:
    c = COLORS
    radius = int(c["radius"])
    radius_lg = int(c["radius_lg"])
    return f"""
* {{
    font-family: {FONT_FAMILY};
    color: {c['text']};
}}

QMainWindow {{ background: {c['bg']}; }}
QWidget#page {{ background: transparent; }}

/* ── 사이드바 ─────────────────────────────────────────── */
QWidget#sidebar {{
    background: {c['surface']};
    border-right: 1px solid {c['border']};
}}
QLabel#brand {{
    color: {c['text']};
    font-size: 16px;
    font-weight: 700;
    padding: 4px 22px 2px 22px;
}}
QLabel#brandSub {{
    color: {c['text_faint']};
    font-size: 11px;
    padding: 0 22px 16px 22px;
}}
QPushButton#navItem {{
    background: transparent;
    border: none;
    border-radius: 14px;
    color: {c['text_muted']};
    font-size: 13px;
    font-weight: 600;
    padding: 11px 14px;
    text-align: left;
    margin: 3px 12px;
}}
QPushButton#navItem:hover {{
    background: {c['surface_alt']};
    color: {c['text']};
}}
QPushButton#navItem:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['primary']}, stop:1 {c['accent']});
    color: {c['on_dark']};
    font-weight: 700;
}}
QLabel#versionLabel {{
    color: {c['text_faint']};
    font-size: 10px;
    padding: 8px 22px 16px 22px;
}}

/* ── 카드 ─────────────────────────────────────────────── */
QFrame#card {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {radius}px;
}}
/* 가장 중요한 카드 하나만 색을 입혀 위계를 만든다 */
QFrame#cardAccent {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['primary']}, stop:1 {c['accent']});
    border: none;
    border-radius: {radius}px;
}}
QFrame#cardTeal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['teal_soft']}, stop:1 {c['blue_soft']});
    border: none;
    border-radius: {radius}px;
}}
QLabel#cardTitle {{ font-size: 13px; font-weight: 700; color: {c['text']}; }}
QLabel#cardHint  {{ font-size: 11px; color: {c['text_faint']}; }}

QLabel#statValue        {{ font-size: 32px; font-weight: 800; color: {c['text']}; }}
QLabel#statValueError   {{ font-size: 32px; font-weight: 800; color: {c['error']}; }}
QLabel#statValueWarn    {{ font-size: 32px; font-weight: 800; color: {c['warn']}; }}
QLabel#statValueReview  {{ font-size: 32px; font-weight: 800; color: {c['review']}; }}
QLabel#statLabel        {{ font-size: 11px; font-weight: 600; color: {c['text_muted']}; }}
QLabel#statValueDark    {{ font-size: 32px; font-weight: 800; color: {c['on_dark']}; }}
QLabel#statLabelDark    {{ font-size: 11px; font-weight: 600; color: {c['on_dark_muted']}; }}
QLabel#statCaption      {{ font-size: 11px; color: {c['text_faint']}; }}

QLabel#pageTitle   {{ font-size: 22px; font-weight: 700; }}
QLabel#pageSub     {{ font-size: 12px; color: {c['text_muted']}; }}
QLabel#sectionHead {{ font-size: 13px; font-weight: 700; }}

/* ── 입력 ─────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 9px 13px;
    font-size: 12px;
    selection-background-color: {c['accent']};
    selection-color: {c['on_dark']};
}}
QLineEdit:hover, QComboBox:hover {{ border-color: {c['border_strong']}; }}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {c['primary']};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: 14px;
    padding: 6px;
    selection-background-color: {c['surface_alt']};
    selection-color: {c['text']};
}}

/* ── 버튼 ─────────────────────────────────────────────── */
QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 18px;
    padding: 9px 18px;
    font-size: 12px;
    font-weight: 600;
    color: {c['primary_deep']};
    min-height: 17px;
}}
QPushButton:hover    {{ background: {c['surface_alt']}; border-color: {c['primary']}; }}
QPushButton:pressed  {{ background: {c['surface_alt']}; padding-top: 10px; padding-bottom: 8px; }}
QPushButton:disabled {{ color: {c['text_faint']}; border-color: {c['border']}; }}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['primary']}, stop:1 {c['accent']});
    border: none;
    border-radius: 20px;
    color: {c['on_dark']};
    font-size: 13px;
    font-weight: 700;
    padding: 12px 24px;
}}
QPushButton#primary:hover    {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['primary_deep']}, stop:1 {c['accent_deep']});
}}
QPushButton#primary:pressed  {{ padding-top: 13px; padding-bottom: 11px; }}
QPushButton#primary:disabled {{ background: {c['border_strong']}; color: {c['surface']}; }}

QPushButton#ghost {{
    background: transparent;
    border: 1px solid {c['border']};
    color: {c['text_muted']};
}}
QPushButton#ghost:hover {{ border-color: {c['primary']}; color: {c['primary_deep']}; }}

QPushButton:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['primary']}, stop:1 {c['accent']});
    border-color: {c['primary']};
    color: {c['on_dark']};
}}

QCheckBox {{ font-size: 12px; spacing: 8px; color: {c['text_muted']}; }}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border: 1px solid {c['border_strong']};
    border-radius: 6px;
    background: {c['surface']};
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['primary']}, stop:1 {c['accent']});
    border-color: {c['primary']};
}}

/* ── 목록·표 ──────────────────────────────────────────── */
QTreeWidget, QListWidget, QTableWidget {{
    background: transparent;
    border: none;
    font-size: 12px;
    outline: none;
}}
QTreeWidget::item, QListWidget::item {{
    padding: 10px 6px;
    border-radius: 10px;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {c['surface_alt']}; }}
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
    color: {c['text_faint']};
    font-size: 11px;
    font-weight: 700;
    padding: 8px 4px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{
    background: {c['border_strong']}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c['primary']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 9px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{
    background: {c['border_strong']}; border-radius: 4px; min-width: 30px;
}}

QSplitter::handle {{ background: transparent; width: 22px; }}

QStatusBar {{ background: transparent; color: {c['text_faint']}; font-size: 11px; }}
QToolTip {{
    background: {c['navy']};
    color: {c['on_dark']};
    border: none;
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 11px;
}}
"""
