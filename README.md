# Scan2RVT

Herramienta externa (Windows) que convierte nubes de puntos de escáner (Leica BLK360)
y de dron (DJI Matrice 4E / DJI Terra) en:

- **Revit 2026 (.rvt)** con elementos nativos: niveles, suelos/forjados y terreno (Toposolid).
- **IFC 4** georreferenciado, **glTF (.glb)**, **OBJ**, **STL** y nube limpia **.laz**.
- **Informe HTML** con niveles, forjados, avisos y plantas.

Instrucciones de uso para el usuario final: [`packaging/LEEME.txt`](packaging/LEEME.txt).

## Cómo funciona

```
Nubes (.e57 .las .laz .ply .pts .xyz)
  → lectura por bloques + submuestreo a 2 cm (centroide por vóxel)
  → limpieza de ruido (filtro estadístico)
  → terreno: clase LAS 2 o filtro morfológico progresivo (Zhang 2003) → MDT
  → niveles y forjados: superficies horizontales (área en planta por franja de altura),
    emparejado techo/suelo = forjado con espesor medido; contornos con huecos
  → modelo.json (coordenadas locales + offset)
      ├─ exportadores IFC / GLB / OBJ / STL / LAZ
      └─ Revit 2026: se abre con SCAN2RVT_JOB, el complemento crea el .rvt y cierra Revit
```

| Carpeta | Contenido |
|---|---|
| `src/scan2rvt/` | Motor (Python): lectura, detección, exportación, interfaz PySide6 |
| `revit/Scan2Rvt.Revit/` | Complemento de Revit 2026 (C#, .NET 8) |
| `packaging/` | PyInstaller, lanzador y LEEME |
| `tests/` | Pruebas con un edificio sintético (`scan2rvt.sintetico`) |

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q
python -m scan2rvt                      # ventana
python -m scan2rvt procesar --demo --nombre Demo --salidas ifc,glb
dotnet build revit/Scan2Rvt.Revit -c Release
```

Cada push a `main` compila en GitHub Actions (Windows) y deja `Scan2RVT.zip` como artefacto;
cada etiqueta `v*` lo publica además como versión descargable.

## Estado (fase 1)

Hecho: terreno, niveles, forjados/suelos, exportadores, interfaz con arrastrar y soltar, puente con Revit.
Pendiente (fase 2): muros, ajuste de contornos de forjado a los muros, alineación escáner–dron,
vista 3D de revisión en la app.
