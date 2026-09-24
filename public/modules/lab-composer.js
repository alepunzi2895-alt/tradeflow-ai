// TradeFlow AI — modules/lab-composer.js
// Composer (2026-09-24): le regole dell'editor del Laboratorio diventano una specifica JSON
// validata sul worker (scripts/strategy_spec.py) con dati MT5, spread reale per barra, uscite
// strutturate e criteri di promozione fissi. Stesse formule del motore del browser (parità
// verificata da scripts/test_strategy_spec.py): l'anteprima nel browser resta la prova veloce.
(function(){
  const form=document.getElementById('lab-form');
  if(!form)return;
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=(v,d=2)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
  const TEMPLATES=[
    {id:'cloud',title:'Pullback nella nuvola · H1',tf:'H1',direction:'long',evidence:'Approssima il tuo Pine con le regole del laboratorio (non esprimono “il minimo tocca la EMA”). Validata il 24/09 su XAU H1: PF 1,74 ma solo 36 trade in 2 anni → campione insufficiente.',
     rules:[{left:'ema',period:20,op:'gt',right:'ema',value:0,rightPeriod:50},{left:'close',period:14,op:'crossUp',right:'ema',value:0,rightPeriod:20},{left:'macd',period:14,op:'gt',right:'macdSignal',value:0,rightPeriod:14}],
     exit:{stop:'donchian',stopA:20,stopB:.3,take_r:2,partial:false,time:30}},
    {id:'adx',title:'Trend ADX + DI + MACD · H1',tf:'H1',direction:'long',evidence:'Stessa famiglia di S00 V3 (regole tue): trend forte, DI dominante, incrocio MACD.',
     rules:[{left:'adx',period:14,op:'gt',right:'number',value:25,rightPeriod:14},{left:'diPlus',period:14,op:'gt',right:'diMinus',value:0,rightPeriod:14},{left:'macd',period:14,op:'crossUp',right:'macdSignal',value:0,rightPeriod:14}],
     exit:{stop:'atr',stopA:1.5,stopB:14,take_r:2.3,partial:true,time:null}},
    {id:'donchian',title:'Breakout Donchian 20 · H4',tf:'H4',direction:'long',evidence:'Classico trend-following: poche operazioni, stop largo.',
     rules:[{left:'close',period:14,op:'crossUp',right:'donHigh',value:0,rightPeriod:20}],
     exit:{stop:'atr',stopA:2,stopB:14,take_r:3,partial:false,time:null}},
    {id:'rsi',title:'Rimbalzo RSI nel trend · H1',tf:'H1',direction:'long',evidence:'Da verificare: la versione RSI(2) su XAU M5/M15 ha perso dopo i costi.',
     rules:[{left:'close',period:14,op:'gt',right:'sma',value:0,rightPeriod:200},{left:'rsi',period:14,op:'crossUp',right:'number',value:30,rightPeriod:14}],
     exit:{stop:'atr',stopA:1.5,stopB:14,take_r:1.5,partial:true,time:48}},
  ];
  const sec=document.createElement('section');sec.className='lab-block';sec.id='lab-comp';
  sec.innerHTML=`<h2><span>04</span> Validazione sul worker</h2>
    <p class="data-note">Le regole sopra, eseguite sulla macchina del bot con gli storici MT5 del broker (2 anni), lo spread reale di ogni candela e i criteri di promozione del sistema. Ogni validazione conta come un tentativo di ricerca.</p>
    <details class="lab-comp-tpl"><summary>Suggerimenti: parti da un modello</summary><div id="lab-comp-templates"></div></details>
    <div class="lab-fields">
      <label>Strumento<select id="lab-comp-inst"></select></label>
      <label>Timeframe<select id="lab-comp-tf">${['M5','M15','M30','H1','H4','D1'].map(t=>`<option${t==='H1'?' selected':''}>${t}</option>`).join('')}</select></label>
      <label>Stop<select id="lab-comp-stop"><option value="atr">ATR ×</option><option value="donchian">Strutturale (min/max N barre)</option><option value="pct">Percentuale</option></select></label>
      <label><span id="lab-comp-stopA-l">Multiplo ATR</span><input id="lab-comp-stopA" type="number" step="any" value="1.5"></label>
      <label><span id="lab-comp-stopB-l">Periodo ATR</span><input id="lab-comp-stopB" type="number" step="any" value="14"></label>
      <label>Target (multipli del rischio R)<input id="lab-comp-take" type="number" min="0.2" max="20" step="0.1" value="2"></label>
      <label>Uscita a tempo (barre, vuoto = no)<input id="lab-comp-time" type="number" min="1" max="2000" step="1"></label>
      <label>Sessione d’ingresso (ora broker)<span class="lab-comp-sess"><input id="lab-comp-from" type="number" min="0" max="23" placeholder="da"><input id="lab-comp-to" type="number" min="1" max="24" placeholder="a"></span></label>
    </div>
    <label class="lab-comp-check"><input type="checkbox" id="lab-comp-partial"> Chiudi metà a 1R e porta lo stop a pareggio (alza il win rate)</label>
    <p id="lab-comp-hint" class="data-note"></p>
    <button type="button" class="lab-primary" id="lab-comp-go">Valida sul worker <span>⚗</span></button>
    <p id="lab-comp-job" class="data-note" role="status"></p>`;
  form.append(sec);
  const aside=document.querySelector('#tp-lab .lab-results');
  const out=document.createElement('section');out.className='lab-block';out.id='lab-comp-result';out.setAttribute('aria-live','polite');
  out.innerHTML='<span class="nb-lbl">Validazione sul worker</span><h2>Criteri di promozione</h2><p class="data-note">Componi le regole e premi “Valida sul worker”: qui vedrai quali criteri supera e l’esito.</p>';
  const runs=document.createElement('section');runs.className='lab-block';runs.id='lab-comp-runs';runs.innerHTML='<h2>Validazioni recenti</h2><div id="lab-comp-runlist" class="data-note">—</div>';
  const onbot=document.createElement('section');onbot.className='lab-block';onbot.id='lab-bot';
  onbot.innerHTML='<h2>Sul bot (demo)</h2><p class="data-note">Strategie del Laboratorio eseguite dal bot con lo stesso interprete del backtest. Solo conto demo, lotto fisso, al massimo 3 attive; pausa automatica se i risultati dal vivo si allontanano da quelli attesi.</p><div id="lab-bot-list" class="data-note">—</div><p id="lab-bot-msg" class="data-note" role="status"></p>';
  aside?.prepend(out); out.after(onbot); onbot.after(runs);
  const $=id=>document.getElementById(id);
  let profiles=null, polling=null;

  function fillInst(){const sel=$('lab-comp-inst'),cur=sel.value||window.activeAsset||'XAU';sel.replaceChildren(...instrumentList().map(i=>new Option(i.label,i.id)));sel.value=instrumentOf(cur)?cur:'XAU';hint();}
  function stopLabels(){
    const t=$('lab-comp-stop').value;
    const [a,b,showB]=t==='atr'?['Multiplo ATR','Periodo ATR',true]:t==='donchian'?['Barre (min/max)','Buffer (× ATR)',true]:['Stop %','',false];
    $('lab-comp-stopA-l').textContent=a;$('lab-comp-stopB-l').textContent=b;$('lab-comp-stopB').parentElement.hidden=!showB;
  }
  function hint(){
    const id=$('lab-comp-inst').value,tf=$('lab-comp-tf').value,c=profiles?.instruments?.[id]?.costs;
    if(!c||c.cost_pct_atr_h1==null){$('lab-comp-hint').textContent='';return;}
    const mins={M5:5,M15:15,M30:30,H1:60,H4:240,D1:1440}[tf];
    const est=c.cost_pct_atr_h1*Math.sqrt(60/mins);           // ATR ~ radice del tempo
    const level=est<5?'basso':est<15?'medio':'alto';
    $('lab-comp-hint').innerHTML=`Costo di ${esc(instrumentLabel(id))}: spread ≈ <b>${num(est,1)}%</b> dell’ATR ${esc(tf)} (stima dalla scheda strumento) · ${level}${est>=15?' — su questo timeframe i costi mangiano gran parte del movimento: prova un timeframe più alto o target più ampi':''}.`;
    $('lab-comp-hint').style.color=est<5?'var(--green)':est<15?'#F4B860':'var(--red)';
  }
  function renderTemplates(){
    $('lab-comp-templates').innerHTML=TEMPLATES.map(t=>`<button type="button" class="lab-comp-t" data-tpl="${t.id}"><b>${esc(t.title)}</b><span>${esc(t.evidence)}</span></button>`).join('');
    $('lab-comp-templates').querySelectorAll('[data-tpl]').forEach(b=>b.addEventListener('click',()=>{
      const t=TEMPLATES.find(x=>x.id===b.dataset.tpl);
      window.labSetRules?.(t.rules,t.title,t.direction);
      $('lab-comp-tf').value=t.tf;$('lab-comp-stop').value=t.exit.stop;stopLabels();
      $('lab-comp-stopA').value=t.exit.stopA;$('lab-comp-stopB').value=t.exit.stopB;$('lab-comp-take').value=t.exit.take_r;
      $('lab-comp-partial').checked=t.exit.partial;$('lab-comp-time').value=t.exit.time??'';hint();
      $('lab-comp-job').textContent='Modello caricato: controlla le regole in “02 Quando entrare” e valida.';$('lab-comp-job').style.color='var(--dim)';
    }));
  }
  function spec(){
    const cfg=window.labGetRules?.()||{};
    const stop=$('lab-comp-stop').value,A=Number($('lab-comp-stopA').value),B=Number($('lab-comp-stopB').value);
    const from=$('lab-comp-from').value,to=$('lab-comp-to').value;
    return {v:1,name:cfg.name,instrument:$('lab-comp-inst').value,tf:$('lab-comp-tf').value,direction:cfg.direction,rules:cfg.rules,
      session:from!==''&&to!==''?{from:Number(from),to:Number(to)}:null,
      exit:{stop:stop==='atr'?{type:'atr',mult:A,period:B}:stop==='donchian'?{type:'donchian',period:A,buffer_atr:B}:{type:'pct',value:A},
        take_r:Number($('lab-comp-take').value),partial:$('lab-comp-partial').checked?{at_r:1,fraction:.5}:null,
        time_stop_bars:$('lab-comp-time').value?Number($('lab-comp-time').value):null},max_trades_per_day:10};
  }
  function renderResult(r,sp,requestId){
    if(r.error){out.innerHTML=`<span class="nb-lbl">Validazione sul worker</span><h2>Non eseguita</h2><p class="data-note" style="color:var(--red)">${esc(r.error)}</p>`;return;}
    const vcol=r.verdict==='PROMUOVIBILE'?'var(--green)':r.verdict==='CANDIDATA DEMO'?'#F4B860':'var(--red)';
    const row=(l,s)=>`<tr><td>${l}</td><td>${s?.n??'—'}</td><td>${num(s?.pf)}</td><td>${s?.wr!=null?num(s.wr,1)+'%':'—'}</td></tr>`;
    let path='';if(r.equity_r?.length>1&&typeof nbSmoothPath==='function'){path=`<svg class="lab-chart" viewBox="0 0 500 150" role="img" aria-label="Curva dei risultati in R"><path d="${nbSmoothPath([0,...r.equity_r],500,150,12).line}" fill="none" stroke="${vcol}" stroke-width="2"/></svg>`;}
    out.innerHTML=`<span class="nb-lbl">Validazione sul worker · ${esc(sp?.name||r.name)}</span>
      <h2 style="color:${vcol}">${esc(r.verdict)}</h2>
      <p class="data-note">${esc(instrumentLabel(r.instrument))} ${esc(r.tf)} ${esc(r.direction)} · ${esc(r.dataset?.symbol)} · ${r.dataset?.bars?.toLocaleString('it-IT')} candele ${esc(r.dataset?.from)} → ${esc(r.dataset?.to)} · spread ${esc(r.dataset?.spread)} · ${num(r.trades_per_month,1)} trade/mese</p>
      <ul class="lab-gates">${r.gates.map(g=>`<li class="${g.ok?'ok':'ko'}">${g.ok?'✓':'✗'} ${esc(g.label)}</li>`).join('')}</ul>
      <table class="lab-hist-table"><thead><tr><th></th><th>Trade</th><th>PF</th><th>Win rate</th></tr></thead><tbody>
        ${row('Tutto il periodo',r.full)}${row('Ultimi mesi (mai usati)',r.holdout)}${row('Costi raddoppiati',r.costs2)}</tbody></table>
      <p class="data-note">Walk-forward: ${r.folds.map(f=>num(f.pf)).join(' · ')||'—'} · risultato ${num(r.net_r,1)}R, drawdown max ${num(r.max_dd_r,1)}R, media ${num(r.avg_r,3)}R a trade · test di significatività ${r.dsr?`p=${num(r.dsr.p,3)} ${r.dsr.significant?'✓':'✗'}`:'n/d'} su ${Number(r.num_trials).toLocaleString('it-IT')} tentativi totali</p>
      ${path}
      <p class="data-note">${r.verdict==='PROMUOVIBILE'?'Supera tutti i criteri: può diventare candidata per il bot (passo successivo).':r.verdict==='CANDIDATA DEMO'?'Supera i criteri pratici ma non il test di significatività: come S35, può andare solo in demo a lotto fisso.':'Non supera i criteri: non va sul conto. Le barre ✗ dicono dove intervenire, ma ogni nuova variante conta come tentativo.'}</p>
      ${promoteBlock(r,sp,requestId)}`;
    out.querySelector('#lab-promote-go')?.addEventListener('click',promote);
  }
  function promoteBlock(r,sp,requestId){
    if(!requestId||!['PROMUOVIBILE','CANDIDATA DEMO'].includes(r.verdict))return '';
    const partial=!!sp?.exit?.partial, def=partial?0.02:0.01;
    const opts=[0.01,0.02,0.03,0.04,0.05].map(l=>`<option value="${l}"${l===def?' selected':''}>${l.toFixed(2)}</option>`).join('');
    return `<div class="lab-promote"><label>Lotto fisso<select id="lab-promote-lot">${opts}</select></label>
      <button type="button" id="lab-promote-go" data-req="${esc(requestId)}">Metti in demo sul bot</button></div>
      <p class="data-note">Il bot la eseguirà solo su conto demo, con i controlli di sicurezza di ogni ordine (max 3 posizioni sul conto, rischio per trade e complessivo).${partial?' Con la chiusura parziale serve almeno 0,02.':''}</p>`;
  }
  async function promote(e){
    const btn=e.currentTarget,msg=$('lab-bot-msg'),lot=$('lab-promote-lot').value;
    if(!confirm('Mettere questa strategia sul bot, in demo, a lotto fisso '+lot+'?'))return;
    btn.disabled=true;
    try{
      const res=await authFetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(8000),body:JSON.stringify({action:'lab_promote',request_id:btn.dataset.req,lot:Number(lot)})});
      const r=await res.json();if(!res.ok||!r.ok)throw Error(r.error||'Promozione non riuscita');
      msg.style.color='var(--green)';msg.textContent='✓ '+r.item.id+' sul bot: parte al prossimo segnale (il bot rilegge l’elenco ogni minuto).';
      loadBot();
    }catch(err){msg.style.color='var(--red)';msg.textContent='✗ '+err.message;btn.disabled=false;}
  }
  async function loadBot(){
    const d=await dbLoad('lab_strategies_get',{},6000),list=$('lab-bot-list');
    const items=(d?.items||[]).filter(x=>x.status!=='retired');
    if(!items.length){list.textContent='Nessuna strategia del Laboratorio sul bot.';return;}
    const live=await Promise.all(items.map(x=>dbLoad('strat_live_get',{key:x.id},6000)));
    list.innerHTML=items.map((x,i)=>{
      const L=live[i]?.data?.overall,e=x.expected||{};
      const st=x.status==='active'?'<b style="color:var(--green)">attiva</b>'
        :'<b style="color:#F4B860">in pausa</b>'+(x.status_reason?' · '+esc(x.status_reason):'')+(x.paused_by==='bot'?' (automatica)':'');
      const liveTxt=L?`${L.n} trade · PF ${num(L.pf)} · WR ${num(L.wr,1)}% · ${num(L.pnl)}`:'nessun trade ancora';
      const act=x.status==='active'?`<button type="button" data-lab-act="paused" data-id="${esc(x.id)}">Pausa</button>`:`<button type="button" data-lab-act="active" data-id="${esc(x.id)}">Riprendi</button>`;
      return `<div class="lab-bot-item"><div><b>${esc(x.id)}</b> · ${esc(x.name)} · ${esc(instrumentLabel(x.spec?.instrument))} ${esc(x.spec?.tf)} ${esc(x.spec?.direction)} · lotto ${num(x.lot)}</div>
        <div>${st}</div>
        <div>Atteso: PF ${num(e.pf)} · WR ${num(e.wr,1)}% · ~${num(e.trades_per_month,1)} trade/mese — Dal vivo: ${liveTxt}</div>
        <div class="lab-bot-actions">${act}<button type="button" data-lab-act="retired" data-id="${esc(x.id)}">Ritira</button></div></div>`;
    }).join('');
    list.querySelectorAll('[data-lab-act]').forEach(b=>b.addEventListener('click',async()=>{
      const act=b.dataset.labAct,msg=$('lab-bot-msg');
      if(act==='retired'&&!confirm('Ritirare '+b.dataset.id+'? Le posizioni aperte restano gestite da MT5 con i loro stop e target.'))return;
      b.disabled=true;
      try{
        const res=await authFetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(8000),body:JSON.stringify({action:'lab_strategy_set',id:b.dataset.id,status:act})});
        const r=await res.json();if(!res.ok||!r.ok)throw Error(r.error||'Operazione non riuscita');
        msg.style.color='var(--green)';msg.textContent='✓ '+b.dataset.id+': '+(act==='active'?'riattivata':act==='paused'?'in pausa':'ritirata');loadBot();
      }catch(err){msg.style.color='var(--red)';msg.textContent='✗ '+err.message;b.disabled=false;}
    }));
  }
  async function loadRuns(){
    const d=await dbLoad('spec_runs_get',{},6000);
    const list=$('lab-comp-runlist');
    if(!d?.ok||!d.runs?.length){list.textContent='Nessuna validazione ancora.';return;}
    list.innerHTML=d.runs.map((x,i)=>{const s=x.summary||{};const v=s.verdict||(s.error?'errore':x.status==='done'?'—':'in corso');
      return `<button type="button" class="lab-history-item" data-run="${i}">${esc(x.spec?.name)} · ${esc(x.spec?.instrument)} ${esc(x.spec?.tf)} · <b>${esc(v)}</b>${s.pf!=null?` · PF ${num(s.pf)} · ultimi mesi ${num(s.holdout_pf)}`:''}</button>`;}).join('');
    list.querySelectorAll('[data-run]').forEach(b=>b.addEventListener('click',()=>{
      const sp=d.runs[+b.dataset.run].spec;if(!sp)return;
      window.labSetRules?.(sp.rules,sp.name,sp.direction);$('lab-comp-inst').value=sp.instrument;$('lab-comp-tf').value=sp.tf;
      const st=sp.exit.stop;$('lab-comp-stop').value=st.type;stopLabels();
      $('lab-comp-stopA').value=st.type==='atr'?st.mult:st.type==='donchian'?st.period:st.value;$('lab-comp-stopB').value=st.type==='atr'?st.period:st.type==='donchian'?st.buffer_atr:'';
      $('lab-comp-take').value=sp.exit.take_r;$('lab-comp-partial').checked=!!sp.exit.partial;$('lab-comp-time').value=sp.exit.time_stop_bars??'';
      $('lab-comp-from').value=sp.session?.from??'';$('lab-comp-to').value=sp.session?.to??'';hint();
      const rid=d.runs[+b.dataset.run].request_id;dbLoad('backtest_result_get',{request_id:rid},6000).then(r=>{if(r?.status==='done'&&r.data)renderResult(r.data,sp,rid);});
    }));
  }
  $('lab-comp-go').addEventListener('click',async()=>{
    const btn=$('lab-comp-go'),job=$('lab-comp-job');
    if(!form.reportValidity())return;
    btn.disabled=true;job.style.color='var(--dim)';job.textContent='Invio della specifica…';
    try{
      const sp=spec();
      const res=await authFetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(8000),body:JSON.stringify({action:'spec_cmd_push',spec:sp})});
      const r=await res.json();
      if(!res.ok||!r.ok)throw Error(r.error||'Specifica non accettata');
      const t0=Date.now();if(polling)clearInterval(polling);
      const tick=async()=>{
        const d=await dbLoad('backtest_result_get',{request_id:r.request_id},6000);const s=Math.round((Date.now()-t0)/1000);
        if(d?.status==='done'||d?.status==='failed'){clearInterval(polling);polling=null;btn.disabled=false;job.textContent=d.status==='done'?`Completata in ${s}s`:'';renderResult(d.data||{error:'Validazione non riuscita'},r.spec,r.request_id);loadRuns();return;}
        job.textContent=d?.status==='running'?`Il worker sta scaricando i dati e validando… (${s}s)`:`In coda (${s}s): parte appena il worker la prende`;
        if(s>900){clearInterval(polling);polling=null;btn.disabled=false;job.textContent='Nessuna risposta dal worker dopo 15 minuti: è acceso? (parte insieme al bot)';}
      };
      polling=setInterval(tick,3000);tick();
    }catch(e){job.textContent='✗ '+e.message;job.style.color='var(--red)';btn.disabled=false;}
  });
  $('lab-comp-stop').addEventListener('change',()=>{const t=$('lab-comp-stop').value;$('lab-comp-stopA').value=t==='atr'?1.5:t==='donchian'?20:1;$('lab-comp-stopB').value=t==='atr'?14:.3;stopLabels();});
  $('lab-comp-inst').addEventListener('change',hint);$('lab-comp-tf').addEventListener('change',hint);
  stopLabels();renderTemplates();fillInst();window.instrumentsReady?.then(fillInst);
  document.querySelector('[data-tab=lab]')?.addEventListener('click',async()=>{loadRuns();loadBot();if(!profiles){const d=await dbLoad('profiles_get',{},8000);if(d?.ok){profiles=d.data;hint();}}});
})();
