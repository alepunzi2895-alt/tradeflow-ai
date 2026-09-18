// TradeFlow AI — modules/myfxbook.js

// ── MYFXBOOK ───────────────────────────────────────────
// btn-myfxb-j already wired above

function renderMyfx(){
  const c=document.getElementById('mfx-content');
  if(mfxSession){
    c.innerHTML=`
      <div style="display:flex;justify-content:space-between;align-items:center;background:#081408;border:1px solid #62E6A625;border-radius:10px;padding:12px;margin-bottom:12px">
        <div><div style="color:var(--green);font-size:12px;font-weight:700">✓ Connesso a MyFxBook</div><div style="color:var(--dim);font-size:10px">${mfxSession.email}</div></div>
        <button onclick="mfxLogout()" style="background:#160c0c;border:1px solid #FF8A8A22;border-radius:6px;padding:5px 10px;color:#FF8A8A;font-size:11px;cursor:pointer">Disconnetti</button>
      </div>
      <div id="mfx-accounts"></div>`;
    loadMyfxAccounts();
  }else{
    c.innerHTML=`
      <div style="color:var(--g);font-size:12px;font-weight:700;margin-bottom:3px;font-family:'Outfit',sans-serif">📊 MYFXBOOK</div>
      <div style="color:var(--dim);font-size:12px;margin-bottom:13px;line-height:1.65">Connetti per importare lo storico trade e analizzare gli errori con AI.</div>
      <div style="background:var(--card);border:1px solid var(--border2);border-radius:10px;padding:14px;margin-bottom:12px">
        <div style="color:var(--g);font-size:11px;font-weight:700;margin-bottom:10px">LOGIN MYFXBOOK</div>
        <div class="ff" style="margin-bottom:8px"><label>EMAIL</label><input id="mfx-email" type="email" placeholder="email@myfxbook.com"></div>
        <div class="ff" style="margin-bottom:10px"><label>PASSWORD</label><input id="mfx-pass" type="password" placeholder="••••••••"></div>
        <button class="bsave" id="btn-mfx-login" style="width:100%">🔗 Connetti</button>
        <div id="mfx-err" style="display:none;margin-top:8px;font-size:11px;color:#FF8A8A;background:#160c0c;border:1px solid #FF8A8A22;border-radius:6px;padding:7px 9px"></div>
      </div>
      
      <div style="margin-top:10px;background:#0d0f12;border:1px solid #E5BD6C33;border-radius:9px;padding:12px">
        <div style="font-size:12px;font-weight:700;color:var(--yellow);margin-bottom:8px;display:flex;align-items:center;gap:5px">📘 COME COLLEGARE MYFXBOOK</div>
        <div style="font-size:11px;color:var(--dim);line-height:1.6;font-family:sans-serif">
          1. <b>Registrati su MyFxBook</b>: Vai su <a href="https://www.myfxbook.com/" target="_blank" style="color:var(--g);text-decoration:underline">myfxbook.com</a> e crea un account.<br>
          2. <b>Scarica l'EA</b>: Nella sezione <i>Portfolio > Add Account</i>, seleziona MetaTrader 4/5 (EA) e scarica il plugin.<br>
          3. <b>Configura MT4/MT5</b>: Trascina l'EA sul grafico. Durante i settaggi inserisci l'indirizzo email e la password utilizzati per registrarti a MyFxBook e imposta un intervallo di pubblicazione (es. 5 min).<br>
          4. <b>Collega l'app</b>: Usa la stessa mail e password nel form in alto su TradeFlow AI.<br><br>
          <i>⚠️ Sicurezza: TradeFlow invia la password solo in una chiamata one-shot alle API ufficiali di MyFxBook per generare un token di sessione. La password NON viene mai salvata sul nostro database (Turso) — resta salvata solo nel browser di questo dispositivo, per riconnetterti in automatico quando la sessione MyFxBook scade da sola.</i>
        </div>
      </div>
      `;
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
    // pass viene salvata SOLO in localStorage (per riautenticarsi in automatico quando la sessione
    // MyFxBook scade lato loro) — mai inviata al nostro DB Turso, solo session+email lo sono.
    mfxSession={session:d.session,email,pass};
    S.set(K.mfx,mfxSession);
    window.dbSaveUserData && window.dbSaveUserData('mfx', {session:d.session,email});
    renderMyfx();
  }catch(e){
    document.getElementById('mfx-err').style.display='block';
    document.getElementById('mfx-err').textContent='❌ '+e.message;
    btn.textContent='🔗 Connetti';btn.disabled=false;
  }
}
function mfxLogout(){mfxSession=null;S.set(K.mfx,null); window.dbSaveUserData && window.dbSaveUserData('mfx', null); renderMyfx();}

// Riautentica in automatico con le credenziali salvate in locale, quando la sessione MyFxBook
// (rilasciata dai loro server, scade da sola col tempo) risulta invalida. Ritorna true se riuscita.
async function mfxRelogin(){
  if(!mfxSession?.email||!mfxSession?.pass) return false;
  try{
    const r=await fetch('/api/myfxbook',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'login',email:mfxSession.email,password:mfxSession.pass})});
    const d=await r.json();
    if(d.error||!d.session) return false;
    mfxSession={...mfxSession,session:d.session};
    S.set(K.mfx,mfxSession);
    window.dbSaveUserData && window.dbSaveUserData('mfx',{session:mfxSession.session,email:mfxSession.email});
    return true;
  }catch(e){return false;}
}

