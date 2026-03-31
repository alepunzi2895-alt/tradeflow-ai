export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  const tf = (req.query?.tf || '1h').toLowerCase();
  const resolution = tf === '1d' ? 'D' : tf === '4h' ? '240' : '60';
  const interval   = tf === '1d' ? '1d' : '1h';
  const yahooRange = tf === '1d' ? '60d' : '14d';
  const COUNT = 300;

  async function fetchT(url, opts = {}, ms = 8000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  // ── Math helpers (exact TV Pine Script behaviour) ──────────────────────────
  // ta.ema(): first value as seed (not SMA of first N)
  const ema = (src, p) => {
    const k = 2/(p+1); let v = src[0]; const o = [v];
    for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
    return o;
  };
  // sma(): standard simple moving average, returns null until enough data
  const sma = (src, p) => {
    const o=new Array(src.length).fill(null);
    for(let i=p-1;i<src.length;i++){let s=0;for(let j=0;j<p;j++)s+=(src[i-j]||0);o[i]=s/p;}
    return o;
  };
  const hi = (a,p,i) => { let m=-Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.max(m,a[j]); return m; };
  const lo = (a,p,i) => { let m=Infinity;  for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.min(m,a[j]); return m; };

  // ── Compute all indicators from candle array ───────────────────────────────
  function computeIndicators(candles) {
    if(candles.length < 120) return null;
    const H=candles.map(x=>x.h), L=candles.map(x=>x.l), C=candles.map(x=>x.c), n=C.length;

    // ── CCI_S ──────────────────────────────────────────────────────────
    // Pine Script v4: cci(close,50) → stoch(cci,cci,cci,50) → SMA(K,8) → SMA(D,8)
    // Settings confirmed: CCI=50, Stoch=50, K=8, D=8, OB=75, OS=25, D line displayed
    const CP=50, SP=50, SK=8, SD=8;
    const cci=new Array(n).fill(null);
    for(let i=CP-1;i<n;i++){
      const sl=C.slice(i-CP+1,i+1);
      const mn=sl.reduce((a,b)=>a+b,0)/CP;
      const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CP;
      cci[i]=md===0?0:(C[i]-mn)/(0.015*md);
    }
    // stoch(cci,cci,cci,50): 100*(cci-lowest(cci,50))/(highest(cci,50)-lowest(cci,50))
    const stk=new Array(n).fill(null);
    for(let i=CP+SP-2;i<n;i++){
      if(cci[i]==null)continue;
      const lv=lo(cci,SP,i), hv=hi(cci,SP,i);
      stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;
    }
    // SMA(stoch,8) — propagate null exactly like Pine Script (no 50-fill)
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
    const cv=stk_d[n-1]??50, cp=stk_d[n-2]??50;
    let cciSig='neutral';
    if(cp>=25&&cv<25)cciSig='enter_buy';
    else if(cp<=75&&cv>75)cciSig='enter_sell';
    else if(cp>75&&cv<=75)cciSig='exit_sell';
    else if(cp<25&&cv>=25)cciSig='exit_buy';

    // ── MACD(12,26,9) ─────────────────────────────────────────────────
    // Pine Script v6 default: fast=12, slow=26, signal=9, type=EMA for both
    // Settings confirmed: Periodo veloce=12, Periodo lento=26, Signal=9, EMA
    const eFast=ema(C,12), eSlow=ema(C,26);
    const ml=eFast.map((v,i)=>v-eSlow[i]);
    const sg=ema(ml,9);
    const hist=ml.map((v,i)=>v-sg[i]);
    const mv=ml[n-1], sv=sg[n-1], hv=hist[n-1], hp=hist[n-2]||0;
    let cross=mv>sv?'above':'below';
    if((ml[n-2]||0)<=(sg[n-2]||0)&&mv>sv) cross='cross_buy';
    else if((ml[n-2]||0)>=(sg[n-2]||0)&&mv<sv) cross='cross_sell';

    // ── ADX and DI for v4 ──────────────────────────────────────────────
    // Pine Script: Wilder smoothing for TR/DM+/DM-, then ADX = SMA(DX, len)
    // Settings confirmed: Per=10, Th=10
    const AP=10;
    const TR=new Array(n).fill(0), DMP=new Array(n).fill(0), DMM=new Array(n).fill(0);
    for(let i=1;i<n;i++){
      TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
      const upMove=H[i]-H[i-1], downMove=L[i-1]-L[i];
      DMP[i]=(upMove>downMove&&upMove>0)?upMove:0;
      DMM[i]=(downMove>upMove&&downMove>0)?downMove:0;
    }
    // SmoothedTR = nz(SmoothedTR[1]) - nz(SmoothedTR[1])/len + TrueRange
    // nz() → starts at 0, so first bar: 0 - 0/len + TR[0] = TR[0] (handled by fill(0))
    const sTR=new Array(n).fill(0), sDMP=new Array(n).fill(0), sDMM=new Array(n).fill(0);
    for(let i=1;i<n;i++){
      sTR[i] =sTR[i-1] -sTR[i-1]/AP  +TR[i];
      sDMP[i]=sDMP[i-1]-sDMP[i-1]/AP +DMP[i];
      sDMM[i]=sDMM[i-1]-sDMM[i-1]/AP +DMM[i];
    }
    const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
    const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
    const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
    // ADX = sma(DX, len) — Pine Script uses SMA here, NOT Wilder RMA!
    const ADX=sma(DX, AP);

    return {
      cv, cp, cciSig,
      mv, sv, hv, hp, cross,
      adx: ADX[n-1]??0,
      diPlus: DIP[n-1], diMinus: DIM[n-1],
      lastClose: C[n-1], count: n
    };
  }

  // ── SOURCE 1: TradingView history API (exact same data as TV charts) ────────
  async function fetchTVCandles() {
    const now = Math.floor(Date.now()/1000);
    const from = now - COUNT * (resolution==='D'?86400:resolution==='240'?14400:3600) - 86400;
    const xauTickers = ['OANDA:XAUUSD','FOREXCOM:XAUUSD','PEPPERSTONE:XAUUSD','CAPITALCOM:GOLD'];
    for(const sym of xauTickers) {
      try {
        const url = `https://data.tradingview.com/history?symbol=${encodeURIComponent(sym)}&resolution=${resolution}&from=${from}&to=${now}&countback=${COUNT}`;
        const r = await fetchT(url, {
          headers: {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Origin': 'https://www.tradingview.com',
            'Referer': 'https://www.tradingview.com/',
            'Accept': 'application/json'
          }
        }, 7000);
        if(!r.ok) continue;
        const d = await r.json();
        if(d.s !== 'ok' || !d.t?.length) continue;
        const candles = [];
        for(let i=0;i<d.t.length;i++){
          if(d.c[i]!=null && d.h[i]!=null && d.l[i]!=null)
            candles.push({t:d.t[i],h:d.h[i],l:d.l[i],c:d.c[i]});
        }
        if(candles.length < 120) continue;
        console.log(`TV history OK: ${sym} ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
        return { candles, source: 'tradingview_'+sym };
      } catch(e){ console.log(`TV history ${sym}:`, e.message); }
    }
    return null;
  }

  // ── SOURCE 2: Yahoo Finance fallback ────────────────────────────────────────
  async function fetchYahooCandles() {
    const SYMS = ['XAUUSD=X','GC=F'];
    for(const sym of SYMS) {
      try {
        const r = await fetchT(
          `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=${interval}&range=${yahooRange}`,
          { headers: { 'User-Agent': 'Mozilla/5.0' } }
        );
        if(!r.ok) continue;
        const d = await r.json();
        const rs = d?.chart?.result?.[0];
        if(!rs?.timestamp) continue;
        const q = rs.indicators?.quote?.[0]||{};
        const candles = [];
        for(let i=0;i<rs.timestamp.length;i++){
          if(q.close[i]!=null&&q.high[i]!=null&&q.low[i]!=null)
            candles.push({t:rs.timestamp[i],h:q.high[i],l:q.low[i],c:q.close[i]});
        }
        if(candles.length<30) continue;
        console.log(`Yahoo OK: ${sym} ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
        return { candles, source: 'yahoo_'+sym };
      } catch(e){ console.log(`Yahoo ${sym}:`, e.message); }
    }
    return null;
  }

  try {
    const candleResult = await fetchTVCandles().then(r => r || fetchYahooCandles());
    if(!candleResult) return res.status(503).json({ ok:false, error:'No candle data available' });

    let { candles, source: candleSource } = candleResult;

    if(tf==='4h'){
      const map=new Map();
      for(const c of candles){
        const d=new Date(c.t*1000);
        const b=Math.floor(d.getUTCHours()/4)*4;
        const k=`${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${b}`;
        if(!map.has(k)) map.set(k,{t:c.t,h:c.h,l:c.l,c:c.c});
        else{const e=map.get(k);e.h=Math.max(e.h,c.h);e.l=Math.min(e.l,c.l);e.c=c.c;e.t=c.t;}
      }
      candles=[...map.values()].sort((a,b)=>a.t-b.t);
    }

    if(candles.length<30) return res.status(503).json({ok:false,error:'Insufficient candles: '+candles.length});

    const vals = computeIndicators(candles);
    if(!vals) return res.status(503).json({ok:false,error:'Need 120+ candles, got '+candles.length});

    const C=candles.map(x=>x.c), n=C.length;
    const { cv, cp, cciSig, mv, sv, hv, hp, cross } = vals;

    const candle_data = candles.slice(-300).map(x=>({t:x.t,h:+x.h.toFixed(2),l:+x.l.toFixed(2),c:+x.c.toFixed(2)}));

    console.log(`Indicators OK [${candleSource}] | CCI_S=${cv.toFixed(2)} MACD=${mv.toFixed(2)} ADX=${(vals.adx??0).toFixed(2)}`);

    return res.status(200).json({
      ok:true, timeframe:tf,
      timestamp:new Date().toISOString(),
      last_candle:new Date(candles.at(-1).t*1000).toISOString(),
      last_close:+C[n-1].toFixed(2),
      candles:n, candle_data, source:candleSource,
      cci:{value:+cv.toFixed(2),signal:cciSig,zone:cv>75?'overbought':cv<25?'oversold':'neutral',ob:75,os:25},
      macd:{macd:+mv.toFixed(4),signal:+sv.toFixed(4),histogram:+hv.toFixed(4),hist_prev:+hp.toFixed(4),hist_rising:hv>hp,cross,diff:+(mv-sv).toFixed(4)},
      adx:{adx:+(vals.adx??0).toFixed(2),di_plus:+vals.diPlus.toFixed(2),di_minus:+vals.diMinus.toFixed(2),threshold:10,trending:(vals.adx??0)>10,strong:(vals.adx??0)>25}
    });
  } catch(e) {
    console.error('Indicators:', e.message);
    return res.status(500).json({ok:false,error:e.message});
  }
}
