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

## 12. Datos reales: fotos de dron de un pueblo (18/09/2026)

El usuario aporta cinco fotos de dron de un pueblo, "representativas de cómo serán los
datos". Cambian el diagnóstico del proyecto, así que se documentan las mediciones.

### Lo que se midió sobre las fotos reales

| foto | segmentos | vp | focal estimada (normalizada a 1000 px de ancho) | campo |
|---|---|---|---|---|
| 3 (casi cenital) | 449 | 3 | 3051 px | 31° |
| 4 (oblicua) | 478 | 3 | **714 px** | 70° |
| 5 (casi cenital) | 756 | 3 | 3051 px | 19° |
| 6 (oblicua) | 573 | 3 | **605 px** | 79° |
| 7 (casi cenital) | 459 | 3 | 2224 px | 25° |

**Es la misma cámara en las cinco.** Que la focal estimada varíe de 605 a 3051 px
demuestra por sí solo que la calibración no es fiable en este material. Recortar un solo
edificio tampoco lo arregla: sobre recortes individuales el rango sigue siendo 807-2435.

### Por qué falla: medido, no supuesto

Barrido sobre la escena sintética de verdad conocida, subiendo la cámara e inclinándola
para mantener el edificio centrado (focal real 620 px):

| altura | picado | segmentos | error de focal |
|---|---|---|---|
| 1,6 m | −12° | 78 | 1,6 % |
| 6 m | 4° | 79 | **0,2 %** |
| 12 m | 24° | 78 | 1,2 % |
| 20 m | 43° | 118 | 1,3 % |
| 35 m | 62° | 111 | 2,9 % |
| 60 m | 74° | 29 | **68,7 %** |
| 100 m | 80° | 15 | 58,7 % |

**El método aguanta hasta unos 60° de picado y se derrumba a partir de 70°.** La causa es
geométrica, no un fallo de implementación: cuanto más cenital es la toma, menos fachada se
ve. Sin aristas verticales visibles nada sujeta la dirección vertical, y además las líneas
del suelo se vuelven casi paralelas en la imagen, con lo que su punto de fuga se va al
infinito y la fórmula `(u−pp)·(v−pp) = −f²` queda malcondicionada: pequeños errores en la
posición del punto de fuga producen errores enormes en `f`.

La escena sintética exagera la caída de segmentos porque el edificio de prueba no tiene
cubierta modelada. En las fotos reales ocurre lo contrario y es más engañoso: hay **muchos**
segmentos (756 en la foto 5), pero son todos aristas de cubierta en orientaciones diversas
y apenas hay verticales. Muchos datos, ninguna restricción útil.

### Lo que funciona bien

La extracción de aristas rectas. Sobre las fotos reales encuentra limpiamente los
caballetes, los aleros y los bordes largos de las naves. Ese detector es un activo que
sirve en cualquier camino que se tome después.

### Lo que no funciona

Los planos candidatos. Están pensados para **un edificio que llena el encuadre**; en la
vista de un pueblo generan cuadriláteros enormes que unen el alero de una casa con el
borde de una carretera cincuenta metros más allá. No es cuestión de ajustar el umbral.

### Consecuencia para el proyecto

Para material aéreo de varios edificios, la reconstrucción monocular de una vista no es
la herramienta. Lo que pide este dato es **fotogrametría multivista** (SfM + MVS: OpenDroneMap,
COLMAP, Metashape, Pix4D), que resuelve calibración, poses y escala con el GPS del EXIF, y
entrega nube de puntos, MDS y ortofoto. A partir de ahí:

1. Huellas de edificio desde el modelo digital de superficies y la ortofoto.
2. **Planos de cubierta por ajuste RANSAC en 3D sobre la nube** — aquí "plano" sí es un plano, ni una mancha de color ni un cuadrilátero inventado.
3. Semántica (cubierta, fachada, buhardilla, chimenea): **aquí es donde el modo LEARN tiene su valor real**, aplicado a segmentos 3D en vez de a píxeles.
4. IFC con IfcOpenShell.

La geometría monocular sigue siendo útil para **tomas oblicuas de un edificio concreto**
(las fotos 4 y 6 caen en ese rango), como complemento, no como vía principal.

### El EXIF es la pieza que falta

Las copias subidas por el chat llegan **sin EXIF y redimensionadas a 1500×1124**. Comprobado
a nivel de bytes: no hay marcador APP1, solo JFIF e ICC. La información no se puede
recuperar de esas copias, hay que partir de los originales.

Y es decisiva, porque los tres datos que el sistema estima mal vienen dados en el original:

| dato | hoy | en el EXIF/XMP del original |
|---|---|---|
| Focal | se estima, con 605-3051 px de dispersión | `FocalLength` + tamaño de sensor → exacta |
| Escala | altura de cámara tecleada a mano | `RelativeAltitude` del XMP de DJI |
| Dirección vertical | se estima del punto de fuga vertical | `GimbalPitchDegree`, `GimbalRollDegree` |

