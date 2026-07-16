# TradeFlow AI — Known Issues & Backlog

## Bug Aperti

| Severity | File | Issue |
|---|---|---|
| 🔴 Fix pronto (non ancora deployato) 2026-07-16 | `scripts/mt5-bot.py` | **Bot fermo da trade dal 2026-07-10 — `_strategy_order_tickets` si blocca a `MAX_OPEN_ORDERS`**: stessa causa radice del comment troncato (vedi riga sotto), ma qui colpisce il cleanup in-memory invece del PerformanceTracker. Alla chiusura di una posizione, `strategy_closed` viene derivato dal comment MT5 troncato (es. `S18_RANGE_` invece di `S18_RANGE_REVERSAL`) e usato per `_strategy_order_tickets.pop(strategy_closed, None)` — la chiave piena non matcha mai quella troncata, il `pop` fallisce silenziosamente e l'entry resta agganciata per sempre. `count_open_positions()` = `max(mt5_count, len(_strategy_order_tickets))` continua a crescere/non scendere mai sotto 2 stale entries → tutti i blocchi segnale (H1/M15/M30/H4) controllano `count_open_positions() >= MAX_OPEN_ORDERS` **prima** di chiamare `has_open_position_for_strategy()` (l'unico punto che si auto-ripara) → deadlock permanente, zero nuovi ordini su tutte le strategie. Confermato in diretta 2026-07-16: `/api/db mt5_get` mostra `positions: []` (0 posizioni reali) ma `bot_status.open_positions: 2` (stale in-memory). Stesso bug secondario su `_strategy_sl_count`/`sl_cooldowns_until`, scritti con la chiave troncata e letti con quella piena → cooldown SL per-strategia mai attivo. **Fix**: risolve `strategy_closed` per ticket-match contro `_strategy_order_tickets` (fonte piena, non ambigua) invece che dal comment troncato, prima del pop. **Serve comunque un restart del bot sulla VPS** per sbloccare lo stato attuale, anche a prescindere dal deploy del fix (il dict in-memory va svuotato). |
| ✅ Fixed 2026-07-09 | `scripts/daily_maintenance.py`, `scripts/performance_tracker.py` | ~~6× AI-Flagged TRADE_SILENCE (S00/S05/S09/S10/S16/S17)~~ **falso positivo confermato**: `check_trade_silence()` leggeva `mt5-trades.json` locale, dimostratosi inaffidabile (ultimo trade 2026-06-04 vs realtà 2026-07-07). Causa radice reale, più seria: il broker tronca il campo `comment` degli ordini MT5 (es. `S16_GOLDEN_SQUEEZE`→`S16_GOLDEN`), e `performance_tracker.py::_parse_strategy_from_comment()` faceva match esatto → ogni trade di ogni strategia con nome >~10 char veniva scartato in silenzio dal self-learning tracker (solo S00_MFKK, 8 char, sopravviveva). Vedi 07_self_learning_log.md 2026-07-09 per il fix (matching per prefisso) e i dettagli. |
| ⚠ Open | `api/webhook.js` | `memCache` senza cleanup globale — stale indicators dopo restart Vercel |
| ⚠ Open | `api/webhook.js` | `X-TV-Secret` check opzionale — attivare `TV_WEBHOOK_SECRET` in env Vercel per protezione completa |
| ⚠ Open | `public/app.js` | `onclick` button bindings (~lines 160-172) falliscono silenziosamente se elemento assente; usare `wire()` pattern |
| ⚠ Open | `api/db.js` | `createClient()` Turso senza timeout esplicito — dipende da kill Vercel a 10s. Low risk |
| ✅ Fixed 2026-04-28 | `scripts/mt5-bot.py` | Race condition `has_position_in_direction()`: MT5 non registrava posizione prima del check successivo → doppio SELL aperto simultaneamente. Fix: `_strategy_order_tickets` ora salva `(ticket, direction)`, check in-memory first. `MAX_OPEN_ORDERS` 3→2. |
| ✅ Fixed 2026-04-28 | `scripts/news_guardian.py` | **TypeError silenzioso**: `now_utc` tz-aware - `evt_dt` tz-naive → TypeError catturato dall'outer try-except → News Guardian sempre `paused=False` anche con news HIGH USD attive. Fix: `now_utc.replace(tzinfo=None)` in `check_news_risk()`. Polling ridotto 900s→60s. |
| ✅ Fixed 2026-05-12 | `scripts/mt5-bot.py` | **`has_position_in_direction()` mai usata**: funzione definita il 2026-04-28 ma mai chiamata nei blocchi segnale → due strategie diverse aprivano nella stessa direzione simultaneamente. Fix: guard aggiunto in tutti i 6 blocchi (H1, H1sec, live scan, M15, M30, H4). |
| ✅ Fixed 2026-05-12 | `scripts/mt5-bot.py` | **`STRATEGY_PARAMS` sl_mult divergeva da `risk_guardian.py`**: sl_mult=1.0 per S05/S09/S10/S17/S00 mentre STRATEGY_ATR_PARAMS aveva 1.5 → SL troppo stretto se RiskGuardian offline. Fix: allineati a 1.5 per tutte. |
| ✅ Fixed 2026-07-07 | `scripts/mt5-bot.py` | **`quality_gate()` RSI threshold 75→85**: soglia RSI>75 bloccava TUTTI i buy durante mercato toro oro (XAU/USD bull market 2026). Gold RSI≥75 è normale in trend rialzista prolungato. Alzata a 85 (buy) e 15 (sell). Root cause del no-trade per 2.5 mesi. |
| ✅ Fixed 2026-07-07 | `scripts/mt5-bot.py` | **`quality_gate()` assente nel blocco M30**: il blocco M30 non chiamava quality_gate → segnali con ATR spike e DI spread insufficiente passavano filtro. Fix: quality_gate aggiunto dopo check direction. |
| ✅ Fixed 2026-07-07 | `scripts/mt5-bot.py` | **`quality_gate()` assente nel blocco H4**: identico a M30. Fix: quality_gate aggiunto nel blocco H4. |
| ✅ Fixed 2026-07-07 | `scripts/mt5-bot.py` | **Blocco H4 segnali senza parametri `hour`/`h1_trend`**: segnali H4 chiamati come `fn_h4(I_h4, idx)` senza contesto sessione/trend. Fix: routing specifico per S17 (h1_trend) e S00 (hour, tf='H4'). |
| ✅ Fixed 2026-07-09 | `public/modules/core.js`, `api/report.js` | **Model ID `claude-sonnet-4-20250514` scaduto (deprecato dal 2026-06-15)**: causava warning/errore nell'analisi screenshot (tab Analisi) e nei report AI giornalieri/settimanali/mensili. Fix: aggiornato a `claude-sonnet-5` in entrambi i punti (chiamata `/api/chat` in core.js e chiamata diretta Anthropic in report.js). |

