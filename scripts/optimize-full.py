"""
MFKK Full Optimizer - 2 anni H1 XAU/USD
=========================================
Ottimizza contemporaneamente:
  - Pesi CCI/MACD/ADX
  - Soglie score separate per BUY e SELL
  - EMA50 trend filter (on/off)
  - ATR-based TP/SL vs fissi
  - Cooling-off period tra trades
  - Min bars between same-direction entries

Obiettivo: massimizzare P&L con minimo drawdown.
"""
import urllib.request, json, time, sys, io, os

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DAYS = 730
MIN_TRADES = 150   # min trade per config valida

# ─── FETCH ───────────────────────────────────────────────────────────────────
def fetch_candles(symbol, days):
    all_candles = []
    now = int(time.time())
    start = now - days * 86400
    for from_t in range(start, now, 59 * 86400):
        to_t = min(from_t + 59 * 86400, now)
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1h&period1={from_t}&period2={to_t}"
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0','Accept':'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
                rs = d.get('chart',{}).get('result',[None])[0]
                if not rs or not rs.get('timestamp'): continue
                q = rs.get('indicators',{}).get('quote',[{}])[0]
                for i,t in enumerate(rs['timestamp']):
                    c=q.get('close',[]);h=q.get('high',[]);l=q.get('low',[]);o=q.get('open',[])
                    if i<len(c) and c[i] and i<len(h) and h[i] and i<len(l) and l[i]:
                        all_candles.append({'t':t,'o':o[i] if i<len(o) else c[i],'h':h[i],'l':l[i],'c':c[i]})
        except: pass
    seen=set(); unique=[]
    for c in all_candles:
        if c['t'] not in seen: seen.add(c['t']); unique.append(c)
    unique.sort(key=lambda x:x['t'])
    return unique

# ─── INDICATORI ───────────────────────────────────────────────────────────────
def ema(src, p):
    k=2/(p+1); v=src[0]; out=[v]
    for x in src[1:]: v=x*k+out[-1]*(1-k); out.append(v)
    return out

def sma(src, p):
    out=[None]*len(src)
    for i in range(p-1,len(src)):
        sl=src[i-p+1:i+1]
        out[i]=None if None in sl else sum(sl)/p
    return out

def calc_indicators(candles):
    n=len(candles)
    H=[x['h'] for x in candles]; L=[x['l'] for x in candles]; C=[x['c'] for x in candles]

    # CCI_S
    CCI_P,STOCH_P,SK,SD=50,50,8,8
    cci=[None]*n
    for i in range(CCI_P-1,n):
        sl=C[i-CCI_P+1:i+1]; mn=sum(sl)/CCI_P
        md=sum(abs(x-mn) for x in sl)/CCI_P
        cci[i]=0.0 if md==0 else (C[i]-mn)/(0.015*md)
    stk=[None]*n
    for i in range(CCI_P+STOCH_P-2,n):
        if cci[i] is None: continue
        w=[cci[j] for j in range(i-STOCH_P+1,i+1) if cci[j] is not None]
        if not w: continue
        lv,hv=min(w),max(w)
        stk[i]=50.0 if hv==lv else ((cci[i]-lv)/(hv-lv))*100
    stk_k=sma(stk,SK); stk_d=sma(stk_k,SD)

    # MACD
    e12=ema(C,12); e26=ema(C,26)
    macd=[e12[i]-e26[i] for i in range(n)]
    signal=ema(macd,9)
    hist=[macd[i]-signal[i] for i in range(n)]

    # ADX
    AP=10
    TR=[0.0]*n; DMP=[0.0]*n; DMM=[0.0]*n
    for i in range(1,n):
        TR[i]=max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
        up=H[i]-H[i-1]; dn=L[i-1]-L[i]
        DMP[i]=up if up>dn and up>0 else 0.0
        DMM[i]=dn if dn>up and dn>0 else 0.0
    sTR=[0.0]*n; sDMP=[0.0]*n; sDMM=[0.0]*n
    for i in range(1,n):
        sTR[i]=sTR[i-1]-sTR[i-1]/AP+TR[i]
        sDMP[i]=sDMP[i-1]-sDMP[i-1]/AP+DMP[i]
        sDMM[i]=sDMM[i-1]-sDMM[i-1]/AP+DMM[i]
    DIP=[sDMP[i]/sTR[i]*100 if sTR[i]>0 else 0.0 for i in range(n)]
    DIM=[sDMM[i]/sTR[i]*100 if sTR[i]>0 else 0.0 for i in range(n)]
    DX=[abs(DIP[i]-DIM[i])/(DIP[i]+DIM[i])*100 if (DIP[i]+DIM[i])>0 else 0.0 for i in range(n)]
    ADX=sma(DX,AP)

    # EMA50 — trend filter
    e50=ema(C,50)

    # ATR(14)
    TR14=[0.0]*n
    for i in range(1,n):
        TR14[i]=max(H[i]-L[i],abs(H[i]-C[i-1]),abs(L[i]-C[i-1]))
    ATR=sma(TR14,14)

    return {'stk_d':stk_d,'macd':macd,'signal':signal,'hist':hist,
            'ADX':ADX,'DIP':DIP,'DIM':DIM,'C':C,'H':H,'L':L,'EMA50':e50,'ATR':ATR}

