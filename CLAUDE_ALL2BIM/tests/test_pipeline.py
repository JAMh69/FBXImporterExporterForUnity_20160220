import laspy
import ifcopenshell
import numpy as np

from all2bim.cli import main
from all2bim.model import BimModel
from all2bim.validate import validate


def _room_las(path, w=6.0, d=4.0, h=2.7, step=0.04):
    pts = []
    xs, ys = np.arange(0, w, step), np.arange(0, d, step)
    zs = np.arange(0, h, step)
    gx, gy = np.meshgrid(xs, ys)
    pts.append(np.column_stack([gx.ravel(), gy.ravel(), np.zeros(gx.size)]))          # suelo
    pts.append(np.column_stack([gx.ravel(), gy.ravel(), np.full(gx.size, h)]))         # techo
    for x in (0, w):
        gy2, gz = np.meshgrid(ys, zs); pts.append(np.column_stack([np.full(gy2.size, x), gy2.ravel(), gz.ravel()]))
    for y in (0, d):
        gx2, gz = np.meshgrid(xs, zs); pts.append(np.column_stack([gx2.ravel(), np.full(gx2.size, y), gz.ravel()]))
    p = np.vstack(pts)
    las = laspy.create(point_format=0, file_version="1.2")
    las.x, las.y, las.z = p[:, 0], p[:, 1], p[:, 2]
    las.write(str(path))


def test_las_to_ifc(tmp_path):
    las, js, ifc = tmp_path / "r.las", tmp_path / "m.json", tmp_path / "o.ifc"
    _room_las(las)
    assert main(["las2model", str(las), str(js)]) == 0
    m = BimModel.load(js)
    assert len(m.storeys) == 1
    assert len(m.roofs) == 1
    assert abs(m.walls[0].height - 2.7) < 0.1
    assert len(m.walls) == 4
    assert validate(m) == []
    assert main(["model2ifc", str(js), str(ifc)]) == 0
    f = ifcopenshell.open(str(ifc))
    assert len(f.by_type("IfcWall")) == 4
    assert len(f.by_type("IfcSlab")) == 1
    assert len(f.by_type("IfcRoof")) == 1
