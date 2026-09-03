# TradeFlow AI — Strategie Attive

## 🔬 2026-09-03 — Ricerca strategia US30 (in corso, nessuna live)

Asset `US30Cash` (vedi `01_data_sources.md`). Harness dedicato, separato dal roster XAU:

- `scripts/us30_harness.py` — backtest realistico (cost model US30: half-spread 1.0 pt, slip stop 2.5 pt, fill pessimistico, entry next-open) + walk-forward 4 fold + holdout 20%. Firma segnale `fn(candles, ind, i, dt)`. Riusa `compute_all`/`stats`/`walk_forward_report` da `strategy-engine-v2.py`.
- `scripts/us30_strategies.py` — ipotesi v1: `orb_breakout` (opening-range breakout sessione USA), `bb_fade` (mean-reversion Bollinger fuori ore-trend), `session_momentum` (trend-follow Supertrend+ADX 14-21 UTC).

**v1 (2026-09-03)**: orb_breakout / bb_fade / session_momentum → nessuna promuovibile (holdout PF < 1 o campione n<10).

**v2 (2026-09-03) — CANDIDATA PROMOSSA: `S30_DOW_DIP`** (`dow_dip_d1` @ H4)

Ragionamento "come Wall Street": l'edge azionario più duraturo è la **mean-reversion di un estremo di breve NELLA DIREZIONE del trend di fondo** (Connors RSI(2), "buy weakness in strength") — long-only, perché l'equity risk premium fa driftare gli indici al rialzo e lo short-mean-reversion non ha lo stesso edge.

Setup (H4, long-only): RSI(2) < 15 · 2 chiusure H4 consecutive in calo · close > EMA50 **e** > EMA233 · EMA50 in salita su 20 barre · prezzo entro 8% dal max di 50 barre. Exit: **TP 1.2×ATR, SL 2.6×ATR, nessun trailing** (si aspetta lo snap-back).

| | n | WR | PF | pnl (pt) | DD (pt) |
|---|---|---|---|---|---|
| full (21 mesi) | 130 | 76.2% | **1.63** | +8037 | 1302 |
| holdout (2026-04-23→) | 26 | 80.8% | **2.09** | +2653 | 1050 |
| walk-forward | — | — | 1.27 / 1.96 / 1.17 / 1.86 | — | **4/4 fold positivi** |

Robusto allo sweep (rsi_buy 10-20 × down_closes 1-2 × TP/SL: PF full 1.45-1.64, holdout 1.3-2.4 su **ogni** combo → non è curve-fitting). Il guard di regime (EMA233 + slope + max_below_hi) fa **sedere fuori dal bear market** — zero trade da fine feb a fine apr 2025 (crollo a 36.6k). Worst month −775 pt (≈ −$77 @ 0.1 lot). Frequenza ~6 trade/mese.

**Stato**: **integrata nel bot (2026-09-03)** come blocco isolato su 2° simbolo `US30Cash` — `signal_dow_dip` in `signals.py`, blocco `_us30_*` in `mt5-bot.py` (`US30_ENABLED`), lotto fisso 0.10, SL/TP hard a MT5, time-stop 18 barre H4, `is_hard_blocked` come safety net. Fuori da StrategySelector/RiskGuardian/`MAX_OPEN_ORDERS`. Dettagli operativi: `04_bot_operations.md`. Fase small-size (come S20: 0.10 fisso → si valuta lo scale dopo 4-6 sett). Harness: `scripts/us30_harness.py --strategy dow_dip_d1`.

---

## ✅ 2026-09-02 — SPRINT "performance stabile e duratura" — riepilogo (branch `sprint/perf-stabile-2026-09`)

**Contesto**: il backtester dava PF ~1.2-1.6 ma il live reale PF 0.59 (S00) / 0.10 (S09) / 0.88 (S16), −$3 807 su 347 trade.

**Fase 0** (backtester realistico): cost model + fill intrabar pessimistico + entry next-bar-open + walk-forward/holdout.
→ Il "PF 1.6 canonico" era una **media gonfiata dai dati 2024–metà 2025**. Sull'holdout recente (~5 mesi) il sistema H1 era a **PF 0.95** (breakeven). **L'edge è decaduto — non è un problema di tuning.**

