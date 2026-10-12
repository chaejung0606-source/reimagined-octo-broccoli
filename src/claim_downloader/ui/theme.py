"""스타일시트 — tokens.py 의 값을 Qt 스타일시트로 옮긴다.

입체감은 카드와 대표 그림(art.py)에만 준다. 표·입력창·작은 버튼은 평평하게 두고
선과 대비로 구분한다 — 오래 들여다보는 화면이라 모든 것이 볼록하면 피곤하다.

Qt 스타일시트에는 box-shadow 가 없어 그림자는 QGraphicsDropShadowEffect 로 준다.
상태 전환 애니메이션도 없으므로 '동작 줄이기' 설정과 부딪힐 일이 없다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from .tokens import COLORS, FONT_FAMILY, FONT_SIZE, RADIUS, SHADOW, SHADOW_RGB

__all__ = ["COLORS", "STATUS", "card_shadow", "stylesheet"]

# QSS 의 image: 는 파일 경로만 받는다. 윈도우에서도 슬래시로 적어야 읽는다.
CHECK_ICON = (Path(__file__).parent / "assets" / "check.svg").as_posix()

# 상태 배지: 이름 → (글자색, 바탕색)
STATUS = {
    name: (COLORS[name], COLORS[f"{name}_bg"])
    for name in ("success", "warning", "danger", "info", "neutral")
}


def card_shadow(widget: QWidget, kind: str = "card") -> None:
    """넓고 옅은 그림자. 카드가 바탕에서 살짝 떠 보일 정도로만."""
    spec = SHADOW[kind]
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(spec["blur"])
    effect.setOffset(0, spec["dy"])
    effect.setColor(QColor(*SHADOW_RGB, round(255 * spec["alpha"])))
    widget.setGraphicsEffect(effect)


def stylesheet() -> str:
    c = COLORS
    r_ctl, r_card, r_hero = RADIUS["control"], RADIUS["card"], RADIUS["hero"]
    f = FONT_SIZE
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: {f['body']}px;
    color: {c['text']};
}}
QMainWindow, QWidget#root {{ background: {c['bg']}; }}
QWidget#page, QWidget#pageBody {{ background: transparent; }}

/* ── 사이드바 ─────────────────────────────────────────── */
QWidget#sidebar {{
    background: {c['surface']};
    border-right: 1px solid {c['divider']};
}}
QLabel#brand {{ font-size: 16px; font-weight: 700; }}
QLabel#workspace {{ font-size: {f['caption']}px; color: {c['text_muted']}; }}
QLabel#navGroup {{
    font-size: {f['caption']}px; font-weight: 600; color: {c['text_faint']};
    padding: 18px 12px 6px 12px;
}}
QPushButton#navItem {{
    background: transparent;
    border: none;
    border-radius: {r_ctl}px;
    color: {c['text_muted']};
    font-weight: 500;
    padding: 9px 12px;
    text-align: left;
    min-height: 20px;
}}
QPushButton#navItem:hover {{ background: {c['hover']}; color: {c['text']}; }}
QPushButton#navItem:checked {{
    background: {c['selection']};
    color: {c['primary_hover']};
    font-weight: 700;
}}
QPushButton#navItem:focus {{ border: 2px solid {c['primary']}; padding: 7px 10px; }}
QLabel#versionLabel {{ font-size: {f['caption']}px; color: {c['text_faint']}; }}

/* ── 페이지 머리 ──────────────────────────────────────── */
QLabel#breadcrumb {{ font-size: {f['caption']}px; color: {c['text_faint']}; }}
QLabel#pageTitle  {{ font-size: {f['title']}px; font-weight: 700; }}
QLabel#pageDesc   {{ font-size: {f['small']}px; color: {c['text_muted']}; }}

/* ── 카드 ─────────────────────────────────────────────── */
QFrame#card {{
    background: {c['surface']};
    border: 1px solid {c['divider']};
    border-radius: {r_card}px;
}}
QFrame#hero {{
    background: {c['surface']};
    border: 1px solid {c['divider']};
    border-radius: {r_hero}px;
}}
QLabel#cardTitle {{ font-size: {f['section']}px; font-weight: 700; }}
QLabel#cardHint  {{ font-size: {f['small']}px; color: {c['text_muted']}; }}
QLabel#body      {{ font-size: {f['body']}px; color: {c['text']}; }}
QLabel#muted     {{ font-size: {f['small']}px; color: {c['text_muted']}; }}
QLabel#stepNo    {{
    font-size: {f['caption']}px; font-weight: 700; color: {c['primary_hover']};
    background: {c['selection']}; border-radius: 10px; padding: 2px 8px;
}}

QLabel#kpiLabel   {{ font-size: {f['small']}px; font-weight: 600; color: {c['text_muted']}; }}
QLabel#kpiValue   {{ font-size: {f['kpi']}px; font-weight: 700; color: {c['text']}; }}
QLabel#kpiCaption {{ font-size: {f['caption']}px; color: {c['text_faint']}; }}

/* 상태 배지 — 색과 글자를 함께 */
{''.join(f"QLabel#pill_{n} {{ background: {bg}; color: {fg}; border-radius: 10px; padding: 2px 9px; font-size: {f['caption']}px; font-weight: 600; }}" for n, (fg, bg) in STATUS.items())}

/* 사람 차례 알림 띠 */
QFrame#banner {{
    background: {c['warning_bg']};
    border: 1px solid #F0D3A8;
    border-radius: {r_ctl + 4}px;
}}
QLabel#bannerText {{ font-weight: 600; color: {c['text']}; }}

/* ── 입력 ─────────────────────────────────────────────── */
QLabel#fieldLabel {{ font-size: {f['small']}px; font-weight: 600; color: {c['text']}; }}
QLabel#fieldHelp  {{ font-size: {f['caption']}px; color: {c['text_muted']}; }}
QLabel#fieldError {{ font-size: {f['caption']}px; color: {c['danger']}; font-weight: 600; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: {r_ctl}px;
    padding: 7px 10px;
    min-height: 20px;
    selection-background-color: {c['selection']};
    selection-color: {c['text']};
}}
QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover {{ border-color: {c['border_strong']}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {c['primary']};
    padding: 6px 9px;
}}
QLineEdit:read-only, QPlainTextEdit[readOnly="true"], QTextBrowser {{ background: {c['surface_alt']}; }}
QLineEdit:disabled, QDoubleSpinBox:disabled {{ background: {c['surface_alt']}; color: {c['text_faint']}; }}
QLineEdit[error="true"] {{ border: 2px solid {c['danger']}; padding: 6px 9px; }}
QPlainTextEdit#logView {{
    font-family: "D2Coding", "Consolas", "Cascadia Mono", monospace;
    font-size: {f['caption']}px;
    color: {c['text_muted']};
}}

/* ── 버튼 ─────────────────────────────────────────────── */
/* 기본(보조) — 흰 바탕 + 선 */
QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r_ctl}px;
    padding: 7px 14px;
    min-height: 20px;
    font-weight: 600;
    color: {c['text']};
}}
QPushButton:hover    {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
QPushButton:pressed  {{ background: {c['divider']}; }}
QPushButton:focus    {{ border: 2px solid {c['primary']}; padding: 6px 13px; }}
QPushButton:disabled {{ background: {c['surface_alt']}; color: {c['text_faint']}; border-color: {c['divider']}; }}

/* 주요 — 화면마다 하나 */
QPushButton#primary {{
    background: {c['primary']};
    border: 1px solid {c['primary']};
    color: {c['on_primary']};
}}
QPushButton#primary:hover   {{ background: {c['primary_hover']}; border-color: {c['primary_hover']}; }}
QPushButton#primary:pressed {{ background: {c['primary_hover']}; }}
QPushButton#primary:focus   {{ border: 2px solid {c['text']}; padding: 6px 13px; }}
QPushButton#primary:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['text_muted']}; }}

/* 글자 버튼 — 덜 중요한 동작 */
QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {c['primary_hover']}; }}
QPushButton#ghost:hover {{ background: {c['selection']}; }}
QPushButton#ghost:focus {{ border: 2px solid {c['primary']}; padding: 6px 13px; }}
QPushButton#ghost:disabled {{ color: {c['text_faint']}; background: transparent; }}

/* 멈춤·중단 */
QPushButton#danger {{ background: {c['surface']}; border: 1px solid #E8B4BD; color: {c['danger']}; }}
QPushButton#danger:hover {{ background: {c['danger_bg']}; }}
QPushButton#danger:disabled {{ background: {c['surface_alt']}; color: {c['text_faint']}; border-color: {c['divider']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {c['border_strong']};
    border-radius: 5px;
    background: {c['surface']};
}}
QCheckBox::indicator:hover {{ border-color: {c['primary']}; }}
QCheckBox::indicator:checked {{ background: {c['primary']}; border-color: {c['primary']}; image: url({CHECK_ICON}); }}
QCheckBox:focus {{ color: {c['primary_hover']}; }}

/* ── 탭 ───────────────────────────────────────────────── */
QTabWidget::pane {{ border: none; border-top: 1px solid {c['divider']}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 4px;
    margin-right: 20px;
    color: {c['text_muted']};
    font-weight: 600;
}}
QTabBar::tab:hover    {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['primary_hover']}; border-bottom: 2px solid {c['primary']}; }}
QTabBar::tab:focus    {{ color: {c['primary_hover']}; }}

/* ── 표 ───────────────────────────────────────────────── */
QTableWidget, QTableView {{
    background: {c['surface']};
    border: 1px solid {c['divider']};
    border-radius: {r_ctl}px;
    gridline-color: {c['divider']};
    selection-background-color: {c['selection']};
    selection-color: {c['text']};
    outline: none;
}}
QTableWidget::item, QTableView::item {{ padding: 0 10px; border-bottom: 1px solid {c['divider']}; }}
QTableWidget::item:hover {{ background: {c['hover']}; }}
QTableWidget::item:selected {{ background: {c['selection']}; color: {c['text']}; }}
QHeaderView {{ background: {c['surface_alt']}; border: none; }}
QHeaderView::section {{
    background: {c['surface_alt']};
    border: none;
    border-bottom: 1px solid {c['border']};
    color: {c['text_muted']};
    font-size: {f['caption']}px;
    font-weight: 700;
    padding: 9px 10px;
}}
QTableCornerButton::section {{ background: {c['surface_alt']}; border: none; }}

/* ── 스크롤 · 기타 ───────────────────────────────────── */
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['border']}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['border_strong']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {c['surface']}; color: {c['text_muted']}; font-size: {f['caption']}px;
              border-top: 1px solid {c['divider']}; }}
QToolTip {{
    background: {c['text']};
    color: {c['surface']};
    border: none;
    padding: 6px 9px;
    font-size: {f['caption']}px;
}}
QMessageBox {{ background: {c['surface']}; }}
QMessageBox QLabel {{ font-size: {f['body']}px; }}
"""
