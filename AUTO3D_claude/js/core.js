/* AUTO3D - core.js : estado global, utilidades, bus de eventos.
   Sin dependencias externas. Se carga como script clasico (funciona en file://). */
window.A3D = window.A3D || {};
(function (A) {
  'use strict';

  /* ---------- clases semanticas (editables por el usuario) ---------- */
  A.CLASSES = [
    { id: 'fachada',   nom: 'Fachada',        color: '#4da3ff', axis: 'vertical'   },
    { id: 'suelo',     nom: 'Suelo / terreno',color: '#3ddc97', axis: 'horizontal' },
    { id: 'cubierta',  nom: 'Cubierta',       color: '#ff6b6b', axis: 'libre'      },
    { id: 'hueco',     nom: 'Hueco (ventana)',color: '#ffb34d', axis: 'vertical'   },
    { id: 'medianera', nom: 'Medianera',      color: '#b07cff', axis: 'vertical'   },
    { id: 'otro',      nom: 'Otro',           color: '#9aa7b8', axis: 'libre'      }
  ];
  A.classById = function (id) {
    for (var i = 0; i < A.CLASSES.length; i++) if (A.CLASSES[i].id === id) return A.CLASSES[i];
    return A.CLASSES[A.CLASSES.length - 1];
  };

  /* ---------- estado global ---------- */
  A.state = {
    media: null,            // {type:'image'|'video', el, w, h, fps, nFrames, duration, name}
    frame: 0,
    zoom: 1, panX: 0, panY: 0,
    mode: 'auto',           // 'auto' | 'learn'
    tool: 'select',         // select|point|edge|plane|move|delete
    activeClass: 'fachada',
    objects: [],            // ver newObject()
    selectedId: null,
    detection: null,        // resultado del pipeline para el frame actual
    params: {
      proc: 640,            // ancho de trabajo del pipeline
      blur: 1.4,
      cannyLo: 0.08,
      cannyHi: 0.20,
      minSegLen: 26,
      dpTol: 1.8,
      vpInlierDeg: 2.2,
      vpIters: 900,
      planeSupport: 0.42,
      maxPlanes: 12,
      camHeight: 1.60,      // m, para reconstruccion monocular
      trackWin: 11,
      trackLevels: 3,
      fbTol: 1.6          // px de error ida-vuelta admitido en el seguimiento
    },
    show: { edges: true, segs: true, vps: true, planes: true, annots: true, ids: false },
    calib: null,            // {f, pp, vps, R}
    model: null,            // modelo aprendido (learn.js)
    autoTrack: true,
    dirty: false
  };

  /* ---------- bus de eventos minimo ---------- */
  var subs = {};
  A.on = function (ev, fn) { (subs[ev] = subs[ev] || []).push(fn); };
  A.emit = function (ev, data) { (subs[ev] || []).forEach(function (f) { try { f(data); } catch (e) { A.log('ERR ' + ev + ': ' + e.message, 'e'); } }); };

  /* ---------- log ---------- */
  A.log = function (msg, cls) {
    var el = document.getElementById('log');
    if (!el) { console.log(msg); return; }
    var d = document.createElement('div');
    if (cls) d.className = cls;
    var t = new Date();
    d.textContent = '[' + String(t.getHours()).padStart(2, '0') + ':' + String(t.getMinutes()).padStart(2, '0') + ':' + String(t.getSeconds()).padStart(2, '0') + '] ' + msg;
    el.appendChild(d); el.scrollTop = el.scrollHeight;
    while (el.childNodes.length > 300) el.removeChild(el.firstChild);
  };

  /* ---------- utilidades numericas ---------- */
  A.clamp = function (v, a, b) { return v < a ? a : (v > b ? b : v); };
  A.lerp = function (a, b, t) { return a + (b - a) * t; };
  A.deg = function (r) { return r * 180 / Math.PI; };
  A.rad = function (d) { return d * Math.PI / 180; };
  A.dist = function (a, b) { var dx = a[0] - b[0], dy = a[1] - b[1]; return Math.sqrt(dx * dx + dy * dy); };
  A.uid = (function () { var n = 0; return function (p) { n++; return (p || 'o') + '_' + Date.now().toString(36) + '_' + n; }; })();

  A.median = function (arr) {
    if (!arr.length) return 0;
    var a = arr.slice().sort(function (x, y) { return x - y; });
    var m = a.length >> 1;
    return a.length % 2 ? a[m] : (a[m - 1] + a[m]) / 2;
  };

  /* geometria homogenea 2D */
  A.cross3 = function (a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  };
  A.lineOf = function (p, q) { return A.cross3([p[0], p[1], 1], [q[0], q[1], 1]); };
  A.interLines = function (l1, l2) {
    var p = A.cross3(l1, l2);
    if (Math.abs(p[2]) < 1e-12) return null;          // paralelas
    return [p[0] / p[2], p[1] / p[2]];
  };
  A.normalize3 = function (v) {
    var n = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
  };
  A.dot3 = function (a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; };
  A.cross = A.cross3;
  A.sub3 = function (a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; };
  A.add3 = function (a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; };
  A.mul3 = function (a, s) { return [a[0] * s, a[1] * s, a[2] * s]; };

  /* poligonos */
  A.polyArea = function (pts) {
    var s = 0;
    for (var i = 0, n = pts.length; i < n; i++) {
      var a = pts[i], b = pts[(i + 1) % n];
      s += a[0] * b[1] - b[0] * a[1];
    }
    return s / 2;
  };
  A.polyCentroid = function (pts) {
    var a = A.polyArea(pts);
    if (Math.abs(a) < 1e-9) {
      var sx = 0, sy = 0;
      pts.forEach(function (p) { sx += p[0]; sy += p[1]; });
      return [sx / pts.length, sy / pts.length];
    }
    var cx = 0, cy = 0;
    for (var i = 0, n = pts.length; i < n; i++) {
      var p = pts[i], q = pts[(i + 1) % n], f = p[0] * q[1] - q[0] * p[1];
      cx += (p[0] + q[0]) * f; cy += (p[1] + q[1]) * f;
    }
    return [cx / (6 * a), cy / (6 * a)];
  };
  A.pointInPoly = function (pt, poly) {
    var x = pt[0], y = pt[1], inside = false;
    for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / ((yj - yi) || 1e-12) + xi)) inside = !inside;
    }
    return inside;
  };
  A.distToSeg = function (p, a, b) {
    var vx = b[0] - a[0], vy = b[1] - a[1];
    var L2 = vx * vx + vy * vy;
    var t = L2 ? A.clamp(((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2, 0, 1) : 0;
    var dx = a[0] + t * vx - p[0], dy = a[1] + t * vy - p[1];
    return Math.sqrt(dx * dx + dy * dy);
  };

  /* ---------- modelo de objetos anotados ----------
     Un objeto = una entidad semantica (punto / arista / plano) con
     keyframes: { [frame]: pts }  y  cache de tracking: { [frame]: pts }  */
  A.newObject = function (kind, cls, pts, frame) {
    var o = {
      id: A.uid(kind),
      kind: kind,                   // 'point' | 'edge' | 'plane'
      cls: cls,
      name: '',
      keys: {},                     // frames marcados a mano (verdad)
      track: {},                    // frames interpolados / trackeados
      source: 'manual',             // 'manual' | 'auto'
      visible: true,
      locked: false,
      score: 1
    };
    o.keys[frame] = pts.map(function (p) { return [p[0], p[1]]; });
    o.name = (cls + '_' + (A.state.objects.filter(function (x) { return x.cls === cls; }).length + 1));
    return o;
  };

  /* Devuelve los puntos de un objeto en un frame:
     - keyframe exacto -> verdad
     - entre dos keyframes -> interpolacion lineal
     - trackeado -> cache
     - fuera de rango -> extrapolacion al keyframe mas cercano          */
  A.objAt = function (o, frame) {
    if (o.keys[frame]) return o.keys[frame];
    if (o.track[frame]) return o.track[frame];
    var ks = Object.keys(o.keys).map(Number).sort(function (a, b) { return a - b; });
    if (!ks.length) return null;
    if (frame <= ks[0]) return o.keys[ks[0]];
    if (frame >= ks[ks.length - 1]) return o.keys[ks[ks.length - 1]];
    var lo = ks[0], hi = ks[ks.length - 1];
    for (var i = 0; i < ks.length - 1; i++) if (ks[i] <= frame && ks[i + 1] >= frame) { lo = ks[i]; hi = ks[i + 1]; break; }
    var t = (frame - lo) / ((hi - lo) || 1), a = o.keys[lo], b = o.keys[hi];
    if (a.length !== b.length) return a;
    return a.map(function (p, i) { return [A.lerp(p[0], b[i][0], t), A.lerp(p[1], b[i][1], t)]; });
  };
  A.isKey = function (o, f) { return !!o.keys[f]; };
  A.setKey = function (o, f, pts) {
    o.keys[f] = pts.map(function (p) { return [p[0], p[1]]; });
    delete o.track[f];
    A.state.dirty = true;
  };
  A.selected = function () {
    var id = A.state.selectedId;
    for (var i = 0; i < A.state.objects.length; i++) if (A.state.objects[i].id === id) return A.state.objects[i];
    return null;
  };
})(window.A3D);