Con esos tres valores **no hay que calibrar nada**, y el problema del picado desaparece.

---

## 13. Anotación multivista: marcar deja de ser seguir

Escrito el 18/09/2026, tras saber que los datos son de un **DJI Matrice 4E** con solape
del 70 % horizontal y 80 % vertical, y que el objetivo principal es **un edificio
concreto**.

### El cambio de concepto

La propuesta del usuario era marcar el contorno en el primer fotograma y en varios más, y
que el programa lo siguiera. Con las posiciones de cámara conocidas hay una versión mucho
mejor de esa misma idea:

| | seguimiento (`tracking.py`) | triangulación (`multiview.py`) |
|---|---|---|
| Qué hace | arrastra la marca de una foto a la siguiente | corta los rayos de dos o más marcas |
| Error | se acumula en cadena | **no se acumula**: cada punto es independiente |
| Necesita | movimiento pequeño entre tomas | **ángulo grande** entre tomas |
| Da | una marca 2D en otra foto | **un punto 3D en metros** |
| Sirve para | vídeo | fotos de una misión con solape |

Con solape del 70 % el salto entre fotos consecutivas es grande, que es justo lo que el
seguimiento lleva peor y lo que la triangulación lleva mejor. Y a la inversa: sabiendo el
punto 3D, se sabe dónde cae en **todas** las fotos sin seguir nada.

### Cuánto error, medido

Edificio de 20 × 10 m y 11 m de alto, dron a 45 m, vuelo circular de 60 m de radio, foto
de 4000 px. Error mediano en la posición 3D según en cuántas fotos se marca y con cuánta
precisión se pincha con el ratón:

| marcas | 1 px | 2 px | 4 px | 8 px |
|---|---|---|---|---|
| 2 | 4,7 cm | 9,3 cm | 19,2 cm | 36,8 cm |
| 3 | 2,8 cm | 5,5 cm | 10,7 cm | 21,4 cm |
| 4 | 2,3 cm | 5,0 cm | 9,7 cm | 19,0 cm |
| 6 | 1,9 cm | 4,1 cm | 8,1 cm | 15,8 cm |
| 8 | 1,7 cm | 3,2 cm | 6,8 cm | 13,8 cm |

**Con marcar en tres fotos con precisión normal de ratón se obtienen 5 cm**, que sobra
para LOD2 y llega para LOD3.

### El ángulo importa mucho más que el número de fotos

Dos marcas, 2 px de error, variando el ángulo entre las dos tomas:

| ángulo | error |
|---|---|
| 2° | **326 cm** |
| 5° | 139 cm |
| 10° | 67 cm |
| 20° | 33 cm |
| 45° | 15 cm |
| 90° | 9,5 cm |
| 120° | 7,9 cm |

Dos tomas separadas 90° dan 9,5 cm; las mismas dos marcas en tomas separadas 2° dan más de
3 metros. **Un factor 35.** Marcar en fotos consecutivas de una misión es casi inútil.

**Regla de diseño para la interfaz, que se deriva de esto**: cuando el usuario marca algo
en una foto, el programa **no** debe ofrecerle la siguiente, sino la toma *más separada
angularmente* que siga viendo ese elemento. Y debe enseñar el error de reproyección de cada
marca: si una reproyecta a 40 px, esa marca está mal puesta y hay que rehacerla.

### Los módulos

```
vision_teach/multiview.py    Camera con pose, triangulación con refinado no lineal,
                             error de reproyección, propagación a todas las fotos,
                             ajuste de planos por RANSAC e inclinación del plano
vision_teach/colmap.py       lectura de cameras.txt / images.txt de COLMAP y ODM
tests/test_multiview.py      14 pruebas
tests/test_colmap.py         4 pruebas, incluida la ida y vuelta del cuaternión
```

`fit_plane` ajusta planos **de verdad**, a puntos 3D. Y `plane_angle` da su inclinación:
0° horizontal, 90° fachada, y los valores intermedios son faldones de cubierta — que es lo
que domina en una foto de dron y lo que la geometría monocular no sabía tratar.

El DLT se refina siempre con Gauss-Newton sobre el error de reproyección: el DLT minimiza
un residuo algebraico que no es el error en píxeles, y sin refinar una vista muy oblicua
sesga el resultado.

---

## 14. Telemetría de vuelo: el `.SRT` de DJI (18/09/2026)

Confirmado con material real del usuario: los vídeos del dron llevan al lado un `.SRT`
con **una entrada por fotograma**. Es el equivalente del EXIF para vídeo.

### Qué trae y qué no

Campos presentes en los dos archivos analizados:
`iso`, `shutter`, `fnum`, `ev`, `ct`, `color_md`, `focal_len`, `dzoom_ratio`, `delta`,
`latitude`, `longitude`, `rel_alt`, `abs_alt`.

**No trae los ángulos del gimbal.** No es fatal: la fotogrametría calcula la orientación
por su cuenta. Pero conviene no contar con ellos.

