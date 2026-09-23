const { chromium } = require('playwright'); const fs=require('fs');
const APP='file:///home/user/FBXImporterExporterForUnity_20160220/AUTO3D_claude/index.html';
const esperado=JSON.parse(fs.readFileSync('/tmp/esperado.json','utf8'));
(async()=>{
 const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
 const page=await b.newPage(); const errs=[];
 page.on('pageerror',e=>errs.push(e.message));
 await page.goto(APP); await page.waitForFunction(()=>window.A3D&&window.A3D.mv);
 const r=await page.evaluate(esp=>{
   const M=window.A3D.mv;
   const cams=esp.camaras.map(c=>new M.Camara(c.f,c.pp,c.R,c.t,c.nombre,c.tam));
   const out={proy:[],tri:[],triRuido:[],err:[],angulos:null,epi:null,prec:null};
   esp.casos.forEach(caso=>{
     // proyeccion
     let dmax=0;
     cams.forEach((c,i)=>{
       const p=c.proyectar(caso.verdad).px;
       dmax=Math.max(dmax,Math.hypot(p[0]-caso.marcas[i][0],p[1]-caso.marcas[i][1]));
     });
     out.proy.push(dmax);
     // triangulacion exacta y con ruido
     const X=M.triangular(cams,caso.marcas);
     out.tri.push(M.norma(M.resta(X,caso.X)));
     const Xr=M.triangular(cams,caso.marcasRuido);
     out.triRuido.push(M.norma(M.resta(Xr,caso.Xruido)));
     const e=M.errorReproyeccion(cams,caso.marcas,X);
     out.err.push(Math.max(...e.map((v,i)=>Math.abs(v-caso.errores[i]))));
   });
   // angulos entre vistas
   const X0=esp.casos[0].verdad;
   out.angulos=M.mejoresParejas(cams,0,X0).map(p=>({i:p.i,ang:p.angulo}));
   // epipolar: el punto verdadero debe caer sobre la recta
   const pxA=esp.casos[0].marcas[0];
   const linea=M.epipolar(cams[0],pxA,cams[2],5,200);
   const pB=cams[2].proyectar(X0).px;
   let dmin=1e9;
   for(let i=0;i<linea.length-1;i++){
     const a=linea[i].px,b2=linea[i+1].px;
     const vx=b2[0]-a[0],vy=b2[1]-a[1],L=vx*vx+vy*vy;
     const t=L?Math.max(0,Math.min(1,((pB[0]-a[0])*vx+(pB[1]-a[1])*vy)/L)):0;
     dmin=Math.min(dmin,Math.hypot(a[0]+t*vx-pB[0],a[1]+t*vy-pB[1]));
   }
   out.epi=dmin;
   out.prec=M.precisionEsperada(cams,X0,2);
   return out;
 },esperado);
 const f=n=>n.toExponential(2);
 console.log('proyeccion, error max frente a Python:', f(Math.max(...r.proy)),'px');
 console.log('triangulacion exacta, dif max:      ', f(Math.max(...r.tri)),'m');
 console.log('triangulacion con ruido, dif max:   ', f(Math.max(...r.triRuido)),'m');
 console.log('error de reproyeccion, dif max:     ', f(Math.max(...r.err)),'px');
 console.log('angulos entre vistas (JS):', r.angulos.map(a=>a.ang.toFixed(1)).join(' '));
 console.log('angulos entre vistas (PY):', esperado.angulosDesde0.slice(1).map(a=>a.toFixed(1)).join(' '));
 console.log('punto verdadero a la recta epipolar:', r.epi.toFixed(4),'px');
 console.log('precision esperada con 2 px de marcado:', r.prec.toFixed(3),'m');
 console.log('errores JS:', errs.length?errs:'ninguno');
 await b.close();
})();
