#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Parser segnali storici da export Telegram (2026-09-07)

Estrae SOLO i dati strutturati (asset, direzione, entry range, SL, TP, timestamp UTC)
da un export JSON di Telegram Desktop ("Export chat history" → JSON). NON salva/riproduce
il testo grezzo dei messaggi (commenti, disclaimer, chat) — solo i numeri necessari per
allineare i segnali ai dati di mercato storici e studiare il setup tecnico che li precede.

USO:
    python parse_telegram_signals.py --input "<path>/result.json" --out ../data/telegram_signals.json

Formato segnali riconosciuto (case-insensitive, con o senza emoji/order-type):
    Gold buy 2271.50 - 2269.50
    SL: 2267
    TP: 2273
    TP: 2275
    ...
"""
import argparse
import json
import re

ENTRY_PAT = re.compile(
    r'^[^A-Za-z0-9]*([A-Za-z]{3,10})\s+(buy|sell)\s*(now|limit)?\s*[:\s]*'
    r'([\d]+\.?\d*)\s*-?\s*([\d]+\.?\d*)?',
    re.IGNORECASE,
)
SL_PAT = re.compile(r'SL\s*[:\s]+([\d]+\.?\d*)', re.IGNORECASE)
TP_PAT = re.compile(r'TP\s*\d*\s*[:\s]+(open|[\d]+\.?\d*)', re.IGNORECASE)

_GOLD_ALIASES = {'GOLD', 'XAUUSD', 'XAU', 'XAUUS'}


def _get_text(m: dict) -> str:
    t = m.get('text')
    if isinstance(t, str):
        return t
    if isinstance(t, list):
        return ''.join(e if isinstance(e, str) else e.get('text', '') for e in t)
    return ''


def parse_signals(messages: list, asset_filter: set = None) -> list:
    """Estrae segnali strutturati. asset_filter=None → tutti gli asset riconosciuti."""
    out = []
    for m in messages:
        txt = _get_text(m)
        if 'SL' not in txt or 'TP' not in txt.upper():
            continue
        first_line = txt.strip().split('\n')[0]
        match = ENTRY_PAT.search(first_line)
        if not match:
            continue
        asset_raw, direction, order_type, p1, p2 = match.groups()
        asset = asset_raw.upper()
        if asset in _GOLD_ALIASES:
            asset = 'XAUUSD'
        if asset_filter and asset not in asset_filter:
            continue
        sl_m = SL_PAT.search(txt)
        tps_raw = TP_PAT.findall(txt)
        tps = [float(x) for x in tps_raw if x.lower() != 'open']
        out.append({
            'ts_unix': int(m['date_unixtime']),
            'date': m.get('date'),
            'asset': asset,
            'direction': direction.lower(),
            'order_type': (order_type or 'market').lower(),
            'entry_hi': float(p1),
            'entry_lo': float(p2) if p2 else float(p1),
            'sl': float(sl_m.group(1)) if sl_m else None,
            'tps': tps,
            'has_runner': any(x.lower() == 'open' for x in tps_raw),
        })
    return out


def dedupe_consecutive(signals: list, window_sec: int = 3600) -> list:
    """Rimuove segnali duplicati/ripetuti (stesso asset+direzione+entry identico entro
    `window_sec`) — il canale a volte ri-posta lo stesso setup non ancora eseguito."""
    out = []
    seen_key = None
    seen_ts = None
    for s in sorted(signals, key=lambda x: x['ts_unix']):
        key = (s['asset'], s['direction'], s['entry_hi'], s['entry_lo'], s['sl'])
        if key == seen_key and seen_ts is not None and s['ts_unix'] - seen_ts <= window_sec:
            continue
        out.append(s)
        seen_key, seen_ts = key, s['ts_unix']
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description="Parser segnali Telegram → JSON strutturato")
    ap.add_argument('--input', required=True, help='Path al result.json esportato da Telegram Desktop')
    ap.add_argument('--out', default='../data/telegram_signals.json')
    ap.add_argument('--assets', default='XAUUSD', help='Comma-separated, es. XAUUSD,EURUSD (default: solo XAUUSD)')
    args = ap.parse_args()

    with open(args.input, encoding='utf-8') as f:
        data = json.load(f)

    asset_filter = set(a.strip().upper() for a in args.assets.split(',')) if args.assets else None
    signals = parse_signals(data['messages'], asset_filter)
    signals = dedupe_consecutive(signals)

    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump({'channel': data.get('name'), 'n_signals': len(signals), 'signals': signals},
                   f, indent=2, ensure_ascii=False)

    print(f"Estratti {len(signals)} segnali ({args.assets}) -> {args.out}")
    buys = sum(1 for s in signals if s['direction'] == 'buy')
    sells = sum(1 for s in signals if s['direction'] == 'sell')
    print(f"  buy={buys} sell={sells}")
    if signals:
        print(f"  range date: {signals[0]['date']} .. {signals[-1]['date']}")
