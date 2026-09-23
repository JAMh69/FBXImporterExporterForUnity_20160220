"""Genera fotos sinteticas con EXIF y XMP de DJI, y verdad conocida.

Sirve para probar la cadena entera -explorar carpeta, construir camaras,
triangular- sobre archivos con el mismo aspecto que los reales, y comprobar la
medida contra unas dimensiones que se conocen de antemano.
"""
import io
import json
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from vision_teach.photo import rotation_from_gimbal          # noqa: E402

ANCHO, ALTO, EQUIV35 = 1600, 1200, 24
FOCAL = ANCHO * EQUIV35 / 36.
LAT0, LON0 = 41.8767, -0.7878          # Zuera, como el material real
TIERRA = 6378137.

# Edificio de 20 x 10 m en planta, alero a 8 m y cumbrera a 11
A, B, C, D = (-10, -5), (10, -5), (10, 5), (-10, 5)
ALERO, CUMBRERA = 8., 11.
CARAS = [
    ([(A[0], A[1], 0), (B[0], B[1], 0), (B[0], B[1], ALERO), (A[0], A[1], ALERO)], (196, 188, 170)),
    ([(B[0], B[1], 0), (C[0], C[1], 0), (C[0], C[1], ALERO), (B[0], B[1], ALERO)], (176, 168, 150)),
    ([(C[0], C[1], 0), (D[0], D[1], 0), (D[0], D[1], ALERO), (C[0], C[1], ALERO)], (186, 178, 160)),
    ([(D[0], D[1], 0), (A[0], A[1], 0), (A[0], A[1], ALERO), (D[0], D[1], ALERO)], (166, 158, 142)),
    ([(A[0], A[1], ALERO), (B[0], B[1], ALERO), (B[0], 0, CUMBRERA), (A[0], 0, CUMBRERA)], (172, 96, 70)),
    ([(C[0], C[1], ALERO), (D[0], D[1], ALERO), (D[0], 0, CUMBRERA), (C[0], 0, CUMBRERA)], (152, 84, 60)),
]
# esquinas con nombre, para comprobar medidas
REFERENCIAS = {
    'base_A': (A[0], A[1], 0.), 'base_B': (B[0], B[1], 0.),
    'alero_A': (A[0], A[1], ALERO), 'alero_B': (B[0], B[1], ALERO),
    'cumbrera_izq': (A[0], 0., CUMBRERA), 'cumbrera_der': (B[0], 0., CUMBRERA),
}


def mirar_a(posicion, objetivo):
    """Guiñado y cabeceo del gimbal para apuntar de una posicion a otra."""
    d = np.asarray(objetivo, float) - np.asarray(posicion, float)
    yaw = np.degrees(np.arctan2(d[0], d[1]))                 # desde el norte, horario
    pitch = np.degrees(np.arcsin(d[2] / np.linalg.norm(d)))  # negativo mirando abajo
    return float(yaw), float(pitch)


def a_grados(este, norte):
    k = np.cos(np.radians(LAT0))
    return LAT0 + np.degrees(norte / TIERRA), LON0 + np.degrees(este / (TIERRA * k))


def proyectar(R, centro, puntos):
    P = np.atleast_2d(np.asarray(puntos, float))
    cam = (P - centro) @ R.T
    z = np.maximum(cam[:, 2], 1e-6)
    return np.column_stack([FOCAL * cam[:, 0] / z + ANCHO / 2,
                            FOCAL * cam[:, 1] / z + ALTO / 2]), cam[:, 2] > 0


XMP = ('<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       '<rdf:Description rdf:about="" xmlns:drone-dji="http://www.dji.com/drone-dji/1.0/" '
       'drone-dji:GpsStatus="RTK" drone-dji:AltitudeType="RtkAlt" '
       'drone-dji:GpsLatitude="{lat:+.9f}" drone-dji:GpsLongitude="{lon:+.9f}" '
       'drone-dji:AbsoluteAltitude="{abs:+.3f}" drone-dji:RelativeAltitude="{rel:+.3f}" '
       'drone-dji:GimbalRollDegree="+0.00" drone-dji:GimbalYawDegree="{yaw:+.2f}" '
       'drone-dji:GimbalPitchDegree="{pitch:+.2f}" drone-dji:DroneModel="M4E" '
       'drone-dji:ImageSource="WideCamera" drone-dji:RtkStdLon="0.021" '
       'drone-dji:RtkStdLat="0.019" drone-dji:RtkStdHgt="0.034" drone-dji:RtkFlag="50" '
       'drone-dji:SurveyingMode="1"/></rdf:RDF></x:xmpmeta>')


