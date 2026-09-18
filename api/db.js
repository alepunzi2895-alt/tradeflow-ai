import { registrySnapshot } from '../lib/strategy-registry.js';
import * as jobs from '../lib/backtest-jobs.js';
// TradeFlow AI — api/db.js
// Universal Turso DB gateway for all CRUD operations, Auth, and external Service Proxying (KB, MyFxBook).
// Consolidated to stay under Vercel Hobby plan limits.

import { createClient } from "@libsql/client";
import { randomUUID } from 'node:crypto';
import { fail, jwtSecret, requireUser, requireOperator, serviceAuthorized, setSession, rateLimit, parseBody } from '../lib/security.js';


// Knowledge Base (GitHub)
const GITHUB_OWNER = process.env.GITHUB_OWNER || "alepunzi2895-alt";
const GITHUB_REPO  = process.env.GITHUB_REPO  || "tradeflow-ai";
const GITHUB_FILE  = "data/knowledge.json";
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;

export function getDb() {
  let url   = process.env.TURSO_DB_URL;
  const token = process.env.TURSO_AUTH_TOKEN;
  if (!url || !token) throw new Error("TURSO_DB_URL or TURSO_AUTH_TOKEN missing");
  if (url.startsWith("libsql://")) url = url.replace("libsql://", "https://");
  return createClient({ url, authToken: token });
}

async function fetchT(url, opts = {}, ms = 8000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal });
    clearTimeout(tid);
    return r;
  } catch(e) {
    clearTimeout(tid);
    throw e;
  }
}

function uuid() {
  return randomUUID();
}

// ── ACTION HANDLERS ──────────────────────────────────────────────────────────

async function upsertUser(db, body) {
  const { id, name, email, risk, max_dd, tp1, tp2, currency } = body;
  if (!id) throw new Error("user id required");
  await db.execute({
    sql: `INSERT INTO users (id, name, email, risk, max_dd, tp1, tp2, currency, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            risk=excluded.risk, max_dd=excluded.max_dd, tp1=excluded.tp1,
            tp2=excluded.tp2, currency=excluded.currency, updated_at=CURRENT_TIMESTAMP`,
    args: [id, name||"Trader", email||null, risk||2, max_dd||6, tp1||1.5, tp2||3.0, currency||"USD"],
  });
  return { ok: true, id };
}

async function saveTrade(db, body) {
  const { user_id, id, symbol, direction, entry_price, exit_price, sl, tp1, tp2, size, result, pnl, emotion, mistake, notes, strategy, source, trade_date } = body;
  if (!user_id) throw new Error("user_id required");
  const tradeId = id || uuid();
  if (!['BUY','SELL'].includes(direction) || !['WIN','LOSS','BE',''].includes(result || '')) throw fail(400, 'Trade non valido');
  const owner = await db.execute({sql:'SELECT user_id FROM trades WHERE id=?', args:[String(tradeId)]});
  if (owner.rows.length && owner.rows[0].user_id !== user_id) throw fail(403, 'Trade non accessibile');
  await db.execute({
    sql: `INSERT INTO trades (id, user_id, symbol, direction, entry_price, exit_price, sl, tp1, tp2, size, result, pnl, emotion, mistake, notes, strategy, source, trade_date)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET
            symbol=excluded.symbol, direction=excluded.direction, entry_price=excluded.entry_price, exit_price=excluded.exit_price,
            sl=excluded.sl, tp1=excluded.tp1, tp2=excluded.tp2, size=excluded.size, result=excluded.result, pnl=excluded.pnl,
            emotion=excluded.emotion, mistake=excluded.mistake, notes=excluded.notes, strategy=excluded.strategy, source=excluded.source, trade_date=excluded.trade_date
            WHERE trades.user_id=excluded.user_id`,
    args: [tradeId, user_id, symbol || "XAUUSD", direction || null, parseFloat(entry_price) || null, parseFloat(exit_price) || null, parseFloat(sl) || null, parseFloat(tp1) || null, parseFloat(tp2) || null, parseFloat(size) || 0, result || "", parseFloat(pnl) || 0, emotion || "Neutro", mistake || "Nessuno", notes || "", strategy || "", source || "manual", trade_date || new Date().toISOString().slice(0, 10)],
  });
  return { ok: true, id: tradeId };
}

