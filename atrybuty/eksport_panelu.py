"""Eksport rozstrzygniętych poprawek w formacie importu panelu (xlsx).

Partiami, i to jest cała idea: pierwsza partia na 20 produktów pokazuje, czy
panel w ogóle łyka plik, zanim puścimy tysiąc. Każda decyzja dostaje
`partia_id`, więc kolejna partia bierze tylko to, czego jeszcze nie było —
bez ręcznego pilnowania, co już poszło.

Plik zawiera WYŁĄCZNIE kolumny klucza (ID, Kod, Kod producenta, Nazwa)
i te atrybuty, które faktycznie zmieniamy. Reszta kolumn zostaje pusta.
To świadoma decyzja: mniej ryzyka, że import nadpisze coś obok — ale trzeba
sprawdzić na małej partii, czy panel traktuje pustą komórkę jako „nie
ruszaj", a nie jako „wyczyść". Dlatego pierwsza partia ma być mała.

Razem z plikiem poprawek powstaje plik cofający (stare wartości w tym samym
układzie), żeby wycofanie zmiany w sklepie było jednym importem.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import panel_format as pf


@dataclass
class Pozycja:
    produkt_id: str
    nazwa: str
    kod: str
    kod_producenta: str
    zmiany: dict[str, str] = field(default_factory=dict)       # kolumna -> nowa
    stare: dict[str, str] = field(default_factory=dict)        # kolumna -> stara
    klucze: list[tuple[str, str, str]] = field(default_factory=list)  # (pid,atr,hasz)


@dataclass
class Plan:
    """Co pójdzie do pliku, a co zostaje z powodem."""
    pozycje: list[Pozycja] = field(default_factory=list)
    pominiete: list[dict] = field(default_factory=list)
    czekajacych: int = 0

    @property
    def zmian(self) -> int:
        return sum(len(p.zmiany) for p in self.pozycje)

    def pominiete_zbiorczo(self) -> list[dict]:
        """Pominięte zwinięte do (atrybut, wartość, powód) — to jest lista do
        naprawy reguł, a nie lista produktów do klikania."""
        licznik: dict[tuple, dict] = {}
        for p in self.pominiete:
            klucz = (p["atrybut"], p["nowa_wartosc"], p["powod"])
            wpis = licznik.setdefault(klucz, {
                "atrybut": p["atrybut"], "nowa_wartosc": p["nowa_wartosc"],
                "powod": p["powod"], "ile": 0, "przyklad": p["produkt_id"]})
            wpis["ile"] += 1
        return sorted(licznik.values(), key=lambda w: -w["ile"])


SQL_CZEKAJACE = """
SELECT d.produkt_id, d.atrybut, d.nowa_wartosc, d.hasz_starej, d.utworzono,
       p.nazwa, p.kody, f.stara_wartosc
FROM decyzje d
LEFT JOIN produkty p ON p.id = d.produkt_id
LEFT JOIN findingi f ON f.produkt_id = d.produkt_id AND f.atrybut = d.atrybut
                    AND f.hasz_starej = d.hasz_starej
WHERE d.status = 'zastosowana' AND d.nowa_wartosc IS NOT NULL
  AND d.partia_id IS NULL