## Performance Bottlenecks (mt5-bot.py) — Risolti

1. **`get_candles()` ogni tick** → Fix: cache 60s (`last_candle_fetch_ts`)
2. **`compute_indicators()` ogni tick** → Fix: `cached_I_h1`, ricalcolo solo su `new_h1_bar`
3. **`_pos_state` crescita illimitata** → Fix: cleanup automatico in `manage_positions()` tramite `open_tickets` set

## Architettura — Note

- Frontend `strategy.js` rileva regime e mostra segnali senza contesto TF: è per guida umana
- Bot MT5 applica strategie su TF specifici decisi da StrategySelector — divergenza intenzionale dal frontend
- **Non aggiungere TF filtering al frontend** senza richiesta esplicita

## Backlog Priorità Alta

- [ ] Fix `onclick` con apostrofi: sostituire `onclick='fn(${JSON.stringify(s)})'` con `data-signal` + `addEventListener`
- [ ] Notifiche push (Service Worker) su nuovo segnale Strategy Engine
- [ ] Filtro news calendar: skip 30min prima/dopo high-impact events
- [x] Backtest adattativi multi-TF 2026-07-07: H1 PF 1.64 +$6087/24m · H4 PF 1.86 +$4941/24m. TF ottimali aggiornati per tutte le strategie.
- [ ] Paper trading 2 settimane prima di live su conto reale con nuovo sistema

## Backlog Priorità Media

- [ ] `weekly_dd_pct` nel bot: calcolo reale da deals history MT5 (ora è hardcoded 0.0)
- [ ] `recent_wr_map` per StrategySelector: calcolo WR ultimi 30 trade per strategia da `mt5-trades.json`
- [ ] Alert bot offline > 5 minuti (email o push)
- [ ] UI: mostrare `active_strategy` e `strategy_confidence` nel tab Strategy Engine (già presenti in `bot_status`)
- [ ] UI mobile: ottimizzare catalog strategie per schermi < 400px

## Backlog Priorità Bassa

- [ ] Export journal in CSV/PDF
- [ ] Integrazione COT data automatica settimanale
- [ ] Fine tuning UI: animazioni transizione tra tab