async function getTrades(db, body) {
  const { user_id, limit = 200, symbol } = body;
  if (!user_id) throw new Error("user_id required");
  let sql = "SELECT * FROM trades WHERE user_id=?";
  const args = [user_id];
  if (symbol) { sql += " AND symbol=?"; args.push(symbol); }
  sql += " ORDER BY trade_date DESC, created_at DESC LIMIT ?";
  args.push(Math.max(1, Math.min(5000, Number(limit) || 200)));
  const result = await db.execute({ sql, args });
  return { ok: true, trades: result.rows };
}

async function register(db, body) {
  const { email, password, name, current_user_id } = body;
  if (typeof email !== 'string' || !email.includes('@') || typeof password !== 'string' || password.length < 12 || password.length > 72) throw fail(400, 'Email e password di 12–72 caratteri richieste');
  const bcrypt = await import("bcryptjs");
  const jwt = await import("jsonwebtoken");
  const _bcrypt = bcrypt.default || bcrypt;
  const _jwt = jwt.default || jwt;

  const existing = await db.execute({ sql: "SELECT id FROM users WHERE email=?", args: [email] });
  if (existing.rows.length > 0) throw new Error("Email già registrata.");

  const userId = uuid();
  const hashed = await _bcrypt.hash(password, 10);
  await db.execute({
    sql: `INSERT INTO users (id, name, email, password, risk, max_dd, tp1, tp2, currency) VALUES (?, ?, ?, ?, 2, 6, 1.5, 3.0, 'USD')`,
    args: [userId, name || "Trader", email, hashed]
  });
  const token = _jwt.sign({ id: userId, email }, jwtSecret(), { expiresIn: "30d" });
  return { ok: true, user: { id: userId, email, name: name || "Trader" }, token };
}

async function login(db, body) {
  const { email, password } = body;
  if (typeof email !== 'string' || typeof password !== 'string' || password.length > 72) throw fail(400, 'Credenziali richieste');
  const bcrypt = await import("bcryptjs");
  const jwt = await import("jsonwebtoken");
  const _bcrypt = bcrypt.default || bcrypt;
  const _jwt = jwt.default || jwt;

  const result = await db.execute({ sql: "SELECT * FROM users WHERE email=?", args: [email] });
  if (result.rows.length === 0) throw new Error("Credenziali non valide.");
  const user = result.rows[0];
  const match = user.password && await _bcrypt.compare(password, user.password);
  if (!match) throw new Error("Credenziali non valide.");

  const token = _jwt.sign({ id: user.id, email }, jwtSecret(), { expiresIn: "30d" });
  return { ok: true, user: { id: user.id, email: user.email, name: user.name }, token };
}

async function saveUserData(db, body) {
  const { user_id, doc_type, payload } = body;
  if (!['chat','kb','mfx','amem','mem','lab'].includes(doc_type)) throw fail(400, 'Tipo documento non consentito');
  if (payload != null && (typeof payload !== 'string' || payload.length > 1_000_000)) throw fail(400, 'Documento non valido');
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [uuid(), user_id, doc_type, payload || null],
  });
  return { ok: true };
}

async function getUserData(db, body) {
  const result = await db.execute({ sql: "SELECT doc_type, payload FROM user_data WHERE user_id=?", args: [body.user_id] });
  return { ok: true, data: result.rows };
}

async function kbLoad(db, body) {
  const r = await db.execute({sql:"SELECT payload FROM user_data WHERE user_id=? AND doc_type='kb'", args:[body.user_id]});
  const kb = r.rows.length ? JSON.parse(r.rows[0].payload || '[]') : [];
  return {ok:true, kb, knowledge:kb.slice(-6).map(x => `[${x.name}]\n${x.summary}`)};
}

