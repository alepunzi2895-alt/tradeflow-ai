// TradeFlow AI — modules/mfkk.js

// Scroll-safe value setter — saves/restores dash-panel scroll position
function _setVal(id, v){
  const el = document.getElementById(id);
  if(!el || v==null || isNaN(+v)) return;
  el.value = +v;
}

// ── MFKK STRATEGY SCORE ──────────────────────────────────
let mfkkDir = 'buy'; // 'buy' or 'sell'
const mfkkTF = '1h'; // MFKK works on H1 only

function setMfkkTF(tf){
  mfkkTF = tf;
  ['1h','4h','1d'].forEach(t=>{
    const btn=document.getElementById('mfkk-tf-'+t);
    if(!btn)return;
    if(t===tf){btn.style.background='#c8a96e30';btn.style.borderColor='#c8a96e55';btn.style.color='var(--g)';}
    else{btn.style.background='var(--bg2)';btn.style.borderColor='var(--border)';btn.style.color='var(--dim)';}
  });
  loadIndicators();
}

// ── MFKK INDICATOR ENGINE ────────────────────────────────
// Candle cache: fetch once per minute, recalculate every 5s with live price
let mfkkCandles = [];     // H1 OHLCV cache (fetched browser-side — shared with strategy.js via window)
Object.defineProperty(window,'mfkkCandles',{get:()=>mfkkCandles,set:v=>{mfkkCandles=v;}});
let mfkkLastFetch = 0;    // timestamp of last candle fetch
let mfkkServerMacd = null; // MACD/ADX from TV Scanner via /api/indicators
let mfkkServerAdx = null;
// Confirmation & Entry Plan data (calcolati da computeFromCandles)
let mfkkEma50 = null;
let mfkkAtr = null;
let mfkkSwingHigh = null;
let mfkkSwingLow = null;

// Math helpers
function _ema(src,p){
  // TradingView ta.ema(): first value as seed (not SMA)
  const k=2/(p+1);
  let v=src[0];
  const o=[v];
  for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
  return o;
}
function _sma(src,p){const o=new Array(src.length).fill(null);for(let i=p-1;i<src.length;i++){let s=0;for(let j=0;j<p;j++)s+=(src[i-j]||0);o[i]=s/p;}return o;}
function _hi(a,p,i){let m=-Infinity;for(let j=Math.max(0,i-p+1);j<=i;j++)if(a[j]!=null)m=Math.max(m,a[j]);return m;}
function _lo(a,p,i){let m=Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++)if(a[j]!=null)m=Math.min(m,a[j]);return m;}

function computeFromCandles(candles, tf){
  // Resample to H4 if needed
  let c4 = candles;
  if(tf==='4h'){
    const map=new Map();
    for(const c of candles){
      const d=new Date(c.t*1000);
      const b=Math.floor(d.getUTCHours()/4)*4;
      const k=`${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${b}`;
      if(!map.has(k))map.set(k,{t:c.t,h:c.h,l:c.l,c:c.c});
      else{const e=map.get(k);e.h=Math.max(e.h,c.h);e.l=Math.min(e.l,c.l);e.c=c.c;e.t=c.t;}
    }
    c4=[...map.values()].sort((a,b)=>a.t-b.t);
  }
  if(c4.length<120)return null; // need at least 120 candles for CCI(50)+Stoch(50)+SMA(8)+SMA(8) warmup

  const H=c4.map(x=>x.h), L=c4.map(x=>x.l), C=c4.map(x=>x.c), n=C.length;

  // CCI_S: CCI(close,50) → stoch(cci,cci,cci,50) → SMA(K,8) → SMA(D,8) — exact Pine Script v4
  const CCI_P=50, STOCH_P=50, SK=8, SD=8;
  const cci=new Array(n).fill(null);
  for(let i=CCI_P-1;i<n;i++){
    const sl=C.slice(i-CCI_P+1,i+1);
    const mn=sl.reduce((a,b)=>a+b,0)/CCI_P;
    const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CCI_P;
    cci[i]=md===0?0:(C[i]-mn)/(0.015*md);
  }
  // stoch(cci,cci,cci,50) — pine: 100*(src-lowest)/(highest-lowest)
  const stk=new Array(n).fill(null);
  for(let i=CCI_P+STOCH_P-2;i<n;i++){
    if(cci[i]==null)continue;
    const lv=_lo(cci,STOCH_P,i), hv=_hi(cci,STOCH_P,i);
    stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;
  }
  // SMA(stoch,8) — propagate null like Pine Script (no 50-fill)
  const stk_k=new Array(n).fill(null);
  for(let i=SK-1;i<n;i++){
    const sl=stk.slice(i-SK+1,i+1);
    if(sl.some(v=>v==null))continue;
    stk_k[i]=sl.reduce((a,b)=>a+b,0)/SK;
  }
  const stk_d=new Array(n).fill(null);
  for(let i=SD-1;i<n;i++){
    const sl=stk_k.slice(i-SD+1,i+1);
    if(sl.some(v=>v==null))continue;
    stk_d[i]=sl.reduce((a,b)=>a+b,0)/SD;
  }
  const cciVal=+(stk_d[n-1]??50).toFixed(2);
  const cciPrev=stk_d[n-2];
  let cciSig='neutral';
  if(cciPrev!=null){
    if(cciPrev>=25&&cciVal<25)cciSig='enter_buy';
    else if(cciPrev<=75&&cciVal>75)cciSig='enter_sell';
    else if(cciPrev>75&&cciVal<=75)cciSig='exit_sell';
    else if(cciPrev<25&&cciVal>=25)cciSig='exit_buy';
  }

  // MACD(12,26,9) EMA — standard Pine Script v6 default parameters
  const e12=_ema(C,12), e26=_ema(C,26);
  const ml=e12.map((v,i)=>v-e26[i]);
  const sg=_ema(ml,9);
  const hist=ml.map((v,i)=>v-sg[i]);
  const macdVal=+ml[n-1].toFixed(4), sigVal=+sg[n-1].toFixed(4);
  const histVal=+hist[n-1].toFixed(4), histPrev=+(hist[n-2]||0).toFixed(4);
  let cross=macdVal>sigVal?'above':'below';
  if((ml[n-2]||0)<=(sg[n-2]||0)&&macdVal>sigVal)cross='cross_buy';
  else if((ml[n-2]||0)>=(sg[n-2]||0)&&macdVal<sigVal)cross='cross_sell';

  // ADX: Wilder smoothing for TR/DM, then SMA(DX,len) — exact Pine Script "ADX and DI for v4"
  const ADX_P=10; // Per=10 as set in user's TradingView indicator settings
  const TR=new Array(n).fill(0),DMP=new Array(n).fill(0),DMM=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
    const upMove=H[i]-H[i-1], downMove=L[i-1]-L[i];
    DMP[i]=(upMove>downMove&&upMove>0)?upMove:0;
    DMM[i]=(downMove>upMove&&downMove>0)?downMove:0;
  }
  // Wilder smoothing: X = X[1] - X[1]/len + value (nz() starts at 0)
  const sTR=new Array(n).fill(0),sDMP=new Array(n).fill(0),sDMM=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    sTR[i]=sTR[i-1]-sTR[i-1]/ADX_P+TR[i];
    sDMP[i]=sDMP[i-1]-sDMP[i-1]/ADX_P+DMP[i];
    sDMM[i]=sDMM[i-1]-sDMM[i-1]/ADX_P+DMM[i];
  }
  const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
  const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
  const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
  // ADX = SMA(DX, len) — Pine Script uses simple moving average here, NOT Wilder RMA!
  const ADX=_sma(DX, ADX_P);

  // EMA50 — trend filter (4th confirmation)
  const e50=_ema(C,50);
  const ema50Val=+e50[n-1].toFixed(2);

  // ATR(14) — per calcolo TP/SL dinamico
  const TR14=new Array(n).fill(0);
  for(let i=1;i<n;i++){
    TR14[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
  }
  const atr14=_sma(TR14,14);
  const atrVal=+(atr14[n-1]??1).toFixed(2);

  // Swing high/low degli ultimi 30 bars (resistenza/supporto recente)
  const SW=30;
  let swHigh=-Infinity, swLow=Infinity;
  for(let i=Math.max(1,n-SW);i<n-1;i++){
    swHigh=Math.max(swHigh,H[i]);
    swLow =Math.min(swLow, L[i]);
  }

  return {
    cci:{value:cciVal,signal:cciSig,zone:cciVal>75?'overbought':cciVal<25?'oversold':'neutral'},
    macd:{macd:macdVal,signal:sigVal,histogram:histVal,hist_prev:histPrev,hist_rising:histVal>histPrev,cross},
    adx:{adx:+ADX[n-1].toFixed(2),di_plus:+DIP[n-1].toFixed(2),di_minus:+DIM[n-1].toFixed(2)},
    ema50:ema50Val, atr:atrVal, swingHigh:+swHigh.toFixed(2), swingLow:+swLow.toFixed(2),
    last_close:+C[n-1].toFixed(2), candles:n
  };
}

