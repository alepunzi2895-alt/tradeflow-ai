#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Listener live segnali Telegram — FASE 1: SOLO LOG, nessun ordine (2026-09-07)

Ascolta in tempo reale il canale Telegram configurato e logga i segnali riconosciuti
(stesso parser di parse_telegram_signals.py — riusato, non duplicato) man mano che
arrivano. NON apre/chiude/modifica NESSUN ordine MT5 — è la fase di osservazione prima
di un'eventuale Fase 2 (esecuzione reale), che va attivata solo con conferma esplicita
separata.

Setup (una tantum, DA FARE DALL'UTENTE, mai da Claude):
  1. Vai su https://my.telegram.org/apps (login con le tue credenziali) e crea un'app
     per ottenere api_id/api_hash.
  2. Aggiungi a .env (mai committare):
       TELEGRAM_API_ID=...
       TELEGRAM_API_HASH=...
       TELEGRAM_CHANNEL_ID=2112242007   # IvanTrades - VIP, dall'export del 2026-09-07
  3. Primo avvio: `python telegram_signal_listener.py` — Telethon chiede numero di
     telefono + codice OTP nel terminale (login interattivo, lo fai tu). Dopo il primo
     login la sessione viene salvata in data/telegram_session.session (gitignored) e
     i run successivi non richiedono di rifare il login.

USO:
    python telegram_signal_listener.py                 # ascolta e stampa/logga
    python telegram_signal_listener.py --backfill 20    # stampa gli ultimi 20 messaggi (test parser)

Log: data/telegram_live_signals.jsonl (append-only, un JSON per riga, gitignored — stessa
policy di riservatezza di data/telegram_signals.json, vedi directives/02_strategies.md).
"""
import argparse
import asyncio
import datetime
import json
import os
import re

from dotenv import load_dotenv

from parse_telegram_signals import ENTRY_PAT, SL_PAT, TP_PAT, _GOLD_ALIASES

load_dotenv()

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')
SESSION_PATH = os.path.join(DATA, 'telegram_session')
LOG_PATH = os.path.join(DATA, 'telegram_live_signals.jsonl')

API_ID = os.getenv('TELEGRAM_API_ID')
API_HASH = os.getenv('TELEGRAM_API_HASH')
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')

# Parole chiave per messaggi di "gestione" (BE, chiusura, SL hit) — free-text, non
# strutturati come i segnali di entry: qui vengono solo FLAGGATI per revisione manuale,
# non parsati automaticamente (il linguaggio libero rende il parsing affidabile difficile).
MANAGEMENT_KEYWORDS = re.compile(
    r'\b(BE|breakeven|SL\s*(a|to)\s*BE|chiud[io]|close|SL\s*HIT|TP\s*HIT|parziale|partial)\b',
    re.IGNORECASE,
)


def parse_message_text(txt: str) -> dict | None:
    """Riusa la stessa logica di parse_telegram_signals.py — un solo punto di verità
    per il formato dei segnali, live e storico."""
    if 'SL' not in txt or 'TP' not in txt.upper():
        return None
    first_line = txt.strip().split('\n')[0]
    match = ENTRY_PAT.search(first_line)
    if not match:
        return None
    asset_raw, direction, order_type, p1, p2 = match.groups()
    asset = asset_raw.upper()
    if asset in _GOLD_ALIASES:
        asset = 'XAUUSD'
    sl_m = SL_PAT.search(txt)
    tps_raw = TP_PAT.findall(txt)
    tps = [float(x) for x in tps_raw if x.lower() != 'open']
    return {
        'asset': asset, 'direction': direction.lower(),
        'order_type': (order_type or 'market').lower(),
        'entry_hi': float(p1), 'entry_lo': float(p2) if p2 else float(p1),
        'sl': float(sl_m.group(1)) if sl_m else None, 'tps': tps,
    }


def _log(entry: dict):
    entry['logged_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(LOG_PATH, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')


def handle_message(msg_text: str, msg_date, msg_id):
    signal = parse_message_text(msg_text)
    if signal:
        signal.update({'type': 'ENTRY_SIGNAL', 'msg_id': msg_id, 'msg_date': str(msg_date)})
        print(f"\n🔔 NUOVO SEGNALE — {signal['asset']} {signal['direction'].upper()} "
              f"{signal['entry_lo']}-{signal['entry_hi']} SL={signal['sl']} TP={signal['tps']}")
        print("   [FASE 1 — solo log, nessun ordine inviato]")
        _log(signal)
        return
    if MANAGEMENT_KEYWORDS.search(msg_text):
        print(f"\n⚠️  Possibile messaggio di gestione (BE/close/hit) — revisione manuale:")
        print(f"   {msg_text[:200]}")
        _log({'type': 'MANAGEMENT_CANDIDATE', 'text_preview': msg_text[:300],
              'msg_id': msg_id, 'msg_date': str(msg_date)})


async def _resolve_channel(client, channel_id: int, name_hint: str = None):
    """Un ID nudo è ambiguo per Telethon (non sa se è uno user o un canale) — va
    risolto esplicitamente come PeerChannel, e serve prima "scaldare" la cache
    entità dell'account con get_dialogs() (Telethon risolve solo entità già viste
    nella sessione). Fallback: cerca tra i dialoghi per titolo se l'ID fallisce."""
    from telethon.tl.types import PeerChannel

    await client.get_dialogs()  # popola la cache entità per tutti i canali/gruppi di cui l'account è membro
    try:
        return await client.get_entity(PeerChannel(channel_id))
    except Exception as e:
        print(f"Risoluzione per ID fallita ({e}) — provo per titolo tra i dialoghi...")
        if name_hint:
            async for dialog in client.iter_dialogs():
                if name_hint.lower() in (dialog.name or '').lower():
                    return dialog.entity
        raise


async def main(backfill: int = 0):
    from telethon import TelegramClient, events

    if not API_ID or not API_HASH:
        print("ERRORE: TELEGRAM_API_ID / TELEGRAM_API_HASH mancanti in .env — vedi docstring per il setup.")
        return
    if not CHANNEL_ID:
        print("ERRORE: TELEGRAM_CHANNEL_ID mancante in .env.")
        return

    client = TelegramClient(SESSION_PATH, int(API_ID), API_HASH)
    await client.start()  # primo avvio: chiede telefono + OTP nel terminale (login interattivo utente)
    print("Connesso a Telegram.")

    entity = await _resolve_channel(client, int(CHANNEL_ID), name_hint="IvanTrades")
    print(f"Canale: {entity.title}")

    if backfill:
        print(f"\n--- Backfill ultimi {backfill} messaggi (test parser, non salva in coda live) ---")
        async for msg in client.iter_messages(entity, limit=backfill):
            if msg.text:
                handle_message(msg.text, msg.date, msg.id)
        return

    @client.on(events.NewMessage(chats=entity))
    async def handler(event):
        if event.message.text:
            handle_message(event.message.text, event.message.date, event.message.id)

    print(f"\nIn ascolto su '{entity.title}' — FASE 1 (solo log). Ctrl+C per fermare.\n")
    await client.run_until_disconnected()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', type=int, default=0,
                     help='Invece di ascoltare live, testa il parser sugli ultimi N messaggi')
    args = ap.parse_args()
    asyncio.run(main(args.backfill))
