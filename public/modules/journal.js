// TradeFlow AI — modules/journal.js

// ── JOURNAL ────────────────────────────────────────────
const FFIELDS=[
  {id:'f-date',lbl:'DATA',type:'date'},{id:'f-dir',lbl:'DIR.',type:'select',opts:['BUY','SELL']},
  {id:'f-entry',lbl:'ENTRY',ph:'3050.00'},{id:'f-sl',lbl:'SL',ph:'3040.00'},
  {id:'f-tp1',lbl:'TP1',ph:'3065.00'},{id:'f-tp2',lbl:'TP2',ph:'3080.00'},
  {id:'f-result',lbl:'RISULTATO',type:'select',opts:['','WIN','LOSS','BE']},{id:'f-pnl',lbl:'P&L $',ph:'+150'},
  {id:'f-emo',lbl:'EMOZIONE',type:'select',opts:['Neutro','Fiducioso','Ansioso','FOMO','Revenge','Paura','Euforia']},
  {id:'f-err',lbl:'ERRORE',type:'select',opts:['Nessuno','Entry anticipata','SL stretto','TP mancato','Oversize','No confluenze','Revenge','FOMO']},
];
function initForm(){
  const g=document.getElementById('fgrid');g.innerHTML='';
  FFIELDS.forEach(f=>{
    const w=document.createElement('div');w.className='ff';
    const l=document.createElement('label');l.textContent=f.lbl;w.appendChild(l);
    let el;
    if(f.type==='select'){el=document.createElement('select');(f.opts||[]).forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o||'--';el.appendChild(op);});}
    else{el=document.createElement('input');el.type=f.type||'text';if(f.ph)el.placeholder=f.ph;}
    el.id=f.id;w.appendChild(el);g.appendChild(w);
  });
  document.getElementById('f-date').value=new Date().toISOString().slice(0,10);
  document.getElementById('f-notes').value='';
}
function saveEntry(){
  const entry=document.getElementById('f-entry').value;if(!entry)return;
  const e={id:Date.now(),date:document.getElementById('f-date').value,dir:document.getElementById('f-dir').value,entry,sl:document.getElementById('f-sl').value,tp1:document.getElementById('f-tp1').value,tp2:document.getElementById('f-tp2').value,result:document.getElementById('f-result').value,pnl:document.getElementById('f-pnl').value,emo:document.getElementById('f-emo').value,err:document.getElementById('f-err').value,notes:document.getElementById('f-notes').value};
  entries.unshift(e);S.set(K.j,entries);
  const w=entries.filter(x=>x.result==='WIN').length;P.winRate=Math.round(w/entries.length*100);S.set(K.p,P);
  document.getElementById('tform').classList.remove('on');renderJournal();updateHdr();
}
document.getElementById('btn-new').onclick=()=>{const f=document.getElementById('tform');f.classList.toggle('on');if(f.classList.contains('on'))initForm();};
document.getElementById('btn-save').onclick=saveEntry;
document.getElementById('btn-fcan').onclick=()=>document.getElementById('tform').classList.remove('on');

// CSV Import
document.getElementById('btn-import').onclick=()=>openOvl('csvsheet');
document.getElementById('btn-csvc').onclick=()=>closeOvl('csvsheet');
document.getElementById('csv-drop').onclick=()=>document.getElementById('csv-file').click();
document.getElementById('csv-file').onchange=async e=>{const f=e.target.files?.[0];if(!f)return;document.getElementById('csv-text').value=(await f.text()).slice(0,3000);e.target.value='';};
document.getElementById('btn-csv-go').onclick=async()=>{
  const text=document.getElementById('csv-text').value.trim();if(!text)return;
  const btn=document.getElementById('btn-csv-go');btn.textContent='⏳...';btn.disabled=true;
  try{
    const reply=await api([{role:'user',content:`Analizza storico trade:\n\n${text.slice(0,2000)}\n\nIgnora Balance/Credit/Deposit/Withdrawal. Solo trade reali. Statistiche, pattern errori, 3 azioni concrete.`}],
      `Sei TradeFlow AI Journal Coach. Italiano. Profilo: ${P.name}.`);
    closeOvl('csvsheet');showAiResult(reply);autoLearn(reply);
  }catch(e){alert('Errore: '+e.message);}
  btn.textContent='🧠 Analizza con AI';btn.disabled=false;
};

