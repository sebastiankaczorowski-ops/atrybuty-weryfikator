"""Domknięcie pętli: czy poprawka, którą wysłaliśmy, faktycznie weszła.

Dzień wygląda tak: rano wgrywany jest świeży zrzut z bazy sklepu, w ciągu
dnia rozstrzygane są findingi, wieczorem partia idzie importem do sklepu.
Nazajutrz przychodzi nowy zrzut — i dopiero on mówi prawdę o tym, co się
naprawdę zmieniło.

Bez tego kroku „wyeksportowane" znaczy tylko „zrobiliśmy plik". Import do
sklepu potrafi przejść połowicznie, panel potrafi odrzucić wiersz po cichu,
ktoś potrafi w międzyczasie wpisać coś innego ręcznie. Ta warstwa nie
zgaduje — porównuje wartość, którą wysłaliśmy, z wartością, która przyszła
w kolejnym zrzucie, i nazywa wynik po imieniu:

    weszlo          w sklepie jest dokładnie to, co wysłaliśmy
    bez_zmian       dalej stara wartość — import nie wszedł
    inna_wartosc    zmieniło się, ale na coś innego niż nasza poprawka
    brak_atrybutu   atrybutu nie ma w zrzucie w ogóle
    brak_produktu   produktu nie ma w zrzucie

Sprawdzamy tylko partie starsze od zrzutu. Zrzut zrobiony przed wysłaniem
partii nie mógł jej jeszcze zawierać, a policzony jako „nie weszło"
generowałby fałszywy alarm co rano.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from .model import Produkt
from .tekst import do_liczby, norm

SCHEMA = """
CREATE TABLE IF NOT EXISTS weryfikacje (
    partia_id INTEGER NOT NULL,
    produkt_id TEXT NOT NULL,
    atrybut TEXT NOT NULL,
    hasz_starej TEXT NOT NULL,
    przebieg_id INTEGER,
    stan TEXT,
    oczekiwana TEXT,
    znaleziona TEXT,
    sprawdzono TEXT,
    PRIMARY KEY (partia_id, produkt_id, atrybut, hasz_starej)
);
CREATE INDEX IF NOT EXISTS ix_wer_partia ON weryfikacje(partia_id);
CREATE INDEX IF NOT EXISTS ix_wer_stan ON weryfikacje(stan);
"""

WESZLO = "weszlo"
BEZ_ZMIAN = "bez_zmian"
INNA = "inna_wartosc"
BRAK_ATRYBUTU = "brak_atrybutu"
BRAK_PRODUKTU = "brak_produktu"

OPISY = {
    WESZLO: "weszło",
    BEZ_ZMIAN: "bez zmian — import nie wszedł",
    INNA: "zmieniło się na coś innego",
    BRAK_ATRYBUTU: "atrybutu nie ma w zrzucie",
    BRAK_PRODUKTU: "produktu nie ma w zrzucie",
}


def przygotuj_baze(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
    con.commit()


def _takie_same(a: str | None, b: str | None) -> bool:
    """Porównanie odporne na to, czym te wartości różnią się bez znaczenia.

    „46" i „46,0" to ta sama liczba; „szkło, metal" i „metal, szkło" to ta
    sama lista. Gdyby porównywać napisy wprost, połowa poprawek wracałaby
    jako „inna wartość" i nikt by temu raportowi nie uwierzył.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if norm(a) == norm(b):
        return True
    la, lb = do_liczby(a), do_liczby(b)
    if la is not None and lb is not None:
        return la == lb
    czlony = lambda s: {norm(c) for c in s.split(",") if c.strip()}  # noqa: E731
    return bool(czlony(a)) and czlony(a) == czlony(b)


SQL_DO_SPRAWDZENIA = """
SELECT d.partia_id, d.produkt_id, d.atrybut, d.hasz_starej, d.nowa_wartosc,
       b.utworzono AS partia_data
FROM decyzje d
JOIN partie b ON b.id = d.partia_id
WHERE d.partia_id IS NOT NULL AND d.status = 'zastosowana'
  AND d.nowa_wartosc IS NOT NULL AND b.wycofana = 0
"""


