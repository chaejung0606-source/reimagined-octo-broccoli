"""스타일시트 — tokens.py 의 값을 Qt 스타일시트로 옮긴다.

화면 뼈대는 위에서부터  상단 바 → 작업 탭(탐색기형) → 흰 작업 표면 → 하단 독.
선택한 탭과 그 아래 작업 표면은 같은 흰색이라 이어져 보인다. 카드는 얇은 테두리가
기본이고, 그림자는 홈의 업무 카드와 독에만 옅게 준다.

Qt 스타일시트에는 box-shadow 가 없어 그림자는 QGraphicsDropShadowEffect 로 준다.
작업 탭은 모양이 복잡해(위만 둥근 모서리, 아래가 트인 선택 탭) 스타일시트 대신
shell.py 에서 직접 그린다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from .tokens import COLORS, FONT_FAMILY, FONT_SIZE, RADIUS, SHADOW, SHADOW_RGB

__all__ = ["COLORS", "STATUS", "card_shadow", "stylesheet"]

# QSS 의 image: 는 파일 경로만 받는다. 윈도우에서도 슬래시로 적어야 읽는다.
CHECK_ICON = (Path(__file__).parent / "assets" / "check.svg").as_posix()
CHEVRON_ICON = (Path(__file__).parent / "assets" / "chevron-down.svg").as_posix()

# 상태 배지: 이름 → (글자색, 바탕색)
STATUS = {
    name: (COLORS[name], COLORS[f"{name}_bg"])
    for name in ("success", "warning", "danger", "info", "neutral")
}


def card_shadow(widget: QWidget, kind: str = "card") -> None:
    """옅은 그림자. 테두리가 있는 카드에는 보통 주지 않는다."""
    spec = SHADOW[kind]
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(spec["blur"])
    effect.setOffset(0, spec["dy"])
    effect.setColor(QColor(*SHADOW_RGB, round(255 * spec["alpha"])))
    widget.setGraphicsEffect(effect)


def stylesheet() -> str:
    c = COLORS
    r_ctl, r_card, r_hero, r_dock = RADIUS["control"], RADIUS["card"], RADIUS["hero"], RADIUS["dock"]
    f = FONT_SIZE
    plate_rules = "".join(
        f"QFrame#taskArt_{name} {{ background: {c['surface']}; border: 1.5px solid {c[name]}; "
        f"border-radius: {r_card}px; }}\n"
        for name in ("lavender", "mint", "cyan", "peach", "sky"))
    return f"""
* {{
    font-family: {FONT_FAMILY};
    font-size: {f['body']}px;
    font-weight: 400;
    color: {c['text']};
}}
QMainWindow, QWidget#root {{ background: {c['bg']}; }}
/* 작업 표면 — 선택한 탭과 같은 흰색 */
QWidget#work {{ background: {c['surface']}; border: 1px solid {c['border']}; border-top: none;
               border-radius: 0 0 {r_card}px {r_card}px; }}
QWidget#page, QWidget#pageBody, QWidget#home {{ background: transparent; }}

