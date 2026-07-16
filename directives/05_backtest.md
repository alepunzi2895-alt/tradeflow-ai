# TradeFlow AI — Procedure Backtest

> ⚠️ **2026-07-16**: i "Risultati Canonici" sotto (2026-05-08) e il baseline 2026-07-07 in `02_strategies.md` sono superati — 2 bug in `strategy-engine-v2.py` (`run_adaptive()` senza ramo S00_MFKK, `run_one()` etichettava vincite trailing-stop come sconfitte) sono stati corretti su `main` il 2026-07-16, e i numeri non tornano identici nemmeno dopo il fix. Numeri freschi riproducibili in `02_strategies.md` § "Refresh 2026-07-16". Dettagli in `07_self_learning_log.md`.

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

## Risultati Canonici (2026-05-08 · MT5 GOLD 24 mesi · lot 0.01 · $1/punto)

> Fix 2026-05-08: S05 rimosso da M30 TREND (WR 22.7%), S10 rimosso da H1 TREND/WEAK (WR 27.1%). Regime priority TF-specifici (REGIME_PRIORITY_H1 / REGIME_PRIORITY_M30).

### M30 Sistema Adattivo

| Strategia | Trade | WR% | P&L | Note |
|---|---|---|---|---|
| S00_MFKK | 661 | 49.0% | +$2,436 | dominante |
| S16_GOLDEN_SQUEEZE | 165 | 43.0% | +$114 | |
| S10_OB_FVG_SCALP | 49 | 49.0% | +$638 | |
| S09_MFKK_SCALPING | 34 | 41.2% | +$287 | |
| **TOTALE M30** | **909** | **47.6%** | **+$3,476** | **PF 1.534 · DD $520 · +$13.74/gg · 21/25 mesi+** |

### H1 Sistema Adattivo (RACCOMANDATO)

| Strategia | Trade | WR% | P&L | Note |
|---|---|---|---|---|
| S00_MFKK | 782 | 52.3% | +$3,704 | dominante |
| S16_GOLDEN_SQUEEZE | 145 | 51.0% | +$1,472 | |
| S09_MFKK_SCALPING | 19 | 36.8% | +$51 | |
| **TOTALE H1** | **949** | **51.6%** | **+$5,201** | **PF 1.863 · DD $186 · +$26.27/gg · 24/25 mesi+** |

### H4 Sistema Adattivo

| Totale H4 | 428 trade | WR 45.1% | +$4,447 | PF 1.993 | DD $316 | +$28.32/gg | 16/23 mesi+ |

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
