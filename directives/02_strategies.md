# TradeFlow AI — Strategie Attive

## ⚠️ Refresh 2026-07-16 — il baseline 2026-07-07 sotto non è riproducibile

Uno sprint di ricerca (5 esperimenti paralleli in worktree isolati, vedi `07_self_learning_log.md` 2026-07-16) ha trovato **2 bug nel backtester** (`scripts/strategy-engine-v2.py`), ora corretti su `main`:

1. `run_adaptive()` non aveva un ramo TP/SL per `S00_MFKK` (~82% del volume H1) → fallback fisso $20/$12 invece di ATR×3.5/1.0. `run_adaptive_rm()` aveva già il ramo corretto.
2. `run_one()` (classifiche standalone Fase 1) etichettava **qualsiasi** uscita non-TP come sconfitta, anche quando il trailing stop aveva già spostato lo stop in profondo profitto prima dell'inversione — falsava WR/PF standalone di ogni strategia storicamente riportata in questo file.

Rilanciando oggi `--rm` (il percorso più vicino al bot live) con codice corretto e stessi dati, i numeri **non tornano** a quelli documentati sotto come "fonte di verità 2026-07-07" — il gap non è spiegato per intero solo da questi 2 bug (nessuna modifica a `signals.py` o ai dati risulta tra le due date), quindi tratta la tabella 2026-07-07 sotto come **superata/non affidabile**, non solo "leggermente disallineata". Numeri freschi, riproducibili oggi (`--rm`, 0.01 lot):

| TF | N trade | WR% | PF | $/gg | DD |
|---|---|---|---|---|---|
| M5  | 1844 | 31.6% | 1.093 | +$3.57 | — |
| M15 | ~1900 | 29.9% | 1.259 | +$11.84 | — |
| M30 | 808  | 31.9% | 1.236 | +$15.58 | $1378 |
| **H1**  | **1333** | **33.6%** | **1.412** | **+$37.95** | **$2323** |
| **H4**  | **408**  | **32.4%** | **1.69**  | **+$44.51** | **$1249** |

H4 già rigenerato **senza S05_MFKK_INTRADAY** (ritirata lo stesso giorno, vedi tabella "Strategie Attive" sotto e `07_self_learning_log.md`) — con S05 ancora nel roster il PF era 1.64/+$42.97/gg (`bt_h4_2026-07-16.json`); senza (`bt_h4_2026-07-16_no-s05.json`) sale a 1.69/+$44.51/gg su 22 trade in meno. M5/M15/M30/H1 sopra sono invece ancora col roster pre-refresh (nessuna delle altre rimozioni validate riguardava quei TF). File salvati: `backtests/results/bt_{m5,m15,m30,h1,h4}_2026-07-16*.json`. **Solo il livello aggregato per-TF è stato riverificato** — le sotto-tabelle "Breakdown per strategia" e "TF ottimale per strategia" più sotto derivano ancora dal run 2026-07-07 pre-bugfix: trattale con cautela finché non vengono ricalcolate.

## Backtest Canonico (2026-07-07 · bt_*_adaptive · lot 0.01 · ~24 mesi · regime-filtered) — ⚠️ superato, vedi sopra

### Sistema Adattivo per TF — Confronto TF (fonte di verità · 2026-07-07)

| TF | WR% | PF | $/gg | DD | Trade/gg | Mesi+ | Dati coperti |
|---|---|---|---|---|---|---|---|
| M5 | 39.2% | 1.077 | +$3.0 | $551 | 6.55 | 6/13 | ~13 mesi |
| M15 | 39.4% | 1.107 | +$3.4 | $519 | 4.23 | 9/13 | ~13 mesi |
| M30 | 42.6% | 1.155 | +$5.4 | $626 | 4.10 | 8/13 | ~13 mesi |
| **H1** | **48.6%** | **1.640** | **+$25.1** | **$390** | **5.49** | **20/24** | ~24 mesi |
| **H4** | **44.4%** | **1.857** | **+$31.1** | **$535** | **2.70** | **14/23** | ~24 mesi |