**Fase 1** (4 subagenti paralleli, worktree isolati, fitness = holdout PF): **nessun re-tuning di segnale restaura un edge robusto sul 2026**. Cambiamenti adottati, tutti conservativi:

| Item | Cosa | Effetto |
|---|---|---|
| S16 call-path | bot chiamava `signal_golden_squeeze` senza `hour` → tradava 24/7 (76 trade vs 15 backtester). Aggiunto `hour` a tutti i call-site. Nessun cambio parametri. | bot allineato al backtester, meno overtrading |
| S17 SL | 1.5→1.75×ATR (unico gradiente robusto e monotòno, 4/4 fold) | holdout PF 0.98→1.32; roster H4 2.09→2.21 |
| S20 sessione | `FIB_SESSION (7,19)→(8,17)` (solo overlap liquido). Zero impatto su size/rischio. | holdout PF M5 2.37→2.78, DD -19% |
| Portfolio trim | `REGIME_PRIORITY_*` ripuliti dei drag: S00 fuori dagli slot **short** su H1 (edge solo long), S18 fuori M30, S16 fuori M30-TREND & H4-WEAK_DOWN, S09 fuori H1-WEAK_UP | vedi sotto |
| Deadlock bot | riconciliazione `_strategy_order_tickets` vs MT5 nel sync loop (bot fermo dal 2026-07-10) | bot deployabile (serve restart VPS) |

**Fase 2** — validazione di portafoglio consolidata (`--rm --walkforward`, cost model ON, config finale senza S00 V3):

| TF | Holdout PF prima → dopo | Full PF | Full DD prima → dopo | Fold+ |
|---|---|---|---|---|
| **H1** | 0.95 → **1.16** | 1.21 → 1.52 | 5018 → **2100** | 4/4 |
| **M30** | 1.04 → **1.19** | 1.15 → 1.20 | 1730 → 1579 | 3/4 |
| **H4** | 1.23 → **1.26** | 1.60 → 1.64 | — | 3/4 |

→ Tutti e 3 i TF ora holdout PF > 1.15, DD ridotto (H1 dimezzato). **Il guadagno viene dal tradare MENO e meglio** (H4 = TF con più edge residuo; S17@H4 miglior contributore singolo), non da nuovi parametri di segnale. File: `backtests/results/bt_sprint_final_{h1,m30,h4}.json`.

### S00_MFKK — candidato V3, NON shippato
Baseline V2 (ADX-weight 0.80) **confermata morta**: standalone full PF 0.64, holdout 0.47, ≈ live 0.59. Il subagente A, minando ~150 combo, ha trovato una config **eq-weight 0.33/0.33/0.34 + R:R 2.5/2.0 H1-only** che passa `is_promotable` sull'holdout (PF 1.51, 4/4 fold) e rende positiva la finestra live. **Ma è di fatto una strategia diversa selezionata mining sull'holdout (contaminazione multi-comparison)** → **NON è stata portata in `signals.py`**. S00 resta hard-blocked (V2). La config V3 è documentata in `backtests/results/opt_s00_2026-09-02.json` come **candidata per un paper-test dedicato** (stesso percorso di S20: 4-6 settimane isolate, gate PF≥1.2/WR≥40%, altrimenti ritiro definitivo). Applicati solo 2 fix di correttezza al call-path S00 (`hour`+`tf` in `get_signal`/`run_one`), neutrali finché il blocco è attivo.

**Restano hard-blocked**: S00_MFKK, S09_MFKK_SCALPING, S18_RANGE_REVERSAL. **S10** tenuta ma lotto NON scalato (campione sottile). **H4 pesa più di M30 che pesa più di H1.**

---

## ✅ 2026-09-02 — Sprint "performance stabile": S17 SL 1.5→1.75×ATR; S10/S09 invariate

Backtester reso realistico in Fase 0 (cost model + fill pessimistico + entry next-open + walk-forward/holdout, `opt_harness.py`). Rivalutate le 3 strategie minori (holdout PF = metrica primaria):

