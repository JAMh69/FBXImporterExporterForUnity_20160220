# CLAUDE_ALL2BIM

Pipeline local / open source: **nube de puntos (.las) -> modelo 3D interno validable -> IFC4 -> RVT**.

## Estado (v0.1, MVP)
Probado con una nube sintética (habitacion 6x4x2.7 m): `pytest` pasa (1 test).
NO probado con escaneos reales. La deteccion es heuristica y necesita revision manual.

| Etapa | Modulo | Estado |
|---|---|---|
| LAS -> puntos (voxel) | `detect.load_las` (laspy) | implementado |
| Plantas (histograma Z) y muros (RANSAC de planos verticales) | `detect.points_to_model` | basico, solo muros ortogonales/rectos, sin huecos |
| Modelo interno JSON | `model.py` | implementado |
| Validacion previa a exportar | `validate.py` | reglas basicas |
| IFC4 (IfcWall, IfcSlab, plantas) | `ifc_export.py` (IfcOpenShell) | implementado |
| IFC -> RVT | manual en Revit | ver abajo |
| Puertas/ventanas, PDF, fotos/video (COLMAP/OpenMVS) | - | pendiente |

## Uso
```
pip install -e .[dev]
all2bim las2model escaneo.las modelo.json     # 1) detectar
# 2) revisar/editar modelo.json a mano
all2bim validate modelo.json                  # 3) validar
all2bim model2ifc modelo.json salida.ifc      # 4) exportar (aborta si hay avisos; --force para ignorar)
```

## Sobre RVT
- RVT es un formato propietario de Autodesk. No conozco ninguna libreria open source que escriba .rvt directamente (no verificado de forma exhaustiva).
- Via documentada por Autodesk: en Revit, *Archivo > Abrir > IFC* y guardar como RVT
  (https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/IFC-model-from-Archicad-appears-distorted-and-misaligned-when-linked-into-Revit.html).
- Revit no admite LAS directamente; hay que pasar por ReCap a RCP/RCS
  (https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-import-Las-point-clouds-files-in-Revit.html).
  Util para superponer la nube como referencia al revisar el modelo.
- Automatizar la etapa IFC->RVT requeriria un add-in con la API de Revit (C#) o pyRevit; es un siguiente paso opcional.

## Proximos pasos propuestos
1. Probar con un LAS real y ajustar tolerancias.
2. Huecos (puertas/ventanas) y muros no ortogonales.
3. Visor para validar el modelo interno.
4. Entradas de fotos/video (COLMAP -> OpenMVS) y PDF de planos.
