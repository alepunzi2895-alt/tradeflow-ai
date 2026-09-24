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

## 🆕 2026-09-07 — Deflated Sharpe Ratio / PBO (skill `walk-forward-validation`)

`scripts/opt_harness.py` importa `overfit_detector.py` dalla skill
`.claude/skills/walk-forward-validation/scripts/` (richiede `pip install scipy`, già installato).

- `dsr_check(ev, num_trials, holdout_frac=0.2)` — Deflated Sharpe Ratio sull'**holdout** di `ev`
  (da `evaluate()`). `num_trials` = quante varianti/combinazioni di parametri sono state provate
  in questa sprint PRIMA di arrivare a questa config — **va dichiarato onestamente da chi chiama**,
  non è deducibile dai dati. Ritorna `None` (non "passato") se l'holdout ha <10 giorni con trade.
- `is_promotable(ev_new, ev_base, num_trials=None)` — se `num_trials` è passato, aggiunge il check
  `dsr_ok` (DSR p-value > 0.95) come gate aggiuntivo, oltre a PF/DD/fold/frequenza esistenti.
  **Se `num_trials` è omesso il comportamento è identico a prima** (nessuna rottura retrocompatibile).
- `pbo_check(variants: dict[nome, trades], n_groups=6, n_test_groups=2)` — Probability of Backtest
  Overfitting via CPCV su più varianti candidate della stessa sprint (serie di P&L giornaliero
  allineate per data). Utile per capire se il processo di selezione tra N varianti tende a
  premiare rumore.
- `print_eval(label, ev, num_trials=None)` stampa il DSR se `num_trials` è passato.

Motivazione: il backtester ha già walk-forward/holdout, ma nessun modo di quantificare quanto
"lo Sharpe sull'holdout regge dopo aver corretto per il numero di varianti testate" — lo stesso
tipo di giudizio fatto a occhio per scartare S00 V3 ("contaminazione multi-comparison", vedi
`02_strategies.md`). Verificato con smoke test su S00_MFKK/S16_GOLDEN_SQUEEZE H1: entrambi DSR
non significativo su holdout con PF<1, coerente con i numeri PF già noti.

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


## Audit 2026-09-18

Nuovo riferimento offline: backtests/results/audit_2026-09-18/report.json. Stop da chiusura applicato dalla barra successiva, gap e timeout contabilizzati, US30 una posizione e time-stop 18 barre. Le metriche precedenti non sono direttamente confrontabili. Nessuna promozione automatica: campioni insufficienti o DSR non significativo.

## 2026-09-24 — S00 come fallback H1 in TREND_DOWN (`scripts/research_s00_trend_fallback.py`)

Dati MT5 H1 freschi (24 mesi, fino al 2026-09-24), holdout da 2026-04-02, trade S00 aggiunti solo se S16 non ha una posizione aperta. 3 varianti registrate in `research_trials` (1756 cumulativi).

| Variante | Full | Holdout |
|---|---|---|
| A solo S16 (live) | n=237 PF 1.79 +1887 DD 514, 16/24 mesi+ | n=41 PF 0.94 −47 |
| B S16 + S00 in TREND_DOWN | n=661 PF 1.12 +1288 DD 1963, 12/24 | n=153 PF 1.34 +735 |
| C S16 + S00 in TREND_DOWN+UP | n=863 PF 1.20 +2586 DD 1941, 15/24 | n=216 PF 1.62 +1733 |
| Solo trade S00 aggiunti in B (tutti SELL) | n=424 PF 0.93 −599 DD 1942, 8/23 | n=112 PF 1.56 +783, 5/6 |

Fold B: 0.95 / 0.90 / 1.47 / 1.01. DSR sui trade aggiunti: non significativo.
Verdetto: **non promuovibile**. Su 24 mesi i SELL di S00 in TREND_DOWN perdono (PF 0.93) e quadruplicano il drawdown; il guadagno è concentrato negli ultimi 6 mesi. Nessuna modifica al bot.

## 2026-09-24 — S00 V3, ingressi a regole dell'utente (`scripts/research_s00_v3_entries.py`)

Regole: ADX ≥ 25; DI dominante con spread ≥ 10 (o 15) e in crescita rispetto a 2 barre prima; MACD con incrocio nelle ultime 2 barre oppure istogramma contrario in contrazione da 2 barre; CCI (stoch-CCI) a 40/60 in due letture: PULL (pullback: BUY se ≤ 40 nelle ultime 3 barre) e MOM (momentum: BUY se ≥ 60). Orari, TP 3.5 / SL 1.5 ATR e motore invariati. 8 trial registrati (1764 cumulativi).

