# TradeFlow AI — Curriculum di trading (ECABS Basic + Intermediate)

> Distillato dei 35 PDF educativi in `Downloads/Basic` + `Downloads/Intermediate` (corso
> ECABS, orientato a **XAU/USD** — gli esempi sui grafici sono quasi tutti oro).
> Serve come: (1) memoria di apprendimento per Claude, (2) base per il tab Knowledge /
> coach AI, (3) checklist di allineamento per le strategie del bot.
>
> **Colonna "App"**: ✅ già implementato · 🔶 parziale / migliorabile · ➕ gap concreto · — non applicabile.
>
> Copertura: letti integralmente i 18 moduli tecnicamente sostanziali (market structure ×2,
> S/R, trendline, Fibonacci ×3, MACD, MA, Stochastic, MTF, price action, triple candles,
> japanese candlesticks, market cycles, risk, sessioni, news). I restanti (psicologia ×3,
> trading plan, chart types, pip, piattaforme/MT4-5, currency strength, forex factory,
> fundamental) sono contenuto introduttivo standard, coperto dalle sezioni sotto.
>
> **2026-09-10** — versione iniziale (dopo l'integrazione di S31_LAYOUT_SMART).

---

## 1. Struttura di mercato (Market Structure / SMC) — il fondamento

Il corso dedica **2 moduli interi** a questo (`Market Strucutre.pdf` + `Market Strucutre 2.pdf`),
tutti con esempi su XAU/USD → è **il** metodo di riferimento, non un dettaglio.

| Concetto | Regola | App |
|---|---|---|
| Trend rialzista | sequenza di **Higher High + Higher Low** (HH/HL) | ➕ il regime usa ADX/DI, NON la struttura a swing |
| Trend ribassista | sequenza di **Lower High + Lower Low** (LH/LL) | ➕ idem |
| Range / consolidamento | massimi e minimi ~uguali | ✅ regime RANGE (ADX<22) |
| Movimento **impulsivo** vs **correttivo** | impulsivo = nel verso del trend, momentum forte · correttivo = contro-trend, debole (**pullback ≠ reversal**) | ➕ |
| **BOS — Break of Structure** | = **CONTINUAZIONE**. Prezzo fa nuovo HH (uptrend) o nuovo LL (downtrend) *senza prima invertire*. Serve **chiusura candela oltre + 1 candela di conferma**. "flusso ordini continuo" | ➕ **nessun rilevamento** |
| **CHoCH — Change of Character** | = **primo segnale di INVERSIONE**. In downtrend (LL/LH) il prezzo rompe l'ultimo **massimo** → CHoCH. **Non serve la chiusura** (basta la mecca). Dopo un CHoCH si **aspetta un BOS** nella nuova direzione prima di entrare | ➕ **nessun rilevamento** |
| Sequenza operativa SMC | trend → CHoCH (allerta inversione) → BOS nuova direzione (conferma) → entry sul pullback a supply/demand | ➕ |
| Supply / Demand zone | l'ultima candela/base prima di un movimento impulsivo = zona da cui rientrare | 🔶 il progetto ha `order_blocks` (S10) — concetto affine |
| Ciclo di Wyckoff | **Accumulation → Markup → Distribution → Markdown** · emozioni hope→greed→doubt→fear · retail compra in alto / smart money vende (distribution) e viceversa · distribution mostra H&S / Double Top | ➕ distinguere RANGE-accumulazione da RANGE-distribuzione |
| Procedura di analisi | 1) trend corrente 2) trendline 3) livelli chiave 4) BOS/CHoCH 5) **multi-timeframe** | 🔶 |

**Azione (gap G1, priorità ALTA)**: `scripts/market_structure.py` — fractal swing detection
(HH/HL/LH/LL, wing 2-3 causale come `telegram_key_levels.swing_points`) + flag **BOS** (close
oltre l'ultimo swing nel verso del trend) e **CHoCH** (rottura dell'ultimo swing opposto).
Da esporre come:
- feature aggiuntiva del regime (`detect_regime_extended`) — es. "TREND_UP confermato da BOS"
  vs "TREND_UP ma CHoCH recente → cautela / riduci size";
- gate per S31 e S16 (entrare solo se la struttura non ha fatto CHoCH contro la direzione);
- eventualmente una nuova strategia "CHoCH + BOS retest a supply/demand" (validare con
  `opt_harness` prima del live).

## 2. Supporto & Resistenza