### Dos vuelos reales, dos resultados opuestos

| | DJI_0776 | DJI_0783 |
|---|---|---|
| Fotogramas | 59 (2,0 s) | 478 (15,9 s) |
| Recorrido | **0,0 m** | 70,3 m |
| Posiciones GPS distintas | **1 de 59** | 149 de 478 |
| Altura | 93,8 m constante | 93,0 → 53,3 m |
| Ángulo barrido | **0°** | **39°** |
| ¿Sirve? | **No** | Sí |

El primero es el dron **parado en el aire**. Dos segundos de vídeo 4K perfectamente
nítido y **completamente inútil para reconstruir**: sin desplazamiento no hay paralaje y
no hay nada que triangular. El criterio que importa no es la duración ni la resolución,
es el **recorrido**.

El segundo sí sirve: 70 m recorridos descendiendo de 93 a 53 m, con 39° barridos sobre el
terreno. Según la tabla del apartado 13, 39° entre dos tomas da del orden de 15-20 cm; con
más tomas baja.

### Cuántos fotogramas extraer

De los 478 fotogramas de DJI_0783 no hay que usar 478. Entre fotogramas consecutivos el
dron se ha movido centímetros y la base es demasiado corta:

| separación | fotogramas |
|---|---|
| cada 2 m | 31 |
| cada 5 m | 14 |
| cada 10 m | 7 |

**Se selecciona por metros recorridos, no por tiempo.** `dji.select_frames` hace eso.

### La focal, y por qué sigue haciendo falta el EXIF

`focal_len : 240` es constante en los dos vuelos, y `dzoom_ratio : 10000` significa zoom
1×. Interpretando 240 como **24,0 mm equivalentes a 35 mm**, en un fotograma 4K de 3840 px
salen **2560 px de focal**.

Ese "interpretando" es el problema: **si DJI escribiera ahí la focal real en vez de la
equivalente, el valor estaría mal y con él toda la escala.** Se resuelve mirando el EXIF de
una foto del mismo equipo, donde `FocalLength` y `FocalLengthIn35mmFilm` aparecen por
separado. Sigue siendo el dato pendiente.

### El módulo

`vision_teach/dji.py` con 12 pruebas. Lee el `.SRT`, da coordenadas locales en metros,
resume el vuelo diciendo **si sirve o no y por qué**, selecciona fotogramas por distancia y
calcula el ángulo barrido.

Un detalle del formato real que rompió la primera versión: DJI mete **varios campos en un
mismo corchete** — `[rel_alt: 93.800 abs_alt: 1048.861]` — así que hay que aislar cada
grupo y después leer todos sus pares. Y los pares no se pueden buscar sobre la línea
entera, porque la marca de tiempo `23:04:58.522` se leería como un campo llamado `23`.

### Consecuencia práctica para volar

Para un edificio concreto, **órbita alrededor**. Los 39° de DJI_0783 salieron de un
descenso en línea; una órbita completa daría 360° y mucha mejor triangulación. Y las
fotos sueltas siguen siendo mejores que el vídeo por una razón: conservan el EXIF.

---

## 15. Una foto original: todo lo que faltaba (18/09/2026)

`CCO_Pedraza_2024.zip` → `DJI_0763.JPG`, 22 MB, **8064 × 6048** (48,8 Mpx), con EXIF y XMP
intactos. Es la primera foto original recibida y resuelve varias incógnitas.

### El dron no es el que creíamos

`drone-dji:DroneModel = Mini 3 Pro`, cámara `FC3582`. El usuario había dicho **Matrice
4E**. O tiene los dos aparatos, o las fotos del pueblo salieron de otro vuelo. **Hay que
preguntárselo**: el modelo condiciona el sensor y con él la escala.

### Confirmada la lectura de la focal del vídeo

| EXIF | valor |
|---|---|
| `FocalLength` | 6,72 mm |
| `FocalLengthIn35mmFilm` | **24** |
| `FNumber` | 1,7 (coincide con `fnum: 170` del SRT) |
| `DigitalZoomRatio` | 1,0 |

`focal_len : 240` del `.SRT` **son 24,0 mm equivalentes**, como se había supuesto. La
interpretación era correcta.

### Pero queda un 4 % sin resolver

`FocalLengthIn35mmFilm` puede referirse al **ancho** de un fotograma de 35 mm (36 mm) o a
su **diagonal** (43,27 mm). Según cuál sea:

| convención | focal | GSD a 78 m | huella |
|---|---|---|---|
| horizontal | 5376 px | 14,51 mm/px | 117,0 × 87,8 m |
| diagonal | 5591 px | 13,95 mm/px | 112,5 × 84,4 m |

**Un 4 % de diferencia, que va directo a todas las medidas.** Una sola foto no permite
decidir. Se resuelve de dos maneras: midiendo una distancia conocida en el terreno, o
dejando que la fotogrametría ajuste la focal con muchas imágenes. Por eso `photo.py`
**exige la convención como parámetro explícito** en vez de esconder una suposición.