| @H1 | Full | Holdout | TREND_DOWN |
|---|---|---|---|
| BASE S00 attuale | n=1315 PF 1.29 DD 1941, 4/4 fold | n=267 PF 1.52 | n=471 PF 1.07 |
| PULL di10 | n=56 PF 2.06 DD 314, 4/4 fold | n=11 PF 1.34 | n=15 PF 1.83 |
| PULL di15 | n=35 PF 2.66 DD 95, 3/4 | n=5 PF 1.34 | n=7 |
| MOM di10 | n=113 PF 1.00 | n=21 PF 0.66 | n=41 PF 0.25 |
| MOM di15 | n=78 PF 0.78 | n=14 PF 1.61 | n=33 PF 0.26 |

M30: PULL in perdita (holdout PF 0.28-0.59), MOM full PF 1.6-1.8 ma holdout < 1; PBO M30 0.67.
Verdetto: nessuna variante promuovibile (holdout sotto BASE, DSR n/d o non significativo). La lettura MOM su H1 è da scartare. PULL su H1 è la più pulita (DD ÷6) ma fa circa 2 trade al mese: campione troppo piccolo per validarla e non risolve la scarsità di trade. Il comportamento opposto tra H1 e M30 indica fragilità. `signals.py` invariato.

## 2026-09-24 — Scalping multi-trade/giorno: 3 ipotesi + Pine utente "XAU Scalper Cloud v3"

**Ipotesi nuove** (`scripts/research_scalp_2026_09_24.py`, parametri fissi, 6 trial): ASIA_FADE (fade Bollinger 0-6 con ADX<20), RSI2_TREND (RSI(2) nel trend EMA50/200), EXPANSION (continuazione dopo candela > 2 ATR). Tutte in perdita su M15 (PF 0.77-0.94) e su M5 (PF 0.69-0.88), 0-2/4 fold. Scartate.

**Pine utente su M5** (`scripts/research_scalper_cloud.py`): port fedele (ribbon EMA20-50, pullback su EMA20 + MACD, reversal Bollinger vicino agli estremi Donchian 55, SL Donchian ± 0.3 ATR, TP 2R), una posizione alla volta, cost model e `simulate_exit` del motore. 9 trial in due giri, selezione solo sul TRAIN.

| Variante | Trade/g | TRAIN | HOLDOUT (da giu 2026) |
|---|---|---|---|
| V0 Pine fedele | 8.1 | PF 0.90 −1418 | PF 0.89 −382 |
| V1 solo trend (pullback nuvola) | 2.2 | **PF 1.04** +248 | PF 1.02 +29 |
| V2 solo reversal | 9.5 | PF 0.91 | PF 0.85 |
| V3 sessione 8-20 | 5.9 | PF 0.87 | PF 0.86 |
| V4 SL swing 10 barre | 9.6 | PF 0.93 | PF 0.94 |
| R2 V1 + trend H1 | 1.6 | PF 0.97 | PF 1.07 |
| R2 V1 + ADX ≥ 20 | 1.5 | PF 0.99 | PF 1.26 |
| R2 V1 + sessione | 1.6 | PF 0.94 | PF 0.90 |
| R2 V1 + trend H1 + SL swing | 2.4 | PF 0.90 | PF 1.20 |

Verdetto: **nessun edge**. Il reversal Bollinger è la parte in perdita; il pullback sulla nuvola a favore del trend è in pareggio dopo i costi. Nessun filtro migliora il TRAIN; gli holdout > 1 di R2 sono smentiti dal train sotto 1. DSR non significativo (1779 trial cumulativi). Nulla integrato nel bot.

**Round 3 (idea utente): scalp M5 solo nella direzione D1** (`--round3`, bias da giorni già chiusi, 3 trial):

| Variante | Trade/g | TRAIN | HOLDOUT (da giu 2026) |
|---|---|---|---|
| V1 + D1 EMA20 (chiusura ieri sopra/sotto EMA20 D1) | 1.7 | PF 1.05 +196 | PF 1.05 +47 |
| V1 + D1 candela di ieri verde/rossa | 1.6 | **PF 1.15** +704, fold 4/4 > 1 | PF 0.86 −173 |
| Pine completo + D1 EMA20 | 6.1 | PF 0.95 | PF 0.99 |

Il filtro D1 alza di poco il trend-only, ma la migliore sul TRAIN crolla sull'holdout (PF 1.15 → 0.86), PBO 0.80, DSR non significativo. La versione EMA20 è stabile ma in pareggio (~1.05, circa +$0.5 a trade dopo i costi). Non salva i reversal. Nessun edge, nulla integrato.
