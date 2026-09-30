"""Informe HTML autocontenido del proceso (se abre con cualquier navegador)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .model import Modelo

_CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--mut:#6e6e73;--line:#d2d2d7;--ok:#1a7f37;--warn:#b35900;--fill:#e8eef7;--stroke:#2f5d9f}
@media (prefers-color-scheme:dark){:root{--bg:#161618;--fg:#f2f2f2;--mut:#a1a1a6;--line:#3a3a3c;--ok:#4ac26b;--warn:#f0a050;--fill:#23324a;--stroke:#7fa8e8}}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:960px;margin:auto}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:28px 0 8px}
.mut{color:var(--mut)}table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left}
th{font-weight:600}.num{text-align:right;font-variant-numeric:tabular-nums}.ok{color:var(--ok)}.warn{color:var(--warn)}
svg{width:100%;height:auto;max-height:360px;border:1px solid var(--line);border-radius:8px}li{margin:4px 0}
.planta path.muro{fill:none;stroke:var(--fg);stroke-width:3}
.planta path{fill:var(--fill);stroke:var(--stroke);stroke-width:1.5;fill-rule:evenodd;vector-effect:non-scaling-stroke}
"""


def _miles(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _svg_planta(modelo: Modelo, nivel_id: str) -> str:
    fj = [f for f in modelo.forjados if f.nivel_id == nivel_id]
    mu = [w for w in modelo.muros if w.nivel_id == nivel_id]
    if not fj and not mu:
        return ""
    xs = [p[0] for f in fj for p in f.contorno] + [q[0] for w in mu for q in (w.inicio, w.fin)]
    ys = [p[1] for f in fj for p in f.contorno] + [q[1] for w in mu for q in (w.inicio, w.fin)]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    m = max(x1 - x0, y1 - y0) * 0.05 + 0.5
    w, h = x1 - x0 + 2 * m, y1 - y0 + 2 * m

    def anillo(pts):
        return "M" + " L".join(f"{p[0] - x0 + m:.2f},{y1 - p[1] + m:.2f}" for p in pts) + " Z"

    paths = "".join(f'<path d="{anillo(f.contorno)} {" ".join(anillo(hh) for hh in f.huecos)}"/>' for f in fj)
    paths += "".join(
        f'<path class="muro" d="M{w.inicio[0] - x0 + m:.2f},{y1 - w.inicio[1] + m:.2f} '
        f'L{w.fin[0] - x0 + m:.2f},{y1 - w.fin[1] + m:.2f}"/>' for w in mu)
    return f'<svg class="planta" viewBox="0 0 {w:.2f} {h:.2f}" role="img" aria-label="Planta">{paths}</svg>'


def escribir(ruta: Path, nombre: str, modelo: Modelo, info: dict, res_niveles=None) -> Path:
    e = html.escape
    filas_niv = "".join(
        f"<tr><td>{e(n.nombre)}</td><td class='num'>{n.cota:+.3f}</td><td class='num'>{n.cota + modelo.offset[2]:.3f}</td></tr>"
        for n in modelo.niveles
    )
    nombres = {n.id: n.nombre for n in modelo.niveles}
    filas_fj = "".join(
        f"<tr><td>{e(f.id)}</td><td>{e(nombres.get(f.nivel_id, ''))}</td><td class='num'>{f.espesor:.3f}</td>"
        f"<td class='num'>{f.area_m2:.1f}</td><td class='num'>{len(f.huecos)}</td>"
        f"<td class='{'ok' if f.espesor_medido else 'warn'}'>{'medido' if f.espesor_medido else 'supuesto'}</td></tr>"
        for f in modelo.forjados
    )
    filas_mu = "".join(
        f"<tr><td>{e(w.id)}</td><td>{e(nombres.get(w.nivel_id, ''))}</td>"
        f"<td class='num'>{((w.fin[0] - w.inicio[0]) ** 2 + (w.fin[1] - w.inicio[1]) ** 2) ** 0.5:.2f}</td>"
        f"<td class='num'>{w.altura:.2f}</td><td class='num'>{w.espesor:.2f} (supuesto)</td>"
        f"<td class='{'ok' if w.confianza >= 0.3 else 'warn'}'>{w.confianza:.2f}</td></tr>"
        for w in modelo.muros
    )
    filas_cu = "".join(
        f"<tr><td>{e(c.id)}</td><td>{e(nombres.get(c.nivel_id, ''))}</td><td class='num'>{c.cota_inferior + modelo.offset[2]:.3f}</td>"
        f"<td class='num'>{c.espesor:.2f}</td><td class='num'>{c.area_m2:.1f}</td>"
        f"<td class='{'ok' if c.espesor_medido else 'warn'}'>{'medido' if c.espesor_medido else 'supuesto'}</td></tr>"
        for c in modelo.cubiertas
    )
    plantas = "".join(
        f"<h3>{e(n.nombre)}</h3>{_svg_planta(modelo, n.id)}" for n in modelo.niveles if _svg_planta(modelo, n.id)
    )
    avisos = "".join(f"<li>{e(a)}</li>" for a in modelo.avisos) or "<li>Sin avisos.</li>"
    archivos = "".join(f"<li>{e(Path(a).name)}</li>" for a in info.get("archivos", []))
    ox, oy, oz = modelo.offset
    terreno = (f"{len(modelo.terreno.puntos)} puntos, malla de {modelo.terreno.paso_m:.2f} m"
               if modelo.terreno else "no generado")
    doc = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Informe Scan2RVT</title><style>{_CSS}</style></head>
<body><main>
<h1>{e(nombre)}</h1>
<p class="mut">Scan2RVT {e(info.get('version', ''))} · {datetime.now():%d/%m/%Y %H:%M} · {info.get('segundos', 0)} s ·
{_miles(info.get('puntos_escaner', 0))} puntos de escáner · {_miles(info.get('puntos_dron', 0))} puntos de dron</p>
<h2>Origen de coordenadas</h2>
<p>Las coordenadas del modelo son locales: <b>real = local + ({ox:.3f}, {oy:.3f}, {oz:.3f})</b>{' · EPSG:' + e(modelo.epsg) if modelo.epsg else ''}.</p>
<h2>Niveles</h2>
<table><tr><th>Nivel</th><th class="num">Cota local (m)</th><th class="num">Cota real (m)</th></tr>{filas_niv}</table>
<h2>Forjados y suelos</h2>
<table><tr><th>Id</th><th>Nivel</th><th class="num">Espesor (m)</th><th class="num">Área (m²)</th><th class="num">Huecos</th><th>Espesor</th></tr>{filas_fj}</table>
<h2>Muros</h2>
{('<table><tr><th>Id</th><th>Nivel</th><th class="num">Longitud (m)</th><th class="num">Altura (m)</th><th class="num">Espesor (m)</th><th>Confianza</th></tr>' + filas_mu + '</table><p class="mut">El eje es la cara vista por el escáner.</p>') if filas_mu else '<p class="mut">Sin muros.</p>'}
<h2>Cubiertas</h2>
{('<table><tr><th>Id</th><th>Planta</th><th class="num">Cota inferior real (m)</th><th class="num">Espesor (m)</th><th class="num">Área (m²)</th><th>Espesor</th></tr>' + filas_cu + '</table>') if filas_cu else '<p class="mut">Sin cubiertas.</p>'}
<h2>Terreno</h2><p>{terreno}</p>
<h2>Plantas</h2>{plantas or '<p class="mut">Sin forjados.</p>'}
<h2>Avisos</h2><ul>{avisos}</ul>
<h2>Archivos generados</h2><ul>{archivos}</ul>
</main></body></html>"""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(doc, encoding="utf-8")
    return ruta
