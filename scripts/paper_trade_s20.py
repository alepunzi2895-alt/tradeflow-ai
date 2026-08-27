#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Paper trader S20_FIB_CONFLUENCE (config di principio) — 2026-08-28

Registra cosa FAREBBE S20 su M5 senza aprire ordini reali. Da lanciare periodicamente
(ogni ~5 min, o via cron/loop). Non tocca mt5-bot.py né il roster live.

Config di principio (07_self_learning_log.md 2026-08-28, OOS ultimi 8 mesi PF 1.72 / n=54):
  - ingresso CONFERMATO: zona estremo 20b + ribbon EMA20/50 al bar j, conferma direzione al bar j+1
  - struttura: higher-low / lower-high (finestra 10 vs 35 barre)
  - filtro trend HTF: EMA200 su M5
  - SL strutturale con floor ATR: min(low − 0.15·ATR, entry − 1.5·ATR)  [simmetrico per SELL]
  - TP1 = 1R (chiudi 50%, sposta stop a BE), TP2 = 2R (residuo)
  - sessione London+NY 7–19 UTC, NIENTE lunedì, cooldown 2h tra ingressi

Stato: data/s20_paper_trades.json

Uso:
  python -X utf8 scripts/paper_trade_s20.py            # un ciclo: rileva + aggiorna + stampa
  python -X utf8 scripts/paper_trade_s20.py --summary  # solo riepilogo, nessuna nuova rilevazione
