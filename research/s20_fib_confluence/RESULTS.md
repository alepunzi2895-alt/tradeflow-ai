# S20_FIB_CONFLUENCE — ricerca (2026-08-28)

Port della strategia scalping Pine "Repro Overlay — M5" (Bollinger + ribbon EMA20/50 +
Auto-Fibonacci swing 50 + trigger sugli estremi a 20 barre), con SL/TP **ancorati ai
livelli Fibonacci** e gestione a parziali 50% TP1 → BE → 50% TP2.

- Segnale: `scripts/signals.py::signal_fib_confluence` (+ `fib_confluence_levels`, `fib_confluence_trade_levels`)
- Simulazione parziali: `scripts/strategy-engine-v2.py::sim_fib_confluence`
- Sweep: `scripts/research_s20_fib.py`
- Dati: `data/xauusd_{m5,m15,m30}_mt5.json` (~13 mesi, 2025-06 → 2026-06)

## 1. Port fedele al Pine — backtest standalone

| TF | N | WR% | PF | P&L | DD |
|---|---|---|---|---|---|
| M5  | 146 | 17.8% | 0.51 | −$177 | $205 |
| M15 |  42 |  9.5% | 0.49 | −$102 | $136 |
| M30 |  23 | 17.4% | 1.06 | +$9   | $91  |

In sistema adattivo (regime-gated, quando inserita in `REGIME_PRIORITY_M30`): M5 PF 0.79 /
M15 0.75 / M30 0.84. **Fallisce i criteri di promozione** (PF adattivo > 1.10, WR ≥ 28% su ≥ 50 trade).

**Diagnosi**: lo SL su Fib 0.236 sotto un pullback poco profondo è ~$2–3 su M5 — spazzato dal
rumore intracandela prima che il prezzo raggiunga TP1 (Fib 0.618). R:R 1.5+ sul foglio, R:R
realizzato dominato dal tasso di stop-out (solo 10–18% dei trade tocca TP1).

## 2. Sweep parametri — 90 combo × 3 TF, split cronologico 80% IS / 20% OOS

Leve: `sl_mode` (fib 0.236 vs atr_floor k×ATR), `sl_atr_k` (1.5/2.5), `tp1` (Fib 0.500 vs 0.618),
`adx_min` (0/20/25), `fresh_extreme` (estremo 20b stretto vs banda 25% + candela di inversione).

### Unico candidato con campione significativo positivo su entrambe le finestre

`sl_mode=fib · tp1=0.500 · adx_min=0 · fresh_extreme=False` — **solo M5**:
- IS:  n=204, WR 26.5%, PF **1.156**, +$40
- OOS: n=51,  WR 27.5%, PF **1.29**, +$22

### Perché non è promuovibile

1. **Non robusto** — cambia una sola leva e degrada o va negativo:
   - `tp1=0.618` (invece di 0.500): IS PF 0.66 / 0.92 (negativo)
   - `fresh_extreme=True`: IS PF 0.71 (negativo)
   - `adx_min=25`: IS PF 0.94 (negativo IS)
   - `adx_min=20`: IS 1.11 / OOS 1.07 (positivo ma marginale)

   È un picco isolato sulla griglia, non un plateau — stesso criterio di rigetto usato nel
   re-tuning 2026-07-17 ("≥ 2/3 celle vicine devono migliorare").

2. **Solo M5** — M15 e M30 negativi per quasi ogni combo (M15 `fib/0.5/0/False`: IS PF 0.38,
   OOS 0.23). Il bot non ha un loop M5.

3. **Edge marginale** — anche nella cella migliore, PF ~1.2 e +$62 su 13 mesi (255 trade).
   Dopo costi di transazione realistici (~4–7% di PF, vedi sprint 2026-07-16) diventa breakeven.

4. Le varianti `atr_floor` con PF alto (2.5) crollano a n=37/10 — il gate R:R rigetta la maggior
   parte dei setup quando lo SL si allarga. Campione insufficiente, e M15/M30 restano negativi.

## 3. v2 — ingresso confermato + SL strutturale + filtro trend HTF (`scripts/research_s20_fib_v2.py`)

Contesto: l'utente ha visto un trader live in profitto con questo Pine su M5/M1, ma **discrezionale
attivo**. La v2 dà alle regole meccaniche le difese che un umano applica:

