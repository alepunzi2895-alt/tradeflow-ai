# TradeFlow AI — Directive Layer (DOE Framework)

> Questo documento è la **Directive Layer** del Framework DOE applicato al progetto TradeFlow AI.  
> L'agente AI (Orchestration Layer) deve leggere queste istruzioni prima di qualsiasi intervento.  
> Quando si corregge un errore, aggiornare questo file per evitare che si ripeta (Self-Learning Loop).

---

## 1. IDENTITÀ DEL PROGETTO

**TradeFlow AI** è una Progressive Web App (PWA) mobile-first per trader XAU/USD (oro spot).  
- **URL produzione**: https://tradeflow-ai-delta.vercel.app/  
- **Repository**: https://github.com/alepunzi2895-alt/tradeflow-ai  
- **Deploy**: Vercel (auto-deploy su push a `main`)  
- **Stack**: Node.js serverless (Vercel Functions), HTML/CSS/JS vanilla frontend  
- **Workflow**: modifica locale → `git push origin main` → verifica su Vercel (~60s)

---

## 2. ARCHITETTURA DEL SISTEMA

```
public/
  index.html          ← UI principale, CSS inline, struttura tab
  app.js              ← init, tab routing, overlays, profilo
  modules/
    core.js           ← storage, fetchJSON, API helpers
    dashboard.js      ← prezzi live, confidence score, sentiment, macro
    mfkk.js           ← MFKK Strategy Score (CCI_S, MACD, ADX + scoring)
    chat.js           ← AI analysis, image upload
    journal.js        ← trade log, coaching, reports
    myfxbook.js       ← account sync MyFxBook
    kb.js             ← Knowledge Base, upload docs
api/
  price.js            ← endpoint prezzo live XAU/USD (TV Scanner multi-ticker)
  market.js           ← UNIFIED HUB: prezzi, calendar, sentiment, cot (proxy server-side)
  indicators.js       ← MFKK indicators: MACD/ADX da TV Scanner, CCI_S da candle browser
  report.js           ← AI report giornaliero
  webhook.js          ← ricezione trades e notifiche
scripts/
  backtest-mfkk.mjs         ← backtester Node.js con config ottimale applicata
  optimize-full.py          ← ottimizzatore grid search 3 fasi (pesi + soglie + cooldown)
  analyze-entry-conditions.py ← analisi empirica zone indicatori su 2 anni H1
```

---

## 3. REGOLE CRITICHE — SEMPRE RISPETTARE

### 3.1 Fonte Dati Prezzi
- **Primaria**: TradingView Scanner (`scanner.tradingview.com/global/scan`)
- **Ticker XAU da provare in ordine**: `OANDA:XAUUSD`, `FOREXCOM:XAUUSD`, `PEPPERSTONE:XAUUSD`, `TVC:GOLD`, `CAPITALCOM:GOLD`
- **MAI usare `GC=F`** (Gold Futures COMEX ≠ spot gold — valori completamente diversi)
- **Yahoo Finance come fallback SOLO con `XAUUSD=X`** (spot), non `GC=F` o `GLD`

### 3.2 Fetch Candle per Indicatori
- **Vercel serverless IP sono blacklistati da Yahoo Finance e `data.tradingview.com`**
- **Candle per CCI_S**: fetchare lato BROWSER in `mfkk.js` (Chrome non è bloccato)
  - URL: `https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD%3DX?interval=1h&range=60d`
  - Range `60d` garantisce 120+ candle necessarie per warmup CCI(50)+Stoch(50)
- **MACD e ADX**: TV Scanner da server Vercel (non necessitano di candle storiche)

### 3.3 Colonne TV Scanner
Formato corretto per timeframe H1: `NOMECOL|60`

| Indicatore | Colonna corretta | Note |
|---|---|---|
| MACD line | `MACD.macd|60` | Default params 12,26,9 ✅ |
| MACD signal | `MACD.signal|60` | ✅ |
| MACD hist | `MACD.hist|60` | ✅ |
| ADX | `ADX|60` | **SENZA** `[period]` — parametro custom non supportato |
| DI+ | `plus_di|60` | ✅ |
| DI- | `minus_di|60` | ✅ |
| CCI | `CCI[50]|60` | Forma parameterizzata supportata |

