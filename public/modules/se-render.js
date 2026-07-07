// ── RENDER ────────────────────────────────────────────────────────────────────
function seRender(mt5Data,pending,snap,isExtreme,inSession,hour){
  const el=document.getElementById('se-content');
  if(!el)return;

  const REGIME_META={
    TREND_UP:    {col:'#00e676',bg:'#00e67612',icon:'📈',label:'TREND RIALZISTA'},
    TREND_DOWN:  {col:'#ff4757',bg:'#ff475712',icon:'📉',label:'TREND RIBASSISTA'},
    WEAK_UP:     {col:'#ffd700',bg:'#ffd70012',icon:'↗️',label:'TREND DEBOLE ↑'},
    WEAK_DOWN:   {col:'#ffca28',bg:'#ffca2812',icon:'↘️',label:'TREND DEBOLE ↓'},
    RANGE:       {col:'#c8a96e',bg:'#c8a96e12',icon:'↔️',label:'LATERALE (RANGING)'},
    VOLATILE:    {col:'#b36cff',bg:'#b36cff12',icon:'⚡',label:'VOLATILE'},
    UNKNOWN:     {col:'var(--dim)',bg:'var(--bg2)',icon:'❓',label:'SCONOSCIUTO'},
  };
  const rm=REGIME_META[seRegime]||REGIME_META.UNKNOWN;
  
  const acc=mt5Data?.account||{};
  const pos=mt5Data?.positions||[];
  const history=mt5Data?.trades||[];
  const bs=mt5Data?.bot_status||{};
  const syncAge=mt5Data?.synced_at?Math.round((Date.now()-new Date(mt5Data.synced_at).getTime())/1000):null;
  // Bot online = sincronizzato negli ultimi 300s (sync ogni 20s, 15 heartbeat di margine)
  const botOnline=syncAge!==null&&syncAge<300;
  const syncLabel=syncAge===null?'Mai sincronizzato':syncAge<5?'Ora':syncAge<60?`${syncAge}s fa`:`${Math.round(syncAge/60)}min fa`;

  // ── STATUS BAR — mostra stato reale bot MT5
  let statusHtml='';
  if(isExtreme){
    statusHtml=`<div style="background:#ff475720;border:1px solid #ff475740;border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;color:#ff4757">
      ⚠️ <b>GIORNO ESTREMO</b> — Volatilità anomala (ATR>${SE.extremeMult}x media). Trading sospeso.
    </div>`;
  }
  // Stato bot MT5 sempre visibile
  const botStatusHtml=`<div style="background:${botOnline?'#00e67608':'#ff475710'};border:1px solid ${botOnline?'#00e67625':'#ff475730'};border-radius:7px;padding:7px 10px;margin-bottom:8px;font-size:10px;display:flex;justify-content:space-between;align-items:center">
    <span style="color:${botOnline?'var(--green)':'#ff4757'}">${botOnline?'🟢 Bot MT5 attivo':'🔴 Bot MT5 offline'}</span>
    <span style="color:var(--dim)">Sync: ${syncLabel}${bs.symbol?' · '+bs.symbol:''}</span>
    ${!botOnline?`<span style="color:#ffca28;font-size:9px">Avvia: python scripts/mt5-bot.py</span>`:`<span style="color:var(--green);font-size:9px">${bs.trades_today||0} trade · ${bs.lot||0.02} lot</span>`}
  </div>`;
  statusHtml = botStatusHtml + statusHtml;

  // ── GUARDIAN STATUS (News + Risk Guardian)
  const _ngPaused   = bs.news_paused;
  const _ngMult     = bs.news_risk_mult ?? 1.0;
  const _ngReason   = bs.news_reason || '';
  const _ngCol      = _ngPaused ? '#ff4757' : _ngMult < 1.0 ? '#ffca28' : 'var(--green)';
  const _ngLabel    = _ngPaused ? '🔴 SOSPESO' : _ngMult < 1.0 ? `⚠️ RIDOTTO ×${_ngMult}` : '🟢 OK';
  const _rgTier     = bs.rg_tier || '—';
  const _rgComp     = bs.rg_composite != null ? bs.rg_composite.toFixed(0) : '—';
  const _rgLot      = bs.rg_lot != null ? bs.rg_lot.toFixed(2) : '—';
  const _rgTierCol  = _rgTier.includes('MAX')||_rgTier.includes('STRONG') ? '#ff4757'
                    : _rgTier.includes('AGGRESS') ? '#ffca28'
                    : _rgTier.includes('NORMAL') ? 'var(--green)'
                    : 'var(--dim)';
  const guardianHtml = botOnline ? `
<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px">
  <div style="background:${_ngPaused?'#ff475712':'#ffffff06'};border:1px solid ${_ngCol}35;border-radius:7px;padding:7px 9px">
    <div style="font-size:7px;color:var(--dim);letter-spacing:.08em;margin-bottom:3px">NEWS GUARDIAN</div>
    <div style="font-size:10px;font-weight:800;color:${_ngCol}">${_ngLabel}</div>
    ${_ngReason?`<div style="font-size:8px;color:var(--dim);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${_ngReason}">${_ngReason}</div>`:''}
  </div>
  <div style="background:#ffffff06;border:1px solid ${_rgTierCol}35;border-radius:7px;padding:7px 9px">
    <div style="font-size:7px;color:var(--dim);letter-spacing:.08em;margin-bottom:3px">RISK GUARDIAN</div>
    <div style="font-size:10px;font-weight:800;color:${_rgTierCol}">${_rgTier}</div>
    <div style="font-size:8px;color:var(--dim);margin-top:2px">Score <b style="color:var(--fg)">${_rgComp}</b> · Lot <b style="color:var(--fg)">${_rgLot}</b></div>
  </div>
</div>` : '';
  statusHtml = statusHtml + guardianHtml;

  // ── BOT LOG PANEL
  const _logs = (bs.last_logs || []).slice().reverse(); // più recenti in cima
  const _lvlCol = l => l==='WARNING'?'#ffca28':l==='ERROR'||l==='CRITICAL'?'#ff4757':'var(--dim)';
  const _lvlBg  = l => l==='WARNING'?'#ffca2808':l==='ERROR'||l==='CRITICAL'?'#ff475708':'transparent';
  const logHtml = botOnline && _logs.length ? `
<div style="background:#0a0c0f;border:1px solid var(--border);border-radius:7px;margin-bottom:8px;overflow:hidden">
  <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 9px;border-bottom:1px solid var(--border)">
    <span style="font-size:7px;color:var(--dim);letter-spacing:.08em">BOT LOG (ultimi ${_logs.length})</span>
    <span style="font-size:7px;color:var(--dim)">● live</span>
  </div>
  <div id="se-log-scroll" style="max-height:140px;overflow-y:auto;font-family:monospace;font-size:8.5px;line-height:1.55">
    ${_logs.map(r=>`<div style="display:flex;gap:6px;padding:2px 9px;background:${_lvlBg(r.lvl)};border-bottom:1px solid #ffffff05">
      <span style="color:#444;flex-shrink:0">${r.ts}</span>
      <span style="color:${_lvlCol(r.lvl)};flex-shrink:0;width:16px">${r.lvl==='WARNING'?'⚠':r.lvl==='ERROR'||r.lvl==='CRITICAL'?'✖':'·'}</span>
      <span style="color:var(--fg);word-break:break-all">${r.msg.replace(/</g,'&lt;')}</span>
    </div>`).join('')}
  </div>
</div>` : '';
  statusHtml = statusHtml + logHtml;

  // ── REGIME + P&L REALE
  const pnlOggi = bs.pnl_today || 0;
  const regimeHtml=`
<div style="background:${rm.bg};border:1px solid ${rm.col}40;border-radius:9px;padding:11px 13px;margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start">
    <div>
      <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:3px">REGIME DI MERCATO</div>
      <div style="font-size:16px;font-weight:800;color:${rm.col}">${rm.icon} ${rm.label}</div>
      <div style="font-size:9px;color:${rm.col};margin-top:4px">
        Strategie attive: ${(SE.regimePriority[seRegime]||['S00_MFKK']).map(n=>`<b>${SE.strategies[n]?.label||n}</b>`).join(' › ')}
      </div>
    </div>
    <div style="text-align:right">
      <div style="font-size:9px;color:var(--dim);margin-bottom:2px">PROFITTO REALIZZATO (MT5)</div>
      <div style="font-size:18px;font-weight:800;color:${pnlOggi>0?'var(--green)':pnlOggi<0?'var(--red)':'var(--fg)'}">${pnlOggi>=0?'+':''}${pnlOggi.toFixed(2)} €</div>
      <div style="font-size:9px;color:var(--dim)">${botOnline?'ONLINE':'OFFLINE'} · ${bs.trades_today||0} trade oggi</div>
    </div>
  </div>
</div>`;

  // ── EMA ALIGNMENT (per S06_EMA_CROSS) — usa snap (già passato a seRender)
  const _e20=parseFloat(snap.e20), _e50=parseFloat(snap.e50), _e100=parseFloat(snap.e100), _e200=parseFloat(snap.e200), _pr=parseFloat(snap.price);
  const emaBullStack = _e20>_e50 && _e50>_e100 && _e100>_e200;
  const emaBearStack = _e20<_e50 && _e50<_e100 && _e100<_e200;
  const emaAlignCol  = emaBullStack?'var(--green)':emaBearStack?'var(--red)':'var(--dim)';
  // Prezzo vs ogni EMA
  const prVs = (e) => _pr>e?'▲':'▼';

  // ── INDICATORI SNAPSHOT
  const indSnap=`
<div style="margin-bottom:8px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:4px">INDICATORI CORRENTI</div>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin-bottom:3px">
    ${[['ADX',snap.adx],['DI+',snap.dip],['DI-',snap.dim],['RSI',snap.rsi],['W%R',snap.wpr]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px;margin-bottom:3px">
    ${[['MACD',snap.macd],['EMA50',snap.e50],['EMA200',snap.e200],['VWAP',snap.vwap]].map(([k,v])=>`
    <div style="background:var(--bg2);border:1px solid var(--border);border-radius:4px;padding:4px 2px;text-align:center">
      <div style="font-size:7px;color:var(--dim)">${k}</div>
      <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
    </div>`).join('')}
  </div>
  <div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
      <span style="font-size:8px;color:var(--dim);letter-spacing:.05em">EMA STACK 20/50/100/200</span>
      <span style="font-size:9px;font-weight:800;color:${emaAlignCol}">${emaBullStack?'▲ RIALZISTA':emaBearStack?'▼ RIBASSISTA':'↔ MISTO'}</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:3px">
      ${[['EMA 20','#ff4757',snap.e20,_e20],['EMA 50','#ff7f50',snap.e50,_e50],['EMA 100','#00bcd4',snap.e100,_e100],['EMA 200','#2196f3',snap.e200,_e200]].map(([k,col,v,raw])=>`
      <div style="border-radius:4px;padding:4px 2px;text-align:center;border:1px solid ${col}40;background:${col}08">
        <div style="font-size:7px;color:${col};font-weight:700">${k}</div>
        <div style="font-size:10px;font-weight:700;color:var(--fg)">${v??'—'}</div>
        <div style="font-size:8px;color:${_pr>raw?'var(--green)':'var(--red)'}">${raw?prVs(raw):''}</div>
      </div>`).join('')}
    </div>
  </div>
</div>`;

  // ── ORDER BLOCKS PANEL
  const _ob = seInds?.ob || null;
  const _price = parseFloat(snap.price);
  let obPanelHtml = '';
  if (_ob && (_ob.latestBull || _ob.latestBear)) {
    const bull = _ob.latestBull;
    const bear = _ob.latestBear;
    const inBull = bull && _price >= bull.low && _price <= bull.high;
    const inBear = bear && _price >= bear.low && _price <= bear.high;
    obPanelHtml = `
<div style="margin-bottom:8px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:4px">ORDER BLOCKS ATTIVI</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px">
    ${bull ? `<div style="background:${inBull?'#00e67618':'#00e67608'};border:1px solid ${inBull?'#00e676':'#00e67630'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--green);font-weight:700;margin-bottom:3px">▲ BULLISH OB${inBull?' 🎯 IN ZONA':''}</div>
      <div style="font-size:9px;color:var(--fg)">H: <b>$${bull.high.toFixed(1)}</b></div>
      <div style="font-size:9px;color:var(--dim)">Avg: $${bull.avg.toFixed(1)}</div>
      <div style="font-size:9px;color:var(--fg)">L: <b>$${bull.low.toFixed(1)}</b></div>
      <div style="font-size:8px;color:var(--dim);margin-top:2px">Dist: ${bull.low > _price ? '+' : ''}${((_price - bull.avg)/_price*100).toFixed(2)}%</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bull OB attivo</div>`}
    ${bear ? `<div style="background:${inBear?'#ff475718':'#ff475708'};border:1px solid ${inBear?'#ff4757':'#ff475730'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--red);font-weight:700;margin-bottom:3px">▼ BEARISH OB${inBear?' 🎯 IN ZONA':''}</div>
      <div style="font-size:9px;color:var(--fg)">H: <b>$${bear.high.toFixed(1)}</b></div>
      <div style="font-size:9px;color:var(--dim)">Avg: $${bear.avg.toFixed(1)}</div>
      <div style="font-size:9px;color:var(--fg)">L: <b>$${bear.low.toFixed(1)}</b></div>
      <div style="font-size:8px;color:var(--dim);margin-top:2px">Dist: ${bear.high < _price ? '-' : ''}${((_price - bear.avg)/_price*100).toFixed(2)}%</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bear OB attivo</div>`}
  </div>
</div>`;
  }

  // ── ICT M15 FVG PANEL
  const _m15ui = seInds?.m15 || null;
  let m15PanelHtml = '';
  if (_m15ui?.fvg) {
    const fvg    = _m15ui.fvg;
    const mi     = _m15ui.n - 1;
    const m15p   = _m15ui.C[mi];
    const bFVG   = fvg.latestBullFVG;
    const brFVG  = fvg.latestBearFVG;
    const m15e20 = _m15ui.e20?.[mi], m15e50 = _m15ui.e50?.[mi];
    const emaDir = m15e20 && m15e50 ? (m15e20>m15e50?'↑ BULL':'↓ BEAR') : '—';
    const emaDirCol = m15e20 && m15e50 ? (m15e20>m15e50?'var(--green)':'var(--red)') : 'var(--dim)';
    const inBullFVG = bFVG && m15p >= bFVG.open && m15p <= bFVG.close;
    const inBearFVG = brFVG && m15p >= brFVG.close && m15p <= brFVG.open;
    m15PanelHtml = `
<div style="margin-bottom:8px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
    <span style="font-size:9px;color:var(--dim);letter-spacing:.08em">ICT M15 — FVG ATTIVI</span>
    <span style="font-size:9px;font-weight:700;color:${emaDirCol}">EMA20/50 M15 ${emaDir}${m15e20?' · $'+m15e20.toFixed(0):''}</span>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:5px">
    ${bFVG ? `<div style="background:${inBullFVG?'#00e67618':'#00e67608'};border:1px solid ${inBullFVG?'#00e676':'#00e67630'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--green);font-weight:700;margin-bottom:3px">▲ Bull FVG${bFVG.displaced?' ⚡':''}${inBullFVG?' 🎯':''}</div>
      <div style="font-size:9px">$${bFVG.open.toFixed(1)} → $${bFVG.close.toFixed(1)}</div>
      <div style="font-size:8px;color:var(--dim)">Mid: $${bFVG.mid.toFixed(1)}</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bull FVG</div>`}
    ${brFVG ? `<div style="background:${inBearFVG?'#ff475718':'#ff475708'};border:1px solid ${inBearFVG?'#ff4757':'#ff475730'};border-radius:6px;padding:6px 8px">
      <div style="font-size:8px;color:var(--red);font-weight:700;margin-bottom:3px">▼ Bear FVG${brFVG.displaced?' ⚡':''}${inBearFVG?' 🎯':''}</div>
      <div style="font-size:9px">$${brFVG.open.toFixed(1)} → $${brFVG.close.toFixed(1)}</div>
      <div style="font-size:8px;color:var(--dim)">Mid: $${brFVG.mid.toFixed(1)}</div>
    </div>` : `<div style="background:var(--bg2);border:1px solid var(--border);border-radius:6px;padding:6px 8px;font-size:8px;color:var(--dim);text-align:center">Nessun Bear FVG</div>`}
  </div>
</div>`;
  }

  // ── SEGNALI ATTIVI
  let pendingHtml='';
  if(pending.length>0&&!isExtreme){
    const qualColors={elite:'#c8a96e', high:'#00e676', medium:'#ffd700'};
    const qualLabels={elite:'💎 ELITE', high:'🔥 FORTE', medium:'⚠️ MODERATO'};
    pendingHtml=`<div style="margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
        <div style="font-size:9px;color:var(--dim);letter-spacing:.08em">🔔 SEGNALI ATTIVI</div>
        <div style="font-size:8px;color:#00e676;font-weight:700">🤖 BOT ATTIVO</div>
      </div>
      ${pending.map((s)=>{
        const dc=s.dir==='buy'?'#00e676':'#ff4757';
        const qc=qualColors[s.quality]||'#ffd700';
        const ql=qualLabels[s.quality]||'';
        // Bottone MT5: abilitato solo se bot online e auto-trading non attivo
        const btnStyle=botOnline
          ?`background:${dc};color:${s.dir==='buy'?'#000':'#fff'};cursor:pointer;opacity:1`
          :`background:var(--bg2);color:var(--dim);cursor:not-allowed;opacity:0.5`;
        const btnLabel=botOnline?`🤖 AUTO — in esecuzione`:`🔴 Bot offline — avvia mt5-bot.py`;
        const btnDisabled='disabled';
        return `<div style="background:${dc}10;border:1px solid ${dc}35;border-radius:8px;padding:9px 11px;margin-bottom:6px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
            <div style="display:flex;align-items:center;gap:6px">
              <span style="color:${dc};font-weight:800;font-size:13px">${s.dir==='buy'?'▲ BUY':'▼ SELL'}</span>
              ${s.counterTrend?`<span style="font-size:8px;background:#b36cff18;border:1px solid #b36cff50;border-radius:3px;padding:1px 5px;color:#b36cff">⚡ CONTRO-TREND</span>`:''}
            </div>
            <div style="display:flex;gap:5px;align-items:center">
              <span style="font-size:9px;background:${qc}18;border:1px solid ${qc}40;border-radius:3px;padding:1px 5px;color:${qc}">${ql}</span>
              <span style="color:var(--dim);font-size:9px">${s.label} · WR ${s.wr}</span>
            </div>
          </div>
          <div style="font-size:9px;color:var(--fg);margin-bottom:5px;line-height:1.4">${s.why}</div>
          <div style="display:flex;gap:12px;font-size:9px;margin-bottom:6px">
            <span style="color:var(--green)">TP +$${s.tp}</span>
            <span style="color:var(--red)">SL -$${s.sl}</span>
            <span style="color:var(--dim)">R:R 1:${(s.tp/s.sl).toFixed(1)}</span>
            <span style="color:var(--dim)">PF ${s.pf}</span>
          </div>
          <button onclick='seSendTradeToMt5(${JSON.stringify(s)})' ${btnDisabled}
            style="width:100%;padding:7px;border:none;border-radius:5px;font-size:10px;font-weight:800;${btnStyle}">
            ${btnLabel}
          </button>
        </div>`;
      }).join('')}
    </div>`;
  } else if(!isExtreme && inSession){
    pendingHtml=`<div style="margin-bottom:10px;text-align:center;padding:12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;font-size:10px;color:var(--dim)">
      ⏳ Nessun segnale attivo in questo momento — monitoraggio in corso...
    </div>`;
  }

  // ── POSIZIONI REALI MT5
  const posHtml=`
<div style="margin-bottom:10px">
  <div style="font-size:9px;color:var(--dim);letter-spacing:.08em;margin-bottom:5px">POSIZIONI APERTE (REALI MT5)</div>
  ${pos.length===0
    ? `<div style="text-align:center;padding:12px;background:var(--bg2);border-radius:7px;font-size:10px;color:var(--dim)">Nessuna posizione aperta sul conto</div>`
    : pos.map(p=>{
        const dc=p.direction==='buy'?'#00e676':'#ff4757';
        const pCol=p.profit>=0?'var(--green)':'var(--red)';
        return `<div style="background:var(--bg2);border:1px solid ${dc}35;border-radius:7px;padding:8px 10px;margin-bottom:5px">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
            <span style="color:${dc};font-weight:800;font-size:11px">${p.direction.toUpperCase()} ${p.symbol}</span>
            <span style="color:${pCol};font-weight:800;font-size:12px">${p.profit>=0?'+':''}${p.profit.toFixed(2)} €</span>
          </div>
          <div style="font-size:9px;color:var(--dim);display:flex;gap:8px">
            <span>Entry <b>$${p.entry}</b></span>
            <span>TP $${p.tp}</span>
            <span>SL $${p.sl}</span>
            <span style="margin-left:auto;color:var(--fg)">${p.strategy||''}</span>
          </div>
        </div>`;
      }).join('')}
</div>`;

  // ── STORICO REALE — con filtro temporale
  function _filterTrades(arr){
    const f=window._seTradeFilter||'week';
    const now=new Date(), today=new Date(now.getFullYear(),now.getMonth(),now.getDate());
    if(f==='today') return arr.filter(t=>new Date(t.time)>=today);
    if(f==='week'){const d=new Date(today);d.setDate(d.getDate()-7);return arr.filter(t=>new Date(t.time)>=d);}
    if(f==='month'){const d=new Date(today);d.setDate(d.getDate()-30);return arr.filter(t=>new Date(t.time)>=d);}
    if(f==='custom'){
      const from=window._seTradeFrom?new Date(window._seTradeFrom):null;
      const to=window._seTradeTo?new Date(window._seTradeTo+'T23:59:59'):null;
      return arr.filter(t=>{const d=new Date(t.time);return(!from||d>=from)&&(!to||d<=to);});
    }
    return arr;
  }
  const filtered=_filterTrades(history);
  const fBtns=[['today','OGGI'],['week','7G'],['month','30G'],['all','TUTTO'],['custom','CUSTOM']].map(([k,lbl])=>{
    const active=window._seTradeFilter===k;
    return `<button onclick="window._seTradeFilter='${k}'" style="padding:2px 7px;font-size:8px;border-radius:4px;border:1px solid ${active?'var(--green)':'var(--border2)'};background:${active?'#00e67615':'transparent'};color:${active?'var(--green)':'var(--dim)'};cursor:pointer">${lbl}</button>`;
  }).join('');
  const customInputs=window._seTradeFilter==='custom'?`
    <div style="display:flex;gap:4px;margin-top:4px;align-items:center">
      <span style="font-size:8px;color:var(--dim)">Da</span>
      <input type="date" value="${window._seTradeFrom}" onchange="window._seTradeFrom=this.value" style="font-size:8px;background:var(--card2);border:1px solid var(--border2);border-radius:3px;color:var(--text);padding:1px 4px">
      <span style="font-size:8px;color:var(--dim)">A</span>
      <input type="date" value="${window._seTradeTo}" onchange="window._seTradeTo=this.value" style="font-size:8px;background:var(--card2);border:1px solid var(--border2);border-radius:3px;color:var(--text);padding:1px 4px">
    </div>`:'';
  const pnlTot=filtered.reduce((s,t)=>s+(t.profit||0),0);
  const histHtml=`
<div style="margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
    <span style="font-size:9px;color:var(--dim);letter-spacing:.08em">STORICO TRADE (REAL MT5)</span>
    <span style="font-size:9px;font-weight:700;color:${pnlTot>=0?'var(--green)':'var(--red)'}">${pnlTot>=0?'+':''}${pnlTot.toFixed(2)} €</span>
  </div>
  <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:4px">${fBtns}</div>
  ${customInputs}
  <div id="se-hist-scroll" style="max-height:180px;overflow-y:auto;margin-top:4px">
  ${filtered.length===0
    ? `<div style="text-align:center;padding:8px;font-size:9px;color:var(--dim)">Nessun trade nel periodo selezionato</div>`
    : filtered.map(t=>{
        const dc=t.direction==='buy'?'#00e676':'#ff4757';
        const dt=new Date(t.time);
        const dtStr=`${dt.toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit'})} ${dt.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})}`;
        return `<div style="display:flex;justify-content:space-between;font-size:8px;padding:3px 0;border-bottom:1px solid var(--border2)">
          <span style="color:${dc};min-width:28px">${t.direction.toUpperCase()}</span>
          <span style="color:var(--dim);min-width:60px">${dtStr}</span>
          <span style="min-width:55px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.strategy||'—'}</span>
          <span style="min-width:48px;text-align:right">$${t.price?.toFixed(2)}</span>
          <span style="color:${t.profit>=0?'var(--green)':'var(--red)'};min-width:42px;text-align:right">${t.profit>=0?'+':''}${t.profit?.toFixed(2)}</span>
        </div>`;
      }).join('')}
  </div>
  <div style="font-size:8px;color:var(--dim);margin-top:3px;text-align:right">${filtered.length} trade nel periodo</div>
