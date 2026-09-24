// Strategie del Laboratorio promosse sul bot (2026-09-24). Registro in user_data system/lab_strategies.
// Regole di sicurezza lato server (non aggirabili dal browser):
//  - si promuove SOLO una validazione del composer salvata sul server (backtest_jobs kind='spec',
//    status done, dell'utente) con esito PROMUOVIBILE o CANDIDATA DEMO: la specifica e i numeri
//    attesi vengono dal DB, non dalla richiesta
//  - lotto fisso 0,01–0,05; con chiusura parziale serve almeno 0,02 (con 0,01 non si divide)
//  - al massimo 3 strategie attive; il bot le esegue solo su conto DEMO (scripts/lab_live.py)
import { fail } from './security.js';

const MAX_ACTIVE = 3;
const KILL = { min_trades: 20, pf_min: 0.8, wr_drop_pp: 15, max_consec_losses: 8 };

async function load(db) {
  const r = await db.execute({ sql: "SELECT payload FROM user_data WHERE user_id='system' AND doc_type='lab_strategies'", args: [] });
  return r.rows.length ? JSON.parse(r.rows[0].payload) : { items: [] };
}
async function save(db, doc) {
  await db.execute({ sql: `INSERT INTO user_data (id,user_id,doc_type,payload,updated_at) VALUES ('system:lab_strategies','system','lab_strategies',?,CURRENT_TIMESTAMP)
    ON CONFLICT(user_id,doc_type) DO UPDATE SET payload=excluded.payload,updated_at=CURRENT_TIMESTAMP`, args: [JSON.stringify(doc)] });
}
const activeCount = doc => doc.items.filter(x => x.status === 'active').length;

export async function promote(db, b) {
  const lot = Math.round(Number(b.lot) * 100) / 100;
  if (!Number.isFinite(lot) || lot < 0.01 || lot > 0.05) throw fail(400, 'Lotto: da 0,01 a 0,05');
  const r = await db.execute({ sql: "SELECT status,params,result FROM backtest_jobs WHERE request_id=? AND user_id=? AND kind='spec'", args: [String(b.request_id || ''), b.user_id] });
  if (!r.rows.length) throw fail(404, 'Validazione non trovata');
  const row = r.rows[0], res = row.result ? JSON.parse(row.result) : null, spec = row.params ? JSON.parse(row.params) : null;
  if (row.status !== 'done' || !res || res.error || !spec) throw fail(409, 'Validazione non completata');
  if (!['PROMUOVIBILE', 'CANDIDATA DEMO'].includes(res.verdict)) throw fail(409, `Esito ${res.verdict}: solo le strategie che superano i criteri pratici possono andare sul bot`);
  if (spec.exit?.partial && lot < 0.02) throw fail(400, 'Con la chiusura parziale serve un lotto di almeno 0,02');
  const doc = await load(db);
  if (doc.items.some(x => x.request_id === b.request_id && x.status !== 'retired')) throw fail(409, 'Questa validazione è già sul bot');
  if (activeCount(doc) >= MAX_ACTIVE) throw fail(409, `Al massimo ${MAX_ACTIVE} strategie del laboratorio attive: mettine una in pausa o ritirala`);
  const id = 'LAB_' + String(b.request_id).replace(/[^a-f0-9]/gi, '').slice(0, 6).toUpperCase();
  const item = {
    id, request_id: b.request_id, name: spec.name, spec, lot, status: 'active', created_at: new Date().toISOString(), created_by: b.user_id,
    expected: { verdict: res.verdict, n: res.full?.n, pf: res.full?.pf, wr: res.full?.wr, holdout_pf: res.holdout?.pf,
                costs2_pf: res.costs2?.pf, avg_r: res.avg_r, trades_per_month: res.trades_per_month },
    killswitch: KILL,
  };
  doc.items.push(item); await save(db, doc);
  return { ok: true, item };
}

export async function setStatus(db, b) {
  if (!['active', 'paused', 'retired'].includes(b.status)) throw fail(400, 'Stato non valido');
  const doc = await load(db);
  const item = doc.items.find(x => x.id === b.id);
  if (!item) throw fail(404, 'Strategia non trovata');
  if (item.status === 'retired') throw fail(409, 'Strategia ritirata: rivalidala e promuovila di nuovo');
  if (b.status === 'active' && item.status !== 'active' && activeCount(doc) >= MAX_ACTIVE) throw fail(409, `Al massimo ${MAX_ACTIVE} strategie attive`);
  item.status = b.status; item.updated_at = new Date().toISOString();
  item.status_reason = b.status === 'paused' ? String(b.reason || 'Pausa manuale').slice(0, 200) : null;
  item.paused_by = b.status === 'paused' ? 'utente' : null;
  await save(db, doc);
  return { ok: true, item };
}

// Chiamata dal bot (service) quando i risultati dal vivo si allontanano troppo dal backtest.
export async function autopause(db, b) {
  const doc = await load(db);
  const item = doc.items.find(x => x.id === b.id);
  if (!item || item.status !== 'active') return { ok: true, changed: false };
  item.status = 'paused'; item.paused_by = 'bot'; item.status_reason = String(b.reason || 'Pausa automatica').slice(0, 200);
  item.updated_at = new Date().toISOString();
  await save(db, doc);
  return { ok: true, changed: true };
}

export async function list(db) {
  return { ok: true, ...(await load(db)) };
}
