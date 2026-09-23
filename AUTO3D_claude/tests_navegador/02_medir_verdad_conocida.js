const { chromium } = require('playwright'); const fs=require('fs');
const APP='file:///home/user/FBXImporterExporterForUnity_20160220/AUTO3D_claude/index.html';
const DIR='/tmp/claude-0/-home-user-FBXImporterExporterForUnity-20160220/27a3a8a3-ff1c-5af1-9fd8-56ea561c45e9/scratchpad/sint';
const verdad=JSON.parse(fs.readFileSync(DIR+'/vuelo_zuera_test/verdad.json','utf8'));
(async()=>{
 const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
 const page=await b.newPage({viewport:{width:1600,height:1000}});
 const errs=[]; page.on('pageerror',e=>errs.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errs.push('C:'+m.text());});
 await page.goto(APP); await page.waitForFunction(()=>window.A3D&&window.A3D.medir);
 await page.setInputFiles('#dirInput', DIR);
 await page.waitForFunction(()=>window.A3D.state.triage,null,{timeout:60000});

 const resumen=await page.evaluate(()=>{
   const t=window.A3D.state.triage;
   return t.vuelos.map(v=>({carpeta:v.carpeta,n:v.n,medible:!!v.medible,
     nota:v.eval.nota,veredicto:v.eval.veredicto,
     camaras:(v.camaras||[]).filter(Boolean).length}));
 });
 console.log('EXPLORACION:', JSON.stringify(resumen));

 // abrir el modo medir y comprobar que las camaras reconstruidas coinciden
 const chequeo=await page.evaluate(vd=>{
   const A=window.A3D, t=A.state.triage;
   const v=t.vuelos.find(x=>x.medible);
   if(!v) return {error:'ningun vuelo medible'};
   const out={pos:[],ang:[],proy:[]};
   v.fotos.forEach((f,i)=>{
     const truth=vd.fotos.find(x=>x.nombre===f.nombre);
     const cam=v.camaras[i], c=cam.centro();
     // posicion local respecto a la primera camara
     out.pos.push(Math.hypot(c[0]-(truth.pos[0]-vd.fotos[0].pos[0]),
                             c[1]-(truth.pos[1]-vd.fotos[0].pos[1]),
                             c[2]-truth.pos[2]));
     // reproyeccion de las esquinas conocidas
     Object.keys(vd.referencias).forEach(k=>{
       const X=vd.referencias[k];
       // el mundo de la app tiene origen en la primera camara
       const Xl=[X[0]-vd.fotos[0].pos[0],X[1]-vd.fotos[0].pos[1],X[2]];
       const p=cam.proyectar(Xl);
       if(p.delante) out.proy.push(Math.hypot(p.px[0]-truth.marcas[k][0],p.px[1]-truth.marcas[k][1]));
     });
   });
   A.medir.abrir(v);
   return out;
 },verdad);
 console.log('camara: error max de posicion', Math.max(...chequeo.pos).toExponential(2),'m');
 console.log('reproyeccion de esquinas conocidas: error max', Math.max(...chequeo.proy).toFixed(3),'px');

 await page.waitForTimeout(1200);   // que carguen las imagenes

 // simular el marcado: dos esquinas separadas 20 m, en dos vistas
 const medida=await page.evaluate(vd=>{
   const A=window.A3D, M=A.mv, t=A.state.triage;
   const v=t.vuelos.find(x=>x.medible);
   const base=vd.fotos[0].pos;
   const res={};
   function marcar(nombrePunto, iA, iB){
     const pxA=vd.fotos[iA].marcas[nombrePunto], pxB=vd.fotos[iB].marcas[nombrePunto];
     const cams=[v.camaras[iA],v.camaras[iB]];
     const X=M.triangular(cams,[pxA,pxB]);
     return {X, err:Math.max(...M.errorReproyeccion(cams,[pxA,pxB],X))};
   }
   const a=marcar('base_A',0,2), b2=marcar('base_B',0,2);
   res.lado20 = M.norma(M.resta(b2.X,a.X));
   const al=marcar('alero_A',0,2);
   res.altura8 = M.norma(M.resta(al.X,a.X));
   const cu=marcar('cumbrera_izq',1,3);
   res.cumbrera11 = cu.X[2] - a.X[2];
   res.errorMax = Math.max(a.err,b2.err,al.err,cu.err);
   res.precision = M.precisionEsperada([v.camaras[0],v.camaras[2]],a.X,2);
   return res;
 },verdad);
 console.log('\nMEDIDAS (verdad: lado 20 m, alero 8 m, cumbrera 11 m):');
 console.log('  lado A-B:      ', medida.lado20.toFixed(4),'m   error', ((medida.lado20-20)*1000).toFixed(1),'mm');
 console.log('  altura alero:  ', medida.altura8.toFixed(4),'m   error', ((medida.altura8-8)*1000).toFixed(1),'mm');
 console.log('  altura cumbrera', medida.cumbrera11.toFixed(4),'m   error', ((medida.cumbrera11-11)*1000).toFixed(1),'mm');
 console.log('  error de reproyeccion max:', medida.errorMax.toFixed(4),'px');
 console.log('  precision anunciada con 2 px:', (medida.precision*100).toFixed(1),'cm');
 await page.screenshot({path:'shot_medir.png'});
 console.log('errores JS:', errs.length?errs:'ninguno');
 await b.close();
})();