</div>`;

  // ── MFKK AI GOLD BOT — pannello principale
  // Stats aggregate sistema (backtest M30 · 25 mesi · 6 strategie · lot=0.01 · $1/punto · 2026-04-19)
  // Sistema adattivo H1 fresh (2026-06-01): 1331 trade · WR 47.9% · PF 1.629 · +$23.5/gg · DD $390 · 19/24 mesi+
  const BOT_STATS = { pnl_1m:246, pnl_6m:1475, pnl_12m:2950, pnl_24m:5900, maxdd:390, maxdd_pct:'3.9%', trades_12m:666, pf:1.629, wr:'47.9%', n_strat:7 };

  // Multi-strategy playbook (allineato a REGIME_PRIORITY_M30 del backtester · S18 aggiunto)
  const PLAYBOOK_UI = {
    'TREND_UP':   {strategy:'S16_GOLDEN_SQUEEZE', others:['S10_OB_FVG_SCALP','S00_MFKK','S17_CONVERGENCE_SCALP'], tf:'H1/M30'},
    'TREND_DOWN': {strategy:'S16_GOLDEN_SQUEEZE', others:['S10_OB_FVG_SCALP','S00_MFKK','S17_CONVERGENCE_SCALP'], tf:'H1/M30'},
    'WEAK_UP':    {strategy:'S10_OB_FVG_SCALP',   others:['S18_RANGE_REVERSAL','S16_GOLDEN_SQUEEZE','S09_MFKK_SCALPING','S00_MFKK'], tf:'M30/H4'},
    'WEAK_DOWN':  {strategy:'S10_OB_FVG_SCALP',   others:['S18_RANGE_REVERSAL','S16_GOLDEN_SQUEEZE','S09_MFKK_SCALPING','S00_MFKK'], tf:'M30/H4'},
    'VOLATILE':   {strategy:'S09_MFKK_SCALPING',  others:['S10_OB_FVG_SCALP','S17_CONVERGENCE_SCALP'], tf:'M30/H4'},
    'RANGE':      {strategy:'S18_RANGE_REVERSAL',  others:['S10_OB_FVG_SCALP','S09_MFKK_SCALPING','S17_CONVERGENCE_SCALP'], tf:'M30/H4'},
    'UNKNOWN':    {strategy:'S18_RANGE_REVERSAL',  others:['S10_OB_FVG_SCALP','S16_GOLDEN_SQUEEZE'], tf:'M30/H4'},
  };
  const playbookEntry = PLAYBOOK_UI[seRegime] || PLAYBOOK_UI['UNKNOWN'];
  const activeList = [playbookEntry.strategy, ...(playbookEntry.others || [])];
  const DD_BUDGET = 30.0;   // soglia DD sistema — solo per gauge visuale
  const portfolioDdPct = parseFloat(BOT_STATS.maxdd_pct) || 0;
  const ddColor = portfolioDdPct < 15 ? 'var(--green)' : portfolioDdPct < 20 ? '#ffd700' : '#ff4757';
  const activeSname = playbookEntry.strategy;
  const activeSt    = SE.strategies[activeSname] || {};
  const activeTF    = playbookEntry.tf;
  const balStr  = acc.balance  ? `€${acc.balance.toFixed(0)}`  : '—';
  const eqStr   = acc.equity   ? `€${acc.equity.toFixed(0)}`   : '—';
  const pnlOggiStr = (bs.pnl_today||0)>=0 ? `+€${(bs.pnl_today||0).toFixed(2)}` : `€${(bs.pnl_today||0).toFixed(2)}`;
  const pnlOggiCol = (bs.pnl_today||0)>=0 ? 'var(--green)' : 'var(--red)';

  const botPanelHtml = `