async function kbSave(db, body) {
  if (!Array.isArray(body.kb)) throw fail(400, 'KB non valida');
  return saveUserData(db, {...body, doc_type:'kb', payload:JSON.stringify(body.kb)});
}

async function mfxProxy(db, body) {
  const { mfx_action, session, email, password, accountId } = body;
  let url = "";
  if (mfx_action === "login") url = `https://www.myfxbook.com/api/login.json?email=${encodeURIComponent(email)}&password=${encodeURIComponent(password)}`;
  else if (mfx_action === "accounts") url = `https://www.myfxbook.com/api/get-my-accounts.json?session=${session}`;
  else if (mfx_action === "history") url = `https://www.myfxbook.com/api/get-history.json?session=${session}&id=${accountId}`;
  else if (mfx_action === "stats") url = `https://www.myfxbook.com/api/get-data-daily.json?session=${session}&id=${accountId}&start=2024-01-01&end=2099-01-01`;
  const r = await fetchT(url);
  return await r.json();
}

async function patchDb(db) {
  try { await db.execute("ALTER TABLE users ADD COLUMN password TEXT"); } catch(e){}
  try {
    await db.execute("CREATE TABLE IF NOT EXISTS user_data (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, doc_type TEXT NOT NULL, payload TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)");
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_data_type ON user_data(user_id, doc_type)");
  } catch(e){}
  return { ok: true };
}

// ── MT5 LIVE SYNC ─────────────────────────────────────────────────────────────
// Il bot locale invia il suo stato ogni ~60s con una chiave segreta.
// La UI legge i dati senza autenticazione (dati di monitoraggio, non sensibili).

