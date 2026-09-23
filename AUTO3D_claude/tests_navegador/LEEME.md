# Pruebas de navegador

La lógica que corre en el navegador se verifica aquí, contra la implementación de
Python —que tiene sus propias 93 pruebas— y contra escenas de verdad conocida.

```bash
npm i playwright                     # una vez
python3 python/tests/hacer_fotos_dji.py /tmp/sint/vuelo_test   # fotos sintéticas con XMP de DJI
node tests_navegador/01_multivista_vs_python.js
node tests_navegador/02_medir_verdad_conocida.js
node tests_navegador/03_marcado_con_raton.js
node tests_navegador/04_explorar_carpeta.js
```

| prueba | qué comprueba | resultado medido |
|---|---|---|
| 01 | el puerto de la triangulación a JavaScript da lo mismo que Python | 4·10⁻¹⁵ m de diferencia |
| 02 | de los metadatos DJI a una medida en metros | lado de 20 m con 0,0 mm de error |
| 03 | el marcado con ratón, la elección de la segunda vista y la recta epipolar | 19,99 m marcando a mano |
| 04 | el explorador de carpetas sobre archivos reales | clasifica y ordena los cuatro casos |

Las rutas están puestas a mano al principio de cada archivo; ajústalas si mueves algo.
