/* AUTO3D - app.js : carga de medios, orquestacion del pipeline,
   paneles, linea de tiempo y exportaciones. */
(function (A) {
  'use strict';
  var S = A.state, P = S.params;
  var work = document.createElement('canvas');          // lienzo de proceso
  var wctx = work.getContext('2d', { willReadFrequently: true });
  var lastPyr = null, lastPyrFrame = -1;
  var busy = false, playing = false, playTimer = null;

  function $(id) { return document.getElementById(id); }
  function show(msg) {
    var el = $('overlayMsg');
    if (!msg) { el.style.display = 'none'; return; }
    el.style.display = 'block'; el.textContent = msg;
  }

  /* ================= carga de medios ================= */
  function loadFile(file) {
    var url = URL.createObjectURL(file);
    var isVid = /^video\//.test(file.type) || /\.(mp4|webm|mov|m4v|ogv)$/i.test(file.name);
    if (isVid) {
      var v = document.createElement('video');
      v.preload = 'auto'; v.muted = true; v.playsInline = true; v.src = url;
      v.addEventListener('loadedmetadata', function () {
        var fps = parseFloat($('fps').value) || 25;
        S.media = { type: 'video', el: v, w: v.videoWidth, h: v.videoHeight, name: file.name,
                    duration: v.duration, fps: fps, nFrames: Math.max(1, Math.floor(v.duration * fps)) };
        onMediaReady();
      }, { once: true });
      v.addEventListener('error', function () { A.log('no se pudo abrir el video (codec no soportado por el navegador)', 'e'); });
    } else {
      var im = new Image();
      im.onload = function () {
        S.media = { type: 'image', el: im, w: im.naturalWidth, h: im.naturalHeight, name: file.name,
                    duration: 0, fps: 1, nFrames: 1 };
        onMediaReady();
      };
      im.onerror = function () { A.log('no se pudo abrir la imagen', 'e'); };
      im.src = url;
    }
  }
  function onMediaReady() {
    S.frame = 0; S.detection = null; lastPyr = null; lastPyrFrame = -1;
    $('drop').classList.add('hide');
    A.ui.resizeTo(S.media.w, S.media.h);
    A.log('cargado ' + S.media.name + '  ' + S.media.w + 'x' + S.media.h +
          (S.media.type === 'video' ? '  ' + S.media.duration.toFixed(1) + 's  ' + S.media.nFrames + ' frames @' + S.media.fps + 'fps' : ''), 'o');
    buildTrack();
    gotoFrame(0, true);
  }

  /* dibuja el frame n en el lienzo base; para video hace seek asincrono */
  function drawFrame(n, cb) {
    var m = S.media, ctx = A.ui.ctxBase();
    if (!m) return cb && cb(false);
    if (m.type === 'image') { ctx.drawImage(m.el, 0, 0); return cb && cb(true); }
    var t = Math.min(m.duration - 1e-3, (n + 0.5) / m.fps);
    var v = m.el;
    var done = function () {
      v.removeEventListener('seeked', done);
      try { ctx.drawImage(v, 0, 0, m.w, m.h); } catch (e) { A.log('error al dibujar frame: ' + e.message, 'e'); }
      cb && cb(true);
    };
    if (Math.abs(v.currentTime - t) < 1e-4 && v.readyState >= 2) { done(); return; }
    v.addEventListener('seeked', done);
    v.currentTime = t;
  }

  /* ================= pipeline de deteccion ================= */
  function grabProc() {
    var m = S.media;
    var pw = Math.min(P.proc, m.w), ph = Math.round(m.h * pw / m.w);
    if (work.width !== pw || work.height !== ph) { work.width = pw; work.height = ph; }
    wctx.drawImage(A.ui.ctxBase().canvas, 0, 0, m.w, m.h, 0, 0, pw, ph);
    return { img: wctx.getImageData(0, 0, pw, ph), scale: pw / m.w };
  }

  function detect() {
    if (!S.media) return null;
    var t0 = performance.now();
    var g = grabProc();
    var det = A.vision.process(g.img, P);
    det.img = g.img; det.scale = g.scale;
    det.vps = A.geom.findVPs(det.segs, P, det.w, det.h);
    det.calib = A.geom.calibrate(det.vps, det.w, det.h);
    det.horizon = det.calib ? A.geom.horizon(det.vps, det.calib) : null;
    det.horizonY = null;
    if (det.horizon && Math.abs(det.horizon[1]) > 1e-9) {
      det.horizonY = -(det.horizon[0] * det.w / 2 + det.horizon[2]) / det.horizon[1];
    }
    det.cands = A.geom.planeCandidates(det, det.vps, P);
    if (S.model && S.model.W) {
      det.cands.forEach(function (c) {
        c.pred = A.learn.predictPoly(S.model, det, c.pts, det.calib, det.horizonY);
      });
    }
    det.ms = performance.now() - t0;
    S.detection = det;
    A.log('deteccion f' + S.frame + ': ' + det.segs.length + ' segmentos, ' + det.vps.length +
          ' vp, ' + det.cands.length + ' planos  (' + det.ms.toFixed(0) + ' ms)');
    return det;
  }

  function gotoFrame(n, forceDetect, cb) {
    if (!S.media || busy) return;
    var prev = S.frame;
    S.frame = A.clamp(Math.round(n), 0, S.media.nFrames - 1);
    busy = true;
    drawFrame(S.frame, function () {
      // seguimiento desde el frame anterior si procede
      if (S.autoTrack && lastPyr && lastPyrFrame !== S.frame && S.objects.length) {
        var g = grabProc();
        var gray = A.vision.toGray(g.img);
        var pyrB = A.track.pyramid(gray, g.img.width, g.img.height, P.trackLevels);
        var r = A.track.propagate(S.objects, lastPyrFrame, S.frame, lastPyr, pyrB, g.scale, P);
        if (r.moved) A.log('seguimiento f' + lastPyrFrame + '->' + S.frame + ': ' + r.moved + ' objetos, ' + r.lost + ' vertices perdidos');
        lastPyr = pyrB; lastPyrFrame = S.frame;
      }
      if (forceDetect !== false && $('autoDetect').checked) detect();
      else if (forceDetect === false) { /* sin deteccion */ }
      if (!lastPyr || lastPyrFrame !== S.frame) {
        var g2 = grabProc();
        lastPyr = A.track.pyramid(A.vision.toGray(g2.img), g2.img.width, g2.img.height, P.trackLevels);
        lastPyrFrame = S.frame;
      }
      busy = false;
      updateTrack(); refreshPanels(); A.ui.render();
      cb && cb();
    });
    if (prev !== S.frame) show(null);
  }
  A.gotoFrame = gotoFrame;

  /* ================= linea de tiempo ================= */
  function buildTrack() {
    var tr = $('track');
    tr.innerHTML = '<div class="cursor" style="left:0"></div>';
    $('frameMax').textContent = S.media ? (S.media.nFrames - 1) : 0;
    $('frameNo').max = S.media ? S.media.nFrames - 1 : 0;
  }
  function updateTrack() {
    var tr = $('track'); if (!S.media) return;
    var W = tr.clientWidth, N = Math.max(1, S.media.nFrames - 1);
    tr.querySelectorAll('.key,.done').forEach(function (e) { e.remove(); });
    var sel = A.selected();
    if (sel) {
      Object.keys(sel.track).map(Number).sort(function (a, b) { return a - b; }).forEach(function (f) {
        var d = document.createElement('div'); d.className = 'done';
        d.style.left = (f / N * W) + 'px'; d.style.width = Math.max(2, W / N) + 'px';
        tr.appendChild(d);
      });
      Object.keys(sel.keys).map(Number).forEach(function (f) {
        var d = document.createElement('div'); d.className = 'key';
        d.style.left = (f / N * W) + 'px'; d.title = 'keyframe ' + f;
        tr.appendChild(d);
      });
    }
    tr.querySelector('.cursor').style.left = (S.frame / N * W) + 'px';
    $('frameNo').value = S.frame;
  }

  /* ================= paneles ================= */
  function refreshPanels() {
    // lista de objetos
    var L = $('objlist'); L.innerHTML = '';
    S.objects.forEach(function (o) {
      var d = document.createElement('div');
      d.className = 'obj' + (o.id === S.selectedId ? ' sel' : '');
      var nk = Object.keys(o.keys).length;
      d.innerHTML = '<span class="sw" style="background:' + A.classById(o.cls).color + '"></span>' +
        '<span class="nm">' + o.name + '</span>' +
        '<span class="kf">' + nk + 'k</span>' +
        '<span class="badge">' + (o.source === 'auto' ? 'auto' : 'man') + '</span>';
      d.onclick = function () { S.selectedId = o.id; refreshPanels(); updateTrack(); A.ui.render(); };
      L.appendChild(d);
    });
    // detalle de seleccion
    var sel = A.selected(), inf = $('selInfo');
    if (!sel) inf.innerHTML = '<div class="hint">Nada seleccionado.</div>';
    else {
      var pts = A.objAt(sel, S.frame) || [];
      var rec = '';
      if (sel.kind === 'plane' && S.detection && S.detection.calib) {
        var sc = S.detection.scale;
        var r = A.geom.reconstructPoly(pts.map(function (p) { return [p[0] * sc, p[1] * sc]; }), sel.cls, S.detection.calib, P.camHeight);
        if (r.error) rec = '<div class="kv"><span>3D</span><b style="color:var(--warn)">no</b></div><div class="hint">' + r.error + '</div>';
        else {
          var dims = polyDims(r.pts3);
          rec = '<div class="kv"><span>3D</span><b style="color:var(--ok)">' + r.method + '</b></div>' +
                '<div class="kv"><span>anchura aprox</span><b>' + dims.a.toFixed(2) + ' m</b></div>' +
                '<div class="kv"><span>altura aprox</span><b>' + dims.b.toFixed(2) + ' m</b></div>';
        }
      }
      inf.innerHTML =
        '<div class="kv"><span>nombre</span><b>' + sel.name + '</b></div>' +
        '<div class="kv"><span>tipo</span><b>' + sel.kind + '</b></div>' +
        '<div class="kv"><span>clase</span><b>' + sel.cls + '</b></div>' +
        '<div class="kv"><span>vertices</span><b>' + pts.length + '</b></div>' +
        '<div class="kv"><span>keyframes</span><b>' + Object.keys(sel.keys).length + '</b></div>' +
        '<div class="kv"><span>en este frame</span><b>' + (A.isKey(sel, S.frame) ? 'CLAVE' : (sel.track[S.frame] ? 'seguido' : 'interpolado')) + '</b></div>' + rec;
    }
    // estado del modelo
    var m = S.model, st = $('modelInfo');
    if (!m || !m.samples.length) st.innerHTML = '<div class="hint">Sin muestras. Marca planos en modo LEARN para empezar a ensenarle.</div>';
    else {
      var byc = {};
      m.samples.forEach(function (s) { byc[s.c] = (byc[s.c] || 0) + 1; });
      st.innerHTML = '<div class="kv"><span>muestras</span><b>' + m.samples.length + '</b></div>' +
        '<div class="kv"><span>clases</span><b>' + Object.keys(byc).length + '</b></div>' +
        '<div class="kv"><span>epocas</span><b>' + m.epochs + '</b></div>' +
        '<div class="kv"><span>precision</span><b>' + (m.W ? (m.acc * 100).toFixed(0) + '%' : '-') + '</b></div>' +
        '<div class="hint">' + Object.keys(byc).map(function (k) { return k + ':' + byc[k]; }).join('  ') + '</div>';
    }
  }
  A.refreshPanels = refreshPanels;

  function polyDims(pts3) {
    var i, mx = [-1e9, -1e9, -1e9], mn = [1e9, 1e9, 1e9];
    pts3.forEach(function (p) { for (i = 0; i < 3; i++) { if (p[i] > mx[i]) mx[i] = p[i]; if (p[i] < mn[i]) mn[i] = p[i]; } });
    var d = [mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]].sort(function (a, b) { return b - a; });
    return { a: d[0], b: d[1] };
  }

  /* ================= aprendizaje ================= */
  function ensureModel() { if (!S.model) S.model = A.learn.newModel(); return S.model; }

  function addSampleFromObject(o) {
    if (o.kind !== 'plane') return false;
    var det = S.detection || detect();
    if (!det) return false;
    var pts = A.objAt(o, S.frame);
    if (!pts || pts.length < 3) return false;
    var sc = det.scale;
    var f = A.learn.features(det, pts.map(function (p) { return [p[0] * sc, p[1] * sc]; }), det.calib, det.horizonY);
    A.learn.addSample(ensureModel(), f, o.cls);
    A.learn.save(S.model);
    return true;
  }

  A.on('newAnnotation', function (o) {
    if (S.mode === 'learn' && o.kind === 'plane') {
      if (addSampleFromObject(o)) { A.log('muestra anadida al modelo (' + o.cls + '), total ' + S.model.samples.length, 'o'); refreshPanels(); }
    }
  });

  A.on('acceptCandidate', function (c) {
    var det = S.detection; if (!det) return;
    var sc = det.scale;
    var pts = c.pts.map(function (p) { return [p[0] / sc, p[1] / sc]; });
    var cls = (c.pred && $('useModelClass').checked) ? c.pred[0].cls : S.activeClass;
    var o = A.newObject('plane', cls, pts, S.frame);
    o.source = 'auto'; o.score = c.score;
    S.objects.push(o); S.selectedId = o.id;
    A.emit('objects'); A.emit('newAnnotation', o);
    A.log('plano detectado aceptado como ' + cls + ' (' + (c.score * 100).toFixed(0) + '% soporte)', 'o');
    refreshPanels(); A.ui.render();
  });

  A.on('objects', function () { refreshPanels(); updateTrack(); });
  A.on('select', function () { refreshPanels(); updateTrack(); });

  /* ================= propagacion por todo el video ================= */
  function propagateAll(from, to) {
    if (!S.media || S.media.type !== 'video') { A.log('la propagacion requiere un video', 'w'); return; }
    var f = from, stop = false;
    $('btnPropStop').disabled = false;
    $('btnPropStop').onclick = function () { stop = true; };
    var prevAuto = $('autoDetect').checked;
    $('autoDetect').checked = false;
    A.log('propagando anotaciones de ' + from + ' a ' + to + '...', 'w');
    function step() {
      if (stop || f >= to) {
        $('autoDetect').checked = prevAuto;
        $('btnPropStop').disabled = true;
        show(null);
        A.log('propagacion terminada en f' + f, 'o');
        gotoFrame(f, prevAuto);
        return;
      }
      f++;
      show('propagando... frame ' + f + ' / ' + to);
      gotoFrame(f, false, function () { setTimeout(step, 0); });
    }
    step();
  }

  /* ================= reconstruccion / export 3D ================= */
  function reconstructCurrent() {
    var det = S.detection || detect();
    if (!det) return { recons: [], errs: ['sin imagen'] };
    if (!det.calib) return { recons: [], errs: ['sin calibracion: se necesitan 2 puntos de fuga ortogonales en la escena'] };
    var sc = det.scale, out = [], errs = [];
    S.objects.forEach(function (o) {
      if (o.kind !== 'plane') return;
      var pts = A.objAt(o, S.frame); if (!pts || pts.length < 3) return;
      var r = A.geom.reconstructPoly(pts.map(function (p) { return [p[0] * sc, p[1] * sc]; }), o.cls, det.calib, P.camHeight);
      if (r.error) { errs.push(o.name + ': ' + r.error); return; }
      out.push({ cls: o.cls, name: o.name, pts3: r.pts3.map(function (X) { return A.geom.toWorld(det.calib, X); }), method: r.method });
      if (r.warn) errs.push(o.name + ': ' + r.warn);
    });
    return { recons: out, errs: errs };
  }
  A.reconstructCurrent = reconstructCurrent;

  /* ================= cableado de la interfaz ================= */
  function bindRange(id, key, fmt) {
    var el = $(id), out = $(id + 'V');
    function upd() {
      P[key] = parseFloat(el.value);
      out.textContent = fmt ? fmt(P[key]) : P[key];
    }
    el.addEventListener('input', upd); upd();
  }

  function init() {
    A.ui.init();

    /* carga de archivos */
    $('file').addEventListener('change', function (e) { if (e.target.files[0]) loadFile(e.target.files[0]); });
    ['dragover', 'drop'].forEach(function (ev) {
      document.addEventListener(ev, function (e) { e.preventDefault(); });
    });
    document.addEventListener('drop', function (e) {
      if (e.dataTransfer.files && e.dataTransfer.files[0]) loadFile(e.dataTransfer.files[0]);
    });

    /* parametros */
    bindRange('pProc', 'proc');
    bindRange('pBlur', 'blur', function (v) { return v.toFixed(1); });
    bindRange('pLo', 'cannyLo', function (v) { return v.toFixed(2); });
    bindRange('pHi', 'cannyHi', function (v) { return v.toFixed(2); });
    bindRange('pMinSeg', 'minSegLen');
    bindRange('pDp', 'dpTol', function (v) { return v.toFixed(1); });
    bindRange('pVpTol', 'vpInlierDeg', function (v) { return v.toFixed(1); });
    bindRange('pSup', 'planeSupport', function (v) { return v.toFixed(2); });
    bindRange('pMaxPl', 'maxPlanes');
    $('pCamH').addEventListener('input', function () { P.camHeight = parseFloat(this.value) || 1.6; refreshPanels(); });

    /* capas */
    ['edges', 'segs', 'vps', 'planes', 'annots', 'ids'].forEach(function (k) {
      var el = $('show_' + k);
      el.checked = S.show[k];
      el.addEventListener('change', function () { S.show[k] = el.checked; A.ui.render(); });
    });

    /* modo */
    function setMode(m) {
      S.mode = m;
      $('modeAuto').classList.toggle('on', m === 'auto');
      $('modeLearn').classList.toggle('on', m === 'learn');
      $('learnBox').style.display = (m === 'learn') ? '' : 'none';
      A.ui.hud();
    }
    $('modeAuto').onclick = function () { setMode('auto'); };
    $('modeLearn').onclick = function () { setMode('learn'); };
    setMode('auto');

    /* herramientas */
    var tools = ['select', 'point', 'edge', 'plane', 'delete'];
    tools.forEach(function (t) {
      $('tool_' + t).onclick = function () {
        S.tool = t; A.ui.cancelPending();
        tools.forEach(function (x) { $('tool_' + x).classList.toggle('on', x === t); });
      };
    });
    $('tool_select').classList.add('on');

    /* clases */
    var cb = $('classes');
    A.CLASSES.forEach(function (c) {
      var d = document.createElement('span');
      d.className = 'chip' + (c.id === S.activeClass ? ' on' : '');
      d.innerHTML = '<span class="dot" style="background:' + c.color + '"></span>' + c.nom;
      d.onclick = function () {
        S.activeClass = c.id;
        cb.querySelectorAll('.chip').forEach(function (x) { x.classList.remove('on'); });
        d.classList.add('on');
        var sel = A.selected();
        if (sel && $('applyClassToSel').checked) { sel.cls = c.id; refreshPanels(); A.ui.render(); }
      };
      cb.appendChild(d);
    });

    /* deteccion */
    $('btnDetect').onclick = function () { if (S.media) { detect(); refreshPanels(); A.ui.render(); } };
    $('btnAcceptAll').onclick = function () {
      var det = S.detection; if (!det || !det.cands.length) { A.log('no hay planos detectados', 'w'); return; }
      det.cands.slice().forEach(function (c) { A.emit('acceptCandidate', c); });
    };

    /* navegacion */
    $('btnPrev').onclick = function () { gotoFrame(S.frame - 1); };
    $('btnNext').onclick = function () { gotoFrame(S.frame + 1); };
    $('btnPrev10').onclick = function () { gotoFrame(S.frame - 10); };
    $('btnNext10').onclick = function () { gotoFrame(S.frame + 10); };
    $('frameNo').addEventListener('change', function () { gotoFrame(parseInt(this.value, 10) || 0); });
    $('btnPlay').onclick = function () {
      playing = !playing;
      $('btnPlay').textContent = playing ? '⏸ pausa' : '▶ reproducir';
      if (playing) {
        playTimer = setInterval(function () {
          if (!S.media || busy) return;
          if (S.frame >= S.media.nFrames - 1) { $('btnPlay').click(); return; }
          gotoFrame(S.frame + 1);
        }, 120);
      } else clearInterval(playTimer);
    };
    $('track').addEventListener('click', function (e) {
      if (!S.media) return;
      var r = this.getBoundingClientRect();
      gotoFrame(Math.round((e.clientX - r.left) / r.width * (S.media.nFrames - 1)));
    });
    $('btnPropAll').onclick = function () { propagateAll(S.frame, S.media ? S.media.nFrames - 1 : 0); };
    $('btnPropStop').disabled = true;
    $('fps').addEventListener('change', function () {
      if (S.media && S.media.type === 'video') {
        S.media.fps = parseFloat(this.value) || 25;
        S.media.nFrames = Math.max(1, Math.floor(S.media.duration * S.media.fps));
        buildTrack(); updateTrack();
      }
    });
    $('autoTrack').addEventListener('change', function () { S.autoTrack = this.checked; });

    /* edicion de objetos */
    $('btnKey').onclick = function () {
      var o = A.selected(); if (!o) return;
      var pts = A.objAt(o, S.frame); if (!pts) return;
      A.setKey(o, S.frame, pts); A.log('keyframe fijado en f' + S.frame + ' (' + o.name + ')', 'o');
      refreshPanels(); updateTrack(); A.ui.render();
    };
    $('btnUnkey').onclick = function () {
      var o = A.selected(); if (!o) return;
      if (Object.keys(o.keys).length <= 1) { A.log('un objeto necesita al menos un keyframe', 'w'); return; }
      delete o.keys[S.frame]; refreshPanels(); updateTrack(); A.ui.render();
    };
    $('btnDelSel').onclick = function () {
      var o = A.selected(); if (!o) return;
      S.objects = S.objects.filter(function (x) { return x !== o; });
      S.selectedId = null; A.emit('objects'); A.ui.render();
    };
    $('btnClearTrack').onclick = function () {
      var o = A.selected(); if (!o) return;
      o.track = {}; A.log('cache de seguimiento borrada (' + o.name + ')');
      updateTrack(); A.ui.render();
    };
    $('btnRename').onclick = function () {
      var o = A.selected(); if (!o) return;
      var n = prompt('Nombre del objeto:', o.name);
      if (n) { o.name = n; refreshPanels(); A.ui.render(); }
    };

    /* aprendizaje */
    $('btnSample').onclick = function () {
      var o = A.selected();
      if (!o || o.kind !== 'plane') { A.log('selecciona un plano para anadirlo como muestra', 'w'); return; }
      if (addSampleFromObject(o)) { A.log('muestra anadida (' + o.cls + ')', 'o'); refreshPanels(); }
    };
    $('btnSampleAll').onclick = function () {
      var n = 0;
      S.objects.forEach(function (o) { if (o.kind === 'plane' && addSampleFromObject(o)) n++; });
      A.log(n + ' muestras anadidas desde los planos del frame actual', 'o'); refreshPanels();
    };
    $('btnTrain').onclick = function () {
      var m = ensureModel();
      var r = A.learn.train(m, parseInt($('epochs').value, 10) || 400, 0.25, parseFloat($('l2').value) || 0.004);
      if (!r.ok) { A.log(r.msg, 'w'); return; }
      A.learn.save(m);
      A.log('modelo entrenado: ' + r.n + ' muestras, ' + r.classes + ' clases, train ' +
            (r.trainAcc * 100).toFixed(0) + '%' + (r.testAcc != null ? ', test ' + (r.testAcc * 100).toFixed(0) + '% (' + r.nTest + ')' : ' (sin hold-out: pocas muestras)'), 'o');
      if (S.detection) { detect(); }
      refreshPanels(); A.ui.render();
    };
    $('btnPredict').onclick = function () {
      if (!S.model || !S.model.W) { A.log('entrena el modelo primero', 'w'); return; }
      var det = S.detection || detect(); if (!det) return;
      det.cands.forEach(function (c) { c.pred = A.learn.predictPoly(S.model, det, c.pts, det.calib, det.horizonY); });
      var sc = det.scale, n = 0;
      if ($('predictAnnots').checked) {
        S.objects.forEach(function (o) {
          if (o.kind !== 'plane') return;
          var pts = A.objAt(o, S.frame); if (!pts) return;
          var p = A.learn.predictPoly(S.model, det, pts.map(function (q) { return [q[0] * sc, q[1] * sc]; }), det.calib, det.horizonY);
          if (p) { o.predicted = p[0]; n++; if ($('applyPrediction').checked) o.cls = p[0].cls; }
        });
      }
      A.log('prediccion aplicada a ' + det.cands.length + ' candidatos' + (n ? ' y ' + n + ' anotaciones' : ''), 'o');
      refreshPanels(); A.ui.render();
    };
    $('btnModelReset').onclick = function () {
      if (!confirm('Borrar todas las muestras y el modelo aprendido?')) return;
      S.model = A.learn.newModel(); A.learn.save(S.model);
      A.log('modelo reiniciado', 'w'); refreshPanels();
    };

    /* proyecto y exportacion */
    $('btnSaveProj').onclick = function () {
      A.export.download('auto3d_proyecto.json', JSON.stringify(A.export.project(), null, 1), 'application/json');
    };
    $('projFile').addEventListener('change', function (e) {
      var f = e.target.files[0]; if (!f) return;
      var rd = new FileReader();
      rd.onload = function () {
        try {
          var n = A.export.loadProject(JSON.parse(rd.result));
          A.log('proyecto cargado: ' + n + ' objetos', 'o');
          refreshPanels(); updateTrack(); A.ui.render();
        } catch (err) { A.log('error al cargar proyecto: ' + err.message, 'e'); }
      };
      rd.readAsText(f);
    });
    $('btnObj').onclick = function () {
      var r = reconstructCurrent();
      r.errs.forEach(function (e) { A.log(e, 'w'); });
      if (!r.recons.length) { A.log('no hay geometria reconstruible en este frame', 'e'); return; }
      A.export.download('auto3d_f' + S.frame + '.obj', A.export.obj(r.recons, 'frame ' + S.frame + ' de ' + (S.media ? S.media.name : '')), 'text/plain');
      A.export.download('auto3d.mtl', A.export.mtl(), 'text/plain');
    };
    $('btnCsv').onclick = function () { A.export.download('auto3d_anotaciones.csv', A.export.csv(), 'text/csv'); };
    $('btnDataset').onclick = function () { A.export.download('auto3d_dataset.json', JSON.stringify(A.export.dataset(), null, 1), 'application/json'); };

    /* teclado */
    window.addEventListener('keydown', function (e) {
      if (/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      switch (e.key) {
        case 'ArrowRight': gotoFrame(S.frame + (e.shiftKey ? 10 : 1)); e.preventDefault(); break;
        case 'ArrowLeft': gotoFrame(S.frame - (e.shiftKey ? 10 : 1)); e.preventDefault(); break;
        case 'Escape': A.ui.cancelPending(); break;
        case 'Enter': A.ui.cancelPending(); break;
        case 'Delete': $('btnDelSel').click(); break;
        case 'k': case 'K': $('btnKey').click(); break;
        case 'd': case 'D': $('btnDetect').click(); break;
        case 'f': case 'F': A.ui.fit(); break;
        case 'v': case 'V': $('tool_select').click(); break;
        case 'p': case 'P': $('tool_point').click(); break;
        case 'e': case 'E': $('tool_edge').click(); break;
        case 'g': case 'G': $('tool_plane').click(); break;
      }
    });

    /* secciones plegables */
    document.querySelectorAll('.sec>h3').forEach(function (h) {
      h.onclick = function () { h.parentNode.classList.toggle('collapsed'); };
    });

    /* modelo guardado */
    var m0 = A.learn.load();
    if (m0) { S.model = m0; A.log('modelo recuperado del navegador: ' + m0.samples.length + ' muestras', 'o'); }
    refreshPanels();
    A.log('AUTO3D listo. Arrastra una foto o un video sobre la ventana.', 'o');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window.A3D);