Se intentó resolverlo midiendo objetos de la propia foto y **no se consiguió**: los coches
son clásicos de un concurso de elegancia, con medidas que no se pueden dar por sabidas, y
el ajuste automático del ruedo circular salió con circularidad 0,43 porque la segmentación
por color se lleva también los prados de alrededor. No se da ningún número de esos: una
medida que no se puede defender es peor que ninguna.

### Las fotos sí traen los ángulos del gimbal

Lo que le falta al `.SRT` del vídeo está en el XMP de las fotos:

```
GimbalPitchDegree = -90.00     GimbalYawDegree = +67.50     GimbalRollDegree = +0.00
FlightPitchDegree = -0.30      FlightYawDegree = +73.40     FlightRollDegree = +0.70
RelativeAltitude  = +78.000    AbsoluteAltitude = +1101.840
GpsLatitude = +40.857202170    GpsLongitude = -4.133570191
GpsStatus = Invalid            SurveyingMode = 0            AltitudeType = RtkAlt
```

**`GimbalPitchDegree = -90` confirma el diagnóstico del apartado 12**: es una toma
perfectamente cenital, justo el caso donde la calibración monocular por puntos de fuga se
derrumba. No era mala suerte: es como vuela.

`GpsStatus = Invalid` (y `GPSStatus = V` en el EXIF) conviene verificarlo con el usuario.
Las coordenadas son plausibles —Pedraza, Segovia— pero si el GPS no tenía solución válida,
la posición absoluta no es fiable.

### Consecuencia: se puede triangular sin fotogrametría

Con posición, altura y los tres ángulos del gimbal, **una foto suelta ya da una cámara con
pose completa**. Dos fotos de un edificio bastan para triangular, sin instalar COLMAP.

`vision_teach/photo.py` hace eso. Verificado sobre la foto real:

| comprobación | resultado |
|---|---|
| Eje óptico en toma cenital | (0, 0, −1) exacto |
| Punto del suelo bajo el dron | cae en el centro exacto de la imagen |
| 20 m sobre el terreno | 1378,5 px, exactamente lo predicho |

Es una pose **aproximada**: la limita la precisión del GPS, del orden de metros sin RTK.
Sirve para arrancar, para descartar tomas inútiles y para dar medidas con su
incertidumbre. La fotogrametría después la refina.

### Por qué las fotos son mejores que el vídeo

| | foto | vídeo |
|---|---|---|
| Posición y altura | sí | sí (`.SRT`) |
| **Ángulos del gimbal** | **sí** | **no** |
| Resolución | 48,8 Mpx | 8,3 Mpx (4K) |
| Pose sin fotogrametría | **sí** | no |

---

## 16. ¿Hacen falta la fotogrametría y el RTK? Medido (18/09/2026)

El usuario aclara que vuela **los dos drones, sobre todo el Matrice 4E**. Como ese es un
equipo de topografía y probablemente lleva RTK, la pregunta pasa a ser concreta: **¿basta
con la pose que viene en los metadatos, o hay que pasar por fotogrametría?**

Simulación sobre el edificio de 20 × 10 × 11 m, seis tomas en órbita de 60 m, marcado con
2 px de error.

### Posición absoluta de un punto

| precisión GPS | gimbal exacto | gimbal 0,5° | gimbal 1,0° | gimbal 2,0° |
|---|---|---|---|---|
| RTK 2 cm | **0,04 m** | 0,52 m | 1,01 m | 1,94 m |
| RTK 5 cm | 0,05 m | 0,50 m | 0,95 m | 1,91 m |
| GPS 0,5 m | 0,42 m | 0,62 m | 1,05 m | 1,88 m |
| GPS 1,5 m | 1,08 m | 1,28 m | 1,51 m | 2,32 m |
| GPS 3 m | 2,33 m | 2,38 m | 2,55 m | 3,12 m |

**El término dominante no es el GPS, es el ángulo del gimbal.** Con RTK perfecto y 1° de
error angular el resultado empeora 25 veces. Es puro brazo de palanca: a 60 m de
distancia, 1° son 1,05 m, y la tabla da 1,01 m. No hay nada que ajustar, es geometría.

### Pero lo que pide el BIM son dimensiones, no coordenadas

Medir **un lado de 20 m del edificio**, que es lo que de verdad importa:

| caso | error en 20 m | relativo |
|---|---|---|
| poses perfectas | 0,028 m | 0,1 % |
| RTK 2 cm + gimbal 0,5° aleatorio | 0,053 m | **0,3 %** |
| RTK 2 cm + gimbal 1,0° aleatorio | 0,111 m | **0,6 %** |
| RTK 2 cm + gimbal 1,0° sistemático | 0,094 m | 0,5 % |
| GPS 1,5 m + gimbal 1,0° aleatorio | 0,269 m | 1,3 % |
| GPS 1,5 m + gimbal 1,0° sistemático | 0,096 m | 0,5 % |

