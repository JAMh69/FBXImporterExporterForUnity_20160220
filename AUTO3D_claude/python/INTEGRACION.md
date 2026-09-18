# Cómo enchufar esto a AUTO3D (la app Python)

Esto **no reemplaza nada**. Añade a la aplicación lo que hoy no tiene: aristas rectas
agrupadas por dirección, puntos de fuga, calibración de cámara, planos con normal en el
espacio, medidas en metros y seguimiento entre fotogramas.

No toca `ui.py`, ni `storage.py`, ni `learning.py`, ni el empaquetado, ni los tests
existentes. **No añade dependencias**: solo `numpy` y `opencv`, que ya están en
`requirements.txt`.

## 1. Copiar tres archivos

```
vision_teach/geometry.py           la matemática, sin OpenCV para dibujar
vision_teach/geometry_overlay.py   el puente: analizar, dibujar, medir
vision_teach/tracking.py           seguimiento entre fotogramas
tests/test_geometry.py             22 pruebas
tests/scene.py                     escena sintética con verdad conocida
```

Ejecuta `python -m pytest tests/ -q`. Deben pasar las 22 sin tocar nada más.

## 2. Mostrar la geometría: tres líneas en `engine.py`

En `Engine.process`, después de `self.result = detect(self.frame, self.learner)`:

```python
from .geometry_overlay import analyse, draw, summary      # arriba del archivo

    def process(self, event='procesar_frame'):
        if self.frame is None:
            raise ValueError('Abre primero una imagen o un vídeo.')
        self.result = detect(self.frame, self.learner)
        if self.geometry_enabled:                                    # nuevo
            self.geometry = analyse(self.frame, self.result['parameters'])
            self.result['image'] = draw(self.result['image'], self.geometry)
            self.result['geometry'] = summary(self.geometry)
        ...
```

`analyse` recibe **los mismos umbrales que ha aprendido el Random Forest**. Es el punto
de unión real entre las dos líneas de trabajo: enseñar a la app a calibrar los filtros
mejora también la geometría, no solo el dibujo de contornos.

Conviene que `geometry_enabled` sea una casilla en la interfaz: el análisis geométrico
cuesta del orden de 150-400 ms por fotograma a 800 px, y durante la reproducción de un
vídeo puede convenir apagarlo.

## 3. Medir un plano anotado

Cuando el usuario guarda una anotación de tipo `surface`:

```python
from .geometry_overlay import measure
from .geometry import VERTICAL, HORIZONTAL, FREE

medida = measure(self.geometry, puntos, VERTICAL)     # o HORIZONTAL para el suelo
if 'error' in medida:
    mensaje = medida['error']          # explica por qué, en castellano
else:
    mensaje = f"{medida['sides'].max():.2f} × {medida['height']:.2f} m"
```

**El eje depende de la clase semántica, y esa es la pieza que falta en la app.** Hoy sus
tres etiquetas (`control`, `edge`, `surface`) son primitivas geométricas, no elementos de
edificio. Para llegar a BIM hace falta que una superficie se pueda marcar como fachada,
suelo, cubierta, hueco o medianera: es lo que decide si el polígono se apoya en el
terreno o se levanta vertical sobre su base. Es un campo más en la anotación y una fila
más de botones.

## 4. Seguimiento entre fotogramas

Hoy las marcas se guardan por `(source_id, frame_index)` y hay que rehacerlas en cada
fotograma. Con `tracking.py`:

```python
from .tracking import track_annotation

# en Engine.__init__
self.previous_gray = None

# en Engine.next_frame, tras leer el fotograma nuevo
gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
if self.previous_gray is not None:
    for fila in self.dataset.for_frame(self.source_id, self.frame_index - 1):
        seguido = track_annotation(self.previous_gray, gray, fila['points'])
        if seguido is not None:
            # propagar como anotación provisional del fotograma nuevo,
            # marcada para distinguirla de una marcada a mano
            ...
self.previous_gray = gray
```

Dos avisos que importan:

- **Lo propagado no es verdad del usuario.** Guárdalo con una marca (`'source': 'track'`)
  y **no lo metas en el dataset de entrenamiento**: si una marca seguida entra como
  ejemplo, el modelo se entrena con su propia salida y se realimenta.
- `track_annotation` devuelve `None` cuando pierde más de la mitad de los vértices. Eso
  es deliberado: es preferible que falte una anotación a arrastrar una mal colocada
  durante doscientos fotogramas.

## 5. Lo que hace falta en la interfaz, y no está aquí

Tres cosas que son de `ui.py` y que no he tocado porque son vuestro terreno:

1. **Retroceder en el vídeo.** Hoy solo se avanza con `capture.read()`. Para corregir en
   el fotograma 47 hace falta `capture.set(cv2.CAP_PROP_POS_FRAMES, n)`.
2. **Mover un vértice ya guardado.** Hoy solo existe *deshacer la última*. Arrastrar un
   vértice es lo que convierte el seguimiento en algo utilizable: se corrige donde se
   desvía y `tracking.interpolate` rellena lo de en medio entre correcciones.
3. **Elegir la clase del elemento** al marcar una superficie (punto 3).

## 6. Lo que sigue faltando para BIM, en las dos líneas

- Fusionar varias vistas en un único modelo. Hoy cada fotograma se reconstruye por
  separado: no hay nube de puntos ni ajuste de haces.
- La escala sale de la altura de cámara, que teclea el usuario. Si está mal, el modelo
  entero está mal en la misma proporción, y no hay forma de detectarlo solo.
- Topología: que una fachada acabe en el suelo y una cubierta apoye en las fachadas.
- IFC. **Este es el motivo de haber portado la geometría a Python en vez de dejarla en
  JavaScript**: IfcOpenShell solo existe aquí. Pero conviene hacerlo después de la
  topología: un IFC con geometría inconsistente es peor que no tener IFC.

## 7. Precisión medida, no estimada

Escena sintética de verdad conocida (fachada de 12 × 11 m, focal real 620 px, cámara a
1,60 m, cabeceo 4°), seis puntos de vista entre 20° y 40°:

| medida | resultado |
|---|---|
| Focal estimada | **0,6 % a 2,5 % de error** |
| Horizonte | 1,9 a 8,1 px, media 5,1 (imagen de 600 px de alto) |
| Reconstrucción con calibración exacta | **error nulo**: 12,000 × 11,000 m |
| Suelo con calibración exacta | exacto, y a −1,600 m de la cámara |
| Seguimiento, desplazamiento de 7 px | dentro de 1 px en los vértices que sobreviven |

La cadena geométrica es exacta; el error métrico final es casi todo error de calibración.
El error del horizonte ya no viene de la focal sino de la dirección vertical estimada
— se comprobó si forzar el horizonte a pasar por el punto de fuga horizontal lo mejoraba,
y resulta ser la misma recta por construcción, así que no hay nada que ganar por ahí.

Como referencia: la versión equivalente en JavaScript daba un **8 %** de error en la
focal. La diferencia está en el Canny y el trazado de contornos de OpenCV, que entregan
segmentos más limpios al RANSAC.