> ⚠️ **BUG NOTO**: `ADX[10]|60` con periodo custom restituisce `null` dal scanner, che viene convertito a `0`. Usare sempre `ADX|60` (periodo default 14) e comunicare all'utente la differenza.

### 3.4 Parametri Indicatori MFKK (confermati da settings TradingView)
| Indicatore | Parametri | Script TV |
|---|---|---|
| **CCI_S** | CCI=50, Stoch=50, K=8, D=8, OB=75, OS=25, D-line | Pine Script v4, `source=close` |
| **MACD** | fast=12, slow=26, signal=9, type=EMA (entrambi) | Pine Script v6 default |
| **ADX** | Per=10, Th=10 | "ADX and DI for v4" — ADX=SMA(DX,len) non Wilder RMA! |

> ⚠️ **ATTENZIONE ADX**: Il custom indicator "ADX and DI for v4" usa `ADX = sma(DX, len)` (SMA semplice), **NON** Wilder's RMA come il built-in ADX di TradingView e TV Scanner. I valori TV Scanner ADX divergeranno da quelli del custom indicator dell'utente.

### 3.5 Formule Indicatori (Pine Script → JavaScript)
```javascript
// ta.ema(): prima barra = source[0] come seed (NON SMA dei primi N)
function _ema(src, p) {
  const k = 2/(p+1); let v = src[0]; const o = [v];
  for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
  return o;
}

// CCI_S: null-propagation nelle SMA (come Pine Script na)
// stk_k: nessun 50-fill per valori null
// ADX finale: SMA(DX, len) non Wilder RMA
```

---

## 4. FLUSSO DI AGGIORNAMENTO LIVE

```
Ogni 5 secondi (recalcIndicators):
  └─ Inietta live XAU price nell'ultima candle
  └─ Ricalcola CCI_S + EMA50 + ATR(14) + SwingH/L con live price
  └─ MACD/ADX: usa server TV Scanner (non ricalcola, aggiorna ogni 60s)
  └─ Aggiorna UI: conferma EMA50, entry plan ATR-based

Ogni 60 secondi (loadIndicatorCandles):
  ├─ BROWSER: fetch Yahoo XAUUSD=X candles → CCI_S + EMA50 + ATR + swings
  └─ SERVER: TV Scanner → MACD.macd|60, MACD.signal|60, ADX|60, plus_di|60, minus_di|60
```

---

## 5. VINCOLI INFRASTRUTTURA VERCEL

| Risorsa | Limite free tier |
|---|---|
| Execution time | 10 secondi max per function |
| RAM | 1024 MB |
| Cold start | ~500ms - aggiungere timeout < 8s in tutte le fetch |
| IP | Blacklistato da Yahoo Finance, `data.tradingview.com`, molte API finanziarie |

**Pattern obbligatorio per ogni fetch server-side**:
```javascript
async function fetchT(url, opts={}, ms=8000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try { const r = await fetch(url, {...opts, signal: ctrl.signal}); clearTimeout(tid); return r; }
  catch(e) { clearTimeout(tid); throw e; }
}
```

---

## 6. SELF-LEARNING LOOP — BUG STORICI RISOLTI