El error de posición absoluta **se cancela casi entero al medir una distancia entre dos
puntos próximos**: los dos se desplazan en el mismo sentido. Un error de 1 m en la
posición del edificio deja la medida de sus 20 m en 11 cm.

Se ve también por qué distinguir el error **sistemático** del **aleatorio**: con GPS de
1,5 m, si la desviación es común a todas las tomas el error en la medida baja de 1,3 % a
0,5 %. Un desplazamiento igual para todas las cámaras no deforma nada.

### Conclusión, que corrige lo dicho en el apartado 15

Aquella afirmación —"con el XMP ya se puede triangular sin fotogrametría"— era **cierta a
medias**, y conviene precisar cuál:

- **Para medir un edificio: sí.** Con RTK y un gimbal razonable, del 0,3 % al 0,6 %, o sea
  de 5 a 11 cm en 20 m. Suficiente para LOD2 y para LOD3.
- **Para situarlo en el mundo: no.** Metros de error, que vienen del gimbal.
- **La fotogrametría sigue ganando** porque refina las orientaciones a partir de las
  propias imágenes, que es justo lo que los metadatos no pueden dar. Pero deja de ser
  imprescindible para arrancar.

### Consecuencia práctica

El **Matrice 4E con RTK es el equipo adecuado**, y no tanto por el GPS como parece: el RTK
por sí solo no arregla nada si el gimbal va a 1°. Lo que más conviene vigilar es la
**calibración del gimbal**.

Pendiente: una foto original del Matrice 4E, para confirmar que su XMP trae los mismos
campos y ver si añade los de RTK (`RtkFlag`, `RtkStdLon`, `RtkStdLat`, `RtkStdHgt`), que
permitirían conocer la precisión real de cada toma en vez de suponerla.

---

## 17. El vuelo bueno: RTK, órbita y 1479 disparos (18/09/2026)

El usuario aporta los archivos auxiliares RTK/PPK de un vuelo del Matrice 4E:
`.MRK`, `.RTK`, `.NAV` y `.pbk`. Es, con diferencia, el mejor material recibido.

### Qué es cada archivo

| archivo | contenido |
|---|---|
| `.MRK` | **una línea por disparo**: posición RTK en el instante exacto de la exposición, con su desviación típica. Lo importante. |
| `.NAV` | efemérides en RINEX 3.05 |
| `.RTK` | observaciones crudas del receptor, en formato propio de DJI (no empieza por `0xd3`, así que **no es RTCM3**) |
| `.pbk` | 29 bytes: solo el nombre del `.RTK` |

Formato de una línea del `.MRK`:

```
1  301666.905683  [2360]  54,N  162,E  84,V
   40.33554262,Lat  -3.87508693,Lon  716.819,Ellh
   0.118401, 0.105962, 0.212182  50,Q
```

disparo · segundo de la semana GPS · [semana] · brazo de antena en mm (N, E, V) ·
latitud · longitud · altura elipsoidal · **desviación típica en m (N, E, V)** · indicador.

### El vuelo 0002, medido

| | |
|---|---|
| Disparos | **1479** en 14,1 min, uno cada 0,55 s (1 sin foto) |
| Recorrido | 1028 m en una extensión de solo 45 × 74 × 7,3 m |
| Ángulo barrido | **167°** |
| Acimut cubierto | **100 % de los doce sectores** |
| Distancia al centro | 6,2 a 42 m (mediana 20) |
| Precisión mediana | **N 5,3 cm · E 4,3 cm · V 6,5 cm** |
| Peor caso | N 11,8 · E 10,6 · V 21,2 cm |
| Indicador | 50 en los 1479 |

Es una **órbita cerrada y cercana** alrededor de un edificio, con posiciones a nivel de
centímetros. Es exactamente el vuelo que hacía falta y que en el apartado 16 se pedía.

Con esta geometría y esta precisión, una fotogrametría en condiciones da un modelo de
edificio a nivel centimétrico. El cuello de botella del apartado 16 —el ángulo del
gimbal— **desaparece**, porque el ajuste de haces recalcula las orientaciones desde las
propias imágenes.

### El ángulo barrido no basta: hace falta el acimut

Lo descubrió una prueba que fallaba. Una **pasada recta larga barre 35°** y una **órbita
cerrada 31°**, y sin embargo la recta ve el edificio siempre desde el mismo lado y deja
caras sin cubrir.

El ángulo dice **cuánta base** hay; el acimut dice **si esa base rodea al objeto**. Hacen
falta los dos, y `flights.py` no tenía el segundo hasta que la prueba lo destapó.

### El brazo de antena queda sin resolver, a propósito

El `.MRK` trae la corrección antena-cámara: 54, 162 y 84 mm. Son unos 15 cm, **del mismo
orden que la precisión**, así que aplicarla cuando ya está aplicada, o no aplicarla cuando
toca, cambia el resultado de forma apreciable. No está confirmado qué entrega DJI.

