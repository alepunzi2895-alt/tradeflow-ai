(function(){
  const panel=document.createElement('section');panel.id='tp-lab';panel.className='tp';
  panel.innerHTML=`<div class="mfp lab-workspace">
    <header class="lab-heading"><span class="nb-lbl">Research station / 01</span><h1>Da un’idea<br>a una strategia.</h1><p>Costruisci le regole. Misura i risultati. Conserva gli esperimenti.</p></header>
    <div class="lab-layout"><form id="lab-form" class="lab-editor">
      <section class="lab-block"><h2><span>01</span> Dati e ipotesi</h2>
        <label>Nome dell’esperimento<input id="lab-name" maxlength="80" value="Trend · EMA 20 / 50" required></label>
        <div class="lab-fields"><label>Simbolo<select id="lab-asset"><option>XAU</option><option>XAG</option><option>US30</option></select></label><label>Timeframe<select id="lab-tf"><option value="1h">H1</option><option value="1d">D1</option></select></label></div>
        <div class="lab-actions"><button type="button" id="lab-load">Carica storico recente</button><label class="lab-file">Importa OHLC JSON<input type="file" id="lab-file" accept=".json,application/json"></label></div>
        <p class="data-note">JSON: array di {t,o,h,l,c,v}, timestamp Unix in secondi, oppure {candles:[…]}. Seleziona simbolo e timeframe prima dell’importazione.</p>
        <p id="lab-data-status" role="status">Nessun dataset caricato.</p>
      </section>
      <section class="lab-block"><h2><span>02</span> Quando entrare</h2><p class="data-note">Tutte le condizioni devono essere vere sulla candela chiusa.</p><div id="lab-rules"></div><button type="button" id="lab-add">＋ Aggiungi condizione</button><label>Direzione<select id="lab-direction"><option value="long">Long</option><option value="short">Short</option></select></label></section>
      <section class="lab-block"><h2><span>03</span> Uscite e costi</h2><div class="lab-fields">
        <label>Stop loss %<input id="lab-stop" type="number" min="0.01" max="99" step="0.01" value="1" required></label>
        <label>Take profit %<input id="lab-take" type="number" min="0.01" max="99" step="0.01" value="2" required></label>
        <label>Unità sottostante<input id="lab-quantity" type="number" min="0.001" step="0.001" value="1" required></label>
        <label>Costi per lato (bps)<input id="lab-cost" type="number" min="0" step="0.1" value="2" required></label></div>
        <p class="data-note">Costi proporzionali comprensivi di commissioni, spread e slippage stimati. 1 bp = 0,01%. Una posizione per volta, senza leva o sizing del bot. P&L in valuta di quotazione.</p>
        <button type="button" id="lab-save">Salva bozza</button><p id="lab-save-status" role="status" class="data-note"></p><button class="lab-primary" type="submit">Esegui backtest <span>↗</span></button>
      </section></form>
      <aside class="lab-results"><div id="lab-result" class="lab-block" aria-live="polite"><span class="nb-lbl">Il tuo banco di prova</span><h2>Un’ipotesi.<br>Risultati verificabili.</h2><p>Carica i dati e avvia il primo esperimento. Qui troverai trade, curva del P&L e confronto temporale 70/30.</p><p class="data-note">Solo ricerca: nessun ordine inviato al bot.</p></div>
      <details class="lab-block"><summary>Esplora gli indicatori</summary><p class="data-note">Valori sull’ultima candela caricata · periodo 14, MACD 12/26/9. Volume disponibile solo se presente nel dataset.</p><div id="lab-indicators">Carica un dataset.</div></details>
      <section class="lab-block"><h2>Esperimenti salvati</h2><p class="data-note">Ultimi 20 su questo browser. Esporta il risultato per conservarlo.</p><div id="lab-history"></div></section></aside></div></div>`;
  document.getElementById('cont').append(panel);
  const nav=document.createElement('button');nav.className='tb';nav.dataset.tab='lab';nav.innerHTML='<span class="ti">◉</span><span class="tl">Laboratorio</span>';document.getElementById('tabs').append(nav);
  const el=id=>document.getElementById('lab-'+id);let data=null,meta=null,last=null,history=[];
  try{history=JSON.parse(localStorage.getItem('tf_lab_history')||'[]');if(!Array.isArray(history))history=[];}catch{}
  const options=()=>Object.entries(LabEngine.catalog).map(([k,v])=>`<option value="${k}">${v}</option>`).join('');
  function rule(seed={left:'rsi',period:14,op:'lt',right:'number',value:30,rightPeriod:14}){
    if(el('rules').children.length>=8)return;
    const row=document.createElement('div');row.className='lab-rule';
    row.innerHTML=`<label>Indicatore<select data-field="left">${options()}</select></label><label>Periodo<input data-field="period" type="number" min="2" max="250" value="14" required></label><label>Condizione<select data-field="op"><option value="gt">maggiore di</option><option value="lt">minore di</option><option value="crossUp">incrocia sopra</option><option value="crossDown">incrocia sotto</option></select></label><label>Confronto<select data-field="right"><option value="number">Valore fisso</option>${options()}</select></label><label>Soglia<input data-field="value" type="number" step="any" value="30" required></label><label>Periodo confronto<input data-field="rightPeriod" type="number" min="2" max="250" value="14" required></label><button type="button" aria-label="Rimuovi condizione">×</button>`;
    Object.entries(seed).forEach(([k,v])=>{row.querySelector(`[data-field="${k}"]`).value=v;});
    const toggle=()=>{const right=row.querySelector('[data-field=right]').value,left=row.querySelector('[data-field=left]').value;const fixed=key=>key.startsWith('macd')||['close','volume','obv'].includes(key);const constant=right==='number';for(const [field,hidden] of [['period',fixed(left)],['value',!constant],['rightPeriod',constant||fixed(right)]]){const input=row.querySelector(`[data-field=${field}]`);input.disabled=hidden;input.parentElement.hidden=hidden;}};
    row.querySelector('[data-field=right]').onchange=toggle;row.querySelector('[data-field=left]').onchange=toggle;toggle();row.querySelector('button').onclick=()=>row.remove();el('rules').append(row);
  }
  rule({left:'ema',period:20,op:'crossUp',right:'ema',value:0,rightPeriod:50});
  el('add').onclick=()=>rule();
  function config(){return {name:el('name').value,direction:el('direction').value,stop:+el('stop').value,take:+el('take').value,cost:+el('cost').value,quantity:+el('quantity').value,rules:[...el('rules').children].map(row=>Object.fromEntries([...row.querySelectorAll('[data-field]')].map(x=>[x.dataset.field,x.type==='number'?Number(x.value):x.value])))};}
  let dataVersion=0,activeWorker=null;
  function workerRun(candles,config,mode='backtest'){
    return new Promise((resolve,reject)=>{
      const worker=new Worker('/modules/lab-worker.js?v=audit1');
      if(mode==='backtest')activeWorker=worker;
      const done=()=>{clearTimeout(timer);worker.terminate();if(activeWorker===worker)activeWorker=null;};
      const timer=setTimeout(()=>{done();reject(Error('Tempo massimo superato'));},120000);
      worker.onmessage=({data})=>{done();data.ok?resolve(data.result):reject(Error(data.error));};
      worker.onerror=()=>{done();reject(Error('Calcolo non disponibile. Ricarica il Laboratorio.'));};
      worker.postMessage({candles,config,mode});
    });
  }
  function accept(rows,source){
    data=LabEngine.normalize(rows);meta={asset:el('asset').value,tf:el('tf').value,source,from:data[0].t,to:data.at(-1).t,count:data.length};
    el('data-status').textContent=`${meta.asset} · ${meta.tf} · ${data.length} candele · ${new Date(meta.from*1000).toLocaleDateString()} – ${new Date(meta.to*1000).toLocaleDateString()} · ${source}`;
    const version=++dataVersion,list=el('indicators');list.textContent='Calcolo indicatori…';
    workerRun(data,null,'indicators').then(values=>{
      if(version!==dataVersion)return;list.replaceChildren();
      for(const [key,label] of Object.entries(LabEngine.catalog)){const value=values[key],row=document.createElement('p');row.className='lab-indicator';row.textContent=label+'  '+(value==null?'Non disponibile':value.toLocaleString('it-IT',{maximumFractionDigits:4}));list.append(row);}
    }).catch(e=>{if(version===dataVersion)list.textContent=e.message;});
  }
  function invalidate(){dataVersion++;data=null;meta=null;el('data-status').textContent='Selezione modificata: ricarica i dati.';el('indicators').textContent='Carica un dataset.';}
  el('asset').onchange=invalidate;el('tf').onchange=invalidate;
  el('load').onclick=async()=>{
    const button=el('load'),asset=el('asset').value,tf=el('tf').value;invalidate();button.disabled=true;el('data-status').textContent='Caricamento…';
    try{const result=await fetchJSON(`/api/candles?asset=${asset}&interval=${tf}&range=${tf==='1d'?'1y':'60d'}&strict=1`,9500);if(asset!==el('asset').value||tf!==el('tf').value)return;if(!result?.ok)throw Error('Fonte non disponibile. Puoi importare un file OHLC JSON.');const seconds=tf==='1d'?86400:3600;accept(result.candles.filter(c=>c.t+seconds<=Date.now()/1000),result.source||'Provider remoto');}catch(e){el('data-status').textContent=e.message;}finally{button.disabled=false;}
  };
  el('file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>15000000)throw Error('File troppo grande (massimo 15 MB).');const json=JSON.parse(await file.text());accept(json.candles||json,'Importazione · '+file.name);}catch(err){data=null;meta=null;el('data-status').textContent=err.message;}finally{e.target.value='';}};
  const fmt=n=>n===null?'—':n.toLocaleString('it-IT',{maximumFractionDigits:2});
  function download(value,name){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  function renderHistory(){const root=el('history');root.replaceChildren();history.forEach(item=>{const b=document.createElement('button');b.className='lab-history-item';b.textContent=`${item.config.name} · ${item.meta.asset} ${item.meta.tf} · P&L ${fmt(item.stats.pnl)}`;b.title='Ripristina le regole; ricarica i dati per rieseguire';b.onclick=()=>{el('name').value=item.config.name;for(const key of ['direction','stop','take','cost','quantity'])el(key).value=item.config[key];el('rules').replaceChildren();item.config.rules.forEach(rule);el('asset').value=item.meta.asset;el('tf').value=item.meta.tf;invalidate();};root.append(b);});}
  el('form').onsubmit=async e=>{
    e.preventDefault();if(activeWorker)return;const root=el('result'),submit=el('form').querySelector('[type=submit]');submit.disabled=true;root.textContent='Backtest in esecuzione…';
    try{
      if(!data)throw Error('Carica un dataset prima di eseguire il backtest.');
      const cfg=config(),candles=data,metadata={...meta},version=dataVersion;
      const result=await workerRun(candles,cfg);
      if(version!==dataVersion)throw Error('Dataset modificato durante il calcolo: riesegui il backtest.');
      const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(candles)));
      last={engineVersion:'audit1',datasetSha256:[...new Uint8Array(hash)].map(x=>x.toString(16).padStart(2,'0')).join(''),createdAt:new Date().toISOString(),config:cfg,meta:metadata,candles,...result};
      root.innerHTML='<span class="nb-lbl">Esperimento completato</span>';const title=document.createElement('h2');title.textContent=cfg.name;root.append(title);const provenance=document.createElement('p');provenance.className='data-note';provenance.textContent=`${meta.asset} · ${meta.tf} · ${meta.count} candele · ${meta.source}`;root.append(provenance);const safety=document.createElement('p');safety.className='data-note';safety.textContent='Solo ricerca: nessun ordine inviato al bot.';root.append(safety);
      const grid=document.createElement('div');grid.className='lab-stats';for(const [label,value] of [['Trade',result.stats.n],['P&L netto',result.stats.pnl],['Profit factor',result.stats.pf],['Win rate %',result.stats.wr],['Drawdown chiuso',result.stats.dd]]){const tile=document.createElement('div');tile.textContent=label;const strong=document.createElement('strong');strong.textContent=fmt(value);tile.append(strong);grid.append(tile);}root.append(grid);
      let sum=0;const curve=[0,...result.trades.map(t=>sum+=t.pnl)];if(curve.length>1){const path=nbSmoothPath(curve,500,150,12);root.insertAdjacentHTML('beforeend',`<svg class="lab-chart" viewBox="0 0 500 150" role="img" aria-label="P&L cumulato dei trade chiusi"><path d="${path.line}" fill="none" stroke="var(--g)" stroke-width="2"/></svg>`);}
      const note=document.createElement('p');note.className='data-note';note.textContent=`Prime 70% candele: ${result.train.n} trade, P&L ${fmt(result.train.pnl)}. Ultime 30%: ${result.holdout.n} trade, P&L ${fmt(result.holdout.pnl)}. Divisione per data d’ingresso; confronto descrittivo, non validazione indipendente. Stop prima del target se entrambi toccati. Posizione residua chiusa a fine dati. Drawdown sui soli trade chiusi.`;root.append(note);
      const exportBtn=document.createElement('button');exportBtn.textContent='Esporta regole e risultati JSON';exportBtn.onclick=()=>download(last,'tradeflow-experiment.json');root.append(exportBtn);
      const details=document.createElement('details');details.innerHTML='<summary>Ultimi 100 trade</summary>';result.trades.slice(-100).forEach(t=>{const p=document.createElement('p');p.className='lab-indicator';p.textContent=`${new Date(t.entryTime*1000).toLocaleString()} → ${new Date(t.exitTime*1000).toLocaleString()} · ${t.reason} · ${fmt(t.pnl)}`;details.append(p);});root.append(details);
      history.unshift({createdAt:last.createdAt,config:cfg,meta:last.meta,stats:result.stats});history=history.slice(0,20);try{localStorage.setItem('tf_lab_history',JSON.stringify(history));}catch{note.textContent+=' Salvataggio locale non disponibile: esporta il risultato.';}renderHistory();
    }catch(error){root.textContent=error.message;}finally{submit.disabled=false;}
  };
  el('save').onclick=()=>{try{if(!el('form').reportValidity())return;localStorage.setItem('tf_lab_draft',JSON.stringify({config:config(),asset:el('asset').value,tf:el('tf').value}));el('save-status').textContent='Bozza salvata su questo browser.';}catch{el('save-status').textContent='Salvataggio locale non disponibile.';}};
  try{const draft=JSON.parse(localStorage.getItem('tf_lab_draft')||'null');if(draft){el('name').value=draft.config.name;for(const key of ['direction','stop','take','cost','quantity'])el(key).value=draft.config[key];el('rules').replaceChildren();draft.config.rules.forEach(rule);el('asset').value=draft.asset;el('tf').value=draft.tf;}}catch{}
  renderHistory();
})();
