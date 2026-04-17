# TradeFlow AI — Self-Learning Log

> Aggiungere sempre una riga quando si risolve un bug. Formato: data | bug | causa radice | fix.

| Data | Bug | Causa radice | Fix applicato |
|---|---|---|---|
| 2026-03-31 | Prezzi XAU non caricavano | Yahoo Finance bloccato + FPMARKETS ticker fallito | Multi-ticker TV Scanner (9 alternative) |
| 2026-03-31 | Indicatori MACD errati (+31 vs -12) | GC=F futures ≠ spot OANDA:XAUUSD | MAI usare GC=F per prezzi live; Yahoo XAUUSD=X come fallback |
| 2026-03-31 | "No candle data" su tutti indicatori | Vercel IP blacklistato da Yahoo Finance | Candele H1 fetched lato browser in mfkk.js |
| 2026-03-31 | ADX = 0,0,0 | `ADX[10]\|60` colonna non valida → null → 0 | Usa `ADX\|60` (default 14) sempre |
| 2026-03-31 | CCI_S mostra "auto" | `step="1"` rifiutava valori decimali | `step="0.01"` su input HTML |
| 2026-03-31 | ADX RMA vs SMA divergenza | Usavamo Wilder RMA, custom TV usa SMA(DX,len) | Server-side calcolo SMA(DX,10) |
| 2026-04-13 | `quality is not defined` | ReferenceError in dashboard.js:565 | Definito qualityBg/Col in updateConfidence() |
| 2026-04-13 | Duplicate strategy logic | strategy.js broken syntax | Unificata logica MT5/Signal, rimosso codice ridondante |
| 2026-04-13 | CORS Calendar Fail | Proxy 3rd party instabili | Creato /api/market server-side proxy per ForexFactory |
| 2026-04-13 | G/S Ratio e Oil bloccati | Ticker mancanti in API unificata | Aggiunti XAG (SILVER) e fallback OIL nel Hub |
| 2026-04-13 | Calendario non caricava | `nfs.faireconomy.media` offline | Multi-source fallback (3 URL FF), slice=60, mapping completo |
| 2026-04-13 | Grafico TradingView schiacciato | Height fissa 600px | Aumentata a 800px container HTML + widget JS |
| 2026-04-14 | MFKK non in sezione Strategies | SE non leggeva dashContext.mfkk | Aggiunti S00_MFKK (score≥75) e S00_MFKK_HWR |
| 2026-04-14 | Confirm dialog bloccava MT5 | `confirm()` bloccante | Rimosso confirm(), aggiunto toast `seToast()` non-bloccante |
| 2026-04-14 | Bottone MT5 sempre abilitato offline | Nessun check stato bot | `seSendTradeToMt5` verifica syncAge<30s prima di inviare |
| 2026-04-14 | Segnali MFKK troppo frequenti | Soglia 68 quasi sempre soddisfatta | Soglia alzata a 75; zona 80-89 ottimale (WR 58.8%) |
| 2026-04-14 | Catalog strategie senza P&L | Mostrava solo PF e WR | Aggiunte colonne P&L 1M/12M/24M e MaxDD |
| 2026-04-14 | Backtest XAUUSD=X delisted Yahoo | HTTP 404 su tutti i chunk | Migrato a GC=F via yfinance per backtesting storico |
| 2026-04-14 | S13/S14 in rotation con P&L negativo | Priority basata su stime | Rimossi dopo backtest 730gg; sostituiti con S04_BB_SQUEEZE in RANGE |
| 2026-04-14 | `ReferenceError: online is not defined` | Variabile `online` usata ma nome corretto è `botOnline` | Rinominato `online` → `botOnline` in strategy.js |
| 2026-04-14 | Ordine MT5 fallisce `retcode=10027` | "AutoTrading disabled by client" | Non è bug — abilitare Algo Trading in MT5 toolbar (vedi 04_bot_operations.md) |
| 2026-04-14 | S00_MFKK_HWR non scattava mai | `seInds.adx` è fallback statico (25) sempre < 35 | Fix: legge `dashContext.mfkk.adx/dip/dim/macd` reali, con fallback a seInds |
| 2026-04-14 | Architettura strategie semplificata | Decisione utente: solo S00_MFKK e S00_MFKK_HWR | Rimosse S01/S04/S06/S09/S12/S13/S14 da UI, SE_STRATEGY_FNS, regimePriority |
| 2026-04-14 | mt5-bot.py aveva vecchie strategie | STRATEGY_PARAMS non sincronizzato con strategy.js | Aggiornati in mt5-bot.py per usare solo S00_MFKK + S00_MFKK_HWR |
| 2026-04-14 | Backtester usava solo yfinance GC=F | Nessun modo per usare dati broker reali MT5 | Creato fetch_mt5_history.py + flag --file in strategy-engine-v2.py |
| 2026-04-14 | Integrazione Ultimate RSI, Momentum, ICT Order Flow | Utente ha richiesto 3 indicatori TV | Tradotti in JS (S02/S03/S04) — logica mantenuta ma non mostrata in UI |
| 2026-04-14 | Refactoring UI Tab Strategie a 2 card | MFKK HighWR rimossa (3 trade in 24m PF 0.83) | Rimossi S01/S02/S03/S04/S00_MFKK_HWR da UI · S05 = V2 Triple MACD H1 |
| 2026-04-14 | Backtest MT5 GOLD — M30 vs H1 verifica | V2 Triple MACD H1 Score=4.149 vs M30 Score=~2.1 | Confermato H1 come TF ottimale per MFKK Intraday |
| 2026-04-14 | UI Strategie: aggiunto trades/day per periodo | Richiesta utente | Aggiunti td_1m/td_6m/td_12m/td_24m in SE.strategies.stats |
| 2026-04-14 | Bot MT5 offline dopo crash silenzioso | Processo zombie impediva nuova connessione MT5 | `taskkill /f /im python.exe` + reconnect automatico |
| 2026-04-14 | Sync Vercel mai aggiornato ("804m fa") | VERCEL_URL terminava con `/` → doppio slash → HTTP 404 | Rimosso slash finale da VERCEL_URL |
| 2026-04-14 | Bot online/offline a tratti in UI | Sync ogni 60s ma soglia UI < 30s → falsi negativi | Sync bot a 20s · soglia UI a 90s (`botOnline = syncAge < 90`) |
| 2026-04-14 | Bot non eseguiva ordini in autonomia | SIGNAL_FNS aveva strategie archiviate, non le attive | Riscritti signal_mfkk_score() e signal_mfkk_intraday() identici a strategy.js |
| 2026-04-14 | Storico trade vuoto in UI | `get_recent_trades_data()` leggeva file mai popolato | Riscritta per usare `mt5.history_deals_get()` direttamente |
| 2026-04-14 | Implementato Risk Manager adattivo | Feature richiesta: AI Score → lot/TP/SL/BE/TS | Creato `scripts/risk_manager.py` · 5 tier risk · integrato in mt5-bot.py |
| 2026-04-15 | Backtest aggiornato su dati MT5 reali (~6m) | `xauusd_h1_mt5.json` copre solo ~6 mesi | Aggiornato §5.2. Per 730gg usare `--mt5` con MT5 aperto |
| 2026-04-16 | Latency in Risk Manager e stats mancanti | `rm.manage_positions` aggiornata solo ogni 1 ora; S10 stats null | Spostata logica nel loop principale (10s); popolato SE.strategies con stats S10 |
| 2026-04-16 | `api/report.js` Anthropic fetch senza timeout | Nessun `fetchT` helper → Vercel hang | Aggiunto `fetchT` helper, timeout 9s |
| 2026-04-16 | `api/price.js` usava `GC=F` come fallback candele | GC=F futures ≠ spot → drift indicatori | Rimosso GC=F; solo XAUUSD=X per XAU |
| 2026-04-16 | Bot MT5 reconnect senza exponential backoff | Wait fisso 5s+30s → spam reconnect | Exponential backoff: 5s → 10s → 20s → ... max 300s |
| 2026-04-16 | CLAUDE.md mancava S10 e S16 | Strategie attive non documentate | Aggiornata sezione Active Strategies con tabella Bot MT5 separata da UI |
| 2026-04-16 | api/webhook.js: memCache senza TTL | Cache stale dopo assenza webhook | CACHE_TTL_MS = 5min + timestamp; fallback su GitHub |
| 2026-04-16 | api/webhook.js: nessuna firma TradingView | Fake segnali possibili | Aggiunta verifica opzionale X-TV-Secret vs env TV_WEBHOOK_SECRET |
| 2026-04-16 | mt5-bot.py: get_candles(300) ogni 10s | 360 chiamate/ora su dati invariati | Cache 60s: riesegue solo se new_ts - last_fetch >= 60 |
| 2026-04-16 | mt5-bot.py: compute_indicators() ogni 10s | CPU waste su dati invariati | cached_I_h1: ricalcolo solo su new_h1_bar |
| 2026-04-16 | strategy-engine-v2.py: S16 TP/SL errato in run_one() | run_one() usava ATR×2.0/1.5; run_adaptive() 3.0/1.2 | Allineato run_one() a 3.0/1.2 come in STRATEGY_PARAMS |
| 2026-04-16 | Backtest combinato Elite 4 + RM su MT5 reale | Prima esecuzione M30 vs H1 | M30 superiore: PF 1.203 vs 1.084; P&L +$6150 vs +$3072; DD $1502 vs $3622 |
| 2026-04-17 | Funzioni segnale duplicate tra mt5-bot.py e strategy-engine-v2.py | Divergenza silenziosa a ogni modifica | Creato scripts/signals.py come source of truth; entrambi i file importano da lì |
| 2026-04-17 | S16_GOLDEN_SQUEEZE in sessione asiatica | Bassa liquidità XAU 00:00-07:59 UTC → WR basso | Aggiunto SESSION_FILTER in mt5-bot.py: skip S16 in ore 0-7 UTC |
| 2026-04-17 | File JSON backtest sparsi nella root (27 file) | Nessuna struttura chiara per risultati vs dati | Creato backtests/results/, backtests/archive/, data/; aggiornati path in tutti gli script |
| 2026-04-17 | Bot sempre offline in UI + posizioni/storico vuoti | sync_to_vercel() gated da `rm and` → mai chiamata se RiskManager fallisce import | Spostata sync nel blocco 20s (indipendente da rm); AI score fetch rimane a 60s senza rm guard |
| 2026-04-17 | Sync Vercel falliva con SSL CERTIFICATE_VERIFY_FAILED | VPS Windows non aveva CA certificates configurati per Python urllib | Aggiunto _SSL_CTX module-level con certifi (fallback: skip verify); fix in sync_to_vercel, fetch_pending_command, RiskManager.fetch_ai_score |
