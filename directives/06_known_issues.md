# TradeFlow AI — Known Issues & Backlog

## Bug Aperti

| Severity | File | Issue |
|---|---|---|
| ⚠ Open | `api/webhook.js` | `memCache` senza cleanup globale — stale indicators dopo restart Vercel |
| ⚠ Open | `api/webhook.js` | `X-TV-Secret` check opzionale — attivare `TV_WEBHOOK_SECRET` in env Vercel per protezione completa |
| ⚠ Open | `public/app.js` | `onclick` button bindings (~lines 160-172) falliscono silenziosamente se elemento assente; usare `wire()` pattern |
| ⚠ Open | `api/db.js` | `createClient()` Turso senza timeout esplicito — dipende da kill Vercel a 10s. Low risk |

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
- [ ] Backtest con StrategySelector attivo (multi-strategy rotation su 730gg) per validare +20-30% Sharpe stimato
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
