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

const ACTIONS = {
  upsert_user: upsertUser, save_trade: saveTrade, get_trades: getTrades, register, login, save_user_data: saveUserData, get_user_data: getUserData, kb_load: kbLoad, kb_save: kbSave, mfx_proxy: mfxProxy, patch_db: patchDb
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
