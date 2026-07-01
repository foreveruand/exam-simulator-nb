import random
import re
from collections import defaultdict

from aqt import mw
from aqt.qt import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QEvent, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QInputDialog, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QStackedWidget, QTableWidget,
    QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, Qt,
)

# ── Defaults (user can override in launcher) ─────────────────────────────────
DEFAULT_NOTE_TYPE = "MCQ-NB"

FLAG_DEFS = [
    (1, "Red",       "#ef4444"),
    (2, "Orange",    "#f97316"),
    (3, "Green",     "#22c55e"),
    (4, "Blue",      "#3b82f6"),
    (5, "Pink",      "#ec4899"),
    (6, "Turquoise", "#06b6d4"),
    (7, "Purple",    "#a855f7"),
]

MULTI_SELECT_TAGS = {
    "multi-choice", "multichoice", "multi-select", "multiselect",
    "multiple-select", "multiple-response", "多选",
}
SINGLE_SELECT_TAGS = {
    "single-choice", "singlechoice", "single-select", "singleselect",
    "单选",
}
TRUE_FALSE_TAGS = {
    "true-false", "truefalse", "tf", "判断", "是非",
}
SHORT_ANSWER_TAGS = {
    "short-answer", "shortanswer", "free-text", "freetext",
    "essay", "简答", "简答题",
}

# ── Helpers ──────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _note_tag_tokens(note):
    tokens = set()
    for tag in getattr(note, "tags", []):
        normalized = str(tag).strip().lower().replace("_", "-")
        if not normalized:
            continue
        tokens.add(normalized)
        tokens.update(part for part in normalized.split("::") if part)
    return tokens


def _normalize_option_text(text: str) -> str:
    return re.sub(r"[\s\.\。:：;；,，、()（）\[\]【】]+", "", text).lower()


def _is_true_false_question(question):
    if len(question["options"]) != 2 or len(question["correct"]) != 1:
        return False
    values = {_normalize_option_text(text) for text in question["options"].values()}
    true_false_sets = [
        {"对", "错"},
        {"正确", "错误"},
        {"true", "false"},
        {"t", "f"},
        {"yes", "no"},
    ]
    return values in true_false_sets


def _answer_mode(correct, tag_tokens):
    if tag_tokens & SHORT_ANSWER_TAGS:
        return "short"
    if tag_tokens & (SINGLE_SELECT_TAGS | TRUE_FALSE_TAGS):
        return "single"
    if tag_tokens & MULTI_SELECT_TAGS:
        return "multi"
    return "multi" if len(correct) > 1 else "single"


def _parse_note(note, note_type_name):
    """Parse a note into a structured dict. Returns None if invalid."""
    try:
        question = _strip_html(note["Question"].strip())
        if not question:
            return None
        options = {}
        for letter, field in [
            ("A", "option_1 (A)"), ("B", "option_2 (B)"),
            ("C", "option_3 (C)"), ("D", "option_4 (D)"),
            ("E", "option_5 (E)"),
        ]:
            try:
                val = _strip_html(note[field].strip())
                if val:
                    options[letter] = val
            except Exception:
                pass
        raw_ans = note["Ans"].strip().upper()
        raw_answer_text = note["Ans"].strip()
        tag_tokens = _note_tag_tokens(note)
        if not options:
            if not raw_answer_text:
                return None
            source = ""
            try:
                source = _strip_html(note["Source"].strip())
            except Exception:
                pass
            explanation = ""
            try:
                explanation = note["Explanation"].strip()   # keep HTML for rendering
            except Exception:
                pass
            return {
                "question":      question,
                "options":       {},
                "correct":       [],
                "correct_text":  raw_answer_text,
                "source":        source,
                "explanation":   explanation,
                "answer_mode":   "short",
                "is_true_false": False,
            }
        correct = set()
        for ch in raw_ans:
            if ch in "ABCDE":
                correct.add(ch)
            elif ch in "12345":
                correct.add(chr(ord("A") + int(ch) - 1))
        correct = correct & set(options.keys())
        if not correct:
            return None
        source = ""
        try:
            source = _strip_html(note["Source"].strip())
        except Exception:
            pass
        explanation = ""
        try:
            explanation = note["Explanation"].strip()   # keep HTML for rendering
        except Exception:
            pass
        parsed = {
            "question":    question,
            "options":     options,
            "correct":     sorted(correct),
            "source":      source,
            "explanation": explanation,
            "answer_mode": _answer_mode(correct, tag_tokens),
        }
        parsed["is_true_false"] = (
            len(options) == 2
            and bool((tag_tokens & TRUE_FALSE_TAGS) or _is_true_false_question(parsed))
        )
        return parsed
    except Exception:
        return None


def _smart_sample(note_ids_with_meta, limit):
    """
    Round-robin across sub-decks so every lesson gets represented.
    Membership is balanced; ordering is preserved unless shuffle is applied later.
    note_ids_with_meta: list of (nid, meta_dict)
    Returns a list of nids of length `limit`.
    """
    groups = defaultdict(list)
    for nid, meta in note_ids_with_meta:
        groups[meta["deck"]].append(nid)
    buckets = list(groups.values())
    result = []
    idx = 0
    while len(result) < limit:
        buckets = [b for b in buckets if b]
        if not buckets:
            break
        i = idx % len(buckets)
        result.append(buckets[i].pop(0))
        idx += 1
    return result[:limit]


def _tagged_sample(note_ids, note_meta, rules, shuffle_groups=False):
    selected = []
    used = set()
    shortages = []

    for tag, limit in rules:
        candidates = [
            (nid, note_meta.get(nid, {"deck": ""}))
            for nid in note_ids
            if nid not in used and tag in note_meta.get(nid, {}).get("tags", [])
        ]
        if shuffle_groups:
            random.shuffle(candidates)
        sampled = _smart_sample(candidates, limit)
        if shuffle_groups:
            random.shuffle(sampled)
        selected.extend(sampled)
        used.update(sampled)
        if len(sampled) < limit:
            shortages.append((tag, limit, len(sampled)))

    return selected, shortages


