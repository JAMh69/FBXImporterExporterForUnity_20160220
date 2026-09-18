# AUTO3D — Cuaderno de conocimiento

> Documento vivo. Cada sesión de trabajo añade una entrada en **9. Registro**.
> Está escrito para poder pegarse entero (o por secciones) en otra IA —
> ChatGPT, Claude, Copilot— y que retome el proyecto sin contexto previo.

- **Objetivo final**: obtener un modelo BIM de un edificio a partir de fotos o vídeos.
- **Estado**: v0.1 — detección geométrica + anotación + seguimiento + clasificador propio + reconstrucción monocular de una vista. **Todavía no genera IFC.**
- **Carpeta**: `AUTO3D_claude` (paralela a `AUTO3D`, que es la línea de trabajo de ChatGPT).
- **Tecnología**: HTML + JavaScript puro, sin dependencias, sin servidor. Funciona abriendo `index.html` con doble clic. Todo el procesado ocurre en el equipo del usuario.

---

## 1. Por qué este camino y no otro

El problema "foto → BIM" se suele atacar por fotogrametría densa (COLMAP, RealityCapture):
nube de puntos → malla → segmentación → IFC. Ese camino necesita muchas fotos,
mucha máquina y aun así la segmentación semántica sigue siendo el cuello de botella.

AUTO3D toma la vía complementaria, que es la que da valor con **una sola foto**:

1. Un edificio es un **mundo de Manhattan**: casi todas sus aristas siguen tres direcciones ortogonales.
2. Esas tres direcciones se ven en la imagen como **tres puntos de fuga**.
3. Con dos puntos de fuga ortogonales se calibra la cámara (distancia focal) sin conocer el equipo.
4. Con la calibración y **un dato de escala** (la altura de la cámara) se recupera geometría métrica.
5. Lo que la geometría no puede decidir —qué es fachada, qué es cubierta, qué es hueco— lo **aprende del usuario** en el modo LEARN.

El paso 5 es el núcleo del proyecto: **la semántica no se adivina, se enseña.** Y una vez
enseñada es transferible (se exporta como dataset + pesos).

---

## 2. Arquitectura del código

```
AUTO3D_claude/
  index.html          interfaz completa (paneles, lienzo, línea de tiempo)
  css/style.css
  js/core.js          estado global, bus de eventos, geometría 2D, modelo de objetos
  js/vision.js        gris → gauss → sobel → Canny → cadenas → segmentos rectos
  js/geometry.js      puntos de fuga (RANSAC), calibración, horizonte,
                      hipótesis de planos, reconstrucción 3D monocular
  js/tracking.js      pirámide gaussiana + Lucas-Kanade + control ida-vuelta
  js/learn.js         descriptores de región + regresión softmax multiclase
  js/exporters.js     proyecto JSON, OBJ+MTL, CSV, dataset portable
  js/ui.js            dibujo del lienzo e interacción con el ratón
  js/app.js           carga de medios, orquestación, paneles, exportaciones
```

Se cargan como **scripts clásicos**, no módulos ES. Es deliberado: los módulos ES no
funcionan desde `file://` por la política de orígenes del navegador, y el requisito es
que la app abra con doble clic sin servidor.

Todo cuelga de un único espacio de nombres, `window.A3D`.

---

## 3. El pipeline, paso a paso

### 3.1 Bordes (`vision.js`)
1. Luminancia Rec.709.
2. Gauss separable, σ ajustable (por defecto 1.4).
3. Sobel 3×3 → magnitud y orientación.
4. Supresión de no-máximos en 4 direcciones.
5. Histéresis con dos umbrales **relativos al máximo del frame** (0.08 / 0.20), no absolutos: así el mismo ajuste sirve para una foto a contraluz y para otra sobreexpuesta.