| Concetto | Regola | App |
|---|---|---|
| S/R sono **zone**, non linee esatte | usare fasce, non prezzi puntuali | ✅ `key_levels.py` usa cluster ATR; S31 usa "zone di confluenza" |
| **Numeri tondi** | il mercato mette ordini a 4400, non a 4382.31 → S/R psicologico | ✅ `key_levels._round_number_levels` ($50 XAU), `telegram_key_levels` round10/round25 |
| Forza del livello | più tocchi/rimbalzi → più forte | 🔶 il Pine "My Strategy" conta i tocchi; S31 conta il *numero di livelli* nella zona, non i tocchi |
| Break di S/R | **aspettare la CHIUSURA candela** oltre il livello (false breakout) | ✅ S31 usa `close > upper` (chiusura), non wick |
| Retest | molti entrano al **retest** del livello rotto, non sul break | ✅ **è il cuore di S31** |
| S/R flip | supporto rotto → diventa resistenza (e viceversa) | 🔶 |
| Strumenti S/R dinamici | trendline, moving average, Fibonacci | ✅ EMA200, trendline, Fib pivot tutti in S31 |

## 3. Trendline

- Bastano **2 punti** per tracciarla, ne servono **3 tocchi** per confermarla valida.
- Uptrend: connette gli HL (sotto il prezzo). Downtrend: connette gli LH (sopra).
- Break della trendline = segnale di inversione → molti aspettano la chiusura della candela.
- "Non forzare la trendline sul mercato: se non combacia, ignorala."
- **App**: ✅ S31 usa `luxalgo_trendline_breaks` (pivot len 14, slope ATR). 🔶 la conferma
  a 3 tocchi non è modellata (la LuxAlgo àncora su 2 pivot e decade). ➕ possibile filtro
  "≥3 tocchi" prima di validare il break.

## 4. Fibonacci

| Livello | Uso |
|---|---|
| 23.6% · 38.2% · **50%** · **61.8% (golden ratio)** · 78.6% | ritracciamenti — zone di re-entry nel trend |
| **Golden Zone 50–61.8%** | dove il prezzo spesso ferma il ritracciamento e riparte nel verso del trend |
| **Premium / Discount** | prezzo **sopra il 50%** dello swing = premium (cerca SELL) · **sotto il 50%** = discount (cerca BUY) |
| "profondità del pullback" | pullback corto = trend forte · pullback profondo (>61.8%) = trend debole / rischio inversione |
| Estensioni 127.2% · 161.8% · 261.8% | target di profit |
| Come si traccia | uptrend: swing low → swing high · downtrend: swing high → swing low |
| Confluenza | Fib + S/R + pattern candela = **setup alta probabilità** (`FIBONACCI WITH SUPPORT_RES.pdf`) |

- **App**: ✅ `signal_fib_confluence` (S20) è esattamente "estremo + Fib 0.382/0.618 + candela
  di inversione + ribbon EMA". ✅ S31 usa i Pivot **Fibonacci** (P ± 0.382/0.618/1.0·range).
  Il progetto ha già `fib_confluence_levels` / `fib_distance` (fib_position 0-1) in
  `telegram_key_levels`. ➕ **premium/discount gate**: S31 solo long in discount / short in
  premium rispetto allo swing recente — feature scala-invariante già mezzo pronta (`fib_position`).

## 5. Indicatori tecnici (parametri standard del corso)

| Indicatore | Parametri | Segnali | App |
|---|---|---|---|
| **MACD** | EMA 12/26, signal 9 | MACD>0 uptrend; cross MACD↑signal = buy; istogramma = MACD−signal; **divergenza** prezzo↔MACD = inversione | ✅ `macd_full(12,26,9)` identico; S16 usa istogramma |
| **Moving Average** | SMA vs EMA; comuni 20/50/100/200 | golden cross (50↑200) rialzista, death cross ribassista; prezzo>MA = bias long; MA come S/R dinamico | ✅ EMA 13/20/34/50/89/100/200/233 ovunque; S31 usa **EMA200 slope** come filtro trend |
| **Stochastic** | %K, %D = SMA3 di %K; OB **80** / OS **20** | %K↓%D sopra 80 = short; %K↑%D sotto 20 = long. **Solo nel verso del trend**; in downtrend prendere solo gli short a OB | ✅ StochRSI K/D in S05/S17; S18 fade OB/OS **solo in RANGE** (ADX<22) — allineato |
| **RSI** | 14; OB 70 / OS 30 | conferma OB/OS + divergenza | ✅ RSI(14) ovunque |
| Regola d'oro oscillatori | "possono restare estremi a lungo — **non anticipare**, aspettare il segnale" + conferma trend/S/R | ✅ regime-gating |

## 6. Pattern a candela