def escribir(path, imagen, lat, lon, rel, yaw, pitch):
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = 'DJI', 'M4E'
    exif[0x8769] = {0x920A: 12.29, 0xA405: EQUIV35, 0x9003: '2026:08:04 11:36:55'}
    buf = io.BytesIO()
    imagen.save(buf, 'JPEG', quality=92, exif=exif)
    datos = buf.getvalue()
    carga = XMP.format(lat=lat, lon=lon, abs=364. + rel, rel=rel, yaw=yaw, pitch=pitch).encode()
    seg = (b'\xff\xe1' + struct.pack('>H', len(carga) + 2 + 29) +
           b'http://ns.adobe.com/xap/1.0/\x00' + carga)
    Path(path).write_bytes(datos[:2] + seg + datos[2:])


def generar(destino, n=6, radio=60., altura=45., objetivo=(0., 0., 5.)):
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    verdad = {'referencias': {k: list(v) for k, v in REFERENCIAS.items()}, 'fotos': []}
    for i in range(n):
        a = 2 * np.pi * i / n
        pos = np.array([radio * np.cos(a), radio * np.sin(a), altura])
        yaw, pitch = mirar_a(pos, objetivo)
        R = rotation_from_gimbal(yaw, pitch, 0.)
        img = Image.new('RGB', (ANCHO, ALTO), (150, 186, 214))
        dib = ImageDraw.Draw(img)
        # suelo
        suelo, _ = proyectar(R, pos, [(-200, -200, 0), (200, -200, 0), (200, 200, 0), (-200, 200, 0)])
        dib.polygon([tuple(p) for p in suelo], fill=(118, 132, 104))
        # caras, de la mas lejana a la mas cercana
        orden = sorted(CARAS, key=lambda c: -np.linalg.norm(np.mean(c[0], axis=0) - pos))
        for vertices, color in orden:
            px, delante = proyectar(R, pos, vertices)
            if not delante.all():
                continue
            dib.polygon([tuple(p) for p in px], fill=color, outline=(60, 54, 48))
        # marcas de textura, para que no sea una imagen plana
        for x in np.arange(-9, 10, 2.):
            for z in np.arange(1.2, 7.5, 2.2):
                hueco = [(x, -5.02, z), (x + 1.2, -5.02, z), (x + 1.2, -5.02, z + 1.4), (x, -5.02, z + 1.4)]
                px, delante = proyectar(R, pos, hueco)
                if delante.all():
                    dib.polygon([tuple(p) for p in px], fill=(58, 70, 84))
        lat, lon = a_grados(pos[0], pos[1])
        nombre = f'DJI_2026080411{3000 + i:04d}_{i + 1:04d}_V.JPG'
        escribir(destino / nombre, img, lat, lon, altura, yaw, pitch)
        marcas = {k: list(proyectar(R, pos, [v])[0][0]) for k, v in REFERENCIAS.items()}
        verdad['fotos'].append({'nombre': nombre, 'yaw': yaw, 'pitch': pitch,
                                'pos': list(pos), 'lat': lat, 'lon': lon, 'marcas': marcas})
    (destino / 'verdad.json').write_text(json.dumps(verdad, indent=1), encoding='utf-8')
    return verdad


if __name__ == '__main__':
    v = generar(sys.argv[1] if len(sys.argv) > 1 else 'fotos_sinteticas')
    print(f"{len(v['fotos'])} fotos generadas")
    print('distancia real base_A -> base_B:',
          np.linalg.norm(np.array(v['referencias']['base_B']) - np.array(v['referencias']['base_A'])), 'm')
