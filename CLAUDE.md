# CLAUDE.md

TradeFlow AI — XAU/USD trading PWA + Python MT5 bot. Frontend vanilla HTML/CSS/JS (no framework), Vercel serverless, local Python process for MetaTrader 5.

- **Production**: https://tradeflow-ai-delta.vercel.app/
- **Deploy**: `git push origin main` → Vercel ~60s

## Quickstart

```bash
# Deploy
git add . && git commit -m "..." && git push origin main

# Bot MT5 (Windows only)
python -X utf8 scripts/mt5-bot.py --dry-run   # dry run
python -X utf8 scripts/mt5-bot.py             # live

# Backtest canonico (MT5 aperto)
python scripts/backtest_mfkk_intraday.py --mt5
python scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json --rm

# Fetch dati freschi
python scripts/fetch_mt5_history.py --tf M30  # → data/xauusd_m30_mt5.json
```

## Dove Trovare Cosa

| Topic | File |
|---|---|
| Architettura, stack, flusso dati | `directives/00_overview.md` |
| Prezzi, TV Scanner, Yahoo, parametri MFKK | `directives/01_data_sources.md` |
| Strategie attive, backtest, regime priority | `directives/02_strategies.md` |
| Risk Guardian, composite score, tier, BE/TS/early-exit | `directives/03_risk_manager.md` |
| Bot MT5, comandi, retcode, checklist deploy | `directives/04_bot_operations.md` |
| Procedure backtest, risultati canonici | `directives/05_backtest.md` |
| Bug aperti, backlog | `directives/06_known_issues.md` |
| Self-learning log (bug storici e fix) | `directives/07_self_learning_log.md` |
| DOM rules, Vercel constraints, JS gotcha | `directives/08_dev_rules.md` |

## Regole Critiche (leggere prima di ogni modifica)

**TV Scanner**: usare `ADX|60` (NON `ADX[10]|60` — custom period restituisce null → 0).

**Prezzi XAU**: MAI usare `GC=F` per prezzi live (futures ≠ spot). Solo `XAUUSD=X` per Yahoo fallback.

**seRender DOM**: `seRender()` ricostruisce TUTTO `#se-content` ogni 1s. MAI salvare riferimenti DOM a elementi figli — diventano stale entro 1s.

**fetchT pattern**: ogni fetch server-side in `api/*.js` DEVE usare `fetchT()` con timeout 8s (limite Vercel 10s).

**onclick + apostrofi**: `JSON.stringify()` non escapa apostrofi italiani (es. `dall'ADX`) → onclick si rompe silenziosamente. Usare `data-*` + `addEventListener`.

**Script load order**: `se-signals.js` → `strategy.js` → `se-render.js` (no ES modules, tutto globale).

**signals.py**: funzioni segnale unificate in `scripts/signals.py`. MAI duplicare logica in mt5-bot.py o strategy-engine-v2.py — importare sempre da lì.

## Architettura Rapida

```
public/modules/
  se-signals.js      — indicator helpers + SE_STRATEGY_FNS (browser)
  strategy.js        — SE config, seRefresh(), loop 1s
  se-render.js       — seRender(), seRenderNoData()

scripts/
  signals.py         — funzioni segnale unificate (source of truth)
  mt5-bot.py         — bot trading, integra StrategySelector + RiskGuardian
  strategy_selector.py — Strategy Selector Agent: regime scoring → best strategy+TF
  risk_guardian.py   — Risk Guardian Agent: composite score → tier → lot/TP/SL + position lifecycle
  risk_manager.py    — Legacy (backward compat, non usato direttamente)
  strategy-engine-v2.py — backtester, importa da signals.py

data/             — xauusd_*.json (price history)
backtests/        — results/ + archive/
```

## Environment Variables (Vercel)

`ANTHROPIC_API_KEY` · `TURSO_DB_URL` · `TURSO_AUTH_TOKEN` · `JWT_SECRET` · `GITHUB_TOKEN` · `GITHUB_OWNER` · `GITHUB_REPO` · `MT5_BOT_SECRET`
