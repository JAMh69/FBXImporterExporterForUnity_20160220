import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyvista")

from all2bim.model import BimModel, Roof, Slab, Storey, Wall
from all2bim.scene import model_meshes


def _model():
    sq = [(0, 0), (6, 0), (6, 4), (0, 4)]
    return BimModel(storeys=[Storey("P0", 0.0)], slabs=[Slab("P0", sq, 0.2)],
                    walls=[Wall("P0", (0, 0), (6, 0), 2.7, 0.2, 0.9), Wall("P0", (6, 0), (6, 4), 2.7, 0.2, 0.2)],
                    roofs=[Roof(sq, 2.7, 0.2)])


def test_scene_meshes():
    meshes = model_meshes(_model())
    assert [m[0] for m in meshes] == ["muro", "muro", "suelo", "cubierta"]
    assert meshes[0][3] == "lightgray" and meshes[1][3] == "orange"  # baja confianza a revision
    zmin = min(m[2].bounds[4] for m in meshes)
    zmax = max(m[2].bounds[5] for m in meshes)
    assert abs(zmin - (-0.2)) < 1e-6 and abs(zmax - 2.9) < 1e-6


def test_window_table_and_delete():
    from PySide6.QtWidgets import QApplication
    from all2bim.gui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    w = MainWindow(show_3d=False)
    w.model = _model(); w.refresh_table()
    assert w.table.rowCount() == 4
    w.table.selectRow(1); w.delete_selected()
    assert len(w.model.walls) == 1 and w.table.rowCount() == 3
    assert "Modelo valido." in w.log.toPlainText() or "confianza" in w.log.toPlainText()