// Screenshot MT5
let scrImgData=null;
document.getElementById('btn-screen').onclick=()=>openOvl('scrsheet');
document.getElementById('btn-scrc').onclick=()=>{closeOvl('scrsheet');scrImgData=null;document.getElementById('scr-prev').style.display='none';document.getElementById('btn-scr-go').style.display='none';};
document.getElementById('scr-drop').onclick=()=>document.getElementById('scr-file').click();
document.getElementById('scr-file').onchange=async e=>{
  const f=e.target.files?.[0];if(!f)return;
  scrImgData=await compress(f);
  document.getElementById('scr-img').src=scrImgData.dataUrl;
  document.getElementById('scr-prev').style.display='block';
  document.getElementById('btn-scr-go').style.display='block';
  e.target.value='';
};
document.getElementById('btn-scr-go').onclick=async()=>{
  if(!scrImgData?.b64)return;
  const btn=document.getElementById('btn-scr-go');btn.textContent='⏳...';btn.disabled=true;
  try{
    const reply=await api([{role:'user',content:[{type:'image',source:{type:'base64',media_type:'image/jpeg',data:scrImgData.b64}},{type:'text',text:'Screenshot storico MT5. REGOLA: ignora completamente Balance, Credit, Deposit, Withdrawal, Bonus, EXP, SC-CC. Leggi SOLO trade reali su strumenti finanziari con direzione buy/sell. Per ogni trade reale: strumento, lotti, entry→exit, P&L. Calcola statistiche SOLO sui trade reali: win rate, avg RR, profitto. Pattern errori e 3 azioni concrete.'}]}],
      `Sei TradeFlow AI Coach. Italiano. Profilo: ${P.name}.`);
    closeOvl('scrsheet');scrImgData=null;showAiResult(reply);autoLearn(reply);
  }catch(e){alert('Errore: '+e.message);}
  btn.textContent='🧠 Analizza Trade Chiusi';btn.disabled=false;
};

function showAiResult(reply){
  const box=document.getElementById('aibox');const aic=document.getElementById('aic');
  aic.innerHTML='';aic.appendChild(md(reply));box.style.display='block';
  document.getElementById('jp').scrollTop=0;
}

// ── REPORT & COACHING ────────────────────────────────────
async function generateReport(period){
  if(!entries.length){alert('Nessun trade nel journal.');return;}
  const btn=document.getElementById(`btn-report-${period}`);
  if(btn){btn.textContent='⏳...';btn.disabled=true;}
  try{
    const mem=tradeMemory.summary||'';
    const r=await fetch('/api/report',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({type:'report',entries,profile:P,period,memory:mem})
    });
    const d=await r.json();
    if(!d.ok)throw new Error(d.error||'Errore report');
    showAiResult(d.report);
    // Auto-save to memory
    tradeMemory.summary=d.report.slice(0,500);
    tradeMemory.lastReport={period,date:new Date().toISOString(),stats:d.stats};
    S.set(K.mem,tradeMemory);
    updateMemoryInfo();
  }catch(e){alert('Errore: '+e.message);}
  if(btn){btn.textContent={day:'📋 Oggi',week:'📋 Settimana',month:'📋 Mese'}[period];btn.disabled=false;}
}

async function generateProgress(){
  if(!entries.length){alert('Nessun trade nel journal.');return;}
  const btn=document.getElementById('btn-progress');
  if(btn){btn.textContent='⏳...';btn.disabled=true;}
  try{
    const mem=tradeMemory.summary||'';
    const r=await fetch('/api/report',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({type:'progress',entries:entries.slice(0,30),profile:P,period:'all',memory:mem})
    });
    const d=await r.json();
    if(!d.ok)throw new Error(d.error||'Errore');
    showAiResult(d.report);
    // Update progress badge
    const badge=document.getElementById('progress-badge');
    if(badge){badge.style.display='block';badge.textContent='📈 Progressi aggiornati — '+new Date().toLocaleDateString('it-IT');}
  }catch(e){alert('Errore: '+e.message);}
  if(btn){btn.textContent='📈 Progressi';btn.disabled=false;}
}

