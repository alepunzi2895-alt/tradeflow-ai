# TradeFlow AI — Strategie Attive

## 🆕 2026-09-10 — Strategie da combo indicatori dei layout TradingView XAU — TUTTE respinte

Richiesta utente: dai layout TradingView `XAU_M15` / `XAU_M30` / `XAU_H1_Volumes` /
`Default` (tutti tranne `MFKK_GOLD` = già S00), costruire strategie dalle **combo degli
indicatori presenti sui grafici** e tunarle finché profittevoli (BE + trailing sempre).

I 4 layout non-MFKK condividono lo stesso toolkit discrezionale (verificato via
`data_get_indicator` sull'istanza CDP di TradingView Desktop):

| Indicatore | Parametri letti dal layout |
|---|---|
| Trendlines with Breaks [LuxAlgo] | swing length 14, slope calc = ATR × 1 |
| Pivot Points Standard | type **Fibonacci**, anchor Auto (daily su M15) |
| Key Levels SpacemanBTC IDWM v15 | PDH/PDL, PWH/PWL, session H/L |
| Moving Average Exponential | length **200**, close (vero EMA200, non l'alias e233) |
| Sessions [LuxAlgo] | London / NY / Tokyo / Sydney (usato solo come filtro `hour`) |

**Port fedeli aggiunti a `strategy-engine-v2.py::compute_all()`** (nuovi array, zero impatto
sulle strategie esistenti): `luxalgo_trendline_breaks()` (port dell'alertcondition
`ta.crossover(src, upper − slope_ph·length)`), `daily_fib_pivots()` (P/R1-3/S1-3 Fibonacci +
PDH/PDL/PWH/PWL, causale), `ema200`. 3 signal fn in `signals.py` (record storico, **non
wired** in `STRATEGIES_CONFIG`/`PLAYBOOK`/`REGIME_PRIORITY_*`):

- `signal_tlb_trend` (SA) — trendline break in direzione EMA200 + sessione + ADX gate
- `signal_pivot_reversal` (SB) — rifiuto (wick) del livello Fib/key più vicino, regime range
- `signal_pivot_break` (SC) — breakout di continuazione oltre un livello Fib + EMA200

**Esito: 180 trial (`opt_harness.evaluate`, cost model ON, walk-forward + holdout), TUTTI
negativi.** Full-period PF < 1.0 su **ogni** configurazione — direzione (trend / fade /
no-EMA / breakout / reversal), TF (M15/M30/H1), grid tp/sl 1.0-3.5×ATR. Ceiling full PF
≈ 0.85 con trade count reale (n ≥ 100). Gli unici holdout PF > 1 sono su n = 4-7 trade
(SA_TLB_FADE H1 holdout PF 1.42 / full PF 0.52 / full pnl −180 — la solita "coda fortunata"
già vista con S10/S09), DSR non calcolabile. 0-1 fold positivi su 4 quasi ovunque.

**Sprint 2-3 (stesso giorno, "spingi più a fondo" richiesto dall'utente)** — altre 4 strutture,
genuinamente diverse dalle prime 3, + robustness sweep:
- `luxalgo_trendline_breaks()` ora produce anche `tlb_up_s`/`tlb_dn_s` (crossover della linea
  al valore CORRENTE `close > upper`, senza la proiezione `−slope·length` dell'alertcondition
  ufficiale — trigger più stretto e pulito).
- `signal_tlb_confluence` (SD): TLB break stretto + cross di un pivot Fib concorde + EMA200 + sessione.
- `signal_pivot_bias_pullback` (SE): bias dal pivot giornaliero, buy-the-dip su S1/EMA200 con candela di inversione.
- `signal_session_range_break` (SF): opening-range breakout Londra + bias pivot.

Esito sprint 2-3 (252 trial): **SE / SF / SD tutti full PF 0.4-0.8** (SE e SF fortemente
negativi anche con n grande, ~600-1000 trade). **L'unico flicker**: `signal_tlb_trend` con
`strict=True` (trigger `tlb_up_s`) trend-following su **H1**, EMA200 + sessione 7-20 + ADX
18-22, **sl ≈ 1.5×ATR** → full PF 1.2-1.6, holdout PF 1.3-1.5. **Ma non promuovibile**:
n = 44-65 su 24 mesi (fragile come S10), DSR non significativo, **knife-edge sullo SL**
(sl 1.25 → full PF 0.5 catastrofico; sl 1.75 → 0.8-1.1 mediocre — un edge vero degrada
con grazia, questo no), 1-3 fold positivi su 4, e **P&L assoluto +157÷261 $ su 24 mesi**
a 0.01 lot (≈ $7-11/mese — sotto ogni soglia di rilevanza pratica). Ogni variante vicina
(ADX 15, no-EMA, sessione 0-24, sessione NY-only, M30/H4) è negativa o rumore da n<20.

**Sprint 4 (max-effort, richiesto: "usa le skill di trading + subagenti + tuning fino a
renderle performanti")** — skill `signal-classification` + `walk-forward-validation` +
`regime-detection` + `exit-strategies`. Nuova infrastruttura di ricerca (SOLO research,
non importata da mt5-bot.py):
- `scripts/layout_features.py` — 43 feature CAUSALI dai 4 indicatori del layout (distanze
  in unità ATR: trendline break/stato, Fib pivot P/R1-3/S1-3, key level PDH/PDL/PWH/PWL,
  EMA200 dist+slope, sessioni LuxAlgo, contesto di regime ADX/ATR-pct/BB-width/RSI).
- `scripts/layout_ml.py` — LightGBM (`pip install lightgbm`), walk-forward **rolling**
  (train ~180g / test ~30g / embargo = horizon, purge), 8-11 fold, prob OOS per barra,
  gain + permutation importance, threshold optimization.
- `scripts/layout_sim.py` — backtest con lifecycle di uscita **parametrizzabile** (hard
  stop ATR → BE → trailing fisso/**Chandelier** → time-stop, parziale opz. a 1R), riusa
  cost model / `resolve_intrabar` / `walk_forward_report` di strategy-engine-v2.py.
  `evaluate_ml()` (soglia sulle prob) + `evaluate_confluence()` (punteggio pesato).

**Esito (≈45 trial)**: **AUC OOS 0.516 (M30) / 0.516 (M15) / 0.526 (H1)** — *sotto* il
baseline 0.579 di `feature_screen.py` con il catalogo completo: le feature specifiche di
questi layout sono MENO informative degli indicatori generici. Backtest (threshold sweep
0.58-0.66, long-only, short-only, regime-gate trend/range, exit chandelier/partial/time-stop,
confluence-score pesato ADX-gated): **full PF 0.48-0.72 su OGNI combinazione, 0/4 fold
positivi.** Gli unici holdout PF > 1 sono su n=22-27 (rumore). Feature più importanti,
coerenti su tutti e 3 i TF (gain **e** permutation): `dist_pwh`/`dist_pwl` (distanza da
massimo/minimo settimana precedente) — conferma l'effetto debole (Cohen's d ~0.2) già
trovato il 2026-09-07, non abbastanza per un edge tradabile.

**Sprint 5 (dopo feedback utente: "queste strategie se usate bene funzionano, usa un po'
di intelligenza")** — cambio di impostazione: invece di mecccanizzare "compra ogni rottura",
codificato **come si trada davvero** questo toolkit:

> REGIME (solo trend pulito: EMA200 in pendenza ≥ k·ATR) → TRIGGER (rottura trendline
> LuxAlgo stretta nel verso del trend, si **memorizza** il livello, non si entra) →
> **RETEST** (nelle K barre il prezzo torna su una **ZONA DI CONFLUENZA**: ≥ `min_lv`
> livelli tra Fib pivot, PDH/PDL/PWH/PWL, H/L sessioni, prev-4H, EMA200, trendline, entro
> `band`·ATR) → ENTRY (candela di rifiuto alla zona) → STOP **strutturale** oltre la zona
> (cap `stop_max`·ATR) → TP1 fisso 1.5R parziale 50% → BE → **trailing dietro la trendline**
> → runner alla zona successiva. Sessione London+NY, niente venerdì pomeriggio.

`scripts/layout_smart.py` — `session_levels()` aggiunto a `compute_all()` (H/L ultima
sessione Asia/London/NY completata + prev-4H + day open, causale). `evaluate_smart()` +
`CANDIDATE_H1`. Grid entry(72)+exit(60)+loosen(72)+robustness(26).

**RISULTATO — prima config con edge reale in ≈700 trial di ricerca sul layout.**
`CANDIDATE_H1` (H1, slope 0.12, retest≤16, min_lv 2, wick 0.22, band 0.55, trail=trendline,
stop_max 2.8, TP1 fisso 1.5R, sessione 7-21 UTC):

| metrica | valore |
|---|---|
| full period (22m) | **PF 1.99**, +$516 @0.01 lot, DD **$130**, WR 52.8%, 16/22 mesi+ |
| HOLDOUT (da 2026-03-17) | PF **1.86** (n=10), +$130 |
| finestra live (apr-lug 2026) | PF **1.66** (n=7) |
| walk-forward | fold PF 2.03 / **0.39** / 3.69 / 2.78 — **3/4 fold+** |
| direzioni | buy n37 WR57% +$281 · sell n16 WR44% +$235 (entrambe reali) |
| per anno | 2024 +$30 · 2025 +$190 · **2026 +$296** (edge NON decaduto) |
| robustezza | fPF 1.5-2.3 su ~20 perturbazioni di parametro · **PBO 0.33 (non overfit)** · regge spread×2 (fPF 1.92) · top-3 winner = 31% del gross (no dipendenza da poche trade) |

**Limiti (per cui è paper-test, non roster):** n=53 in 22 mesi (~2.4/mese, sottile come
S10) · **fold 2 negativo** (equity lumpy, 68% del tempo sotto il picco) · **DSR
inconcludente** (holdout n=10 troppo corto per uno Sharpe, deflazionato da 1036 trial) ·
sensibile alla sessione (7-17 crolla a fPF 1.45/hPF 0.48) · **solo H1** (M30/M15 breakeven
fPF 0.91-0.96, H4 n=12) · $ assoluto piccolo a 0.01 lot (~$23/mese) · dati XMGlobal, la
TV dell'utente è FPMARKETS (feed diverso).

**Sprint 5b — altri layout (M15/M30) + volume, stesso trattamento (456 trial)**:
- **M15 (layout XAU_M15)**: MORTO — fPF ~1.0, 0-1/4 fold; ogni config con "buon holdout" ha
  full P&L negativo (coda fortunata).
- **M30 (layout XAU_M30)**: con filtro **volume** dal layout XAU_H1_Volumes (`vol_min≥1.0`
  sulla candela di rifiuto) fPF 1.28-1.38, hPF 1.95, n~79, 2-3/4 fold — MA **PBO 0.53
  (`is_overfit=True`)**: la selezione tra varianti M30 è più-probabile-che-no overfit.
- **XAU_H1_Volumes**: il filtro volume aiuta poco su H1 (fPF 1.99→2.11 ma n 53→39, hPF cala).
- → **SOLO H1.** Filtro `vol_min` aggiunto a `layout_smart` / `signals.LS_PARAMS` (default 0).

**Verdetto — INTEGRATA NEL ROSTER (2026-09-10, richiesta esplicita utente "come strategia
reale insieme alle altre").** Percorso S20: blocco dedicato `_ls_*` in `mt5-bot.py` (H1),
**sizing via RiskGuardian**, cooldown SL condivisi, **conta in `MAX_OPEN_ORDERS`**, fuori da
StrategySelector (segnale stateful proprio). Lifecycle propria (SL strutturale + TP1 1.5R
parziale + BE + trailing su trendline) — RiskGuardian non la tocca (`'S20' in comment or
'S31' in comment` → skip). Lotto iniziale via RiskGuardian tier (fallback 0.02).
- `scripts/layout_indicators.py` — indicatori dei layout, **source of truth condivisa**
  engine↔bot (`compute_layout_indicators()` in `compute_all` E `compute_indicators`).
- `signals.py::ls_scan` / `ls_manage_step` / `LS_PARAMS` — core stateful, usato da backtest
  (`layout_smart.evaluate_ls_frozen`) E bot (`_ls_check_entry` / `_ls_manage`). Verificato
  che riproduce la config candidata (frozen full PF 1.95 == grid harness 1.99).
- `strategy-engine-v2.py::layout_smart_trades` + flag `--layout-smart` → overlay parallelo
  al portafoglio H1. **Impatto portafoglio H1 adattivo+RM (walk-forward, cost model ON):
  PF 1.519→1.534 · P&L +$499 · DD $2099→$2013 (−$86) · mesi+ 17/24 invariati · 4/4 fold.**
  Additivo e leggermente DD-riducente (decorrelato), non danneggia nulla.
- `risk_guardian.STRATEGY_ATR_PARAMS`, `mt5-bot.STRATEGY_PARAMS`,
  `performance_tracker.BACKTEST_BASELINES` (wr 0.528 / pf 1.95): voci S31 aggiunte.

Gate di permanenza (come S20/S30): rivedere dopo 4-6 settimane live — se PF < 1.2 o WR <
40% su ≥ 15 trade → `LS_ENABLED=False`. n così sottile (~2.4 trade/mese) → il verdetto live
arriverà lento. `STRATEGIES_CONFIG` invariato (i blocchi paralleli S20/S30/S31 non ci vanno,
sono tracciati dal commento ordine via `performance_tracker`).

**Lezione**: l'utente aveva ragione — la mecccanizzazione naïve ("ogni rottura, stop ATR")
era il problema, non gli indicatori. Encodando retest + zona di confluenza + stop
strutturale + trailing sulla trendline l'edge emerge (fPF 0.4-0.85 → 1.99). Coerente con
la nota sui segnali Telegram: "gestisce i trade più attivamente del modello".

**File**: `backtests/results/layout_smart_candidate_2026-09-10.json` (+ `smart_grid_*`),
`layout_combos_2026-09-10.json`, `data/layout_ml_probs_*.json`. `research_trials.json`:
329 → 1036. Infrastruttura (`layout_features/ml/sim/smart.py`, signal fn SA-SF) tenuta.

## 🆕 2026-09-07 — Backtest segnali Telegram COSÌ COME SONO (entry/SL/TP dichiarati)

`scripts/telegram_signal_backtest.py` + `scripts/ivan_lot_sizing.py` — a differenza dello
studio di reverse-engineering (che analizza il *timing*), qui si simula esattamente quello
che il canale ha dichiarato: entry range, SL, 4 TP a gamba equa con lot sizing dalla
tabella fornita dal provider (screenshot utente, dimezzata su richiesta esplicita
"dimezziamo i lottaggi però per ora"). Risponde alla domanda diretta: seguire questi
segnali sarebbe stato profittevole?

**2 bug trovati e corretti durante l'implementazione** (entrambi avrebbero gonfiato/distorto
il risultato):
1. `parse_telegram_signals.py::SL_PAT` non gestiva il formato `SL @ 2908` (il canale è
   passato da `SL: X` a `SL @ X` a un certo punto) — 942/1088 segnali avevano `sl=None`
   prima del fix. Un refuso reale del canale (`SL @ 48328` invece di ~4832) è stato
   scartato con un filtro di sanità (`MAX_SANE_DISTANCE=150`, oltre il p99 empirico ~88).
2. Segnali antecedenti l'inizio dei dati M15 disponibili (agosto 2024, ma i segnali
   partono da marzo 2024) venivano comunque "riempiti" contro prezzi di mesi/anni dopo
   (bug: `bisect_left` su timestamp fuori range ritorna indice 0 silenziosamente) —
   fix: scarto esplicito se `ts_unix` fuori dal periodo coperto dai dati.

**Risultato (1076 segnali XAUUSD, 948 con dati sufficienti, ~3750 gambe TP simulate,
balance riferimento 1000€, lotto dimezzato, cost model realistico riusato da
strategy-engine-v2.py)**:

| TF | full PF | full pnl | HOLDOUT PF | HOLDOUT pnl |
|---|---|---|---|---|
| M15 | 0.83 | -6173.5 | 0.454 | -6364.4 |
| M30 | 0.778 | -8245.5 | 0.441 | -6415.1 |

**Perdita netta su entrambi i timeframe testati, più marcata nell'holdout (ultimi ~5 mesi,
811-835 trade)** — risultato consistente tra M15 e M30 (cross-check), non un artefatto di
un singolo TF. L'utente ha una percezione soggettiva positiva ("lo seguo da anni, è
profittevole") — possibili spiegazioni della divergenza: non prende tutti i segnali,
gestisce i trade più attivamente del modello (trailing/chiusure discrezionali oltre al
semplice "SL a BE dopo la prima gamba TP" assunto qui), o la sua esperienza reale diverge
dal backtest per ragioni non catturabili dal solo testo dei messaggi. Da tenere presente
prima di decidere se rendere questa strategia live.

**Aggiornamento — trailing stop invece di SL fisso a BE** (richiesto dall'utente, `--trailing`):
0.3×ATR dopo la prima gamba TP (stessa convenzione di `risk_guardian.py::ts_step_usd`),
al posto dello SL fisso a breakeven. Migliora ma non ribalta il quadro:

| TF | full PF (trailing) | HOLDOUT PF (trailing) |
|---|---|---|
| M15 | 0.928 (WR 47.7%) | 0.580 |
| M30 | 0.882 (WR 47.1%) | 0.553 |

**Pattern più interessante del numero aggregato**: sia con SL-fisso che con trailing, sia
su M15 che su M30, i **fold di training sono vicini/sopra PF 1.0 (spesso 3-4/4 positivi)
ma l'HOLDOUT (ultimi ~5 mesi) crolla sistematicamente** (PF 0.44-0.58). Stesso pattern di
"edge decaduto di recente" già scoperto per le strategie proprietarie del progetto nello
sprint 2026-09-02 — non un caso isolato di questo canale.

**Chiusure discrezionali NON modellate**: la maggior parte dei messaggi di gestione del
canale sono istruzioni relative e ambigue ("chiudete le voci alte, tenete quelle basse")
che si riferiscono a ingressi multipli paralleli — un concetto che il modello attuale
(1 entry + 4 TP a gamba fissa) non rappresenta, e non ricostruibile in modo affidabile dal
solo testo. Tentare di forzarlo avrebbe prodotto un numero preciso ma inventato — omesso
deliberatamente piuttosto che stimato male.

**Non ancora inserita come strategia live/sempre-attiva** — richiede conferma esplicita
separata (vedi nota di conformità sopra). Il pattern "training ok, holdout recente in
crollo" è un argomento in più per la cautela, non per l'urgenza di renderla live.

**Aggiornamento — confidence score regime-based (richiesto dall'utente)**: testato come
filtro (apri solo se ≥2/3 criteri allineati: DI dominance, ADX≥20, trend EMA233 — le
feature validate nello screening ML di oggi) e come sizing (lotto scalato 0.5x-1.0x in
base allo score). Soglie fissate PRIMA di vedere i risultati (`CONF_FILTER_THRESHOLD=0.67`,
`CONF_SIZE_MIN_MULT=0.5`), nessun tuning successivo.

**Risultato: peggiora in tutte e 4 le combinazioni testate** (filtro/sizing × M15/M30) —
es. M15 trailing PF 0.928 → 0.70 con filtro, → 0.879 con sizing. Il filtro inoltre taglia
il campione da 3750 a 793 gambe (81% escluso), aumentando la varianza oltre a peggiorare
il PF medio. **Ipotesi respinta**: l'allineamento con il regime tecnico proprietario del
progetto non è un buon proxy per la qualità dei segnali di questo canale specifico — non
sorprendente, dato che il canale segue una logica discrezionale non necessariamente legata
agli stessi indicatori. Filtro news (richiesto in parallelo) non backtestabile
retroattivamente: `news_guardian.py` tiene solo cache "settimana corrente", nessun
archivio storico dal 2024 — applicabile solo in avanti (Fase 1 listener / eventuale Fase 2).

## 🆕 2026-09-07 — Listener live segnali Telegram (FASE 1: solo log, nessun ordine)

`scripts/telegram_signal_listener.py` — ascolta in tempo reale il canale via Telethon
(user client, non bot — il canale è privato e l'utente non lo amministra) e logga i
segnali riconosciuti con lo stesso parser di `parse_telegram_signals.py` (riusato, non
duplicato). **Nessun ordine MT5 viene aperto/chiuso/modificato** — è deliberatamente solo
osservazione. Log in `data/telegram_live_signals.jsonl` (gitignored).

> ⚠️ **Stessa nota di conformità di sopra, più stringente qui**: un listener automatico
> continuo è più vicino alla pratica di "mirroring" che il provider vieta esplicitamente
> (citano CONSOB) rispetto allo studio storico una tantum. L'utente ha confermato
> esplicitamente di voler procedere comunque, consapevole della distinzione. **Una
> eventuale Fase 2 (esecuzione reale di ordini MT5 dal listener) richiede una conferma
> esplicita separata — non va mai aggiunta come estensione naturale senza chiederlo di
> nuovo.**

Setup (da fare dall'utente, MAI da Claude — richiede login interattivo con OTP):
`TELEGRAM_API_ID`/`TELEGRAM_API_HASH` da https://my.telegram.org/apps in `.env`,
`TELEGRAM_CHANNEL_ID` (2112242007 per IvanTrades VIP, dall'export 2026-09-07). Primo
avvio chiede telefono+OTP nel terminale dell'utente; sessione poi salvata in
`data/telegram_session.session` (gitignored).

**Aggiornamento — news_guardian integrato (solo osservazione)**: ogni `ENTRY_SIGNAL`
rilevato viene arricchito con `news_paused`/`news_risk_mult`/`news_reason` da
`news_guardian.py::check_news_risk()` e loggato insieme al segnale. Possibile solo qui
(prospettico) e non nel backtest storico — `news_guardian.py` non ha archivio, solo cache
rolling della settimana corrente (vedi sopra). Decisione dell'utente 2026-09-07: continuare
ad osservare in avanti con il listener (Fase 1) invece di continuare a cercare aggiustamenti
al backtest storico, dato che i tentativi onesti finora (trailing, confidence score) non
hanno ribaltato il quadro negativo.

Messaggi di gestione (BE/chiusura/SL hit) sono in linguaggio libero, non strutturato come
gli entry signal — vengono solo FLAGGATI per revisione manuale (`MANAGEMENT_KEYWORDS`),
non parsati/agiti automaticamente: il rischio di misinterpretare testo libero come comando
è troppo alto per farne trigger automatici.

## 🆕 2026-09-07 — Studio segnali storici da canale Telegram privato (reverse-engineering)

`scripts/parse_telegram_signals.py` + `scripts/telegram_signal_study.py` — dato un export
JSON di Telegram Desktop ("Export chat history") di un canale segnali, estrae SOLO i dati
strutturati (asset/direzione/entry range/SL/TP/timestamp UTC), **mai il testo grezzo dei
messaggi**, e confronta lo stato degli indicatori (stessa feature matrix di
`feature_screen.py`) nei bar precedenti ai segnali contro un baseline, sia con effect size
univariato (Cohen's d) che con un classificatore multivariato (RF + permutation importance,
holdout out-of-sample).

> ⚠️ **Nota di conformità**: il canale usato come sorgente (servizio VIP a pagamento) dichiara
> esplicitamente nella propria FAQ che copia/condivisione dei segnali è vietata (citano una
> comunicazione CONSOB sul mirroring) e forniscono range invece di livelli precisi apposta per
> impedirlo. Procedere con l'estrazione è stata una scelta esplicita e consapevole dell'utente
> (proprio abbonamento, uso personale di ricerca) — **`data/telegram_signals.json` NON va mai
> committato** (è in `.gitignore`), solo il codice di analisi è tracciato in git.

**Risultato 2026-09-07** (canale IvanTrades VIP, 1087 segnali XAUUSD marzo 2024–set 2026,
963 allineabili ai dati H1 disponibili, 560 buy/404 sell):
- Cohen's d univariato: **nessuna feature con effetto oltre "piccolo"** (max |d|=0.35,
  `atr_regime` — sia buy che sell tendono a occorrere con ATR corrente sotto la propria
  media mobile 30, cioè in una "pausa" di volatilità locale, non in uno spike).
- Classificatore multivariato (RF, holdout out-of-sample): **AUC 0.567 (buy) / 0.557 (sell)**
  — segnale debole, più debole di quello trovato oggi per il forward-return generico (AUC
  0.579). Nessuna feature dominante interpretabile (importance sparse su force_index/aroon
  per buy, hist_volatility/donchian per sell).

**Conclusione onesta**: non emerge un setup tecnico meccanico forte dietro le chiamate del
canale — compatibile con un processo decisionale discrezionale/multi-fattore (price action,
S/R, contesto fondamentale) che uno snapshot di indicatori single-bar non cattura bene, o con
un edge del provider che non sta nel *timing* dell'entry ma altrove (risk management, size,
selezione). **Nessuna funzione segnale scritta da questo studio** — il segnale trovato è
troppo debole per giustificarla, si ripeterebbe l'errore già visto oggi con S21/S22.

Prossimo passo naturale (non fatto, richiede conferma): invece di reverse-engineering
dell'entry timing, backtestare i segnali COSÌ COME SONO (entry/SL/TP dichiarati) per capire
se seguirli sarebbe stato profittevole — una domanda diversa e più diretta, che userebbe gli
stessi dati già estratti.

**Aggiornamento 2026-09-07 (key level, tutti i TF)** — `scripts/key_levels.py`: 15 feature
di livello chiave (PDH/PDL, PWH/PWL, pivot point classico + R1/R2/S1/S2, distanza da round
number $10/$25, swing high/low fractal 5-barre, posizione/distanza Fibonacci sull'ultimo
swing) — nessuna presente prima in `compute_all()`/`extra_indicators.py` (tutte le feature
esistenti erano "forma" — oscillatori/medie — non "livello"). Studio ripetuto su
M5/M15/M30/H1/H4 con `telegram_signal_study.py --all-tf`.

**Caveat dati**: M5 copre solo le ultime ~99999 candele (~11 mesi, limite MT5) contro 2.5
anni di segnali — solo 14-17 segnali BUY overlap, risultato M5 statisticamente inaffidabile
e scartato. M15/M30/H1 hanno copertura piena (~540-560 segnali allineati su ~555-562 totali).

**Risultato**: AUC out-of-sample **consistente 0.54-0.57** su M15/M30/H1 (buy e sell) — non
migliora sostanzialmente rispetto allo studio senza key-level di prima (H1 era già
0.567/0.557). H4 sotto 0.5 su entrambe le direzioni (holdout troppo corto, 570 righe, rumore).
Però: **pivot/R1/R2/PDH/PWH ricorrono con effetto Cohen's d 0.13-0.26 in modo coerente su
3 timeframe indipendenti** (M15, M30, H1) — più difficile da liquidare come puro rumore
rispetto a un singolo risultato isolato. Il pattern più chiaro: i **SELL** del canale
tendono a occorrere con prezzo SOTTO pivot/R1/PDH (fallimento a tenere sopra il massimo di
ieri/il pivot) — sui BUY la relazione è molto più debole. **Round number ($10/$25)** emerge
come feature più importante nel classificatore multivariato SELL su H4 e compare ripetuto
in H1/M30 SELL — segnale minoritario ma presente.

**Conclusione**: i key level aggiungono un contributo reale ma piccolo, non trasformativo —
l'ipotesi dell'utente aveva del merito (i livelli SELL sono più informativi delle sole
"forme" indicatore), ma il segnale resta nella stessa fascia debole (AUC 0.54-0.57) che ha
già fatto scartare S21/S22 oggi. Non ancora tradotto in una funzione segnale — da valutare
se vale la pena tentare un'ipotesi SELL-only mirata (prezzo sotto pivot/PDH + round number
vicino) con lo stesso rigore (opt_harness.py + DSR) prima di procedere.

## 🆕 2026-09-07 — Pipeline ricerca strategie: registro trial + feature screening ML

Infrastruttura per creare/testare nuove strategie a cadenza regolare (manuale, non cron —
niente automazione non presidiata su un conto live) senza ripetere l'errore di oggi
(re-tuning aggressivo senza correzione statistica onesta):

**1. `scripts/research_trials.py`** — registro cumulativo persistente (`data/research_trials.json`).
Ogni sessione di ricerca (grid search, feature screening) DEVE chiamare `record_trials()` dopo
aver aggregato i risultati, e ogni uso di `dsr_check()`/`is_promotable(..., num_trials=...)` DEVE
passare `total_trials()`, mai un numero scelto a mano — altrimenti il DSR mente per ottimismo
man mano che la cadenza di ricerca si accumula nel tempo. Baseline 2026-09-07: 290 trial totali
(288 dello sprint reparametrizzazione + 2 sessioni di feature screening, vedi sotto).

**2. `scripts/extra_indicators.py`** — 18 indicatori extra dal catalogo standard TradingView non
presenti in `compute_all()`: Ichimoku, Parabolic SAR, Awesome Oscillator, MFI, CMF, Aroon,
Vortex, TRIX, Ultimate Oscillator, Choppiness Index, Elder Ray, Force Index, Coppock Curve,
DPO, Donchian Channels, Chandelier Exit, Historical Volatility, Fisher Transform. Formule
standard pubbliche (non richiesto l'uso di TradingView MCP — riservato a casi con ambiguità
di formula/parametri). **Solo per ricerca** — mai importato da `signals.py`/`mt5-bot.py`.

**3. `scripts/feature_screen.py`** — feature screening ML (skill `signal-classification`):
combina i ~44 indicatori di `compute_all()` + 18 di `extra_indicators.py` + 61 pattern
candlestick TA-Lib (`pip install TA-Lib`, wheel precompilato Windows/Py3.12, nessuna
compilazione C richiesta) = **~123 feature candidate**. Le feature price-level (EMA, Bollinger,
Ichimoku, Donchian, ecc.) sono normalizzate come distanza in unità ATR — usare il prezzo grezzo
avrebbe fatto imparare al modello solo il drift secolare (stesso bug scoperto sul Hurst exponent,
vedi sezione sotto). RandomForest fit su 80% train, **permutation importance misurata SOLO
sull'holdout 20%** (out-of-sample, stesso schema di `opt_harness.py`) — non è un modello da
mettere in produzione, serve solo a dire quali indicatori meritano una strategia rule-based
scritta a mano in `signals.py`.

```bash
cd scripts
python feature_screen.py --asset XAU --tf H1 --horizon 10
python feature_screen.py --asset US30 --tf H4 --horizon 6
```

**Risultati baseline 2026-09-07**:
- **XAU H1** (horizon 10 barre): AUC holdout 0.579 — segnale modesto ma reale. Top feature:
  distanza da EMA233, TRIX, StochRSI-D, breakout Donchian upper, ADX, MFI, Choppiness Index,
  Elder Bear Power. Candidato per una nuova ipotesi di segnale rule-based (trend-following su
  EMA lunga + conferma momentum/volume) — non ancora scritta in `signals.py`.
- **US30 H4** (horizon 6 barre): AUC holdout 0.483 (sotto il caso) — **non affidabile**, n=1366
  totali/274 holdout troppo piccolo (stesso problema di scarsità dati di `S10_OB_FVG_SCALP`,
  vedi sotto). Da ripetere quando ci sarà più storico.

**Aggiornamento 2026-09-07 (stesso giorno)** — ipotesi tradotta e testata:
`signal_ema_trend_confluence` (`S21_EMA_TREND_CONFLUENCE`) in `signals.py` — EMA233/200/100
allineate + ADX≥20 + DI dominance + MACD histogram concorde + StochRSI K/D cross come timing.
Grid tp/sl (7 trial, registrati in `research_trials.json`): **full-period PF<1 su tutte le 7
configurazioni** (0.66-0.89) — l'AUC 0.579 del classificatore non si è tradotto in un edge
reale una volta discretizzato in regole esplicite. L'holdout mostrava a tratti PF>1 ma su
n=18 trade con full-period negativo è rumore, non edge (stesso pattern di S10_OB_FVG_SCALP
oggi). **NON promossa**, funzione presente in `signals.py` ma non wired in `STRATEGIES_CONFIG`/
`PLAYBOOK` — tenuta come record storico dell'ipotesi, zero impatto sul bot live.

Lezione per la prossima iterazione: il trigger StochRSI K/D-cross butta via troppa
informazione del classificatore (l'AUC misura la separabilità continua, non garantisce che
un trigger binario arbitrario la catturi). Prossimi esperimenti da provare: trigger meno
rigido (es. soglia su probabilità invece di crossing discreto), oppure promuovere TRIX/
Choppiness/MFI da `extra_indicators.py` (research-only oggi) nel path live invece di
limitarsi ai soli indicatori già in `compute_all()`/`compute_indicators()`.

**Aggiornamento 2026-09-07 (seconda ipotesi)** — TRIX/Choppiness Index/MFI promossi da
`extra_indicators.py` (research-only) a `compute_all()`/`compute_indicators()` (path live),
tramite import condiviso della stessa funzione (zero rischio di divergenza backtest↔live,
a differenza del bug storico ADX Wilder/SMA — vedi `01_data_sources.md`). Nuova ipotesi
`signal_trix_chop_confluence` (`S22_TRIX_CHOP_CONFLUENCE`): Choppiness<38.2 (soglia standard
"mercato in trend") + prezzo vs EMA233 + TRIX concorde e in crescita (trigger continuo,
non discreto) + MFI in fascia utile. **Anche questa NON promossa**: full-period PF<1 su
tutte le 13 configurazioni testate (0.52-0.77) — rigetto più netto di S21, l'holdout non
mostra nemmeno un falso positivo isolato. Tentativo di affinamento (filtro dominanza DI)
ha dato risultati IDENTICI alla v1 — il filtro era ridondante, non la causa. Il problema
è la selettività: il setup lascia passare troppi trade marginali (~3.1/giorno).

**Bilancio delle prime due ipotesi ML-driven**: entrambe respinte onestamente dal processo
di validazione, nessuna promozione forzata. Indicazione per la prossima iterazione: un
classificatore con AUC 0.55-0.58 non garantisce che *qualsiasi* discretizzazione in soglie
fisse catturi l'edge — andrebbe provato un approccio che usi l'output del modello stesso
(es. probabilità predetta > soglia) invece di ricostruire manualmente le soglie sulle
singole feature, oppure accettare che l'edge trovato dal classificatore sia troppo diffuso
tra molte feature deboli per essere isolato in una regola semplice.

## 🆕 2026-09-07 — Sprint reparametrizzazione strategie deboli (8 subagenti, nessuna promozione)

Grid search tp_mult×sl_mult via `opt_harness.py` su S09_MFKK_SCALPING (M5, M15), S18_RANGE_REVERSAL
(M15, H1), S17_CONVERGENCE_SCALP (M15, M30), S10_OB_FVG_SCALP (M15, M30) — le 4 strategie con PF
standalone <1 su (quasi) tutti i TF. 288 combinazioni totali valutate.

**Esito: nessuna promozione.** 3 candidati passavano `is_promotable()` senza correzione statistica
(S18 M15 tp1.5/sl1.75, S17 M30 tp2.0/sl2.5, S17 M15 tp3.0/sl2.5), ma **tutti falliscono il DSR
check centralizzato** (`dsr_check`, num_trials=288 — somma onesta di tutte le combo testate nello
sprint). Anche il migliore (S17 M30, holdout PF 1.124, pnl +296) non è significativo nemmeno a
num_trials=1 (DSR p=0.70, sotto soglia 0.95) — il problema di fondo è il campione holdout corto
(~20-70 giorni), non solo il numero di tentativi.

S10_OB_FVG_SCALP scartato dai subagenti stessi prima ancora del DSR: M15 ha PF instabile (1.11-3.39
su appena 9 trade, stesso set su tutta la grid), M30 ha risultati identici su tutte le 36 combo
(TP non toccato per primo nei 4 trade holdout) — dati non informativi, non un problema di tuning.

**Conclusione, coerente con lo sprint 2026-09-02**: il problema di queste 4 strategie è l'edge
decaduto/campione insufficiente, non i parametri tp/sl. Riottimizzare aggressivamente su più TF
non ha prodotto nulla di statisticamente distinguibile dal rumore. `STRATEGIES_CONFIG` invariato.

## 🆕 2026-09-07 — Hurst exponent / CUSUM in strategy_selector.py (skill regime-detection)

`detect_regime_extended()` ora calcola anche `hurst`, `hurst_bias` (TRENDING/MEAN_REVERTING/
RANDOM_WALK), `regime_shift_flag` (CUSUM change-point nelle ultime 5 barre) — **solo metadata
informativa, `_score_strategy()` non li usa**: il punteggio (regime match + PF + sessione +
recent WR, 100 pt) resta identico a prima, zero impatto sulla selezione live.

Bug scoperto e fixato in fase di test: Hurst va calcolato sui **log-return**, non sui prezzi
grezzi — su un livello prezzo con drift secolare (XAU 2024-2026 quasi sempre in uptrend) l'R/S
classico satura a ~1.0 anche su finestre di 150 barre H1, rendendo la metrica inutile. Sui
return il bias upward noto del metodo R/S su campioni finiti resta: baseline osservata su H1
XAU (25 campioni random) → range 0.59-0.86, media ~0.70. Le soglie 0.55/0.45 (dalla skill,
generiche) quindi classificano quasi sempre TRENDING — **da ricalibrare su questo dataset
prima di usarle per pesare lo score**, non prendere i valori della skill come oro colato.

Prossimo passo (non fatto, richiede validazione backtest prima di toccare lo score live):
usare `opt_harness.py` per testare se pesare `_score_strategy()` con hurst/regime_shift
migliora PF/DD sull'holdout rispetto al roster attuale, con soglie calibrate su XAU/US30
invece di quelle generiche.

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
| `S31_LAYOUT_SMART` | Layout Smart (break→retest→confl) | strutturale (1R zona conf.) | strutturale | trend pulito (EMA200 slope) | **H1 only** | 1.95 std / +$499 overlay | 52.8% (n=53) |
| `S20_FIB_CONFLUENCE` | Fib Confluence V2 | strutturale (Fib) | strutturale | TREND/WEAK | **M5** (blocco proprio, sizing RiskGuardian ×2) | OOS PF 1.72 | ~52% |
| `S30_DOW_DIP` | Dow Dip (Connors RSI2) | ATR×1.2 | ATR×2.6 | long-only US30 | **H4** (2° simbolo US30Cash) | 1.63 / holdout 2.09 | 76% |

> **2026-09-10** — S20 e S30 **non sono più "live test"**: erano già production nella logica
> del bot (S20 integrata 2026-09-01, S30 live 2026-09-03), ora anche nell'etichetta UI. Card
> tab Strategie normale + badge `📡 LIVE · ROSTER` + P&L live isolato via `strat_live_push`
> (`s20_push_stats` / `us30_push_stats` / `ls_push_stats`). "Blocco proprio" / "2° simbolo"
> restano necessità architetturali (lifecycle specifica, asset diverso), non limiti di test.
> Gate di permanenza self-learning attivo per tutte (`hard_blocks.json` + `performance_tracker`).
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
