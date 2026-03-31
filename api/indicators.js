export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Cache-Control", "no-cache, max-age=0");

  const tf = (req.query?.tf || '1h').toLowerCase();
  const resolution = tf === '1d' ? 'D' : tf === '4h' ? '240' : '60'; // TV resolution format
  const interval  = tf === '1d' ? '1d' : '1h';
  const yahooRange = tf === '1d' ? '60d' : '14d';

  // Candles needed: CCI(50)+Stoch(50)+SMA(8)+SMA(8) = 116 warmup + buffer
  const COUNT = 300;

  // ─── Helper: fetch with timeout ──────────────────────────
  async function fetchT(url, opts = {}, ms = 8000) {
    const ctrl = new AbortController();
    const tid = setTimeout(() => ctrl.abort(), ms);
    try { const r = await fetch(url, { ...opts, signal: ctrl.signal }); clearTimeout(tid); return r; }
    catch(e) { clearTimeout(tid); throw e; }
  }

  // ─── Math helpers ────────────────────────────────────────
  const ema = (src, p) => {
    const k = 2/(p+1); let v = src[0]; const o = [v];
    for(let i=1;i<src.length;i++){v=src[i]*k+v*(1-k);o.push(v);}
    return o;
  };
  const sma = (src, p) => {
    const o=new Array(src.length).fill(null);
    for(let i=p-1;i<src.length;i++){let s=0;for(let j=0;j<p;j++)s+=(src[i-j]||0);o[i]=s/p;}
    return o;
  };
  const hi = (a,p,i) => { let m=-Infinity; for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.max(m,a[j]); return m; };
  const lo = (a,p,i) => { let m=Infinity;  for(let j=Math.max(0,i-p+1);j<=i;j++) if(a[j]!=null) m=Math.min(m,a[j]); return m; };

  // ─── Compute all indicators from candle array ────────────
  function computeIndicators(candles) {
    if(candles.length < 120) return null;
    const H=candles.map(x=>x.h), L=candles.map(x=>x.l), C=candles.map(x=>x.c), n=C.length;

    // CCI_S: CCI(50) source=close → Stoch(50) K=8 D=8, OB=75 OS=25
    const CP=50, SP=50, SK=8, SD=8;
    const cci=new Array(n).fill(null);
    for(let i=CP-1;i<n;i++){
      const sl=C.slice(i-CP+1,i+1);
      const mn=sl.reduce((a,b)=>a+b,0)/CP;
      const md=sl.reduce((a,b)=>a+Math.abs(b-mn),0)/CP;
      cci[i]=md===0?0:(C[i]-mn)/(0.015*md);
    }
    const stk=new Array(n).fill(null);
    for(let i=CP+SP-2;i<n;i++){
      if(cci[i]==null) continue;
      const lv=lo(cci,SP,i), hv=hi(cci,SP,i);
      stk[i]=(hv-lv)===0?50:((cci[i]-lv)/(hv-lv))*100;
    }
    const stk_k=sma(stk.map(v=>v??50),SK);
    const stk_d=sma(stk_k.map(v=>v??50),SD);
    const cv=stk_d[n-1]??50, cp=stk_d[n-2]??50;
    let cciSig='neutral';
    if(cp>=25&&cv<25)cciSig='enter_buy';
    else if(cp<=75&&cv>75)cciSig='enter_sell';
    else if(cp>75&&cv<=75)cciSig='exit_sell';
    else if(cp<25&&cv>=25)cciSig='exit_buy';

    // MACD: fast=27, slow=20, signal=5
    const eFast=ema(C,Math.min(27,n-1)), eSlow=ema(C,Math.min(20,n-1));
    const ml=eFast.map((v,i)=>v-eSlow[i]);
    const sg=ema(ml,Math.min(5,n-1));
    const hist=ml.map((v,i)=>v-sg[i]);
    const mv=ml[n-1], sv=sg[n-1], hv=hist[n-1], hp=hist[n-2]||0;
    let cross=mv>sv?'above':'below';
    if((ml[n-2]||0)<=(sg[n-2]||0)&&mv>sv) cross='cross_buy';
    else if((ml[n-2]||0)>=(sg[n-2]||0)&&mv<sv) cross='cross_sell';

    // ADX: Wilder period=9
    const AP=9;
    const TR=new Array(n).fill(0), DMP=new Array(n).fill(0), DMM=new Array(n).fill(0);
    for(let i=1;i<n;i++){
      TR[i]=Math.max(H[i]-L[i],Math.abs(H[i]-C[i-1]),Math.abs(L[i]-C[i-1]));
      DMP[i]=H[i]-H[i-1]>L[i-1]-L[i]?Math.max(H[i]-H[i-1],0):0;
      DMM[i]=L[i-1]-L[i]>H[i]-H[i-1]?Math.max(L[i-1]-L[i],0):0;
    }
    const sTR=new Array(n).fill(0), sDMP=new Array(n).fill(0), sDMM=new Array(n).fill(0);
    sTR[0]=TR[0]; sDMP[0]=DMP[0]; sDMM[0]=DMM[0];
    for(let i=1;i<n;i++){
      sTR[i]=sTR[i-1]-sTR[i-1]/AP+TR[i];
      sDMP[i]=sDMP[i-1]-sDMP[i-1]/AP+DMP[i];
      sDMM[i]=sDMM[i-1]-sDMM[i-1]/AP+DMM[i];
    }
    const DIP=sTR.map((v,i)=>v>0?sDMP[i]/v*100:0);
    const DIM=sTR.map((v,i)=>v>0?sDMM[i]/v*100:0);
    const DX=DIP.map((v,i)=>{const s=v+DIM[i];return s>0?Math.abs(v-DIM[i])/s*100:0;});
    const adxArr=[DX[0]];
    for(let i=1;i<DX.length;i++) adxArr.push(adxArr[i-1]*(AP-1)/AP+DX[i]/AP);

    return {
      cv, cp, cciSig,
      mv, sv, hv, hp, cross,
      adx: adxArr[n-1],
      diPlus: DIP[n-1], diMinus: DIM[n-1],
      lastClose: C[n-1], count: n
    };
  }

  // ─── SOURCE 1: TradingView history API (exact same data as TV charts) ──
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
        for(let i=0;i<d.t.length;i++) {
          if(d.c[i]!=null && d.h[i]!=null && d.l[i]!=null)
            candles.push({t:d.t[i], h:d.h[i], l:d.l[i], c:d.c[i]});
        }
        if(candles.length < 120) continue;
        console.log(`TV history OK: ${sym} ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
        return { candles, source: 'tradingview_' + sym };
      } catch(e) { console.log(`TV history ${sym}:`, e.message); }
    }
    return null;
  }

  // ─── SOURCE 2: Yahoo Finance (fallback) ────────────────
  async function fetchYahooCandles() {
    const SYMBOLS = ['XAUUSD=X', 'GC=F'];
    for(const sym of SYMBOLS) {
      try {
        const r = await fetchT(
          `https://query1.finance.yahoo.com/v8/finance/chart/${sym}?interval=${interval}&range=${yahooRange}`,
          { headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' } }
        );
        if(!r.ok) continue;
        const d = await r.json();
        const rs = d?.chart?.result?.[0];
        if(!rs?.timestamp) continue;
        const q = rs.indicators?.quote?.[0] || {};
        const candles = [];
        for(let i=0;i<rs.timestamp.length;i++) {
          if(q.close[i]!=null && q.high[i]!=null && q.low[i]!=null)
            candles.push({t:rs.timestamp[i], h:q.high[i], l:q.low[i], c:q.close[i]});
        }
        if(candles.length < 30) continue;
        console.log(`Yahoo OK: ${sym} ${candles.length} candles, last=$${candles.at(-1).c.toFixed(2)}`);
        return { candles, source: 'yahoo_' + sym };
      } catch(e) { console.log(`Yahoo ${sym}:`, e.message); }
    }
    return null;
  }

  // ─── SOURCE 3: TV Scanner for ADX/DI direct values (exact match) ──
  async function fetchTVScannerIndicators() {
    const tickers = ['OANDA:XAUUSD','FOREXCOM:XAUUSD','PEPPERSTONE:XAUUSD'];
    // columns with |60 suffix = H1 timeframe
    const cols = [
      'close|60', 'high|60', 'low|60',
      'ADX[9]|60', 'plus_di[9]|60', 'minus_di[9]|60',
      'CCI[50]|60',
      'MACD.macd|60', 'MACD.signal|60', 'MACD.hist|60'
    ];
    const body = {
      symbols: { tickers, query: { types: [] } },
      columns: cols
    };
    try {
      const r = await fetchT('https://scanner.tradingview.com/global/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'User-Agent': 'Mozilla/5.0',
          'Origin': 'https://www.tradingview.com',
          'Referer': 'https://www.tradingview.com/'
        },
        body: JSON.stringify(body)
      }, 7000);
      if(!r.ok) return null;
      const d = await r.json();
      const item = d.data?.find(x => x.d && x.d[0] != null);
      if(!item) return null;
      const [close, high, low, adx, diPlus, diMinus, cci50, macdLine, macdSig, macdHist] = item.d;
      if(adx==null || isNaN(+adx)) return null;
      console.log(`TV Scanner indicators OK: ADX=${(+adx).toFixed(2)} DI+=${(+diPlus).toFixed(2)} DI-=${(+diMinus).toFixed(2)}`);
      return { close, adx: +adx, diPlus: +diPlus, diMinus: +diMinus, cci50: +cci50, macdLine: +macdLine, macdSig: +macdSig, macdHist: +macdHist, source: item.s };
    } catch(e) { console.log('TV Scanner indicators:', e.message); return null; }
  }

  try {
    // Fetch candles and scanner in parallel
    const [candleResult, scannerResult] = await Promise.all([
      fetchTVCandles().then(r => r || fetchYahooCandles()),
      fetchTVScannerIndicators()
    ]);

    if(!candleResult) return res.status(503).json({ ok:false, error:'No candle data available' });

    let { candles, source: candleSource } = candleResult;

    // Resample to H4 if needed
    if(tf === '4h') {
      const map = new Map();
      for(const c of candles) {
        const d = new Date(c.t*1000);
        const b = Math.floor(d.getUTCHours()/4)*4;
        const k = `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}-${b}`;
        if(!map.has(k)) map.set(k,{t:c.t,h:c.h,l:c.l,c:c.c});
        else { const e=map.get(k); e.h=Math.max(e.h,c.h); e.l=Math.min(e.l,c.l); e.c=c.c; e.t=c.t; }
      }
      candles = [...map.values()].sort((a,b)=>a.t-b.t);
    }

    if(candles.length < 30) return res.status(503).json({ ok:false, error:'Insufficient candles: '+candles.length });

    // Compute indicators from candles
    const vals = computeIndicators(candles);
    if(!vals) return res.status(503).json({ ok:false, error:'Cannot compute indicators: need 120+ candles, got '+candles.length });

    const C = candles.map(x=>x.c);
    const n = C.length;

    // Merge TV Scanner exact values (ADX, DI+, DI- are exact matches from TV)
    // For CCI_S and MACD(27,20,5) we use our computed values from TV candles
    const adxVal   = scannerResult?.adx    ?? vals.adx;
    const diPlusV  = scannerResult?.diPlus  ?? vals.diPlus;
    const diMinusV = scannerResult?.diMinus ?? vals.diMinus;
    // Note: scanner CCI is raw CCI(50), not CCI_S (stochastic of CCI)
    // Scanner MACD is default 12,26,9, not our 27,20,5 — so we keep computed
    const adxSource = scannerResult ? 'tv_scanner' : candleSource;

    // candle_data for client-side live recalc
    const candle_data = candles.slice(-300).map(x=>({t:x.t,h:+x.h.toFixed(2),l:+x.l.toFixed(2),c:+x.c.toFixed(2)}));

    const { cv, cp, cciSig, mv, sv, hv, hp, cross } = vals;

    console.log(`Indicators OK | source: ${candleSource} | ADX source: ${adxSource} | CCI_S=${cv.toFixed(2)} MACD=${mv.toFixed(2)} ADX=${adxVal.toFixed(2)}`);

    return res.status(200).json({
      ok: true, timeframe: tf,
      timestamp: new Date().toISOString(),
      last_candle: new Date(candles.at(-1).t*1000).toISOString(),
      last_close: +C[n-1].toFixed(2),
      candles: n, candle_data,
      source: candleSource,
      adx_source: adxSource,
      cci: {
        value: +cv.toFixed(2), signal: cciSig,
        zone: cv>75?'overbought':cv<25?'oversold':'neutral',
        ob: 75, os: 25
      },
      macd: {
        macd: +mv.toFixed(4), signal: +sv.toFixed(4),
        histogram: +hv.toFixed(4), hist_prev: +hp.toFixed(4),
        hist_rising: hv>hp, cross,
        diff: +(mv-sv).toFixed(4)
      },
      adx: {
        adx: +adxVal.toFixed(2),
        di_plus: +diPlusV.toFixed(2),
        di_minus: +diMinusV.toFixed(2),
        threshold: 10, trending: adxVal>10, strong: adxVal>25
      }
    });

  } catch(e) {
    console.error('Indicators:', e.message);
    return res.status(500).json({ ok:false, error:e.message });
  }
}
