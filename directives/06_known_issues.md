# TradeFlow AI — Known Issues & Performance Bottlenecks

## Bug Aperti

| Severity | File | Issue |
|---|---|---|
| ⚠ Open | `api/webhook.js` | `memCache` ha TTL 5min ma nessun cleanup globale — stale indicators dopo restart Vercel |
| ⚠ Open | `api/webhook.js` | `X-TV-Secret` header check è opzionale (backward-compatible) — attivare `TV_WEBHOOK_SECRET` in env Vercel per protezione completa |
| ⚠ Open | `public/app.js` | `onclick` button bindings (lines ~160-172) falliscono silenziosamente se l'elemento è assente; usare `wire()` pattern |
| ⚠ Open | `api/db.js` | Turso `createClient()` senza timeout esplicito — dipende dal kill Vercel a 10s. Low risk, monitorare |

## Performance Bottlenecks (mt5-bot.py)

Già risolti in parte, documentati per riferimento:

1. **`get_candles()` ogni tick** → Fix: cache 60s, riesegue solo se `now_ts - last_candle_fetch_ts >= 60`
2. **`compute_indicators()` ogni tick** → Fix: `cached_I_h1`, ricalcolo solo su `new_h1_bar` (1×/ora per H1)
3. **`_pos_state` dict** → cleanup automatico in `manage_positions()` tramite confronto con `open_tickets` set. Nessuna crescita illimitata.

## Architettura — Note

- Frontend `strategy.js` (e moduli estratti) rileva regime e mostra segnali senza contesto TF: è per guida umana
- Bot MT5 applica strategie su TF diversi (M5 per S09, M30 per S16, H1 per S05) — divergenza intenzionale
- **Non aggiungere TF filtering al frontend** senza richiesta esplicita

## Backlog Priorità Alta

- [ ] Fix `onclick` con apostrofi: sostituire `onclick='fn(${JSON.stringify(s)})'` con `data-signal` + `addEventListener`
- [ ] Notifiche push (Service Worker) su nuovo segnale Strategy Engine
- [ ] Filtro news calendar: skip 30min prima/dopo high-impact events

## Backlog Priorità Media

- [ ] Backtest periodico automatico (cron mensile) per rilevare drift parametri
- [ ] Alert bot offline > 5 minuti (email o push)
- [ ] UI mobile: ottimizzare catalog strategie per schermi < 400px

## Backlog Priorità Bassa

- [ ] Export journal in CSV/PDF
- [ ] Integrazione COT data automatica settimanale
- [ ] Fine tuning UI: animazioni transizione tra tab