// Fetch candles via server proxy (bypasses both CORS and IP blocks)
async function fetchBrowserCandles(){
  try{
    // Try our server proxy first (it handles Yahoo + TV history fallback)
    const asset = window.activeAsset || 'XAU';
    const url = `/api/candles?asset=${asset}&range=60d&interval=1h`;
    const r = await fetch(url);
    if(!r.ok) throw new Error('Candle proxy HTTP '+r.status);
    const d = await r.json();
    if(!d?.ok || !d.candles?.length) throw new Error('No candles from proxy');
    console.log('Server candle proxy OK:', d.count, 'candles from', d.source);
    return d.candles;
  }catch(e){
    console.log('fetchBrowserCandles proxy:', e.message);
    // Fallback: try the indicators API which also returns candle_data
    try{
      const asset = window.activeAsset || 'XAU';
      const d = await fetchJSON(`/api/indicators?asset=${asset}&tf=1h`, 12000);
      if(d?.ok && d.candle_data?.length > 50){
        console.log('Candles from indicators API:', d.candle_data.length);
        return d.candle_data;
      }
    }catch(e2){ console.log('Candle fallback:', e2.message); }
    return [];
  }
}


// Fetch all indicators from /api/indicators (MACD from TV Scanner + ADX/CCI from candles)
async function fetchServerIndicators(){
  try{
    const asset = window.activeAsset || 'XAU';
    const d = await fetchJSON(`/api/indicators?asset=${asset}&tf=${mfkkTF}`, 12000);
    if(d?.ok){
      if(d.macd) mfkkServerMacd = d.macd;
      if(d.adx)  mfkkServerAdx  = d.adx;
      console.log('Server indicators: MACD='+(d.macd?.macd?.toFixed(2)??'N/A')+' ADX='+(d.adx?.adx?.toFixed(2)??'N/A')+' CCI='+(d.cci?.value??'N/A')+' ['+d.macd_source+']');
    }
    return d;
  }catch(e){ console.log('fetchServerIndicators:', e.message); return null; }
}