| Strategia | TF | Verdetto | Numeri (holdout / full, backtester realistico) |
|---|---|---|---|
| S17_CONVERGENCE_SCALP | H4 | **retune: SL 1.5→1.75×ATR** (TP 4.0 e param segnale invariati) | standalone PF 0.98→1.32 holdout, 0.90→1.38 full, 4/4 fold positivi, live-window 1.15→1.59; adaptive+RM H4 PF 2.09→2.21 holdout, WR 45.7→50.0 |
| S10_OB_FVG_SCALP | M30 | **invariata, lotto NON scalato** | solo ~19 trade full / holdout n=4 in 2+ anni; nessuna config `is_promotable`; campione troppo sottile per ritoccare |
| S09_MFKK_SCALPING | M30 | **resta hard-blocked** | nessuna config con holdout PF ≥1.15 & n≥30 & full PF ≥1.10; le config con holdout PF ~1.7 hanno full PF 0.6-0.7 e P&L full negativo (coda fortunata). Full PF mai > ~0.75 |

SL S17 1.75 sincronizzato in `risk_guardian.py`, `mt5-bot.py`, `strategy_selector.py` (base_params, era 1.1 outlier), `strategy-engine-v2.py` (3 rami). Dettagli e sweep: `07_self_learning_log.md` 2026-09-02, `backtests/results/opt_minors_2026-09-02.json`.

## ✅ 2026-09-01 — Ri-test completo + S18_RANGE_REVERSAL bloccata + fix bug hard-block

Ri-eseguito il backtest canonico da zero (dati MT5 freschi, `strategy-engine-v2.py --rm` su M30/H1/H4) su richiesta utente, criterio di permanenza nel roster: **WR>50% oppure PF alto e robusto** (non taglio WR rigido — alcune strategie hanno edge asimmetrico, es. S17 WR~45% ma PF 2.2-2.7). Risultato:

| Strategia | TF live | WR ri-test (adattivo) | Note | Stato |
|---|---|---|---|---|
| S16_GOLDEN_SQUEEZE | H1 | 47.2% (+$3009.3/24m) | live recente WR 70.6% PF 2.14 | ✅ attiva |
| S17_CONVERGENCE_SCALP | H4 | 45.7% (+$4181.2/24m) | PF storico 2.2-2.7, edge da R:R non da WR | ✅ attiva |
| S10_OB_FVG_SCALP | M30/regime | 56.2% (+$248.3/24m, n=16) | campione piccolo, da monitorare | ✅ attiva |
| S20_FIB_CONFLUENCE | M5 | OOS PF 1.72 | integrata 2026-09-01, vedi sopra | ✅ attiva |
| S00_MFKK | — | 32-37% nell'adattivo (ma miglior P&L assoluto sui 3 TF nel backtest teorico) | live reale WR 13.3%→50%, molto sotto il teorico — bug trovato (vedi sotto) | ⛔ bloccata (dal 2026-07-16, ora davvero effettivo) |
| S09_MFKK_SCALPING | — | mista (adattivo M30 WR54.3% n=35, standalone debole) | | ⛔ bloccata (dal 2026-07-16, ora davvero effettivo) |
| S18_RANGE_REVERSAL | — | **negativa ovunque**: M30 standalone PF 0.629, M30 adattivo -$89/-98, H4 standalone PF 0.202; live 14.3% WR/PF 0.07 | nessun TP raggiunto negli ultimi 7 trade live | ⛔ **bloccata 2026-09-01** (nuova) |

**Bug trovato e corretto**: il hard-block self-learning (`score_mult=0.0` in `data/strategy_overrides.json`) era letto solo da `StrategySelector`, non dai playbook statici (`REGIME_MULTI_STRATEGIES`, `get_signal()`) che generano la maggioranza dei trade reali — per questo S00_MFKK ha continuato a tradare per settimane nonostante il blocco del 07-16. Fix: `is_hard_blocked()` ora richiamata da `quality_gate()`, punto di passaggio comune a tutti i loop di ingresso. Dettagli: `06_known_issues.md` e `07_self_learning_log.md` 2026-09-01.

## ✅ 2026-09-02 — S20_FIB_CONFLUENCE: sessione ristretta a 8–17 UTC (sprint perf-stabile)

