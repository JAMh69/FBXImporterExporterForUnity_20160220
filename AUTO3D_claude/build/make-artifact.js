/* Genera build/artifact.html a partir de index.html y css/style.css.
   La version publicada en la web no lleva doctype/head/body propios: el
   servicio de artifacts envuelve el archivo. El CSS va incrustado y los
   scripts se publican como archivos acompanantes. */
const fs = require('fs'), path = require('path');
const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'css/style.css'), 'utf8');
const body = html.split('<body>')[1].split('</body>')[0];
const out = `<title>AUTO3D</title>
<style>
${css}
/* la pagina publicada vive dentro de un marco: sin margenes y a toda altura */
html,body{height:100%;margin:0;background:#12151a}
</style>
${body.trim()}
`;
fs.writeFileSync(path.join(root, 'build/artifact.html'), out);
console.log('build/artifact.html', (out.length / 1024).toFixed(1), 'KB');
