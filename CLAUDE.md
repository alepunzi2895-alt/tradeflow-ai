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

# Setup one-time (dopo ogni git clone) — pre-commit AI review hook
python scripts/install_git_hooks.py

# Export verso vault Obsidian (secondo cervello) — richiede OBSIDIAN_VAULT_PATH in .env locale
python scripts/obsidian_export.py --dry-run   # anteprima, non tocca il vault
python scripts/obsidian_export.py             # scrive/aggiorna le note
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
| AI review agents (diagnosi anomalie, pre-commit review) | `directives/09_ai_review_agents.md` |
| Curriculum di trading (ECABS Basic+Intermediate) + gap vs app | `directives/10_trading_education.md` |

## Regole Critiche (leggere prima di ogni modifica)

**TV Scanner**: usare `ADX|60` (NON `ADX[10]|60` — custom period restituisce null → 0).

**Prezzi XAU**: MAI usare `GC=F` per prezzi live (futures ≠ spot). Solo `XAUUSD=X` per Yahoo fallback.

**seRender DOM**: `seRender()` ricostruisce TUTTO `#se-content` ogni 1s. MAI salvare riferimenti DOM a elementi figli — diventano stale entro 1s.

**fetchT pattern**: ogni fetch server-side in `api/*.js` DEVE usare `fetchT()` con timeout 8s (limite Vercel 10s).

**onclick + apostrofi**: `JSON.stringify()` non escapa apostrofi italiani (es. `dall'ADX`) → onclick si rompe silenziosamente. Usare `data-*` + `addEventListener`.

**Script load order**: `se-signals.js` → `strategy.js` → `se-render.js` (no ES modules, tutto globale).

**signals.py**: funzioni segnale unificate in `scripts/signals.py`. MAI duplicare logica in mt5-bot.py o strategy-engine-v2.py — importare sempre da lì.

**ai_review pattern**: ogni chiamata Python a Claude DEVE passare da `scripts/ai_review.py` (`call_claude()`/`call_claude_json()`) — mai `requests.post` diretto duplicato nei singoli script.

## Architettura Rapida

