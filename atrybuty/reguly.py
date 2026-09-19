"""Katalog reguł — co system w ogóle potrafi wykryć.

Dwa rodzaje:

* **wbudowane** — zaszyte w kodzie detektorów (format liczby, outliery, test
  skali, spójność rodziny). Można je wyłączyć, nie da się ich dodać z UI,
  bo to logika, nie dane.
* **konfiguracyjne** — sprzeczności, relacje i klucze-śmieci, opisane
  w `config/reguly.yaml`. Te dodajesz i kasujesz z podstrony /reguly.

Skuteczność liczymy z decyzji: reguła, po której ludzie klikają głównie
„fałszywy alarm”, jest do przestrojenia albo wyłączenia.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from . import config
from .model import INFO, KRYTYCZNA, L1, L2, SREDNIA


@dataclass
class Regula:
    id: str
    warstwa: str
    waga: str
    opis: str
    zrodlo: str            # wbudowana | sprzecznosc | relacja | klucz
    szczegoly: str = ""
    # tylko relacje: operator decyduje, czy RÓWNOŚĆ jest błędem — dlatego
    # musi dojechać do UI, a nie tylko do opisu w szczegółach.
    operator: str = ""
    aktywna: bool = True
    # statystyki z ostatniego przebiegu
    findingow: int = 0
    zastosowanych: int = 0
    falszywych: int = 0

    @property
    def rozstrzygnietych(self) -> int:
        return self.zastosowanych + self.falszywych

    @property
    def skutecznosc(self) -> float | None:
        """Udział trafień wśród rozstrzygniętych. None = za mało danych."""
        if self.rozstrzygnietych < 5:
            return None
        return self.zastosowanych / self.rozstrzygnietych


WBUDOWANE: list[tuple[str, str, str, str]] = [
    # (id, warstwa, waga, opis)
    ("L1-FORMAT-DUBEL", L1, KRYTYCZNA,
     "Liczba zdublowana przecinkiem, obie połówki identyczne (\"46, 46\") — propozycja oczywista"),
    ("L1-FORMAT-ROZNE", L1, KRYTYCZNA,
     "Kilka RÓŻNYCH liczb w jednym polu — bez propozycji, bo nie wolno zgadywać"),
    ("L1-NIE-LICZBA", L1, KRYTYCZNA,
     "Pole liczbowe zawiera tekst"),
    ("L1-LISTA-DUBEL", L1, SREDNIA,
     "Powtórzona wartość na liście wielowartościowej (\"drewno, drewno\")"),
    ("L1-LISTA-KOLEJNOSC", L1, INFO,
     "Ta sama lista w innej kolejności — ujednolicenie zapisu"),
    ("L1-ENUM-DUBEL", L1, SREDNIA,
     "Wartość powtórzona w polu jednowartościowym"),
    ("L1-ZAPIS", L1, INFO,
     "Niespójny zapis tej samej wartości (\"Minimalistyczny\" vs \"minimalistyczny\")"),
    ("L1-ALIAS", L1, INFO,
     "Wariant zapisu zdefiniowany w słowniku jako alias"),
    ("L1-SLOWNIK-AUTO", L1, INFO,
     "Wariant zapisu dopasowany rozmyciem powyżej progu automatycznego"),
    ("L1-SLOWNIK-SUGESTIA", L1, SREDNIA,
     "Prawdopodobna literówka — dopasowanie między progiem sugestii a automatycznym"),
    ("L1-SPOZA-SLOWNIKA", L1, SREDNIA,
     "Wartość spoza słownika atrybutu — albo błąd, albo słownik do uzupełnienia"),
    ("L1-BRAK-ATRYBUTOW", L1, SREDNIA,
     "Produkt nie ma żadnych atrybutów"),
    ("L1-BRAK-ZDJECIA", L1, KRYTYCZNA,
     "Brak zdjęcia — produkt wypada też z warstwy wizyjnej"),
    ("L1-BRAK-WYMAGANEGO", L1, SREDNIA,
     "Brak atrybutu, który ma wypełniony ponad próg produktów tej kategorii"),
    ("L1-KLUCZ-SMIEC", L1, KRYTYCZNA,
     "Klucz atrybutu, którego w bazie być nie powinno (lista poniżej)"),
    ("L2-SKALA", L2, KRYTYCZNA,
     "Wartość poza zakresem kategorii, ale po ×10 / ÷10 / ÷100 wpada w normę "
     "— pomyłka jednostki, znana propozycja"),
    ("L2-OUTLIER", L2, SREDNIA,
     "Wartość poza zakresem kategorii (mediana + MAD), bez propozycji"),
    ("L2-NAZWA-ROZJAZD", L2, KRYTYCZNA,
     "Liczebnik z nazwy nie zgadza się z atrybutem (\"3-drzwiowa\" vs \"2-drzwiowe\")"),
    ("L2-NAZWA-UZUPELNIA", L2, SREDNIA,
     "Nazwa niesie wartość, której atrybut nie ma"),
    ("L2-NAZWA-WYMIAR", L2, SREDNIA,
     "Wymiar z nazwy nie zgadza się z żadnym wymiarem w atrybutach"),
    ("L2-RODZINA", L2, SREDNIA,
     "Wartość odstająca od reszty rodziny produktów (ten sam model, inny materiał)"),
    ("L2-DUPLIKAT", L2, INFO,
     "Kilka produktów o tej samej nazwie i wymiarach u jednego producenta"),
]


def katalog(con: sqlite3.Connection | None = None, przebieg: int | None = None) -> list[Regula]:
    wylaczone = config.wylaczone()
    r = config.reguly()
    out: list[Regula] = []

    for rid, warstwa, waga, opis in WBUDOWANE:
        out.append(Regula(rid, warstwa, waga, opis, "wbudowana",
                          aktywna=rid not in wylaczone))

    for wpis in r.get("sprzecznosci", []) or []:
        gdy = wpis.get("gdy", {})
        czesci = [f"{k} = {v}" for k, v in gdy.items()]
        if wpis.get("nie_moze_miec"):
            czesci.append("nie może mieć: " + ", ".join(wpis["nie_moze_miec"]))
        if wpis.get("nazwa_zawiera"):
            czesci.append("nazwa zawiera: " + ", ".join(wpis["nazwa_zawiera"]))
        out.append(Regula(wpis["id"], L2, KRYTYCZNA, wpis.get("opis", ""), "sprzecznosc",
                          " · ".join(czesci), aktywna=wpis["id"] not in wylaczone))

    for wpis in r.get("relacje", []) or []:
        out.append(Regula(wpis["id"], L2, KRYTYCZNA, wpis.get("opis", ""), "relacja",
                          f"{wpis['lewa']} {wpis['operator']} {wpis['prawa']}",
                          operator=wpis["operator"],
                          aktywna=wpis["id"] not in wylaczone))

    for klucz, wpis in (r.get("klucze_do_usuniecia") or {}).items():
        out.append(Regula(f"KLUCZ:{klucz}", L1, KRYTYCZNA,
                          (wpis.get("powod") or "").strip(), "klucz",
                          f"propozycja: {wpis.get('propozycja', '—')}",
                          aktywna=f"KLUCZ:{klucz}" not in wylaczone))

    if con is not None and przebieg:
        _dolacz_statystyki(out, con, przebieg)
    return out


def _dolacz_statystyki(lista: list[Regula], con: sqlite3.Connection, przebieg: int) -> None:
    ile = {r["regula_id"]: r["n"] for r in con.execute(
        "SELECT regula_id, COUNT(*) n FROM findingi WHERE przebieg_id=? GROUP BY 1",
        (przebieg,))}
    dec = {}
    for r in con.execute(
            "SELECT f.regula_id, d.status, COUNT(*) n FROM findingi f "
            "JOIN decyzje d ON d.produkt_id=f.produkt_id AND d.atrybut=f.atrybut "
            "AND d.hasz_starej=f.hasz_starej WHERE f.przebieg_id=? "
            "GROUP BY 1,2", (przebieg,)):
        dec.setdefault(r["regula_id"], {})[r["status"]] = r["n"]

    for reg in lista:
        klucz = "L1-KLUCZ-SMIEC" if reg.zrodlo == "klucz" else reg.id
        reg.findingow = ile.get(klucz, 0)
        d = dec.get(klucz, {})
        reg.zastosowanych = d.get("zastosowana", 0)
        reg.falszywych = d.get("falszywy_alarm", 0)


# --- operacje z UI --------------------------------------------------------

def przelacz(rid: str, aktywna: bool) -> None:
    d = dict(config.reguly())
    wyl = set(d.get("wylaczone") or [])
    wyl.discard(rid) if aktywna else wyl.add(rid)
    d["wylaczone"] = sorted(wyl)
    config.zapisz_reguly(d)


def przelacz_atrybut(nazwa: str, aktywny: bool) -> None:
    """Wyjmuje atrybut z obiegu albo go przywraca.

    Nic nie kasuje: decyzje i findingi sprzed wyłączenia zostają w bazie,
    tylko przestają być pokazywane i eksportowane. Przywrócenie wymaga
    przeliczenia przebiegu, żeby findingi wróciły do kolejki.
    """
    nazwa = (nazwa or "").strip()
    if not nazwa:
        return
    d = dict(config.reguly())
    wyl = set(d.get("atrybuty_wylaczone") or [])
    wyl.discard(nazwa) if aktywny else wyl.add(nazwa)
    d["atrybuty_wylaczone"] = sorted(wyl)
    config.zapisz_reguly(d)


def usun(rid: str) -> bool:
    d = dict(config.reguly())
    przed = (len(d.get("sprzecznosci") or []) + len(d.get("relacje") or [])
             + len(d.get("klucze_do_usuniecia") or {}))
    if rid.startswith("KLUCZ:"):
        d["klucze_do_usuniecia"] = {k: v for k, v in (d.get("klucze_do_usuniecia") or {}).items()
                                    if k != rid[6:]}
    else:
        d["sprzecznosci"] = [x for x in (d.get("sprzecznosci") or []) if x["id"] != rid]
        d["relacje"] = [x for x in (d.get("relacje") or []) if x["id"] != rid]
    po = (len(d.get("sprzecznosci") or []) + len(d.get("relacje") or [])
          + len(d.get("klucze_do_usuniecia") or {}))
    if po == przed:
        return False
    d["wylaczone"] = sorted(set(d.get("wylaczone") or []) - {rid})
    config.zapisz_reguly(d)
    return True


def istnieje(rid: str) -> bool:
    return any(r.id == rid for r in katalog())


def dodaj_sprzecznosc(rid: str, atrybut: str, wartosc: str, nie_moze_miec: list[str],
                      nazwa_zawiera: list[str], opis: str) -> str | None:
    """Zwraca komunikat błędu albo None przy powodzeniu."""
    rid = (rid or "").strip().upper().replace(" ", "-")
    if not rid:
        return "Podaj identyfikator reguły."
    if istnieje(rid):
        return f"Reguła {rid} już istnieje."
    if not atrybut or not wartosc:
        return "Podaj atrybut i wartość, przy której reguła ma się uruchamiać."
    if not nie_moze_miec and not nazwa_zawiera:
        return "Podaj, czego produkt nie może mieć, albo czego szukać w nazwie."

    d = dict(config.reguly())
    d.setdefault("sprzecznosci", [])
    d["sprzecznosci"].append({
        "id": rid,
        "gdy": {atrybut: wartosc},
        "nie_moze_miec": nie_moze_miec,
        "nazwa_zawiera": nazwa_zawiera,
        "opis": opis or f"{atrybut} = {wartosc} wyklucza: " + ", ".join(nie_moze_miec + nazwa_zawiera),
    })
    config.zapisz_reguly(d)
    return None


OPERATORY = ("<=", "<")


def dodaj_relacje(rid: str, lewa: str, operator: str, prawa: str, opis: str) -> str | None:
    rid = (rid or "").strip().upper().replace(" ", "-")
    if not rid:
        return "Podaj identyfikator reguły."
    if istnieje(rid):
        return f"Reguła {rid} już istnieje."
    if operator not in OPERATORY:
        return f"Operator musi być jednym z: {', '.join(OPERATORY)}."
    liczbowe = {k for k, v in config.slowniki().get("atrybuty", {}).items()
                if v.get("typ") == "liczba"}
    if lewa not in liczbowe or prawa not in liczbowe:
        return "Obie strony muszą być atrybutami liczbowymi (patrz slowniki.yaml)."
    if lewa == prawa:
        return "Obie strony relacji są tym samym atrybutem."

    d = dict(config.reguly())
    d.setdefault("relacje", [])
    d["relacje"].append({
        "id": rid, "lewa": lewa, "operator": operator, "prawa": prawa,
        "opis": opis or f"{lewa} {operator} {prawa}",
    })
    config.zapisz_reguly(d)
    return None


def relacja(rid: str) -> dict | None:
    """Surowy wpis relacji — do pokazania w formularzu edycji."""
    for wpis in config.reguly().get("relacje", []) or []:
        if wpis["id"] == rid:
            return dict(wpis)
    return None


def zmien_relacje(rid: str, operator: str, opis: str) -> str | None:
    """Zmienia operator (i opis) istniejącej relacji.

    Operator decyduje o tym, czy RÓWNOŚĆ jest błędem: przy `<` siedzisko
    równe szerokości mebla leci jako błąd krytyczny, przy `<=` błędem jest
    dopiero siedzisko szersze od mebla. To jedyna różnica, a rozstrzyga
    o tysiącach fałszywych alarmów — więc musi dać się zmienić z UI,
    bez wdrożenia i bez kasowania reguły.

    Strony relacji zostają bez zmian: zamiana atrybutu robi z tego inną
    regułę, a na to jest „usuń" i „dodaj".
    """
    if operator not in OPERATORY:
        return f"Operator musi być jednym z: {', '.join(OPERATORY)}."
    d = dict(config.reguly())
    relacje = [dict(x) for x in (d.get("relacje") or [])]
    trafione = [x for x in relacje if x["id"] == rid]
    if not trafione:
        return f"Nie ma relacji {rid}."
    for wpis in relacje:
        if wpis["id"] == rid:
            wpis["operator"] = operator
            wpis["opis"] = (opis or "").strip() or wpis.get("opis", "")
    d["relacje"] = relacje
    config.zapisz_reguly(d)
    return None


def dodaj_klucz(klucz: str, powod: str, propozycja: str) -> str | None:
    klucz = (klucz or "").strip()
    if not klucz:
        return "Podaj nazwę klucza atrybutu."
    d = dict(config.reguly())
    d.setdefault("klucze_do_usuniecia", {})
    if klucz in d["klucze_do_usuniecia"]:
        return f"Klucz „{klucz}” już jest na liście."
    d["klucze_do_usuniecia"][klucz] = {
        "powod": powod or "Klucz oznaczony do usunięcia.",
        "propozycja": propozycja or "usuń",
    }
    config.zapisz_reguly(d)
    return None
