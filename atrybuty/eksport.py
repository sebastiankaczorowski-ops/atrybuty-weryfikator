"""Eksport zatwierdzonych poprawek do importu w sklepie.

Dwa pliki zawsze powstają razem:
  poprawki_*.csv  — to, co ma wejść do sklepu
  cofnij_*.csv    — stare wartości, gwarancja odwracalności bez ruszania bazy

Eksportujemy WYŁĄCZNIE zmienione pola, nie całe wiersze produktów —
minimalizuje to ryzyko nadpisania czegoś obok.
"""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime
from pathlib import Path

NAGLOWEK = ["id", "atrybut", "stara_wartosc", "nowa_wartosc", "regula_id", "uzytkownik", "data"]


def zatwierdzone(con: sqlite3.Connection, tylko_nowe_od: str | None = None) -> list[dict]:
    q = ("SELECT d.*, p.nazwa FROM decyzje d LEFT JOIN produkty p ON p.id = d.produkt_id "
         "WHERE d.status = 'zastosowana' AND d.nowa_wartosc IS NOT NULL")
    par: list = []
    if tylko_nowe_od:
        q += " AND d.utworzono >= ?"
        par.append(tylko_nowe_od)
    return [dict(r) for r in con.execute(q, par)]


def zapisz(con: sqlite3.Connection, katalog: str | Path, paczka: int | None = None,
           tylko_nowe_od: str | None = None) -> dict:
    """paczka: maksymalna liczba wierszy w pliku (pierwszy import warto ograniczyć)."""
    katalog = Path(katalog)
    katalog.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y-%m-%d_%H%M")

    wiersze = zatwierdzone(con, tylko_nowe_od)
    if paczka:
        wiersze = wiersze[:paczka]

    plik_p = katalog / f"poprawki_{stempel}.csv"
    plik_c = katalog / f"cofnij_{stempel}.csv"

    # Stara wartość leży w findingu — decyzja trzyma tylko jej hasz.
    # Trafia do obu plików, żeby każdy z nich dało się przeczytać samodzielnie.
    stare: dict[tuple[str, str, str], str] = {}
    for r in con.execute(
            "SELECT produkt_id, atrybut, hasz_starej, stara_wartosc FROM findingi"):
        stare[(r["produkt_id"], r["atrybut"], r["hasz_starej"])] = r["stara_wartosc"]

    def _stara(r: dict) -> str:
        return stare.get((r["produkt_id"], r["atrybut"], r["hasz_starej"]), "") or ""

    with plik_p.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(NAGLOWEK)
        for r in wiersze:
            w.writerow([r["produkt_id"], r["atrybut"], _stara(r), r["nowa_wartosc"],
                        r["regula_id"] or "", r["uzytkownik"] or "", r["utworzono"]])

    with plik_c.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(NAGLOWEK)
        for r in wiersze:
            w.writerow([r["produkt_id"], r["atrybut"], r["nowa_wartosc"], _stara(r),
                        r["regula_id"] or "", r["uzytkownik"] or "", r["utworzono"]])

    return {"poprawki": str(plik_p), "cofnij": str(plik_c), "wierszy": len(wiersze)}
