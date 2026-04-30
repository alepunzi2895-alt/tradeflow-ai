# TradeFlow AI — Strategie Attive

## Backtest Canonico (2026-04-30 · MT5 GOLD · lot 0.01 · $1/punto)

### Sistema Adattivo per TF (senza RM — fonte di verità · segnali V5 · 2026-04-30)

| TF | WR% | P&L | PF | DD | $/gg | Trade/gg | Mesi+ |
|---|---|---|---|---|---|---|---|
| M30 | **43.0%** | +$4,322 | **1.438** | $545 | +$14.0 | 4.35 | **21/24** |
| H1 | **47.5%** | +$5,785 | 1.610 | $791 | +$23.6 | 5.02 | **21/24** |
| **H4** | **43.4%** | **+$4,872** | **1.913** | **$350** | **+$28.8** | 3.0 | 14/23 |

> H4 ha il miglior PF (1.913) e DD minimo ($350). M30 e H1 entrambi a 21/24 mesi positivi. Segnali V5 (+4pp WR su M30, +2.6pp su H1 vs run precedente).

### Breakdown per strategia (M30 adattivo senza RM — segnali V5)

| Strategia | Trade | WR% | P&L contrib | TF ottimale | Note |
|---|---|---|---|---|---|
| S00_MFKK | 873 | 47.2% | +$2,708 | M30 | sell DI≥25, sell_thr 76 |
| S05_MFKK_INTRADAY | 209 | 24.9% | +$335 | **H1** | V5: ADX18, RSI57/43, slope |
| S16_GOLDEN_SQUEEZE | 157 | 44.6% | +$244 | **H1** | V5: OBV 4 barre, DI spread≥8 |
| S10_OB_FVG_SCALP | 53 | 52.8% | +$815 | M30 | alta qualità, bassa frequenza |
| S09_MFKK_SCALPING | 52 | 30.8% | +$220 | **M30** | V4: RSI>50+OBV>EMA filtri |

### TF ottimale per strategia (da backtest 2026-04-23)

| Strategia | TF Ottimale | PF sistema | WR | Note |
|---|---|---|---|---|
| S16_GOLDEN_SQUEEZE | **H1** | 1.36 | 45.0% | V4 (2026-04-28): H4 context filter SELL. BUY WR 44.5%, SELL WR 50% (countertrend only). H1 proxy: EMA200 slope>0 |
| S00_MFKK | M30 (fallback) | 1.24 | 26.1% | V2 (2026-04-28): DI≥20 or ST bullish gate, sell London/NY only. H1: WR 29.8% PF 1.49 |
| S09_MFKK_SCALPING | **M30** | 1.40 | 29.2% | V3 (2026-04-28): session 06-19h + ST alignment. H1 +$379 positivo. |
| S10_OB_FVG_SCALP | M30 | 1.80 | 51.0% | V3 (2026-04-28): ADX≥18 + ST alignment. 49 trade/25mo — alta qualità. |
| S05_MFKK_INTRADAY | **H1** | 1.07 | 23.4% | V4 (2026-04-28): session 7-17h + ST + ATR≤1.8× gate. H4: WR 34.5% +$769. |
| S17_CONVERGENCE_SCALP | **H4** | 1.75 | 35.3% | H4 adaptive: +$3,052/23mo. Sistema H4 PF 1.878. |

## Strategie Attive nel Bot

| ID | Label | TP mult | SL mult | Regimi ottimali | TF primario | PF sistema | WR adattivo |
|---|---|---|---|---|---|---|---|
| `S00_MFKK` | MFKK Core V2 | ATR×3.5 | ATR×1.5 | TREND/WEAK/RANGE | M30 | 1.326 | 45.6% (H1: 53.8%, H4: 46.4%) |
| `S05_MFKK_INTRADAY` | MFKK Intraday V4 | ATR×3.5 | ATR×1.5 | TREND_UP, TREND_DOWN | **H1** | 1.07 | 24.0% |
| `S09_MFKK_SCALPING` | MFKK Scalping V3 | ATR×4.0 | ATR×1.5 | VOLATILE, WEAK | **M30** | 1.40 | 29.6% |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V3 | ATR×3.5 | ATR×1.5 | RANGING, WEAK | M30 | 1.65 | 51.0% |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V4 | ATR×3.5 | ATR×2.0 | TREND | **H1** | 1.40 | 47.3% |
| `S17_CONVERGENCE_SCALP` | Convergence Scalp V2 | ATR×4.0 | ATR×1.5 | VOLATILE | **H4** | 1.75 | 35.8% |

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

### Baseline backtest (fonte di verità — WR adattivo per TF ottimale · segnali V5 · 2026-04-30)

| Strategia | WR baseline | PF baseline | TF ref | Trade |
|---|---|---|---|---|
| S00_MFKK | **47.2%** | 1.44 | M30 adattivo | 873 |
| S05_MFKK_INTRADAY | 25.3% | 1.10 | H1 adattivo | 162 |
| S09_MFKK_SCALPING | 36.0% | 1.40 | H1 adattivo | 25 |
| S10_OB_FVG_SCALP | 52.8% | 1.65 | M30 adattivo | 53 |
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