<div style="margin-top:18px; padding-top:15px; border-top:1px dashed var(--border)">

  <!-- ══ AI GOLD BOT ══ -->
  <div style="position:relative;background:linear-gradient(135deg,#0d0f12 60%,#1a1400 100%);border:1.5px solid #c8a96e60;border-radius:12px;padding:14px 14px 11px;margin-bottom:18px;overflow:hidden">
    <!-- sfondo decorativo -->
    <div style="position:absolute;top:-18px;right:-18px;width:90px;height:90px;background:radial-gradient(circle,#c8a96e18 0%,transparent 70%);pointer-events:none"></div>

    <!-- header -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:8px">
        <span style="font-size:20px">🤖</span>
        <div>
          <div style="font-size:14px;font-weight:900;color:#c8a96e;letter-spacing:.06em">MFKK AI GOLD BOT</div>
          <div style="font-size:8px;color:var(--dim);letter-spacing:.04em">XAU/USD · Sistema Multi-Strategia</div>
        </div>
      </div>
      <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:3px">
        <div style="font-size:9px;font-weight:700;color:${botOnline?'var(--green)':'#ff4757'}">${botOnline?'● ONLINE':'● OFFLINE'}</div>
        <div style="font-size:8px;font-weight:700;color:#00e676;background:#00e67618;border:1px solid #00e67640;border-radius:4px;padding:2px 7px">🤖 AUTO</div>
        <div style="font-size:8px;color:var(--dim)">Sync ${syncLabel}</div>
      </div>
    </div>

    <!-- regime → strategia attiva (playbook) + DD gauge -->
    <div style="background:#ffffff08;border:1px solid ${rm.col}35;border-radius:8px;padding:8px 10px;margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px">
        <div style="font-size:9px;color:var(--dim);letter-spacing:.06em">REGIME</div>
        <div style="font-size:11px;font-weight:800;color:${rm.col}">${rm.icon} ${rm.label}</div>
        <div style="color:var(--dim);font-size:10px">→</div>
        <div style="font-size:9px;color:var(--dim);letter-spacing:.06em">STRATEGIE ATTIVE</div>
        <div style="font-size:10px;font-weight:800;color:#c8a96e">${activeList.map(id=>SE.strategies[id]?.label||id).join(' · ')}</div>
        <div style="margin-left:auto;background:${rm.col}20;border:1px solid ${rm.col}40;border-radius:4px;padding:2px 7px;font-size:8px;font-weight:700;color:${rm.col}">${activeTF}</div>
      </div>
      <div style="display:flex;align-items:center;gap:6px;font-size:8px">
        <span style="color:var(--dim)">Sistema DD:</span>
        <div style="flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden">
          <div style="width:${Math.min(portfolioDdPct/DD_BUDGET*100,100).toFixed(0)}%;height:100%;background:${ddColor};border-radius:2px"></div>
        </div>
        <span style="font-weight:700;color:${ddColor}">${portfolioDdPct}%</span>
        <span style="color:var(--dim)">/ ${DD_BUDGET}% budget</span>
        <span style="color:${ddColor};font-weight:700">${portfolioDdPct<=DD_BUDGET?'✓ OK':'⚠ OVER'}</span>
      </div>
    </div>

    <!-- stats aggregate -->
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-bottom:10px;font-size:8px;text-align:center">
      ${[['1 MESE',BOT_STATS.pnl_1m,null],['6 MESI',BOT_STATS.pnl_6m,null],['12 MESI',BOT_STATS.pnl_12m,null],['24 MESI',BOT_STATS.pnl_24m,null],['MAX DD',-BOT_STATS.maxdd,BOT_STATS.maxdd_pct]].map(([lbl,val,ddPct])=>{
        const col = ddPct ? 'var(--red)' : (val>=0?'var(--green)':'var(--red)');
        const pctStr = ddPct ? ddPct : `lot0.01: $${Math.abs(val).toFixed(0)}`;
        return `<div style="background:#0d0f12;border:1px solid #c8a96e25;border-radius:5px;padding:5px 2px">
          <div style="color:var(--dim);margin-bottom:2px;font-size:7px">${lbl}</div>
          <div style="font-weight:800;color:${col};font-size:10px">${val>=0&&!ddPct?'+':''}\$${Math.abs(val).toFixed(0)}</div>
          <div style="font-size:7px;color:${col};opacity:0.75;margin-top:1px">${pctStr}</div>
        </div>`;
      }).join('')}
    </div>

    <!-- footer account + metriche -->
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
      <div style="display:flex;gap:10px;font-size:9px">
        <span style="color:var(--dim)">Saldo <b style="color:var(--fg)">${balStr}</b></span>
        <span style="color:var(--dim)">Equity <b style="color:var(--fg)">${eqStr}</b></span>
        <span style="color:var(--dim)">Oggi <b style="color:${pnlOggiCol}">${pnlOggiStr}</b></span>
      </div>
      <div style="display:flex;gap:8px;font-size:9px">
        <span style="color:#c8a96e">PF <b>${BOT_STATS.pf}</b></span>
        <span style="color:var(--blue)">WR <b>${BOT_STATS.wr}</b></span>
        <span style="color:var(--dim)">${BOT_STATS.n_strat} strategie · ${BOT_STATS.trades_12m} trade/anno</span>
      </div>
    </div>
  </div>

