// TradeFlow AI — modules/kb.js

// ── KNOWLEDGE BASE ──────────────────────────────────────
document.getElementById('kb-drop').onclick=()=>document.getElementById('kb-file').click();
document.getElementById('kb-file').onchange=async e=>{
  const files=Array.from(e.target.files||[]);
  if(!files.length)return;
  const total=files.length;
  const drop=document.getElementById('kb-drop');
  for(let i=0;i<files.length;i++){
    const f=files[i];
    if(drop)drop.querySelector('.sdrop-t').textContent=`(${i+1}/${total}) ${f.name}`;
    await processKbFile(f);
    // Wait 5 seconds between files to avoid rate limit (30k tokens/min)
    if(i < files.length-1){
      for(let s=5;s>0;s--){
        if(drop)drop.querySelector('.sdrop-t').textContent=`Attendi ${s}s prima del prossimo...`;
        await new Promise(r=>setTimeout(r,1000));
      }
    }
  }
  if(drop)drop.querySelector('.sdrop-t').textContent='Carica uno o più documenti';
  e.target.value='';
};

async function processKbFile(file){
  const drop=document.getElementById('kb-drop');const stat=document.getElementById('kb-status');
  drop.querySelector('.sdrop-t').textContent=`⏳ Analisi: ${file.name}`;stat.style.display='none';
  try{
    const type=file.type;const isPdf=type==='application/pdf';const isImg=type.startsWith('image/');
    let part;
    if(isPdf||isImg){
      const data=await new Promise((res,rej)=>{const r=new FileReader();r.onload=e=>res(e.target.result);r.onerror=rej;r.readAsDataURL(file);});
      const b64=data.split(',')[1];
      part=isPdf?{type:'document',source:{type:'base64',media_type:'application/pdf',data:b64}}:{type:'image',source:{type:'base64',media_type:type,data:b64}};
    }else{
      const text=await new Promise((res,rej)=>{const r=new FileReader();r.onload=e=>res(e.target.result);r.onerror=rej;r.readAsText(file);});
      part={type:'text',text:text.slice(0,8000)};
    }
    const reply=await api([{role:'user',content:[part,{type:'text',text:'Estrai le regole di trading XAU/USD rilevanti. Entry, risk management, pattern, indicatori, psicologia. Conciso. Italiano.'}]}],
      'Estrai informazioni di trading. Italiano.');
    const entry={id:Date.now(),name:file.name,size:file.size,date:new Date().toLocaleDateString('it-IT'),summary:reply};
    kb.unshift(entry);S.set(K.kb,kb);
    P.knowledge=kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6);S.set(K.p,P);
    stat.style.cssText='display:block;background:#081408;border:1px solid #00e67622;border-radius:7px;padding:7px 10px;margin-bottom:9px;font-size:12px;color:var(--green)';
    stat.textContent=`✓ "${file.name}" integrato.${kbSyncEnabled?' Salvataggio su GitHub...':''}`;
    renderKb();
    // Save to GitHub in background
    saveKbToGithub().then(()=>{
      if(kbSyncEnabled) stat.textContent=`✓ "${file.name}" integrato e salvato su GitHub ☁️`;
    });
  }catch(e){
    stat.style.cssText='display:block;background:#160c0c;border:1px solid #ff475722;border-radius:7px;padding:7px 10px;margin-bottom:9px;font-size:12px;color:#ff8a80';
    stat.textContent='❌ '+e.message;
  }
  drop.querySelector('.sdrop-t').textContent='Carica uno o più documenti';
}