### 3.2 De píxeles a aristas
El salto de "mapa de bordes" a "lista de aristas" no se hace con Hough sino:
1. **Encadenado 8-conexo** empezando por los píxeles con un solo vecino (extremos), después los bucles cerrados.
2. **Douglas-Peucker** sobre cada cadena para partirla en tramos rectos.

Ventaja sobre Hough: devuelve segmentos con extremos reales (Hough da rectas infinitas
y hay que recortarlas), y no necesita acumulador ni umbral de votos.

### 3.3 Puntos de fuga (`geometry.js`)
RANSAC ponderado por longitud, en cascada:
- Se toman dos segmentos al azar, su intersección homogénea es el candidato.
- Un segmento es *inlier* si el ángulo entre su dirección y la dirección a ese punto es menor que la tolerancia (2.2° por defecto).
- El voto es la **longitud** del segmento, no el número: un muro de 300 px pesa más que diez ruidos de 30 px.
- Se extraen hasta 3 puntos de fuga, quitando los inliers de cada uno antes del siguiente.
- Refinamiento final por iteración inversa de potencia sobre `M = Σ wᵢ lᵢ lᵢᵀ` (el punto de fuga es el autovector mínimo).

### 3.4 Calibración
Para dos puntos de fuga ortogonales finitos y centro óptico en el centro de imagen:

```
(u − pp) · (v − pp) = −f²
```

Se calcula `f` con cada pareja válida y se toma la **mediana**.
De ahí salen las direcciones 3D `dᵢ = normalizar(K⁻¹ vᵢ)` y la vertical del mundo.

### 3.5 Horizonte
Es la línea de fuga del plano horizontal. Se obtiene de dos maneras, por este orden:
1. Recta que une los dos puntos de fuga horizontales (más estable) — necesita 3 vp.
2. `l = K⁻ᵀ · up` a partir de la vertical — **funciona con solo 2 vp**, que es el caso habitual.

*(La versión inicial solo tenía la vía 1 y dejaba el horizonte sin calcular en la mayoría
de las fotos reales. Corregido.)*

### 3.6 Hipótesis de planos
Para cada par de familias de puntos de fuga (i, j):
- Se toman las 9 aristas más largas de cada familia.
- Cada combinación de 2 rectas de i × 2 rectas de j define un cuadrilátero.
- **Puntuación = soporte de borde real**: se recorre cada lado muestreando y se mide qué fracción de las muestras cae a ≤2 px de un píxel de borde. Un cuadrilátero "inventado" por rectas que se cruzan en el cielo puntúa bajo.
- Supresión de solapados por distancia de centroides relativa al área.

Este scorer es el eslabón más débil de la v0.1: ver *Limitaciones*.

### 3.7 Reconstrucción 3D monocular
Con una sola vista hace falta **una restricción de escala**. Se usa la altura de cámara (por defecto 1.60 m, ojo humano; cambiar para dron o trípode: todo el modelo escala proporcionalmente).

- **Plano horizontal (suelo)**: cada píxel se proyecta al plano `X·up = −camH`. Vértices por encima del horizonte se rechazan con mensaje explícito.
- **Plano vertical (fachada, hueco, medianera)**: se anclan los **dos vértices más bajos** al suelo, esos dos puntos definen la recta de base, y el plano vertical que la contiene recibe el resto de vértices por intersección de rayo.
- **Clase de eje libre (cubierta, otro)**: se intenta como vertical y se avisa en el registro.

La clase semántica **decide la geometría**. Por eso etiquetar bien no es cosmético.

### 3.8 Seguimiento (`tracking.js`)
- Pirámide gaussiana de 3 niveles (filtro `[1 4 6 4 1]/16`).
- Lucas-Kanade iterativo con ventana 11×11, rechazo por autovalor mínimo de la matriz de estructura (zonas sin textura no se siguen).
- **Control ida-vuelta**: se sigue A→B y después B→A; si el punto no vuelve a su sitio (>1.6 px) el emparejamiento se descarta.

