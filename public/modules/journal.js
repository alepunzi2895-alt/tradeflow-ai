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
  const e={
    id:'tf_'+Date.now(),
    date:document.getElementById('f-date').value,
    dir:document.getElementById('f-dir').value,
    entry,
    sl:document.getElementById('f-sl').value,
    tp1:document.getElementById('f-tp1').value,
    tp2:document.getElementById('f-tp2').value,
    result:document.getElementById('f-result').value,
    pnl:document.getElementById('f-pnl').value,
    emo:document.getElementById('f-emo').value,
    err:document.getElementById('f-err').value,
    notes:document.getElementById('f-notes').value,
    symbol:window.activeAsset==='US30'?'US30':(window.activeAsset||'XAU')+'USD',
  };
  entries.unshift(e);S.set(K.j,entries);
  const w=entries.filter(x=>x.result==='WIN').length;P.winRate=Math.round(w/entries.length*100);S.set(K.p,P);
  document.getElementById('tform').classList.remove('on');renderJournal();updateHdr();
  // Persist to Turso async
  dbSave('save_trade',{
    id:e.id,
    symbol:e.symbol,
    direction:e.dir,
    entry_price:parseFloat(e.entry)||null,
    sl:parseFloat(e.sl)||null,
    tp1:parseFloat(e.tp1)||null,
    tp2:parseFloat(e.tp2)||null,
    result:e.result,
    pnl:parseFloat(e.pnl)||0,
    emotion:e.emo,
    mistake:e.err,
    notes:e.notes,
    trade_date:e.date,
  }).catch(()=>{});
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

// Errore non bloccante (mai alert() — un popup nativo facile da chiudere senza leggere fa
// sembrare "non funziona" un bottone che in realtà ha solo fallito la chiamata AI).
function showAiError(msg){
  const box=document.getElementById('aibox');const aic=document.getElementById('aic');
  aic.innerHTML='';
  const d=document.createElement('div');
  d.style.cssText='color:#FF8A8A;font-size:12px;line-height:1.6;padding:4px 0';
  d.textContent='⚠️ '+msg;
  aic.appendChild(d);box.style.display='block';
  document.getElementById('jp').scrollTop=0;
}

