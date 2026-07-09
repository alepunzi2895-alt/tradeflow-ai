"""
TradeFlow AI — Client condiviso per chiamate Claude (Anthropic Messages API)
═══════════════════════════════════════════════════════════════════
Usato da: daily_maintenance.py (root-cause diagnosis), review_diff.py (pre-commit review)

REGOLA: ogni chiamata Python a Claude DEVE passare da call_claude()/call_claude_json()
qui dentro — mai requests.post('https://api.anthropic.com/...') duplicato altrove.

Nessun pacchetto 'anthropic' installato nel progetto: chiamata raw HTTP via
'requests', stesso schema JSON già usato in api/chat.js e api/report.js.

Lezione appesa (2026-07-09, vedi 07_self_learning_log.md): claude-sonnet-5 attiva
adaptive thinking di default se 'thinking' è omesso, e max_tokens è condiviso tra
thinking e testo visibile — quindi 'thinking' va SEMPRE passato esplicitamente e
max_tokens deve avere margine sufficiente, altrimenti si rischia risposta vuota
per troncamento silenzioso.

Design fail-open: nessuna funzione qui dentro solleva mai un'eccezione verso il
chiamante — un problema di rete/API/parsing non deve mai bloccare uno script di
manutenzione né un commit.
"""
import os
import re
import json
import logging

import requests
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger('ai_review')

ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'
ANTHROPIC_VERSION = '2023-06-01'
DEFAULT_MODEL = 'claude-sonnet-5'


def is_configured() -> bool:
    """True se ANTHROPIC_API_KEY è presente nell'ambiente (da .env o env reale)."""
    return bool(os.getenv('ANTHROPIC_API_KEY'))


def _extract_text(resp_json: dict) -> str:
    """Concatena solo i blocchi type=='text' della risposta — ignora blocchi 'thinking'."""
    blocks = resp_json.get('content') or []
    return '\n'.join(b.get('text', '') for b in blocks if b.get('type') == 'text').strip()


def _strip_json_fences(text: str) -> str:
    """Rimuove eventuali ```json ... ``` fence se il modello li ha aggiunti nonostante l'istruzione contraria."""
    text = text.strip()
    m = re.match(r'^```(?:json)?\s*(.*?)\s*```$', text, re.DOTALL)
    return m.group(1).strip() if m else text


def call_claude(system: str, user: str, *, max_tokens: int = 4000,
                 thinking: str = 'adaptive', timeout: int = 45,
                 model: str = DEFAULT_MODEL) -> dict:
    """
    Chiamata raw a /v1/messages. MAI solleva eccezioni — fail-open sempre.

    Ritorna:
      {'ok': True,  'text': str, 'raw': dict}
      {'ok': False, 'error': str}
    """
    if not is_configured():
        return {'ok': False, 'error': 'ANTHROPIC_API_KEY mancante'}

    body = {
        'model': model,
        'max_tokens': max_tokens,
        'thinking': {'type': thinking},
        'system': system,
        'messages': [{'role': 'user', 'content': user}],
    }

    try:
        r = requests.post(
            ANTHROPIC_API_URL,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': os.getenv('ANTHROPIC_API_KEY'),
                'anthropic-version': ANTHROPIC_VERSION,
            },
            json=body,
            timeout=timeout,
        )
    except requests.exceptions.Timeout:
        return {'ok': False, 'error': f'timeout dopo {timeout}s'}
    except requests.exceptions.SSLError as e:
        return {'ok': False, 'error': f'SSL error: {e}'}
    except requests.exceptions.RequestException as e:
        return {'ok': False, 'error': f'errore rete: {e}'}

    if r.status_code != 200:
        return {'ok': False, 'error': f'HTTP {r.status_code}: {r.text[:300]}'}

    try:
        data = r.json()
    except ValueError:
        return {'ok': False, 'error': 'risposta non JSON'}

    if data.get('error'):
        return {'ok': False, 'error': data['error'].get('message', str(data['error']))}

    text = _extract_text(data)
    if not text:
        stop_reason = data.get('stop_reason', '?')
        return {'ok': False, 'error': f'risposta vuota (stop_reason={stop_reason}, possibile troncamento: alzare max_tokens)'}

    return {'ok': True, 'text': text, 'raw': data}


def call_claude_json(system: str, user: str, **kwargs):
    """
    Come call_claude ma valida/parsa il testo come JSON.
    Ritorna (parsed_dict_or_None, error_str_or_None).
    """
    res = call_claude(system, user, **kwargs)
    if not res['ok']:
        return None, res['error']

    raw = _strip_json_fences(res['text'])
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f'JSON non valido: {e} — testo: {raw[:200]}'
