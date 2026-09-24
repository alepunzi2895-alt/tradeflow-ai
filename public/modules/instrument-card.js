// TradeFlow AI — modules/instrument-card.js
// "Scheda strumento" (2026-09-24): la memoria di ogni strumento del registro per l'asset attivo.
// Dati calcolati dal worker sulla macchina con MT5 (scripts/instrument_profile.py): costi reali
// dal broker, volatilità e orari, correlazioni, COT CFTC, ricerca già fatta. News dal calendario
// già caricato (filtrate per valuta), note personali salvate sull'account (doc 'inst_notes').
(function(){
  const anchor=document.getElementById('sent-card');
  if(!anchor)return;
  const card=document.createElement('section');card.className='inst-card';card.id='inst-card';
  card.setAttribute('aria-labelledby','inst-title');
  anchor.after(card);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const num=(v,d=2)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
  const ago=iso=>{if(!iso)return '—';const h=(Date.now()-Date.parse(iso))/3600000;return h<1?`${Math.max(1,Math.round(h*60))} min fa`:h<48?`${Math.round(h)} h fa`:`${Math.round(h/24)} g fa`;};
  let profiles=null, loadedAt=0, notes={}, noteTimer=null, pendingJob=null;

  async function load(force){
    if(!force&&profiles&&Date.now()-loadedAt<600000)return;
    const d=await dbLoad('profiles_get',{},8000);
    if(d?.ok){profiles=d.data;loadedAt=Date.now();window._instProfiles=profiles;
      if(typeof updateConfidence==='function'&&!isCoreAsset(window.activeAsset||'XAU'))updateConfidence(dashContext.prices||{},dashContext.sentiment);}
  }
  function costVerdict(pct){
    if(pct==null)return ['—','var(--dim)'];
    return pct<5?['basso: adatto anche all’intraday','var(--green)']:pct<15?['medio: scalp solo con target ampi','#F4B860']:['alto: scalp sconsigliato, meglio H1+','var(--red)'];
  }
  function newsFor(ccy){
    const ev=(typeof allCalEvents!=='undefined'?allCalEvents:[])||[];
    const now=Date.now(), week=now+7*86400000;
    return ev.filter(e=>ccy.includes(String(e.currency).toUpperCase())&&Date.parse(e.time)>now&&Date.parse(e.time)<week)
      .sort((a,b)=>Date.parse(a.time)-Date.parse(b.time)).slice(0,5);
  }
  function render(){
    const id=window.activeAsset||'XAU', inst=instrumentOf(id), p=profiles?.instruments?.[id];
    const label=inst?.label||id;
    if(!p){
      card.innerHTML=`<div class="inst-head"><div><span class="nb-lbl">Scheda strumento</span><h3 id="inst-title">${esc(label)}</h3></div>${refreshBtn()}</div>
        <p class="data-note">${profiles?'Scheda non ancora calcolata per questo strumento.':'Schede non ancora disponibili: le calcola il worker sulla macchina con MT5 (parte insieme al bot, poi una volta al giorno).'}</p><p class="data-note inst-job" role="status"></p>`;
      wire(); return;
    }
    const c=p.costs||{}, v=p.volatility||{}, b=p.broker||{}, cot=p.cot, r=p.research||{}, cr=p.correlations||{};
    const d=b.digits??inst?.decimals??2;
    const [verdict,vcol]=costVerdict(c.cost_pct_atr_h1);
    const ccy=(p.ccy||[]).map(x=>x==='XAU'||x==='XAG'?'USD':x);
    const news=newsFor([...new Set(ccy)]);
    const chip=x=>`<button type="button" class="inst-chip" data-switch="${esc(x.id)}" title="Passa a ${esc(instrumentLabel(x.id))}">${esc(instrumentLabel(x.id))} <b>${num(x.r90,2)}</b></button>`;
    const cotHtml=!cot?`<p class="data-note">Nessun contratto CFTC per questo strumento${id==='JP225'?' (il Nikkei CFTC è fermo da marzo 2026)':''}.</p>`
      :cot.error?`<p class="data-note">${esc(cot.error)}</p>`
      :`<div class="inst-kv"><span>Speculatori (non-commercial)</span><b style="color:${cot.bias==='long'?'var(--green)':cot.bias==='short'?'var(--red)':'var(--dim)'}">${cot.net>0?'+':''}${Number(cot.net).toLocaleString('it-IT')} · ${num(cot.net_pct_oi,1)}% OI · ${esc(cot.bias)}</b></div>
         <div class="inst-kv"><span>Variazione settimana</span><b>${cot.week_change==null?'—':(cot.week_change>0?'+':'')+Number(cot.week_change).toLocaleString('it-IT')}</b></div>
         <p class="data-note">${esc(cot.market)} · report ${esc(cot.report_date)}${cot.inverted?' · segno invertito (il future è sulla valuta estera)':''}${cot.stale?' · ⚠ dato vecchio':''}</p>`;
    card.innerHTML=`<div class="inst-head"><div><span class="nb-lbl">Scheda strumento</span><h3 id="inst-title">${esc(label)} <small>${esc(p.name||'')}</small></h3>
        <p class="data-note">Broker: ${esc(b.symbol||'—')} · aggiornata ${ago(profiles.generated_at)} · orari = ora broker (UTC+3 estate, +2 inverno)</p></div>${refreshBtn()}</div>
      <p class="data-note inst-job" role="status"></p>
      ${p.error?`<p class="data-note">⚠ ${esc(p.error)}</p>`:''}
      <div class="inst-grid">
        <div class="inst-sec"><h4>Costi reali</h4>
          <div class="inst-kv"><span>Spread mediano 30g</span><b>${num(c.spread_median,d)}</b></div>
          <div class="inst-kv"><span>Spread p90 · ora</span><b>${num(c.spread_p90,d)} · ${num(c.spread_now,d)}</b></div>
          <div class="inst-kv"><span>Costo / ATR H1</span><b style="color:${vcol}">${num(c.cost_pct_atr_h1,1)}%</b></div>
          <p class="data-note" style="color:${vcol}">Costo ${esc(verdict)}</p></div>
        <div class="inst-sec"><h4>Volatilità e orari</h4>
          <div class="inst-kv"><span>ATR(14) D1</span><b>${num(v.atr_d1,d)}</b></div>
          <div class="inst-kv"><span>Range medio giornaliero 90g</span><b>${num(v.adr_pct_90d,2)}%</b></div>
          <div class="inst-kv"><span>Ore più mosse (broker, dalla più ampia)</span><b>${(v.active_hours_broker||[]).map(h=>String(h).padStart(2,'0')+':00').join(' · ')||'—'}</b></div></div>
        <div class="inst-sec"><h4>Correlazioni 90g</h4>
          <p class="data-note">Si muovono insieme</p><div class="inst-chips">${(cr.most_positive||[]).map(chip).join('')||'<span class="data-note">—</span>'}</div>
          <p class="data-note">In direzione opposta</p><div class="inst-chips">${(cr.most_negative||[]).map(chip).join('')||'<span class="data-note">—</span>'}</div></div>
        <div class="inst-sec"><h4>Posizionamento istituzionale (COT)</h4>${cotHtml}</div>
        <div class="inst-sec"><h4>Contratto</h4>
          <div class="inst-kv"><span>Dimensione contratto</span><b>${num(b.contract_size,0)}</b></div>
          <div class="inst-kv"><span>Lotto min · step</span><b>${num(b.volume_min,2)} · ${num(b.volume_step,2)}</b></div>
          <div class="inst-kv"><span>Swap long · short</span><b>${num(b.swap_long,2)} · ${num(b.swap_short,2)}</b></div></div>
        <div class="inst-sec"><h4>News 7 giorni · ${esc([...new Set(ccy)].join('/'))}</h4>
          ${news.length?news.map(e=>`<div class="inst-kv"><span>${esc(new Date(e.time).toLocaleString('it-IT',{weekday:'short',day:'2-digit',hour:'2-digit',minute:'2-digit'}))} · ${esc(e.currency)}</span><b class="${e.impact==='High'?'inst-high':''}">${esc(e.event)}</b></div>`).join(''):'<p class="data-note">Nessun evento High/Medium nei prossimi 7 giorni.</p>'}</div>
        <div class="inst-sec"><h4>Ricerca già fatta</h4>
          <div class="inst-kv"><span>Varianti testate</span><b>${num(r.trials,0)}</b></div>
          ${(r.recent||[]).map(x=>`<p class="data-note">${esc(x.ts)} · ${esc(x.strategy)} — ${esc(x.note)}</p>`).join('')||'<p class="data-note">Nessun test registrato su questo strumento.</p>'}</div>
        <div class="inst-sec"><h4>Le tue note</h4>
          <textarea id="inst-notes" rows="4" maxlength="4000" placeholder="Cosa hai notato su ${esc(label)}: orari, livelli, comportamento alle news…">${esc(notes[id]||'')}</textarea>
          <p class="data-note inst-note-status" role="status"></p></div>
      </div>`;
    wire();
  }
  function refreshBtn(){return '<button type="button" class="inst-refresh" title="Ricalcola le schede sul worker (MT5 + CFTC)">↻ Aggiorna</button>';}
  function wire(){
    card.querySelectorAll('[data-switch]').forEach(el=>el.addEventListener('click',()=>window.switchAsset(el.dataset.switch)));
    card.querySelector('.inst-refresh')?.addEventListener('click',requestRefresh);
    const ta=card.querySelector('#inst-notes');
    if(ta)ta.addEventListener('input',()=>{
      const id=window.activeAsset||'XAU';notes[id]=ta.value;
      const st=card.querySelector('.inst-note-status');if(st)st.textContent='Salvataggio…';
      clearTimeout(noteTimer);noteTimer=setTimeout(async()=>{
        try{localStorage.setItem('tf_inst_notes',JSON.stringify(notes));}catch{}
        const r=await dbSave('save_user_data',{doc_type:'inst_notes',payload:JSON.stringify(notes)});
        if(st)st.textContent=r?.ok?'Salvate sul tuo account':'Salvate su questo dispositivo (sincronizzazione non riuscita)';
      },900);
    });
    if(pendingJob)showJob(pendingJob.text,pendingJob.color);
  }
  function showJob(text,color){pendingJob={text,color};const el=card.querySelector('.inst-job');if(el){el.textContent=text;el.style.color=color||'var(--dim)';}}
  async function requestRefresh(){
    const btn=card.querySelector('.inst-refresh');if(btn)btn.disabled=true;
    try{
      const res=await authFetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(8000),body:JSON.stringify({action:'profile_cmd_push'})});
      const r=await res.json();
      if(!res.ok||!r.ok)throw Error(r.error||'Richiesta non accettata');
      showJob('Aggiornamento richiesto: il worker ricalcola tutte le schede (circa 1 minuto)…');
      const t0=Date.now();
      const timer=setInterval(async()=>{
        const d=await dbLoad('backtest_result_get',{request_id:r.request_id},6000);
        if(d?.status==='done'){clearInterval(timer);showJob('✓ Schede aggiornate','var(--green)');await load(true);render();setTimeout(()=>{pendingJob=null;const el=card.querySelector('.inst-job');if(el)el.textContent='';},6000);}
        else if(d?.status==='failed'){clearInterval(timer);showJob('✗ '+(d.data?.error||'Aggiornamento non riuscito'),'var(--red)');}
        else if(Date.now()-t0>600000){clearInterval(timer);showJob('Ancora in coda: il worker non risulta attivo (riavvia il bot).');}
      },4000);
    }catch(e){showJob('✗ '+e.message,'var(--red)');}
    finally{const b=card.querySelector('.inst-refresh');if(b)b.disabled=false;}
  }
  try{notes=JSON.parse(localStorage.getItem('tf_inst_notes')||'{}')||{};}catch{notes={};}
  window.setInstrumentNotes=n=>{if(n&&typeof n==='object'){notes={...notes,...n};render();}};
  window.renderInstrumentCard=async()=>{render();await load(false);render();};
  render();
  window.instrumentsReady?.then(()=>window.renderInstrumentCard());
  setInterval(()=>{if(!document.hidden)load(true).then(render);},900000);
})();