> **Conclusione**: H1 è il TF ottimale per PNL totale (+$6087/24m). H4 ha PF più alto (1.857) con meno segnali (+$4941). M30 e inferiori sono molto meno efficienti. Il bot mantiene H1 come loop principale con H4 per S17 e M30 per S09/S10/S18.

### Breakdown per strategia (H1 adattivo — 2026-07-07)

| Strategia | Trade/24m | WR% | P&L/24m | DD | Note |
|---|---|---|---|---|---|
| S00_MFKK | 1070 | **48.9%** | **+$3,896** | $264 | dominante H1 · 21/24 mesi+ |
| S16_GOLDEN_SQUEEZE | 245 | **48.6%** | **+$2,165** | $402 | TREND primario H1 · 16/24 mesi+ |
| S09_MFKK_SCALPING | 17 | 35.3% | +$38 | $71 | marginale su H1 (meglio M30) |

### Breakdown per strategia (H4 adattivo — 2026-07-07)

| Strategia | Trade/24m | WR% | P&L/24m | DD | Note |
|---|---|---|---|---|---|
| S17_CONVERGENCE_SCALP | 95 | **35.8%** | **+$2,819** | $198 | dominante H4 · PF 2.709 · 15/23 mesi+ |
| S00_MFKK | 208 | **52.4%** | **+$992** | $124 | fallback H4 · PF 1.835 (risk-adj ottimo) |

### Breakdown per strategia (M30 adattivo — 2026-07-07)

| Strategia | Trade/13m | WR% | P&L/13m | DD | Note |
|---|---|---|---|---|---|
| S00_MFKK | 575 | 43.8% | +$1,164 | $244 | buona ma inferiore a H1 |
| S10_OB_FVG_SCALP | 11 | **54.5%** | **+$208** | $154 | PF 1.949 ma campione piccolo |
| S09_MFKK_SCALPING | 12 | 25.0% | +$63 | $40 | PF 1.782 · BEST TF per S09 |
| S18_RANGE_REVERSAL | 92 | 43.5% | +$42 | $170 | marginale su M30 (M5 teoricamente migliore) |

### TF ottimale per strategia (aggiornato 2026-07-07)

| Strategia | TF Ottimale | PF adattivo | WR | Note |
|---|---|---|---|---|
| S00_MFKK | **H1** | 1.594 (H1) | 48.9% | Best PNL: +$3896/24m. H4 PF più alto (1.835) ma meno segnali |
| S16_GOLDEN_SQUEEZE | **H1** | 1.770 (H1) | 48.6% | M30 negativo (PF 0.787). Solo H1 |
| S17_CONVERGENCE_SCALP | **H4** | 2.709 (H4) | 35.8% | Dominante H4 (+$2819). H1/M30 standalone pessimi |
| S09_MFKK_SCALPING | **M30** | 1.782 (M30) | 25.0% | Cambiato da [H1]: M30 meglio in adaptive |
| S10_OB_FVG_SCALP | **M30** | 1.949 (M30) | 54.5% | H1 negativo. Campione piccolo (n=11) |
| ~~S05_MFKK_INTRADAY~~ | ⛔ ritirata 2026-07-16 | — | — | Era solo TREND H4, unico drag del roster H4 in adaptive — vedi tabella "Strategie Attive" sopra |
| S18_RANGE_REVERSAL | **M30** (bot) | 1.061 (M30) | 43.5% | M5 migliore in backtest puro (PF 1.438) ma bot non ha M5 |

## Regime Priority per TF (backtester + bot)

### H1 (REGIME_PRIORITY_H1)
- **TREND**: S16 → S00
- **WEAK**: S16 → S09 → S00
- **RANGE/VOLATILE**: S10 → S09

