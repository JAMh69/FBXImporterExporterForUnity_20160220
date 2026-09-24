import json
import os
import xml.etree.ElementTree as ET

import ifcopenshell
import ifcopenshell.geom
import numpy as np
import pytest
import trimesh

from scan2rvt import paths, pipeline, revit_bridge
from scan2rvt.model import Modelo


@pytest.fixture(scope="module")
def resultado(tmp_path_factory):
    raiz = tmp_path_factory.mktemp("h") / "000 APPS JAMh" / "Scan2RVT"
    os.environ["SCAN2RVT_HOME"] = str(raiz)
    paths.ensure_dirs()
    from scan2rvt.config import Settings

    t = pipeline.Trabajo(nombre="Obra: prueba/1", demo=True, salidas=list(pipeline.SALIDAS))
    try:
        yield pipeline.ejecutar(t, Settings())
    finally:
        os.environ.pop("SCAN2RVT_HOME", None)


def test_carpetas_dentro_de_la_raiz(resultado):
    assert "000 APPS JAMh" in str(resultado.carpeta)
    assert resultado.carpeta.name == "Obra_ prueba_1"      # caracteres no válidos en Windows
    for a in resultado.archivos:
        assert resultado.carpeta in a.parents


def test_modelo_json(resultado):
    m = Modelo.load(resultado.carpeta / "resultados" / "modelo.json")
    assert [n.cota for n in m.niveles] == pytest.approx([0.0, 3.3, 6.3], abs=0.02)
    assert m.offset[2] == pytest.approx(100.0, abs=0.01)
    assert m.terreno is not None and len(m.terreno.puntos) > 100
    assert m.epsg == "25830"
    # Todos los forjados pertenecen a un nivel existente.
    ids = {n.id for n in m.niveles}
    assert all(f.nivel_id in ids for f in m.forjados)
    json.dumps(m.to_dict())


def test_ifc(resultado):
    ruta = next(a for a in resultado.archivos if a.suffix == ".ifc")
    f = ifcopenshell.open(str(ruta))
    assert len(f.by_type("IfcBuildingStorey")) == 3
    assert f.by_type("IfcProjectedCRS")[0].Name == "EPSG:25830"
    st = ifcopenshell.geom.settings()
    st.set("use-world-coords", True)
    zs = []
    for losa in f.by_type("IfcSlab"):
        forma = ifcopenshell.geom.create_shape(st, losa)   # mantener la referencia viva mientras se leen los vértices
        v = np.array(forma.geometry.verts).reshape(-1, 3)
        zs.append((round(v[:, 2].min(), 2), round(v[:, 2].max(), 2)))
    assert sorted(zs) == [(-0.3, 0.0), (3.0, 3.3), (6.0, 6.3)]
    assert len(f.by_type("IfcGeographicElement")) == 1


def test_mallas_y_las(resultado):
    glb = next(a for a in resultado.archivos if a.suffix == ".glb")
    escena = trimesh.load(glb)
    assert len(escena.geometry) == 4        # terreno + 3 forjados
    assert any(a.suffix == ".obj" for a in resultado.archivos)
    assert any(a.suffix == ".stl" for a in resultado.archivos)
    assert sum(a.suffix == ".laz" for a in resultado.archivos) == 2


def test_informe(resultado):
    html = resultado.informe.read_text(encoding="utf-8")
    assert "Nivel 1" in html and "EPSG:25830" in html


def test_rvt_fuera_de_windows_avisa(resultado):
    if os.name == "nt":
        pytest.skip("sólo aplica fuera de Windows")
    assert any("RVT no generado" in a for a in resultado.avisos)


def test_manifiesto_addin(home):
    dll = home / "revit" / revit_bridge.DLL
    dll.write_bytes(b"")
    xml = revit_bridge.manifiesto(dll)
    raiz = ET.fromstring(xml.encode("utf-8"))
    assert raiz.find("AddIn/Assembly").text == str(dll)
    assert raiz.find("AddIn/FullClassName").text == "Scan2Rvt.Revit.App"


def test_ajustes_ida_y_vuelta(home):
    from scan2rvt import config

    s = config.load()
    s.terreno.malla_m = 0.5
    s.epsg = "25830"
    config.save(s)
    s2 = config.load()
    assert s2.terreno.malla_m == 0.5 and s2.epsg == "25830"
    assert config.settings_file().parent == home / "config"