</div>`;

  const stratCardsHtml = `
<div style="margin-top:18px; padding-top:15px; border-top:1px dashed var(--border)">

  <!-- ══ LIBRERIA STRATEGIE ══ -->
  <div style="font-size:10px;color:var(--dim);font-weight:700;letter-spacing:.07em;margin-bottom:8px;display:flex;align-items:center;gap:6px">
    <span style="flex:1;height:1px;background:var(--border)"></span>
    <span>STRATEGIE DEL SISTEMA</span>
    <span style="flex:1;height:1px;background:var(--border)"></span>
  </div>
  <div style="display:grid; grid-template-columns:1fr; gap:6px">
    ${Object.entries(SE.strategies).map(([id, s]) => {
      const isActive    = activeList.includes(id);
      const isPrimary   = isActive;   // tutte le attive ottengono badge ✓ ATTIVA
      const isSecondary = false;      // rimosso: non più gerarchia primaria/secondaria
      const st = s.stats || {};
      const pnl1col   = (st.pnl_1m||0)>0  ?'var(--green)':'var(--red)';
      const pnl6col   = (st.pnl_6m||0)>0  ?'var(--green)':'var(--red)';
      const pnl12col  = (st.pnl_12m||0)>0 ?'var(--green)':'var(--red)';
      const pnl24col  = (st.pnl_24m||0)>0 ?'var(--green)':'var(--red)';
      const inds = id==='S00_MFKK'
        ? 'MFKK Score (ADX 80% + MACD 10% + CCI 10%) · BUY≥90 · SELL≥75 · fallback H1 tutti i regimi · 531 trade/anno'
        : id==='S00_MFKK_HWR'
        ? 'ADX≥35 · DI spread≥20 · MACD diff≥0.5 · CCI non OS · SELL ONLY · 83 trade/anno · MaxDD -$61'
        : id==='S05_MFKK_INTRADAY'
        ? 'MFKK Score + Supertrend + OBV · H4 TREND only · 45 trade/24m (fragile statisticamente)'
        : id==='S09_MFKK_SCALPING'
        ? 'EMA stack (20>50>100>200) + FVG retest · VOLATILE/WEAK H1 · 19 trade/24m (fragile)'
        : id==='S10_OB_FVG_SCALP'
        ? 'Order Block + FVG M15 confluenza · WEAK/RANGE M30 · ADX≥18 · ST aligned · 36 trade/anno'
        : id==='S16_GOLDEN_SQUEEZE'
        ? 'EMA200 bias + ADX≥20 + DI dominance + MACD histogram + OBV T-Channel · TREND H1 · 124 trade/anno'
        : id==='S17_CONVERGENCE_SCALP'
        ? 'EMA 13/34 crossover + StochRSI K>D + BB%B + EMA50 trend bias · VOLATILE/TREND H4 · High PF 2.71'
        : id==='S18_RANGE_REVERSAL'
        ? 'BB Band Exhaustion (bb_pct≤0.15/≥0.85) + RSI + WPR + StochRSI mean-reversion · RANGE/WEAK ADX<22 · 7-19h UTC'
        : id==='S05_V3_Sell_Exhaust'
        ? 'OBV T-Channel bear + RSI>60 + ADX≥25 + MOM<0 · Sell exhaustion TREND_UP H1'
        : id==='S01_EXHAUSTION'
        ? 'ADX/DI spread≥15 + MACD vs signal crossover · TREND_DOWN M15 (bot) / H1 (UI)'
        : id==='S13_STRUC_BREAK'
        ? 'Breakout max/min 40 barre + retest immediato · RANGE H1 · Setup strutturale'
        : 'Strategia aggregata di portafoglio · Bilanciamento dinamico · Rischio controllato';
      return `
      <div style="background:var(--bg2); border:1px solid ${isPrimary?rm.col+'70':isSecondary?rm.col+'30':'var(--border)'}; border-radius:8px; padding:9px 10px; position:relative; overflow:hidden">
        ${isActive ? `<div style="position:absolute;top:0;right:0;background:${rm.col};color:#000;font-size:7px;font-weight:900;padding:2px 6px;border-bottom-left-radius:6px">✓ ATTIVA</div>` : ''}
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px">
          <span style="font-size:11px;font-weight:700;color:${isPrimary?rm.col:isSecondary?rm.col+'bb':'var(--fg)'}">${s.label}</span>
          <div style="display:flex;gap:7px;font-size:10px">
            ${s.pf!=null ? `<span style="color:var(--green)">PF <b>${s.pf}</b></span>` : ''}
            ${s.wr!=='N/A' ? `<span style="color:var(--blue)">WR <b>${s.wr}</b></span>` : ''}
          </div>
        </div>
        <div style="font-size:8px;color:var(--dim);margin-bottom:6px;line-height:1.4">${inds}</div>
        ${st.pnl_24m==null ? `
        <div style="background:#1a1600;border:1px solid #c8a96e40;border-radius:5px;padding:6px 8px;margin-bottom:4px">
          <div style="font-size:8px;color:#c8a96e;font-weight:700;margin-bottom:2px">⏳ BACKTEST PENDENTE</div>
          <div style="font-size:7px;color:var(--dim);line-height:1.5">
            Esegui per ottenere statistiche reali:<br>
            <code style="color:#c8a96e;background:#0d0f12;padding:1px 4px;border-radius:3px">python scripts/backtest_ob_fvg_scalp.py --mt5</code><br>
            Poi ottimizza parametri:<br>
            <code style="color:#c8a96e;background:#0d0f12;padding:1px 4px;border-radius:3px">python scripts/param_optimizer.py --mt5</code>
          </div>
        </div>
        ` : `
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:3px;font-size:8px;text-align:center;margin-bottom:3px">
          ${[['1 MESE','pnl_1m','td_1m',pnl1col],['6 MESI','pnl_6m','td_6m',pnl6col],['12 MESI','pnl_12m','td_12m',pnl12col],['24 MESI','pnl_24m','td_24m',pnl24col],['MAX DD','maxdd','maxdd_pct','var(--red)']].map(([label,pkey,tdkey,col])=>{
            const v = st[pkey];
            const isDD = pkey==='maxdd';
            const displayV = isDD
              ? (v!=null ? '-$'+v : '-$—')
              : (v!=null ? (v>=0?'+':'')+`$${v}` : '+$—');
            // Riga % : P&L su capitale $1000 / DD su peak equity (maxdd_pct già calcolato)
            const pctVal = isDD
              ? (st.maxdd_pct || '—')
              : (v!=null ? `${v>=0?'+':''}${(v/1000*100).toFixed(0)}%` : '—');
            const tdVal = (!isDD && tdkey && st[tdkey]!=null)
              ? `<div style="font-size:7px;color:var(--dim);margin-top:1px">${st[tdkey]} td/gg</div>`
              : '';
            return `<div style="background:#0d0f12;border:1px solid var(--border2);border-radius:4px;padding:3px 2px">
              <div style="color:var(--dim);margin-bottom:1px">${label}</div>
              <div style="font-weight:700;color:${col}">${displayV}</div>
              <div style="font-size:7px;color:${col};opacity:0.75;margin-top:1px">${isDD?pctVal:(v!=null?pctVal:'')}</div>
              ${tdVal}
            </div>`;
          }).join('')}
        </div>
        `}
        <div style="margin-top:4px;font-size:8px;color:var(--dim);display:flex;gap:8px">
          <span>~${st.trades_12m||'?'} trade/anno</span>
          <span>Target: TP ${s.tp} · SL ${s.sl}</span>
          <span style="margin-left:auto;color:var(--dim)">Best: ${st.best_regime||'?'}</span>
        </div>
      </div>`;
    }).join('')}
  </div>
