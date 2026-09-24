// TradeFlow AI — modules/confidence-generic.js
// AI Confidence Score per gli strumenti NON core (forex e indici), 2026-09-24.
// Il punteggio MFKK di XAU/XAG/US30 usa fattori e soglie tarati sui metalli/Dow; qui un modello
// generico costruito sulle PROPRIETÀ dello strumento selezionato:
//   momentum rapportato al suo range medio giornaliero · trend H1 (MACD + ADX/DI dei suoi indicatori)
//   · dollaro (DXY col segno giusto: USD base o quotata) o VIX per gli indici · COT CFTC della sua
//   valuta/indice · sentiment MyFxBook contrarian · sessione = sue ore più attive · news delle sue
//   valute · volatilità odierna vs media.
// Stessa scala (0-100, >50 rialzista), stesse soglie di bias e stessa grafica del punteggio core.
// Pesi FISSI dichiarati sotto, non ottimizzati né validati in backtest: è una lettura del contesto,
// non un segnale d'ingresso.
(function(){
  const W={momentum:.20,trend:.20,dxy:.15,cot:.15,sentiment:.10,session:.10,news:.05,vol:.05};
  const indCache={};
  const DEF_ADR={fx:.6,index:1.2,metal:1.5};
  const col=s=>s>=60?'var(--green)':s<=40?'var(--red)':'var(--dim)';
  const fmt=(v,d=2)=>Number(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});

  function brokerHour(){                       // ora del server del broker (EET/EEST), come execution_safety.py
    const now=new Date(), y=now.getUTCFullYear();
    const lastSun=m=>{const d=new Date(Date.UTC(y,m+1,0,1));d.setUTCDate(d.getUTCDate()-d.getUTCDay());return d;};
    const off=now>=lastSun(2)&&now<lastSun(9)?3:2;
    return (now.getUTCHours()+off)%24;
  }
  async function loadInd(asset){
    const c=indCache[asset];
    if(c&&(c.loading||Date.now()-c.at<60000))return;
    indCache[asset]={...(c||{}),loading:true};
    const d=await fetchJSON(`/api/indicators?asset=${encodeURIComponent(asset)}&tf=1h`,12000);
    indCache[asset]={at:Date.now(),ind:d?.ok?d:null,loading:false};
    if((window.activeAsset||'XAU')===asset&&typeof updateConfidence==='function')updateConfidence(dashContext.prices||{},dashContext.sentiment);
  }

  window.updateConfidenceGeneric=function(active,prices){
    const inst=instrumentOf(active)||{id:active,label:active,type:'fx'};
    const prof=window._instProfiles?.instruments?.[active]||null;
    const x=prices?.[active]||dashContext.prices?.[active];
    const f={};
    loadInd(active);
    const ind=indCache[active]?.ind;

    // 1. Momentum rapportato al range medio giornaliero dello strumento
    const adr=prof?.volatility?.adr_pct_90d||DEF_ADR[inst.type]||1;
    if(x&&Number.isFinite(Number(x.change))){
      const chg=Number(x.change),r=chg/adr;
      const s=r>=.6?85:r>=.25?68:r<=-.6?15:r<=-.25?32:50;
      f.momentum={score:s,label:`Momentum ${inst.label} ${chg>=0?'+':''}${fmt(chg)}%`,sub:`${fmt(Math.abs(r)*100,0)}% del suo range medio (${fmt(adr)}%)`};
    }else f.momentum={score:50,label:'Momentum n/d',sub:'Quotazione non disponibile'};

    // 2. Trend H1 dai suoi indicatori (MACD vs segnale, DI dominante, ADX)
    if(ind?.macd||ind?.adx){
      const m=ind.macd?.cross, a=ind.adx;
      const up=(m==='above')+(a&&a.di_plus>a.di_minus), dn=(m==='below')+(a&&a.di_minus>a.di_plus);
      const strong=a?.adx>20;
      const s=up===2?(strong?80:68):dn===2?(strong?20:32):up>dn?60:dn>up?40:50;
      f.trend={score:s,label:s>55?'Trend H1 rialzista':s<45?'Trend H1 ribassista':'Trend H1 misto',sub:`MACD ${m==='above'?'sopra':'sotto'} il segnale · DI+ ${a?fmt(a.di_plus,1):'—'} / DI− ${a?fmt(a.di_minus,1):'—'} · ADX ${a?fmt(a.adx,1):'—'}`};
    }else f.trend={score:50,label:'Trend H1 in caricamento',sub:'Indicatori dello strumento'};

    // 3. Dollaro (forex, col segno giusto) o VIX (indici)
    const ccy=inst.ccy||[];
    if(inst.type==='fx'&&ccy.includes('USD')){
      const dxy=prices?.DXY||dashContext.prices?.DXY, dc=Number(dxy?.change);
      const sign=ccy[1]==='USD'?-1:1;                       // EUR/USD: USD forte = coppia giù; USD/JPY: su
      if(Number.isFinite(dc)){
        const e=sign*dc, s=e>.3?78:e>.1?62:e<-.3?22:e<-.1?38:50;
        f.dxy={score:s,label:`DXY ${dc>=0?'+':''}${fmt(dc)}% · dollaro ${dc>=0?'forte':'debole'}`,sub:ccy[1]==='USD'?`USD è la valuta quotata: effetto inverso su ${inst.label}`:`USD è la valuta base: stesso verso su ${inst.label}`};
      }else f.dxy={score:50,label:'DXY n/d',sub:''};
    }else if(inst.type==='index'){
      const vc=Number((prices?.VIX||dashContext.prices?.VIX)?.change);
      if(Number.isFinite(vc)){const s=vc>5?25:vc>2?38:vc<-5?75:vc<-2?62:50;
        f.dxy={score:s,label:`VIX ${vc>=0?'+':''}${fmt(vc)}% · ${vc>2?'avversione al rischio':vc<-2?'propensione al rischio':'volatilità stabile'}`,sub:'Paura in aumento pesa sugli indici'};}
      else f.dxy={score:50,label:'VIX n/d',sub:''};
    }else f.dxy={score:50,label:'Dollaro non rilevante',sub:''};

    // 4. COT (già con il segno giusto per USD/xxx nella scheda strumento)
    const cot=prof?.cot;
    if(cot&&!cot.error&&!cot.stale){
      const n=cot.net_pct_oi; let s=n>25?72:n>10?62:n<-25?28:n<-10?38:50;
      if(cot.week_change) s+=Math.sign(cot.week_change)*4;
      f.cot={score:s,label:`COT ${cot.bias==='long'?'speculatori long':cot.bias==='short'?'speculatori short':'neutro'} (${fmt(n,1)}% OI)`,sub:`${cot.market||''} · report ${cot.report_date}`};
    }else f.cot={score:50,label:'COT non disponibile',sub:cot?.stale?'Dato vecchio':'Nessun contratto CFTC o scheda non ancora calcolata'};

    // 5. Sentiment retail contrarian
    const st=dashContext.sentiment;
    if(st?.longPct!=null){
      const s=st.longPct>65?25:st.longPct>55?40:st.shortPct>65?75:st.shortPct>55?60:50;
      f.sentiment={score:s,label:`Retail ${fmt(st.longPct,0)}% long / ${fmt(st.shortPct,0)}% short`,sub:'Lettura contrarian (MyFxBook)'};
    }else f.sentiment={score:50,label:'Sentiment n/d',sub:'MyFxBook non pubblica questo strumento o non collegato'};

    // 6. Sessione: ore broker in cui lo strumento si muove di più (scheda strumento)
    const hours=prof?.volatility?.active_hours_broker||[];
    const h=brokerHour();
    if(hours.length){
      const near=hours.some(x=>Math.abs(x-h)===1||Math.abs(x-h)===23);
      const s=hours.includes(h)?80:near?65:40;
      f.session={score:s,label:hours.includes(h)?'Ora di massima attività':near?'Vicino alle ore più attive':'Fuori dalle ore più attive',sub:`Ore più mosse (broker): ${hours.map(x=>String(x).padStart(2,'0')).join(', ')} · ora ${String(h).padStart(2,'0')}`};
    }else f.session={score:50,label:'Sessione n/d',sub:'Scheda strumento non ancora calcolata'};

    // 7. News delle sue valute
    const cc=[...new Set(ccy.map(c=>c==='XAU'||c==='XAG'?'USD':c))];
    const now=Date.now();
    const next=(typeof allCalEvents!=='undefined'?allCalEvents:[]).filter(e=>e.impact==='High'&&cc.includes(String(e.currency).toUpperCase())&&Date.parse(e.time)>now)
      .sort((a,b)=>Date.parse(a.time)-Date.parse(b.time))[0];
    const mins=next?(Date.parse(next.time)-now)/60000:Infinity;
    f.news=mins<60?{score:30,label:`News tra ${Math.round(mins)} min`,sub:`${next.currency} · ${next.event}`}
      :mins<180?{score:45,label:`News tra ${Math.round(mins/60)} h`,sub:`${next.currency} · ${next.event}`}
      :{score:60,label:'Nessuna news imminente',sub:`Valute: ${cc.join('/')}`};

    // 8. Volatilità di oggi vs range medio
    if(x?.high&&x?.low&&x?.price){
      const r=(x.high-x.low)/x.price*100/adr;
      f.vol={score:r>1.5?40:55,label:r>1.5?'Giornata già estesa':r<.5?'Range compresso':'Volatilità nella norma',sub:`Range di oggi ${fmt(r*100,0)}% della media`};
    }else f.vol={score:50,label:'Volatilità n/d',sub:''};

    const total=Math.round(Object.entries(W).reduce((s,[k,w])=>s+(f[k]?.score??50)*w,0));
    let bias,summary;
    if(total>=75){bias='FORTE BUY';summary='Contesto fortemente rialzista';}
    else if(total>=60){bias='BUY VALIDO';summary='Contesto rialzista';}
    else if(total>=50){bias='BUY PARZIALE';summary='Leggera prevalenza rialzista — attendi conferme';}
    else if(total>=40){bias='NEUTRO';summary='Fattori misti';}
    else if(total>=30){bias='SELL PARZIALE';summary='Leggera prevalenza ribassista — attendi conferme';}
    else if(total>=20){bias='SELL VALIDO';summary='Contesto ribassista';}
    else{bias='FORTE SELL';summary='Contesto fortemente ribassista';}

    const color=total>=60?'var(--green)':total>=40?'var(--yellow)':'var(--red)';
    const set=(id,fn)=>{const el=document.getElementById(id);if(el)fn(el);};
    set('conf-num',el=>{el.textContent=total;el.style.color=color;});
    set('conf-bias',el=>{el.textContent=bias;el.style.color=color;});
    set('conf-sub',el=>{el.textContent=summary;});
    // Riga sessione: quella del modello core parla delle kill zone dell'oro, qui le ore dello strumento.
    set('conf-session',el=>{el.textContent=f.session.label+(hours.length?' · ore broker '+hours.map(x=>String(x).padStart(2,'0')).join(', '):'');el.style.color=col(f.session.score);});
    set('conf-circle',el=>{el.style.strokeDashoffset=138.2-(total/100)*138.2;el.style.stroke=color;});
    const ICO={momentum:'📊',trend:'📈',dxy:inst.type==='index'?'😱':'💵',cot:'🏛️',sentiment:'👥',session:'⏰',news:'📰',vol:'📉'};
    set('conf-factors',fl=>{
      fl.innerHTML='';
      Object.keys(W).forEach(k=>{
        const it=f[k],pct=Math.max(0,Math.min(100,it.score)),c=col(it.score);
        const div=document.createElement('div');div.className='cf';
        div.innerHTML=`<div class="cf-ico">${ICO[k]}</div><div class="cf-info"><div class="cf-label" style="color:${c}"></div><div class="cf-sub"><span></span> <span style="color:#3a3d44">peso ${Math.round(W[k]*100)}%</span></div></div>
          <div class="cf-score-bar"><div class="cf-track"><div class="cf-fill" style="width:${pct}%;background:${c}"></div></div><div class="cf-pct" style="color:${c}">${pct}</div></div>`;
        div.querySelector('.cf-label').textContent=it.label;div.querySelector('.cf-sub span').textContent=it.sub||'';
        fl.appendChild(div);
      });
    });
    set('conf-quality',el=>{el.style.display='block';el.style.background='#4fc3f710';el.style.borderRadius='7px';el.style.padding='7px 10px';el.style.color='var(--dim)';el.style.fontSize='11px';el.style.lineHeight='1.5';
      el.textContent=`Modello generico per ${inst.label}: 8 fattori calcolati sulle sue proprietà, pesi fissi non validati in backtest. È una lettura del contesto, non un segnale d’ingresso.`;});
    dashContext.confidence={score:total,bias,summary,model:'generico',factors:{
      momentum:{score:f.momentum.score,label:f.momentum.label},dxy:{score:f.dxy.score,label:f.dxy.label},
      session:{score:f.session.score,label:f.session.label},sentiment:{score:f.sentiment.score,label:f.sentiment.label},
      trend:{score:f.trend.score,label:f.trend.label},cot:{score:f.cot.score,label:f.cot.label},
      news:{score:f.news.score,label:f.news.label},vol:{score:f.vol.score,label:f.vol.label}}};
  };
})();