"""
import sys, os, json, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import research_s20_fib_v2 as v2   # funzioni di segnale già validate (import senza caricare dati)

STATE_FILE = os.path.join(HERE, '..', 'data', 's20_paper_trades.json')
LOOKAHEAD_M5 = 288            # ~24h, coerente col backtest
COOLDOWN_S = 2 * 3600
SESSION = (7, 19)
P_PRINCIPIO = dict(band=0.25, htf='ema200', sl_atr_k=1.5, tp1='r1', tp2_r=2.0, rr_min=1.0)

MT5_LOGIN    = int(os.getenv("MT5_LOGIN", 1301224666))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "Alessandro95!")
MT5_SERVER   = os.getenv("MT5_SERVER", "XMGlobal-MT5 6")
SYMBOL_CANDIDATES = ["GOLD", "XAUUSD", "XAUUSD.m", "XAUUSD_micro"]


def _connect():
    import MetaTrader5 as mt5
    if not mt5.initialize():
        if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
            raise RuntimeError(f"mt5.initialize fallito: {mt5.last_error()}")
    for s in SYMBOL_CANDIDATES:
        if mt5.symbol_info(s) is not None:
            mt5.symbol_select(s, True)
            return mt5, s
    raise RuntimeError("Nessun simbolo GOLD/XAUUSD trovato in MT5")


def _fetch_m5(mt5, symbol, n=900):
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 1, n)  # start_pos=1 → solo barre chiuse
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"nessuna candela M5: {mt5.last_error()}")
    out = []
    for r in rates:
        c = float(r['close'])
        if c <= 0:
            continue
        try:
            vol = float(r['tick_volume']) or float(r['real_volume'])
        except Exception:
            vol = 0.0
        out.append({'t': int(r['time']), 'o': float(r['open']), 'h': float(r['high']),
                    'l': float(r['low']), 'c': c, 'v': vol})
    return out


def _load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    return {'config': P_PRINCIPIO, 'started': None, 'signals': []}


def _save_state(st):
    st['updated'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(st, f, indent=2)


def _resolve(ind, idx, setup):
    """Come v2.sim ma ritorna (pnl, reason). pnl None = ancora aperto."""
    direction, entry, sl, tp1, tp2 = setup
    n = len(v2.CANDLES_CUR)
    filled = False; booked = 0.0; stop = sl
    for j in range(idx + 1, min(idx + LOOKAHEAD_M5, n)):
        jh = v2.CANDLES_CUR[j]['h']; jl = v2.CANDLES_CUR[j]['l']
        if direction == 'buy':
            if not filled and jh >= tp1:
                booked = 0.5 * (tp1 - entry); filled = True; stop = entry
            if filled and jh >= tp2:
                return booked + 0.5 * (tp2 - entry), 'tp1+tp2'
            if jl <= stop:
                return (-(entry - stop), 'sl') if not filled else (booked + 0.5 * (stop - entry), 'tp1+be')
        else:
            if not filled and jl <= tp1:
                booked = 0.5 * (entry - tp1); filled = True; stop = entry
            if filled and jl <= tp2:
                return booked + 0.5 * (entry - tp2), 'tp1+tp2'
            if jh >= stop:
                return (-(stop - entry), 'sl') if not filled else (booked + 0.5 * (entry - stop), 'tp1+be')
    return (None, 'open') if not filled else (None, 'tp1_partial_open')


def _stats(sigs):
    closed = [s for s in sigs if s['status'] == 'closed']
    if not closed:
        return "  nessun trade chiuso ancora"
    n = len(closed); wins = [s for s in closed if s['pnl'] > 0]
    gw = sum(s['pnl'] for s in wins); gl = abs(sum(s['pnl'] for s in closed if s['pnl'] <= 0)) or 1e-9
    r_tot = sum(s['pnl'] / s['risk'] for s in closed)
    return (f"  chiusi={n}  WR={100*len(wins)/n:.0f}%  PF={gw/gl:.2f}  "
            f"P&L=${sum(s['pnl'] for s in closed):+.1f}  R_tot={r_tot:+.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary', action='store_true', help='solo riepilogo')
    a = ap.parse_args()

    st = _load_state()
    mt5, symbol = _connect()
    try:
        candles = _fetch_m5(mt5, symbol)
    finally:
        mt5.shutdown()

    ind = v2.se2.compute_all(candles)
    v2.CANDLES_CUR = candles
    n = len(candles)
    known = {s['bar_time'] for s in st['signals']}
    last_bt = max((s['bar_time'] for s in st['signals']), default=0)
    new_sigs = 0

    if not a.summary:
        # scan largo (~25h) così anche un run poco frequente non perde segnali; il dedup su
        # bar_time + il cooldown gestiscono i re-run
        for i in range(max(260, n - 300), n):
            bt = candles[i]['t']
            if bt in known:
                continue
            dt = datetime.datetime.utcfromtimestamp(bt)
            if dt.weekday() == 0:               # niente lunedì
                continue
            if not (SESSION[0] <= dt.hour < SESSION[1]):
                continue
            if bt - last_bt < COOLDOWN_S:       # cooldown 2h
                continue
            setup = v2.sig_at(ind, i, P_PRINCIPIO)
            if setup is None:
                continue
            direction, entry, sl, tp1, tp2 = setup
            risk = abs(entry - sl)
            st['signals'].append({
                'bar_time': bt,
                'bar_utc': dt.isoformat() + 'Z',
                'detected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'dir': direction, 'entry': round(entry, 2), 'sl': round(sl, 2),
                'tp1': round(tp1, 2), 'tp2': round(tp2, 2), 'risk': round(risk, 2),
                'status': 'open', 'pnl': None, 'resolution': None, 'closed_utc': None,
            })
            known.add(bt); last_bt = max(last_bt, bt); new_sigs += 1
        if st['started'] is None:
            st['started'] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # aggiorna gli aperti
    tmap = {c['t']: k for k, c in enumerate(candles)}
    resolved = 0
    for s in st['signals']:
        if s['status'] != 'open':
            continue
        idx = tmap.get(s['bar_time'])
        if idx is None:                      # segnale più vecchio della finestra fetchata
            continue
        pnl, reason = _resolve(ind, idx, (s['dir'], s['entry'], s['sl'], s['tp1'], s['tp2']))
        if pnl is not None:
            s['status'] = 'closed'; s['pnl'] = round(pnl, 2); s['resolution'] = reason
            s['closed_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            resolved += 1

    if not a.summary:
        _save_state(st)

    opens = [s for s in st['signals'] if s['status'] == 'open']
    print(f"S20 paper — {symbol} M5 · {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')}Z")
    print(f"  nuovi segnali: {new_sigs}   risolti ora: {resolved}   aperti: {len(opens)}   totali: {len(st['signals'])}")
    print(_stats(st['signals']))
    for s in opens:
        print(f"  OPEN  {s['bar_utc']}  {s['dir'].upper():4} entry={s['entry']} sl={s['sl']} tp1={s['tp1']} tp2={s['tp2']}")
    for s in sorted([x for x in st['signals'] if x['status'] == 'closed'], key=lambda x: x['bar_time'])[-5:]:
        print(f"  done  {s['bar_utc']}  {s['dir'].upper():4} {s['resolution']:12} pnl=${s['pnl']:+.1f} ({s['pnl']/s['risk']:+.2f}R)")


if __name__ == '__main__':
    main()