# ─── SCORING (calibrato da backtest 2 anni) ───────────────────────────────────
def score_raw(cci_v, macd_v, sig_v, hist_v, adx_v, dip, dim, is_buy):
    # CCI score — trend continuation (non mean-reversion)
    cs=50
    if is_buy:
        if cci_v>=75:   cs=60
        elif cci_v>=65: cs=52
        elif cci_v>=50: cs=45
        elif cci_v>=35: cs=38
        elif cci_v>=25: cs=28
        else:           cs=18
    else:
        if cci_v<=25:   cs=65
        elif cci_v<=35: cs=58
        elif cci_v<=50: cs=50
        elif cci_v<=65: cs=44
        elif cci_v<75:  cs=40
        else:           cs=40  # OB_DEEP per SELL = esaurimento se ADX forte

    # MACD score — con exhaustion pattern
    diff=macd_v-sig_v
    str_v=min(abs(diff)/3,1)
    hb=10 if ((is_buy and hist_v>0) or (not is_buy and hist_v<0)) else 0
    ms=50
    if is_buy:
        if diff>0.5:    ms=round(65+str_v*25)+hb
        elif diff>0:    ms=60+hb
        elif diff>-1:   ms=30
        elif diff>-3:   ms=40   # exhaustion bearish
        else:           ms=15
    else:
        if diff<-0.5:   ms=round(65+str_v*25)+hb
        elif diff<0:    ms=60+hb
        elif diff<1:    ms=30
        elif diff<3:    ms=45   # exhaustion bullish (82%+ WR storico)
        else:           ms=48
    ms=max(0,min(100,ms))

    # ADX score
    diDiff=dip-dim; spread=min(abs(diDiff)/20,1)
    astr=1.0 if adx_v>=35 else 0.85 if adx_v>=27 else 0.65 if adx_v>=20 else 0.4 if adx_v>=14 else 0.2 if adx_v>=10 else 0.05
    ads=50
    if is_buy:
        if diDiff>0 and adx_v>=25:  ads=round(60+astr*25+spread*15)
        elif diDiff>0 and adx_v>=10: ads=50
        elif diDiff>0:               ads=30
        else:                        ads=5
    else:
        if diDiff<0 and adx_v>=25:  ads=round(60+astr*25+spread*15)
        elif diDiff<0 and adx_v>=10: ads=50
        elif diDiff<0:               ads=30
        else:                        ads=5
    ads=max(0,min(100,ads))
    return cs, ms, ads

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
def run_backtest(inds, cfg):
    """
    cfg keys:
      wc, wm, wa           — pesi CCI/MACD/ADX (sommano a 1)
      buy_thr, sell_thr    — soglie score separate per BUY e SELL
      ema_filter           — True = usa EMA50 come filtro trend
      tp_atr, sl_atr       — moltiplicatori ATR per TP e SL (None = usa tp_usd/sl_usd)
      tp_usd, sl_usd       — TP/SL fissi in USD
      cooldown             — bars minimi tra chiusura e nuova apertura stessa direzione
    """
    wc=cfg['wc']; wm=cfg['wm']; wa=cfg['wa']
    buy_thr=cfg.get('buy_thr',70); sell_thr=cfg.get('sell_thr',70)
    ema_filter=cfg.get('ema_filter',False)
    tp_atr=cfg.get('tp_atr',None); sl_atr=cfg.get('sl_atr',None)
    tp_usd=cfg.get('tp_usd',15);   sl_usd=cfg.get('sl_usd',10)
    cooldown=cfg.get('cooldown',0)

    C=inds['C']; n=len(C)
    trades=[]; ot=None; last_close_bar=-999; last_dir=None; last_dir_bar=-999
    START=130

    for i in range(START,n):
        cci_v=inds['stk_d'][i]; macd_v=inds['macd'][i]; sig_v=inds['signal'][i]
        hist_v=inds['hist'][i]; adx_v=inds['ADX'][i]
        dip=inds['DIP'][i]; dim=inds['DIM'][i]
        atr_v=inds['ATR'][i]; ema50=inds['EMA50'][i]; price=C[i]

        if cci_v is None or adx_v is None or atr_v is None: continue

        # Gestione trade aperto
        if ot:
            h=inds['H'][i]; l=inds['L'][i]
            tp=ot['tp']; sl=ot['sl']
            if ot['d']=='buy':
                if l<=ot['e']-sl:
                    trades.append({**ot,'pnl':-sl,'result':'SL','bars':i-ot['bar']})
                    last_close_bar=i; last_dir='buy'; last_dir_bar=i; ot=None
                elif h>=ot['e']+tp:
                    trades.append({**ot,'pnl':tp,'result':'TP','bars':i-ot['bar']})
                    last_close_bar=i; last_dir='buy'; last_dir_bar=i; ot=None
            else:
                if h>=ot['e']+sl:
                    trades.append({**ot,'pnl':-sl,'result':'SL','bars':i-ot['bar']})
                    last_close_bar=i; last_dir='sell'; last_dir_bar=i; ot=None
                elif l<=ot['e']-tp:
                    trades.append({**ot,'pnl':tp,'result':'TP','bars':i-ot['bar']})
                    last_close_bar=i; last_dir='sell'; last_dir_bar=i; ot=None
            continue

        # Calcola scores
        bs_c,bs_m,bs_a=score_raw(cci_v,macd_v,sig_v,hist_v,adx_v,dip,dim,True)
        ss_c,ss_m,ss_a=score_raw(cci_v,macd_v,sig_v,hist_v,adx_v,dip,dim,False)
        bs=round(bs_c*wc+bs_m*wm+bs_a*wa)
        ss=round(ss_c*wc+ss_m*wm+ss_a*wa)

        # EMA50 filter
        above_ema=(ema50 is not None and price>ema50)
        if ema_filter:
            if above_ema: ss=0   # no SELL se sopra EMA50
            else:         bs=0   # no BUY se sotto EMA50

        # Calcola TP/SL dinamici o fissi
        if tp_atr is not None:
            tp_val=atr_v*tp_atr; sl_val=atr_v*sl_atr
        else:
            tp_val=tp_usd; sl_val=sl_usd

        # Entry logic con soglie separate e cooldown
        dir_chosen=None
        if bs>=buy_thr and bs>ss:
            if cooldown==0 or last_dir!='buy' or (i-last_dir_bar)>=cooldown:
                dir_chosen='buy'
        elif ss>=sell_thr and ss>bs:
            if cooldown==0 or last_dir!='sell' or (i-last_dir_bar)>=cooldown:
                dir_chosen='sell'

        if dir_chosen:
            ot={'d':dir_chosen,'e':price,'bar':i,'tp':tp_val,'sl':sl_val,
                'score':bs if dir_chosen=='buy' else ss}

    # Chiudi eventuale trade aperto
    if ot:
        last_price=C[-1]
        pnl=(last_price-ot['e']) if ot['d']=='buy' else (ot['e']-last_price)
        trades.append({**ot,'pnl':pnl,'result':'OPEN','bars':n-1-ot['bar']})

    return trades