/* ── 상단 바 ─────────────────────────────────────────── */
QWidget#topbar {{ background: {c['surface']}; border-bottom: 1px solid {c['divider']}; }}
QLabel#brand {{ font-size: 16px; font-weight: 700; }}
QLabel#workspace {{ font-size: {f['caption']}px; color: {c['text_muted']}; }}
QLineEdit#search {{
    background: {c['surface_alt']};
    border: 1px solid transparent;
    border-radius: 17px;
    padding: 6px 14px;
    min-height: 20px;
    max-width: 300px;
}}
QLineEdit#search:hover {{ border-color: {c['border']}; }}
QLineEdit#search:focus {{ background: {c['surface']}; border: 2px solid {c['primary']}; padding: 5px 13px; }}
QToolButton#topIcon {{
    background: transparent; border: 1px solid transparent; border-radius: {r_ctl}px;
    padding: 6px; min-width: 24px; min-height: 24px;
}}
QToolButton#topIcon:hover {{ background: {c['hover']}; }}
QToolButton#topIcon:focus {{ border: 2px solid {c['primary']}; }}
QToolButton#topIcon::menu-indicator {{ image: none; width: 0; }}
QPushButton#userMenu {{
    background: transparent; border: 1px solid transparent; border-radius: 17px;
    padding: 4px 12px 4px 6px; font-weight: 500; color: {c['text']};
}}
QPushButton#userMenu:hover {{ background: {c['hover']}; }}
QPushButton#userMenu::menu-indicator {{ image: none; width: 0; }}
QPushButton#aiChip {{
    border: 1px solid transparent; border-radius: 15px; padding: 4px 12px;
    font-size: {f['caption']}px; font-weight: 600;
}}
QPushButton#aiChip::menu-indicator {{ image: none; width: 0; }}
QPushButton#aiChip:focus {{ border: 2px solid {c['primary']}; }}
{''.join(f'QPushButton#aiChip[tone="{n}"] {{ background: {bg}; color: {fg}; }}' + chr(10) for n, (fg, bg) in STATUS.items())}
QLabel#avatar {{
    background: {c['selection']}; color: {c['primary_hover']};
    border-radius: 13px; min-width: 26px; max-width: 26px; min-height: 26px; max-height: 26px;
    font-size: {f['caption']}px; font-weight: 600;
}}
QMenu {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r_ctl + 2}px; padding: 6px;
}}
QMenu::item {{ padding: 8px 28px 8px 12px; border-radius: {r_ctl - 2}px; }}
QMenu::item:selected {{ background: {c['selection']}; color: {c['primary_hover']}; }}
QMenu::item:disabled {{ color: {c['text_faint']}; }}
QMenu::separator {{ height: 1px; background: {c['divider']}; margin: 6px 4px; }}
QMenu::icon {{ padding-left: 6px; }}

/* ── 작업 탭 줄 (탭 자체는 shell.py 가 그린다) ───────── */
QWidget#tabRow {{ background: {c['tabbar']}; }}
QToolButton#tabTool {{
    background: transparent; border: 1px solid transparent; border-radius: {r_ctl}px;
    padding: 4px; min-width: 22px; min-height: 22px; color: {c['text_muted']};
}}
QToolButton#tabTool:hover {{ background: {c['surface']}; border-color: {c['border']}; }}
QToolButton#tabTool:focus {{ border: 2px solid {c['primary']}; }}
QToolButton#tabTool::menu-indicator {{ image: none; width: 0; }}

/* ── 하단 독 ─────────────────────────────────────────── */
QWidget#dockArea {{ background: transparent; }}
QFrame#dock {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r_dock}px;
}}

/* ── 홈 ──────────────────────────────────────────────── */
QLabel#homeTitle {{ font-size: 28px; font-weight: 700; }}
QLabel#homeSub {{ font-size: {f['section']}px; color: {c['text_muted']}; }}
/* 업무 타일 — 테두리 없음. 마우스가 올라오면 옅은 바탕, 키보드 초점은 라벤더 테두리 */
QFrame#taskTile {{ background: transparent; border: 2px solid transparent; border-radius: {r_hero}px; }}
QFrame#taskTile:hover {{ background: {c['hover']}; }}
QFrame#taskTile[focused="true"] {{ border: 2px solid {c['primary']}; }}
{plate_rules}
QLabel#taskName {{ font-size: 16px; font-weight: 600; }}
QLabel#taskStatus {{ font-size: {f['caption']}px; font-weight: 500; color: {c['text_faint']}; }}
QLabel#homeSection {{ font-size: {f['section']}px; font-weight: 600; }}
QFrame#recentRow {{
    background: {c['surface']}; border: 1px solid {c['border']}; border-radius: {r_ctl + 4}px;
}}
QFrame#recentRow:hover {{ background: {c['hover']}; }}
QFrame#updateBanner {{
    background: {c['selection']}; border: 1px solid {c['lavender']}; border-radius: {r_ctl + 4}px;
}}

/* ── 페이지 머리 ──────────────────────────────────────── */
QLabel#breadcrumb {{ font-size: {f['caption']}px; color: {c['text_faint']}; }}
QLabel#pageTitle  {{ font-size: {f['title']}px; font-weight: 700; }}
QLabel#pageDesc   {{ font-size: {f['small']}px; color: {c['text_muted']}; }}

