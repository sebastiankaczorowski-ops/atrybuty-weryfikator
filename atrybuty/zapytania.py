"""Zapytania do kolejki weryfikacji — filtrowanie i grupowanie findingów."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field, fields, replace

from .model import PROG_DO_WIZJI, WIDOCZNE_NA_ZDJECIU


@dataclass
class Filtr:
    kategoria: str = ""
    producent: str = ""
    regula: str = ""
    warstwa: str = ""
    waga: str = ""
    atrybut: str = ""
    status: str = "otwarte"        # otwarte | zdecydowane | wszystkie
    routing: str = ""              # auto | do_wizji | do_czlowieka
    ma_zdjecie: str = ""           # tak | nie
    werdykt: str = ""              # zgodne | niezgodne | nie_widac | brak
    szukaj: str = ""
    grupuj: bool = True
    limit: int = 50
    offset: int = 0

    def jako_query(self, **nadpisz) -> str:
        from urllib.parse import urlencode
        d = {k: v for k, v in self.__dict__.items() if v not in ("", False, 0)}
        d.update(nadpisz)
        d = {k: ("1" if v is True else v) for k, v in d.items() if v not in ("", False)}
        return urlencode(d)

    @classmethod
    def z_query(cls, s: str) -> "Filtr":
        """Odtwarza filtr z query stringa — po to, żeby akcje na grupie
        (podgląd, „Zastosuj ×N", „do importu ×N") działały w tym samym
        zakresie, który człowiek widzi na ekranie.

        Stronicowanie i sam tryb grupowania nie zawężają zbioru produktów,
        więc do zasięgu grupy nie wchodzą.
        """
        from urllib.parse import parse_qsl
        pomijamy = {"grupuj", "limit", "offset", "strona", "widok"}
        pola = {f.name for f in fields(cls)} - pomijamy
        return cls(**{k: v for k, v in parse_qsl(s) if k in pola})


BAZA_SQL = """
SELECT f.*, p.nazwa, p.producent, p.kategoria, p.zdjecie, p.kolekcja,
       d.status AS status_decyzji, d.nowa_wartosc AS decyzja_wartosc,
       w.werdykt AS werdykt_wizji, w.wartosc_ze_zdjecia AS wizja_wartosc,
       w.pewnosc AS wizja_pewnosc, w.uzasadnienie AS wizja_uzasadnienie
FROM findingi f
JOIN produkty p ON p.id = f.produkt_id
LEFT JOIN decyzje d
       ON d.produkt_id = f.produkt_id
      AND d.atrybut = f.atrybut
      AND d.hasz_starej = f.hasz_starej
LEFT JOIN werdykty_wizji w
       ON w.produkt_id = f.produkt_id AND w.atrybut = f.atrybut
WHERE f.przebieg_id = :przebieg
"""


# Zasięg grupy = to, co widać po filtrach. Filtrując kategorię „łóżka"
# człowiek rozstrzyga łóżka, a nie całą grupę razem z szafkami, które akurat
# mają ten sam błąd. Ten sam zasięg obowiązuje licznik „×N", podgląd grupy,
# „Zastosuj ×N" i „do importu ×N" — trzy różne odpowiedzi na to samo pytanie
# byłyby gorsze niż jedna zła.
# Filtry zawężające ZBIÓR PRODUKTÓW wchodzą do zasięgu; status nie — zasięg
# decyzji to zawsze findingi jeszcze nierozstrzygnięte.
def zasieg(fl: Filtr | None) -> tuple[str, dict]:
    if fl is None:
        return "", {}
    return _warunki(replace(fl, status="otwarte"))


# Liczone jednym przejściem po wszystkich grupach i dołączane JOIN-em.
# Trzy skorelowane podzapytania na wiersz dawały te same liczby, ale 5 sekund
# na stronę — tu jest jedno grupowanie po 69 tys. findingów i join po kluczu.
def _staty_grup(warunki: str) -> str:
    return f"""