### M30 (REGIME_PRIORITY_M30)
- **TREND**: S16 → S10 → S00
- **WEAK**: S10 → S16 → S09 → S00
- **RANGE/VOLATILE**: S10 → S09

### H4 (REGIME_PRIORITY_H4)
- **TREND**: S16 → S17 → S00
- **WEAK**: S16 → S17 → S00
- **RANGE**: S17 → S00

## Strategie Attive nel Bot

| ID | Label | TP mult | SL mult | Regimi ottimali | TF primario | PF sistema | WR adattivo |
|---|---|---|---|---|---|---|---|
| `S00_MFKK` | MFKK Core V2 | ATR×3.5 | ATR×1.5 | tutti (fallback) | H1/M30 | 1.863 H1 | 52.3% H1, 49% M30 |
| `S09_MFKK_SCALPING` | MFKK Scalping V3 | ATR×4.0 | ATR×1.5 | VOLATILE, WEAK, RANGE | **M30** | 1.534 M30 | 41.2% |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V3 | ATR×3.5 | ATR×1.5 | RANGING, WEAK, TREND | **M30 only** | 1.534 M30 | 49.0% |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V5 | ATR×3.5 | ATR×2.0 | TREND | **H1** | 1.863 H1 | 51.0% |
| `S17_CONVERGENCE_SCALP` | Convergence Scalp V2 | ATR×4.0 | ATR×1.5 | VOLATILE, TREND | **H4** | 1.993 H4 | 34.3% |
| ~~`S05_MFKK_INTRADAY`~~ | ⛔ **Ritirata 2026-07-16** | — | — | era TREND (H4 only) | era H4 (marginale) | — | rimossa da `STRATEGIES_CONFIG` (strategy_selector.py) e da `REGIME_PRIORITY_H4` (strategy-engine-v2.py) — portfolio concentration study: droppando solo S05 dal roster H4, PF OOS 2.19→2.66 e DD -32% a parità di P&L. H4 era il suo unico slot vivo (H1/M30 già negativi). Codice/funzione segnale lasciati intatti in `signals.py` per eventuale re-instaurazione futura, semplicemente non più selezionabile in live. Vedi `07_self_learning_log.md` 2026-07-16. |

## Strategy Selector Agent (`strategy_selector.py`)

Ogni barra H1 `StrategySelector.select()` esegue:

### Scoring (0–100 pt per strategia)

| Componente | Punti | Criterio |
|---|---|---|
| Regime match | 0–40 | regime in `optimal_regimes` → 40 × strength |
| Performance TF | 0–30 | `min(best_PF / 2.0, 1.0) × 30` |
| Session filter | 0–20 | sessione compatibile → 20pt, altrimenti 5pt |
| WR recente | 0–10 | `min(recent_WR / 0.5, 1.0) × 10` |

### Hysteresis

- Strategia corrente score > 60 → nessun switch
- Nuovo leader deve battere il corrente di almeno **15 pt**

## Performance Tracker — Self-Learning Agent (`performance_tracker.py`)

Legge lo storico deals MT5 ogni barra H1, raggruppa per strategia (dal commento ordine `"TF-AI {strategy_id}"`), calcola WR/PF rolling su 30 trade e retroalimenta il StrategySelector.

### Flusso

1. `tracker.update_from_mt5(mt5)` — accoppia entry+exit per `position_id`, aggiunge nuovi trade a `data/performance_cache.json`
2. `tracker.auto_apply_adjustments()` — confronta WR recente vs baseline backtest, scrive `data/strategy_overrides.json`
3. `tracker.get_recent_wr_map()` → `{strategy_id: wr}` passato a `StrategySelector.select(recent_wr_map=...)`
4. In `_score_strategy()`: punteggio finale moltiplicato per `score_mult` da overrides

### Regole di aggiustamento (richiede ≥ 10 trade recenti)

