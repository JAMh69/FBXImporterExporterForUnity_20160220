/* AUTO3D - tracking.js : Lucas-Kanade piramidal para seguir puntos,
   aristas y vertices de planos fotograma a fotograma. */
(function (A) {
  'use strict';
  var T = A.track = {};

  function bilinear(img, w, h, x, y) {
    if (x < 0) x = 0; if (y < 0) y = 0;
    if (x > w - 1.001) x = w - 1.001; if (y > h - 1.001) y = h - 1.001;
    var x0 = x | 0, y0 = y | 0, fx = x - x0, fy = y - y0, i = y0 * w + x0;
    var a = img[i], b = img[i + 1], c = img[i + w], d = img[i + w + 1];
    return a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy;
  }
  T.bilinear = bilinear;

  /* reduccion 2x con filtro [1 4 6 4 1]/16 separable (piramide gaussiana) */
  function halve(src, w, h) {
    var w2 = Math.max(1, w >> 1), h2 = Math.max(1, h >> 1);
    var tmp = new Float32Array(w2 * h), k = [1, 4, 6, 4, 1], ks = 16, x, y, i, acc, xx;
    for (y = 0; y < h; y++) for (x = 0; x < w2; x++) {
      acc = 0;
      for (i = -2; i <= 2; i++) { xx = A.clamp(2 * x + i, 0, w - 1); acc += src[y * w + xx] * k[i + 2]; }
      tmp[y * w2 + x] = acc / ks;
    }
    var out = new Float32Array(w2 * h2), yy;
    for (y = 0; y < h2; y++) for (x = 0; x < w2; x++) {
      acc = 0;
      for (i = -2; i <= 2; i++) { yy = A.clamp(2 * y + i, 0, h - 1); acc += tmp[yy * w2 + x] * k[i + 2]; }
      out[y * w2 + x] = acc / ks;
    }
    return { data: out, w: w2, h: h2 };
  }

  T.pyramid = function (gray, w, h, levels) {
    var p = [{ data: gray, w: w, h: h }];
    for (var i = 1; i < levels; i++) {
      var prev = p[i - 1];
      if (prev.w < 32 || prev.h < 32) break;
      p.push(halve(prev.data, prev.w, prev.h));
    }
    return p;
  };

  /* Sigue una lista de puntos [[x,y],...] de pyrA a pyrB.
     Devuelve [{x,y,ok,err}] en coordenadas del nivel 0. */
  T.lk = function (pyrA, pyrB, pts, winSize, maxIter) {
    winSize = winSize || 11; maxIter = maxIter || 20;
    var hw = winSize >> 1, L = Math.min(pyrA.length, pyrB.length);
    var res = pts.map(function (p) { return { x: p[0], y: p[1], ok: true, err: 0 }; });

    for (var n = 0; n < pts.length; n++) {
      var g = [0, 0];                                  // desplazamiento acumulado
      var okAll = true, finalErr = 0;
      for (var lev = L - 1; lev >= 0; lev--) {
        var IA = pyrA[lev], IB = pyrB[lev], sc = 1 / Math.pow(2, lev);
        var px = pts[n][0] * sc, py = pts[n][1] * sc;
        g = [g[0] * 2, g[1] * 2];                      // subir de nivel duplica
        if (lev === L - 1) g = [0, 0];
        if (px < hw + 1 || py < hw + 1 || px > IA.w - hw - 2 || py > IA.h - hw - 2) { okAll = false; break; }
        // matriz de estructura sobre la ventana en A
        var Ixx = 0, Iyy = 0, Ixy = 0, gxs = [], gys = [], ref = [], idx = 0, dx, dy, ix, iy, v;
        for (dy = -hw; dy <= hw; dy++) for (dx = -hw; dx <= hw; dx++) {
          ix = (bilinear(IA.data, IA.w, IA.h, px + dx + 1, py + dy) - bilinear(IA.data, IA.w, IA.h, px + dx - 1, py + dy)) * 0.5;
          iy = (bilinear(IA.data, IA.w, IA.h, px + dx, py + dy + 1) - bilinear(IA.data, IA.w, IA.h, px + dx, py + dy - 1)) * 0.5;
          gxs[idx] = ix; gys[idx] = iy; ref[idx] = bilinear(IA.data, IA.w, IA.h, px + dx, py + dy);
          Ixx += ix * ix; Iyy += iy * iy; Ixy += ix * iy; idx++;
        }
        var det = Ixx * Iyy - Ixy * Ixy;
        var minEig = 0.5 * ((Ixx + Iyy) - Math.sqrt((Ixx - Iyy) * (Ixx - Iyy) + 4 * Ixy * Ixy)) / (winSize * winSize);
        if (det < 1e-6 || minEig < 0.0015) { okAll = false; break; }   // textura insuficiente
        for (var it = 0; it < maxIter; it++) {
          var bx = 0, by = 0, err = 0; idx = 0;
          var qx = px + g[0], qy = py + g[1];
          if (qx < 1 || qy < 1 || qx > IB.w - 2 || qy > IB.h - 2) { okAll = false; break; }
          for (dy = -hw; dy <= hw; dy++) for (dx = -hw; dx <= hw; dx++) {
            v = ref[idx] - bilinear(IB.data, IB.w, IB.h, qx + dx, qy + dy);
            bx += v * gxs[idx]; by += v * gys[idx]; err += Math.abs(v); idx++;
          }
          var ux = (Iyy * bx - Ixy * by) / det, uy = (Ixx * by - Ixy * bx) / det;
          g = [g[0] + ux, g[1] + uy];
          finalErr = err / (winSize * winSize);
          if (Math.hypot(ux, uy) < 0.01) break;
        }
        if (!okAll) break;
      }
      if (okAll) {
        res[n].x = pts[n][0] + g[0];
        res[n].y = pts[n][1] + g[1];
        res[n].err = finalErr;
        res[n].ok = finalErr < 42;
      } else { res[n].ok = false; }
    }
    return res;
  };

  /* Comprobacion ida-vuelta: sigue A->B y despues B->A. Si el punto no
     vuelve a su sitio (mas de fbTol px) el emparejamiento se descarta.
     Es lo que evita que una fachada con ventanas repetidas "enganche" en
     la ventana equivocada sin avisar. */
  T.lkFB = function (pyrA, pyrB, pts, winSize, fbTol) {
    fbTol = (fbTol == null) ? 1.6 : fbTol;
    var fwd = T.lk(pyrA, pyrB, pts, winSize, 30);
    var back = T.lk(pyrB, pyrA, fwd.map(function (r) { return [r.x, r.y]; }), winSize, 30);
    for (var i = 0; i < fwd.length; i++) {
      var d = Math.hypot(back[i].x - pts[i][0], back[i].y - pts[i][1]);
      fwd[i].fb = d;
      if (!back[i].ok || d > fbTol) fwd[i].ok = false;
    }
    return fwd;
  };

  /* Propaga todos los objetos visibles de frameA a frameB usando LK.
     grayA/grayB son Float32Array a resolucion de PROCESO; los puntos de los
     objetos se guardan en coordenadas normalizadas de imagen original, asi
     que se escalan a/desde el espacio de proceso. */
  T.propagate = function (objs, frameA, frameB, pyrA, pyrB, scale, P) {
    var flat = [], map = [];
    objs.forEach(function (o) {
      if (o.locked || !o.visible) return;
      if (o.keys[frameB]) return;                    // ya hay verdad en destino
      var pts = A.objAt(o, frameA);
      if (!pts) return;
      pts.forEach(function (p, i) { flat.push([p[0] * scale, p[1] * scale]); map.push({ o: o, i: i }); });
    });
    if (!flat.length) return { moved: 0, lost: 0 };
    var r = T.lkFB(pyrA, pyrB, flat, P.trackWin, P.fbTol == null ? 1.6 : P.fbTol);
    var buf = {}, lost = 0;
    r.forEach(function (res, k) {
      var m = map[k], o = m.o;
      if (!buf[o.id]) buf[o.id] = { o: o, pts: [], ok: 0, tot: 0 };
      buf[o.id].tot++;
      if (res.ok) buf[o.id].ok++; else lost++;
      buf[o.id].pts[m.i] = [res.x / scale, res.y / scale];
    });
    var moved = 0;
    Object.keys(buf).forEach(function (id) {
      var e = buf[id];
      if (e.ok / e.tot >= 0.5) {                     // mayoria de vertices validos
        e.o.track[frameB] = e.pts;
        moved++;
      }
    });
    return { moved: moved, lost: lost };
  };
})(window.A3D);
