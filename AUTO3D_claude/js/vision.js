/* AUTO3D - vision.js : procesado de imagen puro en JS.
   grises -> gauss -> sobel -> NMS -> histeresis -> cadenas -> segmentos rectos. */
(function (A) {
  'use strict';
  var V = A.vision = {};

  /* ---------- conversion a luminancia (Rec.709) ---------- */
  V.toGray = function (img) {
    var d = img.data, n = img.width * img.height, g = new Float32Array(n);
    for (var i = 0, j = 0; i < n; i++, j += 4) {
      g[i] = 0.2126 * d[j] + 0.7152 * d[j + 1] + 0.0722 * d[j + 2];
    }
    return g;
  };

  /* ---------- gauss separable ---------- */
  V.gauss = function (src, w, h, sigma) {
    if (sigma <= 0.05) return src.slice();
    var r = Math.max(1, Math.ceil(sigma * 3)), k = new Float32Array(2 * r + 1), s = 0, i, j;
    for (i = -r; i <= r; i++) { var v = Math.exp(-(i * i) / (2 * sigma * sigma)); k[i + r] = v; s += v; }
    for (i = 0; i < k.length; i++) k[i] /= s;
    var tmp = new Float32Array(w * h), out = new Float32Array(w * h), x, y, acc, xx, yy;
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      acc = 0;
      for (i = -r; i <= r; i++) { xx = A.clamp(x + i, 0, w - 1); acc += src[y * w + xx] * k[i + r]; }
      tmp[y * w + x] = acc;
    }
    for (y = 0; y < h; y++) for (x = 0; x < w; x++) {
      acc = 0;
      for (j = -r; j <= r; j++) { yy = A.clamp(y + j, 0, h - 1); acc += tmp[yy * w + x] * k[j + r]; }
      out[y * w + x] = acc;
    }
    return out;
  };

  /* ---------- sobel ---------- */
  V.sobel = function (g, w, h) {
    var gx = new Float32Array(w * h), gy = new Float32Array(w * h), mag = new Float32Array(w * h);
    var maxm = 1e-6;
    for (var y = 1; y < h - 1; y++) {
      for (var x = 1; x < w - 1; x++) {
        var i = y * w + x;
        var a = g[i - w - 1], b = g[i - w], c = g[i - w + 1];
        var d = g[i - 1], f = g[i + 1];
        var p = g[i + w - 1], q = g[i + w], r = g[i + w + 1];
        var sx = (c + 2 * f + r) - (a + 2 * d + p);
        var sy = (p + 2 * q + r) - (a + 2 * b + c);
        gx[i] = sx; gy[i] = sy;
        var m = Math.sqrt(sx * sx + sy * sy);
        mag[i] = m; if (m > maxm) maxm = m;
      }
    }
    return { gx: gx, gy: gy, mag: mag, max: maxm };
  };

  /* ---------- Canny: NMS + histeresis. Devuelve Uint8Array 0/255 ---------- */
  V.canny = function (s, w, h, lo, hi) {
    var mag = s.mag, gx = s.gx, gy = s.gy, max = s.max;
    var TL = lo * max, TH = hi * max;
    var nms = new Float32Array(w * h);
    for (var y = 1; y < h - 1; y++) {
      for (var x = 1; x < w - 1; x++) {
        var i = y * w + x, m = mag[i];
        if (m < TL) continue;
        var ang = Math.atan2(gy[i], gx[i]);
        var a = ((ang * 180 / Math.PI) + 180) % 180;      // 0..180
        var m1, m2;
        if (a < 22.5 || a >= 157.5) { m1 = mag[i - 1]; m2 = mag[i + 1]; }
        else if (a < 67.5) { m1 = mag[i - w + 1]; m2 = mag[i + w - 1]; }
        else if (a < 112.5) { m1 = mag[i - w]; m2 = mag[i + w]; }
        else { m1 = mag[i - w - 1]; m2 = mag[i + w + 1]; }
        if (m >= m1 && m >= m2) nms[i] = m;
      }
    }
    var out = new Uint8Array(w * h), stack = [], k;
    for (k = 0; k < nms.length; k++) if (nms[k] >= TH) { out[k] = 255; stack.push(k); }
    while (stack.length) {
      var idx = stack.pop(), yy = (idx / w) | 0, xx = idx % w;
      for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
        var nx = xx + dx, ny = yy + dy;
        if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
        var ni = ny * w + nx;
        if (!out[ni] && nms[ni] >= TL) { out[ni] = 255; stack.push(ni); }
      }
    }
    return out;
  };

  /* ---------- encadenado de pixeles de borde ----------
     Recorrido 8-conexo desde extremos; devuelve arrays de puntos ordenados. */
  V.chains = function (edges, w, h, minLen) {
    var visited = new Uint8Array(w * h), chains = [], N = [-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1];
    function nbrCount(i) {
      var c = 0;
      for (var k = 0; k < 8; k++) { var j = i + N[k]; if (j >= 0 && j < edges.length && edges[j]) c++; }
      return c;
    }
    function walk(start) {
      var chain = [], cur = start;
      while (cur >= 0) {
        visited[cur] = 1;
        chain.push([cur % w, (cur / w) | 0]);
        var next = -1, bestC = -1;
        for (var k = 0; k < 8; k++) {
          var j = cur + N[k];
          if (j < 0 || j >= edges.length || !edges[j] || visited[j]) continue;
          // evitar saltos de fila por el borde
          var cx = cur % w, jx = j % w;
          if (Math.abs(cx - jx) > 1) continue;
          var c = (k === 1 || k === 3 || k === 4 || k === 6) ? 2 : 1;  // preferir 4-vecinos
          if (c > bestC) { bestC = c; next = j; }
        }
        cur = next;
      }
      return chain;
    }
    var i, x, y;
    // 1) desde extremos (1 vecino)
    for (y = 1; y < h - 1; y++) for (x = 1; x < w - 1; x++) {
      i = y * w + x;
      if (edges[i] && !visited[i] && nbrCount(i) === 1) {
        var c1 = walk(i); if (c1.length >= minLen) chains.push(c1);
      }
    }
    // 2) restos (bucles cerrados)
    for (y = 1; y < h - 1; y++) for (x = 1; x < w - 1; x++) {
      i = y * w + x;
      if (edges[i] && !visited[i]) {
        var c2 = walk(i); if (c2.length >= minLen) chains.push(c2);
      }
    }
    return chains;
  };

  /* ---------- Douglas-Peucker: parte cadenas en tramos rectos ---------- */
  function dp(pts, a, b, tol, out) {
    var maxd = -1, idx = -1;
    for (var i = a + 1; i < b; i++) {
      var d = A.distToSeg(pts[i], pts[a], pts[b]);
      if (d > maxd) { maxd = d; idx = i; }
    }
    if (maxd > tol && idx > 0) { dp(pts, a, idx, tol, out); dp(pts, idx, b, tol, out); }
    else out.push([a, b]);
  }

  /* ---------- segmentos rectos con orientacion de gradiente ---------- */
  V.segments = function (chains, s, w, minLen, tol) {
    var segs = [];
    chains.forEach(function (ch) {
      var parts = [];
      dp(ch, 0, ch.length - 1, tol, parts);
      parts.forEach(function (pr) {
        var p = ch[pr[0]], q = ch[pr[1]];
        var dx = q[0] - p[0], dy = q[1] - p[1], L = Math.sqrt(dx * dx + dy * dy);
        if (L < minLen) return;
        // fuerza media del gradiente a lo largo del tramo
        var acc = 0, n = 0;
        for (var t = 0; t <= 1.0001; t += 1 / Math.max(2, Math.round(L / 2))) {
          var xi = Math.round(p[0] + dx * t), yi = Math.round(p[1] + dy * t);
          acc += s.mag[yi * w + xi] || 0; n++;
        }
        segs.push({
          p: [p[0], p[1]], q: [q[0], q[1]], len: L,
          ang: Math.atan2(dy, dx),
          str: n ? acc / n / s.max : 0,
          line: A.lineOf(p, q),
          vp: -1
        });
      });
    });
    segs.sort(function (a, b) { return b.len - a.len; });
    return segs;
  };

  /* ---------- pipeline completo sobre un ImageData ---------- */
  V.process = function (img, P) {
    var w = img.width, h = img.height;
    var g0 = V.toGray(img);
    var g = V.gauss(g0, w, h, P.blur);
    var s = V.sobel(g, w, h);
    var edges = V.canny(s, w, h, P.cannyLo, P.cannyHi);
    var ch = V.chains(edges, w, h, Math.max(6, P.minSegLen * 0.4));
    var segs = V.segments(ch, s, w, P.minSegLen, P.dpTol);
    return { w: w, h: h, gray: g0, smooth: g, sob: s, edges: edges, chains: ch, segs: segs };
  };

  /* ---------- soporte de borde a lo largo de un segmento (0..1) ----------
     Fraccion de muestras con un pixel de borde a <=tol px. Es la metrica
     con la que se puntuan los planos candidatos. */
  V.edgeSupport = function (edges, w, h, p, q, tol) {
    tol = tol || 2;
    var dx = q[0] - p[0], dy = q[1] - p[1], L = Math.sqrt(dx * dx + dy * dy);
    if (L < 2) return 0;
    var n = Math.max(4, Math.round(L / 2)), hit = 0;
    for (var i = 0; i <= n; i++) {
      var t = i / n, x = p[0] + dx * t, y = p[1] + dy * t, found = false;
      for (var oy = -tol; oy <= tol && !found; oy++) for (var ox = -tol; ox <= tol; ox++) {
        var xi = Math.round(x + ox), yi = Math.round(y + oy);
        if (xi < 0 || yi < 0 || xi >= w || yi >= h) continue;
        if (edges[yi * w + xi]) { found = true; break; }
      }
      if (found) hit++;
    }
    return hit / (n + 1);
  };
})(window.A3D);
