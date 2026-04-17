# TradeFlow AI — Dev Rules (DOM, JS, Vercel)

## Regole DOM e JavaScript (CRITICO)

### seRefresh ogni 1s
`setInterval(seRefresh, 1000)` ricostruisce `#se-content` intero ogni secondo.
- **MAI** salvare riferimenti DOM a elementi figli di `#se-content` — diventano stale DOM nodes entro 1s
- Il toast `#se-toast` è appeso a `document.body` — sopravvive al refresh
- `event?.target` catturato in onclick può diventare stale dopo 1s

### Script loading order
I moduli sono caricati come `<script src="...">` (NO `type="module"`):
- Ordine in `index.html`: `se-signals.js` → `strategy.js` → `se-render.js`
- Tutte le funzioni devono essere globali (no `export`/`import`)
- `event?.target` funziona solo in script non-module — OK con setup attuale

### onclick con JSON.stringify
`JSON.stringify()` NON escapa apostrofi. Se un campo stringa contiene apostrofi italiani (es. `dall'ADX`), l'`onclick` si rompe silenziosamente.

**Pattern sicuro**:
```javascript
// ❌ Rotto con apostrofi
onclick='fn(${JSON.stringify(signal)})'

// ✅ Sicuro
const btn = document.createElement('button');
btn.dataset.signal = JSON.stringify(signal);
btn.addEventListener('click', e => fn(JSON.parse(e.currentTarget.dataset.signal)));
```

### Variabili definite vs usate
Bug ricorrente: usare `online` invece di `botOnline` (definita nella closure di `seRender`).
Sempre verificare il nome esatto della variabile nel file prima di usarla.

## Vincoli Vercel Serverless

| Risorsa | Limite |
|---|---|
| Execution time | **10s max** per function |
| RAM | 1024 MB |
| Cold start | ~500ms — timeout < 8s in tutte le fetch |
| IP | Blacklistato da Yahoo Finance e `data.tradingview.com` |

**Pattern obbligatorio per ogni fetch server-side** (copiare verbatim):
```javascript
async function fetchT(url, opts={}, ms=8000) {
  const ctrl = new AbortController();
  const tid = setTimeout(() => ctrl.abort(), ms);
  try { const r = await fetch(url, {...opts, signal: ctrl.signal}); clearTimeout(tid); return r; }
  catch(e) { clearTimeout(tid); throw e; }
}
```

Ogni `fetch` in `api/*.js` DEVE usare questo pattern. Senza timeout, una richiesta bloccata causa `504 Gateway Timeout` su Vercel.

## Aggiornamento Live — Frequenze

| Componente | Intervallo | Cosa fa |
|---|---|---|
| `seRefresh()` (strategy.js) | 1s | Candele + regime + segnali + MT5 sync |
| `recalcIndicators()` (mfkk.js) | 5s | Inietta live price nell'ultima candle + ricalcola CCI_S |
| `loadIndicatorCandles()` (mfkk.js) | 60s | Fetch Yahoo candles + TV Scanner MACD/ADX |
| `sync_to_vercel()` (mt5-bot.py) | 20s | Push stato account + posizioni |
| AI Score fetch (mt5-bot.py) | 60s | Aggiorna `current_ai_score` global |