| Tipo | Pattern | Note |
|---|---|---|
| Singola | Doji (indecisione), Hammer / Hanging Man, Shooting Star, Marubozu | corpo/mecca vs ATR |
| Doppia | Engulfing (rialzista/ribassista), Harami, Tweezer, Piercing / Dark Cloud | |
| Tripla | **Morning/Evening Star** (+ doji), **Three White Soldiers / Three Black Crows**, **Three Inside Up/Down** | reversal o continuazione |
| Hammer (thirds-rule) | corpo nel terzo superiore, **mecca inferiore ≥ 2/3** della candela; inverse hammer = speculare | `Price Action Combined.pdf` |
| "Size matters" | candela più grande (range ampio) = pattern più significativo | idem |
| Regola | **mai la candela da sola** — confermare con RSI/MACD/S-R | `TRIPLE CANDLES.pdf` |
| **Ricetta ad alta probabilità** | **hammer a SUPPORTO + oscillatore OVERSOLD** = reversal rialzista forte · **shooting star a RESISTENZA + OVERBOUGHT** = reversal ribassista forte | `Price Action Combined.pdf` |

- **App**: ✅ TA-Lib (61 pattern) già in `feature_screen.py`. 🔶 S31 usa un check
  grezzo di mecca (`reject_wick ≥ 0.22·ATR`) invece del pattern reale (hammer/star con
  thirds-rule). ➕ **la "ricetta ad alta probabilità" è quasi esattamente S31** ma manca
  la conferma oscillatore (RSI/Stoch estremo) alla zona di confluenza — gate testabile.

## 7. Sessioni di mercato (EST → UTC = +5)

| Sessione | EST | **UTC** | Note |
|---|---|---|---|
| Sydney | 18–02 | 22–07 | volume basso |
| Tokyo | 19–04 | 00–09 | volume basso |
| **London** | 03–12 | **08–17** | alto volume (GBP/EUR + oro) |
| **New York** | 08–17 | **13–22** | alto volume (USD + oro) |
| **Overlap London+NY** | 08–11 | **13–16** | **volume massimo → migliori setup** |

- L'oro è liquido in tutte le sessioni ma i movimenti direzionali puliti sono London+NY.
- **App**: ✅ S31 sessione 7–21 UTC · S20 8–17 UTC · S16/S17 7–18/19. Lo sprint S20
  2026-09-02 aveva già ristretto a 8–17 ("solo overlap liquido") → curriculum confermato.
  🔶 nessuna strategia sfrutta specificamente l'overlap 13–16 UTC come boost.

## 8. Gestione del rischio (`WHAT IS RISK.pdf`, `10 KEY POINTS.pdf`, `TRADING PLAN.pdf`)

| Regola | Valore standard | App |
|---|---|---|
| Rischio per trade | **1–3%** del capitale (il corso dice 1-3%; standard prudente 1-2%) | ✅ RiskGuardian risk-cap 2% in `_calc_lot` |
| Risk : Reward | "mai sotto 1:1" (corso) → puntare **1:2 / 1:3** | ✅ TP mult 3.5–4.0 vs SL 1.5–2.0×ATR ≈ 2:1; S31 TP1 1.5R + runner |
| "Sit on your hands 50% of the time" (Lipschutz) | la maggior parte del tempo NON si opera — pazienza | ✅ regime-gating + S31 (~2.4 trade/mese) |
| Stop loss | **sempre** definito prima dell'ingresso; strutturale (oltre swing/zona) | ✅ tutti hard SL a MT5; S31 SL strutturale |
| Non spostare mai lo SL **allargandolo** | | ✅ trailing solo in direzione favorevole |
| 3 uscite pre-definite | stop loss, take profit, trailing stop | ✅ BE + trailing "sempre" (richiesta utente) |
| Trading plan | asset, sessione, setup, size, regole di uscita, giornale | ✅ playbook + `journal.js` + performance_tracker |
| Correlazione | non moltiplicare l'esposizione sullo stesso rischio | ✅ `has_position_in_direction` + `MAX_OPEN_ORDERS` |

## 9. Multi-Timeframe Analysis

- **HTF** (D1/H4) = trend & bias · **MTF** (H1) = struttura & livelli · **LTF** (M15/M5) = timing d'ingresso.
- Regola: opera nel verso dell'HTF; l'onda contro-trend sull'LTF è un pullback, non un'inversione,
  finché l'HTF non fa BOS.
- **App**: 🔶 lo StrategySelector sceglie **un** TF per strategia (H1 loop, H4 per S17, M30 per
  S09/S10). Non c'è un vero "bias HTF filtra entry LTF". ➕ S31 potrebbe filtrare gli ingressi
  H1 con la direzione EMA200 di H4 (MTF confluence) — enhancement testabile.

## 10. Fondamentali & news (`HOW TO READ & TRADE THE NEWS`, `Forex factory basics`, `Forex FUNDAMENTAL`)

