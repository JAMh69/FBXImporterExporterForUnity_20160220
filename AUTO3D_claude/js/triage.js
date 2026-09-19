/* AUTO3D - triage.js : explora una carpeta y clasifica el material de vuelo
   segun sirva o no para reconstruir edificios.

   Lee solo la cabecera de cada archivo (128 KB), que es donde viven el EXIF y
   el XMP, asi que recorrer miles de fotos de 20 MB cuesta segundos y no
   minutos. Nada sale del equipo. */
(function (A) {
  'use strict';
  var T = A.triage = {};

  var CABECERA = 131072;          // bytes que se leen de cada foto
  var TIERRA = 6378137;

  /* Umbrales. Un vuelo cenital no ve fachadas: el escorzo de una pared
     vertical es el seno del angulo respecto a la vertical, y justo bajo el
     dron ese angulo vale cero. */
  T.LIMITES = {
    cenital: -75,      // por debajo, toma cenital
    frontal: -30,      // entre esto y la horizontal, fachada vista de frente
    /* Solo es cielo lo que apunta por encima de la horizontal. El umbral
       estuvo en -10 grados y era un error que destapo el material real: habia
       vuelos enteros con el gimbal fijo a -9 grados, que es casi horizontal y
       precisamente la mejor toma para una fachada alta. */
    cielo: 0,
    recorridoMin: 5,   // m, por debajo no hay paralaje
    anguloMin: 20,     // grados barridos
    acimutMin: 0.5     // fraccion de sectores cubiertos
  };

  /* ---------- lectura de cabeceras ---------- */
  function leerCabecera(file) {
    return new Promise(function (res, rej) {
      var fr = new FileReader();
      fr.onload = function () { res(new Uint8Array(fr.result)); };
      fr.onerror = function () { rej(new Error('no se pudo leer ' + file.name)); };
      fr.readAsArrayBuffer(file.slice(0, Math.min(CABECERA, file.size)));
    });
  }
  function leerTexto(file, max) {
    return new Promise(function (res, rej) {
      var fr = new FileReader();
      fr.onload = function () { res(fr.result); };
      fr.onerror = function () { rej(new Error('no se pudo leer ' + file.name)); };
      fr.readAsText(file.slice(0, max || file.size));
    });
  }
  function aTexto(bytes) {
    var s = '', n = bytes.length;
    for (var i = 0; i < n; i++) s += String.fromCharCode(bytes[i]);
    return s;
  }

  /* ---------- XMP de DJI ----------
     Es texto plano dentro del JPEG. Trae lo que el EXIF no da: los tres
     angulos del gimbal, la altura sobre el despegue y, si el equipo lleva
     RTK, la precision de cada disparo. */
  var CAMPOS_XMP = ['GpsStatus', 'GpsLatitude', 'GpsLongitude', 'AbsoluteAltitude',
    'RelativeAltitude', 'GimbalRollDegree', 'GimbalYawDegree', 'GimbalPitchDegree',
    'FlightRollDegree', 'FlightYawDegree', 'FlightPitchDegree', 'DroneModel',
    'ImageSource', 'RtkFlag', 'RtkStdLon', 'RtkStdLat', 'RtkStdHgt', 'AltitudeType',
    'SurveyingMode', 'CameraSerialNumber', 'DroneSerialNumber'];

  T.leerXMP = function (texto) {
    var ini = texto.indexOf('<x:xmpmeta');
    if (ini < 0) return null;
    var fin = texto.indexOf('</x:xmpmeta>');
    var xmp = texto.slice(ini, fin > 0 ? fin + 12 : undefined);
    var out = {};
    CAMPOS_XMP.forEach(function (c) {
      var m = new RegExp('drone-dji:' + c + '\\s*=\\s*"([^"]*)"').exec(xmp);
      if (!m) m = new RegExp('<drone-dji:' + c + '>([^<]*)<').exec(xmp);
      if (m) out[c] = m[1].trim();
    });
    return Object.keys(out).length ? out : null;
  };

  /* ---------- EXIF minimo ----------
     Solo lo que hace falta para el triaje: tamaño, fecha, equipo y focal
     equivalente. No se pretende un lector completo. */
  T.leerEXIF = function (bytes) {
    var out = {}, n = bytes.length, i = 2;
    if (bytes[0] !== 0xFF || bytes[1] !== 0xD8) return out;
    while (i < n - 3) {
      if (bytes[i] !== 0xFF) { i++; continue; }
      var marca = bytes[i + 1];
      if (marca === 0xD8 || (marca >= 0xD0 && marca <= 0xD9)) { i += 2; continue; }
      var largo = (bytes[i + 2] << 8) | bytes[i + 3];
      // SOF: el tamaño real de la imagen decodificada, que manda sobre el EXIF
      if ((marca >= 0xC0 && marca <= 0xCF) && marca !== 0xC4 && marca !== 0xC8 && marca !== 0xCC) {
        out.alto = (bytes[i + 5] << 8) | bytes[i + 6];
        out.ancho = (bytes[i + 7] << 8) | bytes[i + 8];
      }
      if (marca === 0xE1 && aTexto(bytes.subarray(i + 4, i + 10)) === 'Exif\0\0') {
        try { leerTiff(bytes, i + 10, out); } catch (e) { /* EXIF ilegible: no es fatal */ }
      }
      if (marca === 0xDA) break;                   // empieza la imagen
      i += 2 + largo;
    }
    return out;
  };

  function leerTiff(bytes, base, out) {
    var le = aTexto(bytes.subarray(base, base + 2)) === 'II';
    function u16(p) { return le ? bytes[p] | (bytes[p + 1] << 8) : (bytes[p] << 8) | bytes[p + 1]; }
    function u32(p) {
      return le ? (bytes[p] | (bytes[p + 1] << 8) | (bytes[p + 2] << 16) | (bytes[p + 3] << 24)) >>> 0
                : ((bytes[p] << 24) | (bytes[p + 1] << 16) | (bytes[p + 2] << 8) | bytes[p + 3]) >>> 0;
    }
    function texto(p, len) { return aTexto(bytes.subarray(p, p + len)).replace(/\0+$/, ''); }
    var INTERES = { 0x010F: 'marca', 0x0110: 'modelo', 0x9003: 'fecha', 0xA405: 'focal35',
                    0x920A: 'focal', 0x8769: '_exif' };
    function ifd(offset) {
      if (offset + 2 > bytes.length) return;
      var cuenta = u16(base + offset);
      for (var k = 0; k < cuenta; k++) {
        var p = base + offset + 2 + k * 12;
        if (p + 12 > bytes.length) return;
        var etiqueta = u16(p), tipo = u16(p + 2), num = u32(p + 4);
        var nombre = INTERES[etiqueta];
        if (!nombre) continue;
        var valor;
        if (tipo === 2) {                                    // texto
          var dir = num > 4 ? base + u32(p + 8) : p + 8;
          valor = texto(dir, num - 1);
        } else if (tipo === 3) { valor = u16(p + 8); }       // entero corto
        else if (tipo === 4) { valor = u32(p + 8); }         // entero largo
        else if (tipo === 5) {                               // racional
          var d = base + u32(p + 8);
          valor = u32(d) / (u32(d + 4) || 1);
        }
        if (nombre === '_exif') ifd(u32(p + 8));
        else if (valor !== undefined) out[nombre] = valor;
      }
    }
    ifd(u32(base + 4));
  }

  /* ---------- telemetria .SRT de video ---------- */
  T.leerSRT = function (texto) {
    var frames = [], bloques = texto.split(/\n\s*\n/);
    bloques.forEach(function (b) {
      var reg = {};
      var grupos = b.match(/\[[^\]]*\]/g) || [];
      grupos.forEach(function (g) {
        var re = /([a-zA-Z_]+)\s*:\s*([^\s,\]]+)/g, m;
        while ((m = re.exec(g))) {
          var v = parseFloat(m[2]);
          reg[m[1]] = isNaN(v) ? m[2] : v;
        }
      });
      if (reg.latitude !== undefined) frames.push(reg);
    });
    return frames;
  };

  /* ---------- posiciones RTK .MRK ---------- */
  T.leerMRK = function (texto) {
    var out = [];
    texto.split(/\r?\n/).forEach(function (linea) {
      var p = linea.split('\t');
      if (p.length < 11) return;
      var lat = parseFloat(p[6]), lon = parseFloat(p[7]), h = parseFloat(p[8]);
      var sd = p[9].split(',').map(parseFloat);
      if (isNaN(lat) || isNaN(lon)) return;
      out.push({ disparo: parseInt(p[0], 10), lat: lat, lon: lon, alt: h,
                 sigma: sd, flag: parseInt(p[10], 10) });
    });
    return out;
  };

  /* ---------- geometria del vuelo ---------- */
  function locales(lats, lons, alts) {
    if (!lats.length) return [];
    var refLat = lats.reduce(function (a, b) { return a + b; }, 0) / lats.length;
    var k = Math.cos(refLat * Math.PI / 180);
    return lats.map(function (la, i) {
      return [(lons[i] - lons[0]) * Math.PI / 180 * TIERRA * k,
              (la - lats[0]) * Math.PI / 180 * TIERRA,
              alts[i] || 0];
    });
  }
  T.locales = locales;

  function recorrido(P) {
    var s = 0;
    for (var i = 1; i < P.length; i++) {
      s += Math.hypot(P[i][0] - P[i - 1][0], P[i][1] - P[i - 1][1], P[i][2] - P[i - 1][2]);
    }
    return s;
  }
  /* Angulo maximo barrido sobre un punto del suelo: dice cuanta base hay.

     **El valor depende de donde se suponga el suelo**, y ese dato no siempre
     se tiene. Con alturas relativas al despegue el suelo esta en cero; con
     alturas elipsoidales -las del .MRK rondan los 716 m- cero caeria 716 m por
     debajo y todos los rayos saldrian casi paralelos: el vuelo real de 167
     grados se medía como 6.

     Por eso `sueloZ` es un argumento explicito y no una suposicion escondida.
     Cuando no se sabe, se toma la cota mas baja del vuelo, que sobreestima el
     angulo si el dron nunca bajo hasta el objeto. La cobertura de acimut, en
     cambio, no depende de esta suposicion: es el indicador robusto. */
  function anguloBarrido(P, sueloZ) {
    if (P.length < 2) return 0;
    var cx = 0, cy = 0, cz = P[0][2];
    P.forEach(function (p) { cx += p[0]; cy += p[1]; if (p[2] < cz) cz = p[2]; });
    cx /= P.length; cy /= P.length;
    if (sueloZ !== undefined && sueloZ !== null) cz = sueloZ;
    var u = [];
    P.forEach(function (p) {
      var v = [p[0] - cx, p[1] - cy, p[2] - cz], n = Math.hypot(v[0], v[1], v[2]);
      if (n > 1e-6) u.push([v[0] / n, v[1] / n, v[2] / n]);
    });
    if (u.length < 2) return 0;
    // muestreo si hay muchisimas tomas: el maximo no cambia y el coste baja
    var paso = Math.max(1, Math.floor(u.length / 120)), max = 1;
    for (var i = 0; i < u.length; i += paso) {
      for (var j = i + paso; j < u.length; j += paso) {
        var c = u[i][0] * u[j][0] + u[i][1] * u[j][1] + u[i][2] * u[j][2];
        if (c < max) max = c;
      }
    }
    return Math.acos(Math.max(-1, Math.min(1, max))) * 180 / Math.PI;
  }
  /* Reparto por sectores de acimut: dice si esa base rodea al objeto.
     Hace falta ademas del angulo, no en su lugar: una pasada recta larga
     barre mas angulo que una orbita cerrada y sin embargo ve el edificio
     siempre desde el mismo lado. */
  function acimut(P, sectores) {
    sectores = sectores || 12;
    var h = new Array(sectores).fill(0);
    if (P.length < 2) return h;
    var cx = 0, cy = 0;
    P.forEach(function (p) { cx += p[0]; cy += p[1]; });
    cx /= P.length; cy /= P.length;
    P.forEach(function (p) {
      var a = Math.atan2(p[1] - cy, p[0] - cx) * 180 / Math.PI;
      var k = Math.floor((a + 180) / 360 * sectores);
      h[Math.min(sectores - 1, Math.max(0, k))]++;
    });
    return h;
  }
  T.anguloBarrido = anguloBarrido;
  T.acimut = acimut;

  /* ---------- clasificacion de un vuelo ---------- */
  T.evaluar = function (v) {
    var L = T.LIMITES, avisos = [], notas = [];
    var pitches = v.pitches || [];
    var cen = pitches.filter(function (p) { return p <= L.cenital; }).length / (pitches.length || 1);
    var cielo = pitches.filter(function (p) { return p >= L.cielo; }).length;
    var obl = pitches.filter(function (p) { return p > L.cenital && p < L.cielo; }).length / (pitches.length || 1);
    var acim = v.acimut || [];
    var llenos = acim.filter(function (c) { return c > 0; }).length / (acim.length || 1);

    var frontal = pitches.filter(function (p) {
      return p >= L.frontal && p < L.cielo;
    }).length / (pitches.length || 1);
    var tipo;
    if (!pitches.length) tipo = 'sin angulos de gimbal';
    else if (cen > 0.85) tipo = 'malla cenital: cubiertas y huellas, no fachadas';
    else if (frontal > 0.85) tipo = 'casi horizontal: fachada de frente';
    else if (obl > 0.85) tipo = 'oblicuo: bueno para fachadas';
    else if (cen > 0.2 && obl > 0.2) tipo = 'mixto: cenital y oblicuo, lo ideal';
    else if (cielo / pitches.length > 0.5) tipo = 'apunta por encima de la horizontal';
    else tipo = 'irregular';

    /* Puntuacion sobre 100. Pesa mas lo que mas condiciona el resultado:
       sin movimiento no hay nada que hacer, y sin acimut faltan caras. */
    var nota = 0;
    nota += Math.min(30, (v.recorrido || 0) / 50 * 30);              // movimiento
    nota += Math.min(25, (v.angulo || 0) / 90 * 25);                 // base
    nota += llenos * 25;                                             // rodea al objeto
    nota += (obl > 0.15 ? 15 : 0);                                   // ve fachadas
    nota += (v.rtk ? 5 : 0);                                         // precision
    nota = Math.round(Math.max(0, Math.min(100, nota)));

    if ((v.recorrido || 0) < L.recorridoMin) {
      avisos.push('el dron apenas se mueve: sin paralaje no hay reconstruccion');
      nota = Math.min(nota, 10);
    }
    if ((v.angulo || 0) < L.anguloMin) avisos.push('solo ' + Math.round(v.angulo || 0) + '° barridos: triangulacion debil');
    if (llenos < L.acimutMin) avisos.push('solo se cubre el ' + Math.round(llenos * 100) + ' % del acimut: el edificio se ve siempre desde el mismo lado');
    if (cen > 0.85) avisos.push('todo cenital: dara cubiertas y huellas, no fachadas');
    if (cielo) avisos.push(cielo + ' tomas apuntando al cielo: apartalas antes de procesar');
    if (v.rtk) notas.push('RTK con ' + (v.rtk * 100).toFixed(1) + ' cm de desviacion tipica');
    if (obl > 0.15 && llenos >= L.acimutMin && (v.recorrido || 0) >= L.recorridoMin) {
      notas.push('ve fachadas y rodea al objeto: sirve para modelar el edificio');
    }

    var veredicto;
    if (nota >= 75) veredicto = 'excelente';
    else if (nota >= 55) veredicto = 'util';
    else if (nota >= 30) veredicto = 'limitado';
    else veredicto = 'no sirve';

    return { tipo: tipo, nota: nota, veredicto: veredicto, avisos: avisos, notas: notas,
             cenital: cen, oblicuo: obl, cielo: cielo, acimutLleno: llenos };
  };

  /* ---------- recorrido de la carpeta ---------- */
  function carpetaDe(file) {
    var ruta = file.webkitRelativePath || file.name;
    var partes = ruta.split('/');
    partes.pop();
    return partes.join('/') || '(raiz)';
  }
  function baseDe(nombre) { return nombre.replace(/\.[^.]+$/, ''); }

  /* Agrupa en vuelos por carpeta y por saltos de tiempo. El nombre de carpeta
     suele bastar, pero una misma carpeta puede guardar dos salidas del mismo
     dia, y el corte por tiempo lo resuelve. */
  function agrupar(fotos, huecoMin) {
    huecoMin = (huecoMin || 20) * 60000;
    fotos.sort(function (a, b) {
      return a.carpeta === b.carpeta ? a.tiempo - b.tiempo : (a.carpeta < b.carpeta ? -1 : 1);
    });
    var vuelos = [], actual = [];
    fotos.forEach(function (f) {
      if (actual.length) {
        var p = actual[actual.length - 1];
        if (f.carpeta !== p.carpeta || (f.tiempo - p.tiempo) > huecoMin) {
          vuelos.push(actual); actual = [];
        }
      }
      actual.push(f);
    });
    if (actual.length) vuelos.push(actual);
    return vuelos;
  }

  /* Explora una lista de File. `avance` recibe (hechos, total, mensaje). */
  T.explorar = function (files, avance) {
    var fotos = [], videos = [], srts = {}, mrks = {}, otros = 0;
    var lista = Array.prototype.slice.call(files);
    var imagenes = lista.filter(function (f) { return /\.(jpe?g)$/i.test(f.name); });
    var auxiliares = lista.filter(function (f) { return /\.(srt|mrk)$/i.test(f.name); });
    lista.forEach(function (f) {
      if (/\.(mp4|mov|m4v|avi|mkv)$/i.test(f.name)) videos.push(f);
      else if (!/\.(jpe?g|srt|mrk)$/i.test(f.name)) otros++;
    });
    var total = imagenes.length + auxiliares.length;
    var hechos = 0;

    function paso(msg) { hechos++; if (avance) avance(hechos, total, msg); }

    return Promise.resolve()
      .then(function () {
        return serie(auxiliares, function (f) {
          return leerTexto(f, /\.srt$/i.test(f.name) ? 4e6 : 8e6).then(function (txt) {
            var clave = carpetaDe(f) + '/' + baseDe(f.name);
            if (/\.srt$/i.test(f.name)) srts[clave] = { file: f, frames: T.leerSRT(txt) };
            else mrks[clave] = { file: f, disparos: T.leerMRK(txt) };
            paso(f.name);
          }).catch(function () { paso(f.name); });
        });
      })
      .then(function () {
        return serie(imagenes, function (f) {
          return leerCabecera(f).then(function (bytes) {
            var txt = aTexto(bytes);
            var xmp = T.leerXMP(txt), exif = T.leerEXIF(bytes);
            fotos.push({
              nombre: f.name, carpeta: carpetaDe(f), bytes: f.size,
              tiempo: f.lastModified || 0,
              ancho: exif.ancho, alto: exif.alto, modelo: (xmp && xmp.DroneModel) || exif.modelo || '',
              focal35: exif.focal35,
              lat: xmp ? parseFloat(xmp.GpsLatitude) : NaN,
              lon: xmp ? parseFloat(xmp.GpsLongitude) : NaN,
              alt: xmp ? parseFloat(xmp.RelativeAltitude) : NaN,
              pitch: xmp ? parseFloat(xmp.GimbalPitchDegree) : NaN,
              yaw: xmp ? parseFloat(xmp.GimbalYawDegree) : NaN,
              rtk: xmp && xmp.RtkStdLon ? parseFloat(xmp.RtkStdLon) : NaN,
              gps: xmp ? xmp.GpsStatus : '',
              xmp: !!xmp
            });
            paso(f.name);
          }).catch(function () { paso(f.name); });
        });
      })
      .then(function () {
        return T.componer(fotos, videos, srts, mrks, otros);
      });
  };

  /* Encadena promesas de una en una: leer miles de archivos a la vez agota la
     memoria del navegador. */
  function serie(items, fn) {
    return items.reduce(function (p, item) {
      return p.then(function () { return fn(item); });
    }, Promise.resolve());
  }

  T.componer = function (fotos, videos, srts, mrks, otros) {
    var vuelos = [];
    var conXMP = fotos.filter(function (f) { return f.xmp && isFinite(f.lat); });
    var sinXMP = fotos.length - conXMP.length;

    agrupar(conXMP).forEach(function (g) {
      var P = locales(g.map(function (f) { return f.lat; }),
                      g.map(function (f) { return f.lon; }),
                      g.map(function (f) { return f.alt || 0; }));
      var pitches = g.map(function (f) { return f.pitch; }).filter(isFinite);
      var alturas = g.map(function (f) { return f.alt; }).filter(isFinite);
      var rtks = g.map(function (f) { return f.rtk; }).filter(isFinite);
      // el MRK de esta carpeta, si lo hay, manda sobre el GPS del XMP
      var mrk = null;
      Object.keys(mrks).forEach(function (k) {
        if (k.indexOf(g[0].carpeta) === 0) mrk = mrks[k];
      });
      if (mrk && mrk.disparos.length) {
        var d = mrk.disparos;
        P = locales(d.map(function (x) { return x.lat; }), d.map(function (x) { return x.lon; }),
                    d.map(function (x) { return x.alt; }));
        rtks = d.map(function (x) { return x.sigma[0]; }).filter(isFinite);
      }
      var v = {
        clase: 'fotos', carpeta: g[0].carpeta, n: g.length,
        modelo: g[0].modelo, gigas: g.reduce(function (s, f) { return s + f.bytes; }, 0) / 1073741824,
        desde: new Date(g[0].tiempo), hasta: new Date(g[g.length - 1].tiempo),
        recorrido: recorrido(P), angulo: anguloBarrido(P, mrk ? null : 0), acimut: acimut(P),
        pitches: pitches,
        alturaMin: alturas.length ? Math.min.apply(null, alturas) : null,
        alturaMax: alturas.length ? Math.max.apply(null, alturas) : null,
        pitchMin: pitches.length ? Math.min.apply(null, pitches) : null,
        pitchMax: pitches.length ? Math.max.apply(null, pitches) : null,
        rtk: rtks.length ? mediana(rtks) : null,
        mrk: mrk ? mrk.file.name : null,
        megapixel: g[0].ancho ? g[0].ancho * g[0].alto / 1e6 : null,
        focal35: g[0].focal35 || null
      };
      v.eval = T.evaluar(v);
      vuelos.push(v);
    });

    /* Los videos se evaluan por su .SRT: sin el no hay ni posicion ni escala.
       Y el .SRT no trae los angulos del gimbal, asi que un video nunca podra
       decir si ve fachadas; por eso las fotos son mejores. */
    videos.forEach(function (f) {
      var clave = carpetaDe(f) + '/' + baseDe(f.name);
      var srt = srts[clave];
      var v = { clase: 'video', carpeta: carpetaDe(f), nombre: f.name, n: 0,
                gigas: f.size / 1073741824, recorrido: 0, angulo: 0, acimut: [],
                pitches: [], rtk: null };
      if (srt && srt.frames.length) {
        var fr = srt.frames;
        var P = locales(fr.map(function (x) { return x.latitude; }),
                        fr.map(function (x) { return x.longitude; }),
                        fr.map(function (x) { return x.rel_alt || 0; }));
        v.n = fr.length;
        v.recorrido = recorrido(P);
        v.angulo = anguloBarrido(P, 0);      // rel_alt ya es altura sobre el despegue
        v.acimut = acimut(P);
        v.alturaMin = Math.min.apply(null, fr.map(function (x) { return x.rel_alt; }));
        v.alturaMax = Math.max.apply(null, fr.map(function (x) { return x.rel_alt; }));
        v.srt = srt.file.name;
        v.focal35 = fr[0].focal_len ? fr[0].focal_len / 10 : null;
      }
      v.eval = T.evaluar(v);
      if (!srt) {
        v.eval.avisos.unshift('sin archivo .SRT al lado: el video no lleva posicion ni escala');
        v.eval.nota = Math.min(v.eval.nota, 15);
        v.eval.veredicto = 'no sirve';
      } else {
        v.eval.avisos.push('el .SRT no trae angulos de gimbal: no se puede saber si ve fachadas');
      }
      vuelos.push(v);
    });

    /* Un .SRT o un .MRK sin su material al lado no se puede ignorar: describe
       un vuelo que existe, y a veces es lo unico que se tiene de el. El .MRK
       en concreto lleva la posicion RTK de cada disparo, que es mas de lo que
       dice cualquier foto suelta. */
    var usados = {};
    vuelos.forEach(function (v) {
      if (v.srt) usados[v.carpeta + '/' + baseDe(v.srt)] = 1;
      if (v.mrk) usados[v.carpeta + '/' + baseDe(v.mrk)] = 1;
    });
    Object.keys(srts).forEach(function (k) {
      if (usados[k]) return;
      var fr = srts[k].frames;
      var v = { clase: 'srt', carpeta: k.split('/').slice(0, -1).join('/') || '(raiz)',
                nombre: srts[k].file.name, n: fr.length, gigas: 0,
                recorrido: 0, angulo: 0, acimut: [], pitches: [], rtk: null };
      if (fr.length) {
        var P = locales(fr.map(function (x) { return x.latitude; }),
                        fr.map(function (x) { return x.longitude; }),
                        fr.map(function (x) { return x.rel_alt || 0; }));
        v.recorrido = recorrido(P); v.angulo = anguloBarrido(P, 0); v.acimut = acimut(P);
        v.alturaMin = Math.min.apply(null, fr.map(function (x) { return x.rel_alt; }));
        v.alturaMax = Math.max.apply(null, fr.map(function (x) { return x.rel_alt; }));
        v.focal35 = fr[0].focal_len ? fr[0].focal_len / 10 : null;
      }
      v.eval = T.evaluar(v);
      v.eval.avisos.unshift('telemetria sin su video al lado: el .SRT esta pero el archivo de imagen no');
      v.eval.notas.push('describe un vuelo de ' + fr.length + ' fotogramas aunque falte el video');
      vuelos.push(v);
    });
    Object.keys(mrks).forEach(function (k) {
      if (usados[k]) return;
      var d = mrks[k].disparos;
      var v = { clase: 'mrk', carpeta: k.split('/').slice(0, -1).join('/') || '(raiz)',
                nombre: mrks[k].file.name, n: d.length, gigas: 0,
                recorrido: 0, angulo: 0, acimut: [], pitches: [], rtk: null };
      if (d.length) {
        var Q = locales(d.map(function (x) { return x.lat; }), d.map(function (x) { return x.lon; }),
                        d.map(function (x) { return x.alt; }));
        // el .MRK da altura elipsoidal: el suelo no esta en cero
        v.recorrido = recorrido(Q); v.angulo = anguloBarrido(Q, null); v.acimut = acimut(Q);
        var sg = d.map(function (x) { return x.sigma[0]; }).filter(isFinite);
        v.rtk = sg.length ? mediana(sg) : null;
      }
      v.eval = T.evaluar(v);
      v.eval.avisos.unshift('posiciones RTK sin sus fotos al lado: el .MRK esta pero las imagenes no');
      v.eval.notas.push('describe un vuelo de ' + d.length + ' disparos con posicion RTK');
      vuelos.push(v);
    });

    vuelos.sort(function (a, b) { return b.eval.nota - a.eval.nota; });
    return { vuelos: vuelos, fotos: fotos.length, sinXMP: sinXMP,
             videos: videos.length, otros: otros };
  };

  function mediana(a) {
    var b = a.slice().sort(function (x, y) { return x - y; });
    var m = b.length >> 1;
    return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2;
  }
})(window.A3D);
