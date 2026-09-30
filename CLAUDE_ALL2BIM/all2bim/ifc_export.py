"""Exportacion del modelo interno a IFC4 con IfcOpenShell."""
from __future__ import annotations

import math

import ifcopenshell
import ifcopenshell.api
import numpy as np

from .model import BimModel


def _matrix(x: float, y: float, z: float, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0, x], [s, c, 0, y], [0, 0, 1, z], [0, 0, 0, 1]], dtype=float)


def export_ifc(model: BimModel, path: str, project_name: str = "ALL2BIM") -> None:
    run = ifcopenshell.api.run
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = run("root.create_entity", f, ifc_class="IfcProject", name=project_name)
    run("unit.assign_unit", f)  # SI: metros
    ctx = run("context.add_context", f, context_type="Model")
    body = run("context.add_context", f, context_type="Model", context_identifier="Body",
               target_view="MODEL_VIEW", parent=ctx)
    site = run("root.create_entity", f, ifc_class="IfcSite", name="Site")
    building = run("root.create_entity", f, ifc_class="IfcBuilding", name="Building")
    run("aggregate.assign_object", f, products=[site], relating_object=project)
    run("aggregate.assign_object", f, products=[building], relating_object=site)

    storeys = {}
    for s in model.storeys:
        st = run("root.create_entity", f, ifc_class="IfcBuildingStorey", name=s.name)
        st.Elevation = s.elevation
        run("aggregate.assign_object", f, products=[st], relating_object=building)
        storeys[s.name] = (st, s.elevation)

    for w in model.walls:
        st, elev = storeys[w.storey]
        dx, dy = w.end[0] - w.start[0], w.end[1] - w.start[1]
        wall = run("root.create_entity", f, ifc_class="IfcWall", name="Muro")
        rep = run("geometry.add_wall_representation", f, context=body,
                  length=math.hypot(dx, dy), height=w.height, thickness=w.thickness)
        run("geometry.assign_representation", f, product=wall, representation=rep)
        run("geometry.edit_object_placement", f, product=wall,
            matrix=_matrix(w.start[0], w.start[1], elev, math.atan2(dy, dx)))
        run("spatial.assign_container", f, products=[wall], relating_structure=st)

    for sl in model.slabs:
        st, elev = storeys[sl.storey]
        slab = run("root.create_entity", f, ifc_class="IfcSlab", name="Forjado")
        rep = run("geometry.add_slab_representation", f, context=body,
                  depth=sl.thickness, polyline=[tuple(p) for p in sl.outline])
        run("geometry.assign_representation", f, product=slab, representation=rep)
        run("geometry.edit_object_placement", f, product=slab, matrix=_matrix(0, 0, elev - sl.thickness, 0))
        run("spatial.assign_container", f, products=[slab], relating_structure=st)

    for r in model.roofs:
        roof = run("root.create_entity", f, ifc_class="IfcRoof", name="Cubierta")
        rep = run("geometry.add_slab_representation", f, context=body,
                  depth=r.thickness, polyline=[tuple(p) for p in r.outline])
        run("geometry.assign_representation", f, product=roof, representation=rep)
        run("geometry.edit_object_placement", f, product=roof, matrix=_matrix(0, 0, r.elevation, 0))
        run("spatial.assign_container", f, products=[roof], relating_structure=building)

    f.write(path)
