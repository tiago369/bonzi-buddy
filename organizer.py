"""
Sprite Organizer - Animated Buddy (v3)
=========================================
Each animation is now a list of STEPS, and each step can be one of two
types (this solves the "some sprites only move the mouth, others should
stay in the background" mix):

1) "Alone": a single frame shown in isolation at that instant (e.g. the
   still body, a head pose, a transition frame).

2) "Combined": a BASE frame (the body/background) drawn together with the
   NEXT chosen frame (typically a mouth), overlaid at an offset (X/Y) that
   you adjust while watching the live preview. This simulates talking: the
   body stays still in the background and only the mouth changes.

Since steps are independent, you can freely mix them within the same
animation: some moments with the body alone (pauses in speech) and others
with body + mouth combined (syllables), all in a single sequence.

WORKFLOW
--------
1. "Choose image folder".
2. For a simple step: select the frame in the left-hand list and click
   "Add ALONE".
3. For a combined step:
   a. Select the body/background frame and click "Mark as BASE".
   b. Select the mouth (or other overlay) frame in the left-hand list.
   c. Adjust "Offset X/Y" while watching the live preview.
   d. Click "Add COMBINED (base + selected)".
4. Repeat steps 2/3 in the order the animation should play.
5. Click "Play preview" to see the whole sequence running.
6. Fill in name, description, loop and FPS, then click "Save animation".
7. At the end, "Export JSON" generates animations.json.
"""
import sys
import os
import json
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QLineEdit,
    QTextEdit, QSpinBox, QCheckBox, QFileDialog, QMessageBox, QGroupBox
)

VALID_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")

# Same color/tolerance used in the final app - adjust if your background isn't cyan
BACKGROUND_COLOR = QColor(0, 255, 255)


def load_pixmap_without_background(path, background_color=BACKGROUND_COLOR):
    """Fast version (binary mask) just for the preview inside the organizer.
    The final app (animation.py) uses a color-tolerance version, better for
    quality; here we prioritize speed for a smooth preview."""
    pm = QPixmap(path)
    if pm.isNull():
        return None
    mask = pm.createMaskFromColor(background_color, Qt.MaskInColor)
    pm.setMask(mask)
    return pm


def step_text(step):
    if step["mode"] == "alone":
        return f"[alone] {step['file']}"
    return f"[combined] {step['file']} + {step['extra_file']} (offset {step['offset_x']},{step['offset_y']})"