GROUP BY d.produkt_id, d.atrybut, d.hasz_starej
ORDER BY d.utworzono
"""


def _kody(surowe: str | None) -> dict:
    import json
    try:
        return json.loads(surowe or "{}")
    except ValueError:
        return {}


def zaplanuj(con: sqlite3.Connection, limit_produktow: int = 50) -> Plan:
    """Buduje plan partii: `limit_produktow` produktów, wszystkie ich zmiany.

    Partia liczy się w produktach, nie w decyzjach — bo wiersz w pliku to
    produkt, i rozbicie jednego produktu na dwie partie znaczyłoby dwa
    importy tego samego wiersza.
    """
    slownik = pf.wczytaj_slownik()
    kol_slownikowe = pf.kolumny_slownikowe(slownik)
    wzorzec = pf.wczytaj_wzorzec()
    znane = set(wzorzec.naglowki)
    kol_surowe = set(wzorzec.surowe)
    etykiety = pf.wczytaj_etykiety()

    plan = Plan()
    wg_produktu: dict[str, Pozycja] = {}

    for r in con.execute(SQL_CZEKAJACE):
        plan.czekajacych += 1
        kolumna = r["atrybut"]
        powod = ""

        if znane and kolumna not in znane:
            powod = "kolumny nie ma w formacie panelu"
        else:
            wartosc, powod = pf.wartosc_do_pliku(
                slownik, kolumna, r["nowa_wartosc"], kol_slownikowe, kol_surowe,
                etykiety)

        if powod:
            plan.pominiete.append({
                "produkt_id": r["produkt_id"], "nazwa": r["nazwa"] or "",
                "atrybut": kolumna, "nowa_wartosc": r["nowa_wartosc"],
                "powod": powod})
            continue

        poz = wg_produktu.get(r["produkt_id"])
        if poz is None:
            if len(wg_produktu) >= limit_produktow:
                continue                      # reszta pójdzie w następnej partii
            kody = _kody(r["kody"])
            poz = Pozycja(produkt_id=r["produkt_id"], nazwa=r["nazwa"] or "",
                          kod=kody.get("kod produktu", ""),
                          kod_producenta=kody.get("kod producenta", ""))
            wg_produktu[r["produkt_id"]] = poz
            plan.pozycje.append(poz)

        poz.zmiany[kolumna] = wartosc
        stara = r["stara_wartosc"] or ""
        stara_do_pliku, _ = pf.wartosc_do_pliku(slownik, kolumna, stara,
                                                kol_slownikowe, kol_surowe, etykiety)
        poz.stare[kolumna] = stara_do_pliku or stara
        poz.klucze.append((r["produkt_id"], r["atrybut"], r["hasz_starej"]))

    return plan


def _arkusz(wzorzec: pf.Wzorzec, pozycje: list[Pozycja], pole: str, stempel: str):
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Worksheet"

    for wiersz in wzorzec.preambula:
        ws.append(list(wiersz))
    # wiersz 4 to metadane eksportu — podmieniamy na nasze
    if len(wzorzec.preambula) >= 4:
        ws.cell(4, 1, "Export date:")
        ws.cell(4, 3, stempel)
        ws.cell(4, 4, "Items: ")
        ws.cell(4, 5, len(pozycje))

    while ws.max_row < pf.WIERSZ_NAGLOWKA - 1:   # nagłówki muszą trafić w wiersz 6
        ws.append([])

    ws.append(list(wzorzec.naglowki))
    for c in ws[pf.WIERSZ_NAGLOWKA]:
        c.font = Font(bold=True)

    indeks = {h: i for i, h in enumerate(wzorzec.naglowki)}
    for poz in pozycje:
        wiersz = [None] * len(wzorzec.naglowki)
        # panel trzyma ID jako liczbę — trzymajmy się tego, żeby import nie
        # musiał zgadywać typu komórki
        ident = int(poz.produkt_id) if poz.produkt_id.isdigit() else poz.produkt_id
        for kol, wart in (("ID", ident), ("Kod", poz.kod),
                          ("Kod producenta", poz.kod_producenta), ("Nazwa", poz.nazwa)):
            if kol in indeks and wart:
                wiersz[indeks[kol]] = wart
        for kol, wart in getattr(poz, pole).items():
            if kol in indeks:
                wiersz[indeks[kol]] = wart
        ws.append(wiersz)

    return wb


def zapisz_partie(con: sqlite3.Connection, katalog: str | Path,
                  limit_produktow: int = 50, uwagi: str = "") -> dict:
    """Tworzy partię: pliki na dysku + oznaczenie decyzji w bazie."""
    wzorzec = pf.wczytaj_wzorzec()
    if not wzorzec.ok:
        raise ValueError(
            "Brak wzorca formatu panelu — wgraj najpierw plik z panelu "
            "(admin-product-product-*.xlsx) na stronie importu.")

    plan = zaplanuj(con, limit_produktow)
    if not plan.pozycje:
        return {"ile": 0, "pominietych": len(plan.pominiete), "plan": plan}

    katalog = Path(katalog)
    katalog.mkdir(parents=True, exist_ok=True)
    stempel_pliku = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    stempel = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cur = con.execute(
        "INSERT INTO partie (utworzono, plik, ile, pominietych, uwagi)"
        " VALUES (?,?,?,?,?)",
        (stempel, "", len(plan.pozycje), len(plan.pominiete), uwagi))
    partia_id = int(cur.lastrowid)

    nazwa = f"partia_{partia_id:03d}_{stempel_pliku}"
    plik = katalog / f"{nazwa}.xlsx"
    plik_cofnij = katalog / f"{nazwa}_cofnij.xlsx"
    _arkusz(wzorzec, plan.pozycje, "zmiany", stempel).save(plik)
    _arkusz(wzorzec, plan.pozycje, "stare", stempel).save(plik_cofnij)

    con.execute("UPDATE partie SET plik=? WHERE id=?", (str(plik), partia_id))
    con.executemany(
        "UPDATE decyzje SET partia_id=? WHERE produkt_id=? AND atrybut=? AND hasz_starej=?",
        [(partia_id, *k) for poz in plan.pozycje for k in poz.klucze])
    con.commit()

    return {"partia_id": partia_id, "ile": len(plan.pozycje), "zmian": plan.zmian,
            "pominietych": len(plan.pominiete), "plik": str(plik),
            "plik_cofnij": str(plik_cofnij), "plan": plan}


def wycofaj(con: sqlite3.Connection, partia_id: int) -> int:
    """Zdejmuje oznaczenie — decyzje wrócą do następnej partii.

    Do użycia, gdy plik nie wszedł do sklepu. Nie kasuje samych decyzji.
    """
    cur = con.execute("UPDATE decyzje SET partia_id=NULL WHERE partia_id=?", (partia_id,))
    con.execute("UPDATE partie SET wycofana=1 WHERE id=?", (partia_id,))
    con.commit()
    return cur.rowcount


def partie(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM decyzje d WHERE d.partia_id=p.id) AS decyzji"
        " FROM partie p ORDER BY p.id DESC")]
