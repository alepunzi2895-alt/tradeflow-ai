# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TradeFlow AI is a XAU/USD trading PWA + Python MT5 automated bot. The frontend is **vanilla HTML/CSS/JS** (no framework), deployed on Vercel as serverless functions. A local Python process runs the MetaTrader 5 trading bot.

- **Production URL**: https://tradeflow-ai-delta.vercel.app/
- **Deploy**: `git push origin main` → Vercel auto-deploys in ~60s

## Commands

### Deploy
```bash
git add . && git commit -m "..." && git push origin main
```

### MT5 Bot (Windows only — MetaTrader5 Python lib is Windows-exclusive)
```bash
# Dry run — no real orders
python -X utf8 scripts/mt5-bot.py --dry-run

# Live on demo account
python -X utf8 scripts/mt5-bot.py

# Monitor log
Get-Content mt5-bot.log -Wait -Tail 20
```

### Backtesting
```bash
# Primary (MT5 must be open — uses real broker data for GOLD H1)
python scripts/backtest_mfkk_intraday.py --mt5

# Fallback with saved history
python scripts/backtest_mfkk_intraday.py --h1-file xauusd_h1_730d.json

# Full strategy engine v2
python scripts/strategy-engine-v2.py --file xauusd_h1_730d.json

# Fetch fresh MT5 history → xauusd_h1_mt5.json
python scripts/fetch_mt5_history.py
```

### DB utilities
```bash
node scripts/setup-turso.mjs
node scripts/patch-db.mjs
```

## Architecture

```
public/
  index.html     — shell HTML, loads scripts at bottom (no type="module")
  app.js         — init, tab routing, TradingView chart widget, profile overlay
  modules/
    core.js      — localStorage, fetchJSON, dashContext global (shared state)
    dashboard.js — live prices (TV Scanner → Yahoo fallback), AI Confidence Score, macro
    mfkk.js      — MFKK Strategy Score: CCI_S(50,50,8,8), MACD(12,26,9), ADX(10) indicators
    strategy.js  — Strategy Engine: regime detection, multi-strategy signals, MT5 command bridge
    chat.js      — Claude AI analysis, chart image upload
    journal.js   — trade log, coaching, reports
    myfxbook.js  — MyFxBook account sync
    kb.js        — Knowledge Base, GitHub sync

api/
  db.js          — Universal gateway: Turso DB CRUD, auth (JWT/bcrypt), KB (GitHub), MT5 sync
  price.js       — Fast XAU price + candle proxy (TV Scanner)
  analysis.js    — Market data hub: prices, MACD/ADX/CCI indicators, calendar, sentiment, COT
  chat.js        — Anthropic API proxy
  report.js      — AI coaching report via LLM
  webhook.js     — TradingView webhook receiver → stores indicators to GitHub + Turso

scripts/
  mt5-bot.py              — Main trading bot: H1 loop, regime detection, order execution
  risk_manager.py         — Adaptive risk: AI Score → lot/TP/SL/BreakEven/TrailingStop
  strategy-engine-v2.py   — Python backtester (canonical backtest source)
  backtest_mfkk_intraday.py — Dedicated MFKK + Intraday backtester
  fetch_mt5_history.py    — Downloads GOLD H1 from live MT5 → JSON

directives/
  tradeflow_ai_directive.md — Full directive layer — read this for all historical bugs/decisions
```

### Data flow

**Browser (strategy.js)** — `seRefresh()` every **1 second**:
1. `GET /api/price?type=candles` → compute H1 indicators browser-side
2. Read `dashContext.mfkk` (pre-computed by mfkk.js every 5s)
3. Detect regime + generate signals
4. `POST /api/db action=mt5_get` → fetch real MT5 account state
5. `seRender()` → **full innerHTML rebuild** of `#se-content`

**mfkk.js** — `loadIndicatorCandles()` every **60 seconds**:
- BROWSER: fetch Yahoo `XAUUSD=X` candles (60d range) for CCI_S + EMA + ATR
- SERVER (`/api/analysis?type=indicators`): TV Scanner for MACD + ADX (Vercel IP not blocked for Scanner)

**mt5-bot.py** — loop every **1 second**:
- `manage_positions()` → Break Even + Trailing Stop
- `fetch_remote_commands()` → `POST /api/db action=mt5_command_get`
- `sync_to_vercel()` every 20s → `POST /api/db action=mt5_push`
- On new H1 candle close → autonomous signal analysis + order placement

## Required Environment Variables (Vercel)

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API |
| `TURSO_DB_URL` | Turso DB (format: `libsql://...`) |
| `TURSO_AUTH_TOKEN` | Turso auth |
| `JWT_SECRET` | User auth token signing |
| `GITHUB_TOKEN` | Read+write for KB and COT data |
| `GITHUB_OWNER` | GitHub username |
| `GITHUB_REPO` | GitHub repo name |
| `MT5_BOT_SECRET` | Shared secret for MT5 bot sync |