class SpriteOrganizer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sprite Organizer - Animated Buddy")
        self.resize(1200, 720)

        self.images_folder = ""
        self.animations = {}  # name -> {"description", "loop", "fps", "steps": [...]}
        self.pixmap_cache = {}  # file_name -> QPixmap with background already removed

        self.current_base = None  # name of the file marked as base for the next "combined"

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._advance_preview)
        self.preview_index = 0

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ---------------- Left column: frame bank ----------------
        left_col = QVBoxLayout()
        self.btn_choose_folder = QPushButton("Choose image folder")
        self.btn_choose_folder.clicked.connect(self.choose_folder)
        left_col.addWidget(self.btn_choose_folder)

        self.label_folder = QLabel("No folder selected")
        self.label_folder.setWordWrap(True)
        left_col.addWidget(self.label_folder)

        left_col.addWidget(QLabel("All frames found (select one, then use the buttons on the right):"))
        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListWidget.IconMode)
        self.frame_list.setIconSize(QSize(80, 80))
        self.frame_list.setResizeMode(QListWidget.Adjust)
        self.frame_list.currentItemChanged.connect(self.update_assembly_preview)
        left_col.addWidget(self.frame_list)

        main_layout.addLayout(left_col, 3)

        # ---------------- Center column: step assembly ----------------
        center_col = QVBoxLayout()

        step_group = QGroupBox("Assemble next step")
        step_layout = QVBoxLayout(step_group)

        self.btn_add_alone = QPushButton("Add ALONE (frame selected on the left)")
        self.btn_add_alone.clicked.connect(self.add_alone_step)
        step_layout.addWidget(self.btn_add_alone)

        base_row = QHBoxLayout()
        self.btn_mark_base = QPushButton("Mark selected as BASE")
        self.btn_mark_base.clicked.connect(self.mark_base)
        base_row.addWidget(self.btn_mark_base)
        self.label_current_base = QLabel("Base: (none)")
        base_row.addWidget(self.label_current_base)
        step_layout.addLayout(base_row)

        offset_row = QHBoxLayout()
        offset_row.addWidget(QLabel("Offset X:"))
        self.spin_offset_x = QSpinBox()
        self.spin_offset_x.setRange(-2000, 2000)
        self.spin_offset_x.valueChanged.connect(self.update_assembly_preview)
        offset_row.addWidget(self.spin_offset_x)
        offset_row.addWidget(QLabel("Y:"))
        self.spin_offset_y = QSpinBox()
        self.spin_offset_y.setRange(-2000, 2000)
        self.spin_offset_y.valueChanged.connect(self.update_assembly_preview)
        offset_row.addWidget(self.spin_offset_y)
        step_layout.addLayout(offset_row)

        self.btn_add_combined = QPushButton("Add COMBINED (base + selected on the left)")
        self.btn_add_combined.clicked.connect(self.add_combined_step)
        step_layout.addWidget(self.btn_add_combined)

        center_col.addWidget(step_group)

        center_col.addWidget(QLabel("Step sequence (playback order; double-click to remove):"))
        self.sequence_list = QListWidget()
        self.sequence_list.itemDoubleClicked.connect(self.remove_step)
        self.sequence_list.currentItemChanged.connect(self.update_selected_step_preview)
        center_col.addWidget(self.sequence_list)

        self.btn_clear_sequence = QPushButton("Clear sequence")
        self.btn_clear_sequence.clicked.connect(self.clear_sequence)
        center_col.addWidget(self.btn_clear_sequence)

        config_group = QGroupBox("Animation data")
        form = QVBoxLayout(config_group)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("e.g.: idle, talking, greeting...")
        name_row.addWidget(self.input_name)
        form.addLayout(name_row)

        form.addWidget(QLabel("Description (what this action represents):"))
        self.input_description = QTextEdit()
        self.input_description.setPlaceholderText(
            "e.g.: Buddy standing still, breathing lightly, used when the AI is idle."
        )
        self.input_description.setFixedHeight(60)
        form.addWidget(self.input_description)

        options_row = QHBoxLayout()
        self.check_loop = QCheckBox("Repeat in a loop")
        self.check_loop.setChecked(True)
        options_row.addWidget(self.check_loop)
        options_row.addWidget(QLabel("FPS:"))
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(1, 60)
        self.spin_fps.setValue(8)
        self.spin_fps.valueChanged.connect(self._restart_preview_timer_if_active)
        options_row.addWidget(self.spin_fps)
        form.addLayout(options_row)
        center_col.addWidget(config_group)

        self.btn_save_animation = QPushButton("Save animation")
        self.btn_save_animation.clicked.connect(self.save_animation)
        center_col.addWidget(self.btn_save_animation)

        main_layout.addLayout(center_col, 3)

        # ---------------- Right column: preview + saved animations ----------------
        right_col = QVBoxLayout()

        right_col.addWidget(QLabel("Preview:"))
        self.label_preview = QLabel()
        self.label_preview.setFixedSize(260, 260)
        self.label_preview.setStyleSheet("background-color: #444; border: 1px solid #888;")
        self.label_preview.setAlignment(Qt.AlignCenter)
        right_col.addWidget(self.label_preview)

        preview_buttons = QHBoxLayout()
        self.btn_play = QPushButton("▶ Play preview")
        self.btn_play.clicked.connect(self.play_preview)
        preview_buttons.addWidget(self.btn_play)
        self.btn_stop = QPushButton("⏸ Stop")
        self.btn_stop.clicked.connect(self.stop_preview)
        preview_buttons.addWidget(self.btn_stop)
        right_col.addLayout(preview_buttons)

        right_col.addWidget(QLabel("Saved animations:"))
        self.saved_animations_list = QListWidget()
        right_col.addWidget(self.saved_animations_list)

        self.btn_export = QPushButton("Export JSON (animations.json)")
        self.btn_export.clicked.connect(self.export_json)
        right_col.addWidget(self.btn_export)

        main_layout.addLayout(right_col, 2)

    # ------------------------------------------------------------------
    # Folder loading / cache
    # ------------------------------------------------------------------
    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Choose the folder with the frames")
        if not folder:
            return
        self.images_folder = folder
        self.label_folder.setText(folder)
        self.frame_list.clear()
        self.pixmap_cache.clear()

        files = sorted(
            f for f in os.listdir(folder)
            if f.lower().endswith(VALID_EXTENSIONS)
        )
        for file_name in files:
            path = os.path.join(folder, file_name)
            item = QListWidgetItem(QIcon(path), file_name)
            item.setData(Qt.UserRole, file_name)
            self.frame_list.addItem(item)

        if not files:
            QMessageBox.warning(self, "Warning", "No images found in that folder.")

    def get_pixmap(self, file_name):
        if file_name in self.pixmap_cache:
            return self.pixmap_cache[file_name]
        path = os.path.join(self.images_folder, file_name)
        pm = load_pixmap_without_background(path)
        self.pixmap_cache[file_name] = pm
        return pm

    # ------------------------------------------------------------------
    # Step building
    # ------------------------------------------------------------------
    def mark_base(self):
        item = self.frame_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Warning", "Select a frame in the left-hand list first.")
            return
        self.current_base = item.data(Qt.UserRole)
        self.label_current_base.setText(f"Base: {self.current_base}")
        self.update_assembly_preview()

    def add_alone_step(self):
        item = self.frame_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Warning", "Select a frame in the left-hand list first.")
            return
        step = {"mode": "alone", "file": item.data(Qt.UserRole)}
        self._add_step_to_list(step)

    def add_combined_step(self):
        item = self.frame_list.currentItem()
        if item is None:
            QMessageBox.warning(self, "Warning", "Select the mouth/overlay frame in the left-hand list.")
            return
        if not self.current_base:
            QMessageBox.warning(self, "Warning", "Mark a frame as BASE first.")
            return
        step = {
            "mode": "combined",
            "file": self.current_base,
            "extra_file": item.data(Qt.UserRole),
            "offset_x": self.spin_offset_x.value(),
            "offset_y": self.spin_offset_y.value(),
        }
        self._add_step_to_list(step)

    def _add_step_to_list(self, step):
        item = QListWidgetItem(step_text(step))
        item.setData(Qt.UserRole, step)
        pm = self.compose_step(step)
        if pm is not None:
            item.setIcon(QIcon(pm))
        self.sequence_list.addItem(item)

    def remove_step(self, item):
        self.sequence_list.takeItem(self.sequence_list.row(item))

    def clear_sequence(self):
        self.sequence_list.clear()

    def _current_steps(self):
        return [self.sequence_list.item(i).data(Qt.UserRole)
                for i in range(self.sequence_list.count())]

    # ------------------------------------------------------------------
    # Composition / preview
    # ------------------------------------------------------------------
    def compose_step(self, step):
        if step is None:
            return None
        if step["mode"] == "alone":
            return self.get_pixmap(step["file"])

        base_pm = self.get_pixmap(step["file"])
        if base_pm is None:
            return None
        result = QPixmap(base_pm.size())
        result.fill(Qt.transparent)
        painter = QPainter(result)
        painter.drawPixmap(0, 0, base_pm)
        overlay_pm = self.get_pixmap(step["extra_file"])
        if overlay_pm is not None:
            painter.drawPixmap(step["offset_x"], step["offset_y"], overlay_pm)
        painter.end()
        return result

    def update_assembly_preview(self):
        """Live preview of the step being assembled (before adding it): if a
        base is marked, shows base + the frame selected on the left at the
        current offset; otherwise shows just the selected frame."""
        if self.preview_timer.isActive():
            return
        item = self.frame_list.currentItem()
        if item is None:
            return
        selected_name = item.data(Qt.UserRole)
        if self.current_base:
            candidate_step = {
                "mode": "combined",
                "file": self.current_base,
                "extra_file": selected_name,
                "offset_x": self.spin_offset_x.value(),
                "offset_y": self.spin_offset_y.value(),
            }
        else:
            candidate_step = {"mode": "alone", "file": selected_name}
        self._show_in_preview(self.compose_step(candidate_step))

    def update_selected_step_preview(self):
        if self.preview_timer.isActive():
            return
        item = self.sequence_list.currentItem()
        if item is None:
            return
        self._show_in_preview(self.compose_step(item.data(Qt.UserRole)))

    def _show_in_preview(self, pixmap):
        if pixmap is None:
            self.label_preview.clear()
            return
        scaled = pixmap.scaled(self.label_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label_preview.setPixmap(scaled)

    # ------------------------------------------------------------------
    # Animated preview playback
    # ------------------------------------------------------------------
    def play_preview(self):
        steps = self._current_steps()
        if not steps:
            QMessageBox.warning(self, "Warning", "The sequence is empty.")
            return
        self.preview_index = 0
        self.preview_timer.start(int(1000 / self.spin_fps.value()))

    def stop_preview(self):
        self.preview_timer.stop()
        self.update_selected_step_preview()

    def _restart_preview_timer_if_active(self):
        if self.preview_timer.isActive():
            self.preview_timer.start(int(1000 / self.spin_fps.value()))

    def _advance_preview(self):
        steps = self._current_steps()
        if not steps:
            self.stop_preview()
            return
        step = steps[self.preview_index % len(steps)]
        self._show_in_preview(self.compose_step(step))
        self.preview_index += 1
        if self.preview_index >= len(steps) and not self.check_loop.isChecked():
            self.stop_preview()

    # ------------------------------------------------------------------
    # Save / export
    # ------------------------------------------------------------------
    def save_animation(self):
        name = self.input_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Warning", "Give the animation a name.")
            return
        steps = self._current_steps()
        if not steps:
            QMessageBox.warning(self, "Warning", "The sequence is empty.")
            return

        self.animations[name] = {
            "description": self.input_description.toPlainText().strip(),
            "loop": self.check_loop.isChecked(),
            "fps": self.spin_fps.value(),
            "steps": steps,
        }

        self.update_saved_animations_list()
        QMessageBox.information(self, "OK", f"Animation '{name}' saved with {len(steps)} step(s).")
        self.sequence_list.clear()
        self.input_name.clear()
        self.input_description.clear()
        self.stop_preview()

    def update_saved_animations_list(self):
        self.saved_animations_list.clear()
        for name, data in self.animations.items():
            description = data.get("description") or "(no description)"
            text = f"{name} — {description}  [{len(data['steps'])} step(s), {data['fps']} fps, loop={data['loop']}]"
            self.saved_animations_list.addItem(text)

    def export_json(self):
        if not self.animations:
            QMessageBox.warning(self, "Warning", "No animation saved yet.")
            return
        destination, _ = QFileDialog.getSaveFileName(
            self, "Save JSON", os.path.join(self.images_folder or ".", "animations.json"),
            "JSON (*.json)"
        )
        if not destination:
            return
        with open(destination, "w", encoding="utf-8") as f:
            json.dump(self.animations, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "OK", f"Exported to:\n{destination}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SpriteOrganizer()
    window.show()
    sys.exit(app.exec_())
