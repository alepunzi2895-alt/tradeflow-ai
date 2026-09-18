import { randomUUID } from 'node:crypto';
import { fail } from './security.js';
const strategies=new Set(['S00_MFKK','S09_MFKK_SCALPING','S10_OB_FVG_SCALP','S16_GOLDEN_SQUEEZE','S17_CONVERGENCE_SCALP','S18_RANGE_REVERSAL','S20_FIB_CONFLUENCE','S30_DOW_DIP','S31_LAYOUT_SMART']);
async function setup(db) {
  await db.execute(`CREATE TABLE IF NOT EXISTS backtest_jobs(request_id TEXT PRIMARY KEY,user_id TEXT NOT NULL,strategy_id TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',result TEXT,lease_token TEXT,lease_until INTEGER DEFAULT 0,attempts INTEGER DEFAULT 0,created_at TEXT NOT NULL)`);
}
export async function enqueue(db,b) {
  if(!strategies.has(b.strategy_id)) throw fail(400,'Strategia non supportata');
  await setup(db);
  const count=await db.execute({sql:"SELECT COUNT(*) AS n FROM backtest_jobs WHERE user_id=? AND status IN ('queued','running')",args:[b.user_id]});
  if(Number(count.rows[0].n)>=5) throw fail(429,'Hai già cinque backtest in coda');
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
    RETURNING request_id,strategy_id,created_at,lease_token`,args:[now+1800,lease,now]});
  return {ok:true,command:r.rows.length?{...r.rows[0],requested_at:r.rows[0].created_at}:null};
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
  const r=await db.execute({sql:'SELECT status,result FROM backtest_jobs WHERE request_id=? AND user_id=?',args:[b.request_id||'',b.user_id]});
  if(!r.rows.length) return {ok:true,data:null};
  return {ok:true,status:r.rows[0].status,data:r.rows[0].result?JSON.parse(r.rows[0].result):null};
}