async function coachSingleTrade(entry){
  try{
    const r=await fetch('/api/report',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({type:'coaching',entries:[entry],profile:P,period:'single'})
    });
    const d=await r.json();
    if(!d.ok)return null;
    return d.report;
  }catch(e){return null;}
}

function saveAnalysisMemory(){
  const aic=document.getElementById('aic');
  if(!aic||!aic.textContent)return;
  const entry={date:new Date().toISOString(),text:aic.textContent.slice(0,600)};
  analysisMemory.entries=[entry,...(analysisMemory.entries||[])].slice(0,20);
  S.set(K.amem,analysisMemory);
  alert('✅ Analisi salvata nella memoria operatività.');
}

function resetMemory(type){
  const label=type==='week'?'settimana':'mese';
  if(!confirm(`Reset memoria analisi operatività (${label})?`))return;
  analysisMemory={entries:[],lastReset:new Date().toISOString()};
  S.set(K.amem,analysisMemory);
  tradeMemory.summary='';S.set(K.mem,tradeMemory);
  updateMemoryInfo();
  alert('✅ Memoria resettata.');
}

function updateMemoryInfo(){
  const el=document.getElementById('memory-date');
  if(!el)return;
  const count=(analysisMemory.entries||[]).length;
  const last=tradeMemory.lastReset||tradeMemory.lastReport?.date;
  el.textContent=`Memoria: ${count} analisi salvate${last?' · ultimo reset '+new Date(last).toLocaleDateString('it-IT'):''}`;
}

// ── MYFXBOOK IMPORT TO JOURNAL ────────────────────────────
async function importMfxToJournal(accountId){
  if(!mfxSession)return;
  const btn=document.querySelector(`[onclick="importMfxToJournal('${accountId}')"]`);
  if(btn){btn.textContent='⏳ Importazione...';btn.disabled=true;}
  try{
    const r=await fetch('/api/myfxbook',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({action:'history',session:mfxSession.session,accountId})});
    const d=await r.json();
    if(!d.history?.length)throw new Error('Nessun trade trovato');
    // Debug: log raw history to understand structure
    const rawSample=d.history?.[0];
    console.log('MFX raw trade sample:', JSON.stringify(rawSample));
    console.log('MFX total history:', d.history?.length);

    // MyFxBook returns 'action' field: "Buy"/"Sell" (not 'type')
    // Also filter out non-trade entries
    const SKIP_TYPES=['deposit','withdrawal','credit','balance','bonus','rebate','commission'];
    const realTrades=(d.history||[]).filter(t=>{
      // Try both 'action' and 'type' fields
      const action=String(t.action||t.type||t.actionType||'').toLowerCase();
      if(!action) return false;
      if(SKIP_TYPES.some(s=>action.includes(s))) return false;
      // Accept buy/sell in any form
      return action.includes('buy')||action.includes('sell')||action==='0'||action==='1';
    });

    console.log('MFX real trades after filter:', realTrades.length);

    if(!realTrades.length){
      // Show all available data to debug
      const types=[...new Set((d.history||[]).map(t=>String(t.action||t.type||'unknown')))];
      alert('Nessun trade trovato. Tipi trovati: '+types.slice(0,10).join(', ')+'. Controlla la console per dettagli.');
      if(btn){btn.textContent='📥 Importa Trade al Journal';btn.disabled=false;}
      return;
    }

    const existingKeys=new Set(entries.map(e=>`${e.date}_${e.dir}_${parseFloat(e.entry).toFixed(2)}`));
    let imported=0;
    const newEntries=[];

    for(const t of realTrades.slice(0,100)){
      // Handle both date formats: "2024.01.15 10:30" and "2024-01-15 10:30"
      const rawDate=t.openTime||t.open_time||t.openDate||'';
      const openDate=rawDate?String(rawDate).replace(/\./g,'-').slice(0,10):new Date().toISOString().slice(0,10);

      // Direction from action or type
      const action=String(t.action||t.type||'').toLowerCase();
      const dir=action.includes('sell')||action==='1'?'SELL':'BUY';

      const entryPrice=parseFloat(t.openPrice||t.open_price||t.openRate||0);
      const closePrice=parseFloat(t.closePrice||t.close_price||t.closeRate||0);
      const pnl=parseFloat(t.profit||t.pnl||0);
      const lots=parseFloat(t.size||t.lots||t.volume||0);
      const sym=t.symbol||t.instrument||'XAUUSD';

      // Compute SL/TP if available
      const sl=parseFloat(t.tp||t.stopLoss||0)||'';
      const tp1=parseFloat(t.sl||t.takeProfit||0)||'';

      const key=`${openDate}_${dir}_${entryPrice.toFixed(2)}`;
      if(existingKeys.has(key)) continue;
      existingKeys.add(key);

      // Map emotion from MFX data if available
      const rr=entryPrice&&closePrice&&sl?Math.abs(closePrice-entryPrice)/Math.abs(entryPrice-(sl||entryPrice)):0;

      newEntries.push({
        id:Date.now()+imported+Math.floor(Math.random()*1000),
        date:openDate,
        dir,
        entry:entryPrice,
        sl:sl||'',
        tp1:tp1||'',
        tp2:'',
        result:pnl>0?'WIN':pnl<0?'LOSS':'BE',
        pnl:pnl.toFixed(2),
        emo:'Neutro',
        err:'Nessuno',
        notes:`${sym} ${lots}lot | E:${entryPrice} → C:${closePrice} | RR:${rr.toFixed(2)}`,
        source:'myfxbook'
      });
      imported++;
    }

    if(imported>0){
      entries=[...newEntries,...entries];
      S.set(K.j,entries);
      // Update win rate
      const wins=entries.filter(x=>x.result==='WIN').length;
      if(entries.length>0){P.winRate=Math.round(wins/entries.length*100);S.set(K.p,P);}
      alert('✅ '+imported+' trade importati nel Journal da MyFxBook!');
      switchTab('journal');
      renderJournal();
    }else{
      alert('Tutti i '+realTrades.length+' trade sono già presenti nel Journal (controllo per data+direzione+prezzo).');
    }
  }catch(e){alert('Errore importazione: '+e.message);}
  if(btn){btn.textContent='📥 Importa Trade al Journal';btn.disabled=false;}
}

