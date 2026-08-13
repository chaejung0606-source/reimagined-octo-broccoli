"""디자인 토큰과 스타일시트.

참고 시안(대시보드)의 인상을 옮겼다.
  - 연한 청회색 배경 위에 흰 카드, 큰 라운드(16~20px), 옅은 그림자
  - 강조는 남색→인디고 그라데이션 카드와 청록(teal) 포인트
  - 숫자는 크게, 라벨은 작고 흐리게

Qt 스타일시트에는 box-shadow 가 없어 그림자는 QGraphicsDropShadowEffect 로 준다.
"""
from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# ── 색 토큰 ───────────────────────────────────────────────────────────────

COLORS = {
    "bg":            "#EDF0F7",   # 페이지 배경 (연한 청회색)
    "surface":       "#FFFFFF",   # 카드
    "surface_alt":   "#F6F8FC",   # 카드 안쪽 보조 영역
    "border":        "#E2E8F4",
    "border_strong": "#CBD5EA",

    "text":          "#141B34",   # 본문
    "text_muted":    "#6B7490",   # 라벨·보조 설명
    "text_faint":    "#9AA3B8",

    "navy":          "#1E2A78",   # 그라데이션 시작
    "indigo":        "#3B4BC8",   # 그라데이션 끝 / 주요 강조
    "blue":          "#2E4BFF",
    "blue_soft":     "#93A6F5",
    "teal":          "#2ECFBB",   # 포인트
    "teal_soft":     "#7BE3D6",

    "error":         "#E5484D",
    "warn":          "#F5A524",
    "review":        "#3E8BFF",
    "pass":          "#2ECFBB",

    "on_dark":       "#FFFFFF",
    "on_dark_muted": "#B9C2E8",
}

# 심각도 → 색·라벨. 결과 화면 전체가 이 표를 따른다.
SEVERITY_STYLE = {
    "ERROR":  {"color": COLORS["error"],  "label": "수정 필요", "icon": "●"},
    "WARN":   {"color": COLORS["warn"],   "label": "확인 요망", "icon": "●"},
    "REVIEW": {"color": COLORS["review"], "label": "판독 불가", "icon": "●"},
    "PASS":   {"color": COLORS["pass"],   "label": "이상 없음", "icon": "●"},
}

# 차트 계열색 (시안의 인디고→청록 계열)
CHART_SERIES = [COLORS["indigo"], COLORS["teal"], COLORS["blue_soft"], COLORS["navy"]]

RADIUS = 16
FONT_FAMILY = '"Pretendard", "Noto Sans KR", "Malgun Gothic", "Apple SD Gothic Neo", sans-serif'


def card_shadow(widget: QWidget, blur: int = 28, alpha: int = 26, dy: int = 6) -> None:
    """카드에 옅은 그림자. 시안의 '떠 있는 카드' 느낌을 만든다."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(30, 42, 120, alpha))
    widget.setGraphicsEffect(effect)


def stylesheet() -> str:
    c = COLORS
    return f"""
* {{
    font-family: {FONT_FAMILY};
    color: {c['text']};
}}

QMainWindow, QWidget#page {{
    background: {c['bg']};
}}

/* ── 사이드바 ─────────────────────────────────────────── */
QWidget#sidebar {{
    background: qlineargradient(x1:0, y1:0, x2:0.6, y2:1,
                stop:0 {c['navy']}, stop:1 {c['indigo']});
    border-top-right-radius: {RADIUS}px;
    border-bottom-right-radius: {RADIUS}px;
}}
QLabel#brand {{
    color: {c['on_dark']};
    font-size: 17px;
    font-weight: 700;
    padding: 22px 20px 4px 20px;
}}
QLabel#brandSub {{
    color: {c['on_dark_muted']};
    font-size: 11px;
    padding: 0 20px 18px 20px;
}}
QPushButton#navItem {{
    background: transparent;
    border: none;
    border-radius: 10px;
    color: {c['on_dark_muted']};
    font-size: 13px;
    font-weight: 600;
    padding: 11px 16px;
    text-align: left;
    margin: 2px 12px;
}}
QPushButton#navItem:hover {{
    background: rgba(255, 255, 255, 0.10);
    color: {c['on_dark']};
}}
QPushButton#navItem:checked {{
    background: rgba(255, 255, 255, 0.18);
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
    border-radius: {RADIUS}px;
}}
QFrame#cardAccent {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['navy']}, stop:1 {c['indigo']});
    border: none;
    border-radius: {RADIUS}px;
}}
QFrame#cardTeal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 {c['teal']}, stop:1 #1FB6A6);
    border: none;
    border-radius: {RADIUS}px;
}}
QLabel#cardTitle {{
    font-size: 13px;
    font-weight: 700;
    color: {c['text']};
}}
QLabel#cardHint {{
    font-size: 11px;
    color: {c['text_muted']};
}}

/* 통계 타일 */
QLabel#statValue      {{ font-size: 30px; font-weight: 800; color: {c['text']}; }}
QLabel#statLabel      {{ font-size: 11px; font-weight: 600; color: {c['text_muted']}; }}
QLabel#statValueDark  {{ font-size: 30px; font-weight: 800; color: {c['on_dark']}; }}
QLabel#statLabelDark  {{ font-size: 11px; font-weight: 600; color: {c['on_dark_muted']}; }}
QLabel#statCaption    {{ font-size: 11px; color: {c['text_faint']}; }}

QLabel#pageTitle   {{ font-size: 20px; font-weight: 800; }}
QLabel#pageSub     {{ font-size: 12px; color: {c['text_muted']}; }}
QLabel#sectionHead {{ font-size: 13px; font-weight: 700; }}

/* ── 입력 ─────────────────────────────────────────────── */
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 9px;
    padding: 8px 11px;
    font-size: 12px;
    selection-background-color: {c['indigo']};
}}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 1px solid {c['indigo']};
}}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox::down-arrow {{ width: 9px; height: 9px; }}
QComboBox QAbstractItemView {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {c['bg']};
    selection-color: {c['text']};
}}

QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border_strong']};
    border-radius: 9px;
    padding: 8px 14px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton:hover  {{ border-color: {c['indigo']}; color: {c['indigo']}; }}
QPushButton:disabled {{ color: {c['text_faint']}; border-color: {c['border']}; }}

QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 {c['indigo']}, stop:1 {c['blue']});
    border: none;
    color: {c['on_dark']};
    font-size: 13px;
    font-weight: 700;
    padding: 11px 18px;
}}
QPushButton#primary:hover    {{ background: {c['blue']}; }}
QPushButton#primary:disabled {{ background: {c['border_strong']}; color: #FFFFFF; }}

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
    border-radius: 5px;
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
    border-radius: 8px;
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background: {c['bg']};
    color: {c['text']};
}}
QTreeWidget::branch {{ background: transparent; }}
QTreeWidget::branch:selected {{ background: {c['bg']}; }}
QHeaderView::section {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {c['border']};
    color: {c['text_muted']};
    font-size: 11px;
    font-weight: 700;
    padding: 8px 4px;
}}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 9px; margin: 4px 2px;
}}
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

QStatusBar {{
    background: transparent;
    color: {c['text_muted']};
    font-size: 11px;
}}
QToolTip {{
    background: {c['navy']};
    color: {c['on_dark']};
    border: none;
    border-radius: 6px;
    padding: 6px 9px;
    font-size: 11px;
}}
"""