Sweep parametri S20 (harness `opt_harness.evaluate`, holdout PF + gate `is_promotable`, cost model ON) su `FIB_BAND`, `FIB_STRUCT_NEAR/FAR`, `FIB_SL_ATR_K`, `FIB_TP2_R`, `FIB_SESSION`, no-lunedì — anche su M15/M30 come proxy di robustezza. **Unico cambiamento robusto su holdout E su M15+M30**: `FIB_SESSION (7,19) → (8,17)` (solo overlap London+NY liquido). Holdout PF M5 2.37→2.78, M15 1.17→1.58, M30 1.57→3.67; full PF M5 1.51→1.91 con DD -19%. Non tocca SL/TP/entry → **zero impatto sulla size/rischio del book live 0.03**, cambia solo *quando* si opera (via 07:00 e 17:00–19:00 UTC). Tutti gli altri parametri **tenuti** (TP2_R=2.5 e SL_K=1.75 miglioravano M5 ma crollavano su M15 — non robusti). S20 **non** va disattivata: holdout PF M5 ben sopra la soglia 1.2 del piano. Aggiunto flag `FIB_NO_MONDAY` (default True) per rendere il filtro lunedì tunabile. `data/xauusd_m5_mt5.json` fermo al 2026-08-28 (serve MT5 aperto per M5 fresco) — limitazione nota. Dettaglio: `backtests/results/opt_s20_portfolio_2026-09-02.json`.

## ✅ 2026-09-01 — S20_FIB_CONFLUENCE: promossa da isolata a integrata (sizing RiskGuardian ×2)

Portata in `signals.py` (`signal_fib_confluence` + helper `fib_confluence_levels` / `fib_confluence_trade_levels`) la logica di confluenza del Pine scalping "Repro Overlay": estremi 20 barre + candela di inversione + prezzo oltre Fib 0.382/0.618 (swing 50) + ribbon EMA20/50, con **SL/TP sui livelli Fibonacci** (scelta utente) e parziali 50% TP1→BE→50% TP2 (`sim_fib_confluence` in `strategy-engine-v2.py`).

Backtest M5/M15/M30 — port fedele: WR 10–18%, PF 0.49–1.06 standalone. Sprint v1 (90 combo IS/OOS): solo picco isolato non robusto. v2 (ingresso confermato + SL strutturale + EMA200), v3 (BUY: trend stack + momentum + TP largo), v4 (sessione/orari + circuit breaker) — il "filtro orario migliore" era look-ahead, il circuit breaker non scatta a ~3 trade/mese. **Numero onesto**: config di principio (v2 combined + **no-lunedì** + sessione piena London+NY) → full-period PF 1.54, **OOS ultimi 8 mesi PF 1.72** (n=54), walk-forward 1.16/1.23/1.79, BUY+SELL positivi. **Edge debole ma reale e OOS**, nel range di S00.

**LIVE TEST isolato dal 2026-08-28** a lotto fisso 0.03. **Dal 2026-09-01, su richiesta esplicita, promossa a strategia integrata** dopo solo 4gg di test (non i 4-6 settimane originariamente pianificate — deviazione consapevole, vedi `07_self_learning_log.md` 2026-09-01): sizing ora via `RiskGuardian` (composite score/tier/compounding) con **unica eccezione** lotto finale ×2 (`S20_LOT_MULT`); partecipa ai cooldown SL condivisi (globale + per-strategia) e a `MAX_OPEN_ORDERS`. Resta **fuori da `StrategySelector`** (nessun supporto M5 nel selector H1/M30/H4) e la gestione posizione (SL strutturale, TP1 1R parziale + BE, TP2 2R) resta il mini-manager proprio in `mt5-bot.py`, non generica `RiskGuardian` — l'edge backtestato dipende da questa lifecycle specifica. `signal_fib_confluence` in `signals.py` = V2 config di principio. Vedi `04_bot_operations.md` § S20_FIB_CONFLUENCE per il dettaglio implementativo. `S20_FIB_CONFLUENCE` resta in `STRATS` (fuori da ogni `REGIME_PRIORITY_*` del backtester). Dettagli storici: `research/s20_fib_confluence/RESULTS.md`, `07_self_learning_log.md` 2026-08-28.

## ✅ 2026-07-17 — Re-tuning parametri: nessun cambiamento adottato

