/* AUTO3D - measure.js : medir en metros marcando el mismo punto en dos fotos.

   Marcado un punto en la foto de la izquierda, su correspondiente en la de la
   derecha cae forzosamente sobre una recta. Dibujarla cambia el trabajo: en
   vez de buscar por toda la imagen, se sigue la linea.

   La segunda foto no es la siguiente del vuelo sino la **mas separada
   angularmente** que siga viendo el punto. Medido: dos vistas a 90 grados dan
   35 veces menos error que a 2, y el angulo pesa mucho mas que el numero de
   tomas. */
(function (A) {
  'use strict';
  var Me = A.medir = {};
  var M = A.mv;

  var vuelo = null;          // {fotos, camaras}
  var panel = { A: null, B: null };
  var puntos = [];           // {id, nombre, X, marcas:{indice:[x,y]}, error, precision}
  var enCurso = null;        // marca puesta en A, esperando la de B
  var cache = {};            // imagenes ya cargadas

  /* ---------- carga de imagenes ---------- */
  function cargar(indice) {
    if (cache[indice]) return Promise.resolve(cache[indice]);
    var foto = vuelo.fotos[indice];
    return new Promise(function (res, rej) {
      var url = URL.createObjectURL(foto.file);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        cache[indice] = img;
        // el navegador se queda sin memoria con decenas de imagenes de 48 Mpx
        var claves = Object.keys(cache);
        if (claves.length > 6) delete cache[claves[0]];
        res(img);
      };
      img.onerror = function () { URL.revokeObjectURL(url); rej(new Error('no se pudo abrir ' + foto.nombre)); };
      img.src = url;
    });
  }

  /* ---------- un panel = lienzo + estado de vista ---------- */
  function Panel(lado, canvas, etiqueta, selector) {
    this.lado = lado; this.cv = canvas; this.ctx = canvas.getContext('2d');
    this.etiqueta = etiqueta; this.selector = selector;
    this.indice = -1; this.esc = 1; this.ox = 0; this.oy = 0;
    var self = this;
    canvas.addEventListener('mousedown', function (e) { self.pulsar(e); });
    canvas.addEventListener('wheel', function (e) { self.rueda(e); }, { passive: false });
    canvas.addEventListener('mousemove', function (e) { self.mover(e); });
  }
  Panel.prototype.mostrar = function (indice) {
    var self = this;
    this.indice = indice;
    this.selector.value = String(indice);
    return cargar(indice).then(function (img) {
      self.img = img;
      self.encuadrar();
      self.pintar();
    }).catch(function (e) { A.log(e.message, 'e'); });
  };
  Panel.prototype.encuadrar = function () {
    if (!this.img) return;
    var r = this.cv.getBoundingClientRect();
    this.cv.width = Math.max(50, r.width); this.cv.height = Math.max(50, r.height);
    this.esc = Math.min(this.cv.width / this.img.width, this.cv.height / this.img.height);
    this.ox = (this.cv.width - this.img.width * this.esc) / 2;
    this.oy = (this.cv.height - this.img.height * this.esc) / 2;
  };
  Panel.prototype.aImagen = function (e) {
    var r = this.cv.getBoundingClientRect();
    return [(e.clientX - r.left - this.ox) / this.esc, (e.clientY - r.top - this.oy) / this.esc];
  };
  Panel.prototype.aPantalla = function (p) {
    return [p[0] * this.esc + this.ox, p[1] * this.esc + this.oy];
  };
  Panel.prototype.rueda = function (e) {
    e.preventDefault();
    var r = this.cv.getBoundingClientRect();
    var mx = e.clientX - r.left, my = e.clientY - r.top;
    var ix = (mx - this.ox) / this.esc, iy = (my - this.oy) / this.esc;
    this.esc = Math.max(0.02, Math.min(40, this.esc * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
    this.ox = mx - ix * this.esc; this.oy = my - iy * this.esc;
    this.pintar();
  };
  Panel.prototype.mover = function (e) {
    if (e.buttons === 1 && e.altKey) {
      this.ox += e.movementX; this.oy += e.movementY; this.pintar();
    } else if (this.lado === 'B' && enCurso) {
      this.raton = this.aImagen(e); this.pintar();
    }
  };
  Panel.prototype.pulsar = function (e) {
    if (e.altKey || e.button !== 0) return;
    marcar(this.lado, this.aImagen(e));
  };

  /* ---------- dibujo ---------- */
  Panel.prototype.pintar = function () {
    if (!this.img) return;
    var c = this.ctx;
    c.setTransform(1, 0, 0, 1, 0, 0);
    c.fillStyle = '#0b0d11'; c.fillRect(0, 0, this.cv.width, this.cv.height);
    c.drawImage(this.img, this.ox, this.oy, this.img.width * this.esc, this.img.height * this.esc);

    var self = this;
    // recta epipolar del punto que se esta marcando
    if (this.lado === 'B' && enCurso && this.indice >= 0) {
      var linea = M.epipolar(vuelo.camaras[enCurso.indiceA], enCurso.px,
                             vuelo.camaras[this.indice], 2, 3000);
      if (linea.length > 1) {
        c.save();
        c.strokeStyle = '#ffd25f'; c.lineWidth = 1.5; c.setLineDash([7, 5]);
        c.beginPath();
        linea.forEach(function (p, i) {
          var s = self.aPantalla(p.px);
          i ? c.lineTo(s[0], s[1]) : c.moveTo(s[0], s[1]);
        });
        c.stroke(); c.restore();
        // el punto mas cercano al raton, con su distancia: orienta al marcar
        if (this.raton) {
          var mejor = null;
          linea.forEach(function (p) {
            var s = self.aPantalla(p.px);
            var d = Math.hypot(s[0] - self.aPantalla(self.raton)[0], s[1] - self.aPantalla(self.raton)[1]);
            if (!mejor || d < mejor.d) mejor = { d: d, p: p, s: s };
          });
          if (mejor && mejor.d < 60) {
            c.fillStyle = '#ffd25f';
            c.beginPath(); c.arc(mejor.s[0], mejor.s[1], 4, 0, 6.2832); c.fill();
            c.font = '11px sans-serif';
            c.fillText(mejor.p.dist.toFixed(1) + ' m', mejor.s[0] + 7, mejor.s[1] - 6);
          }
        }
      }
    }
    // puntos ya medidos, reproyectados sobre esta foto
    puntos.forEach(function (pt, i) {
      var cam = vuelo.camaras[self.indice];
      if (!cam) return;
      var pr = cam.proyectar(pt.X);
      if (!pr.delante) return;
      var s = self.aPantalla(pr.px);
      if (s[0] < -20 || s[1] < -20 || s[0] > self.cv.width + 20 || s[1] > self.cv.height + 20) return;
      var sel = pt.id === Me.seleccion;
      c.strokeStyle = sel ? '#3ddc97' : '#4da3ff'; c.lineWidth = sel ? 2.4 : 1.6;
      c.beginPath(); c.arc(s[0], s[1], sel ? 8 : 6, 0, 6.2832); c.stroke();
      c.beginPath(); c.moveTo(s[0] - 11, s[1]); c.lineTo(s[0] + 11, s[1]);
      c.moveTo(s[0], s[1] - 11); c.lineTo(s[0], s[1] + 11); c.stroke();
      c.fillStyle = sel ? '#3ddc97' : '#4da3ff'; c.font = '12px sans-serif';
      c.fillText(pt.nombre, s[0] + 13, s[1] - 9);
    });
    // marca a medio poner
    if (enCurso && this.lado === 'A' && this.indice === enCurso.indiceA) {
      var s2 = this.aPantalla(enCurso.px);
      c.strokeStyle = '#ffb34d'; c.lineWidth = 2;
      c.beginPath(); c.arc(s2[0], s2[1], 7, 0, 6.2832); c.stroke();
    }
  };

  /* ---------- marcado y medida ---------- */
  function marcar(lado, px) {
    if (!vuelo) return;
    if (lado === 'A') {
      enCurso = { indiceA: panel.A.indice, px: px };
      // la segunda foto: la mas separada angularmente, no la siguiente
      var rayo = vuelo.camaras[panel.A.indice].rayo(px);
      var centro = vuelo.camaras[panel.A.indice].centro();
      var tentativo = M.resta(M.cruz([0, 0, 0], [0, 0, 0]), [0, 0, 0]);
      tentativo = [centro[0] + rayo[0] * 60, centro[1] + rayo[1] * 60, centro[2] + rayo[2] * 60];
      var parejas = M.mejoresParejas(vuelo.camaras, panel.A.indice, tentativo, 1);
      if (parejas.length) {
        panel.B.mostrar(parejas[0].i).then(function () {
          estado('Marca el mismo punto sobre la línea amarilla. Vista B a ' +
                 parejas[0].angulo.toFixed(0) + '° de A.');
        });
      } else {
        estado('Ninguna otra foto ve ese punto: prueba con otra vista.');
      }
      panel.A.pintar();
      return;
    }
    // lado B: se cierra la medida
    if (!enCurso) { estado('Marca primero en la foto de la izquierda.'); return; }
    var camaras = [vuelo.camaras[enCurso.indiceA], vuelo.camaras[panel.B.indice]];
    var marcas = [enCurso.px, px];
    var X;
    try { X = M.triangular(camaras, marcas); }
    catch (e) { estado('No se puede medir: ' + e.message); enCurso = null; return; }
    var errores = M.errorReproyeccion(camaras, marcas, X);
    var punto = {
      id: 'p' + Date.now(), nombre: 'P' + (puntos.length + 1), X: X,
      vistas: [{ i: enCurso.indiceA, px: enCurso.px }, { i: panel.B.indice, px: px }],
      error: Math.max(errores[0], errores[1]),
      precision: M.precisionEsperada(camaras, X, 2),
      angulo: M.mejoresParejas([camaras[0], camaras[1]], 0, X, 1)[0]
    };
    punto.angulo = punto.angulo ? punto.angulo.angulo : 0;
    puntos.push(punto);
    Me.seleccion = punto.id;
    enCurso = null;
    pintarLista();
    panel.A.pintar(); panel.B.pintar();
    estado('Punto ' + punto.nombre + ' medido. Error de reproyección ' +
           punto.error.toFixed(1) + ' px.');
  }

  function estado(texto) {
    var el = document.getElementById('mdEstado');
    if (el) el.textContent = texto;
  }

  function pintarLista() {
    var el = document.getElementById('mdLista');
    if (!el) return;
    if (!puntos.length) {
      el.innerHTML = '<div class="hint">Marca un punto en la foto de la izquierda para empezar.</div>';
      document.getElementById('mdDistancia').textContent = '';
      return;
    }
    var html = '';
    puntos.forEach(function (p) {
      var aviso = p.error > 5 ? ' style="color:var(--warn)"' : '';
      html += '<div class="mdpt' + (p.id === Me.seleccion ? ' sel' : '') + '" data-id="' + p.id + '">' +
        '<b>' + p.nombre + '</b> ' +
        '<span class="hint">E ' + p.X[0].toFixed(2) + '  N ' + p.X[1].toFixed(2) +
        '  alt ' + p.X[2].toFixed(2) + ' m</span>' +
        '<span class="hint"' + aviso + '> · error ' + p.error.toFixed(1) + ' px' +
        ' · ±' + (p.precision * 100).toFixed(0) + ' cm' +
        ' · ' + p.angulo.toFixed(0) + '°</span></div>';
    });
    el.innerHTML = html;
    Array.prototype.forEach.call(el.querySelectorAll('.mdpt'), function (d) {
      d.onclick = function () {
        Me.seleccion = d.getAttribute('data-id');
        pintarLista(); panel.A.pintar(); panel.B.pintar();
      };
    });
    calcularDistancia();
  }

  /* Distancia entre los dos ultimos puntos medidos: es lo que se quiere de un
     edificio -cuanto mide este lado- mas que las coordenadas absolutas. */
  function calcularDistancia() {
    var el = document.getElementById('mdDistancia');
    if (!el) return;
    if (puntos.length < 2) { el.textContent = ''; return; }
    var a = puntos[puntos.length - 2], b = puntos[puntos.length - 1];
    var d = M.norma(M.resta(b.X, a.X));
    var inc = Math.hypot(a.precision || 0, b.precision || 0);
    el.innerHTML = '<b>' + a.nombre + ' → ' + b.nombre + ': ' + d.toFixed(2) +
      ' m</b> <span class="hint">± ' + (inc * 100).toFixed(0) + ' cm</span>' +
      '<span class="hint"> · desnivel ' + (b.X[2] - a.X[2]).toFixed(2) + ' m</span>';
  }

  /* ---------- API ---------- */
  Me.abrir = function (v) {
    vuelo = v; puntos = []; enCurso = null; cache = {}; Me.seleccion = null;
    var caja = document.getElementById('medir');
    caja.hidden = false;
    document.getElementById('mdTitulo').textContent = v.carpeta.split(/[\\/]/).pop() +
      ' · ' + v.fotos.length + ' fotos';
    ['A', 'B'].forEach(function (lado) {
      var sel = document.getElementById('mdSel' + lado);
      sel.innerHTML = v.fotos.map(function (f, i) {
        return '<option value="' + i + '">' + (i + 1) + '. ' + f.nombre + '</option>';
      }).join('');
      if (!panel[lado]) {
        panel[lado] = new Panel(lado, document.getElementById('mdCv' + lado),
                                document.getElementById('mdEt' + lado), sel);
      } else {
        panel[lado].selector = sel;
      }
      sel.onchange = function () { panel[lado].mostrar(parseInt(sel.value, 10)); };
    });
    pintarLista();
    estado('Marca un punto en la foto de la izquierda. La app elegirá la mejor segunda vista.');
    panel.A.mostrar(0);
    panel.B.mostrar(Math.min(1, v.fotos.length - 1));
  };
  Me.cerrar = function () {
    document.getElementById('medir').hidden = true;
    cache = {};
  };
  Me.puntos = function () { return puntos; };
  Me.csv = function () {
    var filas = ['punto;este_m;norte_m;altura_m;error_px;precision_cm;angulo_grados;vistas'];
    puntos.forEach(function (p) {
      filas.push([p.nombre, p.X[0].toFixed(3), p.X[1].toFixed(3), p.X[2].toFixed(3),
                  p.error.toFixed(2), (p.precision * 100).toFixed(1), p.angulo.toFixed(1),
                  p.vistas.map(function (v) { return vuelo.fotos[v.i].nombre; }).join(' + ')].join(';'));
    });
    if (puntos.length >= 2) {
      filas.push('');
      filas.push('desde;hasta;distancia_m');
      for (var i = 0; i < puntos.length - 1; i++) {
        for (var j = i + 1; j < puntos.length; j++) {
          filas.push([puntos[i].nombre, puntos[j].nombre,
                      M.norma(M.resta(puntos[j].X, puntos[i].X)).toFixed(3)].join(';'));
        }
      }
    }
    return filas.join('\n');
  };
  Me.deshacer = function () {
    if (enCurso) { enCurso = null; }
    else if (puntos.length) { puntos.pop(); }
    pintarLista();
    if (panel.A) panel.A.pintar();
    if (panel.B) panel.B.pintar();
  };
})(window.A3D);