WITH staty AS (
    SELECT f.grupa,
           COUNT(*) AS ile_w_grupie,
           COUNT(DISTINCT IFNULL(f.proponowana_wartosc,'')) AS roznych_propozycji,
           COUNT(DISTINCT IFNULL(f.stara_wartosc,'')) AS roznych_starych
    FROM findingi f
    JOIN produkty p ON p.id = f.produkt_id
    LEFT JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut
                       AND d.hasz_starej=f.hasz_starej
    LEFT JOIN werdykty_wizji w ON w.produkt_id=f.produkt_id AND w.atrybut=f.atrybut
    WHERE f.przebieg_id = :przebieg AND d.status IS NULL{warunki}
    GROUP BY f.grupa
)
"""


def _warunki(fl: Filtr) -> tuple[str, dict]:
    sql, par = "", {}
    if fl.kategoria:
        sql += " AND p.kategoria = :kategoria"; par["kategoria"] = fl.kategoria
    if fl.producent:
        sql += " AND p.producent = :producent"; par["producent"] = fl.producent
    if fl.regula:
        sql += " AND f.regula_id = :regula"; par["regula"] = fl.regula
    if fl.warstwa:
        sql += " AND f.warstwa = :warstwa"; par["warstwa"] = fl.warstwa
    if fl.waga:
        sql += " AND f.waga = :waga"; par["waga"] = fl.waga
    if fl.atrybut:
        sql += " AND f.atrybut = :atrybut"; par["atrybut"] = fl.atrybut
    if fl.ma_zdjecie == "tak":
        sql += " AND p.zdjecie <> ''"
    elif fl.ma_zdjecie == "nie":
        sql += " AND p.zdjecie = ''"
    if fl.status == "otwarte":
        sql += " AND d.status IS NULL"
    elif fl.status == "zdecydowane":
        sql += " AND d.status IS NOT NULL"
    if fl.szukaj:
        sql += " AND (p.nazwa LIKE :szukaj OR p.id = :dokladnie)"
        par["szukaj"] = f"%{fl.szukaj}%"; par["dokladnie"] = fl.szukaj
    if fl.werdykt == "brak":
        sql += " AND w.werdykt IS NULL"
    elif fl.werdykt:
        sql += " AND w.werdykt = :werdykt"; par["werdykt"] = fl.werdykt

    # routing = bramka kosztowa
    if fl.routing == "auto":
        sql += " AND f.pewnosc >= :prog AND f.proponowana_wartosc IS NOT NULL"
        par["prog"] = PROG_DO_WIZJI
    elif fl.routing == "do_wizji":
        lista = ",".join(f"'{a}'" for a in sorted(WIDOCZNE_NA_ZDJECIU))
        sql += (f" AND f.pewnosc < :prog AND p.zdjecie <> '' AND f.atrybut IN ({lista})")
        par["prog"] = PROG_DO_WIZJI
    elif fl.routing == "do_czlowieka":
        lista = ",".join(f"'{a}'" for a in sorted(WIDOCZNE_NA_ZDJECIU))
        sql += (f" AND NOT (f.pewnosc >= :prog AND f.proponowana_wartosc IS NOT NULL)"
                f" AND NOT (f.pewnosc < :prog AND p.zdjecie <> '' AND f.atrybut IN ({lista}))")
        par["prog"] = PROG_DO_WIZJI
    return sql, par


def policz(con: sqlite3.Connection, przebieg: int, fl: Filtr) -> int:
    sql, par = _warunki(fl)
    par["przebieg"] = przebieg
    kolumna = "COUNT(DISTINCT f.grupa)" if fl.grupuj else "COUNT(*)"
    q = (f"SELECT {kolumna} FROM findingi f JOIN produkty p ON p.id=f.produkt_id "
         "LEFT JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut "
         "AND d.hasz_starej=f.hasz_starej "
         "LEFT JOIN werdykty_wizji w ON w.produkt_id=f.produkt_id AND w.atrybut=f.atrybut "
         f"WHERE f.przebieg_id=:przebieg{sql}")
    return int(con.execute(q, par).fetchone()[0])


def lista(con: sqlite3.Connection, przebieg: int, fl: Filtr) -> list[dict]:
    sql, par = _warunki(fl)
    par |= {"przebieg": przebieg, "limit": fl.limit, "offset": fl.offset}

    if fl.grupuj:
        q = (BAZA_SQL + sql +
             " GROUP BY f.grupa"
             " ORDER BY CASE f.waga WHEN 'krytyczna' THEN 0 WHEN 'srednia' THEN 1 ELSE 2 END,"
             " COUNT(*) DESC LIMIT :limit OFFSET :offset")
        # UWAGA na zasięg. Licznik MUSI znaczyć to samo, co „Zastosuj ×N".
        # Liczony po stronie przefiltrowanych wierszy pokazywał ×8 przy
        # grupie, która rozstrzygała 1569 produktów; liczony po całej grupie
        # obiecywał z kolei, że filtrując łóżka ruszymy też szafki. Jedno
        # i drugie to ten sam błąd: licznik ma znaczyć zasięg decyzji.
        q = q.replace(
            "SELECT f.*,",
            "SELECT f.*, staty.ile_w_grupie, staty.roznych_propozycji,"
            " staty.roznych_starych,")
        q = q.replace("WHERE f.przebieg_id = :przebieg",
                      "LEFT JOIN staty ON staty.grupa = f.grupa\n"
                      "WHERE f.przebieg_id = :przebieg")
        q = _staty_grup(zasieg(fl)[0]) + q
    else:
        q = (BAZA_SQL + sql +
             " ORDER BY CASE f.waga WHEN 'krytyczna' THEN 0 WHEN 'srednia' THEN 1 ELSE 2 END,"
             " f.pewnosc DESC LIMIT :limit OFFSET :offset")
        q = q.replace("SELECT f.*,", "SELECT f.*, 1 AS ile_w_grupie,"
                      " 1 AS roznych_propozycji, 1 AS roznych_starych,")

    wiersze = [dict(r) for r in con.execute(q, par)]
    for w in wiersze:
        # jednorodna = jedna stara wartość i jedna propozycja na całą grupę
        w["jednorodna"] = (w.get("roznych_propozycji", 1) <= 1
                           and w.get("roznych_starych", 1) <= 1)
    return wiersze


def czlonkowie_grupy(con: sqlite3.Connection, przebieg: int, grupa: str,
                     fl: Filtr | None = None) -> list[dict]:
    """Zasięg decyzji hurtowej — grupa zawężona filtrami, które widać na ekranie."""
    sql, par = zasieg(fl)
    q = (BAZA_SQL + " AND f.grupa = :grupa AND d.status IS NULL" + sql)
    return [dict(r) for r in con.execute(
        q, par | {"przebieg": przebieg, "grupa": grupa})]


def podglad_grupy(con: sqlite3.Connection, przebieg: int, grupa: str,
                  limit: int = 200, fl: Filtr | None = None) -> list[dict]:
    """Wszystkie produkty z tym samym problemem — do podglądu na jeden klik.

    W kolejce widać tylko reprezentanta grupy i licznik „×N identycznych".
    Zanim ktoś rozstrzygnie całą grupę jednym kliknięciem, chce zobaczyć, co
    dokładnie w niej siedzi — bo grupa łączy po (reguła, atrybut, wartość),
    a nie po wyglądzie mebla i czasem wpada do niej produkt z innej bajki.
    """
    sql, par = zasieg(fl)
    q = (BAZA_SQL + " AND f.grupa = :grupa AND d.status IS NULL" + sql +
         " ORDER BY p.producent, p.nazwa LIMIT :limit")
    return [dict(r) for r in con.execute(
        q, par | {"przebieg": przebieg, "grupa": grupa, "limit": limit})]


def policz_grupe(con: sqlite3.Connection, przebieg: int, grupa: str,
                 fl: Filtr | None = None) -> int:
    """Ile otwartych findingów w grupie — bo podgląd pokazuje najwyżej `limit`."""
    sql, par = zasieg(fl)
    q = ("SELECT COUNT(*) FROM findingi f "
         "JOIN produkty p ON p.id = f.produkt_id "
         "LEFT JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut "
         "AND d.hasz_starej=f.hasz_starej "
         "LEFT JOIN werdykty_wizji w ON w.produkt_id=f.produkt_id AND w.atrybut=f.atrybut "
         "WHERE f.przebieg_id=:przebieg AND f.grupa=:grupa AND d.status IS NULL" + sql)
    return int(con.execute(
        q, par | {"przebieg": przebieg, "grupa": grupa}).fetchone()[0])


def lista_produktami(con: sqlite3.Connection, przebieg: int, fl: Filtr
                     ) -> tuple[list[dict], int]:
    """Kolejka zwinięta do produktów: jeden kafel = jeden mebel, w środku
    wszystkie jego otwarte findingi.

    Tryb pomocniczy, nie zamiennik grupowania. Grupy schodzą 69 tys. findingów
    do 5,3 tys. decyzji, bo ta sama pomyłka siedzi na tysiącach produktów —
    praca produktami to 28 tys. wizyt, pięć razy więcej. Ale przy produkcie
    z dziesięcioma brakami klikanie ich pojedynczo w ogólnej kolejce jest
    absurdem i po to jest ten widok.
    """
    sql, par = _warunki(fl)
    par["przebieg"] = przebieg

    ile = int(con.execute(
        "SELECT COUNT(DISTINCT f.produkt_id) FROM findingi f "
        "JOIN produkty p ON p.id=f.produkt_id "
        "LEFT JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut "
        "AND d.hasz_starej=f.hasz_starej "
        "LEFT JOIN werdykty_wizji w ON w.produkt_id=f.produkt_id AND w.atrybut=f.atrybut "
        f"WHERE f.przebieg_id=:przebieg{sql}", par).fetchone()[0])

    # najpierw wybieramy produkty (strona), potem dociągamy ich findingi —
    # inaczej limit ucinałby produkt w połowie
    q_prod = (
        "SELECT f.produkt_id, COUNT(*) AS ile_findingow, "
        " MIN(CASE f.waga WHEN 'krytyczna' THEN 0 WHEN 'srednia' THEN 1 ELSE 2 END) AS waga_min "
        "FROM findingi f JOIN produkty p ON p.id=f.produkt_id "
        "LEFT JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut "
        "AND d.hasz_starej=f.hasz_starej "
        "LEFT JOIN werdykty_wizji w ON w.produkt_id=f.produkt_id AND w.atrybut=f.atrybut "
        f"WHERE f.przebieg_id=:przebieg{sql} "
        "GROUP BY f.produkt_id ORDER BY waga_min, ile_findingow DESC, f.produkt_id "
        "LIMIT :limit OFFSET :offset")
    par_prod = par | {"limit": fl.limit, "offset": fl.offset}
    kolejnosc = [r["produkt_id"] for r in con.execute(q_prod, par_prod)]
    if not kolejnosc:
        return [], ile

    miejsca = ",".join(f":p{i}" for i in range(len(kolejnosc)))
    par_f = {"przebieg": przebieg} | {f"p{i}": v for i, v in enumerate(kolejnosc)}
    q = (BAZA_SQL + f" AND f.produkt_id IN ({miejsca}) AND d.status IS NULL"
         " ORDER BY CASE f.waga WHEN 'krytyczna' THEN 0 WHEN 'srednia' THEN 1 ELSE 2 END,"
         " f.atrybut")
    wg_produktu: dict[str, dict] = {}
    for r in con.execute(q, par_f):
        w = dict(r)
        poz = wg_produktu.setdefault(w["produkt_id"], {
            "produkt_id": w["produkt_id"], "nazwa": w["nazwa"],
            "producent": w["producent"], "kolekcja": w["kolekcja"],
            "kategoria": w["kategoria"], "zdjecie": w["zdjecie"], "findingi": []})
        poz["findingi"].append(w)

    produkty = [wg_produktu[pid] for pid in kolejnosc if pid in wg_produktu]
    for poz in produkty:
        poz["gotowe"] = [f for f in poz["findingi"]
                         if f["proponowana_wartosc"] and f["pewnosc"] >= PROG_DO_WIZJI]
    return produkty, ile


@dataclass
class Slowniki:
    kategorie: list[tuple[str, int]] = field(default_factory=list)
    producenci: list[tuple[str, int]] = field(default_factory=list)
    reguly: list[tuple[str, int]] = field(default_factory=list)
    atrybuty: list[tuple[str, int]] = field(default_factory=list)


# Licznik przy opcji filtra ma znaczyć „tyle zostało do zrobienia", a nie
# „tyle było przy wgraniu eksportu". Liczony po surowej tabeli findingów
# pokazywał „Stolik (39)" długo po tym, jak wszystkie 39 zostało
# rozstrzygniętych — wybór kategorii kończył się pustą listą.
#
# Każda lista jest liczona z POZOSTAŁYMI filtrami, ale bez własnego wymiaru:
# po wybraniu producenta kategorie pokazują jego kategorie, a lista
# producentów nadal pokazuje wszystkich — inaczej nie dałoby się zmienić
# raz podjętego wyboru.
def slowniki_filtrow(con: sqlite3.Connection, przebieg: int,
                     fl: Filtr | None = None) -> Slowniki:
    baza = replace(fl or Filtr(), grupuj=False, limit=0, offset=0)

    def zbierz(wymiar: str, kolumna: str, wybrane: str,
               limit: int | None = None) -> list[tuple[str, int]]:
        sql, par = _warunki(replace(baza, **{wymiar: ""}))
        q = (f"SELECT {kolumna} AS k, COUNT(*) n "
             "FROM findingi f JOIN produkty p ON p.id=f.produkt_id "
             "LEFT JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut "
             "AND d.hasz_starej=f.hasz_starej "
             "LEFT JOIN werdykty_wizji w ON w.produkt_id=f.produkt_id AND w.atrybut=f.atrybut "
             f"WHERE f.przebieg_id=:przebieg{sql} GROUP BY 1 ORDER BY 2 DESC")
        if limit:
            q += f" LIMIT {int(limit)}"
        out = [(r["k"], r["n"]) for r in con.execute(q, par | {"przebieg": przebieg})
               if r["k"]]
        # aktualnie wybrana opcja musi zostać w liście, choćby spadła do zera
        # albo wypadła poza limit — inaczej select gubi swoją wartość
        if wybrane and wybrane not in {k for k, _ in out}:
            out.append((wybrane, 0))
        return out

    return Slowniki(
        kategorie=zbierz("kategoria", "p.kategoria", baza.kategoria),
        producenci=zbierz("producent", "p.producent", baza.producent, limit=40),
        reguly=zbierz("regula", "f.regula_id", baza.regula),
        atrybuty=zbierz("atrybut", "f.atrybut", baza.atrybut, limit=40),
    )


def statystyki(con: sqlite3.Connection, przebieg: int) -> dict:
    baza = Filtr(grupuj=False)
    return {
        "otwarte": policz(con, przebieg, Filtr(grupuj=False, status="otwarte")),
        "zdecydowane": policz(con, przebieg, Filtr(grupuj=False, status="zdecydowane")),
        "auto": policz(con, przebieg, Filtr(grupuj=False, routing="auto", status="otwarte")),
        "do_wizji": policz(con, przebieg, Filtr(grupuj=False, routing="do_wizji", status="otwarte")),
        "do_czlowieka": policz(con, przebieg, Filtr(grupuj=False, routing="do_czlowieka", status="otwarte")),
        "grupy": policz(con, przebieg, Filtr(grupuj=True, status="otwarte")),
        "krytyczne": policz(con, przebieg, Filtr(grupuj=False, waga="krytyczna", status="otwarte")),
        "wizja_niezgodne": policz(con, przebieg,
                                  Filtr(grupuj=False, werdykt="niezgodne", status="otwarte")),
        "wizja_zgodne": policz(con, przebieg,
                               Filtr(grupuj=False, werdykt="zgodne", status="otwarte")),
        "wizja_nie_widac": policz(con, przebieg,
                                  Filtr(grupuj=False, werdykt="nie_widac", status="otwarte")),
        "ze_skladowych": policz(con, przebieg,
                                Filtr(grupuj=False, regula="L0-ZE-SKLADOWYCH", status="otwarte")),
        "ze_skladowych_grup": policz(con, przebieg,
                                     Filtr(grupuj=True, regula="L0-ZE-SKLADOWYCH", status="otwarte")),
        "konflikty_skladowych": policz(con, przebieg,
                                       Filtr(grupuj=False, regula="L0-KONFLIKT", status="otwarte")),
    }


def produkt(con: sqlite3.Connection, pid: str) -> dict | None:
    r = con.execute("SELECT * FROM produkty WHERE id=?", (pid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["atrybuty"] = json.loads(d["atrybuty"] or "{}")
    d["atrybuty_surowe"] = json.loads(d["atrybuty_surowe"] or "{}")
    d["skladowe"] = json.loads(d.get("skladowe") or "{}")
    return d


# --- rozstrzygnięte -------------------------------------------------------

SQL_ROZSTRZYGNIETE = """
SELECT d.produkt_id, d.atrybut, d.status, d.nowa_wartosc, d.regula_id,
       d.uzytkownik, d.utworzono, d.hasz_starej, d.partia_id,
       p.nazwa, p.producent, p.kategoria, p.zdjecie,
       f.stara_wartosc, f.waga, f.warstwa, f.dowod, f.grupa,
       b.utworzono AS partia_data, b.wycofana AS partia_wycofana
