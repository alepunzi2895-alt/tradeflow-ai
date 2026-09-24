#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Scheda strumento ("memoria per coppia", 2026-09-24)

Per ogni strumento del registro (public/instruments.json) calcola, dal terminale MT5 e dalla
CFTC, una scheda pubblicata in dashboard:
  - caratteristiche del contratto dal broker (cifre, contract size, lotto minimo, swap)
  - costi reali: spread mediano/p90 degli ultimi 30 giorni (colonna 'spread' delle barre H1
    MT5) e rapporto costo/ATR H1 — l'indicatore chiave per capire se uno scalp può reggere
    (su XAU M5 i costi hanno ucciso ogni scalp testato, vedi directives/05_backtest.md)
  - volatilità: ATR(14) D1, range medio giornaliero %, profilo orario (ore broker più mosse)
  - correlazioni dei rendimenti giornalieri con gli altri strumenti (90 giorni e 1 anno)
  - posizionamento istituzionale COT (CFTC legacy futures-only, non-commercial) con segno
    invertito per le coppie USD/xxx
  - ricerca già fatta sullo strumento (data/research_trials.json)
Eseguita dal worker (una volta al giorno e su richiesta), mai su Vercel (serve MT5).

USO manuale: python -X utf8 scripts/instrument_profile.py [--print]
"""
import datetime
import json
import math
import os
import statistics
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import history_store as HS

CFTC_URL = 'https://publicreporting.cftc.gov/resource/6dca-aqww.json'
TRIALS_PATH = os.path.join(HERE, '..', 'data', 'research_trials.json')
PROFILE_CACHE = os.path.join(HERE, '..', 'data', 'history', 'profiles.json')


def _rates(mt5, symbol, tf, n, need_days):
    """Barre recenti con controllo di completezza: un simbolo appena attivato restituisce
    storia parziale finché il terminale non sincronizza (verificato: GBPUSD/USDJPY al primo giro)."""
    import time
    tf_attr = getattr(mt5, HS.TF_MAP[tf][0]); rows = []
    for attempt in range(6):
        r = mt5.copy_rates_from_pos(symbol, tf_attr, 0, n)
        rows = [] if r is None else list(r)
        if rows and HS.quality([{'t': int(b['time'])} for b in rows], need_days)['complete']:
            return rows
        time.sleep(2 + attempt)
    return rows


def _atr(bars, n=14):
    if len(bars) <= n:
        return None
    trs = [max(b['high'] - b['low'], abs(b['high'] - p['close']), abs(b['low'] - p['close']))
           for p, b in zip(bars[:-1], bars[1:])]
    a = sum(trs[:n]) / n
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n          # Wilder
    return a


def _pearson(x, y):
    if len(x) < 20:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    sx = math.sqrt(sum((a - mx) ** 2 for a in x)); sy = math.sqrt(sum((b - my) ** 2 for b in y))
    if not sx or not sy:
        return None
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y)) / (sx * sy), 2)


def fetch_cot(code, invert):
    q = urllib.parse.urlencode({
        '$where': f"cftc_contract_market_code='{code}'", '$order': 'report_date_as_yyyy_mm_dd DESC', '$limit': 3,
        '$select': 'report_date_as_yyyy_mm_dd,noncomm_positions_long_all,noncomm_positions_short_all,open_interest_all'})
    with urllib.request.urlopen(f'{CFTC_URL}?{q}', timeout=20) as r:
        rows = json.loads(r.read().decode())
    if not rows:
        return None
    def net(row):
        return int(row['noncomm_positions_long_all']) - int(row['noncomm_positions_short_all'])
    sign = -1 if invert else 1
    cur, prev = rows[0], rows[1] if len(rows) > 1 else None
    oi = int(cur['open_interest_all']) or 1
    n_cur = sign * net(cur)
    out = {'report_date': cur['report_date_as_yyyy_mm_dd'][:10], 'net': n_cur,
           'net_pct_oi': round(100 * n_cur / oi, 1),
           'week_change': sign * (net(cur) - net(prev)) if prev else None,
           'inverted': invert}
    out['bias'] = ('long' if out['net_pct_oi'] > 10 else 'short' if out['net_pct_oi'] < -10 else 'neutral')
    age = (datetime.date.today() - datetime.date.fromisoformat(out['report_date'])).days
    out['stale'] = age > 21                  # report settimanale: oltre 3 settimane = dato vecchio
    return out


def research_summary(asset_id):
    try:
        with open(TRIALS_PATH, encoding='utf-8') as f:
            log = json.load(f).get('log', [])
    except Exception:
        return {'trials': 0, 'recent': []}
    mine = [e for e in log if str(e.get('asset', '')).upper() == asset_id]
    return {'trials': sum(int(e.get('n_trials', 0)) for e in mine),
            'recent': [{'ts': e.get('ts', '')[:10], 'strategy': e.get('strategy_id'), 'note': e.get('note', '')[:160]}
                       for e in mine[-5:]][::-1]}


def build_profiles(mt5):
    registry = HS.load_registry()
    now = datetime.datetime.now(datetime.timezone.utc)
    profiles, daily = {}, {}
    for iid, inst in registry.items():
        p = {'id': iid, 'label': inst['label'], 'name': inst.get('name'), 'type': inst['type'],
             'ccy': inst.get('ccy', []), 'core': bool(inst.get('core'))}
        try:
            sym = HS.resolve_symbol(mt5, inst)
            if not sym:
                p['error'] = 'simbolo non disponibile presso il broker'
                profiles[iid] = p; continue
            info = mt5.symbol_info(sym)
            p['broker'] = {'symbol': sym, 'digits': info.digits, 'point': info.point,
                           'contract_size': info.trade_contract_size, 'volume_min': info.volume_min,
                           'volume_step': info.volume_step, 'swap_long': info.swap_long,
                           'swap_short': info.swap_short, 'currency_profit': info.currency_profit}
            h1 = _rates(mt5, sym, 'H1', 24 * 95, 85)
            d1 = _rates(mt5, sym, 'D1', 400, 365)
            # Costi: spread mediano/p90 ultimi 30 giorni (in prezzo) vs ATR H1
            recent = [b for b in h1 if b['time'] >= (now - datetime.timedelta(days=30)).timestamp() and b['spread'] > 0]
            spreads = sorted(float(b['spread']) * info.point for b in recent)
            bars_h1 = [{'high': float(b['high']), 'low': float(b['low']), 'close': float(b['close'])} for b in h1]
            atr_h1 = _atr(bars_h1)
            if spreads:
                med = spreads[len(spreads) // 2]; p90 = spreads[int(len(spreads) * 0.9)]
                p['costs'] = {'spread_median': round(med, info.digits + 1), 'spread_p90': round(p90, info.digits + 1),
                              'spread_now': round(info.spread * info.point, info.digits + 1),
                              'atr_h1': round(atr_h1, info.digits) if atr_h1 else None,
                              'cost_pct_atr_h1': round(100 * med / atr_h1, 1) if atr_h1 else None}
            # Volatilità
            bars_d1 = [{'high': float(b['high']), 'low': float(b['low']), 'close': float(b['close'])} for b in d1]
            atr_d1 = _atr(bars_d1)
            last90 = bars_d1[-90:]
            adr = statistics.fmean((b['high'] - b['low']) / b['close'] * 100 for b in last90) if last90 else None
            by_hour = {}
            for b in h1[-24 * 90:]:
                hr = datetime.datetime.fromtimestamp(int(b['time']), datetime.timezone.utc).hour
                by_hour.setdefault(hr, []).append(float(b['high']) - float(b['low']))
            hours = {h: statistics.fmean(v) for h, v in by_hour.items() if len(v) >= 20}
            top = sorted(hours, key=hours.get, reverse=True)[:3]
            p['volatility'] = {'atr_d1': round(atr_d1, info.digits) if atr_d1 else None,
                               'adr_pct_90d': round(adr, 2) if adr else None,
                               'active_hours_broker': top,
                               'hourly_range': {str(h): round(v, info.digits) for h, v in sorted(hours.items())}}
            daily[iid] = {datetime.datetime.fromtimestamp(int(b['time']), datetime.timezone.utc).date().isoformat(): float(b['close'])
                          for b in d1}
            p['last_close'] = float(d1[-1]['close']) if d1 else None
        except Exception as e:
            p['error'] = f'MT5: {e}'
        try:
            if inst.get('cot'):
                p['cot'] = fetch_cot(inst['cot']['code'], bool(inst['cot'].get('invert')))
                if p['cot']:
                    p['cot']['market'] = inst['cot'].get('market')
        except Exception as e:
            p['cot'] = {'error': f'CFTC non raggiungibile: {e}'}
        p['research'] = research_summary(iid)
        profiles[iid] = p

    # Correlazioni dei rendimenti giornalieri (date comuni)
    ids = [i for i in registry if len(daily.get(i, {})) > 30]
    rets = {}
    for i in ids:
        dates = sorted(daily[i]); closes = daily[i]
        rets[i] = {d: (closes[d] / closes[p0] - 1) for p0, d in zip(dates[:-1], dates[1:])}
    def corr(a, b, days):
        common = sorted(set(rets[a]) & set(rets[b]))[-days:]
        return _pearson([rets[a][d] for d in common], [rets[b][d] for d in common])
    m90 = [[corr(a, b, 90) if a != b else 1.0 for b in ids] for a in ids]
    m365 = [[corr(a, b, 260) if a != b else 1.0 for b in ids] for a in ids]
    for k, a in enumerate(ids):
        pairs = [(ids[j], m90[k][j]) for j in range(len(ids)) if j != k and m90[k][j] is not None]
        pairs.sort(key=lambda x: x[1])
        profiles[a]['correlations'] = {'most_positive': [{'id': i, 'r90': r} for i, r in pairs[::-1] if r > 0][:3],
                                       'most_negative': [{'id': i, 'r90': r} for i, r in pairs if r < 0][:3]}
    result = {'generated_at': now.isoformat(), 'instruments': profiles,
              'correlation': {'ids': ids, 'r90': m90, 'r1y': m365}}
    os.makedirs(os.path.dirname(PROFILE_CACHE), exist_ok=True)
    with open(PROFILE_CACHE, 'w', encoding='utf-8') as f:
        json.dump(result, f)
    return result


def cached_age_hours():
    try:
        with open(PROFILE_CACHE, encoding='utf-8') as f:
            ts = json.load(f)['generated_at']
        return (datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(ts)).total_seconds() / 3600
    except Exception:
        return None


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    import MetaTrader5 as mt5
    if not mt5.initialize():
        sys.exit(f'MT5 initialize() fallito: {mt5.last_error()}')
    res = build_profiles(mt5)
    if '--print' in sys.argv:
        for iid, p in res['instruments'].items():
            c = p.get('costs', {}); v = p.get('volatility', {}); cot = p.get('cot') or {}
            print(f"{iid:7s} spread {c.get('spread_median')} = {c.get('cost_pct_atr_h1')}% ATR H1 · ADR {v.get('adr_pct_90d')}% · "
                  f"ore {v.get('active_hours_broker')} · COT {cot.get('net_pct_oi')}% OI {cot.get('bias')} ({cot.get('report_date')}) · "
                  f"corr+ {[(x['id'], x['r90']) for x in p.get('correlations', {}).get('most_positive', [])][:2]}"
                  + (f" · ERR {p['error']}" if p.get('error') else ''))
    print(f"schede: {len(res['instruments'])} · generato {res['generated_at']}")