// Fetch verso /api/report con parsing sicuro: se la function Vercel va in timeout/errore
// restituisce spesso HTML non-JSON — leggere come testo prima ed evitare che r.json() lanci
// un errore criptico. Il body grezzo va in console per poter diagnosticare senza indovinare.
async function fetchReport(body){
  const r=await authFetch('/api/report',{signal:AbortSignal.timeout(15000),method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const raw=await r.text();
  let d;
  try{d=JSON.parse(raw);}
  catch(parseErr){
    console.error('[report] risposta non-JSON (possibile timeout Vercel):',raw.slice(0,500));
    throw new Error('Risposta del server non valida (probabile timeout) — riprova tra qualche secondo.');
  }
  if(!d.ok)throw new Error(d.error||'Errore report');
  return d;
}

// ── REPORT & COACHING ────────────────────────────────────
async function generateReport(period){
  if(!entries.length){alert('Nessun trade nel journal.');return;}
  const btn=document.getElementById(`btn-report-${period}`);
  if(btn){btn.textContent='⏳...';btn.disabled=true;}
  try{
    const mem=tradeMemory.summary||'';
    const d=await fetchReport({type:'report',entries:journalRows(),profile:P,period,memory:mem,asset:window.activeAsset||'XAU'});
    showAiResult(d.report);
    // Auto-save to memory
    tradeMemory.summary=d.report.slice(0,500);
    tradeMemory.lastReport={period,date:new Date().toISOString(),stats:d.stats};
    S.set(K.mem,tradeMemory);
    window.dbSaveUserData&&window.dbSaveUserData('mem',tradeMemory);
    updateMemoryInfo();
  }catch(e){showAiError(e.message);}
  if(btn){btn.textContent={day:'📋 Oggi',week:'📋 Settimana',month:'📋 Mese'}[period];btn.disabled=false;}
}

function generateProgress(){
  const valid=entries.map(e=>({...e,date:mfxNormalizeDate(e.date)})).filter(e=>e.date).sort((a,b)=>a.date.localeCompare(b.date));
  if(!valid.length){showAiError('Importa o registra almeno un trade per vedere i progressi.');return;}
  const today=new Date(); today.setHours(0,0,0,0);
  const boundary=new Date(today); boundary.setDate(boundary.getDate()-29);
  const previous=new Date(boundary); previous.setDate(previous.getDate()-30);
  const key=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  const stats=rows=>({n:rows.length,pnl:rows.reduce((n,e)=>n+(Number(e.pnl)||0),0),wr:rows.length?100*rows.filter(e=>e.result==='WIN').length/rows.length:0});
  const now=stats(valid.filter(e=>e.date>=key(boundary)&&e.date<=key(today)));
  const before=stats(valid.filter(e=>e.date>=key(previous)&&e.date<key(boundary)));
  showAiResult(`### Progressi · ultimi 30 giorni

${now.n} trade · P&L ${now.pnl.toFixed(2)} · Win rate ${now.wr.toFixed(1)}%

### 30 giorni precedenti

${before.n} trade · P&L ${before.pnl.toFixed(2)} · Win rate ${before.wr.toFixed(1)}%

${now.n&&before.n ? `Variazione P&L: ${(now.pnl-before.pnl).toFixed(2)}. Variazione win rate: ${(now.wr-before.wr).toFixed(1)} punti percentuali.` : 'Confronto incompleto: mancano trade in uno dei due periodi.'}

Statistiche calcolate dai trade registrati, senza analisi AI.`);
}
let journalPeriod='all';
function journalRows(){
  const now=new Date();now.setHours(0,0,0,0);
  const start=new Date(now);start.setDate(start.getDate()-({day:0,week:6,month:29}[journalPeriod]||0));
  const key=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  return entries.map(e=>({...e,date:mfxNormalizeDate(e.date)})).filter(e=>journalPeriod==='all'||(e.date>=key(start)&&e.date<=key(now))).sort((a,b)=>b.date.localeCompare(a.date));
}
function setJournalPeriod(period){
  journalPeriod=period;renderJournal();
  document.querySelectorAll('[data-journal-period]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.journalPeriod===period)));
}

async function coachSingleTrade(entry){
  try{
    const r=await authFetch('/api/report',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({type:'coaching',entries:[entry],profile:P,period:'single',asset:window.activeAsset||'XAU'})
    });
    const d=await r.json();
    if(!d.ok)return null;
    return d.report;
  }catch(e){return null;}
}

// Salva un testo di analisi nella memoria operatività (usata come contesto nelle analisi successive,
// vedi memCtx in buildSys()/btn-analyze/analyzeMfxAccount). Silenziosa: nessun alert, pensata per essere
// chiamata in automatico oltre che dal bottone manuale "💾 Salva in memoria".
function pushAnalysisMemory(text){
  if(!text)return;
  const entry={date:new Date().toISOString(),text:String(text).slice(0,600)};
  analysisMemory.entries=[entry,...(analysisMemory.entries||[])].slice(0,20);
  S.set(K.amem,analysisMemory);
  window.dbSaveUserData&&window.dbSaveUserData('amem',analysisMemory);
  updateMemoryInfo();
}

function saveAnalysisMemory(){
  const aic=document.getElementById('aic');
  if(!aic||!aic.textContent)return;
  pushAnalysisMemory(aic.textContent);
  alert('✅ Analisi salvata nella memoria operatività.');
}

function resetMemory(type){
  const label=type==='week'?'settimana':'mese';
  if(!confirm(`Reset memoria analisi operatività (${label})?`))return;
  analysisMemory={entries:[],lastReset:new Date().toISOString()};
  S.set(K.amem,analysisMemory);
  window.dbSaveUserData&&window.dbSaveUserData('amem',analysisMemory);
  tradeMemory.summary='';S.set(K.mem,tradeMemory);
  window.dbSaveUserData&&window.dbSaveUserData('mem',tradeMemory);
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

// MyFxBook get-history restituisce openTime in formato slash US "MM/DD/YYYY HH:MM" (non
// punteggiato come MT4/MT5) — normalizzare SEMPRE a ISO "YYYY-MM-DD" prima di salvarlo come
// entries[].date, altrimenti il confronto di stringa dei filtri Oggi/Settimana/Mese in
// api/report.js (assume ISO) fallisce silenziosamente per ogni trade importato.
function mfxNormalizeDate(raw){
  const s=String(raw||'').trim();
  if(!s) return '';
  let m=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/); // MM/DD/YYYY (reale formato MyFxBook)
  if(m){ const [,mo,d,y]=m; return `${y}-${mo.padStart(2,'0')}-${d.padStart(2,'0')}`; }
  m=s.match(/^(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})/); // YYYY.MM.DD (MT4/MT5) o già ISO
  if(m){ const [,y,mo,d]=m; return `${y}-${mo.padStart(2,'0')}-${d.padStart(2,'0')}`; }
  const parsed=new Date(s);
  if(!isNaN(parsed.getTime())) return parsed.toISOString().slice(0,10);
  return '';
}

// ── MYFXBOOK IMPORT TO JOURNAL ────────────────────────────
async function importMfxToJournal(accountId){
  if(!mfxSession)return;
  const btn=document.querySelector(`[onclick="importMfxToJournal('${accountId}')"]`);
  if(btn){btn.textContent='⏳ Importazione...';btn.disabled=true;}
  try{
    const d=await mfxApiCall('history',{accountId});
    if(d.error){
      alert('❌ '+(d.message||'Sessione MyFxBook scaduta. Riconnettiti dal tab MFX.'));
      if(btn){btn.textContent='📥 Importa Trade al Journal';btn.disabled=false;}
      return;
    }
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

    // L'import deve riflettere SOLO i trade di questo account MyFxBook: qualunque trade importato
    // in precedenza (da questo o da un altro account collegato) viene svuotato prima di reimportare,
    // altrimenti si accumulano doppioni/trade di account diversi nel Journal.
    const staleCount=entries.filter(e=>String(e.source||'').startsWith('myfxbook')).length;
    const retainedEntries=entries.filter(e=>!String(e.source||'').startsWith('myfxbook'));

    if(!realTrades.length){
      S.set(K.j,entries);
      const wins=entries.filter(x=>x.result==='WIN').length;
      P.winRate=entries.length?Math.round(wins/entries.length*100):null;S.set(K.p,P);
      renderJournal();updateHdr();
      const types=[...new Set((d.history||[]).map(t=>String(t.action||t.type||'unknown')))];
      alert(`Nessun trade reale trovato su questo account MyFxBook (tipi presenti: ${types.slice(0,10).join(', ')||'nessuno'}).`);
      if(btn){btn.textContent='📥 Importa Trade al Journal';btn.disabled=false;}
      return;
    }

    const existingKeys=new Set();
    let imported=0;
    const newEntries=[];

    for(const t of realTrades.slice(0,5000)){
      const rawDate=t.openTime||t.open_time||t.openDate||'';
      const openDate=mfxNormalizeDate(rawDate);

      // Direction from action or type
      const action=String(t.action||t.type||'').toLowerCase();
      const dir=action.includes('sell')||action==='1'?'SELL':'BUY';

      const entryPrice=parseFloat(t.openPrice||t.open_price||t.openRate||0);
      const closePrice=parseFloat(t.closePrice||t.close_price||t.closeRate||0);
      const pnl=parseFloat(t.profit||t.pnl||0);
      const lots=parseFloat(t.size||t.lots||t.volume||0);
      const sym=t.symbol||t.instrument||((window.activeAsset||'XAU')+'USD');

      // Compute SL/TP if available
      const sl=parseFloat(t.sl||t.stopLoss||0)||'';
      const tp1=parseFloat(t.tp||t.takeProfit||0)||'';

      const externalId=t.id||t.orderId||t.ticket||[sym,rawDate,t.closeTime||t.close_time,dir,entryPrice,closePrice,lots,pnl].join('|');
      const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(String(externalId)));
      const key=`mfx:${window.userId}:${accountId}:`+[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');
      if(existingKeys.has(key)) continue;
      existingKeys.add(key);

      // Map emotion from MFX data if available
      const rr=entryPrice&&closePrice&&sl?Math.abs(closePrice-entryPrice)/Math.abs(entryPrice-(sl||entryPrice)):0;

      newEntries.push({
        id:key,
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
        symbol:sym,
        source:'myfxbook:'+accountId,
        exit:closePrice,size:lots,
        mfxAccountId:accountId
      });
      imported++;
    }

    if(imported>0){
      const saved=await dbSave('replace_imported_trades',{account_id:accountId,trades:newEntries.map(ne=>({
        id:ne.id,symbol:ne.symbol,direction:ne.dir,entry_price:ne.entry,exit_price:ne.exit,size:ne.size,
        sl:parseFloat(ne.sl)||null,tp1:parseFloat(ne.tp1)||null,tp2:parseFloat(ne.tp2)||null,
        result:ne.result,pnl:parseFloat(ne.pnl)||0,emotion:ne.emo,mistake:ne.err,notes:ne.notes,trade_date:ne.date}))});
      if(!saved.ok)throw Error(saved.error);
      entries=[...newEntries,...retainedEntries];
      S.set(K.j,entries);
      // Update win rate
      const wins=entries.filter(x=>x.result==='WIN').length;
      if(entries.length>0){P.winRate=Math.round(wins/entries.length*100);S.set(K.p,P);}
      alert('✅ '+imported+' trade importati nel Journal da MyFxBook!'+(staleCount?` (${staleCount} vecchi trade MyFxBook sostituiti)`:''));
      switchTab('journal');
      renderJournal();
    }else{
      // Anche a 0 nuovi importati, i vecchi trade MyFxBook rimossi sopra vanno comunque persistiti
      S.set(K.j,entries);
      const wins=entries.filter(x=>x.result==='WIN').length;
      P.winRate=entries.length?Math.round(wins/entries.length*100):null;S.set(K.p,P);
      renderJournal();updateHdr();
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
    const sum=entries.slice(0,25).map(e=>`${e.date}|${escapeHtml(e.dir)}|E:${escapeHtml(e.entry)} SL:${escapeHtml(e.sl)}|${e.result||'?'}|${escapeHtml(e.pnl)}$|${e.emo}|${e.err}`).join('\n');
    const reply=await api([{role:'user',content:`Analizza operatività ${window.activeAsset||'XAU'}/USD di ${P.name}:\n${sum}\n${memCtx}\nUsa SOLO i numeri riportati sopra. Statistiche, aree di sviluppo (non errori) con evidenza numerica, 3 azioni concrete e specifiche da applicare da subito, Score Disciplina X/10 motivato.`}],
      `Sei TradeFlow AI Coach. Italiano. Tono costruttivo ma diretto. Aree noto sviluppo: ${P.errors.join(',')}.`);
    showAiResult(reply);autoLearn(reply);pushAnalysisMemory(reply);
  }catch(e){alert('Errore: '+e.message);}
  btn.textContent='🧠 Analisi';btn.disabled=false;
};

// Wire report buttons
document.getElementById('btn-report-day').onclick=()=>setJournalPeriod('day');
document.getElementById('btn-report-week').onclick=()=>setJournalPeriod('week');
document.getElementById('btn-report-month').onclick=()=>setJournalPeriod('month');
document.getElementById('btn-progress').onclick=generateProgress;
document.getElementById('btn-myfxb-j').onclick=()=>switchTab('myfx');

function renderJournal(){
  const visible=journalRows();
  const wins=visible.filter(e=>e.result==='WIN').length;
  const wr=visible.length?Math.round(wins/visible.length*100):0;
  const pnl=visible.reduce((s,e)=>s+(parseFloat(e.pnl)||0),0);

  const stats=[
    {l:'Win Rate',v:`${wr}%`,c:wr>=50?'var(--green)':'var(--red)'},
    {l:'P&L Totale',v:`${pnl>=0?'+':''}${pnl.toFixed(0)}$`,c:pnl>=0?'var(--green)':'var(--red)'},
    {l:'Trade Totali',v:visible.length,c:'#fff'},
    {l:'Sessioni',v:P.sessions||0,c:'var(--dim)'}
  ];

  document.getElementById('sgrid').innerHTML=stats.map(s=>`
    <div class="sc">
      <div class="sv" style="color:${s.c}">${s.v}</div>
      <div class="sl">${s.l}</div>
    </div>
  `).join('');

  const eb=document.getElementById('ebox');const et=document.getElementById('etags');
  if(P.errors?.length){
    eb.style.display='block';
    et.innerHTML=P.errors.map(e=>`<span class="etag">${escapeHtml(e)}</span>`).join('');
  }else{eb.style.display='none';}

  const list=document.getElementById('elist');
  if(!visible.length){list.innerHTML='<div style="text-align:center;padding:40px;color:var(--dim);font-size:12px">Nessun trade in questo periodo.</div>';return;}
  list.innerHTML='';

  visible.forEach(e=>{
    const resClass = e.result ? e.result.toLowerCase() : '';
    const d=document.createElement('div');
    d.className=`ec ${resClass}`;

    const pv=parseFloat(e.pnl)||0;
    const dateStr = new Date(e.date).toLocaleDateString('it-IT', {day:'2-digit', month:'short'});

    d.innerHTML=`
      <div class="etop">
        <div>
          <div class="edate">${dateStr} · ${escapeHtml(e.symbol || 'XAUUSD')}</div>
          <div style="display:flex;gap:6px;margin-top:4px">
            <span class="etag" style="background:${e.dir==='BUY'?'rgba(0,230,118,0.1)':'rgba(255,71,87,0.1)'};color:${e.dir==='BUY'?'var(--green)':'var(--red)'}">${escapeHtml(e.dir)}</span>
            ${e.result ? `<span class="etag" style="text-transform:uppercase">${escapeHtml(e.result)}</span>` : ''}
          </div>
        </div>
        <div style="text-align:right">
          <div class="epnl" style="color:${pv>=0?'var(--green)':'var(--red)'}">${pv>=0?'+':''}${escapeHtml(e.pnl)}$</div>
          <div style="display:flex;gap:8px;margin-top:6px;justify-content:flex-end">
            <button class="bcoach" style="background:none;border:none;color:var(--g);font-size:14px;cursor:pointer" title="Coaching AI">💡</button>
            <button class="bdel" data-id="${escapeHtml(e.id)}" style="background:none;border:none;color:var(--dim);font-size:14px;cursor:pointer">✕</button>
          </div>
        </div>
      </div>
      <div style="font-size:11px;color:var(--text);margin-bottom:8px;opacity:0.8">
        Entry: ${escapeHtml(e.entry)} · SL: ${escapeHtml(e.sl)} · TP: ${escapeHtml(e.tp1)}
      </div>
      </div>
      ${tradeMemory.entries?.[e.id] ? `
        <div class="trade-coach" style="position:relative;margin-top:10px;padding:12px 28px 12px 12px;background:rgba(229,189,108,0.06);border:1px solid rgba(229,189,108,0.15);border-radius:12px;font-size:11px;color:var(--text);line-height:1.6">
          <button class="coach-close" data-id="${escapeHtml(e.id)}" style="position:absolute;top:6px;right:8px;background:none;border:none;color:var(--dim);cursor:pointer;font-size:12px;padding:4px">✕</button>
          💡 ${escapeHtml(tradeMemory.entries[e.id])}
        </div>
      ` : ''}
    `;

    // Handle Delete
    const delBtn = d.querySelector('.bdel');
    if(delBtn) {
      delBtn.onclick=async(ev)=>{
        ev.stopPropagation();
        if(!confirm('Eliminare questo trade?'))return;
        const id=e.id;
        delBtn.disabled=true;
        const saved=await dbSave('delete_trade',{id});
        if(!saved.ok){delBtn.disabled=false;return;}
        entries=entries.filter(x=>String(x.id)!==String(id));
        S.set(K.j,entries);
        renderJournal();
        updateHdr();

      };
    }

    // Handle Coach Close
    const closeBtn = d.querySelector('.coach-close');
    if(closeBtn) {
      closeBtn.onclick=(ev)=>{
        ev.stopPropagation();
        if(tradeMemory.entries) {
          delete tradeMemory.entries[e.id];
          S.set(K.mem, tradeMemory);
          window.dbSaveUserData&&window.dbSaveUserData('mem',tradeMemory);
          renderJournal();
        }
      };
    }

    const cbtn=d.querySelector('.bcoach');
    if(cbtn)cbtn.onclick=async()=>{
      cbtn.textContent='⏳';cbtn.disabled=true;
      const coaching=await coachSingleTrade(e);
      if(coaching){
        renderJournal(); // Refresh to show the coaching text
        tradeMemory.entries=tradeMemory.entries||{};
        tradeMemory.entries[e.id]=coaching;
        S.set(K.mem,tradeMemory);
        window.dbSaveUserData&&window.dbSaveUserData('mem',tradeMemory);
      }
      cbtn.textContent='💡';cbtn.disabled=false;
    };
    list.appendChild(d);
  });
}

// ── TURSO BOOT SYNC ─────────────────────────────────────────
// On load: fetch trades from Turso and merge with localStorage (union by id)
async function syncJournalFromDb(){
  try{
    const res=await dbLoad('get_trades',{user_id:window.userId,limit:5000},8000);
    if(!res?.ok||!res.trades?.length) return;
    const localIds=new Set(entries.map(e=>String(e.id)));
    let added=0;
    for(const t of res.trades){
      const tid=String(t.id||t.ID);
      if(localIds.has(tid)) continue;
      // Map Turso cols back to journal format
      entries.push({
        id:tid,
        date:t.trade_date||t.created_at?.slice(0,10)||'',
        dir:t.direction||'BUY',
        entry:t.entry_price||'',
        sl:t.sl||'',
        tp1:t.tp1||'',
        tp2:t.tp2||'',
        result:t.result||'',
        pnl:t.pnl||0,
        emo:t.emotion||'Neutro',
        err:t.mistake||'Nessuno',
        notes:t.notes||'',
        symbol:t.symbol||'XAUUSD',
        source:t.source||'manual',
        mfxAccountId:String(t.source||'').split(':')[1]||null,
      });
      localIds.add(tid);
      added++;
    }
    if(added>0){
      // Sort by date desc
      entries.sort((a,b)=>b.date>a.date?1:-1);
      S.set(K.j,entries);
      renderJournal();
      console.log(`[TradeFlow] Synced ${added} trade(s) from Turso`);
    }
  }catch(e){console.log('[TradeFlow] Journal sync skipped:',e.message);}
}

// Run sync when journal tab is first opened
document.addEventListener('DOMContentLoaded',()=>{
  setTimeout(syncJournalFromDb, 1500); // small delay to let core init finish
});
