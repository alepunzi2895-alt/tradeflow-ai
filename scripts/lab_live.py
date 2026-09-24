#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Strategie del Laboratorio sul bot (2026-09-24)

Esegue dal vivo le strategie promosse dal composer (registro system/lab_strategies, vedi
lib/lab-strategies.js) con LO STESSO interprete del backtest (strategy_spec.signals /
indicator): segnale sulla candela chiusa, ingresso a mercato, stop e target calcolati come in
strategy_spec.simulate, chiusura parziale + pareggio, uscita a tempo.

Sicurezza (fail closed):
  - SOLO conto DEMO (account_info().trade_mode == ACCOUNT_TRADE_MODE_DEMO): su un conto reale
    il modulo non apre nulla e lo scrive nel log
  - lotto fisso della strategia; ogni ordine passa da execution_safety.guard_entry (limite 3
    posizioni sul conto, rischio per trade e complessivo, prezzi/stop coerenti, quotazione fresca)
    e rispetta il toggle auto-trade e la pausa news del bot
  - una posizione alla volta per strategia, max trade al giorno della specifica
  - pausa automatica (lab_autopause) quando i risultati dal vivo si allontanano dal backtest:
    dopo min_trades, PF < pf_min o win rate sotto l'atteso di wr_drop_pp punti, oppure
    max_consec_losses perdite di fila