Sweep IS(80%)/OOS(20%) su parametri di segnale e mult TP/SL delle 5 strategie attive (S00/S16/S09/S10/S17): **nessuna variante ha battuto il baseline in modo robusto** — 2 candidati TP/SL promettenti in isolamento (S00 e S16 con TP 3.5→3.0×ATR) non hanno retto la verifica sul backtest di portafoglio adattivo reale (migliorano un TF, peggiorano gli altri). I parametri attuali restano la configurazione migliore trovata. Dettagli e numeri completi in `07_self_learning_log.md` 2026-07-17. Trovato e corretto anche un bug secondario di routing argomenti in `run_one()` (strategy-engine-v2.py) che azzerava quasi tutti i segnali standalone S09/S10 nelle classifiche Fase 1 (non affettava i numeri canonici adattivi).

**Novità**: `strategy-engine-v2.py` ora salva `equity_curve` (serie `{t, cum_pnl}` per-trade) per ogni strategia nel JSON di output — vedi `strategies[id].equity_curve` (standalone) e `adaptive_rm.by_strategy[id].equity_curve` (portafoglio). Usata dal grafico curva di equità nella sezione Strategie del frontend.

## ⚠️ Refresh 2026-07-17 — SL nel backtester era disallineato dal live (S00/S09/S10/S17)

Cross-check indipendente su TradingView Strategy Tester (port manuale Pine di S00/S16/S17) ha fatto emergere che `strategy-engine-v2.py` testava con SL 1.0×ATR (S00/S09/S17) e 1.2×ATR (S10) invece di **1.5×ATR**, il valore realmente in produzione da 2026-04-30 in `risk_guardian.py::STRATEGY_ATR_PARAMS` e `mt5-bot.py::STRATEGY_PARAMS` (S16 e S18 erano già allineati, nessuna modifica). Il refresh 2026-07-16 sotto era quindi anch'esso calcolato con SL troppo stretti su 4 strategie su 6. Vedi `07_self_learning_log.md` 2026-07-17 per i dettagli.

Numeri freschi post-fix (`--rm`, stessi dati, 0.01 lot):

| TF | N trade | WR% | PF | $/gg | DD | Mesi+ |
|---|---|---|---|---|---|---|
| M30 | 808 | 38.2% | 1.294 | +$23.81 | $1,759 | 9/13 |
| **H1** | **1332** | **40.2%** | **1.277** | **+$33.28** | **$4,418** | **18/24** |
| **H4** | **408** | **40.4%** | **1.725** | **+$56.77** | **$1,299** | **12/23** |

Effetto dello SL corretto rispetto al refresh 2026-07-16 (SL bacato): **WR sale ovunque (+6/+8pp)**, coerente con stop più larghi che tagliano meno trade per rumore intracandela. Ma il **DD H1 quasi raddoppia** ($2,323→$4,418) — il rischio reale del sistema H1 era sottostimato in tutti i numeri documentati finora. Tutte e 3 le TF restano nette positive; H4 resta il miglior profilo rischio/rendimento (PF 1.725, DD più basso in assoluto). File: `backtests/results/bt_{h1,m30,h4}_2026-07-17.json`.

**Le sotto-tabelle "Breakdown per strategia" e "TF ottimale per strategia" più sotto sono ancora sul refresh 2026-07-07/16 (pre-fix SL) — trattale con cautela, non ancora ricalcolate a livello di singola strategia.**

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

> **Trim sprint perf-stabile 2026-09-02** (walk-forward, cost model ON, gate = holdout PF).
> Contributo per (regime × strategia) misurato su holdout; droppati i drag confermati su holdout **e** full period.
> Holdout PF adattivo+RM: **H1 0.95→1.16**, **M30 1.04→1.19**, **H4 1.23** (invariato, solo cleanup, full PF 1.60→1.62).
> Full DD ~dimezzato su H1 (5018→2100) e ridotto su M30. Dettaglio: `backtests/results/opt_s20_portfolio_2026-09-02.json`.
> NB pesatura TF: **H4 > M30 > H1** — H4 tiene l'edge residuo maggiore (S17@H4 holdout PF 2.09, singolo miglior contributo del portfolio); H1 regge solo grazie a S16.
> NB self-learning: `S00_MFKK` / `S09_MFKK_SCALPING` / `S18_RANGE_REVERSAL` sono hard-block in `data/hard_blocks.json` — il backtester non legge quel file, quindi i suoi numeri "grezzi" sono più pessimisti del comportamento live.

