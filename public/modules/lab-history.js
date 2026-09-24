// TradeFlow AI — modules/lab-history.js
// Storici MT5 on-demand dal Laboratorio (2026-09-24). La richiesta va in coda (history_cmd_push),
// la esegue scripts/backtest_worker.py sulla macchina con MT5 (avviato insieme al bot) e i file
// restano lì (data/history/), pronti per i backtest lato worker. Qui: stato del worker, form,
// avanzamento della richiesta e indice dei dataset disponibili.
(function(){
  const aside=document.querySelector('#tp-lab .lab-results');
  if(!aside)return;
  const box=document.createElement('section');box.className='lab-block';box.id='lab-hist';
  box.innerHTML=`<h2>Storici MT5</h2>
    <p id="lab-hist-worker" class="data-note" role="status">Stato worker: verifica in corso…</p>
    <div class="lab-fields">
      <label>Strumento<select id="lab-hist-inst"></select></label>
      <label>Timeframe<select id="lab-hist-tf">${['M1','M5','M15','M30','H1','H4','D1'].map(t=>`<option${t==='H1'?' selected':''}>${t}</option>`).join('')}</select></label>
      <label>Periodo<select id="lab-hist-days">${[[30,'1 mese'],[90,'3 mesi'],[180,'6 mesi'],[365,'1 anno'],[730,'2 anni'],[1095,'3 anni'],[1825,'5 anni']].map(([d,l])=>`<option value="${d}"${d===730?' selected':''}>${l}</option>`).join('')}</select></label>
    </div>
    <button type="button" id="lab-hist-go">Scarica da MT5</button>
    <p id="lab-hist-job" class="data-note" role="status"></p>
    <p class="data-note">I file restano sulla macchina del bot (data/history/) per i backtest. MT5 limita le barre (~100.000): su M1/M5 il periodo coperto può essere più corto del richiesto, e viene indicato.</p>
    <div id="lab-hist-list"></div>`;
  aside.querySelector('#lab-result')?.after(box);
  const $=id=>document.getElementById(id);
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let workerSeen=null, polling=null;

  function fillInstruments(){
    const sel=$('lab-hist-inst'), cur=sel.value||window.activeAsset||'XAU';
    sel.replaceChildren(...instrumentList().map(i=>new Option(i.label,i.id)));
    sel.value=instrumentOf(cur)?cur:'XAU';
  }
  function ago(iso){const s=Math.round((Date.now()-Date.parse(iso))/1000);return s<90?`${s}s fa`:s<5400?`${Math.round(s/60)} min fa`:`${Math.round(s/3600)} h fa`;}
  function renderList(history){
    const ds=Object.values(history?.datasets||{}).sort((a,b)=>String(b.fetched_at).localeCompare(String(a.fetched_at)));
    $('lab-hist-list').innerHTML=ds.length?`<table class="lab-hist-table"><thead><tr><th>Strumento</th><th>TF</th><th>Barre</th><th>Periodo</th><th>Scaricato</th></tr></thead><tbody>${
      ds.map(d=>`<tr><td>${esc(d.label||d.instrument)}</td><td>${esc(d.tf)}</td><td>${Number(d.bars).toLocaleString('it-IT')}</td><td>${esc(d.from?.slice(0,10))} → ${esc(d.to?.slice(0,10))}${d.truncated?' <span title="'+esc(d.note||'')+'">⚠</span>':''}</td><td>${esc(ago(d.fetched_at))}</td></tr>`).join('')
    }</tbody></table>`:'<p class="data-note">Nessuno storico scaricato ancora.</p>';
  }
  async function refreshStatus(){
    const d=await dbLoad('worker_status_get',{},6000);
    const st=d?.data; workerSeen=st?.seen_at||null;
    const alive=workerSeen&&Date.now()-Date.parse(workerSeen)<150000;
    const w=$('lab-hist-worker');
    w.textContent=!st?'Worker mai collegato: parte insieme al bot (mt5-bot.py) sulla macchina con MT5.'
      :alive?`Worker attivo${st.host?' su '+st.host:''} · ultimo segnale ${ago(workerSeen)}`
      :`Worker non attivo (ultimo segnale ${ago(workerSeen)}): riavvia il bot, lo riavvia anche lui.`;
    w.style.color=alive?'var(--green)':'var(--dim)';
    renderList(st?.history);
  }
  async function poll(requestId,startedAt){
    const d=await dbLoad('backtest_result_get',{request_id:requestId},6000);
    const job=$('lab-hist-job');
    if(d?.status==='done'){
      const r=d.data||{};
      job.textContent=`✓ ${r.label||r.instrument} ${r.tf}: ${Number(r.bars).toLocaleString('it-IT')} barre, ${r.from} → ${r.to}`+(r.note?` · ⚠ ${r.note}`:'');
      job.style.color='var(--green)'; clearInterval(polling); polling=null; $('lab-hist-go').disabled=false; refreshStatus(); return;
    }
    if(d?.status==='failed'){
      job.textContent='✗ '+(d.data?.error||'Download non riuscito'); job.style.color='var(--red)';
      clearInterval(polling); polling=null; $('lab-hist-go').disabled=false; return;
    }
    const waited=Math.round((Date.now()-startedAt)/1000);
    const alive=workerSeen&&Date.now()-Date.parse(workerSeen)<150000;
    job.style.color='var(--dim)';
    job.textContent=d?.status==='running'?`Download in corso sul worker… (${waited}s)`
      :alive?`In coda, il worker la prende a breve… (${waited}s)`
      :`In coda (${waited}s): il worker non risulta attivo, la richiesta partirà quando riavvii il bot.`;
    if(waited>900){clearInterval(polling);polling=null;$('lab-hist-go').disabled=false;}
  }
  $('lab-hist-go').addEventListener('click',async()=>{
    const btn=$('lab-hist-go'),job=$('lab-hist-job');
    btn.disabled=true; job.style.color='var(--dim)'; job.textContent='Invio richiesta…';
    try{
      const res=await authFetch('/api/db',{method:'POST',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(8000),
        body:JSON.stringify({action:'history_cmd_push',instrument:$('lab-hist-inst').value,tf:$('lab-hist-tf').value,days:Number($('lab-hist-days').value)})});
      const r=await res.json();
      if(!res.ok||!r.ok)throw Error(r.error||'Richiesta non accettata');
      const t0=Date.now(); if(polling)clearInterval(polling);
      polling=setInterval(()=>poll(r.request_id,t0),3000); poll(r.request_id,t0);
    }catch(e){ job.textContent='✗ '+e.message; job.style.color='var(--red)'; btn.disabled=false; }
  });
  fillInstruments(); window.instrumentsReady?.then(fillInstruments);
  // Aggiorna stato/indice quando si apre il Laboratorio e poi ogni 60s mentre è visibile.
  document.querySelector('[data-tab=lab]')?.addEventListener('click',refreshStatus);
  setInterval(()=>{if(document.getElementById('tp-lab')?.classList.contains('on'))refreshStatus();},60000);
})();