async function mt5Push(db, body) {
  const { secret, account, positions, trades, bot_status } = body;
  const expected = process.env.MT5_BOT_SECRET;
  if (!expected || secret !== expected) throw new Error("Unauthorized");
  const payload = JSON.stringify({ account, positions: positions||[], trades: trades||[], bot_status, synced_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('mt5-live', 'mt5-bot', 'mt5_live', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function mt5Get(db) {
  const result = await db.execute({ sql: "SELECT payload, updated_at FROM user_data WHERE user_id='mt5-bot' AND doc_type='mt5_live'", args: [] });
  if (!result.rows.length) return { ok: true, data: null };
  const row = result.rows[0];
  const data = JSON.parse(row.payload);
  // Leggi AI score salvato dal browser
  const scoreRow = await db.execute({ sql: "SELECT payload FROM user_data WHERE user_id='browser' AND doc_type='ai_score'", args: [] });
  if (scoreRow.rows.length) {
    const s = JSON.parse(scoreRow.rows[0].payload);
    data.ai_score = s.score;
    data.ai_score_updated_at = s.updated_at;  // freshness check lato bot
  }
  return { ok: true, data, updated_at: row.updated_at };
}

async function scorePush(db, body) {
  const { score } = body;
  if (!Number.isFinite(score) || score < 0 || score > 100) throw fail(400, 'Score fuori intervallo 0–100');
  const payload = JSON.stringify({ score, updated_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('ai-score', 'browser', 'ai_score', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function mt5CommandGet(){return {ok:true,command:null,disabled:true};}

async function autoTradeSet(db, body) {
  const { enabled } = body;
  if (typeof enabled !== 'boolean') throw new Error("enabled must be boolean");
  const payload = JSON.stringify({ enabled, updated_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('auto-trade', 'bot-config', 'auto_trade', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true, enabled };
}

async function autoTradeGet(db) {
  const row = await db.execute({ sql: "SELECT payload FROM user_data WHERE user_id='bot-config' AND doc_type='auto_trade'", args: [] });
  if (!row.rows.length) return { ok: true, enabled: false };
  const p = JSON.parse(row.rows[0].payload);
  return { ok: true, enabled: p.enabled === true, updated_at: p.updated_at };
}

// ── S20_FIB_CONFLUENCE PAPER TRADING ─────────────────────────────────────────
// scripts/paper_trade_s20.py invia il riepilogo paper (nessun ordine reale).
// La UI lo legge senza auth per mostrarlo nel tab Strategie (marcato PAPER).
async function s20PaperPush(db, body) {
  const { secret, summary } = body;
  const expected = process.env.MT5_BOT_SECRET;
  if (!expected || secret !== expected) throw new Error("Unauthorized");
  const payload = JSON.stringify({ ...(summary || {}), synced_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('s20-paper', 's20-paper', 's20_paper', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function s20PaperGet(db) {
  const r = await db.execute({ sql: "SELECT payload, updated_at FROM user_data WHERE user_id='s20-paper' AND doc_type='s20_paper'", args: [] });
  if (!r.rows.length) return { ok: true, data: null };
  return { ok: true, data: JSON.parse(r.rows[0].payload), updated_at: r.rows[0].updated_at };
}

// ── LIVE STATS PER-STRATEGIA (generico) ─────────────────────────────────────
// Il bot POSTa il riepilogo live di una strategia parallela (S31_LAYOUT_SMART, ...).
// La UI lo legge senza auth per la card nel tab Strategie. key = tag breve ([A-Za-z0-9_]).
async function stratLivePush(db, body) {
  const { secret, key, summary } = body;
  const expected = process.env.MT5_BOT_SECRET;
  if (!expected || secret !== expected) throw new Error("Unauthorized");
  const k = String(key || "").replace(/[^A-Za-z0-9_]/g, "").slice(0, 32);
  if (!k) throw new Error("key required");
  const uid = `strat-${k}-live`;
  const payload = JSON.stringify({ ...(summary || {}), synced_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES (?, ?, 'strat_live', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [uid, uid, payload],
  });
  return { ok: true };
}

async function stratLiveGet(db, body) {
  const k = String((body && body.key) || "").replace(/[^A-Za-z0-9_]/g, "").slice(0, 32);
  if (!k) return { ok: true, data: null };
  const r = await db.execute({ sql: "SELECT payload, updated_at FROM user_data WHERE user_id=? AND doc_type='strat_live'", args: [`strat-${k}-live`] });
  if (!r.rows.length) return { ok: true, data: null };
  return { ok: true, data: JSON.parse(r.rows[0].payload), updated_at: r.rows[0].updated_at };
}

// ── BACKTEST REPORT (periodico, giornaliero da daily_maintenance.py) ────────
// scripts/portfolio_backtest.py gira una volta al giorno e POSTa qui l'intero report
// (equity curve, full/holdout per strategia, validazione regime) — stessa forma dei file
// backtests/results/portfolio*.json. La UI lo legge senza auth per il pannello "Report
// Backtest" nel tab Strategie (vedi public/modules/backtest-report.js).
async function backtestReportPush(db, body) {
  const { secret, report } = body;
  const expected = process.env.MT5_BOT_SECRET;
  if (!expected || secret !== expected) throw new Error("Unauthorized");
  const payload = JSON.stringify({ ...(report || {}), synced_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('backtest-report', 'backtest-report', 'backtest_report', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function backtestReportGet(db) {
  const r = await db.execute({ sql: "SELECT payload, updated_at FROM user_data WHERE user_id='backtest-report' AND doc_type='backtest_report'", args: [] });
  if (!r.rows.length) return { ok: true, data: null };
  return { ok: true, data: JSON.parse(r.rows[0].payload), updated_at: r.rows[0].updated_at };
}

// ── BACKTEST ON-DEMAND (coda comando verso scripts/backtest_worker.py) ──────
// Stesso pattern one-slot di mt5_command_push/get: la UI mette in coda UNA richiesta di
// backtest per una strategia, il worker (in esecuzione sul PC dell'utente, separato dal
// bot live per non rallentarlo) la consuma, gira il backtest e posta il risultato tramite
// backtest_result_push, keyed per strategy_id così più richieste non si sovrascrivono.
// ── HARD BLOCKS (toggle attiva/blocca dalla UI → commit vero su GitHub) ─────
// data/hard_blocks.json resta la fonte di verità git-tracked (letta da
// strategy_selector.is_hard_blocked(), invariato) — qui la UI può proporre un commit
// invece di richiedere una modifica manuale. Richiede login (JWT) perché tocca
// trading live con soldi veri; il bot legge comunque il file solo al prossimo
// git pull + restart, stesso comportamento di una modifica fatta a mano.
const HARD_BLOCKS_FILE = "data/hard_blocks.json";

async function hardBlocksLoad() {
  const r = await fetchT(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${HARD_BLOCKS_FILE}`, { headers: { "Authorization": `Bearer ${GITHUB_TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TradeFlowHub" } });
  const d = await r.json();
  const content = JSON.parse(Buffer.from(d.content, "base64").toString("utf-8"));
  return { ok: true, blocked: content.blocked || {}, sha: d.sha };
}

async function hardBlocksToggle(db, body) {
  // NB: il campo dispatcher di livello superiore si chiama anche lui "action"
  // (action:"hard_blocks_toggle") — per questo il verbo block/unblock qui è "mode",
  // mai "action", altrimenti nello stesso oggetto JSON l'ultima chiave sovrascrive
  // la prima e il dispatcher riceve "block"/"unblock" invece di "hard_blocks_toggle".
  const { token, strategy_id, mode, reason } = body;
  const user = body.actor;
  if (!strategy_id) throw new Error("strategy_id required");
  if (!["block", "unblock"].includes(mode)) throw new Error("mode deve essere 'block' o 'unblock'");

  const current = await hardBlocksLoad();
  const blocked = { ...current.blocked };
  if (mode === "block") {
    if (!reason) throw new Error("reason required per bloccare una strategia");
    blocked[strategy_id] = { since: new Date().toISOString().slice(0, 10), reason: `${reason} (bloccata dalla dashboard da ${user.email || user.id})` };
  } else {
    delete blocked[strategy_id];
  }

  const content = {
    _comment: "Strategie disabilitate a livello di ESECUZIONE LIVE. File git-tracked, editabile a mano, da scripts/reactivation_check.py o dalla dashboard (toggle autenticato). Letto da strategy_selector.is_hard_blocked() (primo check in mt5-bot.quality_gate). NON viene mai toccato da PerformanceTracker.",
    blocked,
  };
  const message = `${mode === "block" ? "Blocca" : "Sblocca"} ${strategy_id} (dashboard, ${user.email || user.id})`;
  const r = await fetchT(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${HARD_BLOCKS_FILE}`, {
    method: "PUT",
    headers: { "Authorization": `Bearer ${GITHUB_TOKEN}`, "Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "TradeFlowHub" },
    body: JSON.stringify({ message, content: Buffer.from(JSON.stringify(content, null, 2)).toString("base64"), sha: current.sha }),
  });
  if (!r.ok) throw new Error("Scrittura su GitHub fallita — riprova (probabile conflitto di versione, ricarica e riprova)");
  return { ok: true, blocked };
}

async function deleteTrade(db, body) {
  await db.execute({sql:'DELETE FROM trades WHERE id=? AND user_id=?', args:[String(body.id), body.user_id]});
  return {ok:true};
}

async function replaceImportedTrades(db, body) {
  if (!Array.isArray(body.trades) || !body.trades.length || body.trades.length>5000 || !/^[\w-]{1,80}$/.test(String(body.account_id))) throw fail(400,'Importazione non valida');
  for(const t of body.trades) {
    if(!String(t.id).startsWith(`mfx:${body.user_id}:`) || !['BUY','SELL'].includes(t.direction) || !['WIN','LOSS','BE',''].includes(t.result||'')) throw fail(400,'Trade importato non valido');
    for(const field of ['entry_price','exit_price','sl','tp1','tp2','size','pnl']) if(t[field]!=null && !Number.isFinite(Number(t[field]))) throw fail(400,'Valore numerico non valido');
  }
  const payload=JSON.stringify(body.trades);
  const tx=await db.transaction('write');
  try {
    const collision=await tx.execute({sql:"SELECT t.id FROM trades t JOIN json_each(?) j ON t.id=json_extract(j.value,'$.id') WHERE t.user_id<>? LIMIT 1",args:[payload,body.user_id]});
    if(collision.rows.length) throw fail(403,'Identificativo già appartenente a un altro utente');
    await tx.execute({sql:"DELETE FROM trades WHERE user_id=? AND (source='myfxbook' OR source LIKE 'myfxbook:%')",args:[body.user_id]});
    // One bulk statement, rather than two remote round trips for each imported trade.
    await tx.execute({sql:`INSERT INTO trades(id,user_id,symbol,direction,entry_price,exit_price,sl,tp1,tp2,size,result,pnl,emotion,mistake,notes,strategy,source,trade_date)
      SELECT json_extract(value,'$.id'),?,json_extract(value,'$.symbol'),json_extract(value,'$.direction'),
        json_extract(value,'$.entry_price'),json_extract(value,'$.exit_price'),json_extract(value,'$.sl'),json_extract(value,'$.tp1'),json_extract(value,'$.tp2'),
        COALESCE(json_extract(value,'$.size'),0),COALESCE(json_extract(value,'$.result'),''),COALESCE(json_extract(value,'$.pnl'),0),
        json_extract(value,'$.emotion'),json_extract(value,'$.mistake'),json_extract(value,'$.notes'),'',?,json_extract(value,'$.trade_date')
      FROM json_each(?) WHERE true
      ON CONFLICT(id) DO UPDATE SET symbol=excluded.symbol,direction=excluded.direction,entry_price=excluded.entry_price,exit_price=excluded.exit_price,
        sl=excluded.sl,tp1=excluded.tp1,tp2=excluded.tp2,size=excluded.size,result=excluded.result,pnl=excluded.pnl,notes=excluded.notes,source=excluded.source,trade_date=excluded.trade_date
      WHERE trades.user_id=excluded.user_id`,args:[body.user_id,`myfxbook:${body.account_id}`,payload]});
    await tx.commit();return {ok:true,count:body.trades.length};
  } catch(e){await tx.rollback();throw e;} finally{tx.close();}
}

export async function savePerformanceSnapshot(db, b) {
  await db.execute({sql:`INSERT INTO performance_stats(id,user_id,symbol,period,total_trades,wins,losses,winrate,expectancy,avg_win,avg_loss,total_pnl,profit_factor)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,args:[uuid(),b.user_id,b.symbol,b.period||'all',b.total_trades,b.wins,b.losses,b.winrate,b.expectancy,b.avg_win,b.avg_loss,b.total_pnl,Number.isFinite(Number(b.profit_factor))?Number(b.profit_factor):null]});
  return {ok:true};
}
export async function saveSignal(db, b) {
  await db.execute({sql:`INSERT INTO signals(id,symbol,timeframe,type,source,cci,macd,macd_signal,adx,di_plus,di_minus,price)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`,args:[uuid(),b.symbol,b.tf,b.macd>b.signal?'BULLISH':b.macd<b.signal?'BEARISH':'NEUTRAL','tradingview_webhook',b.cci,b.macd,b.signal,b.adx,b.di_plus,b.di_minus,b.price]});
  return {ok:true};
}

const ACTIONS = {
  replace_imported_trades: replaceImportedTrades,
  strategy_registry: () => ({ok:true,data:registrySnapshot()}),
  upsert_user: upsertUser, save_trade: saveTrade, get_trades: getTrades, register, login, save_user_data: saveUserData, get_user_data: getUserData, kb_load: kbLoad, kb_save: kbSave, mfx_proxy: mfxProxy, patch_db: patchDb, delete_trade: deleteTrade,
  mt5_push:   (db, body) => mt5Push(db, body),
  mt5_get:    (db)      => mt5Get(db),
  score_push: (db, body) => scorePush(db, body),
  mt5_command_get:  (db, body) => mt5CommandGet(db, body),
  auto_trade_set:   (db, body) => autoTradeSet(db, body),
  auto_trade_get:   (db)       => autoTradeGet(db),
  s20_paper_push:   (db, body) => s20PaperPush(db, body),
  s20_paper_get:    (db)       => s20PaperGet(db),
  strat_live_push:  (db, body) => stratLivePush(db, body),
  strat_live_get:   (db, body) => stratLiveGet(db, body),
  backtest_report_push: (db, body) => backtestReportPush(db, body),
  backtest_report_get:  (db)       => backtestReportGet(db),
  backtest_cmd_push:    (db, body) => jobs.enqueue(db, body),
  backtest_cmd_get:     (db, body) => jobs.claim(db),
  backtest_result_push: (db, body) => jobs.complete(db, body),
  backtest_result_get:  (db, body) => jobs.result(db, body),
  hard_blocks_load:     ()         => hardBlocksLoad(),
  hard_blocks_toggle:   (db, body) => hardBlocksToggle(db, body),
};

const SERVICE_ACTIONS = new Set(['mt5_push','mt5_command_get','s20_paper_push','strat_live_push','backtest_report_push','backtest_cmd_get','backtest_result_push']);
const READ_ACTIONS = new Set(['strategy_registry','mt5_get','auto_trade_get','s20_paper_get','strat_live_get','backtest_report_get','hard_blocks_load']);
const OPERATOR_ACTIONS = new Set(['auto_trade_set','score_push','hard_blocks_toggle','backtest_cmd_push','patch_db']);

export function createHandler(dbFactory = getDb) {
  return async function handler(req, res) {
    res.setHeader('Cache-Control', 'no-store');
    if (req.method === 'OPTIONS') return res.status(204).end();
    if (!['POST','GET'].includes(req.method)) return res.status(405).json({ok:false,error:'Metodo non consentito'});
    try {
      const body = parseBody(req);
      const isKb = req.url?.split('?')[0] === '/api/kb' || req.query?.route === 'kb';
      const action = body.action || (isKb ? (req.method === 'GET' ? 'kb_load' : 'kb_save') : null);
      if (req.method === 'GET' && !isKb) return res.status(200).json({ok:true,service:'TradeFlow Gateway'});
      if (action === 'admin_reset') throw fail(410, 'Reset remoto disabilitato');
      // Manual orders are disabled until they support the same strategy/guardian checks as automatic entries.
      if (action === 'mt5_command_push') throw fail(410, 'Ordini manuali remoti disabilitati');
      if (!ACTIONS[action] && !['session','logout'].includes(action)) throw fail(400, 'Azione non valida');
      const service = serviceAuthorized(req, body);
      if (SERVICE_ACTIONS.has(action)) {
        if (!service) throw fail(401, 'Servizio non autorizzato');
        body.secret = process.env.MT5_BOT_SECRET;
      } else if (!['login','register'].includes(action) && !(service && READ_ACTIONS.has(action))) {
        const actor = requireUser(req, body);
        if (OPERATOR_ACTIONS.has(action) || ['mt5_get','auto_trade_get','strat_live_get','s20_paper_get'].includes(action)) requireOperator(actor);
        if (body.user_id && body.user_id !== actor.id) throw fail(403, 'Utente non accessibile');
        body.user_id = actor.id;
        body.actor = actor;
        if (action === 'upsert_user') body.id = actor.id;
        if (action === 'logout') { setSession(req,res,''); return res.status(200).json({ok:true}); }
        if (action === 'session') {
          const {default: jwt} = await import('jsonwebtoken');
          setSession(req,res,jwt.sign({id:actor.id,email:actor.email},jwtSecret(),{expiresIn:'30d'}));
          return res.status(200).json({ok:true,user:{id:actor.id,email:actor.email}});
        }
      }
      const db = dbFactory();
      if (['login','register'].includes(action)) {
        jwtSecret();
        const ip = req.headers?.['x-forwarded-for']?.split(',')[0] || req.socket?.remoteAddress || 'unknown';
        await rateLimit(db, 'auth:'+ip, 20, 900);
      }
      const result = await ACTIONS[action](db, body);
      if (result.token) setSession(req,res,result.token);
      return res.status(200).json(result);
    } catch (e) {
      return res.status(e.status || 400).json({ok:false,error:e.message});
    }
  };
}
export default createHandler();