</div>`;

  // Preserva scroll di tutti i container scrollabili prima del rebuild 1s
  const _mfp  = document.querySelector('#tp-strategy .mfp');
  const _log  = document.getElementById('se-log-scroll');
  const _hist = document.getElementById('se-hist-scroll');
  const _mfpST  = _mfp  ? _mfp.scrollTop  : 0;
  const _logST  = _log  ? _log.scrollTop  : 0;
  const _histST = _hist ? _hist.scrollTop : 0;
  el.innerHTML=statusHtml+regimeHtml+botPanelHtml+pendingHtml+posHtml+histHtml+stratCardsHtml+indSnap+obPanelHtml+m15PanelHtml;
  const _mfpN  = document.querySelector('#tp-strategy .mfp');
  const _logN  = document.getElementById('se-log-scroll');
  const _histN = document.getElementById('se-hist-scroll');
  if(_mfpN)  _mfpN.scrollTop  = _mfpST;
  if(_logN)  _logN.scrollTop  = _logST;
  if(_histN) _histN.scrollTop = _histST;
}

async function seSendTradeToMt5(s) {
  const btn = event?.target;

  // Usa i dati già fetchati dal ciclo di render (evita double-check che causa falsi offline)
  // Se seLastMt5Data è troppo vecchio, facciamo un refetch
  let mt5Live = window._seLastMt5Data || null;
  if (!mt5Live) {
    mt5Live = await seFetchMt5Data();
  }
  
  const syncAge = mt5Live?.synced_at ? Math.round((Date.now()-new Date(mt5Live.synced_at).getTime())/1000) : null;
  // Soglia più generosa: 3 minuti (il bot synca ogni 20s ma potrebbe essere in un ciclo lungo)
  const botOk = syncAge !== null && syncAge < 180;

  if (!botOk) {
    seToast('🔴 Bot MT5 offline — avvia python scripts/mt5-bot.py', '#ff4757');
    return;
  }

  if (btn) { btn.disabled = true; btn.innerText = '⌛ Invio in corso...'; }

  try {
    // Il bot MT5 usa il simbolo verificato all'avvio (GOLD, XAUUSD, ecc.)
    // Passiamo 'auto' così il bot usa il simbolo che ha trovato attivo
    const res = await fetch('/api/db', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action: 'mt5_command_push',
        command: {
          direction: s.dir,
          strategy: s.name,
          tp: typeof s.tp === 'number' ? s.tp : parseFloat(String(s.tp).replace(/[^0-9.]/g,'')),
          sl: typeof s.sl === 'number' ? s.sl : parseFloat(String(s.sl).replace(/[^0-9.]/g,'')),
          symbol: mt5Live?.bot_status?.symbol || 'GOLD'
        }
      })
    });
    const j = await res.json();
    if (j.ok) {
      seToast(`✅ Ordine ${s.dir.toUpperCase()} inviato — il bot lo esegue entro 1s`, '#00e676');
      if (btn) { btn.innerText = '✓ INVIATO'; btn.style.cssText += ';background:var(--dim);opacity:0.6'; }
    } else {
      throw new Error(j.error || 'Errore server');
    }
  } catch (e) {
    seToast('❌ Errore invio: ' + e.message, '#ff4757');
    if (btn) { btn.disabled = false; btn.innerText = '🚀 RIPROVA'; }
  }
}
window.seSendTradeToMt5 = seSendTradeToMt5;

function seToast(msg, color='var(--green)'){
  let t=document.getElementById('se-toast');
  if(!t){ t=document.createElement('div'); t.id='se-toast';
    t.style.cssText='position:fixed;bottom:80px;left:50%;transform:translateX(-50%);z-index:9999;padding:8px 18px;border-radius:8px;font-size:11px;font-weight:700;pointer-events:none;transition:opacity .3s';
    document.body.appendChild(t); }
  t.style.background=color; t.style.color=color==='var(--green)'?'#000':'#fff';
  t.style.border='1px solid '+color; t.textContent=msg; t.style.opacity='1';
  clearTimeout(t._tid); t._tid=setTimeout(()=>{t.style.opacity='0';},3500);
}

function seRenderNoData(){
  const el=document.getElementById('se-content');
  if(!el)return;
  el.innerHTML=`<div style="text-align:center;padding:25px;color:var(--dim);font-size:12px">
    <div class="spinner" style="margin:0 auto 10px"></div>
    Caricamento dati candele...<br>
    <span style="font-size:10px">Recupero dati di mercato in corso</span>
  </div>`;
  // Proviamo comunque ad aggiornare i dati MT5
  seFetchMt5Data().then(mt5Data => {
    if(mt5Data) seRender(mt5Data, [], {}, false, true, new Date().getUTCHours());
  });
}

// ── INIT ──────────────────────────────────────────────────────────────────────
async function initStrategyEngine(){
  if(seTimer) clearInterval(seTimer);
  // Assegna seTimer subito (sincrono) per evitare race condition se l'utente
  // cambia tab rapidamente mentre seRefresh è in attesa della risposta API
  seTimer = setInterval(seRefresh, 1000);
  seRefresh(); // prima chiamata immediata, senza await
}
window.initStrategyEngine=initStrategyEngine;
window.seRefresh=seRefresh;
