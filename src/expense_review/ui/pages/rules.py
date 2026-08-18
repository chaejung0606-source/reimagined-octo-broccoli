"""검토 기준 페이지 — 서류 종류별로 기준을 확인하고 고친다.

고친 내용은 배포본 `rules/*.yaml` 이 아니라 `~/.expense-review/` 에 저장한다.
그래야 자동 업데이트를 받아도 수정 내용이 살아남는다(config.py 참고).

판정 로직 자체는 코드에 있으므로 여기서 바꾸지 않는다. 담당자가 실무에서
바꾸고 싶은 것 — 등급, 사용 여부, 검출·조치 문구, 한도값 — 만 연다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...classify import DOC_LABELS
from ...engine import CHECKS, Rule, load_ruleset
from ...models import Severity
from ...review import EXPENSE_TYPES
from ..theme import COLORS, SEVERITY_STYLE, card_shadow
from ..widgets import Card, muted_label

LAYER_LABELS = {
    "L0": "서류 완비성",
    "L1": "문서 내부 정합성",
    "L2": "문서 간 교차 정합성",
    "L3": "규정·한도",
}

SEVERITY_CHOICES = [("수정 필요", "ERROR"), ("확인 요망", "WARN"), ("참고", "INFO")]


class RulesPage(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("page")
        self._current: Rule | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 26, 32, 26)
        layout.setSpacing(22)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel("검토 기준")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addWidget(muted_label(
            "지출종류·서류별 검토 기준입니다. 등급과 문구, 한도값을 고칠 수 있으며 "
            "고친 내용은 업데이트를 받아도 유지됩니다."
        ))
        layout.addLayout(header)

        picker = QHBoxLayout()
        picker.setSpacing(14)
        picker.addWidget(_label("지출종류"))
        self.expense_type = QComboBox()
        self.expense_type.addItems(EXPENSE_TYPES)
        self.expense_type.currentTextChanged.connect(self._reload)
        self.expense_type.setMinimumWidth(180)
        picker.addWidget(self.expense_type)
        self.count_label = QLabel("")
        self.count_label.setObjectName("cardHint")
        picker.addWidget(self.count_label)
        picker.addStretch(1)
        layout.addLayout(picker)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_tree_card())
        splitter.addWidget(self._build_editor())
        splitter.setSizes([560, 540])
        layout.addWidget(splitter, 1)

        self._reload(self.expense_type.currentText())

    # ── 왼쪽: 규칙 목록 ─────────────────────────────────────────────────
    def _build_tree_card(self) -> QWidget:
        card = Card("기준 목록", "검토 단계 · 대상 서류별")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["기준", "등급"])
        self.tree.setColumnWidth(0, 380)
        self.tree.currentItemChanged.connect(self._on_select)
        card.add(self.tree, 1)
        return card

    # ── 오른쪽: 편집기 ──────────────────────────────────────────────────
    def _build_editor(self) -> QWidget:
        """편집 칸은 스크롤 안에 넣는다.

        창이 작아지면 입력칸이 서로 겹쳐 글자가 잘린다. 억지로 한 화면에
        욱여넣는 대신 세로로 넘겨 보게 한다.
        """
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        holder.setObjectName("page")
        scroll.setWidget(holder)
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(4, 4, 12, 6)
        outer.setSpacing(20)

        self.editor_card = Card("기준 편집", "선택한 기준")
        form = QFormLayout()
        form.setSpacing(12)

        self.rule_title = QLabel("왼쪽에서 기준을 선택하세요.")
        self.rule_title.setWordWrap(True)
        self.rule_title.setStyleSheet("font-size: 13px; font-weight: 700;")
        self.editor_card.add(self.rule_title)

        self.rule_meta = QLabel("")
        self.rule_meta.setObjectName("cardHint")
        self.rule_meta.setWordWrap(True)
        self.editor_card.add(self.rule_meta)

        self.severity_combo = QComboBox()
        for label, value in SEVERITY_CHOICES:
            self.severity_combo.addItem(label, value)
        form.addRow("등급", self.severity_combo)

        self.enabled_combo = QComboBox()
        self.enabled_combo.addItem("사용", True)
        self.enabled_combo.addItem("사용 안 함", False)
        form.addRow("사용 여부", self.enabled_combo)

        self.message_edit = QPlainTextEdit()
        self.message_edit.setMinimumHeight(66)
        self.message_edit.setMaximumHeight(90)
        form.addRow("검출 문구", self.message_edit)

        self.fix_edit = QPlainTextEdit()
        self.fix_edit.setMinimumHeight(66)
        self.fix_edit.setMaximumHeight(90)
        form.addRow("조치 문구", self.fix_edit)

        self.editor_card.add_layout(form)
        self.editor_card.add(muted_label(
            "문구 안의 {중괄호} 는 검토할 때 실제 값으로 바뀝니다. 그대로 두세요."
        ))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.reset_button = QPushButton("기본값으로")
        self.reset_button.setObjectName("ghost")
        self.reset_button.clicked.connect(self._reset_rule)
        self.save_button = QPushButton("저장")
        self.save_button.setObjectName("primary")
        card_shadow(self.save_button, blur=18, alpha=28, dy=4)
        self.save_button.clicked.connect(self._save_rule)
        buttons.addWidget(self.reset_button)
        buttons.addWidget(self.save_button)
        self.editor_card.add_layout(buttons)
        self._set_editor_enabled(False)
        outer.addWidget(self.editor_card)

        outer.addWidget(self._build_settings_card(), 1)
        return scroll

    def _build_settings_card(self) -> QWidget:
        card = Card("한도·기준값", "지출종류별 설정")
        card.add(muted_label(
            "규정 문서에서 확인한 값을 넣으면 관련 기준이 자동으로 켜집니다. "
            "비워 두면 해당 기준은 '규정값 미설정' 으로 검사하지 않습니다."
        ))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.settings_holder = QWidget()
        self.settings_holder.setObjectName("page")
        self.settings_form = QFormLayout(self.settings_holder)
        self.settings_form.setSpacing(12)
        scroll.setWidget(self.settings_holder)
        card.add(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("설정 저장")
        save.setObjectName("primary")
        card_shadow(save, blur=18, alpha=28, dy=4)
        save.clicked.connect(self._save_settings)
        buttons.addWidget(save)
        card.add_layout(buttons)
        return card

    # ── 데이터 ───────────────────────────────────────────────────────────
    def _reload(self, expense_type: str) -> None:
        self.ruleset = load_ruleset(expense_type)
        self._rebuild_tree()
        self._rebuild_settings()

    def _rebuild_tree(self) -> None:
        self.tree.clear()
        overrides = config.load_overrides()["rules"]

        by_layer: dict[str, list[Rule]] = {}
        for rule in self.ruleset.rules:
            by_layer.setdefault(rule.layer, []).append(rule)

        implemented = 0
        for layer in ("L0", "L1", "L2", "L3"):
            rules = by_layer.get(layer, [])
            if not rules:
                continue
            group = QTreeWidgetItem([f"{layer} · {LAYER_LABELS[layer]} ({len(rules)})", ""])
            group.setExpanded(layer != "L3")
            self.tree.addTopLevelItem(group)

            for rule in sorted(rules, key=lambda r: r.id):
                marks = []
                if rule.id not in CHECKS:
                    marks.append("미구현")
                if not rule.enabled:
                    marks.append("사용 안 함")
                if rule.id in overrides:
                    marks.append("수정됨")
                else:
                    implemented += 1 if rule.id in CHECKS else 0

                suffix = f"   [{' · '.join(marks)}]" if marks else ""
                item = QTreeWidgetItem([f"{rule.id}  {rule.title}{suffix}",
                                        SEVERITY_STYLE[rule.severity.name]["label"]])
                item.setData(0, Qt.UserRole, rule)
                if rule.id not in CHECKS:
                    item.setForeground(0, Qt.gray)
                group.addChild(item)

        auto = sum(1 for rule in self.ruleset.rules if rule.id in CHECKS)
        self.count_label.setText(
            f"기준 {len(self.ruleset.rules)}건 · 자동 판정 {auto}건 · "
            f"수정됨 {sum(1 for r in self.ruleset.rules if r.id in overrides)}건"
        )

    def _rebuild_settings(self) -> None:
        while self.settings_form.count():
            item = self.settings_form.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.setting_inputs: dict[str, QLineEdit] = {}
        for key, value in sorted(self.ruleset.settings.items()):
            if isinstance(value, (dict, list)):
                continue      # 표 형태 설정은 편집기에서 다루지 않는다
            edit = QLineEdit("" if value is None else str(value))
            edit.setPlaceholderText("미설정")
            self.settings_form.addRow(_setting_label(key), edit)
            self.setting_inputs[key] = edit

    # ── 선택·편집 ────────────────────────────────────────────────────────
    def _on_select(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        rule = current.data(0, Qt.UserRole) if current else None
        self._current = rule
        if rule is None:
            self.rule_title.setText("왼쪽에서 기준을 선택하세요.")
            self.rule_meta.setText("")
            self._set_editor_enabled(False)
            return

        self.rule_title.setText(f"{rule.id} · {rule.title}")
        state = "자동 판정" if rule.id in CHECKS else "자동 판정하지 않음(미구현)"
        overridden = "  ·  수정됨" if rule.overridden else ""
        self.rule_meta.setText(
            f"{rule.layer} · {LAYER_LABELS.get(rule.layer, rule.layer)}  ·  {state}{overridden}"
        )

        index = self.severity_combo.findData(rule.severity.value)
        self.severity_combo.setCurrentIndex(max(index, 0))
        self.enabled_combo.setCurrentIndex(0 if rule.enabled else 1)
        self.message_edit.setPlainText(rule.message)
        self.fix_edit.setPlainText(rule.fix)
        self._set_editor_enabled(True)

    def _set_editor_enabled(self, enabled: bool) -> None:
        for widget in (self.severity_combo, self.enabled_combo, self.message_edit,
                       self.fix_edit, self.save_button, self.reset_button):
            widget.setEnabled(enabled)

    def _save_rule(self) -> None:
        if self._current is None:
            return
        rule_id = self._current.id
        config.set_rule_override(rule_id, "severity", self.severity_combo.currentData())
        config.set_rule_override(rule_id, "enabled", self.enabled_combo.currentData())
        config.set_rule_override(rule_id, "message", self.message_edit.toPlainText().strip())
        config.set_rule_override(rule_id, "fix", self.fix_edit.toPlainText().strip())
        self._reload(self.expense_type.currentText())
        QMessageBox.information(self, "저장", f"{rule_id} 기준을 저장했습니다.")

    def _reset_rule(self) -> None:
        if self._current is None:
            return
        config.clear_rule_override(self._current.id)
        self._reload(self.expense_type.currentText())
        QMessageBox.information(self, "되돌림", "배포본 기본값으로 되돌렸습니다.")

    def _save_settings(self) -> None:
        expense_type = self.expense_type.currentText()
        for key, edit in self.setting_inputs.items():
            text = edit.text().strip()
            if not text:
                config.clear_setting_override(expense_type, key)
                continue
            config.set_setting_override(expense_type, key, _coerce(text))
        self._reload(expense_type)
        QMessageBox.information(self, "저장", "한도·기준값을 저장했습니다.")


def _coerce(text: str):
    """입력한 문자열을 숫자·불리언으로 바꾼다. 안 되면 문자열 그대로."""
    lowered = text.lower()
    if lowered in ("true", "예", "on"):
        return True
    if lowered in ("false", "아니오", "off"):
        return False
    try:
        return int(text.replace(",", ""))
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("statLabel")
    return label


SETTING_LABELS = {
    "max_hours_per_day": "1일 근로시간 한도",
    "max_hours_per_month": "월 근로시간 한도",
    "allow_weekend_work": "주말·공휴일 근로 허용",
    "standard_amount": "표준 지급액(원)",
    "hourly_rate": "시간당 단가(원)",
    "min_members": "소학회 최소 인원",
    "report_max_pages": "활동보고서 최대 쪽수",
    "student_id_pattern": "학번 형식(정규식)",
    "daily_allowance": "일비 한도(원)",
    "meal_allowance": "식비 한도(원)",
    "lodging_cap": "숙박비 한도(원/박)",
    "km_rate": "자가용 km당 단가(원)",
    "route_asymmetry_tolerance": "왕복 거리 차 허용치(비율)",
}


def _setting_label(key: str) -> QLabel:
    label = QLabel(SETTING_LABELS.get(key, key))
    label.setObjectName("statLabel")
    label.setToolTip(key)
    return label
