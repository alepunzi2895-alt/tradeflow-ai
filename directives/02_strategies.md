# TradeFlow AI — Strategie Attive

## Backtest Canonico (2026-04-19 · MT5 GOLD M30 · lot 0.01 · $1/punto)

### Sistema Adattivo M30 (senza RM — fonte di verità per confronto TF)

| Metrica | Prima (2026-04-17) | Dopo (2026-04-19) | Delta |
|---|---|---|---|
| Trade totali (25 mesi) | 4599 | 3385 | -26% |
| Win Rate | 34.1% | **37.4%** | +3.3pp |
| P&L totale | +$5,556 | **+$5,794** | +4.3% |
| Profit Factor | 1.185 | **1.258** | +6.1% |
| Max Drawdown | $803 | **$759** | -5.5% |
| Media $/giorno | +$10.87 | **+$12.02** | +10.6% |
| Mesi positivi | 17/25 | **18/25** | +1 |

### Breakdown per strategia (M30 adattivo senza RM — 2026-04-19)

| Strategia | Trade | WR% | P&L contrib | TF ottimale | Note |
|---|---|---|---|---|---|
| S00_MFKK | 1680 | 42.1% | +$2,496 | M30 | TP/SL 2.5:1.0 |
| S16_GOLDEN_SQUEEZE | 1006 | 29.0% | -$1,144 | M30 | V3 rescaled: ADX>=25 + DI agree|
| S09_MFKK_SCALPING | 211 | 29.4% | -$31.6 | **M30** | |
| S05_MFKK_INTRADAY | 485 | 31.3% | -$1,292 | **H1** | |
| S10_OB_FVG_SCALP | 91 | 33.0% | -$282.6 | M30 | |
| S17_CONVERGENCE_SCALP | 74 | 23.0% | -$119.2 | **H4** | |

### Sistema adattivo per TF (senza RM — 2026-04-19)

| TF | WR% | P&L | PF | DD | $/gg | Trade/gg |
|---|---|---|---|---|---|---|
| **M30** | **37.4%** | **+$5,794** | **1.258** | **$759** | **+$12.0** | 7.0 |
| H1 | 36.0% | +$3,831 | 1.162 | $964 | +$9.1 | 6.6 |
| H4 | 43.1% | +$7,022 | **1.660** | **$626** | +$25.2 | 3.7 |

> M30 è il TF canonico: miglior equilibrio frequenza/DD. H4 ha PF 1.660 WR 43.1% ma solo 3.7 trade/gg.

### TF ottimale per strategia (da backtest 2026-04-19)

| Strategia | TF Ottimale | PF sistema | WR | Note |
|---|---|---|---|---|
| S16_GOLDEN_SQUEEZE | M30 | 0.90 | 29.0% | V3 rescaled, downgraded to secondary |
| S00_MFKK | M30 (fallback) | 1.21 | 42.1% | Best performer in adaptive engine |
| S09_MFKK_SCALPING | **M30** | 0.98 | 29.4% | FVG invariato — no filtri aggiuntivi |
| S10_OB_FVG_SCALP | M30 | 0.80 | 33.0% | — |
| S05_MFKK_INTRADAY | **H1** | 0.80 | 31.3% | — |
| S17_CONVERGENCE_SCALP | **H4** | 0.77 | 23.0% | — |

## Strategie Attive nel Bot

| ID | Label | TP mult | SL mult | Regimi ottimali | TF primario | PF sistema | WR |
|---|---|---|---|---|---|---|---|
| `S00_MFKK` | MFKK Core V2 | ATR×2.5 | ATR×1.0 | TREND/WEAK/RANGE | M30 | 1.21 | 42.1% |
| `S05_MFKK_INTRADAY` | MFKK Intraday V3 | ATR×2.5 | ATR×1.0 | TREND_UP, TREND_DOWN | **H1** | 0.80 | 31.3% |
| `S09_MFKK_SCALPING` | MFKK Scalping V2 | ATR×3.0 | ATR×1.0 | VOLATILE, WEAK | **M30** | 0.98 | 29.4% |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V2 | ATR×2.5 | ATR×1.2 | RANGING, WEAK | M30 | 0.80 | 33.0% |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V3 | ATR×3.5 | ATR×2.0 | TREND | M30 | 0.90 | 29.0% |
| `S17_CONVERGENCE_SCALP` | Convergence Scalp V2 | ATR×2.8 | ATR×1.0 | VOLATILE | **H4** | 0.77 | 23.0% |

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

### Baseline backtest (fonte di verità)

| Strategia | WR baseline | PF baseline |
|---|---|---|
| S16_GOLDEN_SQUEEZE | 29.0% | 0.904 |
| S05_MFKK_INTRADAY | 31.3% | 0.798 |
| S09_MFKK_SCALPING | 29.4% | 0.978 |
| S10_OB_FVG_SCALP | 33.0% | 0.800 |
| S00_MFKK | 42.1% | 1.214 |
| S17_CONVERGENCE_SCALP | 23.0% | 0.772 |  ← H4 ottimale (non più M30)

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
