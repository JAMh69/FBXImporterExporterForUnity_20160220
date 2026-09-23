const { chromium } = require('playwright'); const fs=require('fs');
const APP='file:///home/user/FBXImporterExporterForUnity_20160220/AUTO3D_claude/index.html';
const DIR='/tmp/claude-0/-home-user-FBXImporterExporterForUnity-20160220/27a3a8a3-ff1c-5af1-9fd8-56ea561c45e9/scratchpad/sint';
const verdad=JSON.parse(fs.readFileSync(DIR+'/vuelo_zuera_test/verdad.json','utf8'));
(async()=>{
 const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
 const page=await b.newPage({viewport:{width:1600,height:1000}});
 const errs=[]; page.on('pageerror',e=>errs.push(e.message));
 await page.goto(APP); await page.waitForFunction(()=>window.A3D&&window.A3D.medir);
 await page.setInputFiles('#dirInput', DIR);
 await page.waitForFunction(()=>window.A3D.state.triage,null,{timeout:60000});
 // abrir medir con el boton del informe, como haria el usuario
 await page.click('[data-medir]');
 await page.waitForTimeout(1500);

 async function pantalla(sel, px){
   return await page.evaluate(({sel,px})=>{
     const cv=document.querySelector(sel), r=cv.getBoundingClientRect();
     const img=window.__img(sel);
     const esc=Math.min(cv.width/img.w, cv.height/img.h);
     const ox=(cv.width-img.w*esc)/2, oy=(cv.height-img.h*esc)/2;
     return {x:r.left+ox+px[0]*esc, y:r.top+oy+px[1]*esc};
   },{sel,px});
 }
 // helper para conocer el tamano de la imagen de cada panel
 await page.evaluate(()=>{ window.__img=function(sel){ return {w:1600,h:1200}; }; });

 const indiceA=await page.evaluate(()=>parseInt(document.getElementById('mdSelA').value,10));
 const pxA=verdad.fotos[indiceA].marcas['base_A'];
 const sA=await pantalla('#mdCvA',pxA);
 await page.mouse.click(sA.x,sA.y);
 await page.waitForTimeout(900);

 const tras=await page.evaluate(()=>({
   B:parseInt(document.getElementById('mdSelB').value,10),
   estado:document.getElementById('mdEstado').textContent
 }));
 console.log('tras marcar en A -> vista B =', tras.B);
 console.log('estado:', tras.estado);

 // mover el raton sobre B para que dibuje la guia, y comprobar que hay linea
 const pxB=verdad.fotos[tras.B].marcas['base_A'];
 const sB=await pantalla('#mdCvB',pxB);
 await page.mouse.move(sB.x,sB.y);
 await page.waitForTimeout(300);
 await page.screenshot({path:'shot_epipolar.png'});
 await page.mouse.click(sB.x,sB.y);
 await page.waitForTimeout(600);

 // segundo punto: la otra esquina, para medir los 20 m
 const pxA2=verdad.fotos[indiceA].marcas['base_B'];
 const sA2=await pantalla('#mdCvA',pxA2);
 await page.mouse.click(sA2.x,sA2.y);
 await page.waitForTimeout(800);
 const B2=await page.evaluate(()=>parseInt(document.getElementById('mdSelB').value,10));
 const sB2=await pantalla('#mdCvB',verdad.fotos[B2].marcas['base_B']);
 await page.mouse.click(sB2.x,sB2.y);
 await page.waitForTimeout(600);

 const fin=await page.evaluate(()=>({
   distancia:document.getElementById('mdDistancia').textContent,
   puntos:window.A3D.medir.puntos().map(p=>({n:p.nombre,X:p.X.map(v=>+v.toFixed(3)),
     err:+p.error.toFixed(2),prec:+(p.precision*100).toFixed(1),ang:+p.angulo.toFixed(0)})),
   csv:window.A3D.medir.csv().split('\n').slice(0,4)
 }));
 console.log('\npuntos medidos por clic:');
 fin.puntos.forEach(p=>console.log('  ',p.n,'E',p.X[0],'N',p.X[1],'alt',p.X[2],
   ' error',p.err,'px  +-',p.prec,'cm  angulo',p.ang));
 console.log('distancia mostrada:', fin.distancia.replace(/\s+/g,' ').trim());
 console.log('verdad: 20 m exactos');
 await page.screenshot({path:'shot_medido.png'});
 console.log('errores JS:', errs.length?errs:'ninguno');
 await b.close();
})();