`mrk.positions` lo deja **desactivado por defecto** y obliga a pedirlo. Se resuelve con una
comprobación concreta: comparar una línea del `.MRK` con la latitud y longitud del XMP de
esa misma foto. Si difieren en el brazo, el `.MRK` da la posición de la antena.

### Los módulos

```
vision_teach/mrk.py        lectura del .MRK, precisión por disparo, acimut,
                           emparejado con las fotos por numero de disparo  (12 pruebas)
vision_teach/flights.py    informe de una campaña desde el CSV de metadatos (10 pruebas)
AUTO3D_metadatos.ps1       extractor para Windows: recorre una carpeta, lee solo
                           los primeros 128 KB de cada foto y escribe un CSV de KB
```

El emparejado foto-disparo **va por número de disparo, no por posición en la lista**: en
este vuelo falta un disparo, y emparejar por orden habría desplazado todo lo que viene
detrás.

---

## 18. Explorador de carpetas: 5346 fotos reales analizadas (19/09/2026)

El usuario ejecuta el extractor sobre `E:\005 Territorio Mudejar` y aporta el CSV:
**5346 fotos con coordenadas, 57 vuelos**. Es el primer retrato completo del material.

### Lo que hay

| | |
|---|---|
| Dron | **M4E** (Matrice 4E), cámara `WideCamera` |
| Posicionamiento | `GpsStatus=RTK`, `AltitudeType=RtkAlt`, `SurveyingMode=1` |
| Precisión | de **2 mm** a 13 cm según el vuelo |
| Sitios | Zuera, Zuera ruinas, morat… (Aragón) |

### Los mejores vuelos

| carpeta | fotos | GB | gimbal | recorrido | ángulo | acimut | RTK |
|---|---|---|---|---|---|---|---|
| `049_LiveMissionRec` | 337 | 2,4 | −60…35° | 1492 m | **171°** | 100 % | 8,3 cm |
| `053_Nuevarutadecaptura` | 747 | 6,1 | −90…17° | 553 m | 149° | 100 % | 7,1 cm |
| `048_Nuevarutadecaptura` | **1380** | 10,0 | −90…19° | 976 m | 146° | 100 % | 6,0 cm |
| `044_zuera002` | 212 | 1,5 | −90…−60° | 1020 m | 125° | 100 % | **2,0 cm** |
| `061_morat001` | 249 | 1,7 | −90…−60° | 425 m | 112° | 100 % | **0,2 cm** |

Varios son **mixtos —cenital más oblicuo—, que es la combinación ideal**: cubiertas y
fachadas en el mismo vuelo.

### Dos errores que solo destapó el material real

**1. El umbral del cielo estaba mal.** Dos vuelos (`058` y `059`, 698 fotos y 4,4 GB) tienen
el gimbal fijo en **−9°** y mi clasificador los llamaba *"apunta al cielo: poco
aprovechable"*. Pero −9° es casi horizontal, que es **precisamente la mejor toma para una
fachada alta**. El umbral estaba en −10° cuando debía estar en 0: solo es cielo lo que
apunta por encima de la horizontal. Corregido, y añadida la categoría *"casi horizontal:
fachada de frente"*.

**2. El ángulo barrido dependía de una suposición escondida.** El mismo vuelo daba 167° en
Python y 6° en JavaScript. La causa: el ángulo se mide respecto a un punto del suelo, y
"el suelo" no está en el mismo sitio según el dato. Con alturas **relativas al despegue**
está en cero; con las **elipsoidales del `.MRK`** —que rondan los 716 m— el cero cae 716 m
por debajo y todos los rayos salen casi paralelos.

Ahora la cota del suelo es **un argumento explícito** en las dos implementaciones, y queda
dicho que **la cobertura de acimut no depende de esa suposición**: es el indicador robusto.

### Duplicados y desperdicio

- **5 grupos de vuelos duplicados**, 2,8 GB: los mismos vuelos copiados a la carpeta de entrega. Se detectan comparando fotos, gimbal y recorrido, no el nombre de carpeta, que es justo lo que cambia al copiar.
- **12 vuelos sin aprovechamiento** (238 fotos, 1,2 GB): recorrido nulo o menos de 20° barridos. Cuatro son panoramas —el dron parado girando—, que no sirven para reconstruir por definición.

### El explorador en la app

`js/triage.js` lleva todo esto al navegador. Botón **explorar carpeta**, se elige una
carpeta y recorre todas sus subcarpetas:

- Lee **solo los primeros 128 KB** de cada foto, que es donde están el EXIF y el XMP. Miles de fotos de 20 MB en segundos.
- Lee además `.SRT` de vídeo y `.MRK` de RTK.
- Agrupa en vuelos por carpeta y por saltos de tiempo.
- Puntúa de 0 a 100 y emite un veredicto con sus motivos.
- Exporta el informe a CSV.

Un `.SRT` o un `.MRK` **sin su material al lado no se ignora**: describe un vuelo que
existe, y a veces es lo único que queda de él. El `.MRK` suelto de este proyecto describía,
él solo, el mejor vuelo recibido.

