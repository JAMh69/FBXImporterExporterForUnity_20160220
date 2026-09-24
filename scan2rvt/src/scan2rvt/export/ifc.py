"""Exportación a IFC4: emplazamiento, edificio, plantas, forjados (IfcSlab) y terreno."""

from __future__ import annotations

from pathlib import Path

import ifcopenshell
import ifcopenshell.api.aggregate
import ifcopenshell.api.context
import ifcopenshell.api.geometry
import ifcopenshell.api.georeference
import ifcopenshell.api.project
import ifcopenshell.api.root
import ifcopenshell.api.spatial
import ifcopenshell.api.unit
import numpy as np

from ..model import Forjado, Modelo


def _matriz(z: float = 0.0) -> np.ndarray:
    m = np.eye(4)
    m[2, 3] = z
    return m


def _polilinea(f: ifcopenshell.file, pts: list[list[float]]):
    puntos = [f.createIfcCartesianPoint((float(x), float(y))) for x, y in pts]
    return f.createIfcPolyline(puntos + [puntos[0]])


def _cuerpo_forjado(f: ifcopenshell.file, ctx, fj: Forjado):
    exterior = _polilinea(f, fj.contorno)
    if fj.huecos:
        perfil = f.createIfcArbitraryProfileDefWithVoids("AREA", None, exterior, [_polilinea(f, h) for h in fj.huecos])
    else:
        perfil = f.createIfcArbitraryClosedProfileDef("AREA", None, exterior)
    eje = f.createIfcAxis2Placement3D(f.createIfcCartesianPoint((0.0, 0.0, 0.0)))
    solido = f.createIfcExtrudedAreaSolid(perfil, eje, f.createIfcDirection((0.0, 0.0, 1.0)), float(fj.espesor))
    return f.createIfcShapeRepresentation(ctx, "Body", "SweptSolid", [solido])


def exportar(modelo: Modelo, ruta: Path, nombre: str) -> Path:
    f = ifcopenshell.api.project.create_file(version="IFC4")
    proyecto = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name=nombre)
    unidades = [ifcopenshell.api.unit.add_si_unit(f, unit_type=t) for t in ("LENGTHUNIT", "AREAUNIT", "VOLUMEUNIT")]
    ifcopenshell.api.unit.assign_unit(f, units=unidades)
    modelo3d = ifcopenshell.api.context.add_context(f, context_type="Model")
    cuerpo = ifcopenshell.api.context.add_context(
        f, context_type="Model", context_identifier="Body", target_view="MODEL_VIEW", parent=modelo3d
    )

    if modelo.epsg:
        ifcopenshell.api.georeference.add_georeferencing(f, name=f"EPSG:{modelo.epsg}")
        ox, oy, oz = modelo.offset
        ifcopenshell.api.georeference.edit_georeferencing(
            f, coordinate_operation={"Eastings": ox, "Northings": oy, "OrthogonalHeight": oz}
        )

    sitio = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSite", name="Emplazamiento")
    edificio = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuilding", name=nombre)
    ifcopenshell.api.aggregate.assign_object(f, products=[sitio], relating_object=proyecto)
    ifcopenshell.api.aggregate.assign_object(f, products=[edificio], relating_object=sitio)
    for e in (sitio, edificio):
        ifcopenshell.api.geometry.edit_object_placement(f, product=e, matrix=_matriz())

    plantas = {}
    for n in modelo.niveles:
        p = ifcopenshell.api.root.create_entity(f, ifc_class="IfcBuildingStorey", name=n.nombre)
        p.Elevation = float(n.cota)
        ifcopenshell.api.geometry.edit_object_placement(f, product=p, matrix=_matriz(n.cota))
        ifcopenshell.api.aggregate.assign_object(f, products=[p], relating_object=edificio)
        plantas[n.id] = p

    for fj in modelo.forjados:
        tipo = "BASESLAB" if not fj.espesor_medido and fj.nivel_id == (modelo.niveles[0].id if modelo.niveles else "") else "FLOOR"
        losa = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab", name=fj.id, predefined_type=tipo)
        ifcopenshell.api.geometry.edit_object_placement(f, product=losa, matrix=_matriz(fj.cota_superior - fj.espesor))
        ifcopenshell.api.geometry.assign_representation(f, product=losa, representation=_cuerpo_forjado(f, cuerpo, fj))
        if fj.nivel_id in plantas:
            ifcopenshell.api.spatial.assign_container(f, products=[losa], relating_structure=plantas[fj.nivel_id])

    if modelo.terreno is not None and modelo.terreno.caras:
        terreno = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcGeographicElement", name="Terreno", predefined_type="TERRAIN"
        )
        ifcopenshell.api.geometry.edit_object_placement(f, product=terreno, matrix=_matriz())
        rep = ifcopenshell.api.geometry.add_mesh_representation(
            f,
            context=cuerpo,
            vertices=[[tuple(map(float, v)) for v in modelo.terreno.vertices]],
            faces=[[list(map(int, c)) for c in modelo.terreno.caras]],
        )
        ifcopenshell.api.geometry.assign_representation(f, product=terreno, representation=rep)
        ifcopenshell.api.spatial.assign_container(f, products=[terreno], relating_structure=sitio)

    f.write(str(ruta))
    return ruta
