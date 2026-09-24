import { randomUUID } from 'node:crypto';
import { fail } from './security.js';
import { instrument } from './instruments.js';
import { cleanSpec } from './strategy-spec.js';
const strategies=new Set(['S00_MFKK','S09_MFKK_SCALPING','S10_OB_FVG_SCALP','S16_GOLDEN_SQUEEZE','S17_CONVERGENCE_SCALP','S18_RANGE_REVERSAL','S20_FIB_CONFLUENCE','S30_DOW_DIP','S31_LAYOUT_SMART']);
async function setup(db) {
  await db.execute(`CREATE TABLE IF NOT EXISTS backtest_jobs(request_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,strategy_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',result TEXT,lease_token TEXT,lease_until INTEGER DEFAULT 0,attempts INTEGER DEFAULT 0,created_at TEXT NOT NULL)`);
  // 2026-09-24: la stessa coda serve anche i download di storici MT5 (kind='history').
  for (const col of ["kind TEXT DEFAULT 'backtest'", 'params TEXT']) {
    try { await db.execute(`ALTER TABLE backtest_jobs ADD COLUMN ${col}`); } catch { /* colonna già presente */ }
  }
}
async function queueFull(db,userId) {
  const count=await db.execute({sql:"SELECT COUNT(*) AS n FROM backtest_jobs WHERE user_id=? AND status IN ('queued','running')",args:[userId]});
  if(Number(count.rows[0].n)>=5) throw fail(429,'Hai già cinque richieste in coda');
}
export const HISTORY_TFS = ['M1','M5','M15','M30','H1','H4','D1'];
// Storico MT5 on-demand per uno strumento del registro (eseguito da scripts/backtest_worker.py).
export async function enqueueHistory(db,b) {
  const inst=instrument(b.instrument);
  if(!inst) throw fail(400,'Strumento non nel registro');
  const tf=String(b.tf||'').toUpperCase();
  if(!HISTORY_TFS.includes(tf)) throw fail(400,'Timeframe non supportato');
  const days=Math.round(Number(b.days));
  if(!Number.isFinite(days)||days<7||days>3650) throw fail(400,'Periodo: da 7 a 3650 giorni');
  await setup(db); await queueFull(db,b.user_id);
  const request_id=randomUUID();
  await db.execute({sql:"INSERT INTO backtest_jobs(request_id,user_id,strategy_id,created_at,kind,params) VALUES (?,?,'HISTORY',?,'history',?)",
    args:[request_id,b.user_id,new Date().toISOString(),JSON.stringify({instrument:inst.id,tf,days})]});
  return {ok:true,request_id};
}
export async function enqueue(db,b) {
  if(!strategies.has(b.strategy_id)) throw fail(400,'Strategia non supportata');
  await setup(db); await queueFull(db,b.user_id);
  const request_id=randomUUID();
  await db.execute({sql:'INSERT INTO backtest_jobs(request_id,user_id,strategy_id,created_at) VALUES (?,?,?,?)',args:[request_id,b.user_id,b.strategy_id,new Date().toISOString()]});
  return {ok:true,request_id};
}
export async function claim(db) {
  await setup(db);
  const now=Math.floor(Date.now()/1000),lease=randomUUID();
  await db.execute({sql:"UPDATE backtest_jobs SET status='failed',result=? WHERE status='running' AND lease_until<? AND attempts>=3",args:[JSON.stringify({error:'Worker interrotto dopo tre tentativi'}),now]});
  const r=await db.execute({sql:`UPDATE backtest_jobs SET status='running',attempts=attempts+1,lease_until=?,lease_token=?
    WHERE request_id=(SELECT request_id FROM backtest_jobs WHERE status='queued' OR (status='running' AND lease_until<? AND attempts<3) ORDER BY created_at LIMIT 1)
    RETURNING request_id,strategy_id,created_at,lease_token,kind,params`,args:[now+1800,lease,now]});
  if(!r.rows.length) return {ok:true,command:null};
  const row=r.rows[0];
  return {ok:true,command:{request_id:row.request_id,strategy_id:row.strategy_id,created_at:row.created_at,lease_token:row.lease_token,
    requested_at:row.created_at,kind:row.kind||'backtest',params:row.params?JSON.parse(row.params):null}};
}
export async function complete(db,b) {
  await setup(db);
  if(!b.request_id||!b.lease_token) throw fail(400,'Identificativo richiesta e lease richiesti: aggiornare il worker');
  const result={...b.result,strategy_id:b.strategy_id,request_id:b.request_id,synced_at:new Date().toISOString()};
  const r=await db.execute({sql:"UPDATE backtest_jobs SET status=?,result=? WHERE request_id=? AND strategy_id=? AND lease_token=? AND status='running' RETURNING request_id",args:[result.error?'failed':'done',JSON.stringify(result),b.request_id,b.strategy_id,b.lease_token]});
  if(!r.rows.length) throw fail(409,'Richiesta già completata o lease scaduta');
  return {ok:true};
}
export async function result(db,b) {
  await setup(db);
  const r=await db.execute({sql:'SELECT status,result,attempts FROM backtest_jobs WHERE request_id=? AND user_id=?',args:[b.request_id||'',b.user_id]});
  if(!r.rows.length) return {ok:true,data:null};
  return {ok:true,status:r.rows[0].status,attempts:Number(r.rows[0].attempts||0),data:r.rows[0].result?JSON.parse(r.rows[0].result):null};
}