Lleva un lector de EXIF propio (marcadores JPEG, IFD TIFF) porque solo hacen falta cuatro
campos y no merecía la pena una dependencia. El tamaño se toma del marcador SOF, no del
EXIF: una foto recortada conserva el tamaño viejo en sus etiquetas.

---

## 19. Medir en metros dentro de la app (23/09/2026)

Cerrado el ciclo: **de una carpeta de fotos de dron a una medida en metros, sin
fotogrametría y sin instalar nada**. Los metadatos dan la pose de cada foto (apartado 15),
y marcando el mismo punto en dos vistas se corta en el espacio.

### Lo que se ve en pantalla

Dos fotos lado a lado. Se marca un punto en la izquierda y:

1. La app **elige sola la foto de la derecha**: la más separada angularmente que siga
   viendo ese punto, no la siguiente del vuelo. En la prueba eligió una a **122°**.
2. Dibuja la **recta epipolar**: el punto correspondiente cae forzosamente sobre ella, así
   que en vez de buscar por toda la imagen se sigue la línea. Con la distancia anotada
   sobre la guía, para orientarse.
3. Al marcar en la derecha, sale el punto en metros, su **error de reproyección** y la
   precisión esperada.
4. La distancia entre los dos últimos puntos, con su incertidumbre y el desnivel.

### Medido contra verdad conocida

Escena sintética de un edificio de 20 × 10 m, alero a 8 y cumbrera a 11, con seis fotos
que llevan **EXIF y XMP de DJI auténticos** (`python/tests/hacer_fotos_dji.py`):

| | verdad | medido | error |
|---|---|---|---|
| Lado | 20 m | 20,0000 m | **0,0 mm** |
| Altura de alero | 8 m | 8,0000 m | **0,0 mm** |
| Altura de cumbrera | 11 m | 11,0000 m | **0,0 mm** |
| Error de reproyección | — | 0,0004 px | — |
| Posición de cámara reconstruida | — | — | 0,08 mm |

Y **marcando con el ratón de verdad**, a la resolución de pantalla: **19,99 m** sobre 20,
con 1,0 px de error de reproyección. La app anunciaba ±23 cm y el error real fue de 1 cm:
la estimación es **conservadora**, que es el lado correcto por el que equivocarse.

### Un fallo numérico que la primera prueba no vio

La triangulación necesita el autovector del menor autovalor. La primera versión usaba
iteración de potencia sobre `cI − AᵀA` y **fallaba en silencio**: daba 94 m donde había 20.

La causa: con cámaras a decenas de metros los dos autovalores mayores quedan casi iguales
tras el desplazamiento, y la iteración no converge. La comprobación cruzada contra Python
**había pasado** porque aquella escena estaba mejor condicionada. Sustituido por rotaciones
de Jacobi, que con una matriz simétrica 4×4 no tienen ese problema y cuestan nada.

La lección para el proyecto: **una prueba que pasa no dice que el método sea estable**,
solo que lo es para esos números. Por eso ahora hay dos escenas con condicionamiento
distinto.

### Otro de proceso

Un parche a `triage.js` no llegó a aplicarse y el script que lo aplicaba **dijo que sí**.
Se perdió un rato buscando el fallo en el sitio equivocado. Desde entonces los parches
llevan `assert` de que la sustitución ocurrió.

### Archivos

```
js/multiview.js        triangulación, recta epipolar, elección de la segunda vista,
                       precisión esperada y construcción de cámara desde el XMP
js/measure.js          la interfaz de dos paneles
python/tests/hacer_fotos_dji.py   generador de fotos con metadatos DJI y verdad conocida
tests_navegador/       cuatro pruebas de navegador, repetibles
```

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

### 2026-09-18 — Fotos reales de dron: el supuesto de partida no se sostiene
Cinco fotos de dron de un pueblo. Documentado en el apartado 12. Resumen: el detector de
aristas funciona bien; la calibración monocular se derrumba por encima de 70° de picado
(medido con un barrido de altura sobre escena de verdad conocida); el detector de planos
no sirve en vistas con muchos edificios. Para este material la vía correcta es
fotogrametría multivista, y la geometría monocular pasa a ser complemento para tomas
oblicuas de un edificio concreto. El EXIF de los originales (focal, altitud relativa,
cabeceo del gimbal) elimina de raíz los tres términos peor estimados.

### 2026-09-18 — Anotación multivista por triangulación
Datos reales: DJI Matrice 4E, solape 70/80 %, objetivo principal un edificio concreto.
Escritos `multiview.py` y `colmap.py` con 18 pruebas. Documentado en el apartado 13.
Hallazgo principal: marcar en tres fotos con 2 px de precisión da 5 cm de error en 3D,
pero el ángulo entre tomas pesa mucho más que el número de tomas (factor 35 entre 2° y
90°). De ahí sale una regla de interfaz: ofrecer para la segunda marca la foto más
separada angularmente, no la siguiente.

