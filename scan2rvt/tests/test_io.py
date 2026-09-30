import laspy
import numpy as np
import pytest

from scan2rvt.cloud import Nube, voxel_reduce
from scan2rvt.io import buscar_nubes, leer_nube


def _las(ruta, xyz, rgb=None, clase=None):
    h = laspy.LasHeader(point_format=3, version="1.4")
    h.offsets = np.floor(xyz.min(axis=0))
    h.scales = [0.001] * 3
    las = laspy.LasData(h)
    las.x, las.y, las.z = xyz.T
    if rgb is not None:
        las.red, las.green, las.blue = (rgb.astype(np.uint16) * 257).T
    if clase is not None:
        las.classification = clase
    las.write(ruta)


def test_leer_las_y_laz(tmp_path):
    rng = np.random.default_rng(0)
    xyz = rng.random((20000, 3)) * [10, 10, 3] + [440000, 4474000, 600]
    rgb = rng.integers(0, 255, (20000, 3), dtype=np.uint8)
    for ext in (".las", ".laz"):
        ruta = tmp_path / f"nube{ext}"
        _las(ruta, xyz, rgb, np.full(20000, 2, np.uint8))
        n = leer_nube(ruta, voxel=0.0, origen=1)
        assert len(n) == 20000
        assert np.allclose(np.sort(n.xyz[:, 0]), np.sort(xyz[:, 0]), atol=0.001)
        assert n.rgb is not None and n.clase is not None and (n.origen == 1).all()


def test_submuestreo_por_bloques(tmp_path, monkeypatch):
    from scan2rvt.io import reader

    monkeypatch.setattr(reader, "_BLOQUE", 1000)       # obliga a leer en varios bloques
    rng = np.random.default_rng(0)
    xyz = rng.random((10000, 3)) * [2, 2, 0.1] + [440000, 4474000, 600]
    _las(tmp_path / "a.las", xyz)
    n = leer_nube(tmp_path / "a.las", voxel=0.1, origen=0)
    # 20 × 20 × 1 vóxeles de 10 cm: no puede haber más puntos que vóxeles.
    assert len(n) <= 20 * 20 * 2
    assert np.allclose(n.xyz.mean(axis=0), xyz.mean(axis=0), atol=0.01)


def test_leer_e57(tmp_path):
    pye57 = pytest.importorskip("pye57")
    rng = np.random.default_rng(0)
    xyz = rng.random((5000, 3)) * 5
    ruta = tmp_path / "escaneo.e57"
    e = pye57.E57(str(ruta), mode="w")
    e.write_scan_raw({"cartesianX": xyz[:, 0], "cartesianY": xyz[:, 1], "cartesianZ": xyz[:, 2]})
    e.close()
    n = leer_nube(ruta, voxel=0.0, origen=0)
    assert len(n) == 5000


def test_buscar_en_carpetas_y_rcp(tmp_path):
    (tmp_path / "obra" / "sub").mkdir(parents=True)
    _las(tmp_path / "obra" / "sub" / "x.las", np.random.default_rng(0).random((100, 3)))
    (tmp_path / "obra" / "proyecto.rcp").write_text("")
    (tmp_path / "obra" / "notas.txt").write_text("")
    nubes, avisos = buscar_nubes([tmp_path / "obra"])
    assert [p.name for p in nubes] == ["x.las"]
    assert any("E57" in a for a in avisos)


def test_voxel_centroide():
    xyz = np.array([[0.01, 0.01, 0.01], [0.03, 0.03, 0.03], [0.51, 0, 0]])
    n = voxel_reduce(Nube(xyz), 0.1, origin=np.zeros(3))
    assert len(n) == 2
    assert np.allclose(sorted(n.xyz[:, 0]), [0.02, 0.51])


def test_leer_pts_xyz_ply(tmp_path):
    import trimesh

    rng = np.random.default_rng(0)
    xyz = rng.random((3000, 3)) * 4
    rgb = rng.integers(0, 255, (3000, 3))
    inten = rng.integers(-2047, 2047, (3000, 1))
    # .pts de Leica: primera línea = nº de puntos; x y z intensidad r g b
    with open(tmp_path / "a.pts", "w") as f:
        f.write("3000\n")
        np.savetxt(f, np.hstack([xyz, inten, rgb]), fmt="%.4f %.4f %.4f %d %d %d %d")
    np.savetxt(tmp_path / "b.xyz", xyz, fmt="%.4f")
    trimesh.PointCloud(xyz, colors=np.hstack([rgb, np.full((3000, 1), 255)])).export(tmp_path / "c.ply")
    for nombre in ("a.pts", "b.xyz", "c.ply"):
        n = leer_nube(tmp_path / nombre, voxel=0.0, origen=0)
        assert len(n) == 3000, nombre
        assert np.allclose(np.sort(n.xyz[:, 2]), np.sort(xyz[:, 2]), atol=1e-3)
    assert leer_nube(tmp_path / "a.pts", 0.0, 0).rgb is not None
    assert leer_nube(tmp_path / "c.ply", 0.0, 0).rgb is not None


def test_normales_de_un_plano():
    from scan2rvt.cloud import normales

    rng = np.random.default_rng(0)
    xyz = np.column_stack([rng.random(2000) * 5, rng.random(2000) * 5, np.full(2000, 3.0)])
    assert (np.abs(normales(xyz)[:, 2]) > 0.99).all()


def test_quitar_ruido():
    from scan2rvt.cloud import remove_outliers

    rng = np.random.default_rng(0)
    plano = np.column_stack([rng.random(5000) * 5, rng.random(5000) * 5, np.zeros(5000)])
    ruido = rng.random((20, 3)) * 5 + [0, 0, 3]
    n = remove_outliers(Nube(np.vstack([plano, ruido])))
    assert (n.xyz[:, 2] < 1).sum() >= 4900 and (n.xyz[:, 2] > 1).sum() == 0


def test_ruido_y_normales_por_bloques_dan_lo_mismo():
    """El procesado por bloques (memoria acotada) no cambia el resultado."""
    import numpy as np

    from scan2rvt.cloud import Nube, normales, remove_outliers

    rng = np.random.default_rng(3)
    plano = np.column_stack([rng.random((4000, 2)) * 10, rng.normal(0, 0.002, 4000)])
    ruido = rng.random((40, 3)) * [10, 10, 5] + [0, 0, 1]          # puntos sueltos lejos del plano
    nube = Nube(np.vstack([plano, ruido]))

    grande = remove_outliers(nube, bloque=10_000_000)
    pequena = remove_outliers(nube, bloque=500)
    assert len(grande) == len(pequena) < len(nube)
    assert np.array_equal(grande.xyz, pequena.xyz)

    n1, n2 = normales(plano, bloque=10_000_000), normales(plano, bloque=300)
    assert np.allclose(n1, n2)
    assert np.abs(n1[:, 2]).mean() > 0.99                            # normales verticales en un plano horizontal


def test_limitar_puntos():
    import numpy as np

    from scan2rvt.cloud import Nube, limitar_puntos

    rng = np.random.default_rng(4)
    nube = Nube(np.column_stack([rng.random((200_000, 2)) * 20, np.zeros(200_000)]))
    igual, v0 = limitar_puntos(nube, 10_000_000, 0.02)
    assert igual is nube and v0 == 0.02                                  # ya cabe: no se toca
    red, v = limitar_puntos(nube, 20_000, 0.02)
    assert 0 < len(red) <= 20_000 and v > 0.02
