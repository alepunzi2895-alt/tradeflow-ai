#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TradeFlow AI — Lot sizing per la strategia "Ivan" (canale Telegram, 2026-09-07)

Tabella lottaggi consigliati dal provider (screenshot fornito dall'utente), interpolata
linearmente tra i bracket e DIMEZZATA su richiesta esplicita dell'utente ("dimezziamo i
lottaggi però per ora") come approccio prudenziale iniziale.

Nota dal provider: "I segnali che mando hanno 4 TP, perciò se avete un capitale di 600€ e
volete aprire un'operazione da 0.08 lotti, aprirete 4 operazioni da 0.02 lotti con i
corrispettivi TP" — il lotto totale va diviso equamente tra le gambe TP presenti nel segnale
(tipicamente 4, ma alcuni segnali storici ne hanno meno — vedi telegram_signals.json).
"""

# (balance_eur, total_lot_consigliato) dal provider — interpolazione lineare tra i punti
_TABLE = [
    (300, 0.04),
    (600, 0.08),
    (1000, 0.12),
    (2000, 0.25),
    (5000, 0.60),
    (10000, 1.5),
]

LOT_STEP = 0.01
MIN_LOT = 0.01


def _round_lot(lot: float) -> float:
    steps = round(lot / LOT_STEP)
    return round(max(MIN_LOT, steps * LOT_STEP), 2)


def base_total_lot(balance_eur: float) -> float:
    """Lotto totale consigliato dal provider (NON dimezzato), interpolato tra i bracket
    della tabella. Sotto il primo bracket o sopra l'ultimo: satura al valore estremo
    scalato proporzionalmente al capitale."""
    if balance_eur <= _TABLE[0][0]:
        return round(_TABLE[0][1] * (balance_eur / _TABLE[0][0]), 4)
    if balance_eur >= _TABLE[-1][0]:
        return round(_TABLE[-1][1] * (balance_eur / _TABLE[-1][0]), 4)
    for (b0, l0), (b1, l1) in zip(_TABLE, _TABLE[1:]):
        if b0 <= balance_eur <= b1:
            frac = (balance_eur - b0) / (b1 - b0)
            return round(l0 + frac * (l1 - l0), 4)
    return _TABLE[0][1]


def leg_lot(balance_eur: float, n_legs: int = 4, halve: bool = True) -> float:
    """Lotto per singola gamba TP, dopo aver diviso il totale su n_legs e applicato
    l'eventuale dimezzamento prudenziale (default: sì, come richiesto dall'utente)."""
    total = base_total_lot(balance_eur)
    if halve:
        total /= 2.0
    n_legs = max(1, n_legs)
    return _round_lot(total / n_legs)


if __name__ == '__main__':
    print(f"{'Balance':>10} {'Lotto totale':>14} {'Dimezzato':>11} {'Per gamba (÷4)':>16}")
    for b, _ in _TABLE:
        tot = base_total_lot(b)
        half = tot / 2
        print(f"{b:>9}€ {tot:>13.2f}  {half:>10.2f}  {_round_lot(half/4):>15.2f}")
