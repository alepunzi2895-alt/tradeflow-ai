/**
 * TradeFlow AI — setup-turso.mjs
 * One-shot script to create all Turso DB tables.
 *
 * Usage:
 *   TURSO_DB_URL=libsql://... TURSO_AUTH_TOKEN=... node scripts/setup-turso.mjs
 *   OR with a .env file (install dotenv first)
 */

import { createClient } from "@libsql/client";

const url   = process.env.TURSO_DB_URL;
const token = process.env.TURSO_AUTH_TOKEN;

if (!url || !token) {
  console.error("❌  Missing env vars: TURSO_DB_URL and TURSO_AUTH_TOKEN are required.");
  console.error("   Example: TURSO_DB_URL=libsql://... TURSO_AUTH_TOKEN=... node scripts/setup-turso.mjs");
  process.exit(1);
}

const db = createClient({ url, authToken: token });

const TABLES = [
  // ── USERS ──────────────────────────────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS users (
    id          TEXT PRIMARY KEY,
    email       TEXT,
    name        TEXT,
    risk        REAL DEFAULT 2,
    max_dd      REAL DEFAULT 6,
    tp1         REAL DEFAULT 1.5,
    tp2         REAL DEFAULT 3.0,
    currency    TEXT DEFAULT 'USD',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
  )`,

  // ── TRADES (Journal) ───────────────────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS trades (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    symbol      TEXT DEFAULT 'XAUUSD',
    direction   TEXT CHECK(direction IN ('BUY','SELL')),
    entry_price REAL,
    exit_price  REAL,
    sl          REAL,
    tp1         REAL,
    tp2         REAL,
    size        REAL DEFAULT 0,
    result      TEXT CHECK(result IN ('WIN','LOSS','BE','')),
    pnl         REAL DEFAULT 0,
    emotion     TEXT DEFAULT 'Neutro',
    mistake     TEXT DEFAULT 'Nessuno',
    notes       TEXT DEFAULT '',
    strategy    TEXT DEFAULT '',
    source      TEXT DEFAULT 'manual',
    trade_date  DATE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
  )`,

  // ── POSITIONS (Live open positions) ────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS positions (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    symbol       TEXT,
    direction    TEXT CHECK(direction IN ('BUY','SELL')),
    size         REAL,
    entry_price  REAL,
    risk_percent REAL,
    stop_loss    REAL,
    take_profit  REAL,
    unrealized_pnl REAL DEFAULT 0,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
  )`,

  // ── SIGNALS (from TradingView webhook) ─────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS signals (
    id          TEXT PRIMARY KEY,
    symbol      TEXT,
    timeframe   TEXT DEFAULT '60',
    type        TEXT,
    strength    REAL,
    source      TEXT DEFAULT 'tradingview_webhook',
    cci         REAL,
    macd        REAL,
    macd_signal REAL,
    adx         REAL,
    di_plus     REAL,
    di_minus    REAL,
    price       REAL,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
  )`,

  // ── MARKET DATA (periodic price snapshots) ─────────────────────────────────
  `CREATE TABLE IF NOT EXISTS market_data (
    id          TEXT PRIMARY KEY,
    symbol      TEXT,
    timeframe   TEXT,
    open        REAL,
    high        REAL,
    low         REAL,
    close       REAL,
    volume      REAL,
    source      TEXT DEFAULT 'tradingview',
    timestamp   DATETIME
  )`,

  // ── NEWS EVENTS ────────────────────────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS news_events (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    impact      TEXT CHECK(impact IN ('High','Medium','Low')),
    currency    TEXT,
    forecast    TEXT,
    previous    TEXT,
    actual      TEXT,
    event_time  DATETIME,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
  )`,

  // ── PERFORMANCE SNAPSHOTS ──────────────────────────────────────────────────
  `CREATE TABLE IF NOT EXISTS performance_stats (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    symbol      TEXT DEFAULT 'XAUUSD',
    period      TEXT DEFAULT 'month',
    total_trades INTEGER DEFAULT 0,
    wins        INTEGER DEFAULT 0,
    losses      INTEGER DEFAULT 0,
    winrate     REAL,
    expectancy  REAL,
    avg_win     REAL,
    avg_loss    REAL,
    total_pnl   REAL,
    profit_factor REAL,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
  )`,

  // ── INDEXES ─────────────────────────────────────────────────────────────────
  `CREATE INDEX IF NOT EXISTS idx_trades_user_date   ON trades(user_id, trade_date DESC)`,
  `CREATE INDEX IF NOT EXISTS idx_trades_symbol      ON trades(symbol)`,
  `CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts  ON signals(symbol, created_at DESC)`,
  `CREATE INDEX IF NOT EXISTS idx_market_data_sym_tf ON market_data(symbol, timeframe, timestamp DESC)`,
  `CREATE INDEX IF NOT EXISTS idx_positions_user     ON positions(user_id)`,
  `CREATE INDEX IF NOT EXISTS idx_perf_user          ON performance_stats(user_id, period)`,
];

async function main() {
  console.log("🚀 TradeFlow AI — Turso DB Setup");
  console.log(`📡 Connecting to: ${url.replace(/\/\/.*?@/, "//***@")}\n`);

  let ok = 0, fail = 0;

  for (const sql of TABLES) {
    const label = sql.trim().split("\n")[0].replace("CREATE TABLE IF NOT EXISTS", "TABLE").replace("CREATE INDEX IF NOT EXISTS", "INDEX").trim();
    try {
      await db.execute(sql);
      console.log(`  ✅ ${label}`);
      ok++;
    } catch (err) {
      console.error(`  ❌ ${label}`);
      console.error(`     ${err.message}`);
      fail++;
    }
  }

  console.log(`\n📊 Done — ${ok} OK, ${fail} failed`);

  if (fail === 0) {
    console.log("\n✨ Database ready! Add these env vars to Vercel:");
    console.log("   TURSO_DB_URL=<your-libsql-url>");
    console.log("   TURSO_AUTH_TOKEN=<your-token>");
  }

  await db.close();
}

main().catch((err) => {
  console.error("Fatal:", err.message);
  process.exit(1);
});
