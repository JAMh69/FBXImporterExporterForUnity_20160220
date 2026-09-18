/* AUTO3D - learn.js : extraccion de descriptores y clasificador softmax
   entrenado en el navegador con lo que marca el usuario en modo LEARN. */
(function (A) {
  'use strict';
  var L = A.learn = {};

  L.FEATNAMES = [
    'R', 'G', 'B', 'satMedia', 'lumMedia', 'lumStd',
    'densidadBorde', 'orient0', 'orient45', 'orient90', 'orient135',
    'cx', 'cy', 'areaRel', 'aspecto', 'sobreHorizonte', 'soporteBorde',
    'famVertical', 'famHoriz'
  ];
  var NF = L.FEATNAMES.length;

  function rgb2hsvS(r, g, b) {
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    return mx <= 0 ? 0 : (mx - mn) / mx;
  }

  /* Descriptor de una region poligonal (coords en espacio de PROCESO). */
  L.features = function (det, pts, calib, horizonY) {
    var w = det.w, h = det.h, img = det.img.data;
    var xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
    var x0 = Math.max(0, Math.floor(Math.min.apply(null, xs))), x1 = Math.min(w - 1, Math.ceil(Math.max.apply(null, xs)));
    var y0 = Math.max(0, Math.floor(Math.min.apply(null, ys))), y1 = Math.min(h - 1, Math.ceil(Math.max.apply(null, ys)));
    var bw = Math.max(1, x1 - x0), bh = Math.max(1, y1 - y0);
    var step = Math.max(1, Math.round(Math.sqrt(bw * bh) / 26));
    var n = 0, sr = 0, sg = 0, sb = 0, ss = 0, sl = 0, sl2 = 0, edg = 0;
    var ori = [0, 0, 0, 0], sob = det.sob;
    for (var y = y0; y <= y1; y += step) {
      for (var x = x0; x <= x1; x += step) {
        if (!A.pointInPoly([x, y], pts)) continue;
        var i = y * w + x, j = i * 4;
        var r = img[j] / 255, g = img[j + 1] / 255, b = img[j + 2] / 255;
        sr += r; sg += g; sb += b; ss += rgb2hsvS(r, g, b);
        var lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
        sl += lum; sl2 += lum * lum;
        if (det.edges[i]) {
          edg++;
          var ang = ((Math.atan2(sob.gy[i], sob.gx[i]) * 180 / Math.PI) + 180) % 180;
          var bin = ang < 22.5 || ang >= 157.5 ? 0 : (ang < 67.5 ? 1 : (ang < 112.5 ? 2 : 3));
          ori[bin]++;
        }
        n++;
      }
    }
    if (!n) n = 1;
    var lm = sl / n, lv = Math.max(0, sl2 / n - lm * lm);
    var oriTot = ori[0] + ori[1] + ori[2] + ori[3] || 1;
    var cen = A.polyCentroid(pts);
    var area = Math.abs(A.polyArea(pts));
    // soporte de borde medio de los lados del poligono
    var sup = 0;
    for (var k = 0; k < pts.length; k++) sup += A.vision.edgeSupport(det.edges, w, h, pts[k], pts[(k + 1) % pts.length], 2);
    sup /= pts.length;
    // alineacion de los lados con la familia vertical / horizontal de vps
    var famV = 0, famH = 0;
    for (var e = 0; e < pts.length; e++) {
      var p = pts[e], q = pts[(e + 1) % pts.length];
      var ang2 = Math.abs(Math.atan2(q[1] - p[1], q[0] - p[0]) * 180 / Math.PI);
      if (ang2 > 90) ang2 = 180 - ang2;
      if (ang2 > 60) famV++; else if (ang2 < 30) famH++;
    }
    famV /= pts.length; famH /= pts.length;
    var hy = (horizonY == null) ? h * 0.5 : horizonY;
    return [
      sr / n, sg / n, sb / n, ss / n, lm, Math.sqrt(lv),
      edg / n, ori[0] / oriTot, ori[1] / oriTot, ori[2] / oriTot, ori[3] / oriTot,
      cen[0] / w, cen[1] / h, area / (w * h), bw / bh,
      (cen[1] - hy) / h, sup, famV, famH
    ];
  };

  /* ---------- modelo softmax ---------- */
  L.newModel = function () {
    return { classes: [], W: null, mu: null, sd: null, samples: [], epochs: 0, acc: 0, version: 2 };
  };

  L.addSample = function (model, feat, cls) {
    model.samples.push({ f: feat, c: cls, t: Date.now() });
    if (model.classes.indexOf(cls) < 0) model.classes.push(cls);
  };

  function standardize(model) {
    var N = model.samples.length, mu = new Float64Array(NF), sd = new Float64Array(NF), i, k;
    for (i = 0; i < N; i++) for (k = 0; k < NF; k++) mu[k] += model.samples[i].f[k];
    for (k = 0; k < NF; k++) mu[k] /= N;
    for (i = 0; i < N; i++) for (k = 0; k < NF; k++) { var d = model.samples[i].f[k] - mu[k]; sd[k] += d * d; }
    for (k = 0; k < NF; k++) sd[k] = Math.sqrt(sd[k] / N) || 1;
    model.mu = Array.from(mu); model.sd = Array.from(sd);
  }
  function z(model, f) {
    var o = new Float64Array(NF + 1);
    for (var k = 0; k < NF; k++) o[k] = (f[k] - model.mu[k]) / model.sd[k];
    o[NF] = 1;                                   // sesgo
    return o;
  }
  function softmax(s) {
    var m = -Infinity, i;
    for (i = 0; i < s.length; i++) if (s[i] > m) m = s[i];
    var sum = 0;
    for (i = 0; i < s.length; i++) { s[i] = Math.exp(s[i] - m); sum += s[i]; }
    for (i = 0; i < s.length; i++) s[i] /= sum;
    return s;
  }

  /* Entrena por descenso de gradiente; hold-out del 25% si hay datos de sobra. */
  L.train = function (model, epochs, lr, l2) {
    epochs = epochs || 400; lr = lr || 0.25; l2 = (l2 == null) ? 0.004 : l2;
    var N = model.samples.length, C = model.classes.length;
    if (N < 4 || C < 2) return { ok: false, msg: 'hacen falta al menos 4 muestras y 2 clases distintas' };
    standardize(model);
    var D = NF + 1;
    var W = [];
    for (var c = 0; c < C; c++) { W[c] = new Float64Array(D); }
    var idx = model.samples.map(function (_, i) { return i; });
    // barajado determinista por tiempo de creacion para reproducibilidad
    idx.sort(function (a, b) { return model.samples[a].t - model.samples[b].t; });
    var nTest = (N >= 12) ? Math.max(2, Math.round(N * 0.25)) : 0;
    var test = idx.slice(N - nTest), train = idx.slice(0, N - nTest);
    if (!train.length) train = idx;
    var X = {}, Y = {};
    idx.forEach(function (i) { X[i] = z(model, model.samples[i].f); Y[i] = model.classes.indexOf(model.samples[i].c); });

    for (var ep = 0; ep < epochs; ep++) {
      var G = [];
      for (c = 0; c < C; c++) G[c] = new Float64Array(D);
      for (var t = 0; t < train.length; t++) {
        var i2 = train[t], x = X[i2], y = Y[i2], s = new Float64Array(C);
        for (c = 0; c < C; c++) { var sum = 0; for (var d = 0; d < D; d++) sum += W[c][d] * x[d]; s[c] = sum; }
        softmax(s);
        for (c = 0; c < C; c++) {
          var err = s[c] - (c === y ? 1 : 0);
          for (d = 0; d < D; d++) G[c][d] += err * x[d];
        }
      }
      var eta = lr / (1 + ep * 0.004);
      for (c = 0; c < C; c++) for (d = 0; d < D; d++) {
        W[c][d] -= eta * (G[c][d] / train.length + (d < NF ? l2 * W[c][d] : 0));
      }
    }
    model.W = W.map(function (r) { return Array.from(r); });
    model.epochs += epochs;
    // precision
    function accuracy(list) {
      if (!list.length) return null;
      var good = 0;
      list.forEach(function (i) {
        var p = L.predictFeat(model, model.samples[i].f);
        if (p && p[0].cls === model.samples[i].c) good++;
      });
      return good / list.length;
    }
    var trAcc = accuracy(train), teAcc = accuracy(test);
    model.acc = (teAcc == null ? trAcc : teAcc);
    return {
      ok: true, n: N, classes: C,
      trainAcc: trAcc, testAcc: teAcc, nTest: nTest,
      msg: 'entrenado con ' + N + ' muestras / ' + C + ' clases'
    };
  };

  L.predictFeat = function (model, f) {
    if (!model || !model.W || !model.mu) return null;
    var x = z(model, f), C = model.classes.length, s = new Float64Array(C), D = NF + 1;
    for (var c = 0; c < C; c++) { var a = 0; for (var d = 0; d < D; d++) a += model.W[c][d] * x[d]; s[c] = a; }
    softmax(s);
    var out = [];
    for (c = 0; c < C; c++) out.push({ cls: model.classes[c], p: s[c] });
    out.sort(function (a2, b2) { return b2.p - a2.p; });
    return out;
  };

  L.predictPoly = function (model, det, pts, calib, horizonY) {
    if (!model || !model.W) return null;
    return L.predictFeat(model, L.features(det, pts, calib, horizonY));
  };

  /* persistencia */
  L.save = function (model) {
    try { localStorage.setItem('auto3d.model', JSON.stringify(model)); return true; }
    catch (e) { return false; }
  };
  L.load = function () {
    try {
      var s = localStorage.getItem('auto3d.model');
      if (!s) return null;
      var m = JSON.parse(s);
      if (!m || !m.samples) return null;
      // los descriptores cambiaron de tamano entre versiones: descartar incompatibles
      if (m.samples.length && m.samples[0].f.length !== NF) return null;
      return m;
    } catch (e) { return null; }
  };
})(window.A3D);
