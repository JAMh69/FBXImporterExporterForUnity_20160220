# Scan2RVT

Herramienta externa (Windows) que convierte nubes de puntos de escáner (Leica BLK360)
y de dron (DJI Matrice 4E / DJI Terra) en:

- **Revit 2026 (.rvt)** con elementos nativos: niveles, suelos/forjados, **muros**, **cubiertas planas** y terreno (Toposolid).
- **IFC 4** georreferenciado, **glTF (.glb)**, **OBJ**, **STL** y nube limpia **.laz**.
- **Informe HTML** con niveles, forjados, avisos y plantas.

Instrucciones de uso para el usuario final: [`packaging/LEEME.txt`](packaging/LEEME.txt).

## Cómo funciona

```
Nubes (.e57 .las .laz .ply .pts .xyz)
  → lectura por bloques + submuestreo a 2 cm (centroide por vóxel)
  → limpieza de ruido (filtro estadístico)
  → terreno: clase LAS 2 o filtro morfológico progresivo (Zhang 2003) → MDT
  → muros: superficies verticales vistas en planta como líneas (RANSAC), por planta; esquinas ajustadas
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

Cada push compila en GitHub Actions (Windows) con `.github/workflows/scan2rvt.yml` (en la raíz del
repositorio) y deja `Scan2RVT.zip` como artefacto;
cada etiqueta `v*` lo publica además como versión descargable.

## Estado (fase 1)

Hecho: terreno, niveles, forjados/suelos, exportadores, interfaz con arrastrar y soltar, puente con Revit,
**muros** y **cubierta plana** (formato `modelo.json` versión 2).
Comprobado sólo con el edificio sintético (`scan2rvt.sintetico`): 8 muros de 20,0 × 12,0 m con esquinas cerradas,
geometría verificada en el IFC. **No probado con escaneos reales** ni con Revit (sin Revit en el entorno de desarrollo;
el complemento sólo se compila en GitHub Actions).

Nubes muy grandes: por encima de 40 millones de puntos (`max_puntos` en `config/ajustes.json`) la app sube el tamaño de
vóxel automáticamente y lo avisa; el análisis trabaja a 5 cm, así que no pierde información útil, pero la nube limpia
(.laz) sale con menos resolución. Los vecinos (ruido y normales) se calculan por bloques para acotar la memoria.
Un primer uso con 365 millones de puntos falló por memoria (46 GiB) antes de este cambio.

Solares y vuelos de dron: los niveles y muros están pensados para el **interior de un edificio** (casilla «Escáner»).
Con una nube de cientos de metros en «Escáner» la app lo avisa, y los forjados del edificio pueden no detectarse porque
el suelo exterior domina (se descartan superficies menores de un cuarto de la mayor). Los contornos de superficies enormes se
calculan con celdas más gruesas (hasta 25 millones de celdas) para no agotar la memoria.
Segundo fallo real de memoria (17,2 GiB en `levels._poligonos`) corregido con ese tope.

Limitaciones de los muros: el eje es la **cara vista** por el escáner (no el eje real), el espesor es un supuesto
(0,20 m), sin puertas ni ventanas, sin muros curvos. La cubierta se supone plana y con espesor supuesto.

Pendiente: puertas y ventanas, ajuste de forjados a los muros, alineación escáner–dron, pendientes de cubierta,
vista 3D de revisión en la app.