El control ida-vuelta se añadió tras medir el fallo real: en una fachada con ventanas
repetidas el seguidor "enganchaba" en la ventana contigua y devolvía un resultado
*equivocado pero con residuo bajo*, es decir, un error silencioso. Es preferible perder
un vértice (el usuario lo vuelve a marcar) que arrastrar uno mal colocado por 200 frames.

Un objeto se da por seguido si al menos el 50 % de sus vértices sobrevive.

### 3.9 Aprendizaje (`learn.js`)
**Descriptor de 19 valores por región**, pensado para ser interpretable y no una caja negra:

| # | valor | por qué |
|---|-------|---------|
| 0-2 | R, G, B medios | el hormigón, el ladrillo y el vidrio no comparten color |
| 3 | saturación media | el cielo y el vidrio saturan distinto que el mortero |
| 4-5 | luminancia media y desviación | una cubierta a contraluz vs. una fachada al sol |
| 6 | densidad de borde | el vidrio es liso, el ladrillo no |
| 7-10 | histograma de orientación del gradiente (0/45/90/135°) | textura direccional del despiece |
| 11-12 | centroide x, y normalizado | el suelo cae abajo, la cubierta arriba |
| 13 | área relativa | un hueco es pequeño, una fachada grande |
| 14 | relación de aspecto | ventana apaisada vs. medianera |
| 15 | posición respecto al horizonte | **el descriptor más informativo**: por debajo del horizonte no hay cubiertas |
| 16 | soporte de borde de los lados | distingue plano real de plano inventado |
| 17-18 | fracción de lados verticales / horizontales | orientación del polígono |

**Clasificador**: regresión softmax multiclase entrenada por descenso de gradiente
con L2 y tasa decreciente. Se estandariza cada columna (`z = (f − μ)/σ`).
Con ≥12 muestras reserva el **25 % final como hold-out** y la precisión que muestra es la
de test, no la de entrenamiento.

Por qué softmax y no una red: con 20-100 muestras marcadas a mano una red sobreajusta,
esto no; los pesos se pueden leer e interpretar; entrena en milisegundos sin GPU; y el
modelo entero cabe en un JSON que se lleva a otra app.

---

## 4. Mediciones reales (no estimaciones)

Verificado en Chromium con una escena sintética de edificio en esquina
(dos fachadas de 12 × 11 m, f real 620 px a 800 px de ancho, cámara a 1.60 m, cabeceo 4°):

| prueba | resultado |
|--------|-----------|
| Detección de aristas | 29 segmentos, 2 puntos de fuga, 8 planos candidatos, 260-620 ms a 640 px |
| Focal estimada | 535 px frente a 496 reales → **+8 % de error** |
| Horizonte | y = 275.1 px frente a 274.7 reales → **0.4 px de error** |
| Reconstrucción con calibración exacta, fachada 12 × 11 m | 12.000 × 11.000 m → **error nulo**: la matemática es exacta, el error viene solo de la calibración |
| Reconstrucción del suelo 12 × 12 m | exacta (caja envolvente 16.23 m = 12·(cos28°+sin28°), coherente con el giro de la escena) |
| Lucas-Kanade, desplazamiento 3-12 px | error **0.00 px** en los puntos que pasan el control ida-vuelta |
| Lucas-Kanade, desplazamiento 25 px | 2 de 6 puntos sobreviven; uno de ellos aún con error grande por repetición de ventanas |
| Softmax, 80 muestras / 2 clases separables | 100 % en train y en test |
| Vídeo webm, 73 frames | carga, salto por frame y propagación de un plano anotado: correcto |

**Lectura de estos números**: la cadena geométrica es exacta; el error métrico final es
prácticamente todo error de calibración. Un 8 % en `f` se traduce en un 8 % en las
dimensiones. Mejorar el estimador de puntos de fuga es, por tanto, la palanca con más
retorno del proyecto.

