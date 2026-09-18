/* AUTO3D - exporters.js : proyecto JSON, OBJ 3D, CSV de anotaciones
   y dataset de entrenamiento portable a otras apps. */
(function (A) {
  'use strict';
  var E = A.export = {};

  /* Dentro de un iframe (la version publicada en web) el navegador anula las
     descargas sin avisar. En ese caso se abre un panel con el contenido para
     copiarlo a mano, en lugar de que el boton no haga nada. */
  function embedded() {
    try { return window.self !== window.top; } catch (e) { return true; }
  }
  E.textPanel = function (name, text) {
    var old = document.getElementById('a3dTextPanel');
    if (old) old.remove();
    var d = document.createElement('div');
    d.id = 'a3dTextPanel';
    d.innerHTML =
      '<div class="tp-box"><div class="tp-head"><b>' + name + '</b>' +
      '<span>' + (text.length / 1024).toFixed(1) + ' KB</span>' +
      '<button class="tp-copy">copiar</button><button class="tp-close">cerrar</button></div>' +
      '<textarea readonly></textarea>' +
      '<div class="tp-foot">Este navegador no permite descargar archivos desde una pagina incrustada. ' +
      'Copia el contenido y guardalo como <b>' + name + '</b>.</div></div>';
    d.querySelector('textarea').value = text;
    d.querySelector('.tp-close').onclick = function () { d.remove(); };
    d.querySelector('.tp-copy').onclick = function () {
      var ta = d.querySelector('textarea');
      ta.select();
      var ok = false;
      try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
      if (!ok && navigator.clipboard) { navigator.clipboard.writeText(text); ok = true; }
      d.querySelector('.tp-copy').textContent = ok ? 'copiado' : 'copia manual';
    };
    document.body.appendChild(d);
  };
  E.download = function (name, text, mime) {
    if (embedded()) { E.textPanel(name, text); A.log('descarga bloqueada por el navegador: abierto panel para copiar ' + name, 'w'); return; }
    var blob = new Blob([text], { type: mime || 'application/octet-stream' });
    var url = URL.createObjectURL(blob), a = document.createElement('a');
    a.href = url; a.download = name; document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 400);
    A.log('descargado: ' + name, 'o');
  };

  /* ---------- proyecto completo (para reabrir en AUTO3D) ---------- */
  E.project = function () {
    var s = A.state;
    return {
      format: 'AUTO3D.project', version: 2, saved: new Date().toISOString(),
      media: s.media ? { name: s.media.name, type: s.media.type, w: s.media.w, h: s.media.h, fps: s.media.fps, nFrames: s.media.nFrames } : null,
      params: s.params, classes: A.CLASSES,
      objects: s.objects.map(function (o) {
        return { id: o.id, kind: o.kind, cls: o.cls, name: o.name, source: o.source, keys: o.keys, score: o.score };
      }),
      model: s.model ? { classes: s.model.classes, W: s.model.W, mu: s.model.mu, sd: s.model.sd, epochs: s.model.epochs, acc: s.model.acc, nSamples: s.model.samples.length } : null
    };
  };
  E.loadProject = function (json) {
    var s = A.state;
    if (!json || json.format !== 'AUTO3D.project') throw new Error('no es un proyecto AUTO3D');
    if (json.params) Object.keys(json.params).forEach(function (k) { if (k in s.params) s.params[k] = json.params[k]; });
    s.objects = (json.objects || []).map(function (o) {
      return { id: o.id, kind: o.kind, cls: o.cls, name: o.name, source: o.source || 'manual',
               keys: o.keys || {}, track: {}, visible: true, locked: false, score: o.score || 1 };
    });
    s.selectedId = null;
    return s.objects.length;
  };

  /* ---------- OBJ: geometria reconstruida del frame actual ---------- */
  E.obj = function (recons, meta) {
    var lines = ['# AUTO3D export ' + new Date().toISOString(),
                 '# unidades: metros (escala derivada de la altura de camara)',
                 '# ' + (meta || ''), 'mtllib auto3d.mtl'];
    var vi = 1, groups = {};
    recons.forEach(function (r) {
      if (!r.pts3 || r.pts3.length < 3) return;
      (groups[r.cls] = groups[r.cls] || []).push(r);
    });
    Object.keys(groups).forEach(function (cls) {
      lines.push('g ' + cls);
      lines.push('usemtl ' + cls);
      groups[cls].forEach(function (r) {
        var idxs = [];
        r.pts3.forEach(function (P) {
          lines.push('v ' + P[0].toFixed(4) + ' ' + P[1].toFixed(4) + ' ' + P[2].toFixed(4));
          idxs.push(vi++);
        });
        lines.push('f ' + idxs.join(' '));
      });
    });
    return lines.join('\n') + '\n';
  };
  E.mtl = function () {
    return A.CLASSES.map(function (c) {
      var r = parseInt(c.color.substr(1, 2), 16) / 255,
          g = parseInt(c.color.substr(3, 2), 16) / 255,
          b = parseInt(c.color.substr(5, 2), 16) / 255;
      return 'newmtl ' + c.id + '\nKd ' + r.toFixed(3) + ' ' + g.toFixed(3) + ' ' + b.toFixed(3) + '\nd 1.0\nillum 1\n';
    }).join('\n');
  };

  /* ---------- CSV de anotaciones (una fila por objeto y frame clave) ---------- */
  E.csv = function () {
    var rows = ['objeto;clase;tipo;frame;esClave;puntos_xy'];
    A.state.objects.forEach(function (o) {
      var frames = {};
      Object.keys(o.keys).forEach(function (f) { frames[f] = 1; });
      Object.keys(o.track).forEach(function (f) { frames[f] = frames[f] || 0; });
      Object.keys(frames).sort(function (a, b) { return a - b; }).forEach(function (f) {
        var pts = A.objAt(o, +f) || [];
        rows.push([o.name, o.cls, o.kind, f, frames[f] ? 'si' : 'no',
          pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ')].join(';'));
      });
    });
    return rows.join('\n');
  };

  /* ---------- dataset portable: descriptores + etiquetas ----------
     Pensado para reentrenar el clasificador en otra app (Python, otra web,
     un agente). Incluye los nombres de los descriptores para no perder el
     significado de cada columna.  */
  E.dataset = function () {
    var m = A.state.model;
    return {
      format: 'AUTO3D.dataset', version: 2, saved: new Date().toISOString(),
      featureNames: A.learn.FEATNAMES,
      classes: A.CLASSES.map(function (c) { return { id: c.id, nombre: c.nom, eje: c.axis }; }),
      samples: m ? m.samples.map(function (s) { return { f: s.f.map(function (v) { return +v.toFixed(6); }), c: s.c }; }) : [],
      weights: m && m.W ? { classes: m.classes, W: m.W, mu: m.mu, sd: m.sd } : null,
      notas: 'Regresion softmax multiclase. x = (f - mu)/sd con sesgo 1 al final; p = softmax(W x).'
    };
  };
})(window.A3D);
