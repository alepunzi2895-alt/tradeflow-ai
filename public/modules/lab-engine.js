// Research-only engine: closed-bar signals, next-open fills, one position at a time.
const LabEngine = (() => {
  const catalog={macd:'MACD 12/26',macdSignal:'Segnale MACD 9',macdHist:'Istogramma MACD',adx:'ADX Wilder',diPlus:'DI+',diMinus:'DI−',close:'Prezzo di chiusura',sma:'SMA',ema:'EMA',rsi:'RSI Wilder',atr:'ATR Wilder',roc:'ROC %',momentum:'Momentum',std:'Deviazione standard',bbUpper:'Bollinger superiore',bbLower:'Bollinger inferiore',stoch:'Stocastico %K',williams:'Williams %R',cci:'CCI',donHigh:'Donchian massimo',donLow:'Donchian minimo',volume:'Volume',obv:'OBV'};
  function normalize(rows){
    if(!Array.isArray(rows)||rows.length<60||rows.length>50000)throw Error('Servono da 60 a 50.000 candele OHLC.');
    const data=rows.map(r=>{
      let t=r.t??r.time??r.date; t=typeof t==='number'?(t>1e12?t/1000:t):Date.parse(t)/1000;
      const c={t,o:Number(r.o??r.open),h:Number(r.h??r.high),l:Number(r.l??r.low),c:Number(r.c??r.close),v:r.v??r.volume??null};
      if(![c.t,c.o,c.h,c.l,c.c].every(Number.isFinite)||c.l<=0||c.h<Math.max(c.o,c.c,c.l)||c.l>Math.min(c.o,c.c))throw Error('Candela non valida: controlla timestamp e OHLC.');
      if(c.v!==null){c.v=Number(c.v);if(!Number.isFinite(c.v)||c.v<0)throw Error('Volume non valido.');}
      return c;
    }).sort((a,b)=>a.t-b.t);
    if(data.some((c,i)=>i&&c.t===data[i-1].t))throw Error('Timestamp duplicati nel dataset.');
    return data;
  }
  function indicator(data,key,p){
    if(!catalog[key])throw Error('Indicatore sconosciuto');
    if(!Number.isInteger(p)||p<2||p>250)throw Error('Periodo indicatore: intero da 2 a 250.');
    if(key.startsWith('macd')){
      const ema=(values,n)=>{let v=values[0];return values.map((x,i)=>v=i?v+2/(n+1)*(x-v):x);};
      const prices=data.map(x=>x.c),fast=ema(prices,12),slow=ema(prices,26),line=fast.map((x,i)=>x-slow[i]),signal=ema(line,9);
      return line.map((x,i)=>i<33?null:key==='macd'?x:key==='macdSignal'?signal[i]:x-signal[i]);
    }
    if(['adx','diPlus','diMinus'].includes(key)){
      const values=Array(data.length).fill(null);let trSum=0,plus=0,minus=0,dxSum=0,adx=null;
      for(let i=1;i<data.length;i++){
        const c=data[i],prev=data[i-1],up=c.h-prev.h,down=prev.l-c.l;
        const tr=Math.max(c.h-c.l,Math.abs(c.h-prev.c),Math.abs(c.l-prev.c)),dp=up>down&&up>0?up:0,dm=down>up&&down>0?down:0;
        if(i<=p){trSum+=tr;plus+=dp;minus+=dm;}else{trSum=trSum-trSum/p+tr;plus=plus-plus/p+dp;minus=minus-minus/p+dm;}
        if(i<p)continue;
        const dip=trSum?100*plus/trSum:0,dim=trSum?100*minus/trSum:0,dx=dip+dim?100*Math.abs(dip-dim)/(dip+dim):0;
        if(i<2*p){dxSum+=dx;if(i===2*p-1)adx=dxSum/p;}else adx=(adx*(p-1)+dx)/p;
        values[i]=key==='adx'?adx:key==='diPlus'?dip:dim;
      }
      return values;
    }
    const out=Array(data.length).fill(null);let ema=0,avgGain=0,avgLoss=0,atr=0,obv=0,hasVolume=true;
    for(let i=0;i<data.length;i++){
      const c=data[i],prev=data[i-1],delta=prev?c.c-prev.c:0;
      ema=i?ema+2/(p+1)*(c.c-ema):c.c;
      const tr=prev?Math.max(c.h-c.l,Math.abs(c.h-prev.c),Math.abs(c.l-prev.c)):c.h-c.l;
      if(i<p){atr+=tr/p;if(i){avgGain+=Math.max(delta,0)/p;avgLoss+=Math.max(-delta,0)/p;}}
      else{atr=(atr*(p-1)+tr)/p;avgGain=i===p?avgGain+Math.max(delta,0)/p:(avgGain*(p-1)+Math.max(delta,0))/p;avgLoss=i===p?avgLoss+Math.max(-delta,0)/p:(avgLoss*(p-1)+Math.max(-delta,0))/p;}
      hasVolume=hasVolume&&c.v!==null;
      if(c.v!==null)obv+=Math.sign(delta)*c.v;
      if(key==='close'){out[i]=c.c;continue;}
      if(key==='volume'){out[i]=c.v;continue;}
      if(key==='obv'){out[i]=hasVolume?obv:null;continue;}
      if(i<p-1)continue;
      const w=data.slice(i-p+1,i+1),mean=w.reduce((a,x)=>a+x.c,0)/p;
      const sd=Math.sqrt(w.reduce((a,x)=>a+(x.c-mean)**2,0)/p),hi=Math.max(...w.map(x=>x.h)),lo=Math.min(...w.map(x=>x.l));
      const tp=w.map(x=>(x.h+x.l+x.c)/3),tm=tp.reduce((a,x)=>a+x,0)/p,md=tp.reduce((a,x)=>a+Math.abs(x-tm),0)/p;
      const values={sma:mean,ema,rsi:i<p?null:avgGain+avgLoss===0?50:avgLoss===0?100:100-100/(1+avgGain/avgLoss),atr,roc:i<p?null:(c.c/data[i-p].c-1)*100,momentum:i<p?null:c.c-data[i-p].c,std:sd,bbUpper:mean+2*sd,bbLower:mean-2*sd,stoch:hi===lo?50:100*(c.c-lo)/(hi-lo),williams:hi===lo?-50:-100*(hi-c.c)/(hi-lo),cci:md?((c.h+c.l+c.c)/3-tm)/(.015*md):0,donHigh:hi,donLow:lo};
      out[i]=values[key];
    }
    return out;
  }
  function run(data,config){
    const {rules,direction,stop,take,cost,quantity}=config;
    if(!Array.isArray(rules)||!rules.length||rules.length>8)throw Error('Inserisci da 1 a 8 regole.');
    if(!['long','short'].includes(direction)||![stop,take,cost,quantity].every(Number.isFinite)||stop<=0||stop>=100||take<=0||take>=100||cost<0||quantity<=0)throw Error('Parametri di rischio o costi non validi.');
    const series=new Map();
    const get=(key,p)=>{const k=key+':'+p;if(!series.has(k))series.set(k,indicator(data,key,p));return series.get(k);};
    const prepared=rules.map(r=>{
      if(!['gt','lt','crossUp','crossDown'].includes(r.op))throw Error('Operatore non valido');
      if(r.right==='number'&&!Number.isFinite(r.value))throw Error('Soglia non valida');
      return {...r,a:get(r.left,r.period),b:r.right==='number'?data.map(()=>r.value):get(r.right,r.rightPeriod)};
    });
    const matches=i=>prepared.every(r=>{
      const a=r.a[i],b=r.b[i];if(a===null||b===null)return false;
      if(r.op==='gt')return a>b;if(r.op==='lt')return a<b;
      if(i<1||r.a[i-1]===null||r.b[i-1]===null)return false;
      return r.op==='crossUp'?a>b&&r.a[i-1]<=r.b[i-1]:a<b&&r.a[i-1]>=r.b[i-1];
    });
    const sign=direction==='long'?1:-1,trades=[];let pos=null;
    const close=(price,i,reason)=>{const pnl=(price-pos.price)*sign*quantity-(price+pos.price)*quantity*cost/10000;trades.push({entryTime:data[pos.i].t,exitTime:data[i].t,entry:pos.price,exit:price,pnl,reason,index:pos.i});pos=null;};
    for(let i=1;i<data.length;i++){
      const c=data[i];
      if(!pos&&matches(i-1))pos={i,price:c.o,sl:c.o*(1-sign*stop/100),tp:c.o*(1+sign*take/100)};
      if(!pos)continue;
      const hitSL=sign===1?c.l<=pos.sl:c.h>=pos.sl,hitTP=sign===1?c.h>=pos.tp:c.l<=pos.tp;
      if(hitSL)close(sign===1?Math.min(c.o,pos.sl):Math.max(c.o,pos.sl),i,'Stop');
      else if(hitTP)close(pos.tp,i,'Target');
    }
    if(pos)close(data.at(-1).c,data.length-1,'Fine dati');
    const stats=rows=>{let equity=0,peak=0,dd=0,win=0,loss=0;for(const t of rows){equity+=t.pnl;peak=Math.max(peak,equity);dd=Math.max(dd,peak-equity);if(t.pnl>0)win+=t.pnl;else loss-=t.pnl;}return {n:rows.length,pnl:equity,pf:loss?win/loss:null,wr:rows.length?100*rows.filter(t=>t.pnl>0).length/rows.length:0,dd};};
    const split=Math.floor(data.length*.7);
    return {trades,stats:stats(trades),train:stats(trades.filter(t=>t.index<split)),holdout:stats(trades.filter(t=>t.index>=split)),splitTime:data[split].t};
  }
  return {catalog,normalize,indicator,run};
})();