| Data | Bug | Causa | Fix |
|---|---|---|---|
| 2026-03-31 | Prezzi XAU/USD non caricavano | Yahoo Finance bloccato → FPMARKETS ticker fallito | Multi-ticker TV Scanner (9 alternative) |
| 2026-03-31 | Indicatori MACD errati (+31 server vs -12 client) | GC=F futures != spot OANDA:XAUUSD | MAI usare GC=F; Yahoo XAUUSD=X come fallback |
| 2026-03-31 | Tutti indicatori = "No candle data" | Vercel IP blacklistato da Yahoo Finance | Usa `api/candles.js` proxy per bypassare CORS |
| 2026-03-31 | ADX = 0,0,0 | `ADX[10]|60` colonna non valida → null → 0 | Calcolo server-side esatto da proxy candles |
| 2026-03-31 | CCI_S mostra "auto" | step="1" input rifiutava valori decimali | Impostato `step="0.01"` su input HTML |
| 2026-03-31 | ADX RMA vs SMA | Usavamo Wilder RMA, TV usa SMA(DX,len) | Server-side esatto calcolo SMA(DX,10) |
| 2026-04-13 | quality is not defined | dashboard.js:565 ReferenceError | Definito quality/Bg/Col in updateConfidence |
| 2026-04-13 | Strategy Logic Duplicate | strategy.js Broken Syntax | Unified MT5/Signal logic and cleaned redundant functions |
| 2026-04-13 | CORS Calendar Fail | 3rd party proxy instabili | Creato /api/market server-side proxy per ForexFactory |
| 2026-04-13 | GS Ratio / Oil stuck | Missing tickers in unified API | Aggiunti ticker XAG (SILVER) e fallback OIL nell'Hub |

---

## 7. BACKTESTING & SCORING MFKK — PARAMETRI DEFINITIVI

### 7.1 Backtest eseguito
- **Dataset**: 730 giorni H1 XAU/USD (11.441 candele, apr 2024 – apr 2026)
- **Metodo ottimizzazione**: grid search 2.272 combinazioni (Fase 1) + test ATR vs fisso (Fase 2) + cooldown (Fase 3)
- **File**: `scripts/optimize-full.py`, `scripts/analyze-entry-conditions.py`, `scripts/backtest-mfkk.mjs`

### 7.2 Parametri Scoring Ottimali

| Parametro | Valore XAU | Valore XAG | Note |
|---|---|---|---|
| **Peso CCI_S** | **10%** | 25% | ADX domina il segnale |
| **Peso MACD** | **10%** | 15% | Secondario — conferma momentum |
| **Peso ADX** | **80%** | 60% | Primario — trend e DI+ vs DI- |
| **Score entry BUY** | **≥ 90** | ≥ 75 | BUY richiede alta convinzione (WR 43.5%) |
| **Score entry SELL** | **≥ 68** | ≥ 70 | SELL più permissiva (WR 54.4%) |
| **TP XAU** | **$20** | $0.50 | Ottimizzato su 730gg |
| **SL XAU** | **$12** | $0.25 | R:R 1.67:1 → PF 1.80 |
| **EMA50 filter** | **OFF** | OFF | Non bloccare trades — EMA è solo nota informativa |

### 7.3 HIGH-WR SIGNAL — Filtri Hard (optimize-highwr.py, 730gg H1 XAU/USD)

Setup SELL ONLY con regole hard (no scoring):

| Filtro | Valore | Note |
|---|---|---|
| **ADX** | ≥ 35 | Trend molto forte |
| **DI spread** | ≥ 20 | DI- > DI+ (bearish dominante) |
| **MACD diff** | ≥ 1.0 | MACD bullish esteso = esaurimento del rialzo |
| **CCI** | ≥ 25 (ob_or_neutral) | Non in zona OS |
| **Sessione** | London/NY (7-17 UTC) | Fuori Asian/Off |

Risultati:
- **MACD diff ≥ 1.0**: N=20, **WR=95%**, PnL=$368, PF=31.67, MaxDD=$12
- **MACD diff ≥ 0.5**: N=28, **WR=92.9%**, PnL=$496, PF=21.67, MaxDD=$12
- BUY: non affidabile con hard filter (max 46% WR) — flag SELL ONLY
- UI: badge "💎 HIGH-WR SELL" dorato quando tutte le condizioni sono soddisfatte

> ⚠️ **NOTA**: Il numero di trade è basso (20-28 su 730gg) — questi setup sono rari ma estremamente affidabili. La strategia base (SELL≥68, 1439 trade, 52% WR) rimane il motore principale.

