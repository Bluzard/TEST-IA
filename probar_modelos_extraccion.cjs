// Compara modelos de Ollama como extractores de escena con el MISMO prompt/esquema/reducer de b_chat, en los turnos de evaluación (últimos 15 %).
// uso: node probar_modelos_extraccion.cjs MODELO [N]    (salida: resultados/ETAPA6_modelo_<modelo>.json)
const fs = require('fs');
const path = require('path');
const DG = 'D:/Documentos/bchat_datagen';
const st = require(`${DG}/lib/scene-transition.cjs`);
const sit = require(`${DG}/lib/situation-state.cjs`);

const modelo = process.argv[2];
const N = Number(process.argv[3]) || 58;
const pares = fs.readFileSync(`${DG}/storage/debug/extraction-pairs.jsonl`, 'utf8').split('\n').filter(Boolean).map(JSON.parse).sort((a, b) => a.at.localeCompare(b.at));
const ev = pares.slice(Math.floor(pares.length * 0.85)).slice(0, N);

const tupla = (c) => [c.actor, c.act, c.part || '', c.target, c.targetPart || ''].join('|');
const lim = (t) => String(t || '').replace(/\s+/g, ' ').trim().toLowerCase();
const toks = (t) => lim(t).match(/\w+/g) || [];
function f1(a, b) {
  a = toks(a); b = toks(b);
  if (!a.length && !b.length) return 1;
  if (!a.length || !b.length) return 0;
  const c = {}; a.forEach((w) => { c[w] = (c[w] || 0) + 1; });
  let n = 0; b.forEach((w) => { if (c[w] > 0) { c[w] -= 1; n += 1; } });
  if (!n) return 0;
  const p = n / b.length, r = n / a.length; return 2 * p * r / (p + r);
}
const acum = {};
const anota = (k, v) => { (acum[k] = acum[k] || []).push(Number(v)); };

(async () => {
  let aceptadas = 0, tiempos = [], fallos = 0;
  for (const par of ev) {
    const req = JSON.parse(par.request);
    const state = sit.freshState(par.previousScene);
    const t0 = Date.now();
    let raw = null;
    try {
      const r = await fetch('http://127.0.0.1:11434/api/chat', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: modelo, messages: [{ role: 'system', content: st.INSTRUCTION }, { role: 'user', content: par.request }],
          format: st.extractionSchema(state), stream: false, think: false, keep_alive: '10m', options: { num_ctx: 16384, num_predict: 2200, temperature: 0, top_p: 0.8 } }) });
      const body = await r.json();
      raw = JSON.parse(body.message?.content || '');
    } catch { fallos += 1; }
    tiempos.push((Date.now() - t0) / 1000);
    let pred = null;
    if (raw) {
      const res = st.applyTransition(par.previousScene, raw, { sexes: par.sexes, names: par.names, messages: { user: par.userContent, assistant: par.assistantContent }, lenient: true });
      if (!res.issues.length && res.scene) { aceptadas += 1; pred = res.scene.situationState; }
    }
    const oro = par.scene.situationState;
    for (const q of ['char', 'user']) {
      const p = pred?.[q] || {}, o = oro[q];
      anota(`${q}.posture`, p.posture === o.posture);
      anota(`${q}.support`, lim(p.support) === lim(o.support));
      anota(`${q}.restraint`, Boolean(lim(p.restraint)) === Boolean(lim(o.restraint)));
      anota(`${q}.asleep`, Boolean(p.asleep) === Boolean(o.asleep));
      anota(`${q}.expression_F1`, f1(o.expression, p.expression));
      anota(`${q}.action_F1`, f1(o.action, p.action));
    }
    anota('arrangement', pred?.arrangement === oro.arrangement);
    const a = new Set((oro.contacts || []).map(tupla)), b = new Set((pred?.contacts || []).map(tupla));
    anota('contactos_exacto', a.size === b.size && [...a].every((x) => b.has(x)));
    const inter = [...a].filter((x) => b.has(x)).length;
    anota('contactos_F1', !a.size && !b.size ? 1 : 2 * inter / (a.size + b.size));
  }
  const resumen = {};
  for (const [k, v] of Object.entries(acum)) if (!k.startsWith('escena.')) resumen[k] = Math.round(100 * v.reduce((x, y) => x + y, 0) / v.length) / 100;
  const salida = { modelo, turnos: ev.length, aceptadas_por_reducer: aceptadas, fallos_json: fallos, seg_por_turno_media: Math.round(10 * tiempos.reduce((x, y) => x + y, 0) / tiempos.length) / 10, campos: resumen };
  fs.writeFileSync(path.join(__dirname, 'resultados', `ETAPA6_modelo_${modelo.replace(/[^\w.-]/g, '_')}.json`), JSON.stringify(salida, null, 1));
  console.log(JSON.stringify(salida, null, 1));
})();
