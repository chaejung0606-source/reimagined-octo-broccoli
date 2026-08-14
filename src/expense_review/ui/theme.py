"""디자인 토큰과 스타일시트.

화면은 하나뿐이다 — 아이보리 바탕에 유광 플라스틱 컨트롤.
2000년대 전자기기 느낌으로, 크롬 림·유광 반사·안쪽 그림자를 겹쳐 만든다.

여기서는 '무슨 색인가'만 정한다. '어떻게 빛나는가'는 glossy.py 에 있다.
스타일시트로는 낼 수 없는 질감이라 위젯이 직접 그리기 때문이다.

Qt 스타일시트에는 box-shadow 가 없어 그림자는 QGraphicsDropShadowEffect 로 준다.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# ── 색 ───────────────────────────────────────────────────────────────────
# 다른 모듈이 `from .theme import COLORS` 로 이 객체를 그대로 들고 쓴다.
COLORS: dict[str, str] = {
    # 2000년대 초 전자기기 느낌 — 아이보리 바탕에 유광 플라스틱 컨트롤.
    # 색면·반사·안쪽 그림자는 스타일시트로 안 되므로 glossy.py 가 직접 그린다.
    # 여기 값은 '무슨 색인가'만 정하고, '어떻게 빛나는가'는 그쪽에 있다.
    "bg":            "#E7DCC6",   # 따뜻한 아이보리
    "center_light":  "#FFFBF0",   # 배경 가운데를 밝히는 빛
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
}

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
    CHART_SERIES[:] = [COLORS["indigo"], COLORS["teal"], COLORS["blue_soft"], COLORS["navy"]]


_fill_derived()


def card_shadow(widget: QWidget, blur: int = 26, alpha: int = 30, dy: int = 6) -> None:
    """카드에 옅은 그림자. '떠 있는 카드' 느낌을 만든다."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    base = QColor(COLORS["shadow"])
    # 호출부가 정한 상대적 세기(카드 > 타일 > 파일카드)를 한 번에 조절한다.
    boost = float(COLORS["shadow_boost"])
    effect.setColor(QColor(base.red(), base.green(), base.blue(),
                           min(255, round(alpha * boost))))
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
    /* 카드는 glossy.py 가 직접 그린다. 여기 값은 그리기 전 잠깐 보이는 바탕과
       QSS 로만 스타일이 오는 자잘한 프레임을 위한 것이다. */
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