FROM decyzje d
LEFT JOIN produkty p ON p.id = d.produkt_id
LEFT JOIN findingi f ON f.produkt_id = d.produkt_id AND f.atrybut = d.atrybut
                    AND f.hasz_starej = d.hasz_starej
LEFT JOIN partie b ON b.id = d.partia_id
"""


def rozstrzygniete(con: sqlite3.Connection, status: str = "", atrybut: str = "",
                   regula: str = "", producent: str = "", eksport: str = "",
                   szukaj: str = "", limit: int = 100, offset: int = 0
                   ) -> tuple[list[dict], int]:
    """Co zostało rozstrzygnięte i jak — z widoczną zmianą stara → nowa.

    `eksport`: czeka | wyslane — czy decyzja trafiła już do partii.
    """
    sql, par = "", {}
    if status:
        sql += " AND d.status = :status"; par["status"] = status
    if atrybut:
        sql += " AND d.atrybut = :atrybut"; par["atrybut"] = atrybut
    if regula:
        sql += " AND d.regula_id = :regula"; par["regula"] = regula
    if producent:
        sql += " AND p.producent = :producent"; par["producent"] = producent
    if eksport == "czeka":
        sql += " AND d.partia_id IS NULL AND d.status = 'zastosowana'"
    elif eksport == "wyslane":
        sql += " AND d.partia_id IS NOT NULL"
    if szukaj:
        sql += " AND (p.nazwa LIKE :szukaj OR d.produkt_id = :dokladnie)"
        par["szukaj"] = f"%{szukaj}%"; par["dokladnie"] = szukaj

    warunek = " WHERE 1=1" + sql
    ile = int(con.execute(
        "SELECT COUNT(*) FROM decyzje d LEFT JOIN produkty p ON p.id=d.produkt_id"
        + warunek, par).fetchone()[0])

    q = (SQL_ROZSTRZYGNIETE + warunek +
         " GROUP BY d.produkt_id, d.atrybut, d.hasz_starej"
         " ORDER BY d.utworzono DESC LIMIT :limit OFFSET :offset")
    par |= {"limit": limit, "offset": offset}
    return [dict(r) for r in con.execute(q, par)], ile


def statystyki_decyzji(con: sqlite3.Connection) -> dict:
    d = {r[0]: r[1] for r in con.execute(
        "SELECT status, COUNT(*) FROM decyzje GROUP BY 1")}
    return {
        "zastosowane": d.get("zastosowana", 0),
        "falszywe": d.get("falszywy_alarm", 0),
        "odlozone": d.get("odlozona", 0),
        "do_importu": d.get("do_importu", 0),
        "czeka_na_eksport": int(con.execute(
            "SELECT COUNT(*) FROM decyzje WHERE status='zastosowana'"
            " AND nowa_wartosc IS NOT NULL AND partia_id IS NULL").fetchone()[0]),
        "wyeksportowane": int(con.execute(
            "SELECT COUNT(*) FROM decyzje WHERE partia_id IS NOT NULL").fetchone()[0]),
    }


def slowniki_decyzji(con: sqlite3.Connection) -> dict:
    def zbierz(q):
        return [(r[0], r[1]) for r in con.execute(q) if r[0]]
    return {
        "atrybuty": zbierz("SELECT atrybut, COUNT(*) FROM decyzje GROUP BY 1 ORDER BY 2 DESC"),
        "reguly": zbierz("SELECT regula_id, COUNT(*) FROM decyzje GROUP BY 1 ORDER BY 2 DESC"),
        "producenci": zbierz("SELECT p.producent, COUNT(*) FROM decyzje d "
                             "JOIN produkty p ON p.id=d.produkt_id GROUP BY 1 "
                             "ORDER BY 2 DESC LIMIT 40"),
    }


# --- produkty bez danych --------------------------------------------------

SQL_BRAKI = """
SELECT id, nazwa, producent, kolekcja, kategoria, zdjecie, kompletnosc, atrybuty
FROM produkty
WHERE kompletnosc IN ('pusty','szczatkowy','bez_wymiarow')
"""


def braki(con: sqlite3.Connection, producent: str = "", kategoria: str = "",
          rodzaj: str = "", szukaj: str = "", limit: int = 100, offset: int = 0
          ) -> tuple[list[dict], int]:
    """Produkty, których nie ma sensu analizować — trzeba je zaciągnąć ze źródła."""
    sql, par = "", {}
    if producent:
        sql += " AND producent = :producent"; par["producent"] = producent
    if kategoria:
        sql += " AND kategoria = :kategoria"; par["kategoria"] = kategoria
    if rodzaj:
        sql += " AND kompletnosc = :rodzaj"; par["rodzaj"] = rodzaj
    if szukaj:
        sql += " AND (nazwa LIKE :szukaj OR id = :dokladnie)"
        par["szukaj"] = f"%{szukaj}%"; par["dokladnie"] = szukaj

    ile = int(con.execute(
        "SELECT COUNT(*) FROM produkty WHERE kompletnosc IN "
        f"('pusty','szczatkowy','bez_wymiarow'){sql}", par).fetchone()[0])

    q = SQL_BRAKI + sql + " ORDER BY producent, kolekcja, nazwa LIMIT :limit OFFSET :offset"
    par |= {"limit": limit, "offset": offset}
    wiersze = []
    for r in con.execute(q, par):
        d = dict(r)
        d["ile_atrybutow"] = len(json.loads(d.pop("atrybuty") or "{}"))
        wiersze.append(d)
    return wiersze, ile


def braki_statystyki(con: sqlite3.Connection) -> dict:
    lic = {r[0]: r[1] for r in con.execute(
        "SELECT kompletnosc, COUNT(*) FROM produkty GROUP BY 1")}
    wg_producenta = [(r[0], r[1]) for r in con.execute(
        "SELECT producent, COUNT(*) n FROM produkty "
        "WHERE kompletnosc IN ('pusty','szczatkowy','bez_wymiarow') "
        "GROUP BY 1 ORDER BY n DESC")]
    wg_kategorii = [(r[0], r[1]) for r in con.execute(
        "SELECT kategoria, COUNT(*) n FROM produkty "
        "WHERE kompletnosc IN ('pusty','szczatkowy','bez_wymiarow') "
        "GROUP BY 1 ORDER BY n DESC")]
    return {
        "pusty": lic.get("pusty", 0),
        "szczatkowy": lic.get("szczatkowy", 0),
        "bez_wymiarow": lic.get("bez_wymiarow", 0),
        "ok": lic.get("ok", 0),
        "wylaczone": lic.get("pusty", 0) + lic.get("szczatkowy", 0),
        "razem": lic.get("pusty", 0) + lic.get("szczatkowy", 0) + lic.get("bez_wymiarow", 0),
        "producenci": wg_producenta,
        "kategorie": wg_kategorii,
    }
