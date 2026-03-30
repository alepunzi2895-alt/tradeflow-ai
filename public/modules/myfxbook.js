// TradeFlow AI — modules/myfxbook.js

// ── MYFXBOOK ───────────────────────────────────────────
// btn-myfxb-j already wired above

function renderMyfx(){
  const c=document.getElementById('mfx-content');
  if(mfxSession){
    c.innerHTML=`
      <div style="display:flex;justify-content:space-between;align-items:center;background:#081408;border:1px solid #00e67625;border-radius:10px;padding:12px;margin-bottom:12px">
        <div><div style="color:var(--green);font-size:12px;font-weight:700">✓ Connesso a MyFxBook</div><div style="color:var(--dim);font-size:10px">${mfxSession.email}</div></div>
        <button onclick="mfxLogout()" style="background:#160c0c;border:1px solid #ff475722;border-radius:6px;padding:5px 10px;color:#ff8a80;font-size:11px;cursor:pointer">Disconnetti</button>
      </div>
      <div id="mfx-accounts"></div>`;
    loadMyfxAccounts();
  }else{
    c.innerHTML=`
      <div style="color:var(--g);font-size:12px;font-weight:700;margin-bottom:3px;font-family:'Space Grotesk',sans-serif">📊 MYFXBOOK</div>
      <div style="color:var(--dim);font-size:12px;margin-bottom:13px;line-height:1.65">Connetti per importare lo storico trade e analizzare gli errori con AI.</div>
      <div style="background:var(--card);border:1px solid var(--border2);border-radius:10px;padding:14px;margin-bottom:12px">
        <div style="color:var(--g);font-size:11px;font-weight:700;margin-bottom:10px">LOGIN MYFXBOOK</div>
        <div class="ff" style="margin-bottom:8px"><label>EMAIL</label><input id="mfx-email" type="email" placeholder="email@myfxbook.com"></div>
        <div class="ff" style="margin-bottom:10px"><label>PASSWORD</label><input id="mfx-pass" type="password" placeholder="••••••••"></div>
        <button class="bsave" id="btn-mfx-login" style="width:100%">🔗 Connetti</button>
        <div id="mfx-err" style="display:none;margin-top:8px;font-size:11px;color:#ff8a80;background:#160c0c;border:1px solid #ff475722;border-radius:6px;padding:7px 9px"></div>
      </div>
      <div style="color:var(--dim);font-size:11px;line-height:1.7;padding:0 4px">ℹ️ Le credenziali vengono usate solo per chiamare l'API MyFxBook dal server. Non vengono salvate.</div>`;
    document.getElementById('btn-mfx-login').onclick=mfxLogin;
  }
}

async function mfxLogin(){
  const email=document.getElementById('mfx-email').value.trim();
  const pass=document.getElementById('mfx-pass').value;
  if(!email||!pass)return;
  const btn=document.getElementById('btn-mfx-login');btn.textContent='⏳...';btn.disabled=true;
  try{
    const r=await fetch('/api/myfxbook',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'login',email,password:pass})});
    const d=await r.json();
    if(d.error||!d.session)throw new Error(d.message||'Login fallito');
    mfxSession={session:d.session,email};S.set(K.mfx,mfxSession);renderMyfx();
  }catch(e){
    document.getElementById('mfx-err').style.display='block';
    document.getElementById('mfx-err').textContent='❌ '+e.message;
    btn.textContent='🔗 Connetti';btn.disabled=false;
  }
}
function mfxLogout(){mfxSession=null;S.set(K.mfx,null);renderMyfx();}

async function loadMyfxAccounts(){
  const wrap=document.getElementById('mfx-accounts');if(!wrap)return;
  wrap.innerHTML='<div style="color:var(--dim);font-size:12px;padding:8px 0">⏳ Caricamento...</div>';
  try{
    const r=await fetch('/api/myfxbook',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'accounts',session:mfxSession.session})});
    const d=await r.json();
    if(!d.accounts?.length){wrap.innerHTML='<div style="color:var(--dim);font-size:12px">Nessun account trovato</div>';return;}
    wrap.innerHTML='<div style="color:var(--g);font-size:10px;font-weight:700;margin-bottom:8px;letter-spacing:.07em">ACCOUNT</div>'+
      d.accounts.map(a=>`<div style="background:var(--card);border:1px solid var(--border);border-radius:9px;padding:10px 12px;margin-bottom:7px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <div style="font-size:13px;color:var(--text);font-weight:700">${a.name}</div>
          <div style="font-size:12px;font-family:monospace;color:${parseFloat(a.gain)>=0?'var(--green)':'var(--red)'}">${parseFloat(a.gain)>=0?'+':''}${parseFloat(a.gain).toFixed(1)}%</div>
        </div>
        <div style="font-size:10px;color:var(--dim);font-family:monospace">DD: ${a.drawdown}% · Balance: $${parseFloat(a.balance).toFixed(0)}</div>
        <button style="margin-top:6px;width:100%;background:linear-gradient(135deg,var(--g),var(--g2));border:none;border-radius:7px;padding:8px;color:#000;font-size:12px;font-weight:700;cursor:pointer;font-family:inherit" onclick="analyzeMfxAccount('${a.id}')">🧠 Analizza Operatività</button>
        <button onclick="importMfxToJournal('${a.id}')" style="margin-top:5px;width:100%;background:var(--card);border:1px solid var(--border2);border-radius:7px;padding:7px;color:var(--green);font-size:12px;font-weight:600;cursor:pointer;font-family:inherit">📥 Importa Trade al Journal</button>
      </div>`).join('');
  }catch(e){wrap.innerHTML=`<div style="color:#ff8a80;font-size:12px">❌ ${e.message}</div>`;}
}

async function analyzeMfxAccount(accountId){
  if(!mfxSession)return;
  const wrap=document.getElementById('mfx-accounts');
  const btn=wrap?.querySelector(`[onclick="analyzeMfxAccount('${accountId}')"]`);
  if(btn){btn.textContent='⏳ Analisi...';btn.disabled=true;}
  try{
    const r=await fetch('/api/myfxbook',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'history',session:mfxSession.session,accountId})});
    const d=await r.json();
    const trades=(d.history||[]).filter(t=>t.symbol&&t.type&&!['deposit','withdrawal','credit','balance'].includes((t.type||'').toLowerCase())).slice(0,30);
    const sum=trades.map(t=>`${t.openTime}|${t.type}|${t.symbol}|open:${t.openPrice} close:${t.closePrice}|lots:${t.size}|P&L:${t.profit}$`).join('\n');
    const reply=await api([{role:'user',content:`Analizza storico MyFxBook (solo trade reali):\n${sum}\n\nStatistiche, pattern errori, confronto con strategia (TP1 ${P.tp1}R, TP2 ${P.tp2}R), 3 azioni concrete, Score Disciplina X/10.`}],
      `Sei TradeFlow AI Coach. Italiano. Profilo: ${P.name}.`);
    const box=document.createElement('div');box.className='aib';box.style.marginTop='10px';
    box.innerHTML='<div class="ait">🧠 ANALISI MYFXBOOK</div>';
    box.appendChild(md(reply));wrap.appendChild(box);autoLearn(reply);
  }catch(e){if(btn){btn.textContent='🧠 Analizza Errori AI';btn.disabled=false;}alert('Errore: '+e.message);}
}
