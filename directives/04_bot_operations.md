# TradeFlow AI — Bot MT5: Operazioni & Comandi

## Avvio Bot

```bash
# Prerequisiti: MT5 aperto + pip install MetaTrader5
python -X utf8 scripts/mt5-bot.py              # live
python -X utf8 scripts/mt5-bot.py --dry-run    # simulazione (nessun ordine reale)

# Monitor log
Get-Content mt5-bot.log -Wait -Tail 20

# Kill processo zombie (se bot non si avvia)
taskkill /f /im python.exe
```

Output atteso all'avvio:
```
TradeFlow AI — MT5 Bot avviato
✅ Simbolo Gold rilevato: GOLD
Account: 990.81 EUR (equity=990.81, free margin=990.81)
```

## Flusso Loop Principale (ogni 1s)

```
manage_positions()          → BE + Trailing Stop su posizioni aperte
fetch_remote_commands()     → comandi UI da Turso DB
sync_to_vercel()  (ogni 20s) → push stato account + posizioni
Su nuova candela M30/H1:
  compute_indicators()      → solo su nuova barra (non ogni tick)
  detect_regime()
  get_signal() / signal_fn() per strategia attiva
  place_order() se segnale valido
```

## Flusso Comando UI → MT5

```
1. Utente clicca "ESEGUI SU MT5" in strategy.js
2. seSendTradeToMt5(s) → verifica syncAge < 30s (bot online?)
3. POST /api/db action=mt5_command_push → salva in Turso DB
4. mt5-bot.py loop → fetch_remote_commands() → legge comando
5. Verifica scadenza < 3 minuti (evita esecuzione in ritardo)
6. place_order(direction, tp, sl, strategy) → mt5.order_send()
7. sync_to_vercel() → aggiorna UI
```

## Struttura Comando DB

```json
{
  "direction": "buy" | "sell",
  "strategy": "S16_GOLDEN_SQUEEZE",
  "tp": 30.0,
  "sl": 12.0,
  "symbol": "GOLD",
  "created_at": "2026-04-14T09:00:00Z"
}
```

## Sicurezza

- Scadenza comandi: **3 minuti** dal `created_at`
- Secret condiviso: `MT5_BOT_SECRET` (env Vercel) ↔ `MT5_SECRET` (.env locale)
- Dry-run: `--dry-run` flag rispettato anche per comandi remoti
- Il bot non esegue ordini se c'è già una posizione aperta su GOLD nella stessa direzione

## Retcode MT5 Comuni

| Retcode | Significato | Soluzione |
|---|---|---|
| **10027** | AutoTrading disabled by client | Abilitare **Algo Trading** nella toolbar MT5 (icona ▶ deve essere verde) |
| 10004 | Requote | Normale in volatilità alta — riprova al prossimo ciclo |
| 10006 | Request rejected | Broker rifiuta — verificare orari di trading |
| 10014 | Invalid volume | LOT_SIZE non valido — verificare dimensione minima lotto |
| 10016 | Invalid stops | TP/SL troppo vicini al prezzo — aumentare distanza |
| 10019 | No money | Margine insufficiente — ridurre LOT_SIZE |
| 10021 | No prices | Mercato chiuso o connessione assente |

> ⚠️ **Retcode 10027**: non è un bug di codice. Abilitare Algo Trading in MT5 → toolbar → pulsante verde. Tools → Options → Expert Advisors → deselezionare voci "Disabilita quando...".

## Checklist Pre-Deploy

- [ ] Variabili usate = variabili definite nel file (scope check)
- [ ] `onclick='fn(${JSON.stringify(obj)})'` — no apostrofi nei campi stringa
- [ ] Fetch server-side con timeout < 8s (limite Vercel)
- [ ] `git add <file-specifico>` — non `git add .` per evitare commit `.env`
- [ ] `git push origin main` → attendere ~60s → verificare URL produzione