def _shuffle_question_options(question):
    if question.get("answer_mode") == "short":
        return
    if question.get("is_true_false"):
        return
    items = list(question["options"].items())
    random.shuffle(items)
    letters = ["A", "B", "C", "D", "E"]
    mapping = {}
    shuffled_options = {}
    for idx, (old_letter, text) in enumerate(items):
        new_letter = letters[idx]
        mapping[old_letter] = new_letter
        shuffled_options[new_letter] = text
    question["options"] = shuffled_options
    question["correct"] = sorted(
        mapping[letter] for letter in question["correct"] if letter in mapping
    )


# ── Card Picker Dialog ────────────────────────────────────────────────────────

class CardPickerDialog(QDialog):
    def __init__(self, parent, note_type_name):
        super().__init__(parent)
        self.note_type_name = note_type_name
        self.setWindowTitle("Browse & Select Questions")
        self.resize(1060, 680)
        self.setMinimumSize(800, 500)

        self._note_meta       = {}   # nid -> {deck, tags, flag, preview}
        self._all_note_ids    = []
        self._selected        = set()
        self._active_deck     = None
        self._active_tags     = set()
        self._active_exam_tags = set()
        self._active_flags    = set()
        self._history_index   = {}

        self._build_ui()
        self._load_all_notes()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)

        h_splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(h_splitter, 1)

        # ── LEFT panel: native filter list + one active panel ───────────────
        left = QWidget()
        left.setMinimumWidth(260)
        left.setMaximumWidth(340)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.setSpacing(6)

        nav_row = QVBoxLayout()
        nav_row.setSpacing(4)
        self._filter_buttons = QButtonGroup(self)
        self._filter_buttons.setExclusive(True)
        self._filter_stack = QStackedWidget()

        # Deck panel
        deck_widget = QWidget()
        dv = QVBoxLayout(deck_widget)
        dv.setContentsMargins(8, 8, 8, 8)
        dv.setSpacing(6)
        deck_lbl = QLabel("Browse decks")
        deck_lbl.setStyleSheet("font-weight:bold;font-size:13px;")
        dv.addWidget(deck_lbl)
        self.deck_tree = QTreeWidget()
        self.deck_tree.setHeaderHidden(True)
        self.deck_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.deck_tree.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.deck_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.deck_tree.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.deck_tree.itemSelectionChanged.connect(self._on_deck_changed)
        dv.addWidget(self.deck_tree)
        self._filter_stack.addWidget(deck_widget)

        # Tags panel
        tag_widget = QWidget()
        tv = QVBoxLayout(tag_widget)
        tv.setContentsMargins(8, 8, 8, 8)
        tv.setSpacing(6)
        tag_lbl = QLabel("Tags")
        tag_lbl.setStyleSheet("font-weight:bold;font-size:13px;")
        tv.addWidget(tag_lbl)
        self.tag_list = QListWidget()
        self.tag_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.tag_list.setStyleSheet(
            "QListWidget::item { padding: 5px 6px; }"
            "QListWidget::indicator { width: 20px; height: 20px; }"
        )
        self.tag_list.itemChanged.connect(self._on_tag_changed)
        self.tag_list.viewport().installEventFilter(self)
        tv.addWidget(self.tag_list)
        self._filter_stack.addWidget(tag_widget)

        # Simulation History panel
        exam_tag_widget = QWidget()
        etv = QVBoxLayout(exam_tag_widget)
        etv.setContentsMargins(8, 8, 8, 8)
        etv.setSpacing(6)
        exam_tag_lbl = QLabel("Simulation History")
        exam_tag_lbl.setStyleSheet("font-weight:bold;font-size:13px;")
        etv.addWidget(exam_tag_lbl)

        history_btn_row = QHBoxLayout()
        self.delete_history_btn = QPushButton("Delete selected")
        self.clear_history_btn = QPushButton("Clear all")
        self.delete_history_btn.clicked.connect(self._delete_selected_history)
        self.clear_history_btn.clicked.connect(self._clear_all_history)
        history_btn_row.addWidget(self.delete_history_btn)
        history_btn_row.addWidget(self.clear_history_btn)
        etv.addLayout(history_btn_row)

        self.exam_tag_list = QListWidget()
        self.exam_tag_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection)
        self.exam_tag_list.setStyleSheet(
            "QListWidget::item { padding: 5px 6px; }"
            "QListWidget::indicator { width: 20px; height: 20px; }"
        )
        self.exam_tag_list.itemChanged.connect(self._on_exam_tag_changed)
        self.exam_tag_list.viewport().installEventFilter(self)
        etv.addWidget(self.exam_tag_list)
        self._filter_stack.addWidget(exam_tag_widget)

        # Flags panel
        flag_widget = QWidget()
        fv = QVBoxLayout(flag_widget)
        fv.setContentsMargins(8, 8, 8, 8)
        fv.setSpacing(6)
        flag_lbl = QLabel("Flags")
        flag_lbl.setStyleSheet("font-weight:bold;font-size:13px;")
        fv.addWidget(flag_lbl)
        self._flag_checks = {}
        for fnum, name, color in FLAG_DEFS:
            cb = QCheckBox(f"  {name}")
            cb.setStyleSheet(f"color:{color};font-weight:bold;font-size:12px;")
            cb.stateChanged.connect(self._on_flag_changed)
            self._flag_checks[fnum] = cb
            fv.addWidget(cb)
        fv.addStretch()
        self._filter_stack.addWidget(flag_widget)

        for idx, label in enumerate(["Decks", "Tags", "Simulation History", "Flags"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFlat(True)
            btn.clicked.connect(lambda checked, i=idx: self._set_filter_panel(i))
            self._filter_buttons.addButton(btn, idx)
            nav_row.addWidget(btn)

        lv.addLayout(nav_row)
        lv.addWidget(self._filter_stack, 1)
        h_splitter.addWidget(left)

        # ── RIGHT panel: search + active filters + list ───────────────────
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setSpacing(6)
        rv.setContentsMargins(4, 4, 4, 4)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("🔍  Search question text…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._apply_filters)
        rv.addWidget(self.search_box)

        self._active_filters_wrap = QWidget()
        self._active_filters_layout = QHBoxLayout(self._active_filters_wrap)
        self._active_filters_layout.setContentsMargins(0, 0, 0, 0)
        self._active_filters_layout.setSpacing(6)
        rv.addWidget(self._active_filters_wrap)

        sel_row = QHBoxLayout()
        sel_all = QPushButton("✓ Select all visible")
        sel_none = QPushButton("✕ Deselect all visible")
        sel_all.clicked.connect(self._select_all_visible)
        sel_none.clicked.connect(self._deselect_visible)
        self.preview_btn = QPushButton("👁  Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setToolTip("Show/hide question preview panel")
        self.preview_btn.toggled.connect(self._toggle_preview)
        self.visible_lbl = QLabel("0 shown")
        self.visible_lbl.setStyleSheet("color:#64748b;")
        self.count_lbl = QLabel("Selected: 0")
        self.count_lbl.setStyleSheet("font-weight:bold;color:#2563eb;")
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        sel_row.addWidget(self.preview_btn)
        sel_row.addStretch()
        sel_row.addWidget(self.visible_lbl)
        sel_row.addWidget(self.count_lbl)
        rv.addLayout(sel_row)

        self._list_preview_splitter = QSplitter(Qt.Orientation.Horizontal)

        self.result_list = QListWidget()
        self.result_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.result_list.setSpacing(2)
        self.result_list.setStyleSheet(
            "QListWidget::item { padding: 5px 6px; }"
            "QListWidget::indicator { width: 20px; height: 20px; }"
        )
        self.result_list.viewport().installEventFilter(self)
        self.result_list.itemChanged.connect(self._on_result_item_changed)
        self.result_list.currentItemChanged.connect(self._on_preview_item)
        self._list_preview_splitter.addWidget(self.result_list)

        self._preview_pane = QWidget()
        self._preview_pane.setMinimumWidth(280)
        self._preview_pane.setVisible(False)
        pv_outer = QVBoxLayout(self._preview_pane)
        pv_outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._preview_inner = QWidget()
        self._preview_layout = QVBoxLayout(self._preview_inner)
        self._preview_layout.setSpacing(6)
        self._preview_layout.setContentsMargins(14, 14, 14, 14)
        self._preview_layout.addStretch()
        scroll.setWidget(self._preview_inner)
        pv_outer.addWidget(scroll)
        self._list_preview_splitter.addWidget(self._preview_pane)
        self._list_preview_splitter.setSizes([700, 0])

        rv.addWidget(self._list_preview_splitter, 1)

        h_splitter.addWidget(right)
        h_splitter.setSizes([300, 760])

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Use Selected  ▶")
        ok.setDefault(True)
        ok.clicked.connect(self._confirm)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

        first_btn = self._filter_buttons.button(0)
        if first_btn:
            first_btn.setChecked(True)
        self._set_filter_panel(0)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_all_notes(self):
        query = f'note:"{self.note_type_name}"'
        try:
            nids = list(mw.col.find_notes(query))
        except Exception:
            nids = []
        self._all_note_ids = list(nids)

        from .history_store import grouped_history

        deck_set = set()
        tag_set = set()

        for nid in nids:
            note = mw.col.get_note(nid)
            parsed = _parse_note(note, self.note_type_name)
            if not parsed:
                continue
            cards = note.cards()
            deck_name = ""
            flag = 0
            if cards:
                try:
                    deck_name = mw.col.decks.name(cards[0].did)
                except Exception:
                    pass
                flag = cards[0].flags & 0x07
            tags = []
            for t in note.tags:
                tags.append(t)
                tag_set.add(t)
            deck_set.add(deck_name)
            preview_text = parsed["question"]
            preview = preview_text[:140] + ("…" if len(preview_text) > 140 else "")
            self._note_meta[nid] = {
                "deck":        deck_name,
                "tags":        tags,
                "flag":        flag,
                "preview":     preview,
                "search_text": preview_text.lower(),
            }

        self._history_index = {
            entry["label"]: set(entry["note_ids"])
            for entry in grouped_history()
        }

        self._populate_deck_tree(deck_set)
        self._populate_tag_list(tag_set)
        self._populate_exam_tag_list(self._history_index.keys())
        self._apply_filters()

    def _populate_deck_tree(self, deck_names):
        self.deck_tree.blockSignals(True)
        self.deck_tree.clear()
        all_item = QTreeWidgetItem(["All decks"])
        all_item.setData(0, Qt.ItemDataRole.UserRole, None)
        self.deck_tree.addTopLevelItem(all_item)
        nodes = {}
        for full_name in sorted(deck_names):
            if not full_name:
                continue
            parts = full_name.split("::")
            for depth in range(len(parts)):
                path = "::".join(parts[:depth + 1])
                if path in nodes:
                    continue
                item = QTreeWidgetItem([parts[depth]])
                item.setData(0, Qt.ItemDataRole.UserRole, path)
                if depth == 0:
                    self.deck_tree.addTopLevelItem(item)
                else:
                    parent_path = "::".join(parts[:depth])
                    nodes[parent_path].addChild(item)
                nodes[path] = item
        self.deck_tree.expandAll()
        self.deck_tree.resizeColumnToContents(0)
        self.deck_tree.setCurrentItem(all_item)
        self.deck_tree.blockSignals(False)

    def _populate_tag_list(self, tags):
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for tag in sorted(tags):
            if not tag:
                continue
            item = QListWidgetItem(tag)
            item.setData(Qt.ItemDataRole.UserRole, tag)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.tag_list.addItem(item)
        self.tag_list.blockSignals(False)

    def _populate_exam_tag_list(self, history_labels):
        previous = set(self._active_exam_tags)
        self.exam_tag_list.blockSignals(True)
        self.exam_tag_list.clear()
        for label in history_labels:
            if not label:
                continue
            item = QListWidgetItem(label)
            item.setToolTip(label)
            item.setData(Qt.ItemDataRole.UserRole, label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if label in previous else Qt.CheckState.Unchecked
            )
            self.exam_tag_list.addItem(item)
        self.exam_tag_list.blockSignals(False)
        self.delete_history_btn.setEnabled(self.exam_tag_list.count() > 0)
        self.clear_history_btn.setEnabled(self.exam_tag_list.count() > 0)

    # ── Filter handlers ───────────────────────────────────────────────────────

    def _on_deck_changed(self):
        sel = self.deck_tree.selectedItems()
        self._active_deck = sel[0].data(0, Qt.ItemDataRole.UserRole) if sel else None
        self._apply_filters()

    def _on_tag_changed(self):
        self._active_tags = set()
        for i in range(self.tag_list.count()):
            item = self.tag_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self._active_tags.add(item.data(Qt.ItemDataRole.UserRole) or item.text())
        self._apply_filters()

    def _on_exam_tag_changed(self):
        self._active_exam_tags = set()
        for i in range(self.exam_tag_list.count()):
            item = self.exam_tag_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                self._active_exam_tags.add(item.data(Qt.ItemDataRole.UserRole) or item.text())
        self._apply_filters()

    def _reload_history_index(self):
        from .history_store import grouped_history

        self._history_index = {
            entry["label"]: set(entry["note_ids"])
            for entry in grouped_history()
        }
        self._active_exam_tags &= set(self._history_index.keys())
        self._populate_exam_tag_list(self._history_index.keys())

    def _checked_history_labels(self):
        labels = []
        for i in range(self.exam_tag_list.count()):
            item = self.exam_tag_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                labels.append(item.data(Qt.ItemDataRole.UserRole) or item.text())
        return labels

    def _delete_selected_history(self):
        from .history_store import delete_history_labels

        labels = self._checked_history_labels()
        if not labels:
            QMessageBox.information(self, "No History Selected",
                                    "Select at least one simulation history item to delete.")
            return
        count = len(labels)
        answer = QMessageBox.question(
            self,
            "Delete Simulation History",
            f"Delete {count} selected simulation histor{'y' if count == 1 else 'ies'}?\n\nThis only removes local addon history. It does not delete notes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_history_labels(labels)
        self._reload_history_index()
        self._apply_filters()

    def _clear_all_history(self):
        from .history_store import clear_history

        if not self._history_index:
            return
        answer = QMessageBox.question(
            self,
            "Clear All Simulation History",
            "Delete all local simulation history?\n\nThis only removes addon history. It does not delete notes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        clear_history()
        self._active_exam_tags.clear()
        self._reload_history_index()
        self._apply_filters()

    def _set_filter_panel(self, index):
        self._filter_stack.setCurrentIndex(index)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonRelease:
            if obj is self.result_list.viewport():
                item = self.result_list.itemAt(event.pos())
                if item is not None:
                    rect = self.result_list.visualItemRect(item)
                    indicator_zone = rect.left() + 28
                    if event.pos().x() > indicator_zone:
                        self.result_list.blockSignals(True)
                        new_state = (Qt.CheckState.Unchecked
                                     if item.checkState() == Qt.CheckState.Checked
                                     else Qt.CheckState.Checked)
                        item.setCheckState(new_state)
                        self.result_list.blockSignals(False)
                        self._on_result_item_changed(item)
                        self.result_list.setCurrentItem(item)
                        return True
            elif obj in (self.tag_list.viewport(), self.exam_tag_list.viewport()):
                list_widget = self.tag_list if obj is self.tag_list.viewport() else self.exam_tag_list
                item = list_widget.itemAt(event.pos())
                if item is not None:
                    rect = list_widget.visualItemRect(item)
                    indicator_zone = rect.left() + 28
                    if event.pos().x() > indicator_zone:
                        self._toggle_checkable_item(list_widget, item)
                        return True
        return super().eventFilter(obj, event)

    def _toggle_checkable_item(self, list_widget, item):
        list_widget.blockSignals(True)
        new_state = (Qt.CheckState.Unchecked
                     if item.checkState() == Qt.CheckState.Checked
                     else Qt.CheckState.Checked)
        item.setCheckState(new_state)
        list_widget.blockSignals(False)
        if list_widget is self.tag_list:
            self._on_tag_changed()
        elif list_widget is self.exam_tag_list:
            self._on_exam_tag_changed()

    def _clear_active_filter_chips(self):
        while self._active_filters_layout.count():
            item = self._active_filters_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _add_filter_chip(self, text):
        chip = QLabel(text)
        chip.setFrameShape(QFrame.Shape.Panel)
        chip.setFrameShadow(QFrame.Shadow.Raised)
        chip.setMargin(4)
        self._active_filters_layout.addWidget(chip)

    def _update_active_filter_chips(self):
        self._clear_active_filter_chips()
        added = False
        if self._active_deck:
            self._add_filter_chip(f"Deck: {self._active_deck}")
            added = True
        for tag in sorted(self._active_tags):
            self._add_filter_chip(f"Tag: {tag}")
            added = True
        for tag in sorted(self._active_exam_tags):
            display = tag.split("::", 1)[1] if "::" in tag else tag
            self._add_filter_chip(f"Simulation: {display}")
            added = True
        for fnum in sorted(self._active_flags):
            self._add_filter_chip(f"Flag: {FLAG_DEFS[fnum - 1][1]}")
            added = True
        search = self.search_box.text().strip()
        if search:
            self._add_filter_chip(f"Search: {search}")
            added = True
        if not added:
            empty = QLabel("No filters applied")
            self._active_filters_layout.addWidget(empty)
        self._active_filters_layout.addStretch()

    def _on_flag_changed(self):
        self._active_flags = {
            fnum for fnum, cb in self._flag_checks.items() if cb.isChecked()
        }
        self._apply_filters()

    def _note_matches(self, nid):
        meta   = self._note_meta[nid]
        search = self.search_box.text().lower()
        if self._active_deck:
            dn = meta["deck"]
            if dn != self._active_deck and not dn.startswith(
                    self._active_deck + "::"):
                return False
        if self._active_tags:
            if not (self._active_tags & set(meta["tags"])):
                return False
        if self._active_exam_tags:
            if not any(nid in self._history_index.get(history_name, set())
                       for history_name in self._active_exam_tags):
                return False
        if self._active_flags:
            if meta["flag"] not in self._active_flags:
                return False
        if search and search not in meta.get("search_text", meta["preview"].lower()):
            return False
        return True

    def _apply_filters(self):
        self._update_active_filter_chips()
        visible = [
            (nid, self._note_meta[nid])
            for nid in self._note_meta
            if self._note_matches(nid)
        ]
        visible.sort(key=lambda x: x[1]["preview"])
        self._rebuild_list(visible)

    def _result_item_label(self, nid, meta):
        flag_str = f"[{FLAG_DEFS[meta['flag']-1][1]}] " if meta["flag"] > 0 else ""
        tag_str = ""
        if meta["tags"]:
            tag_str = "  🏷 " + ", ".join(meta["tags"][:3])
            if len(meta["tags"]) > 3:
                tag_str += "…"
        return f"{flag_str}{meta['preview']}   〔{meta['deck']}〕{tag_str}"

    def _sync_result_item(self, item):
        nid = item.data(Qt.ItemDataRole.UserRole)
        meta = self._note_meta.get(nid)
        if meta is None:
            return
        item.setText(self._result_item_label(nid, meta))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(
            Qt.CheckState.Checked if nid in self._selected else Qt.CheckState.Unchecked
        )

    def _rebuild_list(self, items):
        self.result_list.blockSignals(True)
        self.result_list.clear()
        for nid, meta in items:
            item = QListWidgetItem(self._result_item_label(nid, meta))
            item.setData(Qt.ItemDataRole.UserRole, nid)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if nid in self._selected else Qt.CheckState.Unchecked
            )
            self.result_list.addItem(item)
        self.result_list.blockSignals(False)
        self.visible_lbl.setText(f"{len(items)} shown")
        self._refresh_count()

    # ── Selection ─────────────────────────────────────────────────────────────

    def _on_result_item_changed(self, item):
        nid = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected.add(nid)
        else:
            self._selected.discard(nid)
        self._refresh_count()

    def _select_all_visible(self):
        self.result_list.blockSignals(True)
        for i in range(self.result_list.count()):
            item = self.result_list.item(i)
            item.setCheckState(Qt.CheckState.Checked)
            self._selected.add(item.data(Qt.ItemDataRole.UserRole))
        self.result_list.blockSignals(False)
        self._refresh_count()

    def _deselect_visible(self):
        """Only deselects currently visible rows — hidden selections preserved."""
        self.result_list.blockSignals(True)
        for i in range(self.result_list.count()):
            item = self.result_list.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._selected.discard(item.data(Qt.ItemDataRole.UserRole))
        self.result_list.blockSignals(False)
        self._refresh_count()

    def _refresh_count(self):
        self.count_lbl.setText(f"Selected: {len(self._selected)}")

    def _toggle_preview(self, checked):
        self._preview_pane.setVisible(checked)
        if checked:
            self._list_preview_splitter.setSizes([420, 320])
            current = self.result_list.currentItem()
            if current:
                self._on_preview_item(current, None)
        else:
            self._list_preview_splitter.setSizes([700, 0])
            self._clear_preview()

    def _clear_preview(self):
        layout = self._preview_layout
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_preview_item(self, current, previous):
        if not self._preview_pane.isVisible() or current is None:
            return
        nid = current.data(Qt.ItemDataRole.UserRole)
        if nid is None:
            return
        meta = self._note_meta.get(nid)
        if not meta:
            return

        try:
            note = mw.col.get_note(nid)
            q = _parse_note(note, self.note_type_name)
        except Exception:
            q = None

        self._clear_preview()
        layout = self._preview_layout

        def lbl(text, bold=False, size=13, italic=False, color=None):
            w = QLabel(text)
            w.setWordWrap(True)
            style = f"font-size:{size}px;"
            if bold:
                style += "font-weight:bold;"
            if italic:
                style += "font-style:italic;"
            if color:
                style += f"color:{color};"
            w.setStyleSheet(style)
            w.setTextFormat(Qt.TextFormat.PlainText)
            return w

        layout.insertWidget(layout.count() - 1, lbl(meta["deck"], size=11, italic=True))

        if meta["flag"] > 0:
            finfo = FLAG_DEFS[meta["flag"] - 1]
            layout.insertWidget(
                layout.count() - 1,
                lbl(f"⚑  {finfo[1]}", color=finfo[2], size=12, bold=True)
            )

        if meta["tags"]:
            layout.insertWidget(
                layout.count() - 1, lbl("  ·  ".join(meta["tags"]), size=11)
            )

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.insertWidget(layout.count() - 1, sep)

        if q:
            layout.insertWidget(
                layout.count() - 1, lbl(q["question"], bold=True, size=14)
            )
            if q.get("answer_mode") == "short":
                layout.insertWidget(
                    layout.count() - 1,
                    lbl("Short answer question", size=12, italic=True, color="#64748b")
                )
            else:
                for letter, text in q["options"].items():
                    row = QWidget()
                    rh = QHBoxLayout(row)
                    rh.setContentsMargins(4, 0, 0, 0)
                    rh.setSpacing(8)
                    ll = QLabel(f"{letter}.")
                    ll.setStyleSheet("font-weight:bold;font-size:13px;")
                    ll.setFixedWidth(22)
                    lt = QLabel(text)
                    lt.setWordWrap(True)
                    lt.setStyleSheet("font-size:13px;")
                    lt.setTextFormat(Qt.TextFormat.PlainText)
                    rh.addWidget(ll)
                    rh.addWidget(lt, 1)
                    layout.insertWidget(layout.count() - 1, row)
            if q.get("source"):
                src_w = QLabel(f"📚  {q['source']}")
                src_w.setWordWrap(True)
                src_w.setStyleSheet("font-size:11px;font-style:italic;")
                src_w.setTextFormat(Qt.TextFormat.PlainText)
                layout.insertWidget(layout.count() - 1, src_w)
        else:
            layout.insertWidget(
                layout.count() - 1, lbl("Could not parse this card.", size=12)
            )

    def _confirm(self):
        if not self._selected:
            QMessageBox.warning(self, "Nothing Selected",
                                "Please select at least one question.")
            return
        self.accept()

    def selected_note_ids(self):
        return [nid for nid in self._all_note_ids if nid in self._selected]

    def note_meta(self):
        return self._note_meta


# ── Launcher Dialog ───────────────────────────────────────────────────────────

class LauncherDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Exam Simulator — Setup")
        self.setMinimumSize(480, 360)
        self._picked_ids  = []
        self._picked_meta = {}   # nid -> meta (for smart sampling)
        self._note_type_names = []
        self._picked_tags = []
        self._composition_presets = []
        self._build_ui()
        self._fit_to_screen()

    def _populate_note_types(self):
        self._note_type_names = []
        try:
            models = mw.col.models.all()
            self._note_type_names = sorted(
                m.get("name", "") for m in models if m.get("name")
            )
        except Exception:
            self._note_type_names = [DEFAULT_NOTE_TYPE]

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)
        scroll.setWidget(content)
        root_layout.addWidget(scroll, 1)

        self._populate_note_types()

        # ── Note type ───────────────────────────────────────────────────────
        nt_group = QGroupBox("Note Type")
        nt_layout = QVBoxLayout(nt_group)
        nt_top = QHBoxLayout()
        nt_hint = QLabel("Choose an MCQ note type")
        self.note_type_combo = QComboBox()
        self.note_type_combo.addItems(self._note_type_names)
        default_idx = self.note_type_combo.findText(DEFAULT_NOTE_TYPE)
        if default_idx >= 0:
            self.note_type_combo.setCurrentIndex(default_idx)
        self.note_type_combo.setToolTip(
            "Select one of your existing Anki note types.")
        nt_top.addWidget(nt_hint)
        nt_top.addWidget(self.note_type_combo, 1)
        nt_layout.addLayout(nt_top)
        layout.addWidget(nt_group)

        # ── Exam name ───────────────────────────────────────────────────────
        name_group = QGroupBox("Exam Name")
        name_layout = QVBoxLayout(name_group)
        name_label = QLabel("Simulation name")
        name_help = QLabel("Saved in Simulation History")
        name_help.setWordWrap(True)
        name_help.setStyleSheet("color:#64748b;font-size:12px;")
        self.exam_name_edit = QLineEdit()
        self.exam_name_edit.setPlaceholderText("e.g.  Gastro_2024_Exam1")
        name_layout.addWidget(name_label)
        name_layout.addWidget(name_help)
        name_layout.addWidget(self.exam_name_edit)
        layout.addWidget(name_group)

        # ── Question selection ──────────────────────────────────────────────
        q_group = QGroupBox("Questions")
        q_layout = QVBoxLayout(q_group)

        pick_row = QHBoxLayout()
        self.pick_label = QLabel("No questions selected yet.")
        self.pick_label.setStyleSheet("color:#64748b;font-style:italic;")
        pick_btn = QPushButton("📋  Browse && Pick Questions…")
        pick_btn.clicked.connect(self._open_picker)
        pick_row.addWidget(self.pick_label, 1)
        pick_row.addWidget(pick_btn)
        q_layout.addLayout(pick_row)

        limit_row = QHBoxLayout()
        self.limit_check = QCheckBox("Limit to")
        self.limit_spin  = QSpinBox()
        self.limit_spin.setRange(1, 999)
        self.limit_spin.setValue(20)
        self.limit_spin.setEnabled(False)
        limit_row.addWidget(self.limit_check)
        limit_row.addWidget(self.limit_spin)
        limit_row.addWidget(
            QLabel("questions  (balanced across sub-decks/lessons)"))
        limit_row.addStretch()
        self.limit_check.toggled.connect(self.limit_spin.setEnabled)
        q_layout.addLayout(limit_row)

        comp_group = QGroupBox("Tag Composition")
        comp_layout = QVBoxLayout(comp_group)
        self.composition_check = QCheckBox("Build exam by tag quotas")
        self.composition_check.toggled.connect(self._toggle_composition)
        comp_layout.addWidget(self.composition_check)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.load_preset_btn = QPushButton("Load")
        self.save_preset_btn = QPushButton("Save current")
        self.delete_preset_btn = QPushButton("Delete")
        self.load_preset_btn.clicked.connect(self._load_selected_preset)
        self.save_preset_btn.clicked.connect(self._save_current_preset)
        self.delete_preset_btn.clicked.connect(self._delete_selected_preset)
        preset_row.addWidget(self.preset_combo, 1)
        preset_row.addWidget(self.load_preset_btn)
        preset_row.addWidget(self.save_preset_btn)
        preset_row.addWidget(self.delete_preset_btn)
        comp_layout.addLayout(preset_row)

        comp_help = QLabel(
            "Each row selects questions with that tag. Row order becomes exam order."
        )
        comp_help.setWordWrap(True)
        comp_help.setStyleSheet("color:#64748b;font-size:12px;")
        comp_layout.addWidget(comp_help)

        self.composition_table = QTableWidget(0, 2)
        self.composition_table.setHorizontalHeaderLabels(["Tag", "Count"])
        self.composition_table.horizontalHeader().setStretchLastSection(True)
        self.composition_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.composition_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.composition_table.setEnabled(False)
        self.composition_table.setMinimumHeight(120)
        self.composition_table.setMaximumHeight(180)
        comp_layout.addWidget(self.composition_table)

        comp_btns = QHBoxLayout()
        self.add_rule_btn = QPushButton("Add row")
        self.remove_rule_btn = QPushButton("Remove row")
        self.move_rule_up_btn = QPushButton("Move up")
        self.move_rule_down_btn = QPushButton("Move down")
        for btn in (
            self.add_rule_btn, self.remove_rule_btn,
            self.move_rule_up_btn, self.move_rule_down_btn,
        ):
            btn.setEnabled(False)
            comp_btns.addWidget(btn)
        comp_btns.addStretch()
        self.add_rule_btn.clicked.connect(self._add_composition_row)
        self.remove_rule_btn.clicked.connect(self._remove_composition_row)
        self.move_rule_up_btn.clicked.connect(lambda: self._move_composition_row(-1))
        self.move_rule_down_btn.clicked.connect(lambda: self._move_composition_row(1))
        comp_layout.addLayout(comp_btns)
        q_layout.addWidget(comp_group)
        layout.addWidget(q_group)

        # ── Timer ───────────────────────────────────────────────────────────
        timer_group = QGroupBox("Timer")
        timer_layout = QHBoxLayout(timer_group)
        self.timer_check = QCheckBox("Enable timer")
        self.timer_spin  = QSpinBox()
        self.timer_spin.setRange(1, 300)
        self.timer_spin.setValue(60)
        self.timer_spin.setEnabled(False)
        self.timer_check.toggled.connect(self.timer_spin.setEnabled)
        timer_layout.addWidget(self.timer_check)
        timer_layout.addWidget(self.timer_spin)
        timer_layout.addWidget(QLabel("minutes"))
        timer_layout.addStretch()
        layout.addWidget(timer_group)

        # ── Scoring ─────────────────────────────────────────────────────────
        score_group = QGroupBox("Scoring System")
        score_layout = QFormLayout(score_group)
        score_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)

        self.scoring_combo = QComboBox()
        self.scoring_combo.addItems([
            "All or Nothing",
            "Partial Positive +",
            "Partial Negative -",
        ])
        score_layout.addRow("Method:", self.scoring_combo)
        layout.addWidget(score_group)

        # ── Shuffle ─────────────────────────────────────────────────────────
        self.shuffle_check = QCheckBox(
            "Shuffle question and option order (questions stay within tag groups when using tag composition)")
        self.shuffle_check.setChecked(True)
        layout.addWidget(self.shuffle_check)

        # ── Buttons ─────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        self.start_btn = QPushButton("▶  Start Exam")
        self.start_btn.setDefault(True)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self._start)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(self.start_btn)
        root_layout.addLayout(btn_layout)

        self._reload_composition_presets()

    # ─────────────────────────────────────────────────────────────────────────

    def _fit_to_screen(self):
        try:
            screen = self.screen()
            available = screen.availableGeometry() if screen else None
            if not available:
                return
            max_height = max(self.minimumHeight(), available.height() - 80)
            self.setMaximumHeight(max_height)
            self.resize(560, min(720, max_height))
        except Exception:
            pass

    def _open_picker(self):
        nt = self.note_type_combo.currentText().strip() or DEFAULT_NOTE_TYPE
        dlg = CardPickerDialog(self, nt)
        if dlg.exec():
            self._picked_ids  = dlg.selected_note_ids()
            self._picked_meta = dlg.note_meta()
            self._picked_tags = self._available_picked_tags()
            n = len(self._picked_ids)
            self.pick_label.setText(
                f"{n} question{'s' if n != 1 else ''} selected.")
            self.pick_label.setStyleSheet(
                "color:#16a34a;font-weight:bold;")
            self.limit_spin.setMaximum(n)
            self._refresh_composition_tag_options()
            self.start_btn.setEnabled(True)

    def _available_picked_tags(self):
        tags = set()
        for nid in self._picked_ids:
            tags.update(self._picked_meta.get(nid, {}).get("tags", []))
        return sorted(tag for tag in tags if tag)

    def _toggle_composition(self, checked):
        self.composition_table.setEnabled(checked)
        for btn in (
            self.add_rule_btn, self.remove_rule_btn,
            self.move_rule_up_btn, self.move_rule_down_btn,
        ):
            btn.setEnabled(checked)
        self.limit_check.setEnabled(not checked)
        self.limit_spin.setEnabled((not checked) and self.limit_check.isChecked())
        if checked and self.composition_table.rowCount() == 0:
            self._add_composition_row()

    def _make_tag_combo(self, current_text=""):
        combo = QComboBox()
        combo.addItems(self._picked_tags)
        if current_text:
            idx = combo.findText(current_text)
            if idx < 0:
                combo.addItem(current_text)
                idx = combo.findText(current_text)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        return combo

    def _make_count_spin(self, value=1):
        spin = QSpinBox()
        spin.setRange(1, max(1, len(self._picked_ids)))
        spin.setValue(max(1, int(value)))
        return spin

    def _add_composition_row(self):
        row = self.composition_table.rowCount()
        self.composition_table.insertRow(row)
        self.composition_table.setCellWidget(row, 0, self._make_tag_combo())
        self.composition_table.setCellWidget(row, 1, self._make_count_spin())
        self.composition_table.selectRow(row)

    def _remove_composition_row(self):
        row = self.composition_table.currentRow()
        if row >= 0:
            self.composition_table.removeRow(row)

    def _move_composition_row(self, direction):
        row = self.composition_table.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.composition_table.rowCount():
            return
        rules = self._composition_rules(allow_empty=True)
        rules[row], rules[target] = rules[target], rules[row]
        self._set_composition_rules(rules)
        self.composition_table.selectRow(target)

    def _set_composition_rules(self, rules):
        self.composition_table.setRowCount(0)
        for tag, count in rules:
            row = self.composition_table.rowCount()
            self.composition_table.insertRow(row)
            self.composition_table.setCellWidget(row, 0, self._make_tag_combo(tag))
            self.composition_table.setCellWidget(row, 1, self._make_count_spin(count))

    def _composition_rules(self, allow_empty=False):
        rules = []
        for row in range(self.composition_table.rowCount()):
            tag_widget = self.composition_table.cellWidget(row, 0)
            count_widget = self.composition_table.cellWidget(row, 1)
            tag = tag_widget.currentText().strip() if tag_widget else ""
            count = count_widget.value() if count_widget else 0
            if tag or allow_empty:
                rules.append((tag, count))
        return rules

    def _refresh_composition_tag_options(self):
        rules = self._composition_rules(allow_empty=True)
        self._set_composition_rules(rules)

    def _reload_composition_presets(self):
        from .preset_store import load_presets

        self._composition_presets = load_presets()
        current = self.preset_combo.currentText().strip()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for preset in self._composition_presets:
            self.preset_combo.addItem(preset["name"])
        if current:
            idx = self.preset_combo.findText(current)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)
        has_presets = bool(self._composition_presets)
        self.load_preset_btn.setEnabled(has_presets)
        self.delete_preset_btn.setEnabled(has_presets)

    def _selected_preset(self):
        name = self.preset_combo.currentText().strip()
        if not name:
            return None
        for preset in self._composition_presets:
            if preset["name"] == name:
                return preset
        return None

    def _load_selected_preset(self):
        preset = self._selected_preset()
        if not preset:
            return
        rules = [
            (rule["tag"], rule["count"])
            for rule in preset.get("rules", [])
        ]
        self.composition_check.setChecked(True)
        self._set_composition_rules(rules)

    def _save_current_preset(self):
        from .preset_store import upsert_preset

        rules = self._composition_rules()
        if not rules:
            QMessageBox.warning(
                self, "No Tag Composition",
                "Add at least one tag quota row before saving a preset.")
            return
        name, ok = QInputDialog.getText(
            self,
            "Save Tag Composition Preset",
            "Preset name:",
            QLineEdit.EchoMode.Normal,
            self.preset_combo.currentText().strip(),
        )
        name = name.strip()
        if not ok or not name:
            return
        upsert_preset(name, rules)
        self._reload_composition_presets()
        idx = self.preset_combo.findText(name)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

    def _delete_selected_preset(self):
        from .preset_store import delete_preset

        preset = self._selected_preset()
        if not preset:
            return
        answer = QMessageBox.question(
            self,
            "Delete Tag Composition Preset",
            f"Delete preset '{preset['name']}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        delete_preset(preset["name"])
        self._reload_composition_presets()

    def _start(self):
        self.start_btn.setEnabled(False)
        self.start_btn.setText("Loading…")

        note_type = self.note_type_combo.currentText().strip() or DEFAULT_NOTE_TYPE
        note_ids  = list(self._picked_ids)

        if self.composition_check.isChecked():
            rules = self._composition_rules()
            if not rules:
                QMessageBox.warning(
                    self, "No Tag Composition",
                    "Add at least one tag quota row before starting.")
                self.start_btn.setEnabled(True)
                self.start_btn.setText("▶  Start Exam")
                return
            if any(not tag for tag, _count in rules):
                QMessageBox.warning(
                    self, "Incomplete Tag Composition",
                    "Each tag quota row must choose a tag.")
                self.start_btn.setEnabled(True)
                self.start_btn.setText("▶  Start Exam")
                return
            note_ids, shortages = _tagged_sample(
                note_ids, self._picked_meta, rules,
                shuffle_groups=self.shuffle_check.isChecked(),
            )
            if shortages:
                lines = [
                    f"{tag}: requested {wanted}, available {got}"
                    for tag, wanted, got in shortages
                ]
                QMessageBox.warning(
                    self, "Not Enough Questions",
                    "Some tag quotas could not be filled from the selected questions:\n\n"
                    + "\n".join(lines))
                self.start_btn.setEnabled(True)
                self.start_btn.setText("▶  Start Exam")
                return

        # ── Smart sampling across sub-decks ──────────────────────────────
        elif self.limit_check.isChecked():
            limit = self.limit_spin.value()
            pairs = [
                (nid, self._picked_meta.get(nid, {"deck": ""}))
                for nid in note_ids
            ]
            note_ids = _smart_sample(pairs, limit)

        # Shuffle only changes final exam order, never membership logic.
        if self.shuffle_check.isChecked() and not self.composition_check.isChecked():
            random.shuffle(note_ids)

        questions = []
        for nid in note_ids:
            note = mw.col.get_note(nid)
            q = _parse_note(note, note_type)
            if q:
                if self.shuffle_check.isChecked():
                    _shuffle_question_options(q)
                q["nid"] = nid
                questions.append(q)

        if not questions:
            QMessageBox.warning(
                self, "No Valid Questions",
                "Could not parse any valid questions.\n"
                "Check that the 'Ans' field is filled in those cards.")
            self.start_btn.setEnabled(True)
            self.start_btn.setText("▶  Start Exam")
            return

        scoring_modes = ["raw", "partial", "negative"]
        scoring = {
            "mode": scoring_modes[self.scoring_combo.currentIndex()],
        }
        timer_seconds = (self.timer_spin.value() * 60
                         if self.timer_check.isChecked() else 0)
        raw_exam_name = self.exam_name_edit.text().strip()
        exam_name = (raw_exam_name.replace(" ", "_") or "Unnamed_Exam")
        save_history = bool(raw_exam_name)

        if not save_history:
            answer = QMessageBox.question(
                self,
                "Start Without a Name?",
                "This exam will not be saved in Simulation History unless you give it a name.\n\nStart anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.start_btn.setEnabled(True)
                self.start_btn.setText("▶  Start Exam")
                return

        self.accept()

        from .exam_window import ExamWindow
        win = ExamWindow(mw, questions, timer_seconds, scoring, exam_name, save_history=save_history)
        win.showMaximized()
