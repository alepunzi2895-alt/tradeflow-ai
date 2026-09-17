// TradeFlow AI — api/db.js
// Universal Turso DB gateway for all CRUD operations, Auth, and external Service Proxying (KB, MyFxBook).
// Consolidated to stay under Vercel Hobby plan limits.

import { createClient } from "@libsql/client";

const JWT_SECRET = process.env.JWT_SECRET || "tradeflow-fallback-secret-key-1234";

// Knowledge Base (GitHub)
const GITHUB_OWNER = process.env.GITHUB_OWNER || "alepunzi2895-alt";
const GITHUB_REPO  = process.env.GITHUB_REPO  || "tradeflow-ai";
const GITHUB_FILE  = "data/knowledge.json";
const GITHUB_TOKEN = process.env.GITHUB_TOKEN;

function getDb() {
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
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// ── ACTION HANDLERS ──────────────────────────────────────────────────────────

async function upsertUser(db, body) {
  const { id, name, email, risk, max_dd, tp1, tp2, currency } = body;
  if (!id) throw new Error("user id required");
  await db.execute({
    sql: `INSERT INTO users (id, name, email, risk, max_dd, tp1, tp2, currency, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, email=COALESCE(excluded.email, email),
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
  await db.execute({
    sql: `INSERT INTO trades (id, user_id, symbol, direction, entry_price, exit_price, sl, tp1, tp2, size, result, pnl, emotion, mistake, notes, strategy, source, trade_date)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET
            symbol=excluded.symbol, direction=excluded.direction, entry_price=excluded.entry_price, exit_price=excluded.exit_price,
            sl=excluded.sl, tp1=excluded.tp1, tp2=excluded.tp2, size=excluded.size, result=excluded.result, pnl=excluded.pnl,
            emotion=excluded.emotion, mistake=excluded.mistake, notes=excluded.notes, strategy=excluded.strategy, trade_date=excluded.trade_date`,
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
  args.push(limit);
  const result = await db.execute({ sql, args });
  return { ok: true, trades: result.rows };
}

async function register(db, body) {
  const { email, password, name, current_user_id } = body;
  if (!email || !password) throw new Error("email and password required");
  const bcrypt = await import("bcryptjs");
  const jwt = await import("jsonwebtoken");
  const _bcrypt = bcrypt.default || bcrypt;
  const _jwt = jwt.default || jwt;

  const existing = await db.execute({ sql: "SELECT id FROM users WHERE email=?", args: [email] });
  if (existing.rows.length > 0) throw new Error("Email già registrata.");

  const userId = current_user_id || uuid();
  const hashed = await _bcrypt.hash(password, 10);
  await db.execute({
    sql: `INSERT INTO users (id, name, email, password, risk, max_dd, tp1, tp2, currency) VALUES (?, ?, ?, ?, 2, 6, 1.5, 3.0, 'USD')`,
    args: [userId, name || "Trader", email, hashed]
  });
  const token = _jwt.sign({ id: userId, email }, JWT_SECRET, { expiresIn: "30d" });
  return { ok: true, user: { id: userId, email, name: name || "Trader" }, token };
}

async function login(db, body) {
  const { email, password } = body;
  const bcrypt = await import("bcryptjs");
  const jwt = await import("jsonwebtoken");
  const _bcrypt = bcrypt.default || bcrypt;
  const _jwt = jwt.default || jwt;

  const result = await db.execute({ sql: "SELECT * FROM users WHERE email=?", args: [email] });
  if (result.rows.length === 0) throw new Error("Credenziali non valide.");
  const user = result.rows[0];
  const match = await _bcrypt.compare(password, user.password);
  if (!match) throw new Error("Credenziali non valide.");

  const token = _jwt.sign({ id: user.id, email }, JWT_SECRET, { expiresIn: "30d" });
  return { ok: true, user: { id: user.id, email: user.email, name: user.name }, token };
}

async function saveUserData(db, body) {
  const { user_id, doc_type, payload } = body;
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

async function kbLoad() {
  const r = await fetchT(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, { headers: { "Authorization": `Bearer ${GITHUB_TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TradeFlowHub" } });
  if (r.status === 404) return { ok: true, kb: [], knowledge: [] };
  const d = await r.json();
  const content = JSON.parse(Buffer.from(d.content, "base64").toString("utf-8"));
  return { ok: true, ...content, sha: d.sha };
}

async function kbSave(db, body) {
  const { kb, knowledge, sha } = body;
  const content = { kb: kb || [], knowledge: knowledge || [], updatedAt: new Date().toISOString(), app: "TradeFlowHub" };
  const r = await fetchT(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${GITHUB_FILE}`, { method: "PUT", headers: { "Authorization": `Bearer ${GITHUB_TOKEN}`, "Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "TradeFlowHub" }, body: JSON.stringify({ message: "Update KB", content: Buffer.from(JSON.stringify(content, null, 2)).toString("base64"), sha }) });
  if (!r.ok) throw new Error("GitHub Save Failed");
  return { ok: true };
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
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
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
  if (typeof score !== 'number') throw new Error("score must be a number");
  const payload = JSON.stringify({ score, updated_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('ai-score', 'browser', 'ai_score', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function mt5CommandPush(db, body) {
  const { command, secret } = body;
  // Il comando viene pushato dalla UI. La UI non ha il segreto del bot, 
  // ma possiamo richiedere un token utente o semplicemente fidarci se l'azione è protetta.
  // In questo caso, essendo un gateway unico, aggiungiamo un controllo rapido.
  if (!command) throw new Error("Command required");
  const payload = JSON.stringify({ ...command, created_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('mt5-cmd', 'mt5-bot', 'mt5_command', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function mt5CommandGet(db, body) {
  const { secret } = body;
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
  
  const result = await db.execute({ sql: "SELECT payload FROM user_data WHERE user_id='mt5-bot' AND doc_type='mt5_command'", args: [] });
  if (!result.rows.length) return { ok: true, command: null };
  
  const row = result.rows[0];
  if (!row.payload) return { ok: true, command: null };
  
  const command = JSON.parse(row.payload);
  
  // Una volta letto, "consumiamo" il comando svuotando il payload
  await db.execute({ sql: "UPDATE user_data SET payload=NULL WHERE user_id='mt5-bot' AND doc_type='mt5_command'", args: [] });
  
  return { ok: true, command };
}

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
  if (!row.rows.length) return { ok: true, enabled: true };  // default: on
  const p = JSON.parse(row.rows[0].payload);
  return { ok: true, enabled: p.enabled ?? true, updated_at: p.updated_at };
}

// ── S20_FIB_CONFLUENCE PAPER TRADING ─────────────────────────────────────────
// scripts/paper_trade_s20.py invia il riepilogo paper (nessun ordine reale).
// La UI lo legge senza auth per mostrarlo nel tab Strategie (marcato PAPER).
async function s20PaperPush(db, body) {
  const { secret, summary } = body;
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
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
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
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
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
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
async function backtestCmdPush(db, body) {
  const { strategy_id } = body;
  if (!strategy_id) throw new Error("strategy_id required");
  const payload = JSON.stringify({ strategy_id, requested_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES ('backtest-cmd', 'backtest-worker', 'backtest_cmd', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [payload],
  });
  return { ok: true };
}

async function backtestCmdGet(db, body) {
  const { secret } = body;
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
  const result = await db.execute({ sql: "SELECT payload FROM user_data WHERE user_id='backtest-worker' AND doc_type='backtest_cmd'", args: [] });
  if (!result.rows.length || !result.rows[0].payload) return { ok: true, command: null };
  const command = JSON.parse(result.rows[0].payload);
  await db.execute({ sql: "UPDATE user_data SET payload=NULL WHERE user_id='backtest-worker' AND doc_type='backtest_cmd'", args: [] });
  return { ok: true, command };
}

async function backtestResultPush(db, body) {
  const { secret, strategy_id, result } = body;
  const expected = process.env.MT5_BOT_SECRET || "tradeflow-mt5-secret";
  if (secret !== expected) throw new Error("Unauthorized");
  if (!strategy_id) throw new Error("strategy_id required");
  const uid = `backtest-result-${strategy_id}`;
  const payload = JSON.stringify({ ...(result || {}), strategy_id, synced_at: new Date().toISOString() });
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES (?, ?, 'backtest_result', ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [uid, uid, payload],
  });
  return { ok: true };
}

async function backtestResultGet(db, body) {
  const { strategy_id } = body;
  if (!strategy_id) throw new Error("strategy_id required");
  const uid = `backtest-result-${strategy_id}`;
  const r = await db.execute({ sql: "SELECT payload, updated_at FROM user_data WHERE user_id=? AND doc_type='backtest_result'", args: [uid] });
  if (!r.rows.length) return { ok: true, data: null };
  return { ok: true, data: JSON.parse(r.rows[0].payload), updated_at: r.rows[0].updated_at };
}

// ── HARD BLOCKS (toggle attiva/blocca dalla UI → commit vero su GitHub) ─────
// data/hard_blocks.json resta la fonte di verità git-tracked (letta da
// strategy_selector.is_hard_blocked(), invariato) — qui la UI può proporre un commit
// invece di richiedere una modifica manuale. Richiede login (JWT) perché tocca
// trading live con soldi veri; il bot legge comunque il file solo al prossimo
// git pull + restart, stesso comportamento di una modifica fatta a mano.
async function verifyAuthToken(token) {
  if (!token) throw new Error("Login richiesto");
  const jwt = await import("jsonwebtoken");
  const _jwt = jwt.default || jwt;
  try {
    return _jwt.verify(token, JWT_SECRET);
  } catch (e) {
    throw new Error("Sessione non valida o scaduta — rifai il login");
  }
}

const HARD_BLOCKS_FILE = "data/hard_blocks.json";

async function hardBlocksLoad() {
  const r = await fetchT(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${HARD_BLOCKS_FILE}`, { headers: { "Authorization": `Bearer ${GITHUB_TOKEN}`, "Accept": "application/vnd.github+json", "User-Agent": "TradeFlowHub" } });
  const d = await r.json();
  const content = JSON.parse(Buffer.from(d.content, "base64").toString("utf-8"));
  return { ok: true, blocked: content.blocked || {}, sha: d.sha };
}

async function hardBlocksToggle(db, body) {
  const { token, strategy_id, action, reason } = body;
  const user = await verifyAuthToken(token);
  if (!strategy_id) throw new Error("strategy_id required");
  if (!["block", "unblock"].includes(action)) throw new Error("action deve essere 'block' o 'unblock'");

  const current = await hardBlocksLoad();
  const blocked = { ...current.blocked };
  if (action === "block") {
    if (!reason) throw new Error("reason required per bloccare una strategia");
    blocked[strategy_id] = { since: new Date().toISOString().slice(0, 10), reason: `${reason} (bloccata dalla dashboard da ${user.email || user.id})` };
  } else {
    delete blocked[strategy_id];
  }

  const content = {
    _comment: "Strategie disabilitate a livello di ESECUZIONE LIVE. File git-tracked, editabile a mano, da scripts/reactivation_check.py o dalla dashboard (toggle autenticato). Letto da strategy_selector.is_hard_blocked() (primo check in mt5-bot.quality_gate). NON viene mai toccato da PerformanceTracker.",
    blocked,
  };
  const message = `${action === "block" ? "Blocca" : "Sblocca"} ${strategy_id} (dashboard, ${user.email || user.id})`;
  const r = await fetchT(`https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/contents/${HARD_BLOCKS_FILE}`, {
    method: "PUT",
    headers: { "Authorization": `Bearer ${GITHUB_TOKEN}`, "Accept": "application/vnd.github+json", "Content-Type": "application/json", "User-Agent": "TradeFlowHub" },
    body: JSON.stringify({ message, content: Buffer.from(JSON.stringify(content, null, 2)).toString("base64"), sha: current.sha }),
  });
  if (!r.ok) throw new Error("Scrittura su GitHub fallita — riprova (probabile conflitto di versione, ricarica e riprova)");
  return { ok: true, blocked };
}

async function adminReset(db, body) {
  const { email, password } = body;
  if (!email || !password) throw new Error("email and pass required");
  const bcrypt = await import("bcryptjs");
  const _bcrypt = bcrypt.default || bcrypt;
  const hashed = await _bcrypt.hash(password, 10);
  await db.execute({
    sql: "UPDATE users SET password=? WHERE email=?",
    args: [hashed, email]
  });
  return { ok: true, message: `Password resettata per ${email}` };
}

const ACTIONS = {
  upsert_user: upsertUser, save_trade: saveTrade, get_trades: getTrades, register, login, save_user_data: saveUserData, get_user_data: getUserData, kb_load: kbLoad, kb_save: kbSave, mfx_proxy: mfxProxy, patch_db: patchDb, admin_reset: adminReset,
  mt5_push:   (db, body) => mt5Push(db, body),
  mt5_get:    (db)      => mt5Get(db),
  score_push: (db, body) => scorePush(db, body),
  mt5_command_push: (db, body) => mt5CommandPush(db, body),
  mt5_command_get:  (db, body) => mt5CommandGet(db, body),
  auto_trade_set:   (db, body) => autoTradeSet(db, body),
  auto_trade_get:   (db)       => autoTradeGet(db),
  s20_paper_push:   (db, body) => s20PaperPush(db, body),
  s20_paper_get:    (db)       => s20PaperGet(db),
  strat_live_push:  (db, body) => stratLivePush(db, body),
  strat_live_get:   (db, body) => stratLiveGet(db, body),
  backtest_report_push: (db, body) => backtestReportPush(db, body),
  backtest_report_get:  (db)       => backtestReportGet(db),
  backtest_cmd_push:    (db, body) => backtestCmdPush(db, body),
  backtest_cmd_get:     (db, body) => backtestCmdGet(db, body),
  backtest_result_push: (db, body) => backtestResultPush(db, body),
  backtest_result_get:  (db, body) => backtestResultGet(db, body),
  hard_blocks_load:     ()         => hardBlocksLoad(),
  hard_blocks_toggle:   (db, body) => hardBlocksToggle(db, body),
};

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  if (req.method === "GET") return res.status(200).json({ ok:true, service:"TradeFlow Gateway" });
  
  let body = req.body;
  if (typeof body === "string") body = JSON.parse(body);

  let { action } = body || {};
  if (!action) {
    if (req.url.includes("/api/kb")) action = req.method === "POST" ? "kb_save" : "kb_load";
    else if (req.url.includes("/api/myfxbook")) action = "mfx_proxy";
    else if (req.url.includes("/api/auth")) action = body?.action || "login";
  }
  if (!action) return res.status(400).json({ error: "action required" });

  const fn = ACTIONS[action];
  if (!fn) return res.status(400).json({ error: "invalid action" });

  try {
    const db = getDb();
    const result = await fn(db, body);
    return res.status(200).json(result);
  } catch (e) {
    return res.status(500).json({ error: e.message });
  }
}
