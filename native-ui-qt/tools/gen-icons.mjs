// Genera native-ui-qt/icons/*.svg dalle stesse icone lucide che usa il kiosk
// Electron (node_modules/lucide-react, oggi 0.294.0), così le due interfacce
// disegnano esattamente la stessa icona invece di due ricalchi diversi.
//
// Per ogni icona escono due file: `nome.svg` (contorno, come lucide) e
// `nome-fill.svg` (riempita, per play/pausa che in Electron sono `fill`).
// Lo stroke è bianco: la tinta la mette Icon.qml con MultiEffect.
//
//   node tools/gen-icons.mjs [--all]
//
// Senza --all tiene solo le icone citate dai file .qml (sono ~1300 in tutto,
// 11 MB: nel repo ci stanno solo quelle che servono davvero).
import fs from 'node:fs';
import path from 'node:path';

const src = 'node_modules/lucide-react/dist/esm/icons';
const out = path.join(path.dirname(new URL(import.meta.url).pathname), '..', 'icons');
const all = process.argv.includes('--all');

const qmlDir = path.join(out, '..', 'qml');
const used = new Set();
if (!all) {
  for (const f of fs.readdirSync(qmlDir).filter((f) => f.endsWith('.qml'))) {
    const text = fs.readFileSync(path.join(qmlDir, f), 'utf8');
    for (const m of text.matchAll(/"([a-z0-9][a-z0-9-]*)"/g)) used.add(m[1]);
  }
}

fs.mkdirSync(out, { recursive: true });
let n = 0;
for (const f of fs.readdirSync(src)) {
  if (!f.endsWith('.js')) continue;
  const name = f.replace(/\.js$/, '');
  if (!all && !used.has(name)) continue;
  const js = fs.readFileSync(path.join(src, f), 'utf8');
  const m = js.match(/createLucideIcon\("[^"]+",\s*(\[[\s\S]*?\])\s*\);/);
  if (!m) continue;
  let nodes;
  try { nodes = eval(m[1]); } catch { continue; }
  const body = nodes.map(([tag, attrs]) => {
    const a = Object.entries(attrs).filter(([k]) => k !== 'key').map(([k, v]) => `${k}="${v}"`).join(' ');
    return `<${tag} ${a}/>`;
  }).join('');
  const head = (fill) => `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="${fill}" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">`;
  fs.writeFileSync(path.join(out, `${name}.svg`), head('none') + body + '</svg>');
  fs.writeFileSync(path.join(out, `${name}-fill.svg`), head('#ffffff') + body + '</svg>');
  n++;
}
console.log(`icone scritte: ${n}${all ? ' (tutte)' : ' (solo quelle usate dal QML)'}`);
