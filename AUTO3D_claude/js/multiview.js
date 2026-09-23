/* AUTO3D - multiview.js : medir en metros marcando el mismo punto en varias
   fotos, con las poses que vienen en los metadatos del dron.

   Es el mismo calculo que `python/vision_teach/multiview.py`, portado para que
   la app mida sin depender de nada instalado. La diferencia con `tracking.js`
   importa: alli una marca se arrastra de un fotograma al siguiente y el error
   se acumula; aqui dos marcas se cortan en el espacio y no hay cadena.

   Mundo en ENU (este, norte, arriba). Camara con x a la derecha, y hacia abajo
   y z hacia delante, que es el convenio de OpenCV y de COLMAP. */
(function (A) {
  'use strict';
  var M = A.mv = {};
  var EPS = 1e-12;
  var TIERRA = 6378137;

  /* ---------- algebra minima ---------- */
  function mulMV(R, v) {
    return [R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
            R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
            R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2]];
  }
  function mulMtV(R, v) {                       // R transpuesta por vector
    return [R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2],
            R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2],
            R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2]];
  }
  function resta(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
  function suma(a, b) { return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]; }
  function escala(a, s) { return [a[0] * s, a[1] * s, a[2] * s]; }
  function norma(a) { return Math.hypot(a[0], a[1], a[2]); }
  function unitario(a) { var n = norma(a) || 1; return escala(a, 1 / n); }
  function cruz(a, b) {
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  }
  M.resta = resta; M.norma = norma; M.unitario = unitario; M.cruz = cruz;

  /* ---------- camara con pose ---------- */
  function Camara(focal, principal, R, t, nombre, tam) {
    this.f = (typeof focal === 'number') ? [focal, focal] : focal.slice();
    this.pp = principal.slice();
    this.R = R.map(function (fila) { return fila.slice(); });
    this.t = t.slice();
    this.nombre = nombre || '';
    this.tam = tam || null;
  }
  M.Camara = Camara;

  Camara.prototype.centro = function () {
    return escala(mulMtV(this.R, this.t), -1);
  };
  /* Devuelve {px:[x,y], delante:bool}. Un punto detras del objetivo se
     proyecta igualmente en la formula, y sin ese aviso apareceria en pantalla
     como si se viera. */
  Camara.prototype.proyectar = function (X) {
    var c = suma(mulMV(this.R, X), this.t);
    var z = Math.abs(c[2]) < EPS ? EPS : c[2];
    return { px: [this.f[0] * c[0] / z + this.pp[0], this.f[1] * c[1] / z + this.pp[1]],
             delante: c[2] > 0, prof: c[2] };
  };
  Camara.prototype.rayo = function (px) {
    return unitario(mulMtV(this.R, [(px[0] - this.pp[0]) / this.f[0],
                                    (px[1] - this.pp[1]) / this.f[1], 1]));
  };
  Camara.prototype.ve = function (X, margen) {
    var p = this.proyectar(X);
    if (!p.delante) return false;
    if (!this.tam) return true;
    margen = margen || 0;
    return p.px[0] >= -margen && p.px[0] < this.tam[0] + margen &&
           p.px[1] >= -margen && p.px[1] < this.tam[1] + margen;
  };
  Camara.prototype.matriz = function () {           // 3x4
    var f = this.f, pp = this.pp, R = this.R, t = this.t, P = [];
    for (var i = 0; i < 3; i++) {
      var k = i === 0 ? f[0] : (i === 1 ? f[1] : 1);
      var c = i === 2 ? 0 : pp[i];
      P.push([k * R[i][0] + c * R[2][0], k * R[i][1] + c * R[2][1],
              k * R[i][2] + c * R[2][2], k * t[i] + c * t[2]]);
    }
    return P;
  };

  /* ---------- triangulacion ---------- */
  /* DLT para arrancar y despues minimizacion del error de reproyeccion. El DLT
     minimiza un residuo algebraico que no es el error en pixeles; sin refinar,
     una vista muy oblicua sesga el resultado. */
  M.triangular = function (camaras, pixeles, refinar) {
    if (camaras.length < 2) throw new Error('hacen falta al menos dos vistas');
    var filas = [];
    for (var i = 0; i < camaras.length; i++) {
      var P = camaras[i].matriz(), u = pixeles[i][0], v = pixeles[i][1];
      filas.push([u * P[2][0] - P[0][0], u * P[2][1] - P[0][1],
                  u * P[2][2] - P[0][2], u * P[2][3] - P[0][3]]);
      filas.push([v * P[2][0] - P[1][0], v * P[2][1] - P[1][1],
                  v * P[2][2] - P[1][2], v * P[2][3] - P[1][3]]);
    }
    var h = menorAutovector(filas);
    if (Math.abs(h[3]) < EPS) throw new Error('rayos casi paralelos: las vistas estan demasiado juntas');
    var X = [h[0] / h[3], h[1] / h[3], h[2] / h[3]];
    return refinar === false ? X : refinarPunto(camaras, pixeles, X);
  };

  /* Autovector del menor autovalor de A^T A, por rotaciones de Jacobi.

     La primera version usaba iteracion de potencia sobre (cI - A^T A) y
     fallaba en silencio: con camaras a decenas de metros los dos autovalores
     mayores quedan casi iguales tras el desplazamiento, la iteracion no
     converge y el punto salia a 94 m de donde estaba. Jacobi no tiene ese
     problema con matrices simetricas y una 4x4 cuesta nada. */
  function menorAutovector(filas) {
    var n = 4, i, j, k, p, q;
    var Ax = [];
    for (i = 0; i < n; i++) Ax.push(new Float64Array(n));
    filas.forEach(function (f) {
      for (var a = 0; a < n; a++) for (var b = 0; b < n; b++) Ax[a][b] += f[a] * f[b];
    });
    var V = [];
    for (i = 0; i < n; i++) { V.push(new Float64Array(n)); V[i][i] = 1; }

    for (var barrido = 0; barrido < 60; barrido++) {
      var fuera = 0;
      for (p = 0; p < n - 1; p++) for (q = p + 1; q < n; q++) fuera += Ax[p][q] * Ax[p][q];
      if (fuera < 1e-30) break;
      for (p = 0; p < n - 1; p++) {
        for (q = p + 1; q < n; q++) {
          if (Math.abs(Ax[p][q]) < 1e-300) continue;
          var theta = (Ax[q][q] - Ax[p][p]) / (2 * Ax[p][q]);
          var t = Math.sign(theta || 1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
          var c = 1 / Math.sqrt(t * t + 1), sN = t * c;
          for (k = 0; k < n; k++) {
            var akp = Ax[k][p], akq = Ax[k][q];
            Ax[k][p] = c * akp - sN * akq;
            Ax[k][q] = sN * akp + c * akq;
          }
          for (k = 0; k < n; k++) {
            var apk = Ax[p][k], aqk = Ax[q][k];
            Ax[p][k] = c * apk - sN * aqk;
            Ax[q][k] = sN * apk + c * aqk;
          }
          for (k = 0; k < n; k++) {
            var vkp = V[k][p], vkq = V[k][q];
            V[k][p] = c * vkp - sN * vkq;
            V[k][q] = sN * vkp + c * vkq;
          }
        }
      }
    }
    var menor = 0;
    for (i = 1; i < n; i++) if (Ax[i][i] < Ax[menor][menor]) menor = i;
    return [V[0][menor], V[1][menor], V[2][menor], V[3][menor]];
  }

  /* Gauss-Newton amortiguado sobre el error en pixeles. */
  function refinarPunto(camaras, pixeles, X) {
    var actual = X.slice();
    for (var it = 0; it < 12; it++) {
      var N = [[0, 0, 0], [0, 0, 0], [0, 0, 0]], b = [0, 0, 0], valido = true;
      for (var k = 0; k < camaras.length; k++) {
        var cam = camaras[k], R = cam.R;
        var loc = suma(mulMV(R, actual), cam.t);
        if (loc[2] <= EPS) { valido = false; break; }
        var fx = cam.f[0], fy = cam.f[1], z = loc[2];
        var u = fx * loc[0] / z + cam.pp[0], v = fy * loc[1] / z + cam.pp[1];
        // derivadas de (u,v) respecto al punto, por la regla de la cadena
        var J = [[0, 0, 0], [0, 0, 0]];
        for (var c = 0; c < 3; c++) {
          J[0][c] = fx / z * R[0][c] - fx * loc[0] / (z * z) * R[2][c];
          J[1][c] = fy / z * R[1][c] - fy * loc[1] / (z * z) * R[2][c];
        }
        var r = [pixeles[k][0] - u, pixeles[k][1] - v];
        for (var i = 0; i < 3; i++) {
          b[i] += J[0][i] * r[0] + J[1][i] * r[1];
          for (var j = 0; j < 3; j++) N[i][j] += J[0][i] * J[0][j] + J[1][i] * J[1][j];
        }
      }
      if (!valido) break;
      var tr = (N[0][0] + N[1][1] + N[2][2]) / 3 || 1;
      for (i = 0; i < 3; i++) N[i][i] += 1e-6 * tr;
      var paso = resolver3(N, b);
      if (!paso) break;
      actual = suma(actual, paso);
      if (norma(paso) < 1e-9) break;
    }
    return actual;
  }

  function resolver3(Ain, bin) {
    var Mx = [Ain[0].slice(), Ain[1].slice(), Ain[2].slice()], b = bin.slice(), i, j, k;
    for (i = 0; i < 3; i++) {
      var piv = i;
      for (j = i + 1; j < 3; j++) if (Math.abs(Mx[j][i]) > Math.abs(Mx[piv][i])) piv = j;
      if (Math.abs(Mx[piv][i]) < 1e-14) return null;
      if (piv !== i) { var t = Mx[i]; Mx[i] = Mx[piv]; Mx[piv] = t; var tb = b[i]; b[i] = b[piv]; b[piv] = tb; }
      for (j = i + 1; j < 3; j++) {
        var f = Mx[j][i] / Mx[i][i];
        for (k = i; k < 3; k++) Mx[j][k] -= f * Mx[i][k];
        b[j] -= f * b[i];
      }
    }
    var x = [0, 0, 0];
    for (i = 2; i >= 0; i--) {
      var s = b[i];
      for (j = i + 1; j < 3; j++) s -= Mx[i][j] * x[j];
      x[i] = s / Mx[i][i];
    }
    return x;
  }

  /* Error de reproyeccion por vista, en pixeles. Es el numero que debe ver el
     usuario: si una marca reproyecta a 40 px, esa marca esta mal puesta. */
  M.errorReproyeccion = function (camaras, pixeles, X) {
    return camaras.map(function (cam, i) {
      var p = cam.proyectar(X);
      if (!p.delante) return Infinity;
      return Math.hypot(p.px[0] - pixeles[i][0], p.px[1] - pixeles[i][1]);
    });
  };

  /* ---------- recta epipolar ----------
     Marcado un punto en una foto, su correspondiente en otra cae sobre una
     recta. Dibujarla convierte el marcado en algo rapido y preciso: en vez de
     buscar por toda la imagen, el usuario sigue la linea. */
  M.epipolar = function (camA, pxA, camB, rangoMin, rangoMax) {
    var C = camA.centro(), d = camA.rayo(pxA);
    rangoMin = rangoMin || 1; rangoMax = rangoMax || 5000;
    var puntos = [], n = 48;
    for (var i = 0; i <= n; i++) {
      // muestreo logaritmico: la recta se curva mucho cerca y poco lejos
      var t = rangoMin * Math.pow(rangoMax / rangoMin, i / n);
      var p = camB.proyectar(suma(C, escala(d, t)));
      if (p.delante) puntos.push({ px: p.px, dist: t });
    }
    return puntos;
  };

  /* ---------- eleccion de la segunda foto ----------
     El angulo entre tomas pesa mucho mas que su numero: medido, dos vistas a
     90 grados dan 35 veces menos error que a 2. Por eso no se ofrece la foto
     siguiente sino la mas separada angularmente que siga viendo el punto. */
  M.mejoresParejas = function (camaras, indiceA, X, cuantas) {
    var A = camaras[indiceA], ca = A.centro();
    var dA = unitario(resta(X, ca));
    var out = [];
    camaras.forEach(function (cam, i) {
      if (i === indiceA) return;
      if (X && !cam.ve(X, 0)) return;
      var d = unitario(resta(X, cam.centro()));
      var cos = Math.max(-1, Math.min(1, dA[0] * d[0] + dA[1] * d[1] + dA[2] * d[2]));
      out.push({ i: i, camara: cam, angulo: Math.acos(cos) * 180 / Math.PI });
    });
    out.sort(function (a, b) { return b.angulo - a.angulo; });
    return cuantas ? out.slice(0, cuantas) : out;
  };

  /* Precision esperada de una triangulacion, en metros, dado el error de
     marcado en pixeles. Sirve para avisar antes de medir, no despues. */
  M.precisionEsperada = function (camaras, X, errorPx) {
    errorPx = errorPx || 2;
    if (camaras.length < 2) return null;
    var peor = 0;
    for (var i = 0; i < camaras.length; i++) {
      var d = norma(resta(X, camaras[i].centro()));
      var ang = 0;
      for (var j = 0; j < camaras.length; j++) {
        if (i === j) continue;
        var a = unitario(resta(X, camaras[i].centro()));
        var b = unitario(resta(X, camaras[j].centro()));
        var c = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
        ang = Math.max(ang, Math.acos(c));
      }
      if (ang < 1e-6) continue;
      // error transversal del rayo dividido por el seno del angulo entre vistas
      var e = (errorPx * d / camaras[i].f[0]) / Math.sin(ang);
      if (e > peor) peor = e;
    }
    return peor || null;
  };

  /* ---------- de metadatos a camara ---------- */
  /* Rotacion mundo -> camara desde los angulos del gimbal de DJI. Guiñado
     desde el norte en sentido horario, cabeceo con 0 en la horizontal y -90
     mirando al suelo. */
  M.rotacionGimbal = function (yawDeg, pitchDeg, rollDeg) {
    var y = yawDeg * Math.PI / 180, p = pitchDeg * Math.PI / 180, r = (rollDeg || 0) * Math.PI / 180;
    var adelante = [Math.cos(p) * Math.sin(y), Math.cos(p) * Math.cos(y), Math.sin(p)];
    var derecha = [Math.cos(y), -Math.sin(y), 0];
    var abajo = cruz(adelante, derecha);
    if (r) {
      var c = Math.cos(r), s = Math.sin(r);
      var d2 = suma(escala(derecha, c), escala(abajo, s));
      var b2 = suma(escala(derecha, -s), escala(abajo, c));
      derecha = d2; abajo = b2;
    }
    return [derecha, abajo, adelante];
  };

  M.metrosLocales = function (lat, lon, refLat, refLon) {
    var k = Math.cos(refLat * Math.PI / 180);
    return [(lon - refLon) * Math.PI / 180 * TIERRA * k,
            (lat - refLat) * Math.PI / 180 * TIERRA];
  };

  /* `foto` es una entrada del explorador (triage.js). `convencion` decide si
     los 35 mm equivalentes se refieren al ancho del fotograma o a su diagonal:
     entre las dos hay un 4 %, y una sola foto no permite decidirlo. */
  M.camaraDeFoto = function (foto, ref, convencion) {
    if (!isFinite(foto.lat) || !isFinite(foto.pitch)) return null;
    if (!foto.ancho || !foto.alto) return null;
    var eq = foto.focal35;
    if (!eq) return null;
    var f = convencion === 'diagonal'
      ? Math.hypot(foto.ancho, foto.alto) * eq / 43.266615
      : foto.ancho * eq / 36;
    var xy = M.metrosLocales(foto.lat, foto.lon, ref[0], ref[1]);
    var centro = [xy[0], xy[1], foto.alt || 0];
    var R = M.rotacionGimbal(foto.yaw || 0, foto.pitch, foto.roll || 0);
    var t = escala(mulMV(R, centro), -1);
    return new Camara(f, [foto.ancho / 2, foto.alto / 2], R, t, foto.nombre,
                      [foto.ancho, foto.alto]);
  };
})(window.A3D);