### 4.1 El puerto a Python mejora la calibración (medido el 18/09/2026)

Al portar la geometría a Python sobre OpenCV (ver apartado 11) el error de la focal
**baja del 8 % al 0,6-2,5 %**, medido sobre seis puntos de vista entre 20° y 40°.

| medida | JavaScript | Python / OpenCV |
|---|---|---|
| Error de la focal | 8 % | **0,6 % – 2,5 %** |
| Error del horizonte | 0,4 px (un solo punto de vista) | 1,9 – 8,1 px, media 5,1 |
| Reconstrucción con calibración exacta | exacta | exacta |

La diferencia está en el detector de bordes: el Canny y el trazado de contornos de
OpenCV entregan segmentos más limpios al RANSAC que mi encadenado en JavaScript.

Esto **cumple ya el primer punto de la Fase A** de la hoja de ruta (bajar el error de `f`
por debajo del 3 %) sin necesidad del método de Zhang-Košecká. El cuello de botella se ha
desplazado: ahora el error del horizonte viene de la dirección vertical estimada, no de
la focal. Se comprobó si forzar el horizonte a pasar por el punto de fuga horizontal lo
mejoraba: es la misma recta por construcción, así que por ahí no hay nada que ganar.

---

## 5. Limitaciones conocidas (honestas)

1. **No hay SfM**: cada frame se reconstruye por separado. No se fusionan vistas, no hay nube de puntos, no hay bundle adjustment. Un vídeo sirve hoy para *anotar más rápido*, no para reconstruir mejor.
2. **La escala depende de un dato que teclea el usuario.** Si la altura de cámara está mal, todo el modelo está mal en la misma proporción. No hay forma de detectarlo automáticamente.
3. **El detector de planos propone de más.** Cuadriláteros sobre el cielo o a caballo entre dos fachadas pasan el filtro de soporte. Está pensado como *propuesta que el usuario acepta*, no como salida final.
4. **Fachadas con ventanas repetidas confunden al seguidor** en movimientos grandes. El control ida-vuelta elimina la mayoría de los fallos, no todos.
5. **Sin distorsión de lente.** Se supone cámara pinhole. Un gran angular con barril notable falseará las rectas y, con ellas, los puntos de fuga.
6. **El centro óptico se supone en el centro de la imagen.** Falso en fotos recortadas o con desplazamiento de perspectiva.
7. **No exporta IFC.** Ver hoja de ruta.
8. **El modelo aprendido vive en `localStorage`** del navegador: se pierde al limpiar datos. Hay que exportar el dataset para conservarlo.

---

## 6. Hoja de ruta hacia BIM

**Fase A — precisión de una vista** *(mayor retorno por esfuerzo)*
- [x] ~~Bajar el error de `f` del 8 % a <3 %~~ — **conseguido (0,6-2,5 %)** con el puerto a OpenCV, sin cambiar de método. Ver 4.1.
- [ ] Mejorar la estimación de la dirección vertical, que es ahora el término dominante del error del horizonte.
- [ ] Refinar los cuadriláteros aceptados ajustando sus lados a las aristas reales (snap).
- [ ] Estimar y corregir la distorsión radial con el criterio de "las rectas deben ser rectas".

**Fase B — coherencia temporal**
- [ ] Homografía por RANSAC entre frames consecutivos para inicializar el seguimiento (hoy parte de cero).
- [ ] Fusionar los planos de varios frames: un plano visto en 30 frames debería dar una única entidad, no 30.
- [ ] Ajuste de haces ligero solo sobre los vértices anotados (son pocos: es viable en JS).

**Fase C — topología de edificio**
- [ ] Detectar intersecciones entre planos para generar aristas de encuentro y cerrar volúmenes.
- [ ] Deducir espesor de muro a partir de la profundidad del hueco de ventana (dato que ya se puede marcar).
- [ ] Reglas de consistencia: una fachada acaba en el suelo, una cubierta apoya en fachadas, un hueco está contenido en una fachada.