```
public/instruments.json — REGISTRO STRUMENTI (XAU/XAG/US30 core + forex major + indici): unica fonte per UI (modules/instruments.js), API (lib/instruments.js: quotazioni, candele, indicatori, nome MyFxBook) e script Python. Aggiungere uno strumento = una voce qui (ticker 'quotes' da verificare sullo scanner TradingView, 'mt5' sul terminale). core=false → niente MFKK/confidence (avviso esplicito), asset sconosciuto → 400, mai fallback sui ticker dell'oro

public/modules/
  se-signals.js      — indicator helpers + SE_STRATEGY_FNS (browser)
  strategy.js        — SE config, seRefresh(), loop 1s
  se-render.js       — seRender(), seRenderNoData()
  dashboard.js       — dashboard + hero "Orbite strategie" (renderOrbitHero(): nucleo/pianeti = roster SE.strategies per PF reale, equity da mt5_get)
  backtest-report.js — pannello Report Backtest + dettaglio "Genoma" per strategia (gnOpen()/gnScore(): confidenza derivata da PF full/holdout/regime, bootstrap resample client-side — non Sharpe/DSR accademico)
  hive.js            — "The Hive": nebulosa del roster (nodi = SE.strategies, link = regimi condivisi) + knowledge tiles (kb.js) + stato roster (brData)

scripts/
  signals.py         — funzioni segnale unificate (source of truth)
  mt5-bot.py         — bot trading, integra StrategySelector + RiskGuardian
  strategy_selector.py — Strategy Selector Agent: regime scoring → best strategy+TF
  risk_guardian.py   — Risk Guardian Agent: composite score → tier → lot/TP/SL + position lifecycle
  risk_manager.py    — Legacy (backward compat, non usato direttamente)
  strategy-engine-v2.py — backtester, importa da signals.py
  daily_maintenance.py  — job giornaliero: fetch + backtest + drift + trade silence + AI review
  ai_review.py       — client condiviso per chiamate Claude (Python)
  review_diff.py      — pre-commit AI code review (signals.py/mt5-bot.py/risk_guardian.py)
  install_git_hooks.py — setup one-time hook pre-commit
  obsidian_export.py  — export locale → vault Obsidian (secondo cervello): Journal/Genomi/Knowledge/AI-Log come .md con frontmatter + [[wikilink]]. Legge via /api/db (stesso pattern HTTP di mt5-bot.py/daily_maintenance.py, MAI da api/*.js — Vercel è read-only su disco). Score "Genoma" replica gnScore() di backtest-report.js, tenerli allineati. Config: OBSIDIAN_VAULT_PATH + OBSIDIAN_USER_ID in .env locale (mai su Vercel)
  opt_harness.py     — fitness condivisa per sprint ottimizzazione: evaluate/is_promotable/dsr_check/pbo_check
  research_trials.py — registro cumulativo trial di ricerca (data/research_trials.json) — SEMPRE usarlo per num_trials in dsr_check, mai un numero a mano
  macro-score.js (public/modules/) — punteggio tecnico (RSI+trend, storico Yahoo via api/price.js) per le quotazioni macro non tradate dall'app (VIX/SPX/NDX/RUT/OIL/US10Y/US02Y), click dalla griglia Quotazioni — diverso dallo Score Confidenza MFKK di XAU/XAG/US30, mai confonderli. VIX riusato come proxy di sentiment (non esiste sentiment retail per questi strumenti)
  paper_trade_s16.py — paper trader S16_GOLDEN_SQUEEZE (bloccata dal 2026-09-17, passa full/holdout/segmenti/cost-stress ma fallisce il gate DSR nell'audit 2026-09-18) — replica fedele di strategy-engine-v2.py::run_one() (stesso compute_all/simulate_exit/TP-SL/costi) su candele H1 live via MT5, nessun ordine reale. Stato: data/s16_paper_trades.json. Obiettivo: evidenza forward vera, l'unica cosa che un fallimento DSR può risolvere (altro backtest sugli stessi dati aumenta solo num_trials)
  extra_indicators.py — 18 indicatori extra (Ichimoku, PSAR, MFI, ecc.); trix/choppiness_index/mfi promossi al path live (compute_all/compute_indicators), gli altri 15 restano research-only
  feature_screen.py  — ML feature screening (RandomForest + permutation importance) per generare ipotesi di nuove strategie, vedi directives/02_strategies.md
  layout_indicators.py — indicatori dei 5 layout TradingView XAU. SOURCE OF TRUTH condivisa compute_all↔compute_indicators. Default→S31 (Trendlines-with-Breaks LuxAlgo, Pivot Fibonacci, Key Levels SpacemanBTC, EMA200, sessioni); XAU_M30→S33 (Ultimate RSI LuxAlgo, Momentum); XAU_H1_Volumes→S34 (CVD proxy, Volume Profile POC/VAH/VAL rolling+sessione, Normalized Volume)
  layout_smart.py    — backtest S31_LAYOUT_SMART (break→retest→confluenza, H1). evaluate_ls_frozen = config di produzione. layout_features.py/layout_ml.py/layout_sim.py = research (ML classifier + exit sim)
  layout_s3x.py      — backtest S32/S33/S34 (score dei layout XAU_M15/M30/H1_Volumes). evaluate_s3x gira signals.s3?_scan/_manage_step. `system={}` = test col sistema completo (confidence + circuit breaker + sizing). VERDETTO: nessuna promuovibile (PBO 0.80-1.00 anche col sistema) → solo confidence score in dashboard, il bot non apre ordini
  market_structure.py — swing HH/HL/LH/LL + BOS (continuazione) / CHoCH (inversione), causale. Gap G1 di directives/10_trading_education.md
  layout_confidence.py — confidence 0-100 per setup dai fattori del curriculum ECABS (MTF bias, BOS/CHoCH, oscillatore, premium/discount, sessione, candela, regime, news-proxy). Pesi FISSI non tunati. Usato da mt5-bot._layout_confidence_live (dashboard) e layout_s3x (test)

data/             — xauusd_*.json (price history)
backtests/        — results/ + archive/
```

## Environment Variables (Vercel)

`ANTHROPIC_API_KEY` · `TURSO_DB_URL` · `TURSO_AUTH_TOKEN` · `JWT_SECRET` · `GITHUB_TOKEN` · `GITHUB_OWNER` · `GITHUB_REPO` · `MT5_BOT_SECRET`