- Eventi ad alto impatto per l'oro: **NFP, CPI, tassi Fed/FOMC, PCE, disoccupazione, GDP, PMI**,
  discorsi Powell, tensioni geopolitiche (oro = safe haven).
- USD forte → oro debole (correlazione inversa con DXY). Tassi reali su → oro giù.
- Non tradare i 15 min prima/dopo un evento rosso: spread e slippage esplodono.
- **App**: ✅ `news_guardian.py` (pausa ± finestra evento, `news_risk_mult`), `api/market` DXY
  correlation, confidence score regime-based con branch per XAU/XAG/US30 in `dashboard.js`.

## 11. Psicologia (`Trading Psycology`, `MASTERING EMOTIONS`, `POSTIVE MINDSET`)

- I 4 nemici: **paura, avidità, speranza, rimpianto** (mappano sulle 4 fasi di Wyckoff).
- Disciplina > previsione. Seguire il piano anche quando "sembra" sbagliato.
- Giornale di trading obbligatorio; rivedere i trade, non solo i risultati.
- Accettare le perdite come costo del business; non aumentare la size dopo una perdita (revenge trading).
- **App**: ✅ coach AI in `chat.js`, `journal.js` con growth areas, `MASTERING EMOTIONS` già in KB.
  Il bot è per costruzione immune alle emozioni — il valore psicologico è per l'utente.

## 12. Altro (Basic)

- **Pip**: XAU 1 pip = $0.01 di movimento? No — per l'oro il "punto" = $1.00, il bot ragiona in $/punto.
- **Currency strength meter**: confronta la forza relativa delle valute per scegliere la coppia più "pulita".
- **Chart types**: candele > barre > linea; la linea (solo chiusure) riduce il rumore dei false break.
- **Piattaforme / MT4-MT5**: il bot gira su MT5 (Python API).

---

## Sintesi — cosa il curriculum CONFERMA del progetto

1. **Confluenza** (Fib + S/R + candela + sessione) = il principio n°1 → **è esattamente S20 e S31**.
2. **Retest > break** → S31.
3. **SL strutturale, R:R ≥ 1:2, 1–2% risk** → RiskGuardian.
4. **Oscillatori solo in range / nel verso del trend** → regime-gating (S18 ADX<22).
5. **London+NY overlap** = miglior finestra → sprint S20 l'aveva già trovato.
6. **MACD 12/26/9, EMA 50/200, Stoch 80/20, RSI 70/30** → parametri identici nel codice.

## Sintesi — gap concreti (candidati di ricerca, NON ancora fatti)

| # | Gap | Dove | Priorità |
|---|---|---|---|
| ~~G1~~ | ✅ **FATTO 2026-09-10** — `scripts/market_structure.py`: swing HH/HL/LH/LL + **BOS** (continuazione) + **CHoCH** (inversione), causale. Usato in `layout_confidence.py` (fattore struttura del confidence score S31-S34). **Ancora da fare**: integrarlo in `detect_regime` / `strategy_selector` come feature di regime ("TREND_UP confermato da BOS" vs "CHoCH recente → cautela") | `detect_regime` / `strategy_selector` | media (il grosso è fatto) |
| G2 | **MTF bias** (H4 EMA200) | 🔶 in `layout_confidence.py` (fattore `mtf_bias`, score S31-S34). Da portare come **gate** vero in `ls_scan` | media |
| G3 | **Pattern candela reale** (hammer/star thirds-rule, engulfing) | 🔶 in `layout_confidence._hammer` / `_engulf` (fattore `candle`). Da usare in `ls_scan` al posto del check mecca | media |
| G3b | **Conferma oscillatore** (RSI/Stoch estremo) alla zona | 🔶 in `layout_confidence.py` (fattore `oscillator`, solo reversal). Da portare come gate in `ls_scan` | media |
| G4 | **Conteggio tocchi** del livello | `ls_confluence_zones` | bassa |
| G5 | **Overlap London+NY 13–16 UTC** come boost di size/confidence | 🔶 in `layout_confidence.py` (fattore `session` +7). Da portare in RiskGuardian per le altre strategie | bassa |
| G6 | Distinguere RANGE-accumulazione da RANGE-distribuzione (Wyckoff) | regime | bassa |

> **2026-09-10** — G1 fatto (`market_structure.py`), G2/G3/G3b/G5 implementati come **fattori
> del confidence score** in `layout_confidence.py` (test S32/S33/S34 col sistema completo —
> vedi `02_strategies.md`). Il confidence NON ha reso profittevoli S32/S33/S34 (PBO resta
> 0.80-1.00) ma i mattoni sono ora riusabili per S31/S16.

Ognuno va validato con `opt_harness.py` (walk-forward + DSR + PBO) prima di toccare il live —
stesso rigore del resto del programma. Registrare i trial in `research_trials.py`.
