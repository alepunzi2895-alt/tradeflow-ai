# TradeFlow AI — Procedure Backtest

## 🆕 2026-09-02 — Cost model + walk-forward (Fase 0 sprint "performance stabile e duratura")

Il backtester sovrastimava il PF vs live (S00 bt ~1.6 / live 0.59). Tre fix in `strategy-engine-v2.py`,
tutti **attivi di default**, disattivabili per riprodurre i numeri storici:

| Fix | Default | Flag ripristino storico |
|---|---|---|
| **Cost model** — spread + slippage sottratti dal P&L lordo di ogni trade | ON | `--no-costs` |
| **Fill pessimistico** — barra che tocca sia TP che SL → conta SL (`resolve_intrabar()`) | ON | `--optimistic-fill` |
| **Entry al next-bar-open** invece della close della candela di segnale | ON | `--entry-on-close` |

Costanti costo (in cima al file, calibrate da `scripts/calibrate_costs.py` vs `data/performance_cache.json`):
`HALF_SPREAD_USD=0.15` (entry+exit) · `SLIP_ENTRY_USD=0.05` · `SLIP_SL_USD=0.10` (gap-through stop) ·
`COMMISSION_USD=0.0`. Override CLI: `--spread --slippage --sl-slippage --commission`.
Verifica: `--no-costs --optimistic-fill --entry-on-close` riproduce esatto il baseline storico (H1 --rm PF 1.241).

**Walk-forward** (`--walkforward`): 4 fold cronologici di training + **holdout finale 20% intoccabile**
(nessun tuning lo vede). `walk_forward_report()` / `print_walk_forward()` riusabili. La metrica di
promozione della sprint è **PF sull'holdout**, non sul full-period.

**Risultati chiave 2026-09-02** (H1, `--rm --walkforward`, cost model ON):

| Segmento | adattivo+RM PF | S00 PF | S16 PF |
|---|---|---|---|
| full period (~24m) | 1.21 | 1.14 | 1.72 |
| **HOLDOUT (ult. ~5 mesi)** | **0.95** | **0.90** | **1.06** |
| finestra live (apr-lug 2026, standalone) | — | 0.49 (≈ live 0.59 ✓) | 0.21 (bt 15 trade vs 76 live — vedi sotto) |

→ **L'edge documentato come "PF 1.6 canonico" era una media dominata dai dati 2024–metà 2025.**
Nel 2026 il sistema H1 è ~breakeven. H4 regge meglio ($56/gg adattivo+RM). M30 ~breakeven (holdout PF 1.04).

**Divergenza bot ↔ backtester (S16)**: il backtester chiama `signal_golden_squeeze(ind, i, h1_trend=…, hour=…)`;
il bot via `get_signal()`/`PLAYBOOK` (mt5-bot.py ~643) lo chiama `fn(I, i)` **senza `hour`** → il filtro
sessione 7-18 UTC è bypassato e S16 trada 24/7 (76 trade live vs 15 nel backtester sulla stessa finestra).
Da riconciliare: il bot e il backtester devono invocare le signal fn con gli stessi argomenti.

`scripts/opt_harness.py` — `evaluate(name, fn, tf, tp_mult, sl_mult)` → `{full, folds, holdout, live}` +
`is_promotable(ev_new, ev_base)`. Fitness unica per tutti i subagenti della sprint.

---

> ⚠️ **2026-07-17**: la tabella "Refresh 2026-07-16" sotto è a sua volta superata — SL nel backtester disallineato dal live su S00/S09/S10/S17 (1.0-1.2×ATR invece di 1.5×ATR dal 2026-04-30), corretto lo stesso giorno. Numeri freschi riproducibili in `02_strategies.md` § "Refresh 2026-07-17". Dettagli in `07_self_learning_log.md`.
>
> ⚠️ **2026-07-16**: i "Risultati Canonici" sotto (2026-05-08) e il baseline 2026-07-07 in `02_strategies.md` sono superati — 2 bug in `strategy-engine-v2.py` (`run_adaptive()` senza ramo S00_MFKK, `run_one()` etichettava vincite trailing-stop come sconfitte) sono stati corretti su `main` il 2026-07-16, e i numeri non tornano identici nemmeno dopo il fix. Dettagli in `07_self_learning_log.md`.

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
