# AUTO3D — detección de aristas y planos de edificios, con modo LEARN

App de escritorio en un solo HTML. **Doble clic en `index.html`** y lista: no necesita
servidor, ni instalación, ni conexión. Nada sale de tu equipo.

Probada en Chromium/Chrome y Edge. En Firefox funciona, pero el salto por fotograma
en vídeo es menos preciso.

## Qué hace hoy

- Detecta **aristas** rectas en fotos y en fotogramas de vídeo.
- Calcula los **puntos de fuga** y con ellos **calibra la cámara** (distancia focal y horizonte) sin saber con qué se tomó la foto.
- Propone **planos** (fachadas, suelos) puntuados por cuánto borde real los sostiene.
- **Modo LEARN**: marcas puntos, aristas y planos, les pones clase (fachada, suelo, cubierta, hueco, medianera) y el programa **aprende a distinguirlos**.
- **Seguimiento fotograma a fotograma** de lo que marcas, con keyframes editables: corriges en cualquier fotograma y lo demás se recalcula.
- **Reconstrucción 3D métrica** de una vista y exportación a **OBJ**.
- Exporta **proyecto**, **CSV** de anotaciones y **dataset** para llevar lo aprendido a otra app.

Lo que **todavía no** hace: unir varias vistas en un único modelo y exportar IFC.
Ver la hoja de ruta en `AUTO3D_KNOWLEDGE.md`.

## Primeros pasos

1. Abre `index.html`.
2. Arrastra una foto o un vídeo a la ventana.
3. Pulsa **detectar** (o tecla `D`). Verás aristas coloreadas por punto de fuga, el horizonte y los planos candidatos.
4. Pasa el ratón por un plano candidato y **haz clic para aceptarlo**: se convierte en una anotación de la clase activa.
5. Ajusta **altura de cámara** en el panel izquierdo (1.60 m a pie de calle; cámbialo si es dron o trípode) y pulsa **exportar OBJ**.

### Enseñarle a distinguir sólidos (modo LEARN)

1. Pulsa **LEARN** arriba a la derecha.
2. Elige la clase (Fachada, Suelo, Cubierta…) y la herramienta **plano** (`G`).
3. Haz clic en cada esquina y cierra con doble clic o `Enter`. Cada plano que marcas entra automáticamente como muestra.
4. Con 15-20 muestras de al menos dos clases, pulsa **entrenar**. Verás la precisión medida sobre muestras que no ha visto.
5. Pulsa **predecir**: los planos candidatos aparecen ya etiquetados con su probabilidad.
6. Cuantas más muestras en condiciones distintas (sol, sombra, ladrillo, revoco), mejor generaliza.

### Seguir un elemento por el vídeo

1. Marca el plano en el fotograma 0.
2. Avanza con `→`. El plano se sigue solo (línea continua = keyframe tuyo; discontinua = seguido o interpolado).
3. Donde se desvíe, **arrastra los vértices**: eso crea un keyframe nuevo y los fotogramas intermedios se interpolan entre tus keyframes.
4. **propagar a todo el vídeo** recorre el resto de fotogramas de una vez.

Los vértices sin textura suficiente, o que no superan el control de coherencia
ida-vuelta, no se propagan a propósito: es mejor que falte un vértice a que te lo
coloque mal durante 200 fotogramas.

## Atajos

| tecla | acción |
|---|---|
| `V` `P` `E` `G` | seleccionar / punto / arista / plano |
| `D` | detectar |
| `K` | fijar keyframe |
| `F` | encuadrar |
| `←` `→` | fotograma (con `Shift`, ±10) |
| `Supr` | borrar seleccionado |
| `Enter` / doble clic | cerrar polígono |
| `Esc` | cancelar |
| rueda | zoom |
| `Alt`+arrastrar | mover la vista |

## Consejos de fotografía

- La calibración necesita ver **dos direcciones horizontales**: fotografía por la **esquina** del edificio, no de frente. De frente solo hay un punto de fuga y no hay escala.
- Que se vea **el encuentro con el suelo**: la base es lo que ancla la escala. Sin base visible no hay reconstrucción.
- Evita el gran angular extremo: la distorsión de barril curva las rectas y falsea los puntos de fuga.
- Mejor luz difusa: las sombras duras generan falsas aristas.

## Archivos que genera

| archivo | contenido |
|---|---|
| `auto3d_proyecto.json` | objetos, keyframes y parámetros. Se reabre con *abrir proyecto* |
| `auto3d_fN.obj` + `auto3d.mtl` | geometría 3D del fotograma N, en metros, por capas de clase |
| `auto3d_anotaciones.csv` | una fila por objeto y fotograma |
| `auto3d_dataset.json` | descriptores, etiquetas y pesos del clasificador |

## Documentación técnica

`AUTO3D_KNOWLEDGE.md` — algoritmos, mediciones de precisión reales, limitaciones
conocidas, hoja de ruta hacia IFC y cómo pasarle el proyecto a otra IA.
