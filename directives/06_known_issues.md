# TradeFlow AI — Known Issues & Backlog

## Bug Aperti

| Severity | File | Issue |
|---|---|---|
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
