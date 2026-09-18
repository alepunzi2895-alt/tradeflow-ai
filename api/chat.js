import { requireUser, rateLimit, parseBody, fail } from '../lib/security.js';
import { getDb } from './db.js';
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
