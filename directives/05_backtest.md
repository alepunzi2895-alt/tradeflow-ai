# TradeFlow AI — Procedure Backtest

## Comandi

```bash
# Canonico (MT5 aperto — dati broker reali GOLD M30)
python scripts/backtest_mfkk_intraday.py --mt5

# Fallback dati storici salvati
python scripts/backtest_mfkk_intraday.py --h1-file data/xauusd_h1_mt5.json

# Backtester principale multi-strategia
python scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json

# Con Risk Manager attivo
python scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json --rm

# Fetch dati freschi da MT5
python scripts/fetch_mt5_history.py --tf M30   # → data/xauusd_m30_mt5.json
python scripts/fetch_mt5_history.py --tf H1    # → data/xauusd_h1_mt5.json
```

> **Regola**: risultati da `--mt5` con MT5 aperto sono la fonte di verità ufficiale. I valori nelle `stats` di `SE.strategies` devono riflettere l'ultimo run MT5.

## Dataset

- **Primario**: MT5 GOLD (XMGlobal-MT5 6) · 730 giorni reali
- **Fallback**: `data/xauusd_h1_730d.json` se MT5 non disponibile

## File Risultati Canonici

```
backtests/results/M30/2026-04-16_combined_rm.json   ← M30 + RM (fonte verità)
backtests/results/M30/2026-04-16_strategies.json    ← breakdown per strategia
backtests/results/H1/2026-04-16_combined_rm.json    ← H1 + RM (riferimento)
backtests/best_config.json                          ← config ottimale corrente
backtests/archive/                                  ← risultati storici
```

## Risultati Canonici (2026-04-16 · MT5 GOLD 730gg · lot 0.01 · $1/punto)

### M30 + Risk Manager (RACCOMANDATO)

| Strategia | Trade | WR% | P&L |
|---|---|---|---|
| S16_GOLDEN_SQUEEZE | 2547 | 30.0% | +$3,910 |
| S05_MFKK_INTRADAY | 423 | 38.5% | +$892 |
| S09_MFKK_SCALPING | 336 | 35.1% | +$608 |
| S10_OB_FVG_SCALP | 84 | 44.0% | +$739 |
| **TOTALE M30** | **3390** | **31.9%** | **+$6,150** · PF 1.202 · DD $1,502 · **+$12.66/gg** |

### H1 + Risk Manager (riferimento)

| Totale H1 | 2505 trade | WR 31.3% | +$3,072 | PF 1.089 | DD $3,622 | +$7.70/gg |

## Nota su S10_OB_FVG_SCALP

WR 44% e PF alto ma solo 84 trade su 730gg → statisticamente fragile. Non scalare il lotto su questa strategia senza out-of-sample su dati freschi (minimo 12 mesi M30 separati).
