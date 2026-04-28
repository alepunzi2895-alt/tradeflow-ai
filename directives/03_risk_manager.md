# TradeFlow AI — Risk Guardian Agent + News Guardian + Manutenzione Quotidiana

> **Sostituisce** `risk_manager.py` come agente primario dal 2026-04-17.
> `risk_manager.py` è mantenuto come fallback per backward compat ma non viene usato direttamente.

## Composite Confidence Score

Il tier non è più basato solo sull'AI Score, ma su un composite pesato:

```
composite = strategy_confidence × 0.50
          + signal_quality      × 0.30   (AI Score / 100 come proxy)
          + market_conditions   × 0.20   (ATR stability + session liquidity + ADX)
```

`market_conditions = 0` → ordine sospeso (spike ATR > 2.5× avg).

## Tier di Rischio

| Tier | Score | Lot Mult | TP Mult | SL Mult | BE trigger | TS Step | Early Exit |
|---|---|---|---|---|---|---|---|
| 🔵 CONSERVATIVE | < 40 | ×0.5 | ×1.0 | ×0.8 | 80% TP | 1.5×ATR | 30% profit |
| ⚪ NORMAL | 40-60 | ×0.8 | ×1.0 | ×1.0 | 70% TP | 1.5×ATR | 20% profit |
| 🟡 AGGRESSIVE | 60-75 | ×1.0 | ×1.5 | ×1.0 | 60% TP | 1.2×ATR | 10% profit |
| 🟠 STRONG | 75-85 | ×1.2 | ×1.8 | ×1.2 | 50% TP | 1.0×ATR | 5% profit |
| 🔴 MAX | > 85 | ×1.5 | ×2.0 | ×1.5 | 50% TP | 1.0×ATR | 5% profit |

### Aggiustamenti Account Health

| Condizione | Effetto score |
|---|---|
| `today_pnl < -200` | −10 pt |
| `weekly_dd_pct > 3%` | −15 pt |
| `equity > initial × 1.05` AND `weekly_dd < 2%` | +5 pt |

## Circuit Breaker

| Trigger | Azione |
|---|---|
| Daily loss > 3% equity | Halt trading |
| Weekly drawdown > 5% | Halt trading |
| 5 consecutive losses | Halt trading |

> **Limite posizioni**: `MAX_OPEN_ORDERS = 2` (ridotto da 3, 2026-04-28). Max 2 posizioni aperte contemporaneamente, mai più di 1 per direzione (buy o sell).
> **Race condition fix**: `has_position_in_direction()` controlla `_strategy_order_tickets` in-memory prima di MT5 per essere immune alla latenza post-`place_order()` (~500ms).

## Compounding

```python
lot = base_lot × tier.lot_multiplier × min(sqrt(equity / initial_equity), 3.0)
# Cap aggiuntivo: max 2% risk per trade
```

## Position Management (`manage_positions()` — ogni 10s)

1. **Break-Even**: quando profit ≥ `be_trigger` → SL a entry+0.02
2. **Trailing Stop**: dopo BE, quando profit ≥ `trailing_activation` (BE+10%) → trail di `ts_step` ATR
3. **Partial Close**: quando il prezzo tocca un key level target (da KeyLevelsAgent) → chiude 50% del volume residuo
4. **Early Exit**: se BE attivo ma trade stalled oltre `1.5 × expected_duration` con profit < `early_exit_threshold`
5. **Regime Shift Override**: chiude posizione se il regime attuale è ostile alla strategia di entrata (solo se già a BE o in profitto)

### Durate Stimate per Strategia

| Strategia | TF | Durata attesa |
|---|---|---|
| S05_MFKK_INTRADAY | H1 | 180 min |
| S05_MFKK_INTRADAY | M30 | 90 min |
| S09_MFKK_SCALPING | M5 | 20 min |
| S16_GOLDEN_SQUEEZE | M30 | 90 min |
| S10_OB_FVG_SCALP | M30 | 60 min |
| S17_CONVERGENCE_SCALP | H4 | 240 min |

## Key Levels Agent (`key_levels.py`) — integrazione TP/SL

Ogni barra H1, `kla.get_levels(I, i, candles)` calcola:

**Gerarchia timeframe** — la strength di ogni livello viene moltiplicata per il peso TF sorgente:

| TF sorgente | Peso | Autorità |
|---|---|---|
| D1 | 1.00 | Massima — pivot daily dominano |
| H4 | 0.90 | Alta |
| H1 | 0.70 | Media |
| M30 | 0.55 | Bassa |
| M15 | 0.40 | Molto bassa |
| M5 | 0.25 | Minima |

**Tipi di livello rilevati:**

| Tipo | Descrizione | Strength base (prima del peso TF) |
|---|---|---|
| `prev_session` | H/L sessione precedente (Asian/London/NY) | 1.0 |
| `liquidity_pool` | Equal highs/lows clusters (stop hunt zones) | 0.6–0.95 |
| `swing_high/low` | Pivot N-bar (5 barre ciascun lato) | 0.65–0.90 |
| `order_block` | Ultima candela OB prima di impulso forte | 0.80 |
| `round_number` | Multipli di $50 XAU psicologici | 0.60 |

In pratica: un swing_high D1 (0.85 × 1.0 = **0.85**) supera un swing_high H1 (0.85 × 0.7 = **0.60**), e il merge di entrambi sullo stesso prezzo porta a strength ≥ 0.90.

**Aggiustamenti automatici in `place_order()`:**
- **TP snap**: se un livello forte (strength ≥ 0.65) è tra entry e TP → TP si posiziona subito prima di quel livello (−0.15×ATR). TP minimo garantito: 0.8×ATR.
- **SL avoidance**: se una liquidity pool è tra SL e entry → SL si sposta oltre il cluster (−0.20×ATR) per evitare stop hunt sweep.
- **Partial targets**: livelli forti tra entry e TP vengono registrati nel position state; al tocco vengono eseguiti partial close del 50% del volume.

## Flusso Operativo

```
1. Ogni 60s: fetch AI Score da Vercel DB → aggiorna signal_quality
2. Ad ogni nuova barra H1:
   a. fetch D1 (200 barre) + H4 (300 barre) se nuova barra disponibile
   b. kla.get_multi_tf_levels([D1, H4, H1]) → current_levels_result (ponderato per TF)
   b. StrategySelector.select() → strategy_confidence
3. Ad ogni segnale:
   a. rg.get_order_params(strategy_confidence, ai_score, atr, ...) → lot/TP/SL/BE/TS
   b. place_order(..., key_levels_result, atr) → kla.adjust_tp_sl() → ordine inviato
   c. rg.register_position(ticket, params, ..., partial_targets=key_levels)
4. Ogni 10s: rg.manage_positions(mt5, symbol, magic, atr, current_regime)
   → BE / TS / partial close / early exit / regime override
```

## Parametri ATR per Strategia (STRATEGY_ATR_PARAMS)

| Strategia | TP ATR mult | SL ATR mult |
|---|---|---|
| S05_MFKK_INTRADAY | 2.5 | 1.0 |
| S09_MFKK_SCALPING | 3.0 | 1.0 |
| S10_OB_FVG_SCALP | 2.5 | 1.2 |
| S16_GOLDEN_SQUEEZE | 3.5 | 2.0 |
| S17_CONVERGENCE_SCALP | 2.8 | 1.0 |
| S00_MFKK | 2.5 | 1.0 |

> `S17_CONVERGENCE_SCALP` usa H4 (PF 1.710), non più M15/M5. Durata attesa 240min.

## Esempio Log

```
[KeyLevels] 24 levels merged (12 resistance, 9 support) @ 3245.80 ATR=9.20
[KeyLevels] BUY adjustments: TP 3290.00→3268.50 (swing_high @3270.00 str=0.85)
🎯 Partial targets [S16_GOLDEN_SQUEEZE]: 3255.00(prev_session), 3268.50(swing_high)
🛡️ RiskGuardian [🟡 AGGRESSIVE] strat=S16_GOLDEN_SQUEEZE comp=68 (str=0.85/sig=0.72/mkt=0.90)
   | lot=0.05 | TP=$22.70 SL=$11.04 | BE@+$13.62 | TS step=$8.00
🛡️  BE ticket#12345: SL→3238.74 — Profit 27.5 ≥ BE trigger 13.6
🎯  Partial close ticket#12345 — 0.025 @ 3255.00 — prev_session target
📈 Trail ticket#12345: SL→3245.80 (+7.06)
⏱️  Early exit ticket#12346 — Stalled: 8% profit after 135min (expected 90min)
🔄 Regime exit ticket#12347 — Regime shift: TREND_UP → RANGING (hostile to S05_MFKK_INTRADAY)
```