def sprawdz(con: sqlite3.Connection, przebieg_id: int, produkty: list[Produkt],
            data_zrzutu: str | None = None) -> dict:
    """Konfrontuje wysłane poprawki ze świeżym zrzutem. Zwraca podsumowanie."""
    przygotuj_baze(con)
    wg_id = {p.id: p for p in produkty}
    teraz = datetime.now().isoformat(timespec="seconds")
    znacznik = data_zrzutu or teraz

    wiersze, podsumowanie = [], {}
    for r in con.execute(SQL_DO_SPRAWDZENIA):
        # zrzut starszy niż partia nie mógł jej jeszcze widzieć
        if r["partia_data"] and str(r["partia_data"]) > str(znacznik):
            continue

        produkt = wg_id.get(r["produkt_id"])
        oczekiwana = r["nowa_wartosc"]
        if produkt is None:
            stan, znaleziona = BRAK_PRODUKTU, None
        else:
            znaleziona = produkt.atrybuty_surowe.get(r["atrybut"])
            if znaleziona is None:
                stan = BRAK_ATRYBUTU
            elif _takie_same(znaleziona, oczekiwana):
                stan = WESZLO
            else:
                from .db import hasz
                stan = BEZ_ZMIAN if hasz(znaleziona) == r["hasz_starej"] else INNA

        podsumowanie[stan] = podsumowanie.get(stan, 0) + 1
        wiersze.append((r["partia_id"], r["produkt_id"], r["atrybut"], r["hasz_starej"],
                        przebieg_id, stan, oczekiwana, znaleziona, teraz))

    con.executemany(
        "INSERT OR REPLACE INTO weryfikacje (partia_id,produkt_id,atrybut,hasz_starej,"
        "przebieg_id,stan,oczekiwana,znaleziona,sprawdzono) VALUES (?,?,?,?,?,?,?,?,?)",
        wiersze)
    con.commit()
    podsumowanie["sprawdzonych"] = len(wiersze)
    return podsumowanie


def wg_partii(con: sqlite3.Connection) -> list[dict]:
    przygotuj_baze(con)
    q = """
    SELECT b.id, b.utworzono, b.ile, b.uwagi, b.wycofana,
           COUNT(w.stan) AS sprawdzonych,
           SUM(w.stan = 'weszlo') AS weszlo,
           SUM(w.stan = 'bez_zmian') AS bez_zmian,
           SUM(w.stan = 'inna_wartosc') AS inna,
           SUM(w.stan = 'brak_atrybutu') AS brak_atrybutu,
           SUM(w.stan = 'brak_produktu') AS brak_produktu,
           MAX(w.sprawdzono) AS ostatnio
    FROM partie b LEFT JOIN weryfikacje w ON w.partia_id = b.id
    GROUP BY b.id ORDER BY b.id DESC
    """
    return [dict(r) for r in con.execute(q)]


def szczegoly(con: sqlite3.Connection, partia_id: int | None = None,
              stan: str = "", limit: int = 300) -> list[dict]:
    przygotuj_baze(con)
    q = ("SELECT w.*, p.nazwa, p.producent FROM weryfikacje w "
         "LEFT JOIN produkty p ON p.id = w.produkt_id WHERE 1=1")
    par: dict = {"limit": limit}
    if partia_id:
        q += " AND w.partia_id = :partia"; par["partia"] = partia_id
    if stan:
        q += " AND w.stan = :stan"; par["stan"] = stan
    else:
        q += " AND w.stan <> 'weszlo'"      # domyślnie interesuje to, co nie weszło
    q += " ORDER BY w.partia_id DESC, w.produkt_id LIMIT :limit"
    return [dict(r) for r in con.execute(q, par)]


def podsumowanie(con: sqlite3.Connection) -> dict:
    przygotuj_baze(con)
    d = {r[0]: r[1] for r in con.execute(
        "SELECT stan, COUNT(*) FROM weryfikacje GROUP BY 1")}
    sprawdzonych = sum(d.values())
    return {
        "sprawdzonych": sprawdzonych,
        "weszlo": d.get(WESZLO, 0),
        "nie_weszlo": sprawdzonych - d.get(WESZLO, 0),
        "bez_zmian": d.get(BEZ_ZMIAN, 0),
        "inna": d.get(INNA, 0),
        "brak_atrybutu": d.get(BRAK_ATRYBUTU, 0),
        "brak_produktu": d.get(BRAK_PRODUKTU, 0),
        "skutecznosc": round(100 * d.get(WESZLO, 0) / sprawdzonych) if sprawdzonych else 0,
    }
