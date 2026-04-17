# TradeFlow AI — Strategie Attive

## Backtest Canonico (2026-04-16)

Dati: MT5 reale GOLD · 730gg (2024-04-15 → 2026-04-16) · lotto 0.01 · $1/punto

### Sistema Adattivo + Risk Manager (M30 — TF primario)

| TF | Trade | WR% | P&L | PF | DD | $/gg |
|---|---|---|---|---|---|---|
| **M30** | 3390 | 31.9% | +$6,150 | 1.202 | $1,502 | **+$12.66** |
| H1 | 2505 | 31.3% | +$3,072 | 1.089 | $3,622 | +$7.70 |

> M30 è nettamente superiore: P&L 2×, DD 2.6× minore.

### Breakdown M30 per strategia (con RM)

| Strategia | Trade | WR% | P&L |
|---|---|---|---|
| S16_GOLDEN_SQUEEZE | 2547 | 30.0% | +$3,910 |
| S05_MFKK_INTRADAY | 423 | 38.5% | +$892 |
| S09_MFKK_SCALPING | 336 | 35.1% | +$608 |
| S10_OB_FVG_SCALP | 84 | 44.0% | +$739 |

## Strategie Attive nel Bot MT5 (STRATEGY_PARAMS in mt5-bot.py)

| ID | Label | TF | TP mult | SL mult | Regime |
|---|---|---|---|---|---|
| `S05_MFKK_INTRADAY` | MFKK Intraday V3 | H1 | ATR×2.0 | ATR×1.0 | TREND_UP, TREND_DOWN |
| `S09_MFKK_SCALPING` | MFKK Scalping V2 | M5 | ATR×3.0 | ATR×1.0 | VOLATILE, WEAK |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V2 | M15/M30 | ATR×2.5 | ATR×1.2 | Tutti (fallback) |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V2 | M30 | ATR×3.0 | ATR×1.2 | TREND_UP, TREND_DOWN, WEAK |

**Session filter**: S16 saltato nelle sessioni asiatiche (00:00–07:59 UTC) per bassa liquidità XAU.

BE trigger per S16: +ATR×1.1 dal prezzo entry.

## Strategie UI (strategy.js — backtest stats storici)

| ID | Label | WR | PF | Trade/gg | TP / SL | P&L 24m |
|---|---|---|---|---|---|---|
| `S05_MFKK_INTRADAY` | MFKK Intraday [H1] V3 | 38.5% | 1.23 | 0.6 | ATR×2.0 / ATR×1.0 | +$892 |
| `S09_MFKK_SCALPING` | MFKK Scalping [M5] V2 | 35.1% | 1.62 | 0.46 | ATR×3.0 / ATR×1.0 | +$608 |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp [M30] V2 | 44.0% | 1.43 | 0.12 | ATR×2.5 / ATR×1.2 | +$739 |
| `S16_GOLDEN_SQUEEZE` | Elite Golden Squeeze [M30] | 30.0% | 1.45 | 2.01 | ATR×3.0 / ATR×1.2 | +$3,910 |
| `S17_CONVERGENCE_SCALP` | Convergence Scalp [M15] V2 | 26.5% | 1.28 | 2.29 | ATR×2.5 / ATR×0.8 | +$2,337 |

## Regime Priority

| Regime | Ordine priorità |
|---|---|
| TREND_UP | S16_GOLDEN_SQUEEZE → S05_MFKK_INTRADAY → S17_CONVERGENCE_SCALP |
| TREND_DOWN | S16_GOLDEN_SQUEEZE → S05_MFKK_INTRADAY → S17_CONVERGENCE_SCALP |
| WEAK_UP | S16_GOLDEN_SQUEEZE → S10_OB_FVG_SCALP → S09_MFKK_SCALPING → S17 |
| WEAK_DOWN | S16_GOLDEN_SQUEEZE → S10_OB_FVG_SCALP → S09_MFKK_SCALPING → S17 |
| VOLATILE | S09_MFKK_SCALPING → S10_OB_FVG_SCALP → S17_CONVERGENCE_SCALP |
| RANGE | S10_OB_FVG_SCALP → S09_MFKK_SCALPING → S17_CONVERGENCE_SCALP |

## Regime Detection

```python
ADX >= 30 → TREND_UP (DI+>DI-) o TREND_DOWN (DI->DI+)
ADX >= 22 → WEAK_UP o WEAK_DOWN
ATR > 1.4x ATR_avg30 → VOLATILE
default → RANGE
ATR > 3.5x ATR_avg30 → EXTREME (skip tutti i trade)
```

## Aggiungere una Nuova Strategia

1. Definire ID (`S0X_NAME`), scrivere funzione in `scripts/signals.py`
2. Importarla in `scripts/mt5-bot.py` (SIGNAL_FNS) e `scripts/strategy-engine-v2.py` (STRATS)
3. Aggiungere entry in `SE_STRATEGY_FNS` in `public/modules/se-signals.js`
4. Aggiungere entry in `SE.strategies` + `SE.regimePriority` in `public/modules/strategy.js`
5. Aggiungere in `STRATEGY_PARAMS` e `REGIME_MULTI_STRATEGIES` in `mt5-bot.py`
6. Run backtest: `python scripts/strategy-engine-v2.py --file data/xauusd_m30_mt5.json` — minimo 6 mesi
7. Aggiornare questo file + `directives/07_self_learning_log.md`

## Strategie Archiviate

Logica JS mantenuta in `public/modules/se-signals.js`, non mostrate in UI:
S00_MFKK, S00_MFKK_HWR, S01_OBV_MACD, S02_ULTIMATE_RSI, S03_MOMENTUM, S04_ICT_ORDERFLOW, S04_BB_SQUEEZE, S05_V3_Sell_Exhaust, S01_EXHAUSTION, S06_ORDERBLOCK, S12_WPR_KELTNER, S13_STRUC_BREAK, S14_KEY_LEVELS
