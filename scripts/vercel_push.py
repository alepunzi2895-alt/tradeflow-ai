#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Helper condiviso per POSTare/leggere su /api/db da script standalone
(fuori da mt5-bot.py, che duplica lo stesso pattern in più punti — s20_push_stats/
us30_push_stats/ls_push_stats — con MT5_SECRET/VERCEL_URL/SSL context identici).

USO:
    from vercel_push import push, get
    push('backtest_report_push', {'report': {...}})
    d = get('backtest_report_get')
"""
import json
import os
import ssl
import urllib.error
import urllib.request

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()
    _SSL_CTX.check_hostname = False
    _SSL_CTX.verify_mode = ssl.CERT_NONE

VERCEL_URL = os.getenv("VERCEL_URL", "https://tradeflow-ai-delta.vercel.app")
MT5_SECRET = os.getenv("MT5_BOT_SECRET", "tradeflow-mt5-secret")


def _post(body: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        f"{VERCEL_URL}/api/db", data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX) as r:
        return json.loads(r.read().decode('utf-8'))


def push(action: str, payload: dict, timeout: int = 20) -> dict:
    """POST autenticato (aggiunge MT5_SECRET automaticamente)."""
    return _post({'action': action, 'secret': MT5_SECRET, **payload}, timeout)


def get(action: str, payload: dict = None, timeout: int = 10) -> dict:
    """GET (via POST, come il resto dell'API) — nessun secret, per action non protette."""
    return _post({'action': action, **(payload or {})}, timeout)
