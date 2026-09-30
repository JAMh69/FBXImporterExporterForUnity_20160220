# CLAUDE_ALL2BIM

Pipeline local / open source: **nube de puntos (.las) -> modelo 3D interno validable -> IFC4 -> RVT**.

## Estado (v0.1, MVP)
Probado con una nube sintetica (habitacion 6x4x2.7 m): `pytest` pasa (3 tests: motor LAS->IFC, mallas 3D, tabla de la ventana).
NO probado con escaneos reales. La deteccion es heuristica y necesita revision manual.
La interfaz PySide6 NO se ha visto funcionando con pantalla: en el entorno de desarrollo (Linux sin display) solo se
probo la construccion de la ventana/tabla y el render de las mallas con PyVista (`docs/preview_scene.png`).
El visor interactivo (QtInteractor) esta sin probar; el primer arranque en Windows 11 puede requerir ajustes.

| Etapa | Modulo | Estado |
|---|---|---|
| LAS -> puntos (voxel) | `detect.load_las` (laspy) | implementado |
| Plantas (histograma Z) y muros (RANSAC de planos verticales) | `detect.points_to_model` | basico, solo muros ortogonales/rectos, sin huecos |
| Cubiertas planas (nivel horizontal mas alto) | `detect.points_to_model` | basico, solo planas |
| Modelo interno JSON | `model.py` | implementado |
| Validacion previa a exportar | `validate.py` | reglas basicas |
| IFC4 (IfcWall, IfcSlab, IfcRoof, plantas) | `ifc_export.py` (IfcOpenShell) | implementado |
| IFC -> RVT | manual en Revit | ver abajo |
| Puertas/ventanas, PDF, fotos/video (COLMAP/OpenMVS) | - | pendiente |

## Uso
Interfaz (Windows 11): `pip install -e .[gui]` y luego `all2bim-gui` (o `python -m all2bim.gui.main_window`).
Abrir LAS, revisar en 3D (muros de baja confianza en naranja), eliminar elementos, validar y exportar.

Linea de comandos:
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

## Directo a RVT (Revit 2026)
Plan: add-in C# (`net8.0-windows`; la API de Revit es solo .NET 8 desde Revit 2025,
https://help.autodesk.com/view/RVT/2025/ENU/?guid=2db849bc-e193-4919-a96c-cc324cf06f66) que lee `modelo.json`
y crea muros, suelos y cubiertas nativos. Pendiente de implementar; requiere Revit para probarse.
Nota Autodesk: la API no permite crear techos (ceilings) nuevos; las cubiertas (roofs) son otro elemento y su soporte se verificara al implementar.

## Proximos pasos propuestos
1. Probar con un LAS real y ajustar tolerancias.
2. Probar la interfaz en Windows 11.
3. Add-in de Revit 2026.
4. Huecos (puertas/ventanas) y muros no ortogonales.
5. Entradas de fotos/video (COLMAP -> OpenMVS) y PDF de planos.
