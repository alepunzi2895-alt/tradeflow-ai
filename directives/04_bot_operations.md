# TradeFlow AI — Bot MT5: Operazioni & Comandi

## Avvio Bot

```bash
# Prerequisiti: MT5 aperto + pip install MetaTrader5 python-dotenv
python -X utf8 scripts/mt5-bot.py              # live
python -X utf8 scripts/mt5-bot.py --dry-run    # simulazione (nessun ordine reale)

# Monitor log
Get-Content mt5-bot.log -Wait -Tail 20

# Kill processo zombie
taskkill /f /im python.exe
```

Output atteso all'avvio:
```
TradeFlow AI — MT5 Bot avviato
RiskGuardian attivo — equity iniziale=10000.00
StrategySelector attivo — selezione dinamica regime-based
Account: 990.81 EUR (equity=990.81, free margin=990.81)
```

## Flusso Loop Principale (ogni 1s)

```
atr_now = I_h1['atr'][i]
rg.manage_positions(mt5, SYMBOL, MAGIC, atr_now, current_regime)
  → BE + Trailing Stop + Early Exit + Regime Shift Override

fetch_remote_commands()     → comandi UI da Turso DB
sync_to_vercel()  (ogni 20s) → push stato account + posizioni + active_strategy

Su nuova candela H1 chiusa:
  compute_indicators()       → solo su nuova barra
  detect_regime()            → regime semplice (backward compat + logging)
  StrategySelector.select()  → regime esteso + scoring → best strategy + TF
  signal_fn()                → segnale (buy/sell) per la strategia selezionata
  rg.get_order_params()      → composite score → tier → lot/TP/SL/BE/TS params
  place_order()              → mt5.order_send()
  rg.register_position()     → avvia tracking lifecycle
```

## Due Agenti AI

### Strategy Selector (`strategy_selector.py`)

- Gira ogni barra H1 (non ogni tick)
- Input: indicatori H1, ora UTC (session)
- Output: `current_selector_result` → `selected_strategy`, `timeframe`, `confidence`, `reasoning`
- Fallback: se non disponibile, usa `get_signal()` con playbook statico

### Risk Guardian (`risk_guardian.py`)

- `get_order_params()`: chiamato ad ogni segnale valido
  - Input: `strategy_confidence` (da StrategySelector), `ai_score` (da Vercel), `atr`, condizioni account
  - Output: `lot`, `tp_usd`, `sl_usd`, `be_trigger`, `ts_step`, `tier_label`
- `manage_positions()`: chiamato ogni ciclo (~1s o 10s)
  - Gestisce: Break-Even, Trailing Stop, Early Exit, Regime Shift Override
- `register_position()`: chiamato dopo `place_order()` per inizializzare tracking ticket

## Sincronizzazione Vercel

Il `bot_status` pushato ogni 20s include ora:
```json
{
  "active_strategy": "S16_GOLDEN_SQUEEZE",
  "strategy_confidence": 0.85,
  "selector_reasoning": "Regime=TREND_DOWN (ADX=32, strength=0.85) | ..."
}
```

## Flusso Comando UI → MT5

```
1. Utente clicca "ESEGUI SU MT5" in strategy.js
2. POST /api/db action=mt5_command_push → salva in Turso DB
3. mt5-bot.py loop → fetch_pending_command() → legge comando
4. Verifica scadenza < 60s (age_s > 60 → ignorato)
5. place_order(direction, tp, sl, strategy) → mt5.order_send()
6. sync_to_vercel() → aggiorna UI
```

## Retcode MT5 Comuni

| Retcode | Significato | Soluzione |
|---|---|---|
| **10027** | AutoTrading disabled | Abilitare Algo Trading in MT5 toolbar (▶ verde) |
| 10004 | Requote | Normale in volatilità alta — riprova al prossimo ciclo |
| 10006 | Request rejected | Broker rifiuta — verificare orari di trading |
| 10014 | Invalid volume | LOT_SIZE non valido — verificare dimensione minima |
| 10016 | Invalid stops | TP/SL troppo vicini — aumentare distanza |
| 10019 | No money | Margine insufficiente — ridurre LOT_SIZE |
| 10021 | No prices | Mercato chiuso o connessione assente |

## Checklist Pre-Deploy

- [ ] Variabili usate = variabili definite nel file (scope check)
- [ ] `onclick='fn(${JSON.stringify(obj)})'` — no apostrofi nei campi stringa
- [ ] Fetch server-side con timeout < 8s (limite Vercel)
- [ ] `git add <file-specifico>` — non `git add .` per evitare commit `.env`
- [ ] `git push origin main` → attendere ~60s → verificare URL produzione