| Condizione | score_mult | Tipo |
|---|---|---|
| WR recente < 70% del baseline | 0.70 | underperform |
| WR recente > 125% del baseline | 1.30 | outperform |
| ≥ 6 perdite consecutive | 0.50 | streak_penalty |
| Nella norma | 1.00 | normal |

### Baseline backtest (fonte di verità — WR adattivo per TF ottimale · segnali V6 · 2026-04-30)

| Strategia | WR baseline | PF baseline | TF ref | Trade |
|---|---|---|---|---|
| S00_MFKK | **49.4%** | 1.44 | M30 adattivo | 518 |
| S05_MFKK_INTRADAY | 25.3% | 1.10 | H1 adattivo | 162 |
| S09_MFKK_SCALPING | 36.0% | 1.40 | H1 adattivo | 25 |
| S10_OB_FVG_SCALP | 52.8% | 1.65 | M30 adattivo | 54 |
| S16_GOLDEN_SQUEEZE | **51.4%** | 1.50 | H1 adattivo | 140 |
| S17_CONVERGENCE_SCALP | 34.0% | 1.75 | H4 adattivo | 103 |

> Ogni cambiamento significativo (|Δmult| ≥ 0.15) viene automaticamente loggato in `07_self_learning_log.md`.
> Cache trade: `data/performance_cache.json` (max 500 trade). Overrides: `data/strategy_overrides.json`.

---

## Regime Detection (esteso)

```python
ATR > 3.0× ATR_avg30 → VOLATILE (strength ~0.9)
ADX >= 30            → TREND_UP (DI+>DI-) o TREND_DOWN (DI->DI+)
ADX >= 22            → WEAK
ATR > 1.4× ATR_avg30 → VOLATILE
ADX < 20             → RANGING
default              → WEAK
```

---

## PROCEDURA COMPLETA — Aggiungere una Nuova Strategia

Questo è il giro obbligatorio per ogni nuova strategia. Seguirlo nell'ordine esatto.

### Fase 1 — Definizione e implementazione segnale

1. Scegli ID univoco (`S0X_NOME`) e nome leggibile
2. Implementa la funzione in `scripts/signals.py` con firma:
   ```python
   def signal_nome(ind, i, h1_trend=None, hour=None):
       # ind: dict indicatori, i: bar index
       # Ritorna: 'buy' | 'sell' | None
   ```
3. Verifica che usi solo indicatori già calcolati in `compute_indicators()` (mt5-bot.py)
4. Importa in `scripts/mt5-bot.py`:
   ```python
   from signals import signal_nome
   ```

### Fase 2 — Backtest individuale su tutti i TF

```bash
# Aggiorna strategy-engine-v2.py:
# 1. Importa la funzione: from signals import signal_nome as s_nome
# 2. Aggiungi in STRATS: 'S0X_NOME': (s_nome, ['TREND_UP','TREND_DOWN',...])
# 3. Aggiungi ATR-based TP/SL in run_one(), run_adaptive(), run_adaptive_rm()
# 4. Aggiungi la firma corretta nel call routing (se ha parametri custom)

# Aggiungi data fetching se serve TF nuovo
python scripts/fetch_mt5_history.py --tf M30

# Esegui su ogni TF
for TF in M5 M15 M30 H1 H4; do
  python -X utf8 scripts/strategy-engine-v2.py \
    --file data/xauusd_${TF,,}_mt5.json \
    --out backtests/results/bt_${TF}.json
done
```

### Fase 3 — Scegliere il TF ottimale

Criteri in ordine di priorità:
1. **PF nel sistema adattivo** (non standalone) > 1.10
2. **Trade/giorno** ragionevole (≥ 0.5, ≤ 15)
3. **WR** ≥ 28% su almeno 50 trade
4. **DD** proporzionato (< 3× daily_pnl × 30)

Se standalone negativo ma adattivo positivo → usare come fallback/secondary (come S00_MFKK).
Se negativo anche nel sistema adattivo → non aggiungere al bot.

