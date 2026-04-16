# TradeFlow AI

XAU/USD trading PWA + Python MT5 automated bot.

- **Production**: https://tradeflow-ai-delta.vercel.app/
- **Stack**: Vanilla HTML/CSS/JS frontend · Vercel serverless API · Python MT5 bot · Turso DB

## Structure

```
public/
  index.html         — shell HTML (no inline CSS/JS)
  styles.css         — all styles
  app.js             — init, tab routing, TradingView widget, profile overlay
  modules/
    core.js          — localStorage, fetchJSON, dashContext global (shared state)
    dashboard.js     — live prices (TV Scanner → Yahoo), AI Confidence Score, macro
    mfkk.js          — MFKK Strategy Score: CCI_S(50,50,8,8), MACD(12,26,9), ADX(10)
    strategy.js      — Strategy Engine: regime detection, multi-strategy signals, MT5 bridge
    chat.js          — Claude AI analysis, chart image upload
    journal.js       — trade log, AI coaching, reports
    myfxbook.js      — MyFxBook account sync
    kb.js            — Knowledge Base, GitHub sync

api/
  db.js              — Universal gateway: Turso CRUD, auth (JWT/bcrypt), KB (GitHub), MT5 sync
  price.js           — Fast XAU price + candle proxy (TV Scanner → Yahoo)
  analysis.js        — Market data hub: indicators MACD/ADX/CCI, calendar, sentiment, COT
  chat.js            — Anthropic API proxy
  report.js          — AI coaching report via LLM
  webhook.js         — TradingView webhook receiver → GitHub + Turso

scripts/
  mt5-bot.py              — Main trading bot: H1/M5/M15/M30 loop, regime detection, order execution
  risk_manager.py         — Adaptive risk: AI Score → lot/TP/SL/BreakEven/TrailingStop
  strategy-engine-v2.py   — Python backtester (canonical backtest source)
  backtest_mfkk_intraday.py — Dedicated MFKK + Intraday backtester
  fetch_mt5_history.py    — Downloads GOLD H1 from live MT5 → JSON

directives/
  tradeflow_ai_directive.md — Full directive layer: historical bugs, design decisions, self-learning log
```

## Deploy

```bash
git add . && git commit -m "..." && git push origin main
```

Vercel auto-deploys in ~60s.

## MT5 Bot (Windows only)

```bash
# Dry run — no real orders
python -X utf8 scripts/mt5-bot.py --dry-run

# Live on demo account
python -X utf8 scripts/mt5-bot.py

# Monitor log
Get-Content mt5-bot.log -Wait -Tail 20
```

## Backtesting

```bash
# Primary (MT5 must be open — real broker GOLD H1 data)
python scripts/backtest_mfkk_intraday.py --mt5

# Fallback with saved history
python scripts/backtest_mfkk_intraday.py --h1-file xauusd_h1_730d.json

# Full strategy engine
python scripts/strategy-engine-v2.py --file xauusd_h1_730d.json

# Fetch fresh MT5 history → xauusd_h1_mt5.json
python scripts/fetch_mt5_history.py
```

## Active Strategies (Bot)

| ID | Label | TF | Regime |
|---|---|---|---|
| `S05_MFKK_INTRADAY` | MFKK Intraday V3 | H1 | TREND |
| `S09_MFKK_SCALPING` | MFKK Scalping V2 | M5 | VOLATILE |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V2 | M15/M30 | All (fallback) |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V2 | M30 | TREND + WEAK |

## Env vars (Vercel)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API |
| `TURSO_DB_URL` | Turso DB (`libsql://...`) |
| `TURSO_AUTH_TOKEN` | Turso auth |
| `JWT_SECRET` | User auth token signing |
| `GITHUB_TOKEN` | Read+write for KB and COT data |
| `GITHUB_OWNER` | GitHub username |
| `GITHUB_REPO` | GitHub repo name |
| `MT5_BOT_SECRET` | Shared secret for MT5 bot sync |