document.getElementById('btn-analyze').onclick=async()=>{
  if(!entries.length)return;
  const btn=document.getElementById('btn-analyze');btn.textContent='⏳...';btn.disabled=true;
  try{
    const mem=analysisMemory.entries?.slice(0,3).map(e=>`[${e.date?.slice(0,10)}] ${e.text}`).join('\n')||'';
    const memCtx=mem?`\nMEMORIA ANALISI PRECEDENTE:\n${mem}`:'';
    const sum=entries.slice(0,25).map(e=>`${e.date}|${e.dir}|E:${e.entry} SL:${e.sl}|${e.result||'?'}|${e.pnl}$|${e.emo}|${e.err}`).join('\n');
    const reply=await api([{role:'user',content:`Analizza operatività XAU/USD di ${P.name}:\n${sum}\n${memCtx}\nStatistiche, aree di sviluppo (non errori), 3 azioni concrete, Score Disciplina X/10.`}],
      `Sei TradeFlow AI Coach. Italiano. Tono costruttivo. Aree noto sviluppo: ${P.errors.join(',')}.`);
    showAiResult(reply);autoLearn(reply);
  }catch(e){alert('Errore: '+e.message);}
  btn.textContent='🧠 Analisi';btn.disabled=false;
};

// Wire report buttons
document.getElementById('btn-report-day').onclick=()=>generateReport('day');
document.getElementById('btn-report-week').onclick=()=>generateReport('week');
document.getElementById('btn-report-month').onclick=()=>generateReport('month');
document.getElementById('btn-progress').onclick=generateProgress;
document.getElementById('btn-myfxb-j').onclick=()=>switchTab('myfx');

