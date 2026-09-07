#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Registro cumulativo dei trial di ricerca strategie (2026-09-07)

Ogni volta che si lancia una sessione di ricerca/ottimizzazione (grid search, feature
screening, ecc.) va incrementato questo registro PRIMA di usare dsr_check()/is_promotable()
in opt_harness.py con num_trials — altrimenti il DSR diventa disonesto: conta solo i trial
della sessione corrente invece di tutti quelli mai fatti sul programma di ricerca, e con
una cadenza di ricerca giornaliera il conteggio reale cresce in fretta.

USO:
    from research_trials import record_trials, total_trials
    record_trials(42, asset="XAU", strategy_id="S09_MFKK_SCALPING", note="grid tp/sl M5")
    n = total_trials()  # usalo come num_trials in dsr_check()/is_promotable()

Nota: scrittura centralizzata (una sola sessione orchestratrice chiama record_trials dopo
aver aggregato i risultati dei subagenti) — NON pensato per scritture concorrenti da più
processi paralleli, che romperebbero il file con un read-modify-write non atomico.
"""
import datetime
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGER_PATH = os.path.join(HERE, '..', 'data', 'research_trials.json')


def _load() -> dict:
    if not os.path.exists(LEDGER_PATH):
        return {'total': 0, 'log': []}
    with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save(data: dict) -> None:
    with open(LEDGER_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def total_trials() -> int:
    """Numero cumulativo di trial mai registrati — usalo come num_trials in DSR."""
    return _load()['total']


def record_trials(n_new: int, asset: str = "", strategy_id: str = "", note: str = "") -> int:
    """Aggiunge n_new trial al registro cumulativo. Ritorna il nuovo totale.

    Chiamare UNA VOLTA per sessione di ricerca dopo aver aggregato i risultati (non per
    singola chiamata a evaluate()) — se una sessione fallisce a metà e viene rilanciata,
    passa solo i trial NUOVI effettivamente aggiunti per evitare doppio conteggio.
    """
    data = _load()
    data['total'] += n_new
    data['log'].append({
        'ts': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'n_trials': n_new,
        'cumulative_after': data['total'],
        'asset': asset,
        'strategy_id': strategy_id,
        'note': note,
    })
    _save(data)
    return data['total']


def log_summary(last_n: int = 15) -> str:
    """Riepilogo leggibile delle ultime `last_n` sessioni registrate."""
    data = _load()
    lines = [f"Totale cumulativo trial: {data['total']}"]
    for e in data['log'][-last_n:]:
        lines.append(f"  {e['ts']}  +{e['n_trials']:>4}  (tot={e['cumulative_after']:>5})  "
                      f"{e.get('asset',''):5} {e.get('strategy_id',''):24} {e.get('note','')}")
    return "\n".join(lines)


if __name__ == '__main__':
    print(log_summary(30))
