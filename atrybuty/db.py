"""Warstwa SQLite.

Najważniejsza rzecz w tym module to `decyzje`: to one przeżywają wgranie
kolejnego eksportu. Decyzja jest kluczowana po (produkt_id, atrybut, hasz
starej wartości), więc po nowym pliku system sam rozpoznaje, czy poprawka
faktycznie weszła, czy finding jest wciąż otwarty.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .model import Finding, Produkt

SCHEMA = """
CREATE TABLE IF NOT EXISTS produkty (
    id TEXT PRIMARY KEY,
    nazwa TEXT, producent TEXT, kolekcja TEXT, zdjecie TEXT, styl TEXT,
    kategoria TEXT, zrodlo_kategorii TEXT, kompletnosc TEXT, podtyp TEXT,
    kody TEXT, zdjecia TEXT,
    atrybuty TEXT, atrybuty_surowe TEXT, liczby TEXT
);
CREATE INDEX IF NOT EXISTS ix_prod_kat ON produkty(kategoria);
CREATE INDEX IF NOT EXISTS ix_prod_producent ON produkty(producent);

CREATE TABLE IF NOT EXISTS findingi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    przebieg_id INTEGER NOT NULL,
    produkt_id TEXT NOT NULL,
    atrybut TEXT, regula_id TEXT, warstwa TEXT, waga TEXT,
    pewnosc REAL, stara_wartosc TEXT, proponowana_wartosc TEXT,
    dowod TEXT, grupa TEXT, hasz_starej TEXT
);
CREATE INDEX IF NOT EXISTS ix_f_przebieg ON findingi(przebieg_id);
CREATE INDEX IF NOT EXISTS ix_f_grupa ON findingi(grupa);
CREATE INDEX IF NOT EXISTS ix_f_prod ON findingi(produkt_id);
CREATE INDEX IF NOT EXISTS ix_f_regula ON findingi(regula_id);

CREATE TABLE IF NOT EXISTS decyzje (
    produkt_id TEXT NOT NULL,
    atrybut TEXT NOT NULL,
    hasz_starej TEXT NOT NULL,
    status TEXT NOT NULL,          -- zastosowana | falszywy_alarm | odlozona
    nowa_wartosc TEXT,
    regula_id TEXT,
    uzytkownik TEXT,
    utworzono TEXT,
    PRIMARY KEY (produkt_id, atrybut, hasz_starej)
);

CREATE TABLE IF NOT EXISTS przebiegi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plik TEXT, utworzono TEXT, liczba_produktow INTEGER, liczba_findingow INTEGER
);
"""

# Indeksy na kolumnach dodanych migracją muszą powstać PO niej, inaczej
# otwarcie starej bazy wywala się, zanim zdąży się domigrować.
INDEKSY_PO_MIGRACJI = """
CREATE INDEX IF NOT EXISTS ix_prod_kompletnosc ON produkty(kompletnosc);
CREATE INDEX IF NOT EXISTS ix_prod_podtyp ON produkty(podtyp);
"""


def hasz(wartosc: str | None) -> str:
    return hashlib.sha1((wartosc or "").encode("utf-8")).hexdigest()[:12]


# Kolumny dodane po pierwszym wydaniu. CREATE TABLE IF NOT EXISTS nie migruje
# istniejącej bazy, a kasowanie jej kosztowałoby wszystkie decyzje — więc
# dokładamy brakujące kolumny w miejscu.
MIGRACJE: list[tuple[str, str, str]] = [
    ("produkty", "kompletnosc", "TEXT DEFAULT 'ok'"),
    ("produkty", "podtyp", "TEXT DEFAULT ''"),
    ("produkty", "kody", "TEXT DEFAULT '{}'"),
    ("produkty", "zdjecia", "TEXT DEFAULT '[]'"),
]


def _migruj(con: sqlite3.Connection) -> None:
    for tabela, kolumna, typ in MIGRACJE:
        istniejace = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
        if istniejace and kolumna not in istniejace:
            con.execute(f"ALTER TABLE {tabela} ADD COLUMN {kolumna} {typ}")
    con.commit()


def polacz(sciezka: str | Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(sciezka))
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migruj(con)
    con.executescript(INDEKSY_PO_MIGRACJI)
    return con


def _teraz() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def zapisz_przebieg(con: sqlite3.Connection, plik: str, produkty: list[Produkt],
                    findingi: list[Finding]) -> int:
    cur = con.execute(
        "INSERT INTO przebiegi (plik, utworzono, liczba_produktow, liczba_findingow)"
        " VALUES (?,?,?,?)", (plik, _teraz(), len(produkty), len(findingi)))
    przebieg_id = int(cur.lastrowid)

    con.execute("DELETE FROM produkty")
    con.executemany(
        "INSERT INTO produkty (id,nazwa,producent,kolekcja,zdjecie,styl,kategoria,"
        "zrodlo_kategorii,kompletnosc,podtyp,kody,zdjecia,atrybuty,atrybuty_surowe,liczby)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(p.id, p.nazwa, p.producent, p.kolekcja, p.zdjecie, p.styl, p.kategoria,
          p.zrodlo_kategorii, p.kompletnosc, p.podtyp,
          json.dumps(p.kody, ensure_ascii=False),
          json.dumps([(z.etykieta, z.url) for z in p.zdjecia], ensure_ascii=False),
          json.dumps(p.atrybuty, ensure_ascii=False),
          json.dumps(p.atrybuty_surowe, ensure_ascii=False),
          json.dumps(p.liczby, ensure_ascii=False)) for p in produkty])

    con.executemany(
        "INSERT INTO findingi (przebieg_id,produkt_id,atrybut,regula_id,warstwa,waga,"
        "pewnosc,stara_wartosc,proponowana_wartosc,dowod,grupa,hasz_starej)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(przebieg_id, f.produkt_id, f.atrybut, f.regula_id, f.warstwa, f.waga,
          f.pewnosc, f.stara_wartosc, f.proponowana_wartosc, f.dowod, f.grupa,
          hasz(f.stara_wartosc)) for f in findingi])
    con.commit()
    return przebieg_id


def ostatni_przebieg(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM przebiegi ORDER BY id DESC LIMIT 1").fetchone()


def zapisz_decyzje(con: sqlite3.Connection, produkt_id: str, atrybut: str,
                   stara: str | None, status: str, nowa: str | None,
                   regula_id: str | None, uzytkownik: str = "local") -> None:
    con.execute(
        "INSERT OR REPLACE INTO decyzje (produkt_id,atrybut,hasz_starej,status,"
        "nowa_wartosc,regula_id,uzytkownik,utworzono) VALUES (?,?,?,?,?,?,?,?)",
        (produkt_id, atrybut, hasz(stara), status, nowa, regula_id, uzytkownik, _teraz()))
    con.commit()


def zapisz_decyzje_grupowo(con: sqlite3.Connection, wiersze: Iterable[tuple], status: str,
                           uzytkownik: str = "local") -> int:
    dane = [(pid, atr, hasz(stara), status, nowa, reg, uzytkownik, _teraz())
            for pid, atr, stara, nowa, reg in wiersze]
    con.executemany(
        "INSERT OR REPLACE INTO decyzje (produkt_id,atrybut,hasz_starej,status,"
        "nowa_wartosc,regula_id,uzytkownik,utworzono) VALUES (?,?,?,?,?,?,?,?)", dane)
    con.commit()
    return len(dane)