### 7.5 Risultati Backtest Config Ottimale (730gg H1 XAU/USD)

| Metrica | Valore |
|---|---|
| Trades totali | 1.439 (317 BUY + 1.122 SELL) |
| **Win Rate** | **52.0%** |
| **P&L totale** | **$6.668** |
| **Profit Factor** | **1.80** |
| **Max Drawdown** | **$600** |
| BUY Win Rate | 43.5% (P&L +$612 con soglia 90+) |
| SELL Win Rate | 54.4% (P&L +$6.056) |
| Mesi positivi | 15/25 (60%) |

### 7.6 Insights chiave dal Backtest Empirico

1. **CCI non è mean-reversion, è trend-continuation**:
   - Per BUY: CCI alto (OB_DEEP ≥75) = uptrend in corso = favorevole (NON il contrario)
   - Per SELL: CCI basso (OS_DEEP ≤25) = downtrend in corso = favorevole (WR 48% storico)
   - La logica "compra oversold / vendi overbought" è empiricamente sbagliata su H1 XAU

2. **Pattern ESAURIMENTO (82-88% WR)**:
   - Setup: ADX ≥35 + DI allineato + MACD esteso in direzione OPPOSTA al trade
   - Esempio SELL: ADX forte con DI- dominante + MACD molto bullish → esaurimento del rialzo
   - Il MACD "contro-trend" non è penalizzante ma è il segnale più potente
   - Mostrato in UI con badge viola "ESAURIMENTO"

3. **Zona score ottimale è 80-89** (58.8% WR), NON 90-100 (48.2% WR):
   - I segnali "estremi" (>90) entrano troppo tardi quando il trend è già over-esteso
   - Score 80-89 = momentum forte ma non esaurito = entry migliore

4. **SELL >> BUY su XAU H1**:
   - XAU ha pattern di pullback frequenti (sell-the-bounce) più affidabili dei breakout rialzisti
   - In periodi bull market (gold ATH), le SELL sui pullback catturano correzioni tecniche
   - BUY richiede score ≥90 per essere profittevole

5. **EMA50 filter OFF** su XAU H1:
   - Il pattern di esaurimento SELL funziona anche quando il prezzo è sopra EMA50 (bull trend)
   - Filtrare le SELL con EMA50 rimuove i migliori trade (bounce reversal in uptrend)
   - EMA50 è mostrata in UI come **informazione contestuale**, non come blocco

### 7.7 Funzionalità UI aggiunte (calibrate su backtest)

- **4° Conferma EMA50**: mostra allineamento trend + CCI crossover detection in tempo reale
- **Entry Plan dinamico**: calcola Entry / TP / SL / R:R usando ATR(14) + swing H/L degli ultimi 30 bars
  - Base SL = 1.0x ATR adattato agli swing levels reali
  - TP minimo = max(2.0x ATR, SL × 1.67)
  - Aggiornato ogni 5 secondi con prezzo live

---

## 8. CHECKLIST PRE-DEPLOY

- [ ] `node --check public/modules/mfkk.js` — verifica sintassi JS
- [ ] Fetch server/proxy con timeout bilanciati (< 8s) per arginare Vercel Cold Starts
- [ ] Mantenere proxy `api/candles.js` come singola fonte di verità per bypass blacklist
- [ ] Verificare che non ci sia parsing intero (`parseInt`) o step HTML restrittivi (`step="1"`)
- [ ] `git push origin main` prima di verificare su Vercel
- [ ] Attendere deploy completato (~60s) su dashboard prima di refresh utente

---

## 9. STRATEGY ENGINE (implementato)

### 9.1 Architettura
```
scripts/strategy-engine-v2.py  ← backtester v2: 12 strategie × 18 indicatori (730gg H1)
scripts/strategy-mtf.py        ← MTF backtester: 5 strategie × 3 TF (1h/4h/1d)
public/modules/strategy.js     ← monitor real-time: regime + segnali + real MT5 account data
public/index.html              ← tab "⚡ Strategie" (Real account execution monitoring)
```