Isolate dal resto del bot: niente StrategySelector/RiskGuardian/compounding (esclusione per
commento 'LAB' in risk_guardian/risk_manager), stato in data/lab_live_state.json (gitignored).
"""
import datetime
import json
import os
import time

import strategy_spec as SS

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(HERE, '..', 'data', 'lab_live_state.json')
TF_SECONDS = {'M5': 300, 'M15': 900, 'M30': 1800, 'H1': 3600, 'H4': 14400, 'D1': 86400}
REFRESH_S = 60


class LabRunner:
    def __init__(self, mt5, get_fn, push_fn, log, magic, entry_allowed, dry_run=False, state_path=STATE_PATH,
                 registry=None, now=time.time):
        self.mt5, self.get, self.push, self.log, self.magic = mt5, get_fn, push_fn, log, magic
        self.entry_allowed, self.dry_run, self.state_path, self.now = entry_allowed, dry_run, state_path, now
        if registry is None:
            import history_store
            registry = history_store.load_registry()
        self.registry = registry
        self.items, self.last_refresh, self.warned_real = [], 0.0, False
        self.state = self._load()

    # ── stato persistente ─────────────────────────────────────────────────────
    def _load(self):
        try:
            with open(self.state_path, encoding='utf-8') as f:
                d = json.load(f)
            d.setdefault('positions', {}); d.setdefault('last_bar', {}); d.setdefault('per_day', {})
            return d
        except Exception:
            return {'positions': {}, 'last_bar': {}, 'per_day': {}}

    def _save(self):
        try:
            tmp = self.state_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.state, f, indent=1)
            os.replace(tmp, self.state_path)
        except Exception as e:
            self.log.warning(f'[LAB] stato non salvato: {e}')

    # ── registro strategie ────────────────────────────────────────────────────
    def refresh(self, force=False):
        if not force and self.now() - self.last_refresh < REFRESH_S:
            return
        self.last_refresh = self.now()
        try:
            d = self.get('lab_strategies_get') or {}
            self.items = [x for x in d.get('items', []) if x.get('status') == 'active']
        except Exception as e:
            self.log.warning(f'[LAB] registro non letto (resto con l’ultimo noto): {e}')

    def is_demo(self):
        acc = self.mt5.account_info()
        return bool(acc) and acc.trade_mode == self.mt5.ACCOUNT_TRADE_MODE_DEMO

    def _symbol(self, instrument_id):
        inst = self.registry.get(instrument_id)
        if not inst:
            return None
        for sym in inst.get('mt5', []):
            info = self.mt5.symbol_info(sym)
            if info is None:
                continue
            if not info.visible:
                self.mt5.symbol_select(sym, True)
                info = self.mt5.symbol_info(sym)
            if info and info.visible:
                return sym
        return None

    def _closed_candles(self, symbol, tf, n=400):
        r = self.mt5.copy_rates_from_pos(symbol, getattr(self.mt5, f'TIMEFRAME_{tf}'), 0, n)
        if r is None or len(r) < 60:
            return None
        info = self.mt5.symbol_info(symbol)
        rows = [{'t': int(b['time']), 'o': float(b['open']), 'h': float(b['high']), 'l': float(b['low']),
                 'c': float(b['close']), 'v': float(b['tick_volume']), 's': float(b['spread']) * info.point} for b in r]
        return rows[:-1]                     # l'ultima barra è ancora in formazione

    # ── ciclo principale (chiamato dal bot ogni ~10s) ──────────────────────────
    def tick(self, auto_ok=True, news_paused=False):
        self.refresh()
        self.manage()
        if not self.items:
            return
        if not self.is_demo():
            if not self.warned_real:
                self.log.warning('[LAB] conto NON demo: le strategie del Laboratorio restano ferme (solo demo)')
                self.warned_real = True
            return
        for item in self.items:
            try:
                self._check_entry(item, auto_ok, news_paused)
            except Exception as e:
                self.log.warning(f"[LAB] {item.get('id')}: {e}")

    def _open_for(self, sid):
        return any(p.get('id') == sid for p in self.state['positions'].values())

    def _check_entry(self, item, auto_ok, news_paused):
        spec, sid = item['spec'], item['id']
        symbol = self._symbol(spec['instrument'])
        if not symbol:
            return
        data = self._closed_candles(symbol, spec['tf'])
        if not data:
            return
        bar_t = data[-1]['t']
        if self.state['last_bar'].get(sid) == bar_t:
            return                            # barra già valutata
        self.state['last_bar'][sid] = bar_t; self._save()
        if not auto_ok or news_paused or self._open_for(sid):
            return
        j = len(data) - 1
        if not SS.signals(data, spec['rules'])[j]:
            return
        sess = spec.get('session')
        hour = datetime.datetime.fromtimestamp(bar_t, datetime.timezone.utc).hour
        if sess and not (int(sess['from']) <= hour < int(sess['to'])):
            return
        day = datetime.datetime.fromtimestamp(bar_t, datetime.timezone.utc).strftime('%Y-%m-%d')
        key = f'{sid}:{day}'
        if self.state['per_day'].get(key, 0) >= int(spec.get('max_trades_per_day', 10) or 10):
            return
        tick = self.mt5.symbol_info_tick(symbol)
        info = self.mt5.symbol_info(symbol)
        if not tick or not info:
            return
        sign = 1 if spec['direction'] == 'long' else -1
        entry = tick.ask if sign == 1 else tick.bid
        st = spec['exit']['stop']
        # Stop come in strategy_spec.simulate (valori della candela di segnale)
        if st['type'] == 'atr':
            atr = SS.indicator(data, 'atr', int(st.get('period', 14)))[j]
            if atr is None:
                return
            stop = entry - sign * float(st['mult']) * atr
        elif st['type'] == 'pct':
            stop = entry * (1 - sign * float(st['value']) / 100)
        else:
            p = int(st['period']); atr = SS.indicator(data, 'atr', 14)[j]
            if j < p or atr is None:
                return
            w = data[j - p + 1:j + 1]; buf = float(st.get('buffer_atr', 0.3)) * atr
            stop = (min(x['l'] for x in w) - buf) if sign == 1 else (max(x['h'] for x in w) + buf)
        risk = (entry - stop) * sign
        if risk <= 0:
            return
        target = entry + sign * float(spec['exit']['take_r']) * risk
        d = info.digits
        request = {'action': self.mt5.TRADE_ACTION_DEAL, 'symbol': symbol, 'volume': float(item['lot']),
                   'type': self.mt5.ORDER_TYPE_BUY if sign == 1 else self.mt5.ORDER_TYPE_SELL,
                   'price': entry, 'sl': round(stop, d), 'tp': round(target, d), 'deviation': 20, 'magic': self.magic,
                   'comment': f'TF-AI {sid}', 'type_time': self.mt5.ORDER_TIME_GTC, 'type_filling': self.mt5.ORDER_FILLING_IOC}
        from execution_safety import guard_entry, OrderRejected
        try:
            request = guard_entry(self.mt5, request, self.entry_allowed(),
                                  now=datetime.datetime.fromtimestamp(self.now(), datetime.timezone.utc))
        except (OrderRejected, AttributeError, TypeError, ValueError) as e:
            self.log.warning(f'[LAB] {sid} ingresso rifiutato dai controlli di sicurezza: {e}')
            return
        self.log.info(f"★ SEGNALE {sid} ({item.get('name')}): {spec['direction'].upper()} {symbol} {spec['tf']} "
                      f"@ {entry} SL {request['sl']} TP {request['tp']} lot {request['volume']}")
        if self.dry_run:
            ticket = f'dry-{sid}-{bar_t}'
        else:
            res = self.mt5.order_send(request)
            if not res or res.retcode != self.mt5.TRADE_RETCODE_DONE:
                self.log.warning(f"[LAB] {sid} ordine non eseguito: {getattr(res, 'comment', 'errore')}")
                return
            ticket = str(res.order)
        part = spec['exit'].get('partial')
        self.state['positions'][ticket] = {
            'id': sid, 'symbol': symbol, 'tf': spec['tf'], 'sign': sign, 'entry': entry, 'risk': risk,
            't1': entry + sign * float(part['at_r']) * risk if part else None,
            'fraction': float(part['fraction']) if part else 0.0, 'partial_done': False,
            'entry_bar': bar_t, 'time_stop_bars': spec['exit'].get('time_stop_bars'), 'lot': float(request['volume'])}
        self.state['per_day'][key] = self.state['per_day'].get(key, 0) + 1
        self._save()

    # ── gestione posizioni aperte: parziale + pareggio, uscita a tempo ─────────
    def _close(self, pos, volume, comment):
        tick = self.mt5.symbol_info_tick(pos.symbol)
        if not tick:
            return False
        req = {'action': self.mt5.TRADE_ACTION_DEAL, 'symbol': pos.symbol, 'volume': volume,
               'type': self.mt5.ORDER_TYPE_SELL if pos.type == 0 else self.mt5.ORDER_TYPE_BUY, 'position': pos.ticket,
               'price': tick.bid if pos.type == 0 else tick.ask, 'deviation': 20, 'magic': self.magic, 'comment': comment,
               'type_time': self.mt5.ORDER_TIME_GTC, 'type_filling': self.mt5.ORDER_FILLING_IOC}
        res = self.mt5.order_send(req)
        return bool(res) and res.retcode == self.mt5.TRADE_RETCODE_DONE

    def manage(self):
        if not self.state['positions']:
            return
        if self.dry_run:
            return
        open_pos = {str(p.ticket): p for p in (self.mt5.positions_get() or []) if p.magic == self.magic}
        changed = False
        for ticket, st in list(self.state['positions'].items()):
            p = open_pos.get(ticket)
            if p is None:                                   # chiusa da MT5 (stop/target)
                self.state['positions'].pop(ticket); changed = True
                self.log.info(f"[LAB] {st['id']} posizione #{ticket} chiusa")
                continue
            tick = self.mt5.symbol_info_tick(st['symbol'])
            if not tick:
                continue
            # Uscita a tempo: barre del TF della strategia trascorse dalla barra d'ingresso
            if st.get('time_stop_bars'):
                bars = int((tick.time - st['entry_bar']) // TF_SECONDS[st['tf']])
                if bars > int(st['time_stop_bars']):
                    if self._close(p, p.volume, f"TF-AI {st['id']} tempo"):
                        self.state['positions'].pop(ticket); changed = True
                        self.log.info(f"[LAB] {st['id']} uscita a tempo #{ticket}")
                    continue
            if st.get('t1') is not None and not st['partial_done']:
                px = tick.bid if st['sign'] == 1 else tick.ask
                if (px >= st['t1']) if st['sign'] == 1 else (px <= st['t1']):
                    info = self.mt5.symbol_info(st['symbol'])
                    from execution_safety import floor_volume
                    vol = floor_volume(p.volume * st['fraction'], p.volume - info.volume_min, info.volume_min,
                                       info.volume_max, info.volume_step)
                    if vol > 0 and self._close(p, vol, f"TF-AI {st['id']} parziale"):
                        self.mt5.order_send({'action': self.mt5.TRADE_ACTION_SLTP, 'symbol': st['symbol'], 'position': p.ticket,
                                             'sl': round(st['entry'], info.digits), 'tp': p.tp})
                        st['partial_done'] = True; changed = True
                        self.log.info(f"[LAB] {st['id']} parziale {vol} a {st['t1']:.5g} + stop a pareggio #{ticket}")
        if changed:
            self._save()

    # ── risultati dal vivo e pausa automatica ─────────────────────────────────
    def push_stats(self, trades):
        """trades = get_recent_trades_data() del bot (tutti i simboli, strategia dal commento)."""
        for item in self.items + []:
            sid = item['id']
            rows = sorted([t for t in (trades or []) if str(t.get('strategy', '')).startswith(sid)], key=lambda t: t['time'])
            n = len(rows)
            wins = [t['profit'] for t in rows if t['profit'] > 0]; losses = [t['profit'] for t in rows if t['profit'] <= 0]
            pf = round(sum(wins) / abs(sum(losses)), 3) if losses and sum(losses) else (None if not wins else 99.0)
            wr = round(100 * len(wins) / n, 1) if n else None
            streak = 0
            for t in reversed(rows):
                if t['profit'] > 0:
                    break
                streak += 1
            summary = {'mode': 'live-demo', 'lot': f"fisso {item['lot']}", 'config': f"{item['spec']['instrument']} {item['spec']['tf']} {item['spec']['direction']} · Laboratorio",
                       'n_total': n, 'overall': {'n': n, 'pf': pf, 'wr': wr, 'pnl': round(sum(t['profit'] for t in rows), 2)} if n else None,
                       'expected': item.get('expected'), 'consecutive_losses': streak,
                       'recent': [{'bar_utc': t['time'], 'dir': t.get('direction'), 'pnl': t['profit']} for t in rows[-8:]]}
            try:
                self.push('strat_live_push', {'key': sid, 'summary': summary})
            except Exception as e:
                self.log.debug(f'[LAB] stats {sid}: {e}')
            ks, exp = item.get('killswitch') or {}, item.get('expected') or {}
            reason = None
            if streak >= int(ks.get('max_consec_losses', 8)):
                reason = f'{streak} perdite di fila'
            elif n >= int(ks.get('min_trades', 20)):
                if pf is not None and pf < float(ks.get('pf_min', 0.8)):
                    reason = f'PF dal vivo {pf} dopo {n} trade (atteso {exp.get("pf")})'
                elif wr is not None and exp.get('wr') is not None and wr < float(exp['wr']) - float(ks.get('wr_drop_pp', 15)):
                    reason = f'win rate dal vivo {wr}% contro {exp["wr"]}% atteso dopo {n} trade'
            if reason:
                self.log.warning(f'[LAB] {sid} messa in pausa automaticamente: {reason}')
                try:
                    self.push('lab_autopause', {'id': sid, 'reason': reason})
                    self.items = [x for x in self.items if x['id'] != sid]
                except Exception as e:
                    self.log.warning(f'[LAB] pausa automatica {sid} non registrata: {e}')
