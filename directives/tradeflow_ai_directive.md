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
  tvprice.js          ← proxy TradingView Scanner per prezzi
  market.js           ← tutti gli asset (DXY, EUR, GBP, OIL, US10Y, Silver, GSR)
  indicators.js       ← MFKK indicators: MACD/ADX da TV Scanner, CCI_S da candle browser
  report.js           ← AI report giornaliero
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

### 7.3 Risultati Backtest Config Ottimale (730gg H1 XAU/USD)

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

### 7.4 Insights chiave dal Backtest Empirico

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

### 7.5 Funzionalità UI aggiunte (calibrate su backtest)

- **4° Conferma EMA50**: mostra allineamento trend + CCI crossover detection in tempo reale
- **Entry Plan dinamico**: calcola Entry / TP / SL / R:R usando ATR(14) + swing H/L degli ultimi 30 bars
  - Base SL = $12 (XAU) adattato agli swing levels reali
  - TP minimo = max($20, SL × 1.67)
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

## 9. PROSSIMI STEP (backlog)
- [ ] Creazione report automatico giornaliero (`api/report.js`) usando LLM per l'interpretazione dei dati
- [ ] Gestione account MyFxBook integrato
- [ ] Fine tuning componenti UI (notifiche e user feedback)
- [ ] Backtest periodico automatico (cron mensile) per rilevare drift nei parametri
- [ ] Aggiungere filtro temporale (no trade nelle prime 2h di sessione Asian)
