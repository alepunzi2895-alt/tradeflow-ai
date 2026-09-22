// TradeFlow AI — modules/macro-score.js (2026-09-22)
//
// Punteggio "quello che serve per loro" per le quotazioni macro cliccate nella griglia
// Quotazioni che NON sono asset tradati dall'app (VIX/SPX/NDX/RUT/OIL/US10Y/US02Y) —
// diverso dallo Score Confidenza di XAU/XAG/US30 (mfkk.js/dashboard.js::updateConfidence),
// che resta l'unico invariato. Sola lettura: nessun ordine, nessuna strategia collegata.
//
// Storico via /api/candles (Yahoo, stessa fonte già usata per XAU/XAG/US30 — vedi
// api/price.js::MACRO_TICKERS). Richiede se-signals.js (_rsi/_sma, generiche, non
// specifiche dell'oro) già caricato prima di questo script.
(function(){
  const META = {
    VIX:   {label:'VIX',            kind:'vix',   full:'CBOE Volatility Index'},
    SPX:   {label:'S&P 500',        kind:'index', full:'S&P 500'},
    NDX:   {label:'NASDAQ 100',     kind:'index', full:'Nasdaq 100'},
    RUT:   {label:'Russell 2000',   kind:'index', full:'Russell 2000 (small cap)'},
    OIL:   {label:'Petrolio (WTI)', kind:'trend', full:'WTI Crude Oil'},
    US10Y: {label:'US 10Y',         kind:'yield', full:'Rendimento Treasury 10 anni'},
    US02Y: {label:'US 2Y',          kind:'yield', full:'Rendimento Treasury 2 anni'},
  };

  // dashContext è `let` in core.js: proprietà del global scope condiviso tra script classici,
  // MAI di window (window.dashContext sarebbe sempre undefined) — bug trovato testando con
  // Playwright prima del push (audit 2026-09-22).
  function livePrice(symbol){ return (typeof dashContext!=='undefined' ? dashContext.prices?.[symbol] : null) || null; }

  // RSI(14) + trend vs SMA50 → punteggio 0-100 (50=neutro). Non è il Confidence Score
  // MFKK (pesi ADX/MACD/CCI tarati sull'oro) — qui la lettura è generica per qualunque
  // serie di prezzo, pensata per essere onesta su strumenti mai analizzati prima nell'app.
  function technicalRead(candles){
    const closes = candles.map(c=>c.c).filter(v=>typeof v==='number' && Number.isFinite(v));
    if(closes.length<30) return null;
    const rsiSeries = _rsi(closes, 14);
    const rsi = rsiSeries[rsiSeries.length-1];
    const smaSeries = _sma(closes, 50);
    const sma50 = smaSeries[smaSeries.length-1];
    const last = closes[closes.length-1];
    const trendUp = sma50!=null ? last>sma50 : null;
    let score = rsi!=null ? rsi : 50;
    if(trendUp!=null) score = score*0.65 + (trendUp?68:32)*0.35;
    return {rsi, sma50, last, trendUp, score:Math.max(0,Math.min(100,Math.round(score)))};
  }

  // Fasce VIX: convenzione di mercato nota (non tarata da noi), usata anche come proxy di
  // "sentiment" per gli asset di rischio (SPX/NDX/RUT/OIL) dato che qui non esiste un vero
  // sentiment retail per questi strumenti (MyFxBook copre solo forex/metalli/index CFD).
  function vixBand(level){
    if(typeof level!=='number') return null;
    if(level<15) return {label:'Compiacenza · risk-on forte', color:'var(--green)'};
    if(level<20) return {label:'Normale', color:'var(--dim)'};
    if(level<30) return {label:'Elevato · nervosismo', color:'var(--yellow)'};
    return {label:'Paura · risk-off', color:'var(--red)'};
  }

  // Spread 10Y-2Y dai prezzi live già in memoria (stesso batch da cui arriva la griglia,
  // nessun fetch aggiuntivo) — per uno yield a 2 anni lo spread conta più di un tecnico
  // proprio, ed è l'unico modo pulito di leggerlo: Yahoo non ha un ticker storico diretto
  // per il 2Y (verificato — ^IRX è il 13 settimane, non il 2 anni).
  function yieldSpread(){
    const y10=livePrice('US10Y')?.price, y2=livePrice('US02Y')?.price;
    if(typeof y10!=='number' || typeof y2!=='number') return null;
    const spread=+(y10-y2).toFixed(2);
    return {y10, y2, spread, inverted:spread<0};
  }

  // Forza relativa tra i 3 indici dalla variazione giornaliera già live: small cap (RUT)
  // che guida su mega cap (NDX) è una lettura di ampiezza risk-on/risk-off diffusa, non
  // isolata su un solo titolo — euristica nota, non inventata qui.
  function indexBreadth(){
    const c=s=>{const v=livePrice(s)?.change; return typeof v==='number'?v:null;};
    const spx=c('SPX'), ndx=c('NDX'), rut=c('RUT');
    if(spx==null||ndx==null||rut==null) return null;
    const smallVsBig=+(rut-ndx).toFixed(2);
    return {spx,ndx,rut,smallVsBig,riskOn:smallVsBig>0};
  }

  function scoreColor(score){ return score>=60?'var(--green)':score<=40?'var(--red)':'var(--yellow)'; }
  function fmtNum(v,d=2){ return typeof v==='number' && Number.isFinite(v) ? v.toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d}) : '—'; }

  function renderBody(symbol, meta, live, tech){
    const price = live?.price, change = live?.change;
    const priceRow = `<div class="nb-between" style="align-items:baseline;margin-bottom:14px">
      <div><div style="font-family:'Outfit',sans-serif;font-size:20px;font-weight:700">${meta.full}</div>
      <div style="font-size:11px;color:var(--dim)">${symbol}${meta.kind==='yield'?' · rendimento %':''}</div></div>
      <div style="text-align:right">
        <div class="nb-mono" style="font-size:22px;font-weight:600">${typeof price==='number'?fmtNum(price, meta.kind==='yield'?3:2):'—'}${meta.kind==='yield'?'%':''}</div>
        <div style="font-size:12px;color:${typeof change==='number'?(change>=0?'var(--green)':'var(--red)'):'var(--dim)'}">${typeof change==='number'?(change>=0?'+':'')+fmtNum(change)+'%':'—'}</div>
      </div>
    </div>`;

    let techBlock = '';
    if(tech){
      techBlock = `
      <div class="nb-panel nb-panel--pad" style="margin-bottom:10px">
        <div class="nb-between" style="align-items:baseline;margin-bottom:8px">
          <span class="nb-lbl">Lettura tecnica</span>
          <span class="nb-mono" style="font-size:20px;font-weight:600;color:${scoreColor(tech.score)}">${tech.score}<span style="font-size:11px;color:var(--nb-muted)">/100</span></span>
        </div>
        <div class="nb-bar"><div class="nb-bar__fill" style="width:${tech.score}%;background:${scoreColor(tech.score)}"></div></div>
        <p style="margin:8px 0 0;font-size:12px;line-height:1.6;color:var(--nb-muted)">RSI(14) ${tech.rsi!=null?tech.rsi.toFixed(0):'—'} · ${tech.trendUp==null?'trend non disponibile':tech.trendUp?'sopra la media a 50 giorni (trend rialzista)':'sotto la media a 50 giorni (trend ribassista)'}. Lettura generica RSI+trend, non lo stesso metodo MFKK di XAU/XAG/US30 (pesi tarati sull'oro, qui non applicabili).</p>
      </div>`;
    } else if(meta.kind!=='yield' || symbol!=='US02Y'){
      techBlock = `<div class="nb-panel nb-panel--pad" style="margin-bottom:10px"><p style="margin:0;font-size:12px;color:var(--nb-muted)">Storico non disponibile in questo momento — la caratteristica sotto resta comunque valida (usa solo dati live).</p></div>`;
    }

    let charBlock = '';
    if(meta.kind==='vix'){
      const band = vixBand(price);
      if(band) charBlock = `<div class="nb-panel nb-panel--pad" style="margin-bottom:10px">
        <span class="nb-lbl">Fascia di livello</span>
        <div style="font-size:16px;font-weight:600;color:${band.color};margin-top:4px">${band.label}</div>
        <p style="margin:6px 0 0;font-size:12px;color:var(--nb-muted)">Il VIX è mean-reverting: qui conta il livello assoluto più del trend. Sotto 15 il mercato è storicamente compiacente, sopra 30 in stato di stress — soglie di mercato note, non calibrate da noi.</p>
      </div>`;
    } else if(meta.kind==='yield'){
      const ys = yieldSpread();
      if(ys) charBlock = `<div class="nb-panel nb-panel--pad" style="margin-bottom:10px">
        <span class="nb-lbl">Spread curva 10Y-2Y</span>
        <div style="font-size:16px;font-weight:600;color:${ys.inverted?'var(--red)':'var(--green)'};margin-top:4px">${ys.spread>=0?'+':''}${ys.spread.toFixed(2)}%${ys.inverted?' · curva INVERTITA':''}</div>
        <p style="margin:6px 0 0;font-size:12px;color:var(--nb-muted)">10Y ${fmtNum(ys.y10,3)}% · 2Y ${fmtNum(ys.y2,3)}%. Uno spread negativo (curva invertita) è il segnale macro più citato come anticipatore di recessione — per uno yield conta più di un tecnico di prezzo proprio.</p>
      </div>`;
    } else if(meta.kind==='index'){
      const b = indexBreadth();
      if(b) charBlock = `<div class="nb-panel nb-panel--pad" style="margin-bottom:10px">
        <span class="nb-lbl">Forza relativa small cap vs mega cap</span>
        <div style="font-size:16px;font-weight:600;color:${b.riskOn?'var(--green)':'var(--red)'};margin-top:4px">Russell ${b.smallVsBig>=0?'+':''}${b.smallVsBig.toFixed(2)}pt vs Nasdaq 100 oggi</div>
        <p style="margin:6px 0 0;font-size:12px;color:var(--nb-muted)">SPX ${b.spx>=0?'+':''}${b.spx.toFixed(2)}% · NDX ${b.ndx>=0?'+':''}${b.ndx.toFixed(2)}% · RUT ${b.rut>=0?'+':''}${b.rut.toFixed(2)}%. Small cap che guida = propensione al rischio diffusa (risk-on); mega cap che guida da sola = mercato più difensivo.</p>
      </div>`;
    } else if(meta.kind==='trend'){
      charBlock = `<div class="nb-panel nb-panel--pad" style="margin-bottom:10px">
        <span class="nb-lbl">Contesto</span>
        <p style="margin:4px 0 0;font-size:12px;color:var(--nb-muted)">Il petrolio tende a muoversi in modo indipendente dall'oro (entrambi sensibili al dollaro, ma driver diversi — domanda industriale/energetica vs bene rifugio). Nessuna correlazione calcolata qui, solo contesto.</p>
      </div>`;
    }

    let sentimentBlock = '';
    if(meta.kind==='index' || meta.kind==='trend'){
      const vix = livePrice('VIX')?.price;
      const band = vixBand(vix);
      if(band) sentimentBlock = `<div class="nb-panel nb-panel--pad">
        <span class="nb-lbl">Sentiment di mercato (proxy VIX)</span>
        <div style="font-size:14px;font-weight:600;color:${band.color};margin-top:4px">${band.label} <span class="nb-mono" style="font-size:12px;color:var(--nb-muted);font-weight:400">VIX ${fmtNum(vix)}</span></div>
        <p style="margin:6px 0 0;font-size:12px;color:var(--nb-muted)">Non esiste un sentiment retail (MyFxBook) per ${symbol} — il VIX è lo standard di mercato più vicino a un indicatore di sentiment/paura diffuso, qui riusato come contesto onesto invece di un numero inventato.</p>
      </div>`;
    }

    return priceRow + techBlock + charBlock + sentimentBlock +
      `<p class="data-note" style="margin-top:14px">Sola lettura — nessuna strategia o ordine collegato a questo strumento. Diverso dallo Score Confidenza di XAU/XAG/US30.</p>`;
  }

  window.openMacroScore = async function(symbol, gridLabel){
    const meta = META[symbol] || {label:gridLabel||symbol, kind:'trend', full:gridLabel||symbol};
    const body = document.getElementById('macrosheet-body');
    if(!body) return;
    openOvl('macrosheet');
    body.innerHTML = '<p class="data-note">Calcolo in corso…</p>';
    const live = livePrice(symbol);

    if(symbol==='US02Y'){ // niente storico pulito su Yahoo per il 2Y, vedi yieldSpread()
      body.innerHTML = renderBody(symbol, meta, live, null);
      return;
    }
    const res = await fetchJSON(`/api/candles?asset=${encodeURIComponent(symbol)}&interval=1d&range=6mo`, 9000);
    const tech = (res?.ok && Array.isArray(res.candles)) ? technicalRead(res.candles) : null;
    body.innerHTML = renderBody(symbol, meta, live, tech);
  };
})();
