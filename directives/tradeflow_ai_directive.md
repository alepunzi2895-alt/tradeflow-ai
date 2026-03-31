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
  └─ Ricalcola CCI_S con live price
  └─ MACD/ADX: usa server TV Scanner (non ricalcola, aggiorna ogni 60s)

Ogni 60 secondi (loadIndicatorCandles):
  ├─ BROWSER: fetch Yahoo XAUUSD=X candles → CCI_S computation
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
| 2026-03-31 | Tutti indicatori = "No candle data" | Vercel IP blacklistato da Yahoo Finance | Fetch candle browser-side in mfkk.js |
| 2026-03-31 | ADX = 0,0,0 | `ADX[10]|60` colonna non valida → null → 0 | Usare `ADX|60` senza parametro custom |
| 2026-03-31 | CCI_S mostra "auto" | range=14d troppo corto o Yahoo XAUUSD=X fallito | range=60d, controllare CORS browser |
| 2026-03-31 | ADX RMA vs SMA | Usavamo Wilder RMA, TV usa SMA(DX,len) | `ADX = sma(DX, len)` come Pine Script |
| 2026-03-31 | MACD params errati | (27,20,5) invece di (12,26,9) | Verificare sempre dai settings dialog TV |

---

## 7. CHECKLIST PRE-DEPLOY

- [ ] Parametri indicatori verificati da settings dialog TradingView (CCI_S, MACD, ADX)
- [ ] Nessun `GC=F` nella lista dei ticker
- [ ] Fetch serverless con timeout < 8s e AbortController
- [ ] Candle fetch per CCI_S lato browser (non server)
- [ ] Colonne TV Scanner senza parametro custom per ADX (`ADX|60` non `ADX[10]|60`)
- [ ] `git push origin main` prima di verificare su Vercel
- [ ] Vercel deploy completato (~60s) prima di testare
- [ ] Aggiornare sezione "Self-Learning Loop" con nuovi bug risolti

---

## 8. PROSSIMI STEP (backlog)

- [ ] **Backtesting MFKK score**: testare su 1 anno di candle H1 XAU/USD per calibrare pesi e soglie dello scoring
- [ ] **Fix ADX exact match**: implementare SMA(DX,10) lato browser-side per replicare esattamente "ADX and DI for v4"
- [ ] **CCI_S vs TV**: verificare allineamento dopo fix range=60d
- [ ] **Auto-refresh MACD/ADX**: polling ogni 60s con indicator del server reload
