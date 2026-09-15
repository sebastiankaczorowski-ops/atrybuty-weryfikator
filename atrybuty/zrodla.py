"""Warstwa L4 — źródła zewnętrzne (feedy producentów).

Feedy producenckie nie mają wspólnego formatu: jeden daje XML z `<product>`,
drugi CSV ze średnikiem, trzeci JSON. Zamiast zgadywać strukturę, narzędzie
pobiera plik, **samo wykrywa powtarzający się rekord i dostępne pola**, pokazuje
je z przykładowymi wartościami, a Ty w UI mówisz, które pole jest szerokością,
a które kodem produktu. Mapowanie zostaje zapisane i kolejne pobranie idzie
już bez pytania.

Dopasowanie do naszych produktów idzie po kluczu (kod producenta / EAN),
a nie po nazwie — nazwy w feedach są zbyt niestabilne, żeby na nich polegać.
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .tekst import do_liczby, norm

SCHEMA_ZRODLA = """
CREATE TABLE IF NOT EXISTS zrodla (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nazwa TEXT NOT NULL,
    producent TEXT,                -- nazwa producenta w NASZEJ bazie (do dopasowania)
    url TEXT,
    plik TEXT,                     -- alternatywa dla url: wgrany plik
    format TEXT,                   -- xml | csv | json
    sciezka_rekordu TEXT,          -- tag powtarzającego się elementu (XML)
    mapowanie TEXT,                -- JSON: nasze pole -> pole w feedzie
    strategia TEXT DEFAULT 'auto', -- auto | klucz | nazwa
    aktywne INTEGER DEFAULT 1,
    ostatnie_pobranie TEXT,
    liczba_pozycji INTEGER DEFAULT 0,
    blad TEXT,
    utworzono TEXT
);

