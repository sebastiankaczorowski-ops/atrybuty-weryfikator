"""Generator schema.yaml — zakresów liczbowych per kategoria.

Statystyka odporna: mediana i MAD, nie średnia i odchylenie standardowe.
Przy tym poziomie zaśmiecenia średnia i sigma same są zepsute przez outliery,
więc próg liczony na nich przepuszczałby właśnie te błędy, które mamy łapać.

Wynik to PROPOZYCJA do ręcznej korekty — plik jest wersjonowany w repo.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable

from . import config, kategorie
from .model import Produkt

MIN_PROBKA = 30          # poniżej cofamy się do grupy nadrzędnej
MNOZNIK_MAD = 6.0        # ile MAD-ów od mediany uznajemy jeszcze za normę


def _mad(dane: list[float], mediana: float) -> float:
    if not dane:
        return 0.0
    return statistics.median([abs(x - mediana) for x in dane]) or 0.0


def _percentyl(dane: list[float], p: float) -> float:
    if not dane:
        return 0.0
    s = sorted(dane)
    k = (len(s) - 1) * p
    dol, gora = int(k), min(int(k) + 1, len(s) - 1)
    return s[dol] + (s[gora] - s[dol]) * (k - dol)


def _statystyki(dane: list[float]) -> dict:
    med = statistics.median(dane)
    mad = _mad(dane, med)
    # granice: szersze z dwóch — percentylowych i MAD-owych, żeby nie ucinać
    # legalnych ogonów (narożniki, szafy przesuwne) na starcie
    p1, p99 = _percentyl(dane, 0.01), _percentyl(dane, 0.99)
    if mad:
        dol = min(p1, med - MNOZNIK_MAD * mad)
        gora = max(p99, med + MNOZNIK_MAD * mad)
    else:
        dol, gora = p1, p99
    return {
        "n": len(dane),
        "mediana": round(med, 1),
        "mad": round(mad, 2),
        "p1": round(p1, 1),
        "p99": round(p99, 1),
        "min_dopuszczalne": round(max(0.0, dol), 1),
        "max_dopuszczalne": round(gora, 1),
    }


def zbuduj(produkty: Iterable[Produkt]) -> dict:
    per_kat: dict[tuple[str, str], list[float]] = defaultdict(list)
    per_grupa: dict[tuple[str, str], list[float]] = defaultdict(list)
    obecnosc: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    licznik_kat: dict[str, int] = defaultdict(int)

    for p in produkty:
        licznik_kat[p.kategoria] += 1
        grupa = kategorie.grupa_nadrzedna(p.kategoria)
        for klucz, wartosc in p.liczby.items():
            per_kat[(p.kategoria, klucz)].append(wartosc)
            per_grupa[(grupa, klucz)].append(wartosc)
        for klucz in p.atrybuty:
            obecnosc[p.kategoria][klucz] += 1

    out: dict = {
        "_meta": {
            "opis": "Wygenerowane automatycznie przez schema_gen. Poprawiaj ręcznie — "
                    "plik jest wersjonowany, a regeneracja NIE nadpisuje pól "
                    "oznaczonych `recznie: true`.",
            "min_probka": MIN_PROBKA,
            "mnoznik_mad": MNOZNIK_MAD,
        },
        "kategorie": {},
        "grupy": {},
    }

    for (grupa, klucz), dane in sorted(per_grupa.items()):
        if len(dane) >= MIN_PROBKA:
            out["grupy"].setdefault(grupa, {})[klucz] = _statystyki(dane)

    for kat, liczba in sorted(licznik_kat.items()):
        wpis: dict = {"liczba_produktow": liczba, "zakresy": {}, "pokrycie": {}}
        for klucz, ile in sorted(obecnosc[kat].items(), key=lambda x: -x[1]):
            udzial = ile / liczba
            wpis["pokrycie"][klucz] = round(udzial, 3)
        for (k, klucz), dane in per_kat.items():
            if k != kat or len(dane) < MIN_PROBKA:
                continue
            wpis["zakresy"][klucz] = _statystyki(dane)
        # atrybuty obecne u >=90% produktów kategorii uznajemy za wymagane
        wpis["wymagane"] = [k for k, u in wpis["pokrycie"].items() if u >= 0.90]
        out["kategorie"][kat] = wpis

    return out


def zakres(kategoria: str, atrybut: str) -> dict | None:
    """Zakres dla (kategoria, atrybut), z cofnięciem do grupy nadrzędnej."""
    s = config.schema()
    wpis = s.get("kategorie", {}).get(kategoria, {}).get("zakresy", {}).get(atrybut)
    if wpis:
        return wpis
    grupa = kategorie.grupa_nadrzedna(kategoria)
    return s.get("grupy", {}).get(grupa, {}).get(atrybut)