### H1 (REGIME_PRIORITY_H1)
- **TREND_UP / WEAK_UP**: S16 → S00
- **TREND_DOWN**: S16 solo *(S00 rimosso: solo long ha edge — TREND_DOWN S00 holdout PF 0.75 / -$780, full 0.92 / -$1277)*
- **WEAK_DOWN**: S16 → S09 *(S00 rimosso: holdout PF 0.58)*
- **RANGE/VOLATILE**: S10 → S09 → S17

### M30 (REGIME_PRIORITY_M30)
- **TREND**: S10 → S00 *(S16 rimosso: TREND_UP full PF 0.82 / -$599)*
- **WEAK**: S10 → S16 → S09 → S00 *(S18 rimosso)*
- **RANGE**: S10 → S09 → S17 *(S18 rimosso: holdout PF 0.51 / -$187, full 0.86 / -$184)*
- **VOLATILE**: S09 → S10 → S17

### H4 (REGIME_PRIORITY_H4)
- **TREND**: S16 → S17 → S00
- **WEAK_UP**: S16 → S17 → S00
- **WEAK_DOWN**: S17 → S00 *(S16 rimosso: n=2, -$158)*
- **RANGE/VOLATILE**: S17 → S00

## Strategie Attive nel Bot

| ID | Label | TP mult | SL mult | Regimi ottimali | TF primario | PF sistema | WR adattivo |
|---|---|---|---|---|---|---|---|
| `S00_MFKK` | MFKK Core V2 | ATR×3.5 | ATR×1.5 | tutti (fallback) | H1/M30 | 1.863 H1 | 52.3% H1, 49% M30 |
| `S09_MFKK_SCALPING` | MFKK Scalping V3 | ATR×4.0 | ATR×1.5 | VOLATILE, WEAK, RANGE | **M30** | 1.534 M30 | 41.2% |
| `S10_OB_FVG_SCALP` | OB+FVG Scalp V3 | ATR×3.5 | ATR×1.5 | RANGING, WEAK, TREND | **M30 only** | 1.534 M30 | 49.0% |
| `S16_GOLDEN_SQUEEZE` | Golden Squeeze V5 | ATR×3.5 | ATR×2.0 | TREND | **H1** | 1.863 H1 | 51.0% |
| `S17_CONVERGENCE_SCALP` | Convergence Scalp V2 | ATR×4.0 | ATR×1.75 | VOLATILE, TREND | **H4** | 1.993 H4 | 34.3% |
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
2. `tracker.auto_apply_adjustments()` — confronta WR recente vs baseline backtest, scrive `data/strategy_overrides.json`. Le strategie in `data/hard_blocks.json` sono forzate a `score_mult 0.0` e mai ri-valutate qui.
3. `tracker.get_recent_wr_map()` → `{strategy_id: wr}` passato a `StrategySelector.select(recent_wr_map=...)`
4. In `_score_strategy()`: punteggio finale moltiplicato per `score_mult` da overrides; `is_hard_blocked()` (che legge `hard_blocks.json`) forza score 0

### Hard-block esecuzione live (`data/hard_blocks.json`) — 2026-09-03

Fonte di verità del "questa strategia non deve tradare live": **file git-tracked, editabile solo a mano o da `reactivation_check.py`**, MAI scritto dal bot. Letto da `strategy_selector.is_hard_blocked()`, primo check di `mt5-bot.quality_gate()` (comune a tutti i 6 loop di ingresso). Prima viveva in `strategy_overrides.json`, che però il bot riscrive a runtime ed è (era) git-tracked → sulla VPS working tree dirty → `git pull` non aggiornava il blocco e S00/S09/S18 continuavano a tradare (vedi `07_self_learning_log.md` 2026-09-03). `strategy_overrides.json` / `performance_cache.json` / `ai_score_history.json` sono ora **gitignored** (stato runtime locale VPS).

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
> Cache trade: `data/performance_cache.json` (max 500 trade, **gitignored**). Overrides soft: `data/strategy_overrides.json` (**gitignored**, riscritto dal bot). Hard-block: `data/hard_blocks.json` (**git-tracked, human-only**).

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
