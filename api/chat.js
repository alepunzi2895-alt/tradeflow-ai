import { requireUser, rateLimit, parseBody, fail } from '../lib/security.js';
import { getDb } from './db.js';
// 2026-09-23: alzato fetchT a 55s ipotizzando un piano Vercel Pro+ (maxDuration reale) — sbagliato,
// vedi directives/08_dev_rules.md ("Execution time: 10s max per function", regola scritta prima di
// questo audit, mai verificata contro il codice). Su Hobby il cap reale resta 10s A PRESCINDERE da
// maxDuration: senza un self-abort sotto quella soglia, Vercel uccide la function a metà (504/nessun
// body) invece del nostro catch pulito — ha rotto l'Analisi (system prompt lungo + eventuale
// screenshot, il caso più lento) invece di ripararla. Reverted a 8s (pattern standard del progetto,
// vedi fetchT in directives/08_dev_rules.md). config.maxDuration lasciato: no-op innocuo su Hobby,
// utile se il piano viene confermato Pro+ in futuro — ma il fix vero deve restare sotto la fetchT.
export const config = { maxDuration: 60 };
export default async function handler(req,res) {
  if(req.method!=='POST') return res.status(405).json({error:'Metodo non consentito'});
  try {
    const body=parseBody(req), user=requireUser(req);
    await rateLimit(getDb(),'ai:'+user.id,30,3600);
    if(!Array.isArray(body.messages)||body.messages.length>50||body.messages.some(m=>!['user','assistant'].includes(m.role))) throw fail(400,'Messaggi non validi');
    if(!process.env.ANTHROPIC_API_KEY) throw fail(503,'Servizio AI non configurato');
    const response=await fetchT('https://api.anthropic.com/v1/messages',{
      method:'POST',headers:{'Content-Type':'application/json','x-api-key':process.env.ANTHROPIC_API_KEY,'anthropic-version':'2023-06-01'},
      body:JSON.stringify({model:process.env.ANTHROPIC_MODEL||'claude-sonnet-5',max_tokens:Math.min(3000,Math.max(1,Number(body.max_tokens)||2000)),system:body.system||'',messages:body.messages})
    });
    return res.status(response.status).json(await response.json());
  } catch(e) { return res.status(e.status||502).json({error:e.message}); }
}
async function fetchT(url, options) { return fetch(url,{...options,signal:AbortSignal.timeout(8000)}); }