// Wrapper per tutte le chiamate autenticate: se la sessione risulta scaduta, prova un relogin
// silenzioso con le credenziali salvate e ritenta una volta sola prima di arrendersi.
async function mfxApiCall(action, extra={}, _retried=false){
  const r=await fetch('/api/myfxbook',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,session:mfxSession?.session,...extra})});
  const d=await r.json();
  if(d.error && !_retried){
    const ok=await mfxRelogin();
    if(ok) return mfxApiCall(action, extra, true);
  }
  return d;
}

function mfxShowExpired(wrap, msg){
  const hasSavedPass=!!mfxSession?.pass;
  const hint=hasSavedPass
    ? 'Il rinnovo automatico ha provato e non è riuscito (password salvata probabilmente cambiata su MyFxBook).'
    : 'Questa connessione risale a prima del rinnovo automatico: riconnettiti una volta sola, da qui in poi le scadenze si risolveranno da sole.';
  wrap.innerHTML=`<div style="color:#FF8A8A;font-size:12px;background:#160c0c;border:1px solid #FF8A8A22;border-radius:8px;padding:10px 12px;margin-bottom:8px">⚠️ ${msg||'Sessione MyFxBook scaduta.'}<br><span style="color:var(--dim);font-weight:400">${hint}</span></div>
    <button onclick="mfxLogout()" style="width:100%;background:var(--card);border:1px solid var(--border2);border-radius:7px;padding:8px;color:var(--g);font-size:12px;font-weight:700;cursor:pointer;font-family:inherit">🔄 Riconnetti (reinserisci email/password)</button>`;
}

async function loadMyfxAccounts(){
  const wrap=document.getElementById('mfx-accounts');if(!wrap)return;
  wrap.innerHTML='<div style="color:var(--dim);font-size:12px;padding:8px 0">⏳ Caricamento...</div>';
  try{
    const d=await mfxApiCall('accounts');
    if(d.error){mfxShowExpired(wrap, d.message); return;}
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
  }catch(e){wrap.innerHTML=`<div style="color:#FF8A8A;font-size:12px">❌ ${e.message}</div>`;}
}

async function analyzeMfxAccount(accountId){
  if(!mfxSession)return;
  const wrap=document.getElementById('mfx-accounts');
  const btn=wrap?.querySelector(`[onclick="analyzeMfxAccount('${accountId}')"]`);
  if(btn){btn.textContent='⏳ Analisi...';btn.disabled=true;}
  try{
    const d=await mfxApiCall('history',{accountId});
    if(d.error){
      if(btn){btn.textContent='🧠 Analizza Operatività';btn.disabled=false;}
      mfxShowExpired(wrap, d.message);
      return;
    }
    // MyFxBook restituisce il campo 'action' ("Buy"/"Sell"), non 'type' — vedi anche importMfxToJournal()
    const SKIP_TYPES=['deposit','withdrawal','credit','balance','bonus','rebate','commission'];
    const trades=(d.history||[]).filter(t=>{
      const act=String(t.action||t.type||'').toLowerCase();
      return t.symbol && act && !SKIP_TYPES.some(s=>act.includes(s));
    }).slice(0,30);
    if(!trades.length){
      if(btn){btn.textContent='🧠 Analizza Operatività';btn.disabled=false;}
      wrap.insertAdjacentHTML('beforeend', `<div style="color:var(--dim);font-size:12px;margin-top:8px">Nessun trade reale trovato nello storico MyFxBook di questo account.</div>`);
      return;
    }
    const sum=trades.map(t=>`${t.openTime||t.open_time||''}|${(t.action||t.type||'').toUpperCase()}|${t.symbol}|open:${t.openPrice??t.open_price} close:${t.closePrice??t.close_price}|lots:${t.size??t.lots??t.volume}|P&L:${t.profit}$`).join('\n');
    const mem=analysisMemory.entries?.slice(0,3).map(e=>`[${(e.date||'').slice(0,10)}] ${e.text}`).join('\n')||'';
    const memCtx=mem?`\nMEMORIA ANALISI PRECEDENTE (resta coerente, non ripetere consigli già dati se risultano già seguiti):\n${mem}`:'';
    const reply=await api([{role:'user',content:`Analizza operatività reale di ${P.name} su MyFxBook (solo trade chiusi reali, ignora depositi/prelievi):\n${sum}\n${memCtx}\n\nUsa SOLO i numeri riportati sopra, non inventare dati. Calcola win rate, P&L totale e RR medio dai trade forniti. Individua il pattern d'errore più ricorrente con l'evidenza numerica che lo dimostra. Confronta con la strategia target di ${P.name} (TP1 ${P.tp1}R, TP2 ${P.tp2}R, rischio ${P.risk}%/trade). Dai 3 azioni concrete e specifiche da applicare da subito (niente consigli generici tipo "sii più disciplinato"). Chiudi con Score Disciplina X/10 motivato in una frase.`}],
      `Sei TradeFlow AI Coach. Italiano. Tono diretto, concreto, onesto. Profilo: ${P.name}. Aree di sviluppo note: ${P.errors?.length?P.errors.join(', '):'nessuna'}.`);
    const box=document.createElement('div');box.className='aib';box.style.marginTop='10px';
    box.innerHTML='<div class="ait">🧠 ANALISI MYFXBOOK</div>';
    box.appendChild(md(reply));wrap.appendChild(box);autoLearn(reply);
    pushAnalysisMemory(reply);
    if(btn){btn.textContent='🧠 Analizza Operatività';btn.disabled=false;}
  }catch(e){if(btn){btn.textContent='🧠 Analizza Operatività';btn.disabled=false;}alert('Errore: '+e.message);}
}