def stats(trades):
    closed=[t for t in trades if t['result']!='OPEN']
    if not closed: return None
    wins=[t for t in closed if t['pnl']>0]
    losses=[t for t in closed if t['pnl']<0]
    pnl=sum(t['pnl'] for t in closed)
    gp=sum(t['pnl'] for t in wins); gl=abs(sum(t['pnl'] for t in losses))
    pf=gp/gl if gl>0 else (999 if gp>0 else 0)
    wr=len(wins)/len(closed)*100

    # max drawdown
    eq=0; peak=0; maxdd=0
    for t in closed:
        eq+=t['pnl']; peak=max(peak,eq); maxdd=max(maxdd,peak-eq)

    buys=[t for t in closed if t['d']=='buy']
    sells=[t for t in closed if t['d']=='sell']
    bwr=len([t for t in buys if t['pnl']>0])/len(buys)*100 if buys else 0
    swr=len([t for t in sells if t['pnl']>0])/len(sells)*100 if sells else 0

    return {
        'n':len(closed),'wins':len(wins),'losses':len(losses),
        'wr':round(wr,1),'pnl':round(pnl,2),'pf':round(pf,3),
        'maxdd':round(maxdd,2),'bwr':round(bwr,1),'swr':round(swr,1),
        'bn':len(buys),'sn':len(sells)
    }

