#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test di scripts/lab_live.py con un MT5 finto (tempi in ORA DEL SERVER, come il vero XM).
USO: python -X utf8 scripts/test_lab_live.py"""
import datetime, logging, os, sys, tempfile, unittest
from types import SimpleNamespace as NS
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
from execution_safety import broker_utc_offset
import lab_live

NOW = datetime.datetime(2026, 9, 18, 12, tzinfo=datetime.timezone.utc)
OFF = broker_utc_offset(NOW)
H = 3600


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0; TIMEFRAME_H1 = 16385; TRADE_ACTION_DEAL = 1; TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY = 0; ORDER_TYPE_SELL = 1; ORDER_TIME_GTC = 0; ORDER_FILLING_IOC = 1; TRADE_RETCODE_DONE = 10009

    def __init__(self, closes, demo=True):
        self.mode = 0 if demo else 2
        self.sent = []; self.positions = []; self.next_ticket = 5000
        # barre H1 in ora server: l'ultima (in formazione) inizia all'ora corrente
        t_last = int(NOW.timestamp() + OFF) // H * H
        self.rates = [{'time': t_last - (len(closes) - 1 - k) * H, 'open': c - .2, 'high': c + 1.0, 'low': c - 1.0,
                       'close': c, 'tick_volume': 100, 'spread': 30} for k, c in enumerate(closes)]
        self.price = closes[-1]
        self.server_now = NOW.timestamp() + OFF

    def account_info(self): return NS(trade_mode=self.mode, equity=10000., balance=10000., margin_free=9000.)
    def symbol_info(self, s): return NS(visible=True, point=0.01, digits=2, volume_min=.01, volume_max=10., volume_step=.01)
    def symbol_select(self, s, v): return True
    def symbol_info_tick(self, s): return NS(time=self.server_now, bid=self.price, ask=self.price + .3)
    def copy_rates_from_pos(self, s, tf, pos, n): return self.rates[-n:]
    def positions_get(self): return self.positions
    def history_deals_get(self, *a): return []
    def order_calc_profit(self, typ, sym, vol, entry, exit): return (exit - entry) * 100 * vol * (1 if typ == 0 else -1)
    def order_calc_margin(self, *a): return 50.

    def order_send(self, req):
        self.sent.append(req)
        if req['action'] == self.TRADE_ACTION_DEAL and 'position' not in req:
            self.next_ticket += 1
            self.positions.append(NS(ticket=self.next_ticket, magic=req['magic'], symbol=req['symbol'], type=req['type'],
                                     volume=req['volume'], tp=req['tp'], sl=req['sl'], price_open=req['price']))
            return NS(retcode=self.TRADE_RETCODE_DONE, order=self.next_ticket)
        return NS(retcode=self.TRADE_RETCODE_DONE, order=0)


ITEM = {'id': 'LAB_ABC123', 'name': 'test', 'status': 'active', 'lot': 0.02,
        'spec': {'instrument': 'XAU', 'tf': 'H1', 'direction': 'long',
                 'rules': [{'left': 'close', 'period': 14, 'op': 'crossUp', 'right': 'number', 'value': 100, 'rightPeriod': 14}],
                 'session': None, 'exit': {'stop': {'type': 'atr', 'mult': 1.5, 'period': 14}, 'take_r': 2,
                                           'partial': {'at_r': 1, 'fraction': .5}, 'time_stop_bars': 5},
                 'max_trades_per_day': 10},
        'expected': {'pf': 1.4, 'wr': 52}, 'killswitch': {'min_trades': 20, 'pf_min': .8, 'wr_drop_pp': 15, 'max_consec_losses': 8}}
REG = {'XAU': {'id': 'XAU', 'mt5': ['GOLD']}}
# 80 barre sotto 100, poi la penultima (ultima chiusa) sopra 100 → incrocio sulla barra chiusa
CLOSES = [95 + (k % 3) * .5 for k in range(80)] + [101.0, 101.5]


def runner(mt5, pushed, allowed=True):
    log = logging.getLogger('lab-test'); log.setLevel(logging.CRITICAL)
    r = lab_live.LabRunner(mt5, get_fn=lambda a: {'items': [ITEM]}, push_fn=lambda a, p: pushed.append((a, p)),
                           log=log, magic=777, entry_allowed=lambda: allowed,
                           state_path=os.path.join(tempfile.mkdtemp(), 'lab.json'), registry=REG,
                           now=lambda: NOW.timestamp())
    return r


class LabLive(unittest.TestCase):
    def test_real_account_never_trades(self):
        m = FakeMT5(CLOSES, demo=False); r = runner(m, [])
        r.tick(); self.assertEqual(m.sent, [])

    def test_demo_entry_once_per_bar(self):
        m = FakeMT5(CLOSES); r = runner(m, [])
        r.tick()
        self.assertEqual(len(m.sent), 1)
        req = m.sent[0]
        self.assertEqual((req['symbol'], req['type'], req['comment'], req['magic']), ('GOLD', 0, 'TF-AI LAB_ABC123', 777))
        self.assertEqual(req['volume'], .02)
        self.assertLess(req['sl'], req['price']); self.assertGreater(req['tp'], req['price'])
        risk = req['price'] - req['sl']
        self.assertAlmostEqual(req['tp'] - req['price'], 2 * risk, delta=.02)       # target 2R
        r.tick(); self.assertEqual(len(m.sent), 1, 'stessa barra: nessun duplicato')

    def test_auto_trade_off_and_guard(self):
        m = FakeMT5(CLOSES); r = runner(m, [])
        r.tick(auto_ok=False); self.assertEqual(m.sent, [])
        m2 = FakeMT5(CLOSES); r2 = runner(m2, [], allowed=False)
        r2.tick(); self.assertEqual(m2.sent, [], 'guard_entry rifiuta con ingressi disabilitati')
        m3 = FakeMT5(CLOSES); m3.positions = [NS(ticket=1, magic=1, symbol='X', type=0, volume=1, tp=2, sl=1, price_open=1)] * 3
        r3 = runner(m3, []); r3.tick(); self.assertEqual(m3.sent, [], 'limite 3 posizioni sul conto')

    def test_partial_breakeven_and_time_stop(self):
        m = FakeMT5(CLOSES); r = runner(m, [])
        r.tick(); req = m.sent[0]; risk = req['price'] - req['sl']
        m.price = req['price'] + risk * 1.05                 # oltre 1R → parziale + pareggio
        r.manage()
        closes = [x for x in m.sent if x.get('position') and x['action'] == m.TRADE_ACTION_DEAL]
        sltp = [x for x in m.sent if x['action'] == m.TRADE_ACTION_SLTP]
        self.assertEqual(closes[0]['volume'], .01); self.assertEqual(round(sltp[0]['sl'], 2), round(req['price'], 2))
        r.manage(); self.assertEqual(len([x for x in m.sent if x['action'] == m.TRADE_ACTION_SLTP]), 1, 'parziale una volta sola')
        m.server_now += 7 * H                                  # oltre le 5 barre dell'uscita a tempo
        r.manage()
        self.assertTrue(any('tempo' in x.get('comment', '') for x in m.sent))

    def test_autopause_after_losing_streak(self):
        pushed = []; m = FakeMT5(CLOSES); r = runner(m, pushed); r.refresh(force=True)
        trades = [{'strategy': 'LAB_ABC123', 'time': f'2026-09-{10 + k:02d}T10:00', 'profit': -5.0, 'direction': 'buy'} for k in range(8)]
        r.push_stats(trades)
        pauses = [p for a, p in pushed if a == 'lab_autopause']
        self.assertEqual(len(pauses), 1); self.assertIn('8 perdite', pauses[0]['reason'])
        self.assertEqual(r.items, [], 'strategia tolta dagli attivi subito')
        live = [p for a, p in pushed if a == 'strat_live_push'][0]
        self.assertEqual(live['summary']['n_total'], 8)


if __name__ == '__main__':
    unittest.main(verbosity=1)