---

## News Guardian (`news_guardian.py`)

Monitora il calendario economico ForexFactory e regola rischio/pausa automaticamente.

### Comportamento

| Condizione | risk_mult | Azione bot |
|---|---|---|
| HIGH impact USD/XAU entro ±30/60min | 0.0 | Pausa totale apertura nuovi trade |
| HIGH impact altre valute entro ±30/20min | 0.5 | Lot size ridotto al 50% |
| Nessuna news imminente | 1.0 | Operatività normale |

### Finestre di pausa

- **PAUSE_BEFORE_MIN = 30** — 30 min prima dell'evento
- **PAUSE_AFTER_MIN = 60** — 60 min dopo l'evento
- Refresh calendario: ogni **6 ore** (cache in `data/news_calendar_cache.json`)
- Fonti: `https://nfs.faireconomy.media/ff_calendar_thisweek.json` + nextweek

### Integrazione nel bot

```
ogni 60s nel loop:  ← (era 15min — bug timezone fix 2026-04-28)
  news_risk = news_guardian.check_news_risk(now_utc)
  → se news_risk['paused'] → skip place_order su H1/M15/M30/H4
  → se news_risk['risk_mult'] < 1.0 → lot_use *= risk_mult

startup:
  news_guardian.refresh(force=True)
  → log eventi HIGH USD/XAU prossime 12h
```

> **Bug critico risolto 2026-04-28**: `check_news_risk(now_utc)` riceveva `now_utc` tz-aware (`datetime.now(UTC)`) ma i datetime in cache erano tz-naive → `TypeError` silenzioso nell'outer try-except → guardian sempre `paused=False`. Fix: `now_utc.replace(tzinfo=None)` all'inizio di `check_news_risk()`. Polling ridotto 900s→60s per eliminare blind spot.

### Uso standalone

```bash
python scripts/news_guardian.py              # eventi prossime 12h
python scripts/news_guardian.py --hours 24  # prossime 24h
python scripts/news_guardian.py --force     # forza re-fetch
```

---

## Daily Maintenance (`daily_maintenance.py`)

Script da eseguire ogni giorno sulla VPS (es. **06:00 UTC**).

### Step eseguiti

| Step | Azione |
|---|---|
| 1 | Fetch dati storici MT5 per M5, M15, M30, H1, H4 (richiede MT5 aperto) |
| 2 | Backtest adattivo per ogni TF (strategy-engine-v2.py) |
| 3 | Drift analysis: confronta PF/WR recenti vs baseline canonico |
| 4 | Parameter drift hints: flag se PF cambia >15% o WR >5pp |
| 5 | Report `.txt` + update `07_self_learning_log.md` per drift significativi |

### Soglie drift

| Metrica | Soglia flag | Tipo |
|---|---|---|
| PF cambia | ±15% vs baseline | PF_DRIFT_UP / PF_DRIFT_DOWN |
| WR cambia | ±5pp vs baseline | WR_DRIFT_UP / WR_DRIFT_DOWN |

> Se PF_DRIFT_DOWN: suggerisci aumentare SL mult o ridurre TP mult.
> Se PF_DRIFT_UP: aggiorna baseline in BASELINE_STATS.

### Task Scheduler Windows

```
Task: TradeFlow Daily Maintenance
Trigger: ogni giorno alle 06:00
Action: python -X utf8 C:\...\scripts\daily_maintenance.py
Start in: C:\...\tradeflow-ai
```

### Uso manuale

```bash
python scripts/daily_maintenance.py                       # completo
python scripts/daily_maintenance.py --skip-fetch          # salta download MT5
python scripts/daily_maintenance.py --tfs M30,H1          # solo TF specifici
python scripts/daily_maintenance.py --dry-run             # nessuna scrittura
```