// Main loader: fetches candles + server indicators, populates all MFKK fields
async function loadIndicatorCandles(){
  try{
    mfkkLastFetch = Date.now();
    const telEl = document.getElementById('mfkk-time');

    // Run in parallel: candle proxy (for CCI_S live recalc) + server indicators (MACD+ADX+CCI)
    const [candles, serverData] = await Promise.all([
      fetchBrowserCandles(),
      fetchServerIndicators()
    ]);

    const set = (id,v) => _setVal(id,v);

    // Store candles for live recalc
    if(candles.length > 0) mfkkCandles = candles;

    // CCI_S + EMA50 + ATR + swings dal calcolo locale sulle candele
    if(mfkkCandles.length >= 120){
      const vals = computeFromCandles(mfkkCandles, mfkkTF);
      if(vals){
        const cciVal = vals.cci?.value ?? vals.cci;
        if(cciVal != null && !isNaN(cciVal)) set('mfkk-cci', cciVal);
        if(vals.ema50!=null)     mfkkEma50=vals.ema50;
        if(vals.atr!=null)       mfkkAtr=vals.atr;
        if(vals.swingHigh!=null) mfkkSwingHigh=vals.swingHigh;
        if(vals.swingLow!=null)  mfkkSwingLow=vals.swingLow;
        console.log('CCI_S:',cciVal,'EMA50:',vals.ema50,'ATR:',vals.atr,'SwH:',vals.swingHigh,'SwL:',vals.swingLow);
      }
    } else if(serverData?.cci?.value != null){
      set('mfkk-cci', serverData.cci.value);
    }

    // MACD: from TV Scanner (exact TradingView values)
    if(mfkkServerMacd){
      set('mfkk-macd-fast', mfkkServerMacd.macd);
      set('mfkk-macd-slow', mfkkServerMacd.signal);
      set('mfkk-macd-hist', mfkkServerMacd.histogram);
    }

    // ADX(10): prefer server-computed (exact Pine Script formula)
    if(mfkkServerAdx?.adx != null){
      set('mfkk-adx',     mfkkServerAdx.adx);
      set('mfkk-diplus',  mfkkServerAdx.di_plus);
      set('mfkk-diminus', mfkkServerAdx.di_minus);
    }

    // Update timestamp display
    if(telEl){
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      const now = new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit',timeZone:tz});
      const price = serverData?.last_close || mfkkCandles.at(-1)?.c || '?';
      telEl.textContent = '$'+price+' · '+now+' ('+mfkkTF.toUpperCase()+') ⟳';
    }

    if(serverData?.ok || mfkkCandles.length >= 120){
      dashContext.indicatorBase = serverData;
      dashContext.indicators = serverData;
      setTimeout(autoSelectBestDir, 50);
    }
  }catch(e){ console.log('loadIndicatorCandles:', e.message); }
}



// Recalculate CCI_S ogni 5s: inietta prezzo live nell'ultima candela
// MACD e ADX usano i valori del TV Scanner (aggiornati ogni 60s)
function recalcIndicators(){
  if(mfkkCandles.length<50) return;
  const asset = window.activeAsset || 'XAU';
  const livePrice = marketData?.[asset]?.price ?? marketData?.XAU?.price;
  if(!livePrice) return;
  const live=parseFloat(livePrice);
  if(isNaN(live)) return;

  // Clone candles e aggiorna l'ultima con prezzo live
  const candles=[...mfkkCandles];
  const last={...candles[candles.length-1]};
  last.c=live; last.h=Math.max(last.h,live); last.l=Math.min(last.l,live);
  candles[candles.length-1]=last;

  // Ricalcola CCI_S + EMA50 + ATR + swing con prezzo live
  const vals=computeFromCandles(candles, mfkkTF);
  if(!vals) return;

  // Salva dati per conferma e entry plan
  if(vals.ema50!=null)     mfkkEma50=vals.ema50;
  if(vals.atr!=null)       mfkkAtr=vals.atr;
  if(vals.swingHigh!=null) mfkkSwingHigh=vals.swingHigh;
  if(vals.swingLow!=null)  mfkkSwingLow=vals.swingLow;

  const set=(id,v)=>_setVal(id,v);
  const cv=vals.cci?.value??vals.cci;
  // Aggiorna CCI dal calcolo locale (usa prezzo live)
  if(cv != null && !isNaN(cv)) set('mfkk-cci', cv);


  // Use server TV Scanner values for MACD/ADX (no recalc needed - they update every 60s)
  const mv = mfkkServerMacd?.macd;
  const sv_val = mfkkServerMacd?.signal;
  const hv = mfkkServerMacd?.histogram;
  const av = mfkkServerAdx?.adx;
  const dp = mfkkServerAdx?.di_plus;
  const dm = mfkkServerAdx?.di_minus;
  if(mv!=null){set('mfkk-macd-fast',mv);set('mfkk-macd-slow',sv_val);set('mfkk-macd-hist',hv);}
  if(av!=null){set('mfkk-adx',av);set('mfkk-diplus',dp);set('mfkk-diminus',dm);}


  const telEl=document.getElementById('mfkk-time');
  if(telEl){
    const now=new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});
    telEl.textContent='$'+live+' · '+now+' ⚡live';
  }
  calcMfkk();
  setTimeout(autoSelectBestDir,20);
}

// Backward compatible wrapper
async function loadIndicators(){
  return loadIndicatorCandles();
}

function setMfkkDir(dir){
  mfkkDir = dir;
  document.getElementById('mfkk-buy').className = 'mfkk-dir' + (dir==='buy'?' on-buy':'');
  document.getElementById('mfkk-sell').className = 'mfkk-dir' + (dir==='sell'?' on-sell':'');
  calcMfkk();
}

