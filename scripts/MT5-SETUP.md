# TradeFlow AI — Guida Setup MT5 Bot

## 1. Installa MetaTrader 5

Scarica MT5 dal sito del tuo broker (o da MetaQuotes: metatrader5.com/en/download).
Apri MT5 e crea/accedi a un **conto DEMO** su XAUUSD.

---

## 2. Installa la libreria Python

```bash
pip install MetaTrader5
```

> ⚠ Funziona **solo su Windows** (la libreria MT5 Python è Windows-only).

---

## 3. Configura il bot

Apri `scripts/mt5-bot.py` e modifica le prime righe:

```python
MT5_LOGIN    = 123456789      # numero conto demo (trovalo in MT5 → File → Apri conto)
MT5_PASSWORD = "demo_pass"    # password del conto
MT5_SERVER   = "MetaQuotes-Demo"  # nome server (visibile in MT5 → login screen)

LOT_SIZE     = 0.02           # 0.02 lot per conto €1000 (regola 2% risk)
```

> Se MT5 è già aperto e loggato, puoi lasciare LOGIN/PASSWORD/SERVER vuoti — il bot usa la sessione attiva.

---

## 4. Prima esecuzione — modalità DRY RUN

Testa **senza inviare ordini reali**:

```bash
cd tradeflow-ai
python -X utf8 scripts/mt5-bot.py --dry-run
```

Dovresti vedere output tipo:
```
2025-04-13 09:00:01 [INFO] TradeFlow AI — MT5 Bot avviato
2025-04-13 09:00:01 [INFO] Account: 10000.00 USD (equity=10000.00, free margin=10000.00)
2025-04-13 09:00:01 [INFO] ─── Nuova barra H1 chiusa: 2025-04-13 08:00 UTC ───
2025-04-13 09:00:01 [INFO] Regime: TREND_UP | Nessun segnale su 08:00
```

---

## 5. Esecuzione reale su DEMO

```bash
python -X utf8 scripts/mt5-bot.py
```

Il bot:
- Controlla una nuova barra H1 ogni 60 secondi
- Calcola tutti i 18 indicatori sulle ultime 300 barre
- Rileva il regime di mercato
- Se trova un segnale valido → piazza l'ordine su MT5 con TP/SL automatici
- Logga tutto in `mt5-bot.log` e `mt5-trades.json`

---

## 6. Parametri chiave

| Parametro | Default | Significato |
|---|---|---|
| `LOT_SIZE` | 0.02 | Lotto per trade (0.02 = sicuro su €1000) |
| `MAX_TRADES` | 3 | Max operazioni al giorno |
| `COOLDOWN_H` | 1 | Ore di attesa tra un trade e l'altro |
| `SESSION_UTC` | (7, 17) | Solo London+NY session |
| `EXTREME_MULT` | 3.0 | ATR > 3x media → giorno estremo, skip |
| `MAGIC` | 20250413 | ID univoco per riconoscere gli ordini del bot |

---

## 7. Scaling del lot size in base al capitale

| Capitale | Lot consigliato | Rischio/trade | €/giorno atteso |
|---|---|---|---|
| €1.000 | **0.02** | €11 (1.1%) | ~€4 |
| €2.000 | **0.04** | €22 (1.1%) | ~€8 |
| €5.000 | **0.10** | €55 (1.1%) | ~€20 |
| €10.000 | **0.20** | €110 (1.1%) | ~€40 |

---

## 8. Monitora i risultati

**Log real-time:**
```bash
# Su Windows PowerShell:
Get-Content mt5-bot.log -Wait -Tail 20
```

**File trade:**
- `mt5-bot.log` — log completo con timestamp
- `mt5-trades.json` — storico trade in formato JSON

---

## 9. Fermare il bot

Premi `Ctrl+C` nel terminale. Il bot chiude la connessione MT5 correttamente.

---

## 10. Troubleshooting

| Problema | Soluzione |
|---|---|
| `MT5 initialize() fallito` | Apri MetaTrader 5 prima di lanciare il bot |
| `Simbolo non trovato` | Cerca XAUUSD in MT5 → click destro → Mostra simbolo |
| `Ordine fallito retcode=10014` | Volume lot non valido — controlla LOT_SIZE min del broker |
| `Ordine fallito retcode=10016` | SL/TP troppo vicini al prezzo — verifica stop level del broker |
| `No candles` | MT5 non ha caricato abbastanza storico — scorri il grafico H1 manualmente |

---

## 11. Raccomandazioni per il demo test

1. **Testa almeno 30 giorni** in demo prima di passare al reale
2. **Confronta** i risultati con il backtest (WR~41%, ~1.8 trade/giorno)
3. **Non modificare** LOT_SIZE o parametri durante il test
4. Tieni MT5 **sempre aperto** (o usa un VPS Windows se vuoi 24/7)
5. Attiva **Strumenti → Opzioni → Expert Advisor → Consenti trading automatico** in MT5