**Fase D — IFC**
- [ ] Exportar IFC4 (`IfcWallStandardCase`, `IfcSlab`, `IfcWindow` con `IfcExtrudedAreaSolid`).
- No se ha hecho aún a propósito: **un IFC con topología inconsistente es peor que no tener IFC**. Primero la fase C.
- Camino alternativo más rápido: exportar el JSON estructurado actual y convertirlo con *IfcOpenShell* en Python.

---

## 7. Cómo trasladar este trabajo a otra IA

Para que otra herramienta continúe sin contexto, pásale:

1. **Este documento completo** (es autosuficiente).
2. El **dataset**: botón *exportar dataset* → `auto3d_dataset.json`. Contiene los descriptores, sus nombres, las etiquetas y los pesos entrenados. Formato documentado dentro del propio archivo.
3. El **proyecto**: botón *guardar proyecto* → `auto3d_proyecto.json`. Contiene objetos, keyframes y parámetros.

Prompt sugerido:

> Trabajo en AUTO3D, una app HTML/JS sin dependencias que extrae aristas, puntos de fuga
> y planos de fotos y vídeos de edificios para llegar a un modelo BIM. Te paso el cuaderno
> de conocimiento con la arquitectura, las mediciones y las limitaciones. Quiero que
> trabajes en [FASE / TAREA]. Respeta: sin dependencias externas, sin módulos ES (debe
> abrir desde file://), todo el procesado en cliente, y no toques el formato de
> `auto3d_dataset.json` sin subir su número de versión.

---

## 8. Convenios para no romper nada

- **Coordenadas**: las anotaciones se guardan en píxeles de la **imagen original**. El pipeline trabaja a resolución reducida (`params.proc`, 640 px por defecto); el factor está en `detection.scale`. Multiplicar para ir a espacio de proceso, dividir para volver.
- **Cámara**: modelo pinhole, `rayo = [x − cx, y − cy, f]`, con y de imagen hacia abajo. La vertical del mundo `up` se guarda con componente y negativa.
- **Keyframe vs. seguimiento**: `obj.keys[frame]` es verdad marcada por el usuario; `obj.track[frame]` es caché del seguidor. `A3D.objAt()` resuelve la prioridad: clave → seguido → interpolado entre claves → extrapolado al más cercano. Marcar una clave borra el seguimiento de ese frame.
- **Versionado del dataset**: si cambia el número o el orden de los descriptores, subir `version` en `learn.js` y en `exporters.js`. Los modelos guardados con otro tamaño de descriptor se descartan al cargar (ya implementado).

---

## 10. La otra línea de trabajo: AUTO3D (Python, ChatGPT)

Analizado el 18/09/2026 a partir de `AUTO3D_codigo.zip` (733 líneas de Python).

### Qué es
App de escritorio **Python + PyQt6 + OpenCV + scikit-learn**, empaquetada como `.exe`
con PyInstaller. Arquitectura: `app.py` (arranque y bloqueo de sesión),
`vision_teach/{ui,engine,detection,learning,storage,migration}.py`, más 211 líneas de tests.

### El hallazgo importante: las dos apps aprenden cosas distintas

Esto no es un solapamiento, es una división del trabajo que encaja:

| | AUTO3D (Python) | AUTO3D_claude (HTML) |
|---|---|---|
| **Qué aprende** | **cómo mirar**: un Random Forest predice los umbrales de Canny y la tolerancia de color a partir del contexto de la imagen | **qué está mirando**: un softmax clasifica la región como fachada, suelo, cubierta, hueco… |
| Supervisión | débil e indirecta: de la región que marcas se *mide* el contraste y la dispersión de color, y eso se usa como objetivo | directa: la clase que tú eliges es la etiqueta |
| "Arista" significa | contorno de Canny de ≥12 px (no necesariamente recto) | segmento recto con extremos, agrupado por punto de fuga |
| "Plano" significa | región de color parecido en espacio Lab (2D) | cuadrilátero sostenido por aristas reales, con normal 3D |
| Geometría 3D | **ninguna** | puntos de fuga, focal, horizonte, reconstrucción métrica |
| Seguimiento entre frames | **ninguno**: se reanota cada fotograma | Lucas-Kanade + keyframes interpolables |
| Navegación de vídeo | solo hacia delante (`capture.read()`), no se puede retroceder | salto libre a cualquier fotograma |
| Editar una anotación | solo *deshacer la última* | arrastrar cualquier vértice en cualquier fotograma |
| Persistencia | **muy sólida**: JSON atómico, identidad del archivo por SHA-256, bloqueo de sesión, registro de auditoría en Markdown en hilo aparte | débil: `localStorage` + exportación manual |
| Tests | 211 líneas (persistencia, vídeo, aprendizaje, Qt) | verificación en navegador, sin suite automatizada |
| Camino a IFC | abierto (IfcOpenShell es Python) | cerrado (no existe en JS) |

### Lo que hay que copiarle sí o sí

1. **Calibración automática de filtros.** Mis umbrales de Canny son deslizadores que el usuario toca a ciegas; los suyos se aprenden de las propias marcas del usuario. Es una idea mejor que la mía y es portable a JS: el descriptor de contexto son 10 valores (media y desviación Lab + percentiles 25/50/75/90 del gradiente) y el modelo puede ser una regresión en lugar de un Random Forest.
2. **Identidad del archivo por SHA-256.** Reabres el mismo vídeo aunque lo hayas renombrado y recuperas tus marcas. Yo pierdo todo si no exporto el proyecto a mano.
3. **Escritura atómica y registro de auditoría.** Escribir a temporal y `os.replace`; nunca sobrescribir un dataset ilegible con uno vacío.
4. **Espacio Lab** para la similitud de color, en lugar del RGB/HSV que uso yo.
5. **Entrenar antes de confirmar**: si el entrenamiento falla, no se ha guardado nada a medias.

### Lo que le falta para el objetivo BIM

Su propio README lo dice sin adornos: *"no infiere planitud física, profundidad ni
geometría 3D"*. Sus planos son manchas de color. Sin puntos de fuga, sin calibración de
cámara y sin reconstrucción no hay camino a BIM, por buena que sea la ingeniería del resto.
Tampoco tiene seguimiento entre fotogramas, que es un requisito explícito del proyecto.

### Conclusión

La ingeniería de la app Python es mejor que la mía. La visión geométrica de la mía no
existe en la suya. El destino natural es **un motor Python** (OpenCV + scikit-learn +
IfcOpenShell para el IFC final) **con la geometría de AUTO3D_claude portada a él**, y la
interfaz HTML como capa de anotación sobre un servidor local — que ya tiene un
`iniciar.cmd` donde encajarlo.

---

## 11. El puente: geometría portada a Python

Carpeta `AUTO3D_claude/python/`. Son módulos pensados para **añadirse a la app de
ChatGPT**, no para sustituirla:

```
vision_teach/geometry.py           puntos de fuga, calibración, planos, 3D  (387 líneas)
vision_teach/geometry_overlay.py   puente: analizar, dibujar, medir          (82 líneas)
vision_teach/tracking.py           seguimiento con control ida-vuelta        (71 líneas)
tests/test_geometry.py             22 pruebas contra verdad conocida
tests/scene.py                     generador de escena sintética
INTEGRACION.md                     los cambios exactos a hacer en su app
```

Decisiones de diseño:

- **Sin dependencias nuevas.** Solo numpy y OpenCV, ya presentes en su `requirements.txt`.
- **Se reutilizan sus umbrales aprendidos.** `analyse()` recibe el diccionario que
  devuelve su `Learner.parameters`, de modo que lo que el Random Forest aprende calibra
  también la geometría. Es la unión real entre las dos líneas, no una convivencia.
- **`geometry.py` no dibuja.** La matemática se prueba sin pintar y el dibujo se cambia
  sin tocar la matemática.
- **`cv2.calcOpticalFlowPyrLK`** sustituye a mis 150 líneas de Lucas-Kanade en JavaScript.
  El control ida-vuelta sí se conserva: es lo que evita el emparejamiento equivocado con
  residuo bajo en fachadas de ventanas repetidas.
- **Las marcas propagadas por seguimiento no deben entrar en el dataset de
  entrenamiento.** Si una marca seguida se usa como ejemplo, el modelo se entrena con su
  propia salida y se realimenta. Queda avisado en `INTEGRACION.md`.

Lo que hace falta en su interfaz y no está aquí porque es su terreno: retroceder en el
vídeo (`CAP_PROP_POS_FRAMES`), arrastrar un vértice ya guardado, y elegir la clase del
elemento (fachada / suelo / cubierta / hueco / medianera) al marcar una superficie. Sin
esa clase no hay BIM: es la que decide si un polígono se apoya en el terreno o se levanta
vertical sobre su base.

---

## 9. Registro

### 2026-09-18 — v0.1, primera versión funcional (Claude)
Creado desde cero en `AUTO3D_claude`. Implementados: Canny propio, encadenado +
Douglas-Peucker, RANSAC de puntos de fuga con refinamiento, calibración, hipótesis de
planos por soporte de borde, reconstrucción monocular, Lucas-Kanade piramidal,
descriptor de 19 valores, softmax con hold-out, exportadores (proyecto, OBJ+MTL, CSV,
dataset), interfaz con modos AUTO/LEARN, línea de tiempo y keyframes.

Errores encontrados y corregidos durante la verificación en navegador:
- Una variable `acc` tapaba a la función `acc()` en el entrenamiento (hoisting de `var`): el entrenamiento reventaba siempre. Renombrada a `accuracy`.
- El horizonte exigía 3 puntos de fuga y quedaba sin calcular en el caso normal de 2. Añadida la vía `l = K⁻ᵀ·up`.
- El seguidor devolvía emparejamientos equivocados con residuo bajo en fachadas repetitivas. Añadido control ida-vuelta.
- Con 8-10 planos candidatos rellenos, el lienzo tapaba la foto. Ahora solo se rellena el candidato bajo el ratón.

Pendiente inmediato: fusionar con la línea de trabajo paralela de ChatGPT en `AUTO3D`.

### 2026-09-18 — Análisis de la línea Python de ChatGPT
Leído `AUTO3D_codigo.zip` completo. Documentada la comparación en el apartado 10.
Conclusión: las dos apps aprenden cosas distintas y complementarias (calibración de
filtros frente a semántica + geometría). Pendiente la decisión del usuario sobre cómo
unificar las dos líneas.

### 2026-09-18 — Geometría portada a Python para la app de ChatGPT
Escritos `geometry.py`, `geometry_overlay.py` y `tracking.py` más 22 pruebas. Se enchufan
a su aplicación sin dependencias nuevas y sin tocar su interfaz, su persistencia ni su
empaquetado. Reparto: ellos la ingeniería que ya funciona, yo la geometría.

Hallazgos de la verificación:
- La focal pasa de un 8 % de error en JavaScript a un 0,6-2,5 % en OpenCV. Queda cumplido el primer objetivo de la Fase A sin cambiar de método.
- La escena sintética de prueba tenía un defecto: el suelo se dibujaba envolviendo la cámara y tapaba el cielo, porque no se comprobaba que los vértices estuvieran delante del objetivo. Corregido; las cifras de detección anteriores a esa corrección no son válidas.
- Descartada una mejora del horizonte (forzarlo a pasar por el punto de fuga horizontal): es la misma recta por construcción. Resultado negativo, anotado para no repetirlo.
