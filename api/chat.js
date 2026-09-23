import { requireUser, rateLimit, parseBody, fail } from '../lib/security.js';
import { getDb } from './db.js';
// Hobby plan: Vercel impone comunque un tetto di 10s a prescindere da questo valore (nessun
// danno, no-op silenzioso). Pro+: alza davvero il tetto — un'analisi con screenshot o un
// system prompt lungo (mercato live + confidence score + knowledge base) può richiedere più
// di 8s a Claude per generare fino a max_tokens; prima il fetchT interno abortiva a 8s ben
// prima che servisse, producendo "The operation was aborted due to timeout" lato utente anche
// quando Vercel stesso avrebbe lasciato girare la function più a lungo (audit 2026-09-23).
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
async function fetchT(url, options) { return fetch(url,{...options,signal:AbortSignal.timeout(55000)}); }
