// TradeFlow AI — api/db.js
// Universal Turso DB gateway for all CRUD operations.
// Uses HTTP transport via https:// URL (libsql auto-detects, works on Vercel serverless).

import { createClient } from "@libsql/client";
import * as bcrypt from "bcryptjs";
import * as jwt from "jsonwebtoken";

const JWT_SECRET = process.env.JWT_SECRET || "tradeflow-fallback-secret-key-1234";

function getDb() {
  let url   = process.env.TURSO_DB_URL;
  const token = process.env.TURSO_AUTH_TOKEN;
  if (!url || !token) throw new Error("TURSO_DB_URL or TURSO_AUTH_TOKEN missing");
  // Force HTTP transport: replace libsql:// with https:// so no WebSocket is attempted
  if (url.startsWith("libsql://")) url = url.replace("libsql://", "https://");
  return createClient({ url, authToken: token });
}


// ── HELPERS ─────────────────────────────────────────────────────────────────

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
            name=excluded.name,
            email=COALESCE(excluded.email, email),
            risk=excluded.risk,
            max_dd=excluded.max_dd,
            tp1=excluded.tp1,
            tp2=excluded.tp2,
            currency=excluded.currency,
            updated_at=CURRENT_TIMESTAMP`,
    args: [id, name||"Trader", email||null, risk||2, max_dd||6, tp1||1.5, tp2||3.0, currency||"USD"],
  });
  return { ok: true, id };
}

async function saveTrade(db, body) {
  const {
    user_id, id, symbol, direction, entry_price, exit_price,
    sl, tp1, tp2, size, result, pnl, emotion, mistake, notes,
    strategy, source, trade_date
  } = body;
  if (!user_id) throw new Error("user_id required");
  const tradeId = id || uuid();
  await db.execute({
    sql: `INSERT INTO trades
            (id, user_id, symbol, direction, entry_price, exit_price, sl, tp1, tp2,
             size, result, pnl, emotion, mistake, notes, strategy, source, trade_date)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET
            symbol=excluded.symbol, direction=excluded.direction,
            entry_price=excluded.entry_price, exit_price=excluded.exit_price,
            sl=excluded.sl, tp1=excluded.tp1, tp2=excluded.tp2,
            size=excluded.size, result=excluded.result, pnl=excluded.pnl,
            emotion=excluded.emotion, mistake=excluded.mistake,
            notes=excluded.notes, strategy=excluded.strategy,
            trade_date=excluded.trade_date`,
    args: [
      tradeId, user_id,
      symbol || "XAUUSD",
      direction || null,
      parseFloat(entry_price) || null,
      parseFloat(exit_price) || null,
      parseFloat(sl) || null,
      parseFloat(tp1) || null,
      parseFloat(tp2) || null,
      parseFloat(size) || 0,
      result || "",
      parseFloat(pnl) || 0,
      emotion || "Neutro",
      mistake || "Nessuno",
      notes || "",
      strategy || "",
      source || "manual",
      trade_date || new Date().toISOString().slice(0, 10),
    ],
  });
  return { ok: true, id: tradeId };
}

async function deleteTrade(db, body) {
  const { id, user_id } = body;
  if (!id || !user_id) throw new Error("id and user_id required");
  await db.execute({
    sql: "DELETE FROM trades WHERE id=? AND user_id=?",
    args: [id, user_id],
  });
  return { ok: true };
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

async function getStats(db, body) {
  const { user_id, symbol } = body;
  if (!user_id) throw new Error("user_id required");
  let sql = `SELECT
    COUNT(*) as total,
    SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN result='LOSS' THEN 1 ELSE 0 END) as losses,
    ROUND(AVG(CASE WHEN result='WIN' THEN pnl ELSE NULL END),2) as avg_win,
    ROUND(ABS(AVG(CASE WHEN result='LOSS' THEN pnl ELSE NULL END)),2) as avg_loss,
    ROUND(SUM(pnl),2) as total_pnl
  FROM trades WHERE user_id=?`;
  const args = [user_id];
  if (symbol) { sql += " AND symbol=?"; args.push(symbol); }
  const result = await db.execute({ sql, args });
  const row = result.rows[0] || {};
  const wins = parseInt(row.wins) || 0;
  const total = parseInt(row.total) || 0;
  const losses = parseInt(row.losses) || 0;
  const avgWin = parseFloat(row.avg_win) || 0;
  const avgLoss = parseFloat(row.avg_loss) || 0;
  const winrate = total > 0 ? Math.round(wins / total * 100) : 0;
  const expectancy = total > 0 ? ((wins/total) * avgWin - (losses/total) * avgLoss) : 0;
  const pf = avgLoss > 0 ? ((avgWin * wins) / (avgLoss * losses)).toFixed(2) : null;
  return { ok: true, stats: { total, wins, losses, winrate, expectancy: expectancy.toFixed(2), avg_win: avgWin, avg_loss: avgLoss, total_pnl: parseFloat(row.total_pnl)||0, profit_factor: pf } };
}

async function saveSignal(db, body) {
  const { symbol, timeframe, type, strength, source, cci, macd, macd_signal, adx, di_plus, di_minus, price } = body;
  const id = uuid();
  await db.execute({
    sql: `INSERT INTO signals (id, symbol, timeframe, type, strength, source, cci, macd, macd_signal, adx, di_plus, di_minus, price)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    args: [id, symbol||"XAUUSD", timeframe||"60", type||null, parseFloat(strength)||null,
           source||"tradingview_webhook", parseFloat(cci)||null, parseFloat(macd)||null,
           parseFloat(macd_signal)||null, parseFloat(adx)||null,
           parseFloat(di_plus)||null, parseFloat(di_minus)||null, parseFloat(price)||null],
  });
  return { ok: true, id };
}