## Active Strategies

Backtest 2026-04-16 · MT5 GOLD H1 730gg · RM sempre attivo

### Bot MT5 (STRATEGY_PARAMS in mt5-bot.py)

| ID | Label | TF | TP mult | SL mult | Regime |
|---|---|---|---|---|---|
| `S05_MFKK_INTRADAY` | MFKK Intraday V3 | H1 | ATR×2.0 | ATR×1.0 | TREND_UP, TREND_DOWN |
| `S09_MFKK_SCALPING` | MFKK Scalping V2 | M5 | ATR×3.0 | ATR×1.0 | VOLATILE, WEAK |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V2 | M15/M30 | ATR×2.5 | ATR×1.2 | Tutti i regimi (fallback) |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V2 | M30 | ATR×3.0 | ATR×1.2 | TREND_UP, TREND_DOWN, WEAK |

BE trigger per S16: +ATR×1.1 dal prezzo entry.

### Frontend UI (strategy.js — backtest stats storici)

| ID | Label | WR | PF | Trade/gg | TP / SL | P&L 24m |
|---|---|---|---|---|---|---|
| `S00_MFKK` | MFKK Score | 41% | 1.16 | 3.7 | $20 / $12 | +$3052 |
| `S05_MFKK_INTRADAY` | MFKK Intraday V2 | 36.9% | 1.23 | 3.3 | ATR×1.5 / ATR×1 | +$4776 |
| `S09_MFKK_SCALPING` | MFKK Scalping | 40.7% | 1.62 | 0.11 | ATR×1.5 / ATR×1 | +$2954 |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp | 41.3% | 1.43 | ~0.5 | ATR×2.5 / ATR×1.2 | — |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze | 53.0% | 1.45 | ~0.3 | ATR×3.0 / ATR×1.2 | — |

Soglie MFKK Score: `BUY≥85` / `SELL≥70` (era 90/75).
S05_MFKK_INTRADAY usa V2 Triple MACD (OBV T-Channel + RSI50 + MACD + Momentum, ADX≥20, buy+sell).

Archived strategies (logic kept in code, hidden from UI): S00_MFKK_HWR, S01_OBV_MACD, S02_ULTIMATE_RSI, S03_MOMENTUM, S04_ICT_ORDERFLOW, S04_BB_SQUEEZE, S05_V3_Sell_Exhaust, S01_EXHAUSTION, S06_ORDERBLOCK, S12_WPR_KELTNER, S13_STRUC_BREAK, S14_KEY_LEVELS.

## Critical Rules

### Price data sources
- **Live XAU price**: TradingView Scanner only (`scanner.tradingview.com/global/scan`)
- **Ticker fallback order**: `OANDA:XAUUSD` → `FOREXCOM:XAUUSD` → `TVC:GOLD`
- **NEVER use `GC=F`** for live prices (Gold Futures ≠ spot — variable spread). `GC=F` is only acceptable in backtesting Python scripts.
- **Yahoo fallback for live**: `XAUUSD=X` only, not `GC=F` or `GLD`
- **Candles for indicators**: fetched browser-side in `mfkk.js` (Vercel IPs are blacklisted by Yahoo Finance and `data.tradingview.com`)

### TV Scanner column format (H1 timeframe)
```
MACD.macd|60   MACD.signal|60   MACD.hist|60
ADX|60         plus_di|60       minus_di|60
CCI[50]|60
```
**Never use `ADX[10]|60`** — custom period returns `null` → treated as 0.

### Indicator parameters (must match Pine Script source)
- **CCI_S**: CCI=50, Stoch=50, K=8, D=8, OB=75, OS=25
- **MACD**: fast=12, slow=26, signal=9 (EMA)
- **ADX custom**: uses `SMA(DX, 10)` — **not** Wilder RMA. TV Scanner default (14 RMA) will diverge.

### DOM / JS rules
- `seRender()` rebuilds **all of `#se-content`** every 1s — never save DOM references to child elements; they become stale within 1s
- The `#se-toast` element is appended to `document.body`, not inside `#se-content`, so it survives refreshes
- `onclick` attributes with `JSON.stringify`: apostrophes in Italian strings (e.g. `dall'ADX`) break `onclick` silently. Use `encodeURIComponent` or `data-*` + `addEventListener` instead
- Scripts are loaded as regular `<script src="...">` (no `type="module"`), so `event?.target` works globally

### Vercel serverless constraints
- Max execution time: **10s** — all `fetch` calls must use AbortController with 8s timeout
- Required pattern for every server-side fetch:
```javascript
async function fetchT(url, opts={}, ms=8000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try { const r = await fetch(url, {...opts, signal: ctrl.signal}); clearTimeout(tid); return r; }
  catch(e) { clearTimeout(tid); throw e; }
}
```