function renderKb(){
  document.getElementById('kb-count').textContent=kb.length;
  const list=document.getElementById('kb-list');
  if(!kb.length){list.innerHTML='<div style="color:var(--border2);font-size:12px;text-align:center;padding:18px 0">Nessun documento caricato.</div>';return;}
  list.innerHTML='';
  kb.forEach(k=>{
    const d=document.createElement('div');d.className='kdoc';
    d.innerHTML=`<div class="kdoc-top"><div><div class="kdoc-name">📄 ${k.name}</div><div class="kdoc-meta">${k.date} · ${(k.size/1024).toFixed(0)}KB</div></div><button onclick="deleteKb(${k.id})" style="background:none;border:none;color:var(--border2);cursor:pointer;font-size:13px">✕</button></div><div class="kdoc-prv">${k.summary?.slice(0,200)||''}</div>`;
    list.appendChild(d);
  });
}
function deleteKb(id){
  kb=kb.filter(k=>k.id!==id);
  S.set(K.kb,kb);
  P.knowledge=kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6);
  S.set(K.p,P);
  renderKb();
  saveKbToGithub();
}

function exportKb(){
  if(!kb.length){alert('Nessun documento nella Knowledge Base.');return;}
  const data={knowledge:kb,exportedAt:new Date().toISOString(),app:'TradeFlowAI'};
  const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});
  const url=URL.createObjectURL(blob);
  const a=document.createElement('a');
  a.href=url;a.download=`tradeflow-knowledge-${new Date().toISOString().slice(0,10)}.json`;
  a.click();URL.revokeObjectURL(url);
}

function importKbFromJson(file){
  const r=new FileReader();
  r.onload=e=>{
    try{
      const data=JSON.parse(e.target.result);
      if(data.knowledge&&Array.isArray(data.knowledge)){
        // Merge with existing, avoid duplicates by name
        const existing=new Set(kb.map(k=>k.name));
        const newDocs=data.knowledge.filter(k=>!existing.has(k.name));
        kb=[...newDocs,...kb];
        S.set(K.kb,kb);
        P.knowledge=kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6);
        S.set(K.p,P);
        renderKb();
        alert(`✅ ${newDocs.length} documenti importati nella Knowledge Base.`);
      }
    }catch(err){alert('❌ File non valido: '+err.message);}
  };
  r.readAsText(file);
}

// ── GITHUB KB SYNC ──────────────────────────────────────
let kbSyncEnabled = false;

async function checkKbSync(){
  try{
    const r = await fetch('/api/kb');
    const txt = await r.text();
    if(txt.trim().startsWith('<'))return; // endpoint not ready
    const d = JSON.parse(txt);
    if(d.ok){
      kbSyncEnabled = true;
      // If GitHub has more docs than local, load from GitHub
      if(d.kb && d.kb.length > 0){
        if(d.kb.length >= kb.length){
          kb = d.kb;
          S.set(K.kb, kb);
          if(d.knowledge && d.knowledge.length > 0){
            P.knowledge = d.knowledge;
          } else {
            P.knowledge = kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6);
          }
          S.set(K.p, P);
          renderKb();
          console.log('KB caricata da GitHub:', kb.length, 'documenti');
        }
      }
      updateKbSyncBadge(true);
    }
  }catch(e){
    console.log('GitHub KB sync non disponibile:', e.message);
    updateKbSyncBadge(false);
  }
}

async function saveKbToGithub(){
  if(!kbSyncEnabled) return;
  try{
    await fetch('/api/kb',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        kb: kb,
        knowledge: kb.map(k=>`[${k.name}]\n${k.summary}`).slice(-6)
      })
    });
    console.log('KB salvata su GitHub');
  }catch(e){
    console.log('GitHub KB save failed:', e.message);
  }
}

function updateKbSyncBadge(synced){
  const badge = document.getElementById('kb-sync-badge');
  if(!badge) return;
  if(synced){
    badge.textContent = '☁️ Sync GitHub';
    badge.style.color = 'var(--green)';
    badge.style.borderColor = '#00e67630';
  } else {
    badge.textContent = '💾 Locale';
    badge.style.color = 'var(--dim)';
    badge.style.borderColor = 'var(--border2)';
  }
}