function calcMfkk(){
  const dir = mfkkDir;
  const isBuy = dir === 'buy';
  const cciVal    = parseFloat(document.getElementById('mfkk-cci').value);
  const macdFast  = parseFloat(document.getElementById('mfkk-macd-fast').value);
  const macdSlow  = parseFloat(document.getElementById('mfkk-macd-slow').value);
  const macdHist  = parseFloat(document.getElementById('mfkk-macd-hist').value);
  const adxVal    = parseFloat(document.getElementById('mfkk-adx').value);
  const diPlus    = parseFloat(document.getElementById('mfkk-diplus').value);
  const diMinus   = parseFloat(document.getElementById('mfkk-diminus').value);
  const hasCci = !isNaN(cciVal);
  const hasMacd = !isNaN(macdFast) && !isNaN(macdSlow);
  const hasHist = !isNaN(macdHist);
  const hasAdx = !isNaN(adxVal) && !isNaN(diPlus) && !isNaN(diMinus);

  if(!hasCci && !hasMacd && !hasAdx){
    ['mfkk-num','mfkk-bias','mfkk-circle','mfkk-desc','mfkk-quality'].forEach(id=>{
      const el=document.getElementById(id);
      if(!el)return;
      if(id==='mfkk-num')el.textContent='0';
      if(id==='mfkk-bias'){el.textContent='In attesa di dati...';el.style.color='var(--dim)';}
      if(id==='mfkk-circle'){el.style.strokeDashoffset='163.4';el.style.stroke='var(--dim)';}
      if(id==='mfkk-desc')el.textContent='Caricamento automatico indicatori...';
      if(id==='mfkk-quality')el.style.display='none';
    });
    return;
  }

  // ── CCI SCORE — calibrato su 2 anni XAU/XAG H1 (trend-continuation) ──────
  // Backtest finding: CCI non è mean-reversion ma trend-alignment.
  // OB_DEEP per BUY (trend up continua) e OS_DEEP per SELL (trend down continua)
  // hanno win-rate migliori. OB_DEEP+SELL = esaurimento (gestito da MACD/ADX).
  let cciScore=50, cciCol='var(--dim)', cciHint='';
  if(hasCci){
    if(isBuy){
      // Trend-continuation BUY: alto CCI = uptrend in corso = favorevole
      if(cciVal>=75){cciScore=60;cciCol='var(--green)';cciHint='OB ('+cciVal.toFixed(0)+') — uptrend forte, BUY momentum. ADX determina qualità.';}
      else if(cciVal>=65){cciScore=52;cciCol='var(--green)';cciHint='Zona alta ('+cciVal.toFixed(0)+') — buon momentum BUY in trend rialzista';}
      else if(cciVal>=50){cciScore=45;cciCol='var(--yellow)';cciHint='Zona centrale-alta ('+cciVal.toFixed(0)+') — momentum neutro, attendere ADX';}
      else if(cciVal>=35){cciScore=38;cciCol='var(--yellow)';cciHint='Zona bassa ('+cciVal.toFixed(0)+') — trend incerto per BUY';}
      else if(cciVal>=25){cciScore=28;cciCol='var(--red)';cciHint='OS_EXIT ('+cciVal.toFixed(0)+') — uscita zona ribassista, BUY rischioso';}
      else{cciScore=18;cciCol='var(--red)';cciHint='OS_DEEP ('+cciVal.toFixed(0)+') — downtrend dominante, evita BUY (WR 31% storico)';}
    } else {
      // Trend-continuation SELL: basso CCI = downtrend in corso = favorevole
      // OS_DEEP per SELL = 48% WR (migliore per SELL), OB_DEEP+ADX forte = esaurimento 82%+ WR
      if(cciVal<=25){cciScore=65;cciCol='var(--green)';cciHint='OS_DEEP ('+cciVal.toFixed(0)+') — downtrend forte, SELL momentum (WR 48% storico)';}
      else if(cciVal<=35){cciScore=58;cciCol='var(--green)';cciHint='OS_EXIT ('+cciVal.toFixed(0)+') — buon momentum SELL in trend ribassista';}
      else if(cciVal<=50){cciScore=50;cciCol='var(--yellow)';cciHint='Zona centrale-bassa ('+cciVal.toFixed(0)+') — SELL neutro, peso su ADX';}
      else if(cciVal<=65){cciScore=44;cciCol='var(--yellow)';cciHint='Zona alta ('+cciVal.toFixed(0)+') — SELL moderato, servono ADX+MACD forti';}
      else if(cciVal<75){cciScore=40;cciCol='var(--yellow)';cciHint='OB_EXIT ('+cciVal.toFixed(0)+') — attenzione: potenziale esaurimento (ADX decide)';}
      else{cciScore=40;cciCol='var(--yellow)';cciHint='OB_DEEP ('+cciVal.toFixed(0)+') — se ADX≥35+DI- dominante = esaurimento SELL 82%+ WR';}
    }
    const pct=Math.max(0,Math.min(100,cciScore));
    const bar=document.getElementById('mfkk-cci-bar');
    const pp=document.getElementById('mfkk-cci-pct');
    const hint=document.getElementById('mfkk-cci-hint');
    const row=document.getElementById('mfkk-cci-row');
    if(bar){bar.style.width=pct+'%';bar.style.background=cciCol;}
    if(pp){pp.textContent=pct;pp.style.color=cciCol;}
    if(hint)hint.textContent=cciHint;
    if(row)row.style.borderColor=cciScore>=70?cciCol+'55':'var(--border)';
  }

  // ── MACD SCORE (35%) — params: 12,26,9 EMA ─────────────
  let macdScore=50, macdCol='var(--dim)', macdHint='';
  if(hasMacd){
    const diff=macdFast-macdSlow;
    const str=Math.min(Math.abs(diff)/3,1);
    // Histogram adds confirmation: if hist same direction as signal = stronger
    const histBonus=hasHist?((isBuy&&macdHist>0)||((!isBuy)&&macdHist<0)?10:0):0;
    if(isBuy){
      if(diff>0.5){macdScore=Math.round(65+str*25)+histBonus;macdCol='var(--green)';macdHint='BLU>ROSSO +'+diff.toFixed(2)+(hasHist?' Hist:'+macdHist.toFixed(2):'')+(Math.abs(diff)>1?' FORTE':'');}
      else if(diff>0){macdScore=60+histBonus;macdCol='var(--yellow)';macdHint='Appena incrociato BUY'+(hasHist?' · Hist:'+macdHist.toFixed(2):'');}
      else if(diff>-1){macdScore=30;macdCol='var(--yellow)';macdHint='Prossimo cross BUY — attendi';}
      // Backtest: MACD bearish forte + BUY = può essere esaurimento del ribasso (ADX decide)
      else if(diff>-3){macdScore=40;macdCol='var(--yellow)';macdHint='MACD bearish ('+diff.toFixed(2)+') — possibile esaurimento, ADX+DI+ necessari';}
      else{macdScore=15;macdCol='var(--red)';macdHint='ROSSO>BLU '+diff.toFixed(2)+' — trend ribassista forte, BUY solo su ADX estremo';}
    } else {
      if(diff<-0.5){macdScore=Math.round(65+str*25)+histBonus;macdCol='var(--green)';macdHint='ROSSO>BLU '+diff.toFixed(2)+(hasHist?' Hist:'+macdHist.toFixed(2):'')+(Math.abs(diff)>1?' FORTE':'');}
      else if(diff<0){macdScore=60+histBonus;macdCol='var(--yellow)';macdHint='Appena incrociato SELL'+(hasHist?' · Hist:'+macdHist.toFixed(2):'');}
      else if(diff<1){macdScore=30;macdCol='var(--yellow)';macdHint='Prossimo cross SELL — attendi';}
      // Backtest finding: MACD bullish forte + SELL + ADX DI- forte = esaurimento 82-88% WR
      else if(diff<3){macdScore=45;macdCol='var(--yellow)';macdHint='MACD bullish ('+diff.toFixed(2)+') — ESAURIMENTO: se ADX≥35+DI-, WR 82%+ storico';}
      else{macdScore=48;macdCol='var(--yellow)';macdHint='MACD super-esteso rialzista ('+diff.toFixed(2)+') — ESAURIMENTO MASSIMO, attendi ADX DI- dominante';}
    }
    const pct=Math.max(0,Math.min(100,macdScore));
    const bar=document.getElementById('mfkk-macd-bar');
    const pp=document.getElementById('mfkk-macd-pct');
    const hint=document.getElementById('mfkk-macd-hint');
    const row=document.getElementById('mfkk-macd-row');
    if(bar){bar.style.width=pct+'%';bar.style.background=macdCol;}
    if(pp){pp.textContent=pct;pp.style.color=macdCol;}
    if(hint)hint.textContent=macdHint;
    if(row)row.style.borderColor=macdScore>=70?macdCol+'55':'var(--border)';
  }

  // ── ADX SCORE (30%) — params: period=10, Th=10 ──────────
  let adxScore=50, adxCol='var(--dim)', adxHint='';
  if(hasAdx){
    const diDiff=diPlus-diMinus;
    const diSpread=Math.abs(diDiff);
    const spreadBonus=Math.min(diSpread/20,1);
    let adxStr=adxVal>=35?1.0:adxVal>=27?0.85:adxVal>=20?0.65:adxVal>=14?0.4:adxVal>=10?0.2:0.05;
    if(isBuy){
      if(diDiff>0&&adxVal>=25){
        adxScore=Math.round(60+adxStr*25+spreadBonus*15);adxCol='var(--green)';
        adxHint='DI+('+diPlus.toFixed(1)+')>DI-('+diMinus.toFixed(1)+') gap '+diSpread.toFixed(1)+' · ADX '+adxVal.toFixed(1)+' '+(adxVal>=30?'FORTE':'mod.');
      } else if(diDiff>0&&adxVal>=10){
        adxScore=50;adxCol='var(--yellow)';adxHint='DI+>DI- · ADX '+adxVal.toFixed(1)+' (sopra Th=10, < 25) trend nascente';
      } else if(diDiff>0){
        adxScore=30;adxCol='var(--yellow)';adxHint='DI+>DI- ma ADX '+adxVal.toFixed(1)+' < Th=10 — laterale';
      } else if(diDiff<0&&adxVal>=35){
        adxScore=Math.round(60+adxStr*25+spreadBonus*15);adxCol='var(--green)';
        adxHint='DI-('+diMinus.toFixed(1)+')>DI+('+diPlus.toFixed(1)+') ma ADX esteso ('+adxVal.toFixed(1)+') — SETUP INVERSIONE BUY';
      } else {
        adxScore=5;adxCol='var(--red)';adxHint='DI-('+diMinus.toFixed(1)+')>DI+('+diPlus.toFixed(1)+') — bearish, no BUY';
      }
    } else {
      if(diDiff<0&&adxVal>=25){
        adxScore=Math.round(60+adxStr*25+spreadBonus*15);adxCol='var(--green)';
        adxHint='DI-('+diMinus.toFixed(1)+')>DI+('+diPlus.toFixed(1)+') gap '+diSpread.toFixed(1)+' · ADX '+adxVal.toFixed(1)+' '+(adxVal>=30?'FORTE':'mod.');
      } else if(diDiff<0&&adxVal>=10){
        adxScore=50;adxCol='var(--yellow)';adxHint='DI->DI+ · ADX '+adxVal.toFixed(1)+' (sopra Th=10, < 25) trend nascente';
      } else if(diDiff<0){
        adxScore=30;adxCol='var(--yellow)';adxHint='DI->DI+ ma ADX '+adxVal.toFixed(1)+' < Th=10 — laterale';
      } else if(diDiff>0&&adxVal>=35){
        adxScore=Math.round(60+adxStr*25+spreadBonus*15);adxCol='var(--green)';
        adxHint='DI+('+diPlus.toFixed(1)+')>DI-('+diMinus.toFixed(1)+') ma ADX esteso ('+adxVal.toFixed(1)+') — SETUP INVERSIONE SELL';
      } else {
        adxScore=5;adxCol='var(--red)';adxHint='DI+('+diPlus.toFixed(1)+')>DI-('+diMinus.toFixed(1)+') — bullish, no SELL';
      }
    }
    adxScore=Math.max(0,Math.min(100,adxScore));
    const bar=document.getElementById('mfkk-adx-bar');
    const pp=document.getElementById('mfkk-adx-pct');
    const hint=document.getElementById('mfkk-adx-hint');
    const row=document.getElementById('mfkk-adx-row');
    if(bar){bar.style.width=adxScore+'%';bar.style.background=adxCol;}
    if(pp){pp.textContent=adxScore;pp.style.color=adxCol;}
    if(hint)hint.textContent=adxHint;
    if(row)row.style.borderColor=adxScore>=70?adxCol+'55':'var(--border)';
  }

  // ── WEIGHTED TOTAL ─────────────────────────────────────
  // Pesi ottimizzati su 2 anni H1 (grid search 2272 combinazioni):
  // XAU: CCI 10%, MACD 10%, ADX 80% → PF 1.802, WR 51.9%, P&L $6648
  // XAG: CCI 25%, MACD 15%, ADX 60% (trend-dipendente, meno dati)
  let tot=0, w=0;
  const isXag = window.activeAsset === 'XAG';
  const wCci = isXag ? 0.25 : 0.10;
  const wMacd = isXag ? 0.15 : 0.10;
  const wAdx = isXag ? 0.60 : 0.80;

  if(hasCci){tot+=cciScore*wCci;w+=wCci;}
  if(hasMacd){tot+=macdScore*wMacd;w+=wMacd;}
  if(hasAdx){tot+=adxScore*wAdx;w+=wAdx;}
  const score=w>0?Math.round(tot/w):0;
  const allThree=hasCci&&hasMacd&&hasAdx;
  const strong=[hasCci&&cciScore>=70,hasMacd&&macdScore>=70,hasAdx&&adxScore>=70].filter(Boolean).length;
  const weak=[hasCci&&cciScore<=30,hasMacd&&macdScore<=30,hasAdx&&adxScore<=30].filter(Boolean).length;
  const col=score>=75?'var(--green)':score>=55?'var(--yellow)':score>=40?'var(--yellow)':'var(--red)';
  const dirLabel=isBuy?'BUY':'SELL';
  let bias='', desc='';
  
  // Soglie ottimizzate da backtest 2 anni (2272 combinazioni):
  // BUY richiede score >=90 (WR 43.5%), SELL basta >=68 (WR 54.3%)
  const BUY_THR = 90, SELL_THR = 68;
  const isValidEntry = isBuy ? (score >= BUY_THR) : (score >= SELL_THR);

  // Rilevamento pattern esaurimento: ADX forte con MACD contro-trend (backtest: 82-88% WR sell)
  const macdDiff = hasMacd ? (macdFast - macdSlow) : 0;
  const isExhaustionSell = !isBuy && hasAdx && hasMacd && adxScore >= 75 && macdDiff > 1.0;
  const isExhaustionBuy  = isBuy && hasAdx && hasMacd && adxScore >= 75 && macdDiff < -1.0;
  const isExhaustion = isExhaustionSell || isExhaustionBuy;

  // HIGH-WR SIGNAL: hard filter rules da optimize-highwr.py (backtest 730gg H1 XAU)
  // ADX>=35 + DI spread>=20 + MACD diff>=1.0 (bullish MACD = esaurimento SELL) + CCI not OS + London/NY
  // Risultato: 95% WR (20 trade), 92.9% WR (28 trade) — SELL ONLY (BUY non affidabile)
  const nowHour = new Date().getUTCHours();
  const isLondonNY = nowHour >= 7 && nowHour < 17;
  const diSpreadAbs = hasAdx ? Math.abs(diPlus - diMinus) : 0;
  const isHighWrSell = !isBuy && hasAdx && hasMacd && hasCci
    && adxVal >= 35
    && diMinus > diPlus       // DI- dominante (bearish)
    && diSpreadAbs >= 20      // spread ampio = trend forte e chiaro
    && macdDiff >= 1.0        // MACD bullish esteso = esaurimento del rialzo (pattern inversione)
    && cciVal >= 25           // CCI non in OS (ob_or_neutral)
    && isLondonNY;            // sessione London/NY (7-17 UTC)
  const isHighWrSignal = isHighWrSell; // BUY WR ~46% — non abbastanza per HIGH-WR flag

  if(isHighWrSignal){
    bias='💎 HIGH-WR SELL';
    desc='Filtri hard: ADX≥35+DI spread≥20+MACD esaurito+London/NY → 92-95% WR storico (730gg)';
  } else if(isExhaustion && adxScore >= 80 && isValidEntry){
    bias=dirLabel+' ESAURIMENTO';
    desc='ADX forte + MACD esteso = pattern inversione 82-88% WR storico H1. ADX DI domina.';
  } else if(score>=90&&allThree&&strong>=2){
    bias=dirLabel+' FORTE';
    desc=isBuy
      ? 'Score BUY ≥90 — soglia minima calibrata. TP $20 SL $12 consigliati.'
      : 'Tutti gli indicatori allineati — setup SELL ad alta convinzione.';
  } else if(!isBuy && score>=80&&allThree){
    bias='SELL OTTIMALE';
    desc='Setup SELL ideale H1 confermato da 2 anni backtest — TP $20 SL $12';
  } else if(!isBuy && score>=68&&adxScore>=70){
    bias='SELL VALIDO';
    desc='ADX confermato — SELL valido. Score ≥68 sufficiente per SELL (backtest).';
  } else if(isBuy && score>=90){
    bias='BUY VALIDO';
    desc='Score BUY ≥90 raggiunto — soglia minima per BUY secondo backtest 2 anni.';
  } else if(isBuy && score>=80){
    bias='BUY PARZIALE';
    desc='BUY: score 80-89 — ancora sotto soglia ottimale (90+). Attendi conferma.';
  } else if(score>=55){
    bias=dirLabel+' PARZIALE';
    desc='Segnale parziale — attendi ulteriori conferme';
  } else if(score>=40){
    bias='NEUTRO';
    desc='Indicatori misti — evita entries adesso';
  } else{
    bias='CONTRO '+dirLabel;
    desc='Segnale contro la direzione predominante — no trade';
  }

  // Render — colori basati su soglie calibrate (BUY>=90, SELL>=68)
  const DASH=163.4;
  const ringCol = isHighWrSignal ? '#ffd700'
    : isValidEntry
      ? (isExhaustion ? '#b36cff' : (score>=90?'var(--yellow)':col))
      : (score>=55?'var(--yellow)':'var(--red)');
  const circ=document.getElementById('mfkk-circle');
  if(circ){circ.style.strokeDashoffset=DASH*(1-score/100);circ.style.stroke=ringCol;}
  const num=document.getElementById('mfkk-num');
  if(num){num.textContent=score;num.style.color=ringCol;}
  const bel=document.getElementById('mfkk-bias');
  if(bel){bel.textContent=bias;bel.style.color=isHighWrSignal?'#ffd700':(score>=80?'var(--yellow)':col);}
  const del=document.getElementById('mfkk-desc');
  if(del)del.textContent=desc;

  // Indicatore sessione
  const sessionLabel = isLondonNY ? `🟢 London/NY (${nowHour}:00 UTC)` : `🔴 Fuori sessione (${nowHour}:00 UTC)`;
  const sessionEl = document.getElementById('mfkk-session');
  if(sessionEl) sessionEl.textContent = sessionLabel;

  const qel=document.getElementById('mfkk-quality');
  if(qel){
    // TP/SL ottimali calibrati su 2 anni backtest (TP $20 / SL $12 per XAU — PF 1.802)
    const tpVal = isXag ? '$0.50' : '$20';
    const slVal = isXag ? '$0.25' : '$12';
    const rrLabel = isXag ? '1:2.0' : '1:1.67';
    if(isHighWrSignal){
      qel.style.cssText='display:block;background:#ffd70020;border:2px solid #ffd70060;color:#ffd700;font-weight:700';
      qel.innerHTML=`💎 HIGH-WR SELL: ADX≥35 · DI spread≥20 · MACD esaurito · London/NY<br><span style="font-size:9px;font-weight:400;opacity:.85">92-95% WR (730gg backtest) · TP ${tpVal} | SL ${slVal} | R:R ${rrLabel}</span>`;
    } else if(isExhaustion && adxScore>=80 && isValidEntry){
      qel.style.cssText='display:block;background:#b36cff15;border:1px solid #b36cff40;color:#b36cff';
      qel.textContent=`🔥 ESAURIMENTO ${dirLabel}: ADX forte + MACD esteso = 82-88% WR. TP ${tpVal} | SL ${slVal} | R:R ${rrLabel}`;
    } else if(isValidEntry && allThree && strong>=2){
      qel.style.cssText='display:block;background:#00e67615;border:1px solid #00e67630;color:var(--green)';
      qel.textContent=`✅ ENTRY VALIDA (calibrata 2yr) — TP ${tpVal} | SL ${slVal} | R:R ${rrLabel}`;
    } else if(isValidEntry){
      qel.style.cssText='display:block;background:#00e67615;border:1px solid #00e67630;color:var(--green)';
      qel.textContent=`🎯 ${dirLabel} VALIDO — TP ${tpVal} | SL ${slVal} | R:R ${rrLabel}`;
    } else if(!isValidEntry && isBuy && score>=80){
      qel.style.cssText='display:block;background:#ffca2810;border:1px solid #ffca2825;color:var(--yellow)';
      qel.textContent=`⏳ BUY score ${score} — soglia minima 90. Attendi ulteriore forza.`;
    } else if(weak>=2){
      qel.style.cssText='display:block;background:#ff475715;border:1px solid #ff475730;color:var(--red)';
      qel.textContent='❌ SEGNALE DEBOLE — Aspetta migliore allineamento';
    } else if(!allThree && (score>=68)){
      qel.style.cssText='display:block;background:#ffca2810;border:1px solid #ffca2825;color:var(--yellow)';
      qel.textContent='⏳ Dati parziali — inserisci tutti e 3 indicatori per score completo';
    } else {
      qel.style.display='none';
    }
  }
  const tel=document.getElementById('mfkk-time');
  if(tel)tel.textContent=new Date().toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});

  // ── 4° CONFERMA: EMA50 Trend Filter + CCI Crossover ──────────────────────────
  const confEl=document.getElementById('mfkk-confirm');
  if(confEl && mfkkEma50!=null){
    const asset = window.activeAsset || 'XAU';
    const livePrice = parseFloat(marketData?.[asset]?.price ?? marketData?.XAU?.price ?? 0);
    const above = livePrice > mfkkEma50;
    const emaAligned = isBuy ? above : !above;
    const emaCol = emaAligned ? 'var(--green)' : 'var(--red)';
    const emaIcon = emaAligned ? '✅' : '⚠️';
    const emaLabel = above
      ? `Prezzo $${livePrice.toFixed(0)} > EMA50 $${mfkkEma50} → uptrend`
      : `Prezzo $${livePrice.toFixed(0)} < EMA50 $${mfkkEma50} → downtrend`;
    const emaHint = emaAligned
      ? `${emaIcon} EMA50 <span style="color:${emaCol}">${emaLabel}</span> — conferma ${dirLabel}`
      : `${emaIcon} EMA50 <span style="color:${emaCol}">${emaLabel}</span> — contro-trend, attenzione`;

    // CCI crossover
    const cciSig = dashContext?.indicators?.cci?.signal ?? '';
    const crossMap = {
      enter_buy:'🔔 CCI ha appena incrociato sotto 25 — segnale BUY attivo',
      enter_sell:'🔔 CCI ha appena incrociato sopra 75 — segnale SELL attivo',
      exit_buy:'↗ CCI uscito da OS (cross sopra 25)',
      exit_sell:'↘ CCI uscito da OB (cross sotto 75)',
      neutral:''
    };
    const crossHtml = crossMap[cciSig] ? `<br><span style="color:#ffca28;font-size:9px">${crossMap[cciSig]}</span>` : '';

    confEl.style.display='block';
    confEl.innerHTML=`<span style="font-size:9px;color:var(--dim)">CONFERMA EMA50</span><br><span style="font-size:10px">${emaHint}</span>${crossHtml}`;
  } else if(confEl){
    confEl.style.display='none';
  }

  // ── ENTRY PLAN: Entry / TP / SL / R:R ────────────────────────────────────────
  const planEl=document.getElementById('mfkk-entry-plan');
  if(planEl && mfkkAtr!=null && score>=55){
    const asset = window.activeAsset || 'XAU';
    const isXag = asset==='XAG';
    const liveP = parseFloat(marketData?.[asset]?.price ?? marketData?.XAU?.price ?? 0);
    const entry = liveP || (isXag?30:3000);
    const atr = mfkkAtr;
    // Base SL/TP calibrati su backtest 2 anni (TP$20/SL$12 = R:R 1.67 = PF 1.802)
    const BASE_TP = isXag ? 0.50 : 20;
    const BASE_SL = isXag ? 0.25 : 12;

    // SL: parte da BASE_SL e si adatta agli swing levels
    let slDist = BASE_SL;
    if(isBuy && mfkkSwingLow && entry - mfkkSwingLow > 0){
      const swingDist = entry - mfkkSwingLow + atr*0.2;
      slDist = Math.min(Math.max(slDist, swingDist), BASE_SL * 2); // cap a 2x base SL
    } else if(!isBuy && mfkkSwingHigh && mfkkSwingHigh - entry > 0){
      const swingDist = mfkkSwingHigh - entry + atr*0.2;
      slDist = Math.min(Math.max(slDist, swingDist), BASE_SL * 2);
    }

    // TP: R:R minimo 1.67:1 (calibrato), migliora se c'è swing favorevole
    let tpDist = Math.max(slDist * 1.67, BASE_TP);
    if(isBuy && mfkkSwingHigh){
      const swTP = mfkkSwingHigh - entry;
      if(swTP > slDist * 1.2) tpDist = Math.max(tpDist, swTP * 0.95);
    } else if(!isBuy && mfkkSwingLow){
      const swTP = entry - mfkkSwingLow;
      if(swTP > slDist * 1.2) tpDist = Math.max(tpDist, swTP * 0.95);
    }
    tpDist = Math.min(tpDist, atr * 4); // cap TP a 4x ATR

    const rr = (tpDist / slDist).toFixed(1);
    const dec = isXag ? 3 : 2;
    const tpPrice = isBuy ? entry + tpDist : entry - tpDist;
    const slPrice = isBuy ? entry - slDist : entry + slDist;
    const tpLabel = isBuy ? '+' : '-';
    const slLabel = isBuy ? '-' : '+';
    const scoreCol = score>=75?'var(--green)':score>=55?'var(--yellow)':'var(--dim)';

    // EMA alignment bonus/warning
    const liveForPlan = liveP > 0;
    const emaOk = mfkkEma50!=null && ((isBuy && liveP>mfkkEma50)||(!isBuy && liveP<mfkkEma50));
    const emaWarn = mfkkEma50!=null && !emaOk;

    planEl.style.display='block';
    planEl.innerHTML=`
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
  <span style="font-size:9px;font-weight:700;letter-spacing:.08em;color:var(--dim)">ENTRY PLAN · ATR=${atr.toFixed(2)}</span>
  <span style="font-size:9px;font-weight:700;color:${scoreCol}">SCORE ${score} · R:R 1:${rr}</span>
</div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;text-align:center">
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:5px;padding:5px 3px">
    <div style="font-size:8px;color:var(--dim);margin-bottom:2px">ENTRY (MARKET)</div>
    <div style="font-size:11px;font-weight:700;color:var(--fg)">${liveForPlan?'$'+entry.toFixed(dec):'—'}</div>
    <div style="font-size:8px;color:var(--dim)">${dirLabel}</div>
  </div>
  <div style="background:#00e67608;border:1px solid #00e67630;border-radius:5px;padding:5px 3px">
    <div style="font-size:8px;color:var(--dim);margin-bottom:2px">TAKE PROFIT</div>
    <div style="font-size:11px;font-weight:700;color:var(--green)">$${tpPrice.toFixed(dec)}</div>
    <div style="font-size:8px;color:var(--green)">${tpLabel}$${tpDist.toFixed(dec)}</div>
  </div>
  <div style="background:#ff475708;border:1px solid #ff475730;border-radius:5px;padding:5px 3px">
    <div style="font-size:8px;color:var(--dim);margin-bottom:2px">STOP LOSS</div>
    <div style="font-size:11px;font-weight:700;color:var(--red)">$${slPrice.toFixed(dec)}</div>
    <div style="font-size:8px;color:var(--red)">${slLabel}$${slDist.toFixed(dec)}</div>
  </div>
</div>
${emaWarn?`<div style="margin-top:5px;font-size:9px;color:#ffca28">⚠️ Contro-trend EMA50: aumenta SL del 20% o riduci size</div>`:''}
${emaOk?`<div style="margin-top:5px;font-size:9px;color:var(--green)">✅ EMA50 allineata — trend a favore dell'entry</div>`:''}
<div style="margin-top:4px;font-size:8px;color:var(--dim)">Swing: H=${mfkkSwingHigh??'—'} L=${mfkkSwingLow??'—'} · Adatta alla tua size</div>
    `.trim();
  } else if(planEl && score<55){
    planEl.style.display='none';
  }

  dashContext.mfkk={score,dir:dirLabel,bias,cciScore,macdScore,adxScore,allThree,strongSignals:strong};
}

// Auto-calculate both directions and pick the best one
function autoSelectBestDir(){
  // Check if any values are actually populated
  const cci = parseFloat(document.getElementById('mfkk-cci')?.value);
  const macd = parseFloat(document.getElementById('mfkk-macd-fast')?.value);
  const adx = parseFloat(document.getElementById('mfkk-adx')?.value);
  if(isNaN(cci) && isNaN(macd) && isNaN(adx)) return; // no data yet

  const origDir = mfkkDir;

  // Calculate BUY score without side effects
  mfkkDir='buy';
  document.getElementById('mfkk-buy').className='mfkk-dir on-buy';
  document.getElementById('mfkk-sell').className='mfkk-dir';
  calcMfkk();
  const buyScore = dashContext.mfkk?.score || 0;

  // Calculate SELL score
  mfkkDir='sell';
  document.getElementById('mfkk-buy').className='mfkk-dir';
  document.getElementById('mfkk-sell').className='mfkk-dir on-sell';
  calcMfkk();
  const sellScore = dashContext.mfkk?.score || 0;

  // Keep best
  const best = sellScore > buyScore ? 'sell' : 'buy';
  mfkkDir = best;
  document.getElementById('mfkk-buy').className='mfkk-dir'+(best==='buy'?' on-buy':'');
  document.getElementById('mfkk-sell').className='mfkk-dir'+(best==='sell'?' on-sell':'');
  calcMfkk();
  console.log('MFKK auto-dir: BUY='+buyScore+' SELL='+sellScore+' → '+best.toUpperCase());
}