Pendiente de confirmar con el usuario: especificaciones del Matrice 4E (saldrán del EXIF,
no de mi memoria) y si su vídeo lleva archivo .SRT de telemetría, que haría las veces de
EXIF y permitiría usar vídeo sin perder la escala.

### 2026-09-18 — Telemetría .SRT confirmada con material real
Escrito `vision_teach/dji.py` (12 pruebas, 52 en total). Documentado en el apartado 14.
Confirmado que el `.SRT` existe y trae posición, altura y focal, pero **no los ángulos del
gimbal**. De los dos vuelos analizados uno es inservible (el dron estaba parado: 0 m de
recorrido en 2 s) y el otro sí vale (70 m, 39° barridos).

Las fotos siguen llegando sin EXIF por el chat, comprobado a nivel de bytes en las ocho
recibidas. Para el EXIF hay que usar Drive.

### 2026-09-18 — Primera foto original: pose de cámara sin fotogrametría
`DJI_0763.JPG` con EXIF y XMP intactos. Escrito `vision_teach/photo.py` (17 pruebas, 71 en
total). Documentado en el apartado 15.

- Confirmado que `focal_len: 240` del SRT son 24 mm equivalentes.
- Queda sin resolver un 4 %: `FocalLengthIn35mmFilm` puede ser respecto al ancho o a la diagonal del fotograma de 35 mm. La convención es ahora un parámetro explícito.
- Las fotos traen los ángulos del gimbal; el SRT del vídeo no. Con ellos se construye la pose completa y se puede triangular sin COLMAP.
- `GimbalPitchDegree = -90` confirma que las tomas son cenitales por costumbre de vuelo, no por casualidad: es justo el caso que rompe la calibración monocular.
- **El dron es un Mini 3 Pro, no el Matrice 4E** que se había dicho. Pendiente de aclarar.
- No se logró validar la escala con objetos de la propia foto (coches clásicos de medidas desconocidas, ajuste del ruedo fallido). No se publica ningún número de esos.

### 2026-09-18 — ¿Metadatos o fotogrametría? Medido, y corrige lo anterior
El usuario vuela los dos drones, sobre todo el Matrice 4E. Medido en el apartado 16 cómo
se propaga el error de la pose. El término dominante es el **ángulo del gimbal**, no el
GPS: a 60 m, 1° son 1 m. Pero al medir una distancia entre dos puntos próximos el error
se cancela casi entero, y con RTK quedan del 0,3 al 0,6 % — de 5 a 11 cm en 20 m.

Queda matizado el apartado 15: los metadatos bastan para **medir** un edificio, no para
**situarlo**. La fotogrametría sigue siendo mejor, pero ya no es imprescindible para
empezar.

### 2026-09-18 — Archivos RTK/PPK: el primer vuelo realmente bueno
Escritos `mrk.py` y `flights.py` más el extractor `AUTO3D_metadatos.ps1` (22 pruebas
nuevas, 93 en total). Documentado en el apartado 17.

El vuelo 0002 es una órbita cerrada de 1479 disparos con RTK a 4-6 cm y 100 % de acimut
cubierto: con eso la fotogrametría da centímetros y el problema del gimbal desaparece.

Hallazgo de una prueba que falló: el ángulo barrido no distingue una órbita de una pasada
recta (35° la recta, 31° la órbita) y hacía falta añadir la cobertura de acimut.

Pendiente: una foto de ese mismo vuelo, para resolver si el `.MRK` da la posición de la
antena o la de la cámara comparándola con el XMP.

### 2026-09-19 — Explorador de carpetas en la app, y 5346 fotos reales
Escrito `js/triage.js` con su interfaz. Documentado en el apartado 18. Analizado el CSV
real: 57 vuelos, varios mixtos con acimut completo y RTK de milímetros.

Dos errores que solo apareció con datos de verdad: el umbral del cielo estaba en −10° y
descartaba vuelos casi horizontales que son los mejores para fachadas; y el ángulo barrido
dependía de dónde se suponía el suelo, dando 167° en Python y 6° en JavaScript para el
mismo vuelo. Los dos corregidos, y la suposición es ahora explícita.

El extractor de PowerShell escribe en `<carpeta del script>\datos`, dentro del proyecto en
E:, no en el Escritorio.

### 2026-09-23 — Medir en metros dentro de la app
Escritos `js/multiview.js` y `js/measure.js`, más el generador de fotos sintéticas con
metadatos DJI y cuatro pruebas de navegador repetibles. Documentado en el apartado 19.

Medido contra verdad conocida: lado de 20 m con 0,0 mm de error; marcando con el ratón,
19,99 m. La cadena entera —metadatos, pose, triangulación, metros— queda cerrada sin
fotogrametría.

Un fallo numérico en la triangulación (iteración de potencia que no converge) pasó la
comprobación cruzada contra Python y solo apareció con la segunda escena. Sustituido por
Jacobi.