function renderJournal(){
  const wins=entries.filter(e=>e.result==='WIN').length;
  const wr=entries.length?Math.round(wins/entries.length*100):0;
  const pnl=entries.reduce((s,e)=>s+(parseFloat(e.pnl)||0),0);
  const stats=[{l:'Trade',v:entries.length,c:'var(--g)'},{l:'Win%',v:`${wr}%`,c:wr>=50?'var(--green)':'var(--red)'},{l:'P&L',v:`${pnl>=0?'+':''}${pnl.toFixed(0)}$`,c:pnl>=0?'var(--green)':'var(--red)'},{l:'Sess.',v:P.sessions||0,c:'var(--dim)'}];
  document.getElementById('sgrid').innerHTML=stats.map(s=>`<div class="sc"><div class="sv" style="color:${s.c}">${s.v}</div><div class="sl">${s.l}</div></div>`).join('');
  const eb=document.getElementById('ebox');const et=document.getElementById('etags');
  if(P.errors?.length){eb.style.display='block';et.innerHTML=P.errors.map(e=>`<span class="etag" style="background:#ffca2810;border-color:#ffca2830;color:var(--yellow)">${e}</span>`).join('');}else{eb.style.display='none';}
  const list=document.getElementById('elist');
  if(!entries.length){list.innerHTML='<div class="empt">Nessun trade loggato.</div>';return;}
  list.innerHTML='';
  entries.forEach(e=>{
    const bc=e.result==='WIN'?'#00e67618':e.result==='LOSS'?'#ff475718':'var(--border)';
    const ac=e.result==='WIN'?'var(--green)':e.result==='LOSS'?'var(--red)':'#444';
    const pv=parseFloat(e.pnl)||0;
    const d=document.createElement('div');d.className='ec';d.style.cssText=`border:1px solid ${bc};border-left:3px solid ${ac}`;
    const savedCoaching=tradeMemory.entries?.[e.id]||'';
    d.innerHTML=`<div class="etop"><div class="etgs"><span class="edate">${e.date}</span><span class="edir ${e.dir==='BUY'?'buy':'sell'}">${e.dir}</span>${e.result?`<span class="eres ${e.result.toLowerCase()}">${e.result}</span>`:''}</div><div class="eright">${e.pnl?`<span class="epnl ${pv>=0?'p':'n'}">${pv>=0?'+':''}${e.pnl}$</span>`:''}<button class="bcoach" style="background:none;border:1px solid var(--border);border-radius:4px;padding:1px 6px;color:var(--g);font-size:11px;cursor:pointer" title="Coaching AI">💡</button><button class="bdel" data-id="${e.id}">✕</button></div></div><div class="elvl">E:${e.entry} · SL:${e.sl} · TP1:${e.tp1} · TP2:${e.tp2}</div><div class="ebdg">${e.emo!=='Neutro'?`<span class="bemo">${e.emo}</span>`:''}${e.err&&e.err!=='Nessuno'?`<span class="berr">💡 ${e.err}</span>`:''}</div>${savedCoaching?`<div class="trade-coach" style="margin-top:6px;padding:6px 8px;background:#0c0f18;border:1px solid #c8a96e22;border-radius:6px;font-size:11px;color:var(--dim);line-height:1.6">💡 ${savedCoaching}</div>`:''}`;
    d.querySelector('.bdel').onclick=()=>{entries=entries.filter(x=>x.id!==e.id);S.set(K.j,entries);renderJournal();};
    // Coaching button
    const cbtn=d.querySelector('.bcoach');
    if(cbtn)cbtn.onclick=async()=>{
      cbtn.textContent='⏳';cbtn.disabled=true;
      const coaching=await coachSingleTrade(e);
      if(coaching){
        // Show coaching inline
        const existing=d.querySelector('.trade-coach');
        if(existing)existing.remove();
        const div=document.createElement('div');
        div.className='trade-coach';
        div.style.cssText='margin-top:6px;padding:6px 8px;background:#0c0f18;border:1px solid #c8a96e22;border-radius:6px;font-size:11px;color:var(--dim);line-height:1.6';
        div.textContent='💡 '+coaching;
        d.appendChild(div);
        // Save to trade memory
        tradeMemory.entries=tradeMemory.entries||{};
        tradeMemory.entries[e.id]=coaching;
        S.set(K.mem,tradeMemory);
      }
      cbtn.textContent='💡';cbtn.disabled=false;
    };
    list.appendChild(d);
  });
}
