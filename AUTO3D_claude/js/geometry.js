/* AUTO3D - geometry.js : puntos de fuga, calibracion monocular,
   hipotesis de planos y reconstruccion 3D de un solo punto de vista. */
(function (A) {
  'use strict';
  var G = A.geom = {};

  /* Direccion (unitaria) desde el punto medio de un segmento hacia un vp
     homogeneo. Si vp esta en el infinito (w~0) la direccion es la propia
     del vp. */
  function dirToVP(seg, vp) {
    var mx = (seg.p[0] + seg.q[0]) / 2, my = (seg.p[1] + seg.q[1]) / 2;
    var dx, dy;
    if (Math.abs(vp[2]) < 1e-9) { dx = vp[0]; dy = vp[1]; }
    else { dx = vp[0] / vp[2] - mx; dy = vp[1] / vp[2] - my; }
    var n = Math.hypot(dx, dy) || 1;
    return [dx / n, dy / n];
  }
  function segDir(s) { var dx = s.q[0] - s.p[0], dy = s.q[1] - s.p[1], n = Math.hypot(dx, dy) || 1; return [dx / n, dy / n]; }

  function angErr(s, vp) {
    var a = segDir(s), b = dirToVP(s, vp);
    var c = Math.abs(a[0] * b[0] + a[1] * b[1]);
    return Math.acos(A.clamp(c, -1, 1));   // 0..pi/2
  }

  /* ---------- RANSAC de puntos de fuga ----------
     Devuelve hasta 3 vps homogeneos con sus segmentos asignados.
     Ponderado por longitud: un muro largo pesa mas que un ruido corto. */
  G.findVPs = function (segs, P, w, h) {
    var pool = segs.slice(0, 400).filter(function (s) { return s.len >= P.minSegLen; });
    var tol = A.rad(P.vpInlierDeg), res = [], used = new Array(pool.length).fill(false);
    var iters = P.vpIters;

    for (var vpi = 0; vpi < 3; vpi++) {
      var avail = [];
      for (var i = 0; i < pool.length; i++) if (!used[i]) avail.push(i);
      if (avail.length < 6) break;
      var best = null, bestScore = 0;
      for (var it = 0; it < iters; it++) {
        var a = avail[(Math.random() * avail.length) | 0];
        var b = avail[(Math.random() * avail.length) | 0];
        if (a === b) continue;
        var v = A.cross3(pool[a].line, pool[b].line);
        var nn = Math.hypot(v[0], v[1], v[2]); if (nn < 1e-9) continue;
        v = [v[0] / nn, v[1] / nn, v[2] / nn];
        var score = 0;
        for (var k = 0; k < avail.length; k++) {
          var s = pool[avail[k]];
          if (angErr(s, v) < tol) score += s.len;
        }
        if (score > bestScore) { bestScore = score; best = v; }
      }
      if (!best) break;
      // refinamiento: minimos cuadrados sobre los inliers (SVD 3x3 por potencia inversa simplificada)
      var inl = [];
      for (var k2 = 0; k2 < avail.length; k2++) {
        var s2 = pool[avail[k2]];
        if (angErr(s2, best) < tol) inl.push(avail[k2]);
      }
      if (inl.length < 3) break;
      best = G.refineVP(inl.map(function (ix) { return pool[ix]; }), best);
      var lenSum = 0;
      inl.forEach(function (ix) { used[ix] = true; lenSum += pool[ix].len; pool[ix].vp = vpi; });
      res.push({ v: best, idx: inl, weight: lenSum, n: inl.length });
    }
    res.sort(function (x, y) { return y.weight - x.weight; });
    // marcar de nuevo el indice de vp tras la ordenacion
    segs.forEach(function (s) { s.vp = -1; });
    res.forEach(function (r, i) { r.idx.forEach(function (ix) { pool[ix].vp = i; }); });
    return res;
  };

  /* Minimiza sum w_i (l_i . v)^2 con |v|=1  ->  autovector minimo de M=sum w l l^T.
     Iteracion inversa de potencia con 3 pasos de eliminacion gaussiana. */
  G.refineVP = function (segsIn, v0) {
    var M = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
    segsIn.forEach(function (s) {
      var l = s.line, n = Math.hypot(l[0], l[1]) || 1;
      var L = [l[0] / n, l[1] / n, l[2] / n], wgt = s.len;
      for (var i = 0; i < 3; i++) for (var j = 0; j < 3; j++) M[i][j] += wgt * L[i] * L[j];
    });
    // traza para regularizar
    var tr = (M[0][0] + M[1][1] + M[2][2]) / 3 || 1;
    var v = v0.slice();
    for (var it = 0; it < 12; it++) {
      var Ashift = [
        [M[0][0] - 1e-6 * tr, M[0][1], M[0][2]],
        [M[1][0], M[1][1] - 1e-6 * tr, M[1][2]],
        [M[2][0], M[2][1], M[2][2] - 1e-6 * tr]
      ];
      var x = solve3(Ashift, v);
      if (!x) break;
      var n2 = Math.hypot(x[0], x[1], x[2]); if (n2 < 1e-12) break;
      v = [x[0] / n2, x[1] / n2, x[2] / n2];
    }
    return v;
  };
  function solve3(Ain, bIn) {
    var M = [Ain[0].slice(), Ain[1].slice(), Ain[2].slice()], b = bIn.slice(), i, j, k;
    for (i = 0; i < 3; i++) {
      var piv = i;
      for (j = i + 1; j < 3; j++) if (Math.abs(M[j][i]) > Math.abs(M[piv][i])) piv = j;
      if (Math.abs(M[piv][i]) < 1e-14) return null;
      if (piv !== i) { var t = M[i]; M[i] = M[piv]; M[piv] = t; var tb = b[i]; b[i] = b[piv]; b[piv] = tb; }
      for (j = i + 1; j < 3; j++) {
        var f = M[j][i] / M[i][i];
        for (k = i; k < 3; k++) M[j][k] -= f * M[i][k];
        b[j] -= f * b[i];
      }
    }
    var x = [0, 0, 0];
    for (i = 2; i >= 0; i--) {
      var s = b[i];
      for (j = i + 1; j < 3; j++) s -= M[i][j] * x[j];
      x[i] = s / M[i][i];
    }
    return x;
  }

  /* ---------- calibracion a partir de 2-3 vps ortogonales ----------
     pp = centro de imagen.  (u-pp).(v-pp) = -f^2  para vps ortogonales.
     Devuelve {f, pp, dirs[], vertIdx} o null si no hay pareja valida. */
  G.calibrate = function (vps, w, h) {
    var pp = [w / 2, h / 2];
    var fin = [];
    vps.forEach(function (r, i) {
      if (Math.abs(r.v[2]) > 1e-7) fin.push({ i: i, p: [r.v[0] / r.v[2], r.v[1] / r.v[2]] });
    });
    var fs = [];
    for (var a = 0; a < fin.length; a++) for (var b = a + 1; b < fin.length; b++) {
      var ua = [fin[a].p[0] - pp[0], fin[a].p[1] - pp[1]];
      var ub = [fin[b].p[0] - pp[0], fin[b].p[1] - pp[1]];
      var d = ua[0] * ub[0] + ua[1] * ub[1];
      if (d < -1) fs.push(Math.sqrt(-d));
    }
    var f = fs.length ? A.median(fs) : null;
    if (!f || !isFinite(f)) return null;
    // direcciones 3D de cada vp: d = K^-1 v normalizado
    var dirs = vps.map(function (r) {
      var v = r.v, x, y, z;
      if (Math.abs(v[2]) > 1e-9) { x = v[0] / v[2] - pp[0]; y = v[1] / v[2] - pp[1]; z = f; }
      else { x = v[0]; y = v[1]; z = 0; }
      return A.normalize3([x, y, z]);
    });
    // vp vertical = aquel cuya direccion tiene mayor |componente y| en imagen
    var vertIdx = 0, bestV = -1;
    dirs.forEach(function (d, i) {
      var m = Math.abs(d[1]) / (Math.hypot(d[0], d[1]) || 1e-9);
      if (m > bestV) { bestV = m; vertIdx = i; }
    });
    // signo: "arriba" en camara = y negativa
    var up = dirs[vertIdx].slice();
    if (up[1] > 0) up = [-up[0], -up[1], -up[2]];
    return { f: f, pp: pp, dirs: dirs, vertIdx: vertIdx, up: up, nFinite: fin.length, fSamples: fs.length };
  };

  /* Horizonte = linea de fuga del plano horizontal. Se obtiene de la
     direccion vertical con l = K^-T . up, asi que basta con tener 2 vps
     (no hacen falta los 3).  Si hay dos vps horizontales se usa la recta
     que los une, que es mas estable. */
  G.horizon = function (vps, calib) {
    if (!calib) return null;
    var others = [];
    vps.forEach(function (r, i) { if (i !== calib.vertIdx) others.push(r.v); });
    if (others.length >= 2) {
      var l = A.cross3(others[0], others[1]);
      if (Math.hypot(l[0], l[1]) > 1e-9) return l;
    }
    var u = calib.up, f = calib.f, cx = calib.pp[0], cy = calib.pp[1];
    return [u[0] / f, u[1] / f, u[2] - (cx * u[0] + cy * u[1]) / f];
  };

  /* ---------- hipotesis de planos (cuadrilateros de 2 familias de vp) ----------
     Para cada par (i,j) de familias, se toman las K rectas mas largas de cada
     una, se intersecan y se puntua cada cuadrilatero por el soporte de borde
     real de sus 4 lados. Se quedan los mejores no solapados. */
  G.planeCandidates = function (det, vps, P) {
    var segs = det.segs, w = det.w, h = det.h, out = [];
    if (vps.length < 2) return out;
    var K = 9;
    function familyLines(fi) {
      var list = segs.filter(function (s) { return s.vp === fi; });
      list.sort(function (a, b) { return b.len - a.len; });
      return list.slice(0, K);
    }
    for (var i = 0; i < vps.length; i++) {
      for (var j = i + 1; j < vps.length; j++) {
        var A1 = familyLines(i), B1 = familyLines(j);
        if (A1.length < 2 || B1.length < 2) continue;
        for (var a1 = 0; a1 < A1.length; a1++) for (var a2 = a1 + 1; a2 < A1.length; a2++) {
          for (var b1 = 0; b1 < B1.length; b1++) for (var b2 = b1 + 1; b2 < B1.length; b2++) {
            var c = [
              A.interLines(A1[a1].line, B1[b1].line),
              A.interLines(A1[a1].line, B1[b2].line),
              A.interLines(A1[a2].line, B1[b2].line),
              A.interLines(A1[a2].line, B1[b1].line)
            ];
            if (c.indexOf(null) >= 0) continue;
            var ok = true;
            for (var t = 0; t < 4; t++) {
              if (c[t][0] < -w * 0.25 || c[t][0] > w * 1.25 || c[t][1] < -h * 0.25 || c[t][1] > h * 1.25) { ok = false; break; }
            }
            if (!ok) continue;
            var area = Math.abs(A.polyArea(c));
            if (area < w * h * 0.012) continue;
            if (area > w * h * 0.94) continue;
            var sup = 0;
            for (var e = 0; e < 4; e++) sup += A.vision.edgeSupport(det.edges, w, h, c[e], c[(e + 1) % 4], 2);
            sup /= 4;
            if (sup < P.planeSupport) continue;
            out.push({ pts: c, score: sup, area: area, fam: [i, j], id: A.uid('cand') });
          }
        }
      }
    }
    out.sort(function (x, y) { return (y.score * Math.sqrt(y.area)) - (x.score * Math.sqrt(x.area)); });
    // supresion de solapados por distancia de centroides + area
    var keep = [];
    for (var k = 0; k < out.length && keep.length < P.maxPlanes; k++) {
      var cand = out[k], cc = A.polyCentroid(cand.pts), dup = false;
      for (var m = 0; m < keep.length; m++) {
        var kc = A.polyCentroid(keep[m].pts);
        var rad = Math.sqrt(Math.max(cand.area, keep[m].area)) * 0.45;
        if (A.dist(cc, kc) < rad) { dup = true; break; }
      }
      if (!dup) keep.push(cand);
    }
    return keep;
  };

  /* ---------- reconstruccion monocular ----------
     Hipotesis de Manhattan + altura de camara conocida.
     Suelo: X.up = -camH  (camara en el origen, mirando -z? no: modelo pinhole
     estandar con z hacia delante).  Para un pixel p el rayo es r = K^-1 p.   */
  G.ray = function (calib, p) {
    return [p[0] - calib.pp[0], p[1] - calib.pp[1], calib.f];
  };
  G.groundPoint = function (calib, p, camH) {
    var r = G.ray(calib, p), d = A.dot3(r, calib.up);
    if (d > -1e-6) return null;                     // por encima del horizonte
    var t = -camH / d;
    if (t <= 0 || !isFinite(t)) return null;
    return A.mul3(r, t);
  };
  G.planeHit = function (calib, p, n, d) {          // n.X = d
    var r = G.ray(calib, p), den = A.dot3(r, n);
    if (Math.abs(den) < 1e-9) return null;
    var t = d / den;
    if (t <= 0 || !isFinite(t)) return null;
    return A.mul3(r, t);
  };

  /* Reconstruye un poligono segun su clase.
     - horizontal (suelo): todos los vertices sobre el plano del suelo.
     - vertical (fachada, hueco, medianera): se anclan los 2 vertices mas
       bajos al suelo y se define el plano vertical que los contiene.
     - libre (cubierta, otro): se intenta plano vertical; si falla, se marca
       como no reconstruible (se exporta solo en 2D).
     Devuelve {pts3:[[x,y,z]...], method, warn} o {error:'...'}          */
  G.reconstructPoly = function (pts, cls, calib, camH) {
    if (!calib) return { error: 'sin calibracion (hacen falta 2 puntos de fuga ortogonales)' };
    var info = A.classById(cls), axis = info.axis;
    var i;
    if (axis === 'horizontal') {
      var out = [];
      for (i = 0; i < pts.length; i++) {
        var X = G.groundPoint(calib, pts[i], camH);
        if (!X) return { error: 'vertice por encima del horizonte: no se puede apoyar en el suelo' };
        out.push(X);
      }
      return { pts3: out, method: 'suelo' };
    }
    // plano vertical: anclar por los dos vertices mas bajos de la imagen
    var order = pts.map(function (p, k) { return { p: p, k: k }; })
                   .sort(function (a, b) { return b.p[1] - a.p[1]; });
    var b1 = G.groundPoint(calib, order[0].p, camH);
    var b2 = null, used = 1;
    for (i = 1; i < order.length && !b2; i++) {
      var cand = G.groundPoint(calib, order[i].p, camH);
      if (cand && A.dist(order[0].p, order[i].p) > 8) { b2 = cand; used = i; }
    }
    if (!b1 || !b2) return { error: 'no hay dos vertices apoyables en el suelo (base oculta o sobre el horizonte)' };
    var dirH = A.normalize3(A.sub3(b2, b1));
    var n = A.normalize3(A.cross3(dirH, calib.up));   // normal del plano vertical
    var d = A.dot3(n, b1);
    var pts3 = [];
    for (i = 0; i < pts.length; i++) {
      var Xi = G.planeHit(calib, pts[i], n, d);
      if (!Xi) return { error: 'vertice paralelo al plano: geometria degenerada' };
      pts3.push(Xi);
    }
    var warn = (axis === 'libre') ? 'clase sin eje definido: se ha supuesto plano vertical' : null;
    return { pts3: pts3, method: 'vertical', normal: n, warn: warn };
  };

  /* cambio a coordenadas de mundo alineadas con Manhattan (X,Y arriba,Z) */
  G.toWorld = function (calib, X) {
    var up = calib.up, ax = null, az = null;
    calib.dirs.forEach(function (d, i) {
      if (i === calib.vertIdx) return;
      if (!ax) ax = d; else if (!az) az = d;
    });
    if (!ax) ax = A.normalize3([1, 0, 0]);
    if (!az) az = A.normalize3(A.cross3(up, ax));
    ax = A.normalize3(A.sub3(ax, A.mul3(up, A.dot3(ax, up))));   // ortogonalizar
    az = A.normalize3(A.cross3(up, ax));
    return [A.dot3(X, ax), A.dot3(X, up) + 0, A.dot3(X, az)];
  };
})(window.A3D);