// Stato del worker (heartbeat ~60s) + indice degli storici scaricati, pubblicati dal worker.
export async function workerStatusPush(db,b) {
  const payload=JSON.stringify({seen_at:new Date().toISOString(),host:String(b.host||'').slice(0,60),
    history:b.history&&typeof b.history==='object'?b.history:{datasets:{}}});
  await db.execute({sql:`INSERT INTO user_data (id,user_id,doc_type,payload,updated_at) VALUES ('system:worker_status','system','worker_status',?,CURRENT_TIMESTAMP)
    ON CONFLICT(user_id,doc_type) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP`,args:[payload]});
  return {ok:true};
}
export async function workerStatusGet(db) {
  const r=await db.execute({sql:"SELECT payload FROM user_data WHERE user_id='system' AND doc_type='worker_status'",args:[]});
  return {ok:true,data:r.rows.length?JSON.parse(r.rows[0].payload):null};
}

// Schede strumento (scripts/instrument_profile.py sul worker): aggiornamento su richiesta,
// pubblicazione (service) e lettura (utente autenticato). ~25 KB per 15 strumenti.
export async function enqueueProfile(db,b) {
  await setup(db); await queueFull(db,b.user_id);
  const pending=await db.execute({sql:"SELECT request_id FROM backtest_jobs WHERE kind='profile' AND status IN ('queued','running') LIMIT 1",args:[]});
  if(pending.rows.length) return {ok:true,request_id:pending.rows[0].request_id,already:true};
  const request_id=randomUUID();
  await db.execute({sql:"INSERT INTO backtest_jobs(request_id,user_id,strategy_id,created_at,kind,params) VALUES (?,?,'PROFILE',?,'profile','{}')",
    args:[request_id,b.user_id,new Date().toISOString()]});
  return {ok:true,request_id};
}
export async function profilesPush(db,b) {
  if(!b.profiles||typeof b.profiles!=='object'||!b.profiles.instruments) throw fail(400,'Schede mancanti');
  const payload=JSON.stringify(b.profiles);
  if(payload.length>400000) throw fail(413,'Schede troppo grandi');
  await db.execute({sql:`INSERT INTO user_data (id,user_id,doc_type,payload,updated_at) VALUES ('system:instrument_profiles','system','instrument_profiles',?,CURRENT_TIMESTAMP)
    ON CONFLICT(user_id,doc_type) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP`,args:[payload]});
  return {ok:true};
}
export async function profilesGet(db) {
  const r=await db.execute({sql:"SELECT payload FROM user_data WHERE user_id='system' AND doc_type='instrument_profiles'",args:[]});
  return {ok:true,data:r.rows.length?JSON.parse(r.rows[0].payload):null};
}

// Composer: validazione di una specifica sul worker (dati MT5, costi reali, criteri di promozione).
export async function enqueueSpec(db,b) {
  const spec=cleanSpec(b.spec);
  await setup(db); await queueFull(db,b.user_id);
  const request_id=randomUUID();
  await db.execute({sql:"INSERT INTO backtest_jobs(request_id,user_id,strategy_id,created_at,kind,params) VALUES (?,?,'SPEC',?,'spec',?)",
    args:[request_id,b.user_id,new Date().toISOString(),JSON.stringify(spec)]});
  return {ok:true,request_id,spec};
}
export async function specRuns(db,b) {
  await setup(db);
  const r=await db.execute({sql:"SELECT request_id,status,params,result,created_at FROM backtest_jobs WHERE user_id=? AND kind='spec' ORDER BY created_at DESC LIMIT 20",args:[b.user_id]});
  return {ok:true,runs:r.rows.map(x=>{const spec=x.params?JSON.parse(x.params):null,res=x.result?JSON.parse(x.result):null;
    return {request_id:x.request_id,status:x.status,created_at:x.created_at,spec,
      summary:res&&!res.error?{verdict:res.verdict,n:res.full?.n,pf:res.full?.pf,holdout_pf:res.holdout?.pf,net_r:res.net_r}:res?.error?{error:res.error}:null};})};
}
