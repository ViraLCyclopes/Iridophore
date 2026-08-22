"""Qt editor for DinosaurLayered_Layer and DinosaurLayered_Swatch_Opaque FGMs."""
import os
from PyQt5 import QtCore, QtWidgets

from material_fgm import MaterialFgm, meaning


class MaterialFgmTab(QtWidgets.QWidget):
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

    def load_path(self, path):
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
        self.save_button.setEnabled(True); self.save_as_button.setEnabled(True)
        return self.model

    def _commit(self):
        for row in range(self.attrs.rowCount()):
            self.model.set_attribute(self.attrs.item(row, 0).text(), self.attrs.item(row, 1).text())
        for row in range(self.textures.rowCount()):
            self.model.set_texture_index(self.textures.item(row, 0).text(),
                                         int(self.textures.item(row, 2).text()))

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