### Fase 4 — Wiring nel bot e negli agenti

```python
# mt5-bot.py
# 1. SIGNAL_FNS
SIGNAL_FNS['S0X_NOME'] = signal_nome

# 2. STRATEGY_PARAMS
STRATEGY_PARAMS['S0X_NOME'] = {
    'tp_usd': 'ATR', 'sl_usd': 'ATR',
    'label': 'Label Visibile', 'tp_mult': 2.0, 'sl_mult': 1.0
}

# 3. REGIME_MULTI_STRATEGIES (aggiungi nel TF corretto per il regime giusto)
REGIME_MULTI_STRATEGIES['TREND_UP'].append(('S0X_NOME', 'M30', None))

# strategy_selector.py — STRATEGIES_CONFIG
{
    "id": "S0X_NOME",
    "name": "...",
    "signal_function": "signal_nome",
    "performance_by_tf": {
        "M30": {"wr": 0.xx, "pf": x.xx, "daily_pnl": x.x, "dd": xxx}
    },
    "optimal_regimes": ["TREND_UP", "TREND_DOWN"],
    "base_params": {"tp_atr_mult": 2.0, "sl_atr_mult": 1.0}
}

# risk_guardian.py
# STRATEGY_ATR_PARAMS
STRATEGY_ATR_PARAMS['S0X_NOME'] = {"tp_atr": 2.0, "sl_atr": 1.0}
# TRADE_DURATIONS
TRADE_DURATIONS[("S0X_NOME", "M30")] = 60  # minuti stimati

# _get_strategy_optimal_regimes()
mapping['S0X_NOME'] = ["TREND", "WEAK"]
```

### Fase 5 — Wiring UI frontend

```javascript
// public/modules/se-signals.js
// Aggiungi la funzione signal in SE_STRATEGY_FNS[id]

// public/modules/strategy.js
// 1. SE.strategies['S0X_NOME'] = { label, pf, wr, tp, sl, stats: {...} }
// 2. SE.regimePriority[regime].push('S0X_NOME')
```

### Fase 6 — Aggiornamento documentazione

1. Aggiornare `directives/02_strategies.md` (questo file):
   - Tabella strategie attive
   - Breakdown per strategia nei risultati canonici
2. Aggiornare `directives/05_backtest.md` con i nuovi risultati canonici
3. Aggiornare `STRATEGIES_CONFIG` in `strategy_selector.py` con stats reali
4. Aggiungere entry in `directives/07_self_learning_log.md`

### Fase 7 — Deploy

```bash
git add scripts/signals.py scripts/mt5-bot.py scripts/strategy_selector.py \
        scripts/risk_guardian.py scripts/strategy-engine-v2.py \
        public/modules/strategy.js public/modules/se-signals.js \
        backtests/results/ directives/
git commit -m "feat: add S0X_NOME strategy — TF M30, PF x.xx, WR xx%"
git push origin main
```

---

## Note su Statistiche Fragili

- **S10_OB_FVG_SCALP**: WR 42.5% ma solo 73 trade nel sistema → fragile statisticamente. Non scalare lotto senza out-of-sample 12+ mesi.
- **S09_MFKK_SCALPING M15**: PF 0.92 standalone → non attivare su M15, solo M5.
- **S00_MFKK standalone**: PF < 1 su tutti i TF individualmente. Proficua solo come fallback nel sistema adattivo M30.

## Strategie Archiviate

Logica JS mantenuta in `public/modules/se-signals.js`, non mostrate in UI:
S00_MFKK_HWR, S01_OBV_MACD, S02_ULTIMATE_RSI, S03_MOMENTUM, S04_ICT_ORDERFLOW, S04_BB_SQUEEZE, S05_V3_Sell_Exhaust, S01_EXHAUSTION, S06_ORDERBLOCK, S12_WPR_KELTNER, S13_STRUC_BREAK, S14_KEY_LEVELS
