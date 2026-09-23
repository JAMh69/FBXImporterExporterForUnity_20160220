const { chromium } = require('playwright');
const APP='file:///home/user/FBXImporterExporterForUnity_20160220/AUTO3D_claude/index.html';
const DIR='/tmp/claude-0/-home-user-FBXImporterExporterForUnity-20160220/27a3a8a3-ff1c-5af1-9fd8-56ea561c45e9/scratchpad/vuelos';
(async()=>{
 const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium-1194/chrome-linux/chrome'});
 const page=await b.newPage({viewport:{width:1500,height:950}});
 const errs=[]; page.on('pageerror',e=>errs.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errs.push('C:'+m.text());});
 await page.goto(APP);
 await page.waitForFunction(()=>window.A3D&&window.A3D.triage);
 await page.setInputFiles('#dirInput', DIR);
 await page.waitForFunction(()=>window.A3D.state.triage,null,{timeout:60000});
 const inf=await page.evaluate(()=>{
   const t=window.A3D.state.triage;
   return {fotos:t.fotos,sinXMP:t.sinXMP,videos:t.videos,otros:t.otros,
     vuelos:t.vuelos.map(v=>({clase:v.clase,carpeta:v.carpeta,nombre:v.nombre,n:v.n,
       modelo:v.modelo,mpx:v.megapixel?+v.megapixel.toFixed(1):null,
       pitch:v.pitchMin!=null?[Math.round(v.pitchMin),Math.round(v.pitchMax)]:null,
       recorrido:Math.round(v.recorrido),angulo:Math.round(v.angulo),
       acimut:Math.round(v.eval.acimutLleno*100),rtk:v.rtk!=null?+(v.rtk*100).toFixed(1):null,
       mrk:v.mrk,srt:v.srt,nota:v.eval.nota,veredicto:v.eval.veredicto,tipo:v.eval.tipo,
       avisos:v.eval.avisos}))};
 });
 console.log(JSON.stringify(inf,null,1));
 await page.screenshot({path:'shot_triage.png'});
 console.log('errores JS:', errs.length?errs:'ninguno');
 await b.close();
})();
