# TradeFlow AI — Strategie Attive

## Backtest Canonico (2026-04-17 · MT5 GOLD M30 · lot 0.01 · $1/punto)

### Sistema Adattivo M30 + Risk Manager (fonte di verità)

| Metrica | Valore |
|---|---|
| Trade totali (25 mesi) | 4598 |
| Win Rate | 32.6% |
| P&L totale | +$6,869 |
| Profit Factor | 1.196 |
| Max Drawdown | $1,298 |
| Media $/giorno | **+$13.44** |
| Mesi positivi | 17/25 |

### Breakdown per strategia (M30 adattivo + RM)

| Strategia | Trade | WR% | P&L contrib | Note |
|---|---|---|---|---|
| S16_GOLDEN_SQUEEZE | 1721 | 31.7% | +$4,416 | Primaria trend/weak |
| S00_MFKK | 1595 | 34.0% | +$848 | Fallback trend/weak |
| S17_CONVERGENCE_SCALP | 641 | 25.7% | +$220 | Complementare |
| S05_MFKK_INTRADAY | 301 | 36.9% | +$288 | H1 trend |
| S09_MFKK_SCALPING | 267 | 37.8% | +$583 | M5 volatile |
| S10_OB_FVG_SCALP | 73 | 42.5% | +$514 | M30 ranging |

### Sistema adattivo per TF (senza RM)

| TF | WR% | P&L | PF | DD | $/gg |
|---|---|---|---|---|---|
| M5 | 30.8% | +$509 | 1.036 | $674 | +$1.4 |
| M15 | 31.7% | +$2,942 | 1.114 | $1,051 | +$5.7 |
| **M30** | **34.0%** | **+$5,530** | **1.184** | **$592** | **+$10.8** |
| H1 | 34.1% | +$2,918 | 1.086 | $2,230 | +$5.9 |
| H4 | 38.6% | +$7,584 | 1.393 | $1,113 | +$19.7 |

> M30 è il TF canonico: miglior equilibrio frequenza/DD. H4 ha PnL/gg superiore ma solo 4 trade/gg.

## Strategie Attive nel Bot

| ID | Label | TP mult | SL mult | Regimi ottimali | TF primario | PF sistema |
|---|---|---|---|---|---|---|
| `S00_MFKK` | MFKK Score | ATR×2.0 | ATR×1.0 | TREND/WEAK (fallback) | M30 | 1.15* |
| `S05_MFKK_INTRADAY` | MFKK Intraday V3 | ATR×2.0 | ATR×1.0 | TREND_UP, TREND_DOWN | H1 | 1.21 |
| `S09_MFKK_SCALPING` | MFKK Scalping V2 | ATR×3.0 | ATR×1.0 | VOLATILE, WEAK | M5 | 1.18 |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V2 | ATR×2.5 | ATR×1.2 | RANGING, WEAK | M30 | 1.85 |
| `S16_GOLDEN_SQUEEZE` | Elite Golden Squeeze | ATR×3.0 | ATR×1.2 | TREND/WEAK | M30 | 1.25 |
| `S17_CONVERGENCE_SCALP` | Convergence Scalp V2 | ATR×2.5 | ATR×0.8 | VOLATILE/TREND | M15 | 1.20 |

*S00_MFKK: standalone non proficua; contribuisce positivamente come fallback nel sistema adattivo M30.

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