CREATE TABLE IF NOT EXISTS pozycje_zrodla (
    zrodlo_id INTEGER NOT NULL,
    klucz TEXT NOT NULL,           -- kod producenta / EAN, znormalizowany
    dane TEXT,                     -- JSON: zmapowane pola
    surowe TEXT,                   -- JSON: cały rekord z feedu
    PRIMARY KEY (zrodlo_id, klucz)
);
CREATE INDEX IF NOT EXISTS ix_pz_klucz ON pozycje_zrodla(klucz);
"""

# Kolumny dodane po pierwszym wydaniu — jak w db.MIGRACJE.
MIGRACJE_ZRODLA = [("zrodla", "strategia", "TEXT DEFAULT 'auto'"),
                   ("pozycje_zrodla", "nazwa_pozycji", "TEXT DEFAULT ''"),
                   ("pozycje_zrodla", "kolekcja_pozycji", "TEXT DEFAULT ''")]

# Pola, które umiemy wykorzystać. Klucz jest obowiązkowy — bez niego nie ma
# jak połączyć pozycji feedu z naszym produktem.
POLA_DOCELOWE = {
    "klucz": "Kod producenta / EAN — klucz dopasowania (wymagany przy strategii „po kodzie”)",
    "nazwa": "Nazwa produktu — potrzebna przy strategii „po nazwie”",
    "kolekcja": "Kolekcja / seria — zawęża dopasowanie po nazwie",
    "Szerokość": "Szerokość [cm]",
    "Wysokość": "Wysokość [cm]",
    "Głębokość": "Głębokość [cm]",
    "Waga": "Waga [kg]",
    "Materiał": "Materiał",
    "Liczba drzwi": "Liczba drzwi",
    "Liczba szuflad": "Liczba szuflad",
    "Liczba półek": "Liczba półek",
}
POLA_LICZBOWE = {"Szerokość", "Wysokość", "Głębokość", "Waga"}


def przygotuj_baze(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_ZRODLA)
    for tabela, kolumna, typ in MIGRACJE_ZRODLA:
        istniejace = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
        if istniejace and kolumna not in istniejace:
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {kolumna} {typ}")
    con.commit()


def _teraz() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- pobieranie -----------------------------------------------------------

class BladZrodla(RuntimeError):
    pass


def pobierz(url: str, timeout: int = 60, maks_mb: int = 60) -> bytes:
    zadanie = urllib.request.Request(url, headers={
        "User-Agent": "atrybuty-oxm/1.0 (kontrola jakosci danych)",
        "Accept": "application/xml, text/xml, text/csv, application/json, */*",
    })
    try:
        with urllib.request.urlopen(zadanie, timeout=timeout) as odp:
            dane = odp.read(maks_mb * 1_048_576 + 1)
    except urllib.error.HTTPError as e:
        raise BladZrodla(f"serwer zwrócił {e.code} {e.reason}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise BladZrodla(f"nie udało się połączyć: {e}") from e
    if len(dane) > maks_mb * 1_048_576:
        raise BladZrodla(f"plik większy niż {maks_mb} MB")
    if not dane:
        raise BladZrodla("plik jest pusty")
    return dane


def wykryj_format(dane: bytes, nazwa: str = "") -> str:
    poczatek = dane[:4096].lstrip()
    if poczatek.startswith(b"<"):
        return "xml"
    if poczatek.startswith(b"{") or poczatek.startswith(b"["):
        return "json"
    if nazwa.lower().endswith(".xml"):
        return "xml"
    if nazwa.lower().endswith(".json"):
        return "json"
    return "csv"


# --- parsowanie: feed -> lista płaskich rekordów --------------------------

# Atrybuty często siedzą w feedach jako pary nazwa/wartość:
#   <attr name="Szerokość (cm)">160</attr>
# Płaskie "attrs.attr[7]" byłoby wtedy bezużyteczne, bo numer pozycji zmienia
# się produkt po produkcie. Gdy powtarzany element ma jeden z tych atrybutów,
# używamy jego wartości jako nazwy pola.
ATRYBUTY_NAZWY = ("name", "nazwa", "key", "klucz", "code", "kod", "id", "attribute")


def _splaszcz(el: ET.Element, prefiks: str = "") -> dict[str, str]:
    """Element XML -> płaski słownik 'tag.podtag' -> wartość.

    Atrybuty XML lądują jako 'tag@atrybut'. Powtórzone tagi dostają indeks,
    żeby nie gubić wartości (np. kilka <imge>), a pary nazwa/wartość —
    nazwę z atrybutu (patrz ATRYBUTY_NAZWY).
    """
    out: dict[str, str] = {}
    licznik: Counter = Counter()
    for k, v in el.attrib.items():
        out[f"{prefiks}@{k}" if prefiks else f"@{k}"] = (v or "").strip()

    for dziecko in el:
        tag = _bez_przestrzeni(dziecko.tag)
        tekst = "".join(dziecko.itertext()).strip()
        etykieta = _etykieta_pary(dziecko)

        if etykieta:
            klucz = f"{prefiks}.{tag}:{etykieta}" if prefiks else f"{tag}:{etykieta}"
            if tekst:
                out[klucz] = tekst
            continue

        licznik[tag] += 1
        klucz = f"{prefiks}.{tag}" if prefiks else tag
        if licznik[tag] > 1:
            klucz = f"{klucz}[{licznik[tag]}]"
        if tekst and not len(dziecko):
            out[klucz] = tekst
        out.update(_splaszcz(dziecko, klucz))
    return out


def _etykieta_pary(el: ET.Element) -> str:
    """Zwraca nazwę pola, gdy element wygląda na parę nazwa/wartość."""
    if len(el):                       # ma dzieci — to nie para nazwa/wartość
        return ""
    for k in ATRYBUTY_NAZWY:
        wartosc = (el.attrib.get(k) or "").strip()
        if wartosc:
            return wartosc
    return ""


def _bez_przestrzeni(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def rekordy_xml(dane: bytes, sciezka_rekordu: str = "") -> tuple[list[dict], str]:
    """Zwraca (rekordy, nazwa tagu rekordu).

    Gdy tag nie jest podany, wybieramy najczęściej powtarzający się element —
    w feedach produktowych to zawsze pojedynczy produkt.
    """
    try:
        korzen = ET.fromstring(dane)
    except ET.ParseError as e:
        raise BladZrodla(f"niepoprawny XML: {e}") from e

    if not sciezka_rekordu:
        sciezka_rekordu = _wykryj_rekord(korzen)

    elementy = [el for el in korzen.iter() if _bez_przestrzeni(el.tag) == sciezka_rekordu]
    if not elementy:
        raise BladZrodla(f"nie znaleziono elementów <{sciezka_rekordu}>")
    return [_splaszcz(el) for el in elementy], sciezka_rekordu


def _wykryj_rekord(korzen: ET.Element) -> str:
    """Który tag jest pojedynczym produktem.

    Nie „najczęstszy” — w tym feedzie najczęstszy jest <attr> (10 126 sztuk
    wewnątrz 560 produktów). Szukamy NAJPŁYTSZEGO powtarzającego się tagu:
    produkt zawsze leży wyżej niż jego własne atrybuty i zdjęcia.
    """
    kandydaci: dict[str, tuple[int, int]] = {}      # tag -> (głębokość, liczność)

    def obejdz(el: ET.Element, glebokosc: int) -> None:
        licznik: Counter = Counter()
        for d in el:
            licznik[_bez_przestrzeni(d.tag)] += 1
        for tag, ile in licznik.items():
            if ile < 2:
                continue
            poprzednia = kandydaci.get(tag)
            if poprzednia is None or glebokosc < poprzednia[0]:
                kandydaci[tag] = (glebokosc, ile)
            elif glebokosc == poprzednia[0]:
                kandydaci[tag] = (glebokosc, poprzednia[1] + ile)
        for d in el:
            obejdz(d, glebokosc + 1)

    obejdz(korzen, 0)
    if not kandydaci:
        raise BladZrodla("XML nie zawiera powtarzających się elementów")
    # najpłycej, a przy remisie najliczniej
    return min(kandydaci.items(), key=lambda x: (x[1][0], -x[1][1]))[0]


def rekordy_csv(dane: bytes) -> list[dict]:
    tekst = dane.decode("utf-8-sig", errors="replace")
    probka = tekst[:8192]
    sep = ";" if probka.count(";") > probka.count(",") else ","
    czytnik = csv.DictReader(io.StringIO(tekst), delimiter=sep)
    return [{(k or "").strip(): (v or "").strip() for k, v in w.items() if k}
            for w in czytnik]


def rekordy_json(dane: bytes) -> list[dict]:
    try:
        obiekt = json.loads(dane.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as e:
        raise BladZrodla(f"niepoprawny JSON: {e}") from e
    if isinstance(obiekt, dict):
        # najdłuższa lista w obiekcie to prawie zawsze lista produktów
        listy = [v for v in obiekt.values() if isinstance(v, list)]
        obiekt = max(listy, key=len) if listy else []
    if not isinstance(obiekt, list):
        raise BladZrodla("JSON nie zawiera listy rekordów")
    return [{k: ("" if v is None else str(v)) for k, v in r.items()}
            for r in obiekt if isinstance(r, dict)]


def rekordy(dane: bytes, format_: str, sciezka_rekordu: str = "") -> tuple[list[dict], str]:
    if format_ == "xml":
        return rekordy_xml(dane, sciezka_rekordu)
    if format_ == "json":
        return rekordy_json(dane), ""
    return rekordy_csv(dane), ""


# --- podgląd pól ----------------------------------------------------------

@dataclass
class Pole:
    nazwa: str
    wypelnienie: float          # udział rekordów, w których pole nie jest puste
    przyklady: list[str] = field(default_factory=list)
    wyglada_na_liczbe: bool = False


def opisz_pola(rek: list[dict], maks: int = 120) -> list[Pole]:
    """Jakie pola są w feedzie, jak często wypełnione i co w nich stoi."""
    if not rek:
        return []
    wystapienia: Counter = Counter()
    wartosci: dict[str, list[str]] = defaultdict(list)
    liczbowe: Counter = Counter()

    for r in rek:
        for k, v in r.items():
            if v:
                wystapienia[k] += 1
                if len(wartosci[k]) < 3:
                    wartosci[k].append(v[:60])
                if do_liczby(v) is not None:
                    liczbowe[k] += 1

    out = []
    for k, ile in wystapienia.most_common(maks):
        out.append(Pole(nazwa=k, wypelnienie=ile / len(rek), przyklady=wartosci[k],
                        wyglada_na_liczbe=liczbowe[k] / ile > 0.8))
    return out


def zgadnij_klucz(rek: list[dict], pola: list[Pole],
                  nasze_klucze: set[str]) -> tuple[str, int]:
    """Które pole feedu faktycznie trafia w nasze produkty.

    Zgadywanie po nazwie pola bywa mylące: ten feed ma i `@id` (wewnętrzne id
    producenta), i `sku`, i `ean`. Dobre jest to, które REALNIE pokrywa się
    z kodami z naszych nazw produktów — więc po prostu to sprawdzamy.
    """
    if not nasze_klucze or not rek:
        return "", 0
    probka = rek[:1500]
    najlepsze, najwiecej = "", 0
    for p in pola:
        if p.wypelnienie < 0.5:
            continue
        trafien = sum(1 for r in probka if norm(r.get(p.nazwa, "")) in nasze_klucze)
        if trafien > najwiecej:
            najlepsze, najwiecej = p.nazwa, trafien
    return najlepsze, najwiecej


def zgadnij_mapowanie(pola: list[Pole]) -> dict[str, str]:
    """Wstępna propozycja mapowania — do poprawienia ręcznie w UI.

    Kolejność słów w podpowiedziach to priorytet: `sku` przed `ean`, bo
    dopasowanie idzie po kodach z nazw naszych produktów, a EAN-ów w naszym
    eksporcie nie ma.
    """
    podpowiedzi = {
        "klucz": ("sku", "kod", "symbol", "indeks", "ean", "gtin", "id"),
        "nazwa": ("nazwa", "name", "title", "tytul"),
        "Szerokość": ("szerokosc", "width", "szer"),
        "Wysokość": ("wysokosc", "height", "wys"),
        "Głębokość": ("glebokosc", "depth", "gleb"),
        "Waga": ("waga", "weight", "masa"),
        "Materiał": ("material", "materialy", "tworzywo"),
        "Liczba drzwi": ("drzwi", "doors"),
        "Liczba szuflad": ("szuflad", "drawers"),
        "Liczba półek": ("polek", "polki", "shelves"),
    }
    out: dict[str, str] = {}
    uzyte: set[str] = set()
    for docelowe, slowa in podpowiedzi.items():
        trafione = None
        for slowo in slowa:                      # priorytet ma słowo, nie pole
            for p in pola:
                if p.nazwa in uzyte or slowo not in norm(p.nazwa):
                    continue
                if docelowe in POLA_LICZBOWE and not p.wyglada_na_liczbe:
                    continue
                trafione = p.nazwa
                break
            if trafione:
                break
        if trafione:
            out[docelowe] = trafione
            uzyte.add(trafione)
    return out


# --- zapis i odczyt -------------------------------------------------------

def lista_zrodel(con: sqlite3.Connection) -> list[dict]:
    przygotuj_baze(con)
    out = []
    for r in con.execute("SELECT * FROM zrodla ORDER BY nazwa"):
        d = dict(r)
        d["mapowanie"] = json.loads(d["mapowanie"] or "{}")
        out.append(d)
    return out


def zrodlo(con: sqlite3.Connection, zid: int) -> dict | None:
    r = con.execute("SELECT * FROM zrodla WHERE id=?", (zid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["mapowanie"] = json.loads(d["mapowanie"] or "{}")
    return d


def dodaj_zrodlo(con: sqlite3.Connection, nazwa: str, producent: str,
                 url: str = "", plik: str = "") -> int:
    przygotuj_baze(con)
    cur = con.execute(
        "INSERT INTO zrodla (nazwa, producent, url, plik, mapowanie, utworzono)"
        " VALUES (?,?,?,?,'{}',?)",
        (nazwa.strip(), producent.strip(), url.strip(), plik.strip(), _teraz()))
    con.commit()
    return int(cur.lastrowid)


def usun_zrodlo(con: sqlite3.Connection, zid: int) -> None:
    con.execute("DELETE FROM pozycje_zrodla WHERE zrodlo_id=?", (zid,))
    con.execute("DELETE FROM zrodla WHERE id=?", (zid,))
    con.commit()


def zapisz_mapowanie(con: sqlite3.Connection, zid: int, mapowanie: dict[str, str]) -> None:
    con.execute("UPDATE zrodla SET mapowanie=? WHERE id=?",
                (json.dumps(mapowanie, ensure_ascii=False), zid))
    con.commit()


def ustaw_strategie(con: sqlite3.Connection, zid: int, strategia: str) -> None:
    if strategia not in ("auto", "klucz", "nazwa"):
        strategia = "auto"
    con.execute("UPDATE zrodla SET strategia=? WHERE id=?", (strategia, zid))
    con.commit()


def raport_dopasowania(con: sqlite3.Connection) -> dict:
    """Ile produktów udało się połączyć z feedami — i jakim sposobem."""
    dop = dopasuj(con)
    wg_sposobu = Counter(d.get("sposob", "?") for d in dop.values())
    wg_zrodla = Counter(d["zrodlo"] for d in dop.values())
    return {"dopasowanych": len(dop), "wg_sposobu": dict(wg_sposobu),
            "wg_zrodla": dict(wg_zrodla)}


def przelacz_zrodlo(con: sqlite3.Connection, zid: int, aktywne: bool) -> None:
    con.execute("UPDATE zrodla SET aktywne=? WHERE id=?", (1 if aktywne else 0, zid))
    con.commit()


# --- odświeżenie źródła ---------------------------------------------------

def dane_zrodla(z: dict, katalog_danych: Path) -> tuple[bytes, str]:
    """Zwraca (zawartość, nazwa) — z URL-a albo z wgranego pliku."""
    if z.get("url"):
        return pobierz(z["url"]), z["url"]
    if z.get("plik"):
        sciezka = katalog_danych / Path(z["plik"]).name
        if not sciezka.exists():
            raise BladZrodla(f"nie ma pliku {sciezka.name}")
        return sciezka.read_bytes(), sciezka.name
    raise BladZrodla("źródło nie ma ani URL-a, ani pliku")


def odswiez(con: sqlite3.Connection, zid: int, katalog_danych: Path) -> dict:
    """Pobiera feed, parsuje i zapisuje pozycje. Zwraca podsumowanie."""
    przygotuj_baze(con)
    z = zrodlo(con, zid)
    if not z:
        raise BladZrodla("nie ma takiego źródła")

    try:
        surowe, nazwa = dane_zrodla(z, katalog_danych)
        fmt = z.get("format") or wykryj_format(surowe, nazwa)
        rek, tag = rekordy(surowe, fmt, z.get("sciezka_rekordu") or "")
    except BladZrodla as e:
        con.execute("UPDATE zrodla SET blad=?, ostatnie_pobranie=? WHERE id=?",
                    (str(e), _teraz(), zid))
        con.commit()
        raise

    pola = opisz_pola(rek)
    mapowanie = z["mapowanie"] or zgadnij_mapowanie(pola)

    strategia = z.get("strategia") or "auto"
    zapisane = 0
    if not mapowanie.get("klucz") and mapowanie.get("nazwa"):
        # przy dopasowaniu po nazwie klucz jest tylko identyfikatorem wiersza
        mapowanie = dict(mapowanie)
        mapowanie["klucz"] = mapowanie["nazwa"]
    if mapowanie.get("klucz"):
        con.execute("DELETE FROM pozycje_zrodla WHERE zrodlo_id=?", (zid,))
        wiersze = []
        for r in rek:
            klucz = norm(r.get(mapowanie["klucz"], ""))
            if not klucz:
                continue
            dane = {}
            for docelowe, zrodlowe in mapowanie.items():
                if docelowe == "klucz":
                    continue
                wartosc = (r.get(zrodlowe) or "").strip()
                if wartosc:
                    dane[docelowe] = wartosc
            wiersze.append((zid, klucz, json.dumps(dane, ensure_ascii=False),
                            json.dumps(r, ensure_ascii=False),
                            dane.get("nazwa", ""), dane.get("kolekcja", "")))
        con.executemany(
            "INSERT OR REPLACE INTO pozycje_zrodla "
            "(zrodlo_id,klucz,dane,surowe,nazwa_pozycji,kolekcja_pozycji)"
            " VALUES (?,?,?,?,?,?)", wiersze)
        zapisane = len(wiersze)

    con.execute(
        "UPDATE zrodla SET format=?, sciezka_rekordu=?, mapowanie=?, blad=NULL,"
        " ostatnie_pobranie=?, liczba_pozycji=? WHERE id=?",
        (fmt, tag, json.dumps(mapowanie, ensure_ascii=False), _teraz(), zapisane, zid))
    con.commit()

    return {"rekordow": len(rek), "zapisanych": zapisane, "format": fmt,
            "tag": tag, "pola": pola, "mapowanie": mapowanie,
            "brak_klucza": not mapowanie.get("klucz")}


def podglad(con: sqlite3.Connection, zid: int, katalog_danych: Path, ile: int = 5) -> dict:
    """Pobiera feed i pokazuje pola z przykładami — bez zapisywania pozycji."""
    z = zrodlo(con, zid)
    if not z:
        raise BladZrodla("nie ma takiego źródła")
    surowe, nazwa = dane_zrodla(z, katalog_danych)
    fmt = z.get("format") or wykryj_format(surowe, nazwa)
    rek, tag = rekordy(surowe, fmt, z.get("sciezka_rekordu") or "")
    pola = opisz_pola(rek)

    mapowanie = dict(z["mapowanie"] or zgadnij_mapowanie(pola))
    klucz_z_danych, trafien = zgadnij_klucz(rek, pola, _nasze_klucze(con))
    if not z["mapowanie"] and klucz_z_danych:
        mapowanie["klucz"] = klucz_z_danych

    return {"rekordow": len(rek), "format": fmt, "tag": tag, "pola": pola,
            "mapowanie": mapowanie, "przyklady": rek[:ile],
            "klucz_z_danych": klucz_z_danych, "trafien_klucza": trafien}


def _nasze_klucze(con: sqlite3.Connection) -> set[str]:
    """Wszystkie kody, jakie da się wyciągnąć z nazw i id naszych produktów."""
    out: set[str] = set()
    for r in con.execute("SELECT id, nazwa, kody FROM produkty"):
        out |= klucze_produktu(r["nazwa"], r["id"], json.loads(r["kody"] or "{}"))
    return out


# --- dopasowanie do naszych produktów -------------------------------------

RE_KOD = re.compile(r"\b[A-Z0-9][A-Z0-9/-]{3,}\b")


def klucze_produktu(nazwa: str, pid: str, kody: dict | None = None) -> set[str]:
    """Kandydaci na klucz dopasowania.

    Od eksportu z 15.09 mamy wprost `kod producenta`, `kod produktu` i EAN —
    i to one dają pewne dopasowanie. Kody wyłuskane z nazwy zostają jako
    zapas dla starszych plików.
    """
    out = {norm(pid)}
    for wartosc in (kody or {}).values():
        if wartosc and len(str(wartosc).strip()) >= 3:
            out.add(norm(str(wartosc)))
    for kod in RE_KOD.findall((nazwa or "").upper()):
        if any(c.isdigit() for c in kod):
            out.add(norm(kod))
    return {k for k in out if k}


# Dopasowanie po nazwie: ile punktów podobieństwa wymagamy i o ile drugi
# kandydat musi być gorszy. Bez marginesu "Szafka nocna Rimini" trafiłaby
# losowo w jedną z dwóch różnych szafek nocnych z tej samej kolekcji.
PROG_NAZWY = 88
MARGINES_NAZWY = 6

# Kody i liczby wycinamy z nazw przed porównaniem: w feedzie stoi
# "Rimini RI01 Kredens", u nas "Kredens Rimini" — sam kod tylko przeszkadza.
RE_SMIECI_NAZWY = re.compile(r"\b([a-z]{1,3}\d{1,4}[a-z]?|\d+(?:[.,]\d+)?(?:cm|mm|kg)?)\b")


def _nazwa_do_porownania(nazwa: str, kolekcja: str = "") -> str:
    """Zostawia sam typ mebla: bez kodów i bez nazwy kolekcji.

    Kolekcja służy do grupowania kandydatów, więc zostawianie jej w tekście
    tylko zaciera różnice — wszystkie pozycje z kolekcji Rimini mają "rimini"
    i wynik podobieństwa robi się dla nich niemal identyczny.
    """
    n = RE_SMIECI_NAZWY.sub(" ", norm(nazwa))
    for slowo in norm(kolekcja).split():
        n = re.sub(rf"\b{re.escape(slowo)}\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def dopasuj(con: sqlite3.Connection) -> dict[str, dict]:
    """Zwraca {produkt_id: dane z feedu} dla produktów, które udało się dopasować.

    Dwie strategie, bo feedy bywają różne:
    * **po kodzie** — pewna, gdy nasze nazwy zawierają SKU producenta;
    * **po nazwie** — dla feedów, gdzie nazwy opisują to samo innymi słowami
      ("Rimini RI01 Kredens" vs "Kredens Rimini"). Zawężona do producenta
      i kolekcji, z progiem podobieństwa i marginesem nad drugim kandydatem.

    `auto` próbuje najpierw kodu, a dla nieprzypisanych sięga po nazwę.
    """
    przygotuj_baze(con)
    aktywne = [z for z in lista_zrodel(con) if z["aktywne"] and z["liczba_pozycji"]]
    if not aktywne:
        return {}

    out: dict[str, dict] = {}
    for z in aktywne:
        pozycje = [dict(r) for r in con.execute(
            "SELECT klucz, dane, nazwa_pozycji, kolekcja_pozycji FROM pozycje_zrodla "
            "WHERE zrodlo_id=?", (z["id"],))]
        if not pozycje:
            continue

        produkty = [dict(r) for r in con.execute(
            "SELECT id, nazwa, producent, kolekcja, kody FROM produkty"
            + (" WHERE producent = ?" if z["producent"] else ""),
            (z["producent"],) if z["producent"] else ())]

        strategia = z.get("strategia") or "auto"
        if strategia in ("auto", "klucz"):
            _dopasuj_po_kodzie(z, pozycje, produkty, out)
        if strategia in ("auto", "nazwa"):
            _dopasuj_po_nazwie(z, pozycje, produkty, out)
    return out


def _opis(z: dict, dane: dict, sposob: str, nazwa_pozycji: str = "") -> dict:
    """Jak dopasowaliśmy i z czym — to trafia do dowodu przy findingu.

    Bez nazwy dopasowanej pozycji człowiek w kolejce nie ma jak odróżnić
    realnego błędu w danych od pomyłki samego dopasowania.
    """
    return {"dane": dane, "zrodlo": z["nazwa"], "producent": z["producent"],
            "sposob": sposob, "nazwa_pozycji": nazwa_pozycji}


def _dopasuj_po_kodzie(z: dict, pozycje: list[dict], produkty: list[dict],
                       out: dict[str, dict]) -> None:
    indeks = {p["klucz"]: {"dane": json.loads(p["dane"] or "{}"),
                           "nazwa": p.get("nazwa_pozycji") or ""} for p in pozycje}
    for r in produkty:
        if r["id"] in out:
            continue
        for k in klucze_produktu(r["nazwa"], r["id"], json.loads(r.get("kody") or "{}")):
            if k in indeks:
                out[r["id"]] = _opis(z, indeks[k]["dane"], "kod", indeks[k]["nazwa"])
                break


def _dopasuj_po_nazwie(z: dict, pozycje: list[dict], produkty: list[dict],
                       out: dict[str, dict]) -> None:
    from rapidfuzz import fuzz, process

    # Grupujemy po kolekcji — poza nią porównywanie nazw nie ma sensu.
    wg_kolekcji: dict[str, list[dict]] = defaultdict(list)
    for p in pozycje:
        if p.get("nazwa_pozycji"):
            wg_kolekcji[norm(p.get("kolekcja_pozycji") or "")].append(p)
    if not wg_kolekcji:
        return

    for r in produkty:
        if r["id"] in out:
            continue
        kandydaci = wg_kolekcji.get(norm(r["kolekcja"] or ""))
        if not kandydaci:
            continue
        nasza = _nazwa_do_porownania(r["nazwa"], r["kolekcja"])
        if not nasza:
            continue
        teksty = [_nazwa_do_porownania(p["nazwa_pozycji"], p.get("kolekcja_pozycji") or "")
                  for p in kandydaci]
        # WRatio wypadł najlepiej na feedzie Livin Hill (69 dopasowań wobec
        # 57 dla token_set i 44 dla samego ratio) — karze nadmiarowe słowa
        # ("komoda" vs "komoda rtv"), ale wybacza inną kolejność.
        wyniki = process.extract(nasza, teksty, scorer=fuzz.WRatio, limit=2)
        if not wyniki or wyniki[0][1] < PROG_NAZWY:
            continue
        if len(wyniki) > 1 and wyniki[0][1] - wyniki[1][1] < MARGINES_NAZWY:
            continue                      # dwie równie pasujące pozycje — nie zgadujemy
        wybrany = kandydaci[wyniki[0][2]]
        out[r["id"]] = _opis(z, json.loads(wybrany["dane"] or "{}"), "nazwa",
                             wybrany.get("nazwa_pozycji") or "")


def statystyki(con: sqlite3.Connection) -> dict:
    przygotuj_baze(con)
    zrodel = con.execute("SELECT COUNT(*) FROM zrodla").fetchone()[0]
    pozycji = con.execute("SELECT COUNT(*) FROM pozycje_zrodla").fetchone()[0]
    return {"zrodel": zrodel, "pozycji": pozycji}


# --- detektor L4 ----------------------------------------------------------

# Ile procent różnicy tolerujemy, zanim uznamy to za rozjazd. Producenci
# zaokrąglają wymiary i podają je z opakowaniem albo bez, więc szukanie
# różnic co do milimetra zasypałoby kolejkę szumem.
TOLERANCJA = {"Szerokość": 0.03, "Wysokość": 0.03, "Głębokość": 0.03, "Waga": 0.10}


def znajdz_rozjazdy(con: sqlite3.Connection, przebieg_id: int) -> list[dict]:
    """Porównuje nasze wartości z referencją producenta.

    Zwraca listę findingów gotowych do zapisania. Produkt bez dopasowania
    w feedzie jest pomijany — brak referencji to nie błąd danych.
    """
    dopasowania = dopasuj(con)
    if not dopasowania:
        return []

    findingi: list[dict] = []
    for r in con.execute("SELECT id, liczby, atrybuty FROM produkty"):
        trafienie = dopasowania.get(r["id"])
        if not trafienie:
            continue
        nasze_liczby = json.loads(r["liczby"] or "{}")
        nasze_atrybuty = json.loads(r["atrybuty"] or "{}")
        ref = trafienie["dane"]

        for klucz, tolerancja in TOLERANCJA.items():
            wartosc_ref = do_liczby(ref.get(klucz, ""))
            if wartosc_ref is None or wartosc_ref <= 0:
                continue

            nasza = nasze_liczby.get(klucz)
            if nasza is None:
                if klucz in nasze_atrybuty:
                    continue
                findingi.append({
                    "produkt_id": r["id"], "atrybut": klucz,
                    "regula_id": "L4-UZUPELNIA", "waga": "srednia",
                    "pewnosc": _pewnosc(trafienie, 0.80),
                    "stara": None, "proponowana": _fmt(wartosc_ref),
                    "dowod": f"{_zrodlo_opis(trafienie)}: {klucz} = {_fmt(wartosc_ref)}, "
                             f"u nas brak",
                    "grupa": f"L4-UZUPELNIA|{klucz}|{trafienie['zrodlo']}",
                })
                continue

            odchylka = abs(nasza - wartosc_ref) / wartosc_ref
            if odchylka > tolerancja:
                findingi.append({
                    "produkt_id": r["id"], "atrybut": klucz,
                    "regula_id": "L4-ROZJAZD", "waga": "krytyczna",
                    "pewnosc": _pewnosc(trafienie, 0.82),
                    "stara": _fmt(nasza), "proponowana": _fmt(wartosc_ref),
                    "dowod": f"{_zrodlo_opis(trafienie)}: {klucz} = {_fmt(wartosc_ref)}, "
                             f"u nas {_fmt(nasza)} (różnica {odchylka:.0%}, "
                             f"tolerancja {tolerancja:.0%})",
                    "grupa": f"L4-ROZJAZD|{klucz}|{trafienie['zrodlo']}",
                })
    return findingi


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _zrodlo_opis(trafienie: dict) -> str:
    """Nazwa źródła + z czym dokładnie porównaliśmy."""
    opis = trafienie["zrodlo"]
    if trafienie.get("nazwa_pozycji"):
        opis += f" → „{trafienie['nazwa_pozycji']}”"
    if trafienie.get("sposob") == "nazwa":
        opis += " (dopasowane po nazwie — sprawdź, czy to ten sam mebel)"
    return opis


def _pewnosc(trafienie: dict, bazowa: float) -> float:
    """Dopasowanie po nazwie jest z definicji mniej pewne niż po kodzie.

    Dzięki niższej pewności taki finding nie wpada do kubełka „jedno
    kliknięcie”, tylko trafia do ręcznej oceny — bo wątpliwy bywa nie sam
    wymiar, ale to, czy porównaliśmy właściwe meble."""
    return bazowa if trafienie.get("sposob") == "kod" else 0.55


def dopisz_findingi_l4(con: sqlite3.Connection, przebieg_id: int) -> int:
    """Dokłada findingi L4 do świeżego przebiegu. Uruchamiane PO zapisie
    produktów — dopasowanie potrzebuje ich już w bazie."""
    from .db import hasz

    znalezione = znajdz_rozjazdy(con, przebieg_id)
    if not znalezione:
        return 0
    con.executemany(
        "INSERT INTO findingi (przebieg_id,produkt_id,atrybut,regula_id,warstwa,waga,"
        "pewnosc,stara_wartosc,proponowana_wartosc,dowod,grupa,hasz_starej)"
        " VALUES (?,?,?,?,'L4',?,?,?,?,?,?,?)",
        [(przebieg_id, f["produkt_id"], f["atrybut"], f["regula_id"], f["waga"],
          f["pewnosc"], f["stara"], f["proponowana"], f["dowod"], f["grupa"],
          hasz(f["stara"])) for f in znalezione])
    con.execute("UPDATE przebiegi SET liczba_findingow = liczba_findingow + ? WHERE id=?",
                (len(znalezione), przebieg_id))
    con.commit()
    return len(znalezione)