/* ── 카드 ─────────────────────────────────────────────── */
QFrame#card {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r_card}px;
}}
QFrame#cardCurrent {{
    background: {c['surface']};
    border: 2px solid {c['primary']};
    border-radius: {r_card}px;
}}
QFrame#cardDone {{
    background: {c['surface_alt']};
    border: 1px solid {c['border']};
    border-radius: {r_card}px;
}}
QLabel#cardTitle {{ font-size: {f['card']}px; font-weight: 600; }}
QLabel#cardHint  {{ font-size: {f['small']}px; color: {c['text_muted']}; }}
QLabel#body      {{ font-size: {f['body']}px; color: {c['text']}; }}
QLabel#muted     {{ font-size: {f['small']}px; color: {c['text_muted']}; }}
QLabel#stepNo    {{
    font-size: {f['caption']}px; font-weight: 600; color: {c['primary_hover']};
    background: {c['selection']}; border-radius: 11px; min-width: 14px; padding: 3px 7px;
}}
QLabel#stepNoDone {{
    font-size: {f['caption']}px; font-weight: 600; color: {c['success']};
    background: {c['success_bg']}; border-radius: 11px; min-width: 14px; padding: 3px 7px;
}}
QPushButton#disclosure {{
    background: transparent; border: none; color: {c['primary_hover']};
    font-size: {f['small']}px; font-weight: 500; padding: 2px 4px; text-align: left;
}}
QPushButton#disclosure:hover {{ text-decoration: underline; }}

QLabel#kpiLabel   {{ font-size: {f['small']}px; font-weight: 500; color: {c['text_muted']}; }}
QLabel#kpiValue   {{ font-size: {f['kpi']}px; font-weight: 600; color: {c['text']}; }}
QLabel#kpiCaption {{ font-size: {f['caption']}px; color: {c['text_faint']}; }}

/* 상태 배지 — 색과 글자를 함께 */
{''.join(f"QLabel#pill_{n} {{ background: {bg}; color: {fg}; border-radius: 10px; padding: 2px 9px; font-size: {f['caption']}px; font-weight: 500; }}" for n, (fg, bg) in STATUS.items())}

/* 사람 차례 알림 띠 */
QFrame#banner {{
    background: {c['warning_bg']};
    border: 1px solid #F0D3A8;
    border-radius: {r_ctl + 4}px;
}}
QLabel#bannerText {{ font-weight: 500; color: {c['text']}; }}

/* 회의 폴더 끌어다 놓기 — 점선 테두리, 끌고 들어오면 라벤더 */
QFrame#dropZone {{
    background: {c['surface_alt']}; border: 1.5px dashed {c['border_strong']}; border-radius: {r_card}px;
}}
QFrame#dropZone[active="true"] {{ background: {c['selection']}; border-color: {c['primary']}; }}
QProgressBar {{ background: {c['surface_alt']}; border: 1px solid {c['border']}; border-radius: 4px; }}
QProgressBar::chunk {{ background: {c['primary']}; border-radius: 3px; }}

/* 준비 중 안내 띠 */
QFrame#notice {{
    background: {c['info_bg']}; border: 1px solid #C9DDF0; border-radius: {r_ctl + 4}px;
}}
QLabel#noticeText {{ color: {c['text']}; }}

/* ── 입력 ─────────────────────────────────────────────── */
QLabel#fieldLabel {{ font-size: {f['small']}px; font-weight: 500; color: {c['text']}; }}
QLabel#fieldHelp  {{ font-size: {f['caption']}px; color: {c['text_muted']}; }}
QLabel#fieldError {{ font-size: {f['caption']}px; color: {c['danger']}; font-weight: 500; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit, QPlainTextEdit, QTextEdit, QTextBrowser {{
    background: {c['surface']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: {r_ctl}px;
    padding: 7px 10px;
    min-height: 22px;
    selection-background-color: {c['selection']};
    selection-color: {c['text']};
}}
QLineEdit:hover, QComboBox:hover, QDoubleSpinBox:hover, QDateTimeEdit:hover {{ border-color: {c['border_strong']}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {c['primary']};
    padding: 6px 9px;
}}
QLineEdit:read-only, QPlainTextEdit[readOnly="true"], QTextBrowser {{ background: {c['surface_alt']}; }}
/* 펼침 단추를 따로 꾸미지 않으면 테두리를 바꾼 고르기 칸 오른쪽 아래에 운영체제 기본 단추의 검은 선이 비친다 */
QComboBox {{ padding-right: 28px; }}
QComboBox:focus {{ padding-right: 27px; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; background: transparent; }}
QComboBox::down-arrow {{ image: url({CHEVRON_ICON}); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url({CHEVRON_ICON}); }}
/* 날짜시각 칸(주차등록 유효기간)의 달력 단추도 고르기 칸처럼 */
QDateTimeEdit {{ padding-right: 28px; }}
QDateTimeEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 26px; border: none; background: transparent; }}
QDateTimeEdit::down-arrow {{ image: url({CHEVRON_ICON}); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {c['surface']}; color: {c['text']}; border: 1px solid {c['border']};
    selection-background-color: {c['selection']}; selection-color: {c['text']}; outline: 0;
}}
/* 숫자 칸 안쪽의 글자 칸에까지 위 여백·테두리가 겹쳐 붙으면 값이 칸 밖으로 밀려 안 보인다 */
QAbstractSpinBox QLineEdit {{ border: none; padding: 0; min-height: 0; background: transparent; }}
/* 화살표는 쓰지 않는다. 키보드 위·아래 화살표로는 값이 바뀐다 */
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: 0; border: none; }}
QLineEdit:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled {{
    background: {c['surface_alt']}; color: {c['text_faint']}; border-style: dashed;
}}
QLineEdit[error="true"] {{ border: 2px solid {c['danger']}; padding: 6px 9px; }}
QPlainTextEdit#logView, QPlainTextEdit#foldLog {{
    font-family: "D2Coding", "Consolas", "Cascadia Mono", monospace;
    font-size: {f['table']}px;
    color: {c['text_muted']};
}}
/* 단계 아래에 펼치는 진행 기록(청구서 받기) — 창이 낮아도 몇 줄은 읽히게. 픽셀이 아니라 글자 크기로 */
QPlainTextEdit#foldLog {{ min-height: 4em; }}

