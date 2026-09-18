/* AUTO3D - ui.js : dibujo del lienzo, interaccion con raton y paneles. */
(function (A) {
  'use strict';
  var U = A.ui = {};
  var base, ov, bctx, octx, stage;
  var drag = null, pending = [];      // poligono/arista en construccion
  var hoverCand = null;

  U.init = function () {
    stage = document.getElementById('stage');
    base = document.getElementById('cvBase');
    ov = document.getElementById('cvOver');
    bctx = base.getContext('2d', { willReadFrequently: true });
    octx = ov.getContext('2d');
    stage.addEventListener('mousedown', onDown);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    stage.addEventListener('wheel', onWheel, { passive: false });
    stage.addEventListener('dblclick', onDbl);
    stage.addEventListener('contextmenu', function (e) { e.preventDefault(); closePending(); });
    window.addEventListener('resize', U.fit);
  };

  U.resizeTo = function (w, h) {
    base.width = w; base.height = h; ov.width = w; ov.height = h;
    U.fit();
  };
  U.fit = function () {
    var s = A.state;
    if (!s.media) return;
    var r = stage.getBoundingClientRect();
    var z = Math.min(r.width / s.media.w, r.height / s.media.h) * 0.97;
    s.zoom = z;
    s.panX = (r.width - s.media.w * z) / 2;
    s.panY = (r.height - s.media.h * z) / 2;
    U.applyXform();
    U.render();
  };
  U.applyXform = function () {
    var s = A.state, t = 'translate(' + s.panX + 'px,' + s.panY + 'px) scale(' + s.zoom + ')';
    base.style.transform = t; ov.style.transform = t;
  };
  U.ctxBase = function () { return bctx; };

  function screenToImg(e) {
    var r = stage.getBoundingClientRect(), s = A.state;
    return [(e.clientX - r.left - s.panX) / s.zoom, (e.clientY - r.top - s.panY) / s.zoom];
  }
  U.screenToImg = screenToImg;

  /* ---------------- dibujo ---------------- */
  var edgeCv = document.createElement('canvas');
  function drawEdges(det, sc) {
    if (!det) return;
    if (edgeCv.width !== det.w || edgeCv.height !== det.h) { edgeCv.width = det.w; edgeCv.height = det.h; }
    var c = edgeCv.getContext('2d'), im = c.createImageData(det.w, det.h), d = im.data;
    for (var i = 0, j = 0; i < det.edges.length; i++, j += 4) {
      if (det.edges[i]) { d[j] = 90; d[j + 1] = 240; d[j + 2] = 255; d[j + 3] = 190; }
    }
    c.putImageData(im, 0, 0);
    octx.save(); octx.globalAlpha = 0.42;
    octx.drawImage(edgeCv, 0, 0, det.w, det.h, 0, 0, det.w / sc, det.h / sc);
    octx.restore();
  }

  var VPCOL = ['#ff5f5f', '#5fff9d', '#5fa8ff'];

  U.render = function () {
    var s = A.state;
    if (!s.media) return;
    octx.clearRect(0, 0, ov.width, ov.height);
    var lw = 1.6 / s.zoom, det = s.detection, sc = det ? det.scale : 1;

    if (det && s.show.edges) drawEdges(det, sc);

    if (det && s.show.segs) {
      octx.lineWidth = lw * 1.1;
      det.segs.forEach(function (sg) {
        octx.strokeStyle = sg.vp >= 0 ? VPCOL[sg.vp % 3] : 'rgba(255,255,255,.28)';
        octx.beginPath();
        octx.moveTo(sg.p[0] / sc, sg.p[1] / sc);
        octx.lineTo(sg.q[0] / sc, sg.q[1] / sc);
        octx.stroke();
      });
    }

    if (det && s.show.vps && det.horizon) {
      var H = det.horizon, W = base.width;
      var y0 = -(H[0] * 0 + H[2]) / (H[1] || 1e-9) / sc;
      var y1 = -(H[0] * (W * sc) + H[2]) / (H[1] || 1e-9) / sc;
      octx.save();
      octx.strokeStyle = '#ffd25f'; octx.lineWidth = lw; octx.setLineDash([9 / s.zoom, 6 / s.zoom]);
      octx.beginPath(); octx.moveTo(0, y0); octx.lineTo(W, y1); octx.stroke();
      octx.restore();
      octx.fillStyle = '#ffd25f';
      octx.font = (12 / s.zoom) + 'px sans-serif';
      octx.fillText('horizonte', 6 / s.zoom, y0 - 5 / s.zoom);
    }

    if (det && s.show.planes && det.cands) {
      det.cands.forEach(function (c, i) {
        var col = c.pred ? A.classById(c.pred[0].cls).color : '#7fd3ff';
        octx.save();
        octx.strokeStyle = col; octx.lineWidth = lw * (hoverCand === c ? 2.8 : 1.5);
        octx.beginPath();
        c.pts.forEach(function (p, k) { var x = p[0] / sc, y = p[1] / sc; k ? octx.lineTo(x, y) : octx.moveTo(x, y); });
        octx.closePath();
        // solo se rellena el candidato bajo el raton: con 10 planos superpuestos
        // el relleno tapaba la foto y hacia imposible juzgar la deteccion
        if (hoverCand === c) { octx.fillStyle = col + '33'; octx.fill(); }
        octx.stroke();
        var cc = A.polyCentroid(c.pts);
        octx.fillStyle = col; octx.font = (12 / s.zoom) + 'px sans-serif';
        var lab = 'P' + (i + 1) + '  ' + (c.score * 100).toFixed(0) + '%';
        if (c.pred) lab += '  ' + c.pred[0].cls + ' ' + (c.pred[0].p * 100).toFixed(0) + '%';
        octx.fillText(lab, cc[0] / sc - 22 / s.zoom, cc[1] / sc);
        octx.restore();
      });
    }

    if (s.show.annots) {
      s.objects.forEach(function (o) {
        if (!o.visible) return;
        var pts = A.objAt(o, s.frame);
        if (!pts) return;
        var col = A.classById(o.cls).color, sel = (o.id === s.selectedId);
        var isKey = A.isKey(o, s.frame);
        octx.save();
        octx.lineWidth = (sel ? 2.8 : 1.8) / s.zoom;
        octx.strokeStyle = col;
        octx.setLineDash(isKey ? [] : [6 / s.zoom, 4 / s.zoom]);
        if (o.kind === 'plane' && pts.length >= 3) {
          octx.fillStyle = col + (sel ? '44' : '24');
          octx.beginPath();
          pts.forEach(function (p, k) { k ? octx.lineTo(p[0], p[1]) : octx.moveTo(p[0], p[1]); });
          octx.closePath(); octx.fill(); octx.stroke();
        } else if (pts.length >= 2) {
          octx.beginPath();
          pts.forEach(function (p, k) { k ? octx.lineTo(p[0], p[1]) : octx.moveTo(p[0], p[1]); });
          octx.stroke();
        }
        octx.setLineDash([]);
        pts.forEach(function (p) {
          octx.beginPath(); octx.arc(p[0], p[1], (sel ? 4.6 : 3.2) / s.zoom, 0, 6.2832);
          octx.fillStyle = isKey ? col : '#0b0d11';
          octx.fill(); octx.strokeStyle = col; octx.lineWidth = 1.4 / s.zoom; octx.stroke();
        });
        if (s.show.ids || sel) {
          var c0 = A.polyCentroid(pts);
          octx.fillStyle = col; octx.font = (12 / s.zoom) + 'px sans-serif';
          octx.fillText(o.name + (isKey ? ' *' : ''), c0[0] + 6 / s.zoom, c0[1] - 6 / s.zoom);
        }
        octx.restore();
      });
    }

    if (pending.length) {
      var col2 = A.classById(A.state.activeClass).color;
      octx.save(); octx.strokeStyle = col2; octx.lineWidth = 2 / s.zoom;
      octx.setLineDash([5 / s.zoom, 4 / s.zoom]);
      octx.beginPath();
      pending.forEach(function (p, k) { k ? octx.lineTo(p[0], p[1]) : octx.moveTo(p[0], p[1]); });
      octx.stroke(); octx.restore();
      pending.forEach(function (p) {
        octx.beginPath(); octx.arc(p[0], p[1], 3.6 / s.zoom, 0, 6.2832);
        octx.fillStyle = col2; octx.fill();
      });
    }
    U.hud();
  };

  U.hud = function () {
    var s = A.state, el = document.getElementById('hud');
    if (!el) return;
    var d = s.detection, L = [];
    L.push('frame ' + s.frame + (s.media && s.media.nFrames > 1 ? ' / ' + (s.media.nFrames - 1) : ''));
    if (d) {
      L.push('segmentos ' + d.segs.length + '   vp ' + d.vps.length);
      if (d.calib) L.push('f ' + d.calib.f.toFixed(0) + ' px   fov ' + (2 * A.deg(Math.atan(d.w / 2 / d.calib.f))).toFixed(0) + '°');
      else L.push('sin calibracion');
      L.push('planos auto ' + (d.cands ? d.cands.length : 0));
    }
    L.push('objetos ' + s.objects.length + '   modo ' + s.mode.toUpperCase());
    el.textContent = L.join('\n');
  };

  /* ---------------- interaccion ---------------- */
  function hitVertex(pt) {
    var s = A.state, tol = 9 / s.zoom, best = null, bd = tol;
    s.objects.forEach(function (o) {
      if (!o.visible || o.locked) return;
      var pts = A.objAt(o, s.frame); if (!pts) return;
      pts.forEach(function (p, i) {
        var d = A.dist(p, pt);
        if (d < bd) { bd = d; best = { o: o, i: i }; }
      });
    });
    return best;
  }
  function hitObject(pt) {
    var s = A.state, best = null, bd = 12 / s.zoom;
    s.objects.forEach(function (o) {
      if (!o.visible) return;
      var pts = A.objAt(o, s.frame); if (!pts) return;
      if (o.kind === 'plane' && pts.length >= 3 && A.pointInPoly(pt, pts)) { best = o; bd = 0; return; }
      for (var i = 0; i < pts.length - (o.kind === 'plane' ? 0 : 1); i++) {
        var d = A.distToSeg(pt, pts[i], pts[(i + 1) % pts.length]);
        if (d < bd) { bd = d; best = o; }
      }
      if (pts.length === 1 && A.dist(pts[0], pt) < bd) { bd = A.dist(pts[0], pt); best = o; }
    });
    return best;
  }
  function hitCandidate(pt) {
    var s = A.state, d = s.detection;
    if (!d || !d.cands) return null;
    for (var i = 0; i < d.cands.length; i++) {
      var pp = d.cands[i].pts.map(function (p) { return [p[0] / d.scale, p[1] / d.scale]; });
      if (A.pointInPoly(pt, pp)) return d.cands[i];
    }
    return null;
  }

  function onDown(e) {
    if (!A.state.media) return;
    var s = A.state, pt = screenToImg(e);
    if (e.button === 1 || (e.button === 0 && e.altKey)) { drag = { type: 'pan', x: e.clientX, y: e.clientY, px: s.panX, py: s.panY }; e.preventDefault(); return; }
    if (e.button !== 0) return;

    if (s.tool === 'point') { commit('point', [pt]); return; }
    if (s.tool === 'edge' || s.tool === 'plane') {
      pending.push(pt);
      if (s.tool === 'edge' && pending.length === 2) closePending();
      U.render(); return;
    }
    if (s.tool === 'delete') {
      var o = hitObject(pt);
      if (o) { s.objects = s.objects.filter(function (x) { return x !== o; }); A.emit('objects'); U.render(); A.log('borrado ' + o.name, 'w'); }
      return;
    }
    // select / move
    var hv = hitVertex(pt);
    if (hv) {
      s.selectedId = hv.o.id;
      var cur = A.objAt(hv.o, s.frame).map(function (p) { return p.slice(); });
      drag = { type: 'vertex', o: hv.o, i: hv.i, pts: cur };
      A.emit('select'); U.render(); return;
    }
    var ob = hitObject(pt);
    if (ob) {
      s.selectedId = ob.id;
      var cur2 = A.objAt(ob, s.frame).map(function (p) { return p.slice(); });
      drag = { type: 'obj', o: ob, pts: cur2, start: pt };
      A.emit('select'); U.render(); return;
    }
    var cand = hitCandidate(pt);
    if (cand) { A.emit('acceptCandidate', cand); return; }
    s.selectedId = null; A.emit('select'); U.render();
  }

  function onMove(e) {
    var s = A.state;
    if (!s.media) return;
    if (!drag) {
      if (s.tool === 'select' && s.detection) {
        var h = hitCandidate(screenToImg(e));
        if (h !== hoverCand) { hoverCand = h; U.render(); }
      }
      if (pending.length) U.render();
      return;
    }
    if (drag.type === 'pan') {
      s.panX = drag.px + (e.clientX - drag.x); s.panY = drag.py + (e.clientY - drag.y);
      U.applyXform(); return;
    }
    var pt = screenToImg(e);
    if (drag.type === 'vertex') {
      var p2 = drag.pts.map(function (p) { return p.slice(); });
      p2[drag.i] = pt;
      A.setKey(drag.o, s.frame, p2);
    } else if (drag.type === 'obj') {
      var dx = pt[0] - drag.start[0], dy = pt[1] - drag.start[1];
      A.setKey(drag.o, s.frame, drag.pts.map(function (p) { return [p[0] + dx, p[1] + dy]; }));
    }
    U.render();
  }
  function onUp() {
    if (drag && (drag.type === 'vertex' || drag.type === 'obj')) {
      A.log('keyframe en ' + A.state.frame + ' para ' + drag.o.name);
      A.emit('objects');
    }
    drag = null;
  }
  function onDbl(e) { if (pending.length >= 3) { closePending(); e.preventDefault(); } }
  function onWheel(e) {
    e.preventDefault();
    var s = A.state, r = stage.getBoundingClientRect();
    var mx = e.clientX - r.left, my = e.clientY - r.top;
    var ix = (mx - s.panX) / s.zoom, iy = (my - s.panY) / s.zoom;
    var f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
    s.zoom = A.clamp(s.zoom * f, 0.05, 20);
    s.panX = mx - ix * s.zoom; s.panY = my - iy * s.zoom;
    U.applyXform(); U.render();
  }

  function closePending() {
    var s = A.state;
    if (s.tool === 'edge' && pending.length >= 2) commit('edge', pending.slice(0, 2));
    else if (s.tool === 'plane' && pending.length >= 3) commit('plane', pending.slice());
    pending = []; U.render();
  }
  U.cancelPending = function () { pending = []; U.render(); };

  function commit(kind, pts) {
    var s = A.state;
    var o = A.newObject(kind, s.activeClass, pts, s.frame);
    s.objects.push(o); s.selectedId = o.id;
    pending = [];
    A.emit('objects'); A.emit('select'); A.emit('newAnnotation', o);
    U.render();
    A.log('nuevo ' + kind + ' [' + o.cls + '] ' + o.name, 'o');
  }
  U.commit = commit;
})(window.A3D);
