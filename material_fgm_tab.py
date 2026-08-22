"""Qt editor for DinosaurLayered_Layer and DinosaurLayered_Swatch_Opaque FGMs."""
import os
from PyQt5 import QtCore, QtWidgets

from material_fgm import MaterialFgm, meaning, validate_value


class MaterialFgmTab(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = None
        layout = QtWidgets.QVBoxLayout(self)
        bar = QtWidgets.QHBoxLayout()
        self.open_button = QtWidgets.QPushButton("Open layer/swatch FGM...")
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_as_button = QtWidgets.QPushButton("Save As...")
        self.save_button.setEnabled(False); self.save_as_button.setEnabled(False)
        bar.addWidget(self.open_button); bar.addWidget(self.save_button); bar.addWidget(self.save_as_button)
        bar.addStretch(1); layout.addLayout(bar)
        self.summary = QtWidgets.QLabel("Open a DinosaurLayered_Layer or DinosaurLayered_Swatch_Opaque .fgm")
        self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.attrs = QtWidgets.QTableWidget(0, 4)
        self.attrs.setHorizontalHeaderLabels(["Parameter", "Value", "Type", "Mapping"])
        self.attrs.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.attrs.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.attrs.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(QtWidgets.QLabel("Attributes")); layout.addWidget(self.attrs, 2)
        self.textures = QtWidgets.QTableWidget(0, 4)
        self.textures.setHorizontalHeaderLabels(["Texture slot", "Dependency", "Array index", "Type"])
        self.textures.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        layout.addWidget(QtWidgets.QLabel("Texture references")); layout.addWidget(self.textures, 1)
        self.open_button.clicked.connect(self.open_dialog)
        self.save_button.clicked.connect(self.save)
        self.save_as_button.clicked.connect(self.save_as)
        self._change_timer = QtCore.QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(300)
        self._change_timer.timeout.connect(self._emit_changed)
        self.attrs.cellChanged.connect(lambda _r, c: self._queue_changed() if c == 1 else None)
        self.textures.cellChanged.connect(lambda _r, c: self._queue_changed() if c == 2 else None)

    def _queue_changed(self):
        if self.model is not None:
            self._change_timer.start()

    def _emit_changed(self):
        try:
            self._commit()
            self.changed.emit(self.model)
        except Exception as e:
            self.summary.setText("Edit not applied: %s" % e)

    def load_path(self, path):
        self.attrs.blockSignals(True); self.textures.blockSignals(True)
        self.model = MaterialFgm.load(path)
        aa, tt = self.model.attributes(), self.model.textures()
        self.attrs.setRowCount(len(aa))
        for row, a in enumerate(aa):
            state, text = meaning(a.name)
            for col, value in enumerate((a.name, a.value, a.dtype, "%s — %s" % (state, text))):
                item = QtWidgets.QTableWidgetItem(value)
                if col != 1: item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.attrs.setItem(row, col, item)
        self.textures.setRowCount(len(tt))
        for row, t in enumerate(tt):
            for col, value in enumerate((t.name, t.dependency, str(t.array_index), t.dtype)):
                item = QtWidgets.QTableWidgetItem(value)
                if col != 2: item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.textures.setItem(row, col, item)
        self.summary.setText("%s — %s — %d attributes, %d texture slots" %
                             (os.path.basename(path), self.model.shader, len(aa), len(tt)))
        self.attrs.blockSignals(False); self.textures.blockSignals(False)
        self.save_button.setEnabled(True); self.save_as_button.setEnabled(True)
        return self.model

    def _commit(self):
        for row in range(self.attrs.rowCount()):
            name = self.attrs.item(row, 0).text()
            dtype = self.attrs.item(row, 2).text()
            value = validate_value(dtype, self.attrs.item(row, 1).text())
            self.model.set_attribute(name, value)
        for row in range(self.textures.rowCount()):
            index = int(self.textures.item(row, 2).text())
            if not 0 <= index <= 254:
                raise ValueError("texture array index must be between 0 and 254")
            self.model.set_texture_index(self.textures.item(row, 0).text(), index)

    def save(self):
        if self.model:
            self._commit(); self.model.save(); self.load_path(self.model.path)

    def save_as(self):
        if not self.model: return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save material FGM", self.model.path,
                                                       "FGM files (*.fgm)")
        if path:
            if not path.lower().endswith(".fgm"): path += ".fgm"
            self._commit(); self.model.save(path); self.load_path(path)

    def open_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open layer or swatch FGM", "",
                                                       "FGM files (*.fgm)")
        if path:
            try: self.load_path(path)
            except Exception as e: QtWidgets.QMessageBox.critical(self, "Material FGM", str(e))
