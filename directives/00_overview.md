# TradeFlow AI — Overview & Architecture

## Identità del Progetto

**TradeFlow AI** è una PWA mobile-first per trader XAU/USD (oro spot).

| Attributo | Valore |
|---|---|
| **URL produzione** | https://tradeflow-ai-delta.vercel.app/ |
| **Repository** | https://github.com/alepunzi2895-alt/tradeflow-ai |
| **Deploy** | Vercel (auto-deploy su push a `main`) |
| **Stack frontend** | HTML/CSS/JS vanilla, no framework |
| **Stack backend** | Node.js serverless (Vercel Functions) |
| **DB** | Turso (libSQL) — credenziali in env Vercel |
| **Bot trading** | Python locale (`scripts/mt5-bot.py`) → MetaTrader 5 |

## Architettura

```
public/
  index.html     — UI principale, struttura tab, script caricati in fondo
  app.js         — init, tab routing, overlays, profilo utente
  modules/
    core.js      — storage locale, fetchJSON, API helpers, dashContext globale
    dashboard.js — prezzi live, AI Confidence Score (10 fattori), sentiment, macro
    mfkk.js      — MFKK Strategy Score (CCI_S, MACD, ADX)
    strategy.js  — Strategy Engine: regime detection, segnali multi-strategia, render UI, bridge MT5
    se-signals.js — indicator helpers + SE_STRATEGY_FNS (estratto da strategy.js)
    se-render.js — seRender() + seRenderNoData() (estratto da strategy.js)
    chat.js      — AI analysis via Claude API, upload immagini grafici
    journal.js   — trade log, coaching AI, reports
    myfxbook.js  — account sync MyFxBook
    kb.js        — Knowledge Base, upload documenti, search

api/
  price.js      — endpoint prezzi live XAU/USD (TV Scanner multi-ticker) + proxy candele
  analysis.js   — SUPER HUB: prezzi, indicatori MACD/ADX/CCI, calendario, sentiment, COT
  db.js         — Gateway universale Turso DB: auth, trades, mt5_push/get, comandi, KB
  report.js     — Report AI giornaliero via LLM
  webhook.js    — Ricezione trades e notifiche push

scripts/
  mt5-bot.py              — Bot trading Python: loop 1s, due agenti AI integrati
  strategy_selector.py   — [NUOVO] Strategy Selector Agent: regime scoring + selezione dinamica
  risk_guardian.py       — [NUOVO] Risk Guardian Agent: composite confidence + position management
  risk_manager.py        — Legacy risk manager (mantenuto per backward compat, non usato direttamente)
  signals.py             — Funzioni segnale unificate (importate da bot + backtester)
  fetch_mt5_history.py   — Scarica GOLD da MT5 → data/xauusd_*.json
  strategy-engine-v2.py — Backtester Python principale
  backtest_mfkk_intraday.py — Backtester dedicato MFKK

data/                     — Price data JSON (xauusd_h1_mt5.json, etc.)
backtests/
  results/               — Risultati backtest per TF
  archive/               — Risultati storici

directives/               — Documentazione progetto
```

## Flusso Dati Globale

```
Browser (strategy.js) — seRefresh() ogni 1s:
  1. GET /api/price?type=candles → calcola indicatori H1 browser-side
  2. legge dashContext.mfkk (da mfkk.js, ogni 5s)
  3. rileva regime + segnali
  4. POST /api/db action=mt5_get → dati account reali MT5
  5. seRender() → rebuild completo #se-content

mt5-bot.py — loop ogni 1s:
  manage_positions()          → RiskGuardian: BE + TS + early exit + regime shift
  fetch_remote_commands()     → POST /api/db action=mt5_command_get
  sync_to_vercel() (ogni 20s) → POST /api/db action=mt5_push
  Su nuova candela H1 chiusa:
    StrategySelector.select() → regime scoring → sceglie strategy + TF
    signal_fn()               → genera segnale (buy/sell) per la strategia scelta
    RiskGuardian.get_order_params() → composite score → tier → lot/TP/SL/BE/TS
    place_order()             → esegue ordine su MT5
    RiskGuardian.register_position() → avvia tracking lifecycle posizione
```

## Protocollo Autoapprendimento (obbligatorio)

Prima di ogni intervento:
1. Leggere il file coinvolto (MAI modificare codice non letto)
2. Cercare in `directives/07_self_learning_log.md` se il bug è già noto
3. Controllare `directives/08_dev_rules.md` per evitare regressioni note

Dopo ogni correzione:
1. Aggiungere riga nel self-learning log con: data, bug, causa radice, fix
2. Se cambia un'API, aggiornare `directives/01_data_sources.md`
3. Se cambia la logica bot, aggiornare `directives/04_bot_operations.md`

## Sistema Interattivo

- Ogni indicatore nel dashboard è cliccabile → modal glassmorphism con spiegazione contestuale
- `api/analysis.js` è il singolo hub per dati macro, calendario, sentiment, COT, indicatori
- Resilienza: timeout rigidi + fallback silenziosi per ogni fonte dati