### 9.2 Strategie Attive & Timeframes (Real-time Optimized)
| Strategia | TF Best | WR% | PF | Note |
|---|---|---|---|---|
| **S01_EXHAUSTION** | **1h** | 57.9% | 2.29 | ADX≥30+DI spread≥15+MACD contra-trend |
| **S09_VWAP_WPR** | **1h** | 47.4% | 1.50 | VWAP cross + W%R oversold/overbought |
| **S06_ORDERBLOCK** | **1h** | 46.1% | 1.42 | Institutional OB zone + momentum |
| **S13_STRUC_BREAK** | **1h** | 52.4% | 1.61 | Breakout di Pivot H/L + Retest confermato |
| **S14_KEY_LEVELS** | **1h** | 49.2% | 1.54 | Bounce o Break out di Daily/Weekly Pivots |
| **S12_WPR_KELTNER** | **1h** | 42.3% | 1.22 | W%R + Keltner channel breakout |

**MTF Test (Gold XAU/USD)**:
- **1H**: Unico TF profittevole con indicatori standard (WR 38.1% adapt).
- **5m/15m/30m**: Performance negative (WR < 36%, P&L negativo) causa rumore e spread.
- **Decisione**: Il motore opera su 1H, ma esegue i controlli ogni 3s.

### 9.3 Regime Detection
| Regime | Condizione | Strategie priorità |
|---|---|---|
| TREND_UP | ADX≥30, DI+>DI- | S01→S06→S10 |
| TREND_DOWN | ADX≥30, DI->DI+ | S01→S06→S10 |
| WEAK_UP | 22≤ADX<30, DI+>DI- | S06→S10→S12 |
| WEAK_DOWN | 22≤ADX<30, DI->DI+ | S06→S10→S12 |
| RANGE | ADX<22 | S09→S12→S06 |
| VOLATILE | ADX<22, ATR>1.4x avg | S12→S09 |

### 9.4 Regole Operative
- **Max 10 trade/giorno**, cooldown 30 min tra trade
- **Giorno estremo**: ATR > 3.5x media 30gg → trading sospeso
- **Sessione**: 24h (Sessione continua per massimizzare profitti)
- **TP/SL dinamici**: S13/S14 usano ATR(14) multipliers (TP=2x, SL=1x)
- **Risk Management**: Break Even (BE) e Trailing Stop gestiti dal bot locale
- **Tracking**: Nessuna simulazione locale; visualizzazione esclusiva di dati reali MT5.

### 9.5 Sistema Adattivo MTF (backtest 730gg)
- **1318 trade totali**, WR 41.1%, P&L $1528, PF 1.164
- **$3.01/giorno** media, mesi positivi: 20/29
- Tutte le strategie operano su timeframe 1H (validato MTF test)

## 10. PROSSIMI STEP (backlog)
- [x] Creazione report automatico giornaliero (`api/report.js`) usando LLM
- [ ] Fine tuning componenti UI (notifiche push quando arriva segnale)
- [ ] Backtest periodico automatico (cron mensile) per rilevare drift parametri
- [ ] Aggiungere filtro news calendar (skip 30 min prima/dopo high-impact event)
- [ ] Notifiche browser (Service Worker) quando strategy engine genera segnale

---

## 11. MT5 EXECUTION BRIDGE (Integrazione Reale)

Per garantire che i segnali della PWA diventino ordini reali su MetaTrader 5, il sistema utilizza un ponte asincrono tramite database.

### 11.1 Flusso di Comando
1.  **Dashboard UI**: Rileva un segnale (S01, S06, etc.) e genera un comando d'ordine.
2.  **API Vercel (`api/db.js`)**: Salva il comando come `mt5_command` nella tabella `user_data`.
3.  **MT5 Bot Locale (`scripts/mt5-bot.py`)**:
    -   Esegue un loop ultra-rapido (ogni **1s**) interrogando `api/db.js?action=mt5_command_get`.
    -   Invia snapshot del conto (equity, bilancio, posizioni) ogni **1s** al DB.
    -   Gestisce attivamente le posizioni con **Break Even** e **Trailing Stop**.
    -   Se trova un comando dalla dashboard, lo esegue immediatamente.

