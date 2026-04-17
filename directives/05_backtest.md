# TradeFlow AI — Procedure Backtest

## Comandi

```bash
# Backtester principale multi-strategia (fonte di verità)
python scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json

# Con Risk Manager legacy attivo (pre-Guardian)
python scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json --rm

# Campaign MFKK multi-TF
python scripts/backtest_mfkk_campaign.py

# Fetch dati freschi da MT5 (MT5 deve essere aperto)
python scripts/fetch_mt5_history.py --tf M30   # → data/xauusd_m30_mt5.json
python scripts/fetch_mt5_history.py --tf H1    # → data/xauusd_h1_mt5.json
python scripts/fetch_mt5_history.py --tf H4    # → data/xauusd_h4_mt5.json
python scripts/fetch_mt5_history.py --tf M5    # → data/xauusd_m5_mt5.json
python scripts/fetch_mt5_history.py --tf M15   # → data/xauusd_m15_mt5.json
```

> **Regola**: dati fetched con MT5 aperto sono la fonte di verità ufficiale. I valori in `STRATEGIES_CONFIG` (strategy_selector.py) devono riflettere l'ultimo run canonico.

## Dataset

- **Primario**: MT5 GOLD (XMGlobal-MT5 6) · 730 giorni reali
- **File disponibili**: `data/xauusd_m5_mt5.json`, `_m15_`, `_m30_`, `_h1_`, `_h4_`

## File Risultati Recenti

```
backtests/results/mfkk_bt_M5.json    ← MFKK campaign M5
backtests/results/mfkk_bt_M15.json   ← MFKK campaign M15
backtests/results/mfkk_bt_M30.json   ← MFKK campaign M30
backtests/results/mfkk_bt_H1.json    ← MFKK campaign H1
backtests/results/mfkk_bt_H4.json    ← MFKK campaign H4
backtests/archive/                   ← risultati storici
```

## Risultati Canonici (2026-04-16 · MT5 GOLD 730gg · lot 0.01 · $1/punto)

### M30 Sistema Adattivo (RACCOMANDATO)

| Strategia | Trade | WR% | P&L | PF | $/gg |
|---|---|---|---|---|---|
| S16_GOLDEN_SQUEEZE | 2547 | 30.0% | +$3,910 | 1.25 | — |
| S05_MFKK_INTRADAY | 423 | 38.5% | +$892 | 1.21 | — |
| S09_MFKK_SCALPING | 336 | 35.1% | +$608 | 1.18 | — |
| S10_OB_FVG_SCALP | 84 | 44.0% | +$739 | 1.85 | — |
| **TOTALE M30** | **3390** | **31.9%** | **+$6,150** | **1.202** | **+$12.66** |

### H1 (riferimento)

| Totale H1 | 2505 trade | WR 31.3% | +$3,072 | PF 1.089 | DD $3,622 | +$7.70/gg |

## Aggiornare STRATEGIES_CONFIG dopo un Backtest

Dopo ogni run canonico aggiornare `performance_by_tf` in `strategy_selector.py`:

```python
{
  "id": "S05_MFKK_INTRADAY",
  "performance_by_tf": {
    "H1":  {"wr": 0.385, "pf": 1.15, "daily_pnl": 7.70,  "dd": 3622},
    "M30": {"wr": 0.385, "pf": 1.21, "daily_pnl": 12.66, "dd": 1502},
  },
  ...
}
```

Lo StrategySelector usa questi valori per lo scoring (`best_PF × best_WR` determina il TF preferito).

## Note Statistiche

- **S10_OB_FVG_SCALP**: WR 44%, PF 1.85 ma solo 84 trade → fragile. Non scalare senza out-of-sample 12+ mesi.
- **S09_MFKK_SCALPING M15**: PF 0.92 → non attivare su M15. Solo M5.
- **S17_CONVERGENCE_SCALP**: gate `min_atr_percentile = 0.60` → attivo solo in mercati con ATR nella fascia alta.