/* ── 버튼 ─────────────────────────────────────────────── */
QPushButton {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r_ctl}px;
    padding: 7px 14px;
    min-height: 22px;
    font-weight: 500;
    color: {c['text']};
}}
QPushButton:hover    {{ background: {c['hover']}; border-color: {c['border_strong']}; }}
QPushButton:pressed  {{ background: {c['divider']}; }}
QPushButton:focus    {{ border: 2px solid {c['primary']}; padding: 6px 13px; }}
QPushButton:disabled {{ background: {c['surface_alt']}; color: {c['text_faint']}; border-color: {c['divider']}; }}

QPushButton#primary {{
    background: {c['primary']};
    border: 1px solid {c['primary']};
    color: {c['on_primary']};
}}
QPushButton#primary:hover   {{ background: {c['primary_hover']}; border-color: {c['primary_hover']}; }}
QPushButton#primary:pressed {{ background: {c['primary_hover']}; }}
QPushButton#primary:focus   {{ border: 2px solid {c['text']}; padding: 6px 13px; }}
QPushButton#primary:disabled {{ background: {c['border']}; border-color: {c['border']}; color: {c['text_muted']}; }}

QPushButton#ghost {{ background: transparent; border: 1px solid transparent; color: {c['primary_hover']}; }}
QPushButton#ghost:hover {{ background: {c['selection']}; }}
QPushButton#ghost:focus {{ border: 2px solid {c['primary']}; padding: 6px 13px; }}
QPushButton#ghost:disabled {{ color: {c['text_faint']}; background: transparent; }}

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

/* ── 탭(카드 안) ──────────────────────────────────────── */
QTabWidget::pane {{ border: none; border-top: 1px solid {c['divider']}; top: -1px; }}
QTabBar::tab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 4px;
    margin-right: 20px;
    color: {c['text_muted']};
    font-weight: 500;
}}
QTabBar::tab:hover    {{ color: {c['text']}; }}
QTabBar::tab:selected {{ color: {c['primary_hover']}; border-bottom: 2px solid {c['primary']}; }}
QTabBar::tab:focus    {{ color: {c['primary_hover']}; }}

/* ── 표 ───────────────────────────────────────────────── */
QTableWidget, QTableView {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r_ctl}px;
    gridline-color: {c['divider']};
    selection-background-color: {c['selection']};
    selection-color: {c['text']};
    outline: none;
    font-size: {f['table']}px;
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
    font-weight: 600;
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

QStatusBar {{ background: transparent; color: {c['text_muted']}; font-size: {f['caption']}px; }}
QToolTip {{
    background: {c['text']};
    color: {c['surface']};
    border: none;
    padding: 6px 9px;
    font-size: {f['caption']}px;
}}
QMessageBox {{ background: {c['surface']}; }}
QDialog#reportDialog {{ background: {c['surface']}; }}
QMessageBox QLabel {{ font-size: {f['body']}px; }}
"""
