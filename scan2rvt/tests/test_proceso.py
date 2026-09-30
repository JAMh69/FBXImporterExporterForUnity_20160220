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
    assert all(w.nivel_id in ids for w in m.muros) and all(c.nivel_id in ids for c in m.cubiertas)
    assert (len(m.forjados), len(m.muros), len(m.cubiertas)) == (2, 8, 1)
    assert m.version == 2
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
    assert sorted(zs) == [(-0.3, 0.0), (3.0, 3.3)]          # solera y forjado; el techo superior es cubierta
    assert len(f.by_type("IfcGeographicElement")) == 1

    # Cubierta: una sola, plana, entre 6,0 y 6,3 m.
    (cub,) = f.by_type("IfcRoof")
    v = np.array(ifcopenshell.geom.create_shape(st, cub).geometry.verts).reshape(-1, 3)
    assert (round(v[:, 2].min(), 2), round(v[:, 2].max(), 2)) == (6.0, 6.3)

    # Muros: 4 por planta, con la longitud, altura y espesor del modelo, en el nivel correcto.
    muros = f.by_type("IfcWall")
    assert len(muros) == 8
    dims = []
    for w in muros:
        v = np.array(ifcopenshell.geom.create_shape(st, w).geometry.verts).reshape(-1, 3)
        ext = v.max(axis=0) - v.min(axis=0)
        assert round(min(ext[0], ext[1]), 2) == 0.20            # espesor supuesto del modelo
        dims.append((round(max(ext[0], ext[1]), 1), round(ext[2], 1), round(v[:, 2].min(), 1)))
    assert sorted(dims) == sorted([(20.0, 3.0, 0.0)] * 2 + [(12.0, 3.0, 0.0)] * 2 + [(20.0, 2.7, 3.3)] * 2 + [(12.0, 2.7, 3.3)] * 2)


def test_mallas_y_las(resultado):
    glb = next(a for a in resultado.archivos if a.suffix == ".glb")
    escena = trimesh.load(glb)
    assert len(escena.geometry) == 12       # terreno + 2 forjados + 1 cubierta + 8 muros
    assert any(a.suffix == ".obj" for a in resultado.archivos)
    assert any(a.suffix == ".stl" for a in resultado.archivos)
    assert sum(a.suffix == ".laz" for a in resultado.archivos) == 2


def test_informe(resultado):
    html = resultado.informe.read_text(encoding="utf-8")
    assert "Nivel 1" in html and "EPSG:25830" in html
    assert "Muros" in html and "Cubiertas" in html and 'class="muro"' in html


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


def test_aviso_si_la_nube_de_escaner_es_un_solar(tmp_path, monkeypatch):
    """Un escáner de cientos de metros no es el interior de un edificio: la app debe avisarlo."""
    import numpy as np

    from scan2rvt import pipeline, sintetico
    from scan2rvt.cloud import Nube
    from scan2rvt.config import Settings

    monkeypatch.setenv("SCAN2RVT_HOME", str(tmp_path / "000 APPS JAMh" / "Scan2RVT"))
    paths.ensure_dirs()
    d = sintetico.generar()
    cx, cy = sintetico.X0 + 30, sintetico.Y0 + 26
    lejos = np.array([[cx + 400, cy, 99.0], [cx - 400, cy, 99.0]])       # dos puntos: nube de 800 m
    demo = sintetico.Demo(Nube(np.vstack([d.escaner.xyz, lejos])), d.dron)
    monkeypatch.setattr(sintetico, "generar", lambda *a, **k: demo)
    r = pipeline.ejecutar(pipeline.Trabajo(nombre="Solar", demo=True, salidas=["ifc"]), Settings())
    assert any("parece un solar entero" in a for a in r.avisos)