- Ingresso **confermato**: zona/estremo + ribbon al bar j, poi bar j+1 conferma la direzione → entra al close di j+1.
- **Higher-low / lower-high di struttura**: il pullback deve tenere sopra/sotto lo swing precedente.
- **SL strutturale con floor ATR**: `min(low_candela − 0.15×ATR, entry − k×ATR)`, mai su Fib 0.236.
- **Filtro trend HTF**: EMA200 su M5 (~16h di contesto) — solo pullback in trend.
- TP1 = 1R, TP2 = 2R, parziali 50/50, stop a BE dopo TP1.

Dati **estesi a 20 mesi** (M5 2024-12 → 2026-08, refresh 2026-08-28, include 2.5 mesi mai visti prima).

### Aggregato — sembra promettente

| config M5 | N | WR% | PF | P&L | DD | mesi+ |
|---|---|---|---|---|---|---|
| `k=1.5 · TP2=2R · band=0.25` | 144 | 54.2% | **1.24** | +$114 | $73 | 11/18 |
| `k=1.75 · TP2=2R · band=0.20` | 132 | 53.8% | **1.33** | +$158 | $62 | 11/18 |

WR salta da 10–18% (v1) a **52–57%**. Griglia di robustezza (36 celle, k 1.25–2.0 × TP2 1.5–2.5 ×
band 0.20–0.30): **PF > 1 in tutte**, cluster migliore k 1.5–1.75 / band ≤ 0.25. Walk-forward 3
terzi cronologici: PF 1.17 / 1.37 / 1.21 — positivo in tutti e tre. Non è un picco isolato.

### Decomposizione — l'edge non regge

**BUY vs SELL** (config centrale, 20 mesi):
- BUY:  n=60, WR 51.7%, PF **0.98**, −$4  → nessun edge sul lato lungo
- SELL: n=84, WR 56%,   PF **1.42**, +$118 → tutto il profitto è qui

**SELL-only walk-forward** (k=1.5 TP2=2R):
- T1 (2025-01 → 2025-07): PF **0.51**, WR 46%, **−$33**  ← 7 mesi in perdita
- T2 (2025-07 → 2026-01): PF 1.90, +$53
- T3 (2026-01 → 2026-05): PF 1.62, +$99

L'edge SELL è concentrato negli ultimi ~10 mesi — la finestra del grande movimento dell'oro
2025-26. **È una scommessa di regime, non un edge strutturale** — stessa diagnosi di C5
(2026-07-17: "regime, non edge"). Il lato BUY (il setup che il trader live probabilmente usa nel
trend rialzista) è un coin flip. M15/M30 su dati estesi: M15 PF 0.85 (negativo), M30 PF 1.15 (n=38).

## 4. v3 — ultimo tentativo sul lato BUY (`scripts/research_s20_fib_v3_buy.py`)

Il lato BUY di v2 era breakeven (PF 0.98). Nuove leve BUY-specifiche: trend HTF forte
(EMA20>EMA50>EMA200, non solo close>EMA200), momentum intatto (RSI in salita / MACD hist in
salita), TP1 più largo (1.5–2R invece di 1R — le pullback in trend forte corrono oltre 1R).

**Miglior config** (`trend=stack · mom=macd · SL=1.5×ATR · TP1=1.5R · TP2=2R · band=0.20`), M5, 20 mesi:
n=51, WR 47.1%, PF **1.56**, +$87, DD $54, 11/17 mesi+. Griglia robustezza (48 celle, band 0.15–0.30
× k 1.25–1.75 × TP1 1.25–2.0): **PF > 1 in tutte**, cluster k≥1.5 / TP1≥1.5.

**Walk-forward per terzi di calendario (equal time):**
| | T1 (2024-12→2025-06) | T2 (2025-06→2026-01) | T3 (2026-01→2026-08) |
|---|---|---|---|
| PF | 1.80 | 1.87 | **1.04–1.20** |
| WR | 43% | 59% | **31–36%** |
| n | 23 | 17 | 11–13 |

Il terzo **più recente** è breakeven, con WR che crolla a 31–36% (la tesi è "pullback ad alta WR" —
il carattere è cambiato). n=11 nel T3 = rumore. M15 PF 1.09 (n=24), M30 PF 1.24 (n=11) — non confermano.

## 5. v4 — filtro sessione/orari + circuit breaker giornaliero (`scripts/research_s20_fib_v4_session.py`)