async function saveMarketData(db, body) {
  const { symbol, timeframe, open, high, low, close, volume, timestamp, source } = body;
  const id = uuid();
  await db.execute({
    sql: `INSERT INTO market_data (id, symbol, timeframe, open, high, low, close, volume, source, timestamp)
          VALUES (?,?,?,?,?,?,?,?,?,?)`,
    args: [id, symbol||"XAUUSD", timeframe||"60",
           parseFloat(open)||null, parseFloat(high)||null, parseFloat(low)||null,
           parseFloat(close)||null, parseFloat(volume)||null,
           source||"tradingview", timestamp||new Date().toISOString()],
  });
  return { ok: true, id };
}

async function savePerformanceSnapshot(db, body) {
  const { user_id, symbol, period, total_trades, wins, losses, winrate, expectancy, avg_win, avg_loss, total_pnl, profit_factor } = body;
  if (!user_id) throw new Error("user_id required");
  const id = uuid();
  await db.execute({
    sql: `INSERT INTO performance_stats
            (id, user_id, symbol, period, total_trades, wins, losses, winrate, expectancy, avg_win, avg_loss, total_pnl, profit_factor)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    args: [id, user_id, symbol||"XAUUSD", period||"month",
           parseInt(total_trades)||0, parseInt(wins)||0, parseInt(losses)||0,
           parseFloat(winrate)||0, parseFloat(expectancy)||0,
           parseFloat(avg_win)||0, parseFloat(avg_loss)||0,
           parseFloat(total_pnl)||0, parseFloat(profit_factor)||null],
  });
  return { ok: true, id };
}

async function getLatestSignals(db, body) {
  const { symbol, limit = 20 } = body;
  let sql = "SELECT * FROM signals";
  const args = [];
  if (symbol) { sql += " WHERE symbol=?"; args.push(symbol); }
  sql += " ORDER BY created_at DESC LIMIT ?";
  args.push(limit);
  const result = await db.execute({ sql, args });
  return { ok: true, signals: result.rows };
}

async function register(db, body) {
  const { email, password, name, current_user_id } = body;
  if (!email || !password) throw new Error("email and password required");

  // Check if user already exists
  const existing = await db.execute({ sql: "SELECT id FROM users WHERE email=?", args: [email] });
  if (existing.rows.length > 0) {
    throw new Error("Email già registrata.");
  }

  const userId = current_user_id || uuid();
  const hashed = await bcrypt.hash(password, 10);

  await db.execute({
    sql: `INSERT INTO users (id, name, email, password, risk, max_dd, tp1, tp2, currency)
          VALUES (?, ?, ?, ?, 2, 6, 1.5, 3.0, 'USD')
          ON CONFLICT(id) DO UPDATE SET
            email=excluded.email,
            password=excluded.password,
            name=COALESCE(excluded.name, name)`,
    args: [userId, name || "Trader", email, hashed]
  });

  const token = jwt.sign({ id: userId, email }, JWT_SECRET, { expiresIn: "30d" });
  return { ok: true, user: { id: userId, email, name: name || "Trader" }, token };
}

async function login(db, body) {
  const { email, password } = body;
  if (!email || !password) throw new Error("email and password required");

  const result = await db.execute({ sql: "SELECT * FROM users WHERE email=?", args: [email] });
  if (result.rows.length === 0) {
    throw new Error("Credenziali non valide.");
  }

  const user = result.rows[0];
  if (!user.password) {
    throw new Error("Account senza password. Impossibile accedere.");
  }

  const match = await bcrypt.compare(password, user.password);
  if (!match) {
    throw new Error("Credenziali non valide.");
  }

  const token = jwt.sign({ id: user.id, email }, JWT_SECRET, { expiresIn: "30d" });
  return {
    ok: true,
    user: { id: user.id, email: user.email, name: user.name },
    token
  };
}

async function saveUserData(db, body) {
  const { user_id, doc_type, payload } = body;
  if (!user_id || !doc_type) throw new Error("user_id and doc_type required");
  const id = uuid();
  await db.execute({
    sql: `INSERT INTO user_data (id, user_id, doc_type, payload, updated_at)
          VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(user_id, doc_type) DO UPDATE SET 
            payload=excluded.payload, updated_at=CURRENT_TIMESTAMP`,
    args: [id, user_id, doc_type, payload || null],
  });
  return { ok: true };
}

async function getUserData(db, body) {
  const { user_id } = body;
  if (!user_id) throw new Error("user_id required");
  const result = await db.execute({
    sql: "SELECT doc_type, payload FROM user_data WHERE user_id=?",
    args: [user_id],
  });
  return { ok: true, data: result.rows };
}

async function patchDb(db) {
  const results = [];
  try {
    await db.execute("ALTER TABLE users ADD COLUMN password TEXT");
    results.push({ msg: "Added password to users" });
  } catch (e) {
    results.push({ msg: "Password col might exist: " + e.message });
  }
  try {
    await db.execute("CREATE TABLE IF NOT EXISTS user_data (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, doc_type TEXT NOT NULL, payload TEXT, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))");
    await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_data_type ON user_data(user_id, doc_type)");
    results.push({ msg: "Created user_data table & index" });
  } catch(e) {
    results.push({ msg: "Error creating user_data: " + e.message });
  }
  return { ok: true, results };
}

// ── MAIN HANDLER ─────────────────────────────────────────────────────────────

const ACTIONS = {
  upsert_user:              upsertUser,
  save_trade:               saveTrade,
  delete_trade:             deleteTrade,
  get_trades:               getTrades,
  get_stats:                getStats,
  save_signal:              saveSignal,
  save_market_data:         saveMarketData,
  save_performance_snapshot: savePerformanceSnapshot,
  get_latest_signals:       getLatestSignals,
  save_user_data:           saveUserData,
  get_user_data:            getUserData,
  patch_db:                 (db) => patchDb(db),
  register:                 register,
  login:                    login,
};

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();

  // Health check
  if (req.method === "GET") {
    return res.status(200).json({ ok: true, service: "TradeFlow DB Gateway", tables: Object.keys(ACTIONS) });
  }

  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { return res.status(400).json({ error: "Invalid JSON" }); }
  }

  const { action } = body || {};
  if (!action) return res.status(400).json({ error: "action required" });

  const fn = ACTIONS[action];
  if (!fn) return res.status(400).json({ error: `Unknown action: ${action}. Valid: ${Object.keys(ACTIONS).join(", ")}` });

  try {
    const db = getDb();
    const result = await fn(db, body);
    if (!result) return res.status(500).json({ error: "Action returned no result" });
    return res.status(200).json(result);
  } catch (e) {
    console.error("[db.js] Error executing action:", action, e.message);
    return res.status(500).json({ error: e.message || "Internal Server Error" });
  }
}
