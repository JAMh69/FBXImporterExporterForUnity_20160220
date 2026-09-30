"""Ventana principal: visor 3D (nube + modelo interno), tabla de elementos, validacion y exportacion."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QHeaderView, QCheckBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView)

from ..model import BimModel
from ..scene import cloud_mesh, model_meshes
from ..validate import validate


class DetectWorker(QThread):
    done = Signal(object, object)   # puntos, modelo
    failed = Signal(str)

    def __init__(self, path: str, voxel: float, wall_t: float, slab_t: float):
        super().__init__()
        self.path, self.voxel, self.wall_t, self.slab_t = path, voxel, wall_t, slab_t

    def run(self):
        try:
            from ..detect import load_las, points_to_model
            pts = load_las(self.path, self.voxel)
            self.done.emit(pts, points_to_model(pts, self.wall_t, self.slab_t))
        except Exception as e:  # noqa: BLE001 - se muestra al usuario
            self.failed.emit(f"{type(e).__name__}: {e}")


class MainWindow(QMainWindow):
    def __init__(self, show_3d: bool = True):
        super().__init__()
        self.setWindowTitle("ALL2BIM - Nube de puntos a BIM")
        self.resize(1400, 850)
        self.model = BimModel()
        self.pts: np.ndarray | None = None
        self.worker: DetectWorker | None = None
        self.plotter = None
        if show_3d:
            from pyvistaqt import QtInteractor
            self.plotter = QtInteractor(self)
            self.setCentralWidget(self.plotter.interactor)
        else:
            self.setCentralWidget(QWidget())
        self._build_panels()
        self._build_menu()
        self.statusBar().showMessage("Abra un archivo .las")

    # ---- construccion de la UI ----
    def _build_menu(self):
        bar = self.menuBar().addMenu("Archivo")
        for text, fn in [("Abrir LAS y detectar...", self.open_las), ("Abrir modelo JSON...", self.open_json),
                         ("Guardar modelo JSON...", self.save_json), ("Exportar IFC...", self.export_ifc)]:
            act = QAction(text, self); act.triggered.connect(fn); bar.addAction(act)
        bar.addSeparator()
        q = QAction("Salir", self); q.triggered.connect(self.close); bar.addAction(q)

    def _build_panels(self):
        # Parametros de deteccion
        params = QWidget(); form = QFormLayout(params)
        self.voxel = QDoubleSpinBox(); self.voxel.setRange(0.0, 1.0); self.voxel.setSingleStep(0.01); self.voxel.setValue(0.05)
        self.wall_t = QDoubleSpinBox(); self.wall_t.setRange(0.05, 1.0); self.wall_t.setSingleStep(0.01); self.wall_t.setValue(0.20)
        self.slab_t = QDoubleSpinBox(); self.slab_t.setRange(0.05, 1.0); self.slab_t.setSingleStep(0.01); self.slab_t.setValue(0.20)
        form.addRow("Voxel de submuestreo (m)", self.voxel)
        form.addRow("Espesor muro (m)", self.wall_t)
        form.addRow("Espesor suelo/cubierta (m)", self.slab_t)
        self.show_cloud = QCheckBox("Mostrar nube"); self.show_cloud.setChecked(True)
        self.show_cloud.toggled.connect(self.refresh_scene)
        form.addRow(self.show_cloud)
        b = QPushButton("Abrir LAS y detectar..."); b.clicked.connect(self.open_las); form.addRow(b)
        self._dock("Deteccion", params, Qt.LeftDockWidgetArea)

        # Tabla de elementos
        box = QWidget(); lay = QVBoxLayout(box)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Tipo", "Planta", "Longitud/Area", "Espesor", "Confianza"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self.refresh_scene)
        lay.addWidget(self.table)
        d = QPushButton("Eliminar seleccionados"); d.clicked.connect(self.delete_selected); lay.addWidget(d)
        v = QPushButton("Validar modelo"); v.clicked.connect(self.run_validation); lay.addWidget(v)
        self.log = QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(160); lay.addWidget(self.log)
        e = QPushButton("Exportar IFC (valida antes)..."); e.clicked.connect(self.export_ifc); lay.addWidget(e)
        box.setMinimumWidth(430)
        self._dock("Elementos y validacion", box, Qt.RightDockWidgetArea)

    def _dock(self, title, widget, area):
        d = QDockWidget(title, self); d.setWidget(widget); self.addDockWidget(area, d)

    # ---- acciones ----
    def open_las(self):
        path, _ = QFileDialog.getOpenFileName(self, "Nube de puntos", "", "LAS (*.las);;Todos (*)")
        if not path:
            return
        self.statusBar().showMessage(f"Detectando en {Path(path).name}...")
        self.worker = DetectWorker(path, self.voxel.value(), self.wall_t.value(), self.slab_t.value())
        self.worker.done.connect(self._on_detected)
        self.worker.failed.connect(lambda m: (self.statusBar().clearMessage(), QMessageBox.critical(self, "Error", m)))
        self.worker.start()

    def _on_detected(self, pts, model):
        self.pts, self.model = pts, model
        self.statusBar().showMessage(f"{len(pts):,} puntos | {len(model.storeys)} plantas, {len(model.walls)} muros, "
                                     f"{len(model.slabs)} suelos, {len(model.roofs)} cubiertas")
        self.refresh_table(); self.refresh_scene(reset_camera=True); self.run_validation()

    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Modelo", "", "JSON (*.json)")
        if path:
            self.model = BimModel.load(path)
            self.refresh_table(); self.refresh_scene(reset_camera=True); self.run_validation()

    def save_json(self):
        path, _ = QFileDialog.getSaveFileName(self, "Guardar modelo", "modelo.json", "JSON (*.json)")
        if path:
            self.model.save(path)

    def export_ifc(self):
        issues = validate(self.model)
        if issues and QMessageBox.question(self, "Avisos de validacion",
                                           f"{len(issues)} avisos. Exportar de todos modos?") != QMessageBox.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar IFC", "salida.ifc", "IFC (*.ifc)")
        if path:
            from ..ifc_export import export_ifc
            export_ifc(self.model, path)
            self.statusBar().showMessage(f"IFC escrito: {path}")

    def run_validation(self):
        issues = validate(self.model)
        self.log.setPlainText("\n".join(issues) if issues else "Modelo valido.")
        return issues

    # ---- elementos ----
    def _rows(self):
        m = self.model
        import math
        rows = [("muro", i, w.storey, f"{math.dist(w.start, w.end):.2f} m", f"{w.thickness:.2f}", f"{w.confidence:.2f}")
                for i, w in enumerate(m.walls)]
        rows += [("suelo", i, s.storey, "", f"{s.thickness:.2f}", "") for i, s in enumerate(m.slabs)]
        rows += [("cubierta", i, "", "", f"{r.thickness:.2f}", "") for i, r in enumerate(m.roofs)]
        return rows

    def refresh_table(self):
        rows = self._rows()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for r, (kind, idx, *cols) in enumerate(rows):
            first = QTableWidgetItem(kind); first.setData(Qt.UserRole, (kind, idx))
            self.table.setItem(r, 0, first)
            for c, text in enumerate(cols, start=1):
                self.table.setItem(r, c, QTableWidgetItem(text))
        self.table.blockSignals(False)

    def _selected(self) -> set[tuple[str, int]]:
        return {self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectionModel().selectedRows()}

    def delete_selected(self):
        sel = self._selected()
        for attr, kind in (("walls", "muro"), ("slabs", "suelo"), ("roofs", "cubierta")):
            setattr(self.model, attr, [e for i, e in enumerate(getattr(self.model, attr)) if (kind, i) not in sel])
        self.refresh_table(); self.refresh_scene(); self.run_validation()

    def refresh_scene(self, reset_camera: bool = False):
        if self.plotter is None:
            return
        sel = self._selected()
        self.plotter.clear()
        if self.pts is not None and self.show_cloud.isChecked():
            self.plotter.add_mesh(cloud_mesh(self.pts), scalars="z", cmap="viridis", point_size=2,
                                  render_points_as_spheres=False, show_scalar_bar=False)
        for kind, idx, mesh, color in model_meshes(self.model):
            self.plotter.add_mesh(mesh, color="red" if (kind, idx) in sel else color,
                                  opacity=0.6, show_edges=True)
        if reset_camera:
            self.plotter.reset_camera()


def main() -> int:
    app = QApplication(sys.argv)
    w = MainWindow(); w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