### 11.2 Struttura Comando
```json
{
  "direction": "buy" | "sell",
  "strategy": "S01_EXHAUSTION",
  "tp": 15.0,
  "sl": 9.0,
  "symbol": "GOLD",
  "timestamp": "ISO-DATE"
}
```

### 11.3 Regole di Sicurezza
-   **Scadenza**: I comandi più vecchi di 3 minuti vengono ignorati dal bot (prevenzione esecuzione in ritardo).
-   **Deduplicazione**: Il bot utilizza l'ID comando o il timestamp per non ri-eseguire lo stesso trade.
-   **Dry-Run**: Il bot rispetta il proprio flag `--dry-run` anche per i comandi remoti.

---

## 12. SISTEMA INTERATTIVO & EDUCATIONAL

### 12.1 Interactive Indicators
Ogni indicatore nel dashboard (AI Confidence e MFKK) è ora cliccabile per visualizzare una spiegazione contestuale.
- **Componenti**: `.info-overlay` (glassmorphism modal), `.info-content`.
- **Logica**: Gestita in `dashboard.js` tramite `INDICATOR_DEFS`.
- **Dinamismo**: Le spiegazioni cambiano in base al valore attuale dell'indicatore (es. Trend Forte vs Laterale).

### 12.2 Unified Market Hub (`api/market.js`)
Singola fonte di verità per dati macro e calendario, eliminando problemi di CORS e rate-limiting lato client.
- **Tipi supportati**: `prices` (multi-asset), `calendar` (ForexFactory proxy), `sentiment` (MyFxBook proxy), `cot` (CFTC data).
- **Resilienza**: Implementati timeout rigidi e fallback silenziosi (Yahoo Finance per l'Oil) per evitare il blocco della UI.

---

## 13. AI CONFIDENCE SCORE (V2 — 10 FATTORI)

Il sistema di punteggio istituzionale è stato evoluto per integrare i fondamentali macro insieme alla tecnica pura.

### 13.1 Pesi e Componenti (10% cad. — Bilanciamento Totale)

| Fattore | Tipo | Logica Score (Bullish XAU) |
|---|---|---|
| **Momentum** | Tecnica | Chg > 0.3% → Bullish |
| **DXY Corr** | Correlazione | DXY ↓ XAU ↑ → Bullish |
| **Session KZ** | Timing | London/NY Open → Bullish |
| **Sentiment** | Contrarian | Retail over-short (>65%) → Bullish |
| **Multi-pair** | Confluenza | EUR/GBP/XAU allineati → Bullish |
| **US 10Y Yield**| Macro (Yield) | Rendimenti in calo → Bullish |
| **G/S Ratio** | Macro (Risk) | Ratio in crescita (Safe Haven) → Bullish |
| **COT Data** | Macro (Smart) | Istituzionali Net Long → Bullish |
| **Volatilità** | Rischio | Low range ATR → Bullish (setup puliti) |
| **News Filter** | Rischio | Nessuna news imminente (±30m) → Bullish |

### 13.2 Soglie Operative
- **≥ 75**: FORTE BUY — Setup istituzionale confermato.
- **60-74**: BUY — Setup operabile con size normale.
- **40-59**: NEUTRO — Evitare entrate direzionali.
- **≤ 25**: FORTE SELL — Pressione ribassista coordinata.

### 13.3 Intelligenza Multi-Asset (XAU vs XAG)
Il punteggio si adatta dinamicamente all'asset selezionato (`window.activeAsset`):
- **G/S Ratio**: 
    - Per **XAU**: Ratio alto (>78) = SAFE HAVEN (Bullish Oro).
    - Per **XAG**: Ratio basso (<68) = RISK ON (Bullish Argento).
- **Yield & Confluence**: Etichette e calcoli si basano sul simbolo attivo per evitare disallineamenti macro.