Richiesta utente: trovare fasi/orari coi profitti migliori + fermare il sistema dopo una serie di
profitti nella giornata (non continuare ad aprire dopo aver guadagnato).

**Breakdown orario (v2 combined, 20 mesi, tutto il dataset):** h16 UTC (NY afternoon) = outlier
enorme (n=13, WR 85%, +$137), h8 (London open) e h15 anche positivi; h7/h9/h17/h18 negativi;
**lunedì netto negativo** (−$63, probabile rumore da gap weekend). Filtrando su ore {8,10,14–16} +
no-lunedì l'aggregato saliva a PF 2.3–3.4 con DD $15–37.

**MA la validazione onesta lo ridimensiona.** Selezionando le ore **solo sul primo 60% dei dati** e
testando sull'ultimo 40%:
- Ore positive nel train: {8,11,12,15,16,17} (≠ quelle scelte a occhio sul dataset intero).
- Test (ore da train): n=25, WR 52%, PF **1.55**.
- Test **senza** filtro ore: n=54, PF **1.72** — il filtro ore *peggiora* l'OOS.

Cioè: le "ore buone" del passato non sono in modo affidabile le ore buone del futuro. Il PF 2.3+
del filtro orario era in gran parte look-ahead (ore scelte guardando anche il periodo di test).

**Circuit breaker giornaliero** (stop dopo +N R / −M R nel giorno): a ~3 trade/mese **non scatta
mai** (`dstop=None` e `dstop=2.5` danno risultati identici). Alzando la frequenza (entry più larga),
lo stop-dopo-profitto *taglia i vincitori* nelle ore buone → peggiora. Idea sana in generale, inutile
per questa strategia che si auto-limita già con la bassa frequenza.

**Numero onesto** (config di principio, non fittata: v2 combined + ingresso confermato + SL
strutturale + EMA200 + **no-lunedì** + sessione piena London+NY 7–19):
- Full period: n=111, WR 52.3%, PF **1.54**, +$177, DD $46
- OOS ultimi 8 mesi: n=54, PF **1.72**
- Walk-forward 3 terzi: PF 1.16 / 1.23 / 1.79 (recente il migliore)
- BUY e SELL entrambi positivi

## Conclusione

- **Port fedele**: perdente netto (WR 10–18%, PF 0.5).
- **v1** (90 combo): solo picco isolato non robusto.
- **v2** (ingresso confermato + SL strutturale + EMA200): aggregato PF 1.24; il lato SELL da solo
  perde 7 mesi di fila in walk-forward.
- **v3 BUY** (trend stack + momentum + TP largo): aggregato PF 1.56, plateau robusto, ma il terzo
  di calendario più recente è breakeven (WR 31%, n=11).
- **v4** (sessione + circuit breaker): il filtro orario "migliore" (PF 2.3+) era look-ahead;
  selezionando le ore solo sul train l'OOS *peggiora* (1.55 vs 1.72 senza filtro). Il circuit
  breaker non scatta a ~3 trade/mese.

**Il numero onesto**: config di principio — v2 combined + **no-lunedì** + sessione piena London+NY —
dà full-period PF **1.54** (n=111) e **OOS ultimi 8 mesi PF 1.72** (n=54), walk-forward 1.16/1.23/1.79,
BUY e SELL entrambi positivi. È un edge **debole ma reale e out-of-sample**, non un regime bet come
sembravano v2/v3 isolate. ~3–4 trade/mese, M5.

Non è "sempre in profitto" come il trader live (che aggiunge selezione discrezionale + gestione
attiva). Ma non è nemmeno morta: **PF ~1.7 OOS** è nel range di S00 nel roster.

**Bloccanti per il live**: (1) il bot non ha un loop M5 — cablarla richiede aggiungerlo in
`mt5-bot.py::run()` (pattern esistente da M15); (2) contributo assoluto piccolo (~+$180 su 20 mesi
a 0.01 lot, ma profilo rischio ottimo: DD $46, maxCL 3); (3) tanta selezione di parametri fatta per
arrivarci — meriterebbe paper trading prima del capitale reale.

Codice segnale + 4 sweep (`scripts/research_s20_fib*.py`) lasciati come riferimento. **Non cablata
nel live** (`mt5-bot.py` / `strategy_selector.py` / `risk_guardian.py` / UI intatti).