# ─── MAIN ────────────────────────────────────────────────────────────────────
def main():
    print("MFKK Full Optimizer — 2 anni XAU H1")
    print("="*60)
    print("Caricamento candele locali...")
    with open('data/xauusd_h1_730d.json', 'r') as f:
        data = json.load(f)
        candles = data.get('candles', data) if isinstance(data, dict) else data
    print(f"  {len(candles)} candele locali caricate")
    if len(candles)<500: print("ERRORE: dati insufficienti"); return

    print("Calcolo indicatori...")
    inds=calc_indicators(candles)
    print("  OK\n")

    # ── FASE 1: Grid search pesi + soglie separate BUY/SELL ──────────────────
    print("FASE 1: Grid search pesi + soglie BUY/SELL separate (EMA filter ON)")
    print("-"*60)

    best_results=[]
    tested=0
    for wc in range(10,55,5):
        for wm in range(10,55,5):
            wa=100-wc-wm
            if wa<20 or wa>85: continue
            wc_f=wc/100; wm_f=wm/100; wa_f=wa/100

            for buy_thr in [75,80,85,90]:      # BUY richiede score più alto
                for sell_thr in [68,70,72,75]:  # SELL più permissiva
                    for ema_f in [True, False]:
                        cfg={
                            'wc':wc_f,'wm':wm_f,'wa':wa_f,
                            'buy_thr':buy_thr,'sell_thr':sell_thr,
                            'ema_filter':ema_f,
                            'tp_usd':20,'sl_usd':12,'cooldown':0
                        }
                        trades=run_backtest(inds,cfg)
                        s=stats(trades)
                        if s and s['n']>=MIN_TRADES:
                            metric=s['pnl']*(1-s['maxdd']/max(s['pnl']*2,1)) if s['pnl']>0 else s['pnl']
                            best_results.append({**cfg,**s,'metric':metric})
                        tested+=1

        if wc%10==0: print(f"  {tested} combinazioni testate...")

    best_results.sort(key=lambda x:x['metric'],reverse=True)
    top=best_results[:5]

    print(f"\nTOP 5 (Fase 1 — su {tested} combinazioni):")
    print(f"{'CCI%':>5}{'MACD%':>6}{'ADX%':>5}{'BuyThr':>7}{'SellThr':>8}{'EMA':>5} | {'N':>5}{'WR%':>6}{'PnL':>9}{'PF':>6}{'DD':>8}")
    for r in top:
        print(f"{int(r['wc']*100):>5}{int(r['wm']*100):>6}{int(r['wa']*100):>5}"
              f"{r['buy_thr']:>7}{r['sell_thr']:>8}{'Y' if r['ema_filter'] else 'N':>5} | "
              f"{r['n']:>5}{r['wr']:>5.1f}%{r['pnl']:>9.1f}{r['pf']:>6.3f}{r['maxdd']:>8.1f}")

    # ── FASE 2: Ottimizza TP/SL ATR-based con i migliori pesi ────────────────
    print("\nFASE 2: ATR-based TP/SL vs fixed (top config Fase 1)")
    print("-"*60)
    best_cfg=top[0]

    atr_results=[]
    for tp_atr in [1.2,1.5,1.8,2.0,2.5]:
        for sl_atr in [0.7,0.8,1.0,1.2]:
            if tp_atr/sl_atr < 1.3: continue  # R:R minimo 1.3:1
            cfg={**best_cfg,'tp_atr':tp_atr,'sl_atr':sl_atr}
            # rimuovi tp/sl fissi
            cfg.pop('tp_usd',None); cfg.pop('sl_usd',None)
            trades=run_backtest(inds,cfg)
            s=stats(trades)
            if s and s['n']>=MIN_TRADES:
                metric=s['pnl']*(1-s['maxdd']/max(s['pnl']*2,1)) if s['pnl']>0 else s['pnl']
                atr_results.append({**cfg,**s,'metric':metric,'mode':'ATR'})

    # Aggiungi fixed TP/SL come baseline
    for tp_usd,sl_usd in [(15,10),(20,12),(25,15),(30,18)]:
        cfg={**best_cfg,'tp_usd':tp_usd,'sl_usd':sl_usd}
        cfg.pop('tp_atr',None); cfg.pop('sl_atr',None)
        trades=run_backtest(inds,cfg)
        s=stats(trades)
        if s and s['n']>=MIN_TRADES:
            metric=s['pnl']*(1-s['maxdd']/max(s['pnl']*2,1)) if s['pnl']>0 else s['pnl']
            atr_results.append({**cfg,**s,'metric':metric,'mode':f'USD TP{tp_usd}/SL{sl_usd}'})

    atr_results.sort(key=lambda x:x['metric'],reverse=True)

    print(f"\nTOP 5 (Fase 2 — ATR vs Fixed):")
    print(f"{'Modo':<20}{'BuyThr':>7}{'SellThr':>8} | {'N':>5}{'WR%':>6}{'PnL':>9}{'PF':>6}{'DD':>8}")
    for r in atr_results[:5]:
        modo=r.get('mode','?')
        if r.get('tp_atr'): modo=f"ATR TP{r['tp_atr']}x SL{r['sl_atr']}x"
        print(f"{modo:<20}{r['buy_thr']:>7}{r['sell_thr']:>8} | "
              f"{r['n']:>5}{r['wr']:>5.1f}%{r['pnl']:>9.1f}{r['pf']:>6.3f}{r['maxdd']:>8.1f}")

    # ── FASE 3: Cooldown test con la config migliore ──────────────────────────
    print("\nFASE 3: Cooldown period (bars min tra trades stessa direzione)")
    print("-"*60)
    best_atr=atr_results[0]
    cool_results=[]
    for cd in [0,2,3,5,8]:
        cfg={**best_atr,'cooldown':cd}
        trades=run_backtest(inds,cfg)
        s=stats(trades)
        if s and s['n']>=50:
            metric=s['pnl']*(1-s['maxdd']/max(s['pnl']*2,1)) if s['pnl']>0 else s['pnl']
            cool_results.append({**s,'cooldown':cd,'metric':metric})
            print(f"  cooldown={cd:2}bars: N={s['n']:4} WR={s['wr']:4.1f}% PnL={s['pnl']:8.1f} PF={s['pf']:.3f} DD={s['maxdd']:.1f} BuyWR={s['bwr']:.1f}% SellWR={s['swr']:.1f}%")

    cool_results.sort(key=lambda x:x['metric'],reverse=True)
    best_cool=cool_results[0]['cooldown']

    # ── RISULTATO FINALE ─────────────────────────────────────────────────────
    print("\n" + "="*60)
    print("CONFIGURAZIONE OTTIMALE FINALE")
    print("="*60)
    final_cfg={**best_atr,'cooldown':best_cool}
    final_trades=run_backtest(inds,final_cfg)
    final_s=stats(final_trades)

    print(f"  Pesi: CCI={int(final_cfg['wc']*100)}% MACD={int(final_cfg['wm']*100)}% ADX={int(final_cfg['wa']*100)}%")
    print(f"  EMA50 filter: {'ON' if final_cfg.get('ema_filter') else 'OFF'}")
    print(f"  Score BUY>={final_cfg['buy_thr']}  SELL>={final_cfg['sell_thr']}")
    if final_cfg.get('tp_atr'):
        print(f"  TP: {final_cfg['tp_atr']}x ATR  SL: {final_cfg['sl_atr']}x ATR")
    else:
        print(f"  TP: ${final_cfg.get('tp_usd')}  SL: ${final_cfg.get('sl_usd')}")
    print(f"  Cooldown: {best_cool} bars")
    print(f"\n  RISULTATI su {DAYS} giorni H1 XAU/USD:")
    print(f"  Trades: {final_s['n']}  (BUY {final_s['bn']} · SELL {final_s['sn']})")
    print(f"  Win Rate: {final_s['wr']}%  (BUY {final_s['bwr']}% · SELL {final_s['swr']}%)")
    print(f"  P&L: ${final_s['pnl']}  |  Profit Factor: {final_s['pf']}  |  Max DD: ${final_s['maxdd']}")

    # Monthly breakdown
    print("\n  Monthly breakdown:")
    mmap={}
    for t in final_trades:
        if t['result']=='OPEN': continue
        import datetime
        d=datetime.datetime.fromtimestamp(candles[t['bar']]['t'])
        k=f"{d.year}-{d.month:02d}"
        if k not in mmap: mmap[k]={'t':0,'w':0,'pnl':0}
        mmap[k]['t']+=1
        if t['pnl']>0: mmap[k]['w']+=1
        mmap[k]['pnl']+=t['pnl']
    neg_months=0; pos_months=0
    for k,m in sorted(mmap.items()):
        wr=m['w']/m['t']*100 if m['t']>0 else 0
        sign='✅' if m['pnl']>=0 else '❌'
        print(f"    {sign} {k}: {m['t']:3}t WR{wr:4.0f}% PnL${m['pnl']:8.1f}")
        if m['pnl']>=0: pos_months+=1
        else: neg_months+=1
    print(f"\n  Mesi positivi: {pos_months}  |  Mesi negativi: {neg_months}")

    # Salva config ottimale come JSON
    out={
        'generated':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
        'period':f'{DAYS}d H1 XAU/USD',
        'optimal_config':{
            'weights':{'cci':int(final_cfg['wc']*100),'macd':int(final_cfg['wm']*100),'adx':int(final_cfg['wa']*100)},
            'buy_threshold':final_cfg['buy_thr'],
            'sell_threshold':final_cfg['sell_thr'],
            'ema50_filter':bool(final_cfg.get('ema_filter',False)),
            'tp_atr':final_cfg.get('tp_atr'),
            'sl_atr':final_cfg.get('sl_atr'),
            'tp_usd':final_cfg.get('tp_usd'),
            'sl_usd':final_cfg.get('sl_usd'),
            'cooldown_bars':best_cool
        },
        'results':final_s
    }
    with open('optimal_config.json','w') as f: json.dump(out,f,indent=2)
    print("\n  Config salvata: optimal_config.json")
    print("  OTTIMIZZAZIONE COMPLETATA!")

if __name__=='__main__':
    main()