### Adding a new strategy
1. Define ID (`S0X_NAME`), write signal function in `SE_STRATEGY_FNS` inside `strategy.js`
2. Add entry in `SE.strategies` with backtest stats
3. Add to `regimePriority` map
4. Add to `STRATEGY_PARAMS` and `REGIME_PRIORITY` in `mt5-bot.py` to keep both in sync
5. Run backtest with `--mt5` flag before activating — minimum 6 months H1 data required
6. Update `directives/tradeflow_ai_directive.md` (Self-Learning Log §6 + §5.2)

### Backtest source of truth
Results from `backtest_mfkk_intraday.py --mt5` (real broker GOLD data) are canonical. Stats in `SE.strategies` must reflect the latest MT5 run.

## Backtest Results — MFKK AI Gold Bot (2026-04-16)

Dati: MT5 reale GOLD · 730gg (2024-04-15 → 2026-04-16) · lotto 0.01 · $1/punto

### Sistema Adattivo (Regime-based, senza RM)

| TF | Trade | WR% | P&L | PF | DD | Mesi+ |
|---|---|---|---|---|---|---|
| **H1** | 2505 | 31.3% | +$2,241 | 1.084 | $2,529 | 13/25 |
| **M30** | 3390 | 31.9% | +$4,915 | **1.203** | **$960** | 14/25 |

### Sistema Adattivo + Risk Manager (lot scaling da AI Score)

| TF | Trade | WR% | P&L | PF | DD | $/gg |
|---|---|---|---|---|---|---|
| **H1** | 2505 | 31.3% | +$3,072 | 1.089 | $3,622 | +$7.70 |
| **M30** | 3390 | 31.9% | +$6,150 | 1.202 | $1,502 | **+$12.66** |

### Breakdown M30 per strategia (con RM)

| Strategia | Trade | WR% | P&L |
|---|---|---|---|
| S16_GOLDEN_SQUEEZE | 2547 | 30.0% | +$3,910 |
| S05_MFKK_INTRADAY | 423 | 38.5% | +$892 |
| S09_MFKK_SCALPING | 336 | 35.1% | +$608 |
| S10_OB_FVG_SCALP | 84 | 44.0% | +$739 |

### Raccomandazioni dal backtest

- **M30 è nettamente superiore a H1** (P&L 2.2×, DD 2.6× minore, tutte le strategie positive)
- **RM lot scaling aggiunge +25% P&L** su M30 senza degradare WR o PF
- Il bot dovrebbe usare M30 come timeframe primario (aggiornare FALLBACK_PLAYBOOK in mt5-bot.py)
- S16 è il driver principale (75% dei trade): le altre strategie sono complementari e positive
- Trade frequency su M30: 7/gg — accettabile con regime filter attivo
- Tier distribution su M30 più equilibrata (MAX 35% vs H1 42%) — AI Score ben calibrato

## Known Issues & Architectural Notes

### Confirmed bugs (as of 2026-04-16)

| Severity | File | Issue | Status |
|---|---|---|---|
| ✅ Fixed | `api/report.js` | Anthropic fetch had no timeout → Vercel hang | Fixed: added `fetchT` 9s timeout |
| ✅ Fixed | `api/price.js` | `GC=F` in candles fallback violated spec | Fixed: removed, only `XAUUSD=X` |
| ✅ Fixed | `scripts/mt5-bot.py` | Flat 30s reconnect wait, no backoff | Fixed: exponential backoff 5→10→20…→300s |
| ⚠ Open | `api/webhook.js` | `memCache` has no TTL — stale indicators served forever | Add 5-min expiry |
| ⚠ Open | `api/webhook.js` | No HMAC signature check on TradingView POST | Add `X-TV-Secret` header verification |
| ⚠ Open | `public/app.js` | `onclick` button bindings (lines 160-172) fail silently if element missing | Use `wire()` for all bindings |
| ⚠ Open | `api/db.js` | Turso `createClient()` has no explicit timeout — relies on Vercel 10s kill | Low risk, monitor |

### Bot performance bottlenecks

1. **`get_candles(300)` called every loop tick (every ~10s)** — fetches 300 bars even when no new H1 bar has opened. Fix: cache last bar timestamp, skip fetch if no new bar expected.
2. **`compute_indicators()` runs every 10s** — all indicators recomputed on same data. Fix: only recompute on new H1 candle close (once per hour for H1 strategies).
3. **`_pos_state` dict in RiskManager never cleaned up** — grows unbounded if bot runs for months. Fix: prune closed tickets periodically.
4. **Signal functions duplicated** between `mt5-bot.py` and `strategy-engine-v2.py` — diverge silently when one is updated. Fix: extract to `scripts/signals.py`.

### Strategy/timeframe consistency

- Frontend `strategy.js` detects regime and shows signals without timeframe context
- Bot applies strategies on different TFs (M5 for S09, M30 for S16, H1 for S05)
- This is expected — frontend is for human guidance, bot uses its own regime+TF logic
- **Do not add timeframe filtering to the frontend signal engine** unless explicitly requested
