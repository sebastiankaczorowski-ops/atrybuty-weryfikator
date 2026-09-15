"""Import pliku z przeglądarki — przebieg w tle z podglądem postępu.

Przebieg na 32 tys. produktów trwa kilkanaście sekund. Robienie go w wątku
obsługującym żądanie blokowałoby całą aplikację i kończyło się timeoutem
w przeglądarce, więc leci w osobnym wątku, a strona odpytuje o stan.

Jednocześnie może trwać tylko jeden import — drugi równoległy nadpisywałby
tabelę produktów w trakcie czytania przez pierwszy.
"""
from __future__ import annotations

import shutil
import threading
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import config, db, detektory, kategorie, schema_gen
from .model import PROG_DO_WIZJI, WIDOCZNE_NA_ZDJECIU
from .pipeline import BAZA, wczytaj_csv

KATALOG_DANYCH = BAZA.parent
_zamek = threading.Lock()

STAN: dict = {
    "trwa": False,
    "etap": "",
    "plik": "",
    "start": None,
    "wynik": None,
    "blad": None,
}


def zajety() -> bool:
    return bool(STAN["trwa"])


def zapisz_plik(nazwa: str, zawartosc: bytes) -> Path:
    """Zapisuje wgrany plik obok pozostałych danych, ze stemplem czasu."""
    KATALOG_DANYCH.mkdir(parents=True, exist_ok=True)
    bezpieczna = Path(nazwa).name.replace(" ", "_") or "products.csv"
    if not bezpieczna.lower().endswith(".csv"):
        bezpieczna += ".csv"
    stempel = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    sciezka = KATALOG_DANYCH / f"{stempel}__{bezpieczna}"
    sciezka.write_bytes(zawartosc)
    return sciezka


def uruchom_w_tle(plik: Path, plik_kategorii: Path | None = None,
                  regeneruj_schema: bool = False) -> bool:
    """Startuje import. Zwraca False, jeśli inny właśnie trwa."""
    if not _zamek.acquire(blocking=False):
        return False
    STAN.update({"trwa": True, "etap": "wczytywanie pliku", "plik": plik.name,
                 "start": datetime.now(), "wynik": None, "blad": None})
    watek = threading.Thread(target=_przebieg, args=(plik, plik_kategorii, regeneruj_schema),
                             daemon=True)
    watek.start()
    return True


def _przebieg(plik: Path, plik_kategorii: Path | None, regeneruj_schema: bool) -> None:
    try:
        produkty, f_norm = wczytaj_csv(plik, plik_kategorii)
        STAN["etap"] = f"wczytano {len(produkty)} produktów"

        if regeneruj_schema or not config.schema():
            STAN["etap"] = "liczenie zakresów per kategoria"
            config.zapisz_schema(schema_gen.zbuduj(produkty))

        STAN["etap"] = "uruchamianie detektorów"
        findingi = detektory.uruchom(produkty, f_norm)

        STAN["etap"] = "zapis do bazy"
        con = db.polacz(BAZA)
        przebieg = db.zapisz_przebieg(con, str(plik), produkty, findingi)
        con.close()

        STAN["wynik"] = _podsumowanie(przebieg, produkty, findingi)
        STAN["etap"] = "gotowe"
    except Exception as e:                                   # noqa: BLE001
        STAN["blad"] = f"{e}"
        STAN["etap"] = "błąd"
        traceback.print_exc()
    finally:
        STAN["trwa"] = False
        _zamek.release()


def _podsumowanie(przebieg: int, produkty: list, findingi: list) -> dict:
    kompl = Counter(p.kompletnosc for p in produkty)
    zdjecia = {p.id: p.ma_zdjecie for p in produkty}
    auto = sum(1 for f in findingi if f.pewnosc >= PROG_DO_WIZJI and f.proponowana_wartosc)
    do_wizji = sum(1 for f in findingi
                   if f.pewnosc < PROG_DO_WIZJI and f.atrybut in WIDOCZNE_NA_ZDJECIU
                   and zdjecia.get(f.produkt_id))
    zrodla = Counter(p.zrodlo_kategorii for p in produkty)
    return {
        "przebieg": przebieg,
        "produktow": len(produkty),
        "findingow": len(findingi),
        "grup": len({f.grupa for f in findingi}),
        "auto": auto,
        "do_wizji": do_wizji,
        "do_czlowieka": len(findingi) - auto - do_wizji,
        "kategoria_ze_sklepu": zrodla.get("sklep", 0),
        "kategoria_z_nazwy": zrodla.get("nazwa", 0),
        "nieprzypisane": sum(1 for p in produkty if p.kategoria == kategorie.NIEZNANA),
        "bez_danych": kompl.get("pusty", 0) + kompl.get("szczatkowy", 0),
        "ok": kompl.get("ok", 0),
    }


def historia(con, limit: int = 12) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT * FROM przebiegi ORDER BY id DESC LIMIT ?", (limit,))]


def wgrane_pliki(limit: int = 12) -> list[dict]:
    if not KATALOG_DANYCH.exists():
        return []
    pliki = sorted((p for p in KATALOG_DANYCH.glob("*.csv")),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"nazwa": p.name, "rozmiar_mb": round(p.stat().st_size / 1_048_576, 1),
             "zmodyfikowano": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
            for p in pliki[:limit]]


def sciezka_wgranego(nazwa: str) -> Path | None:
    """Zwraca ścieżkę pliku z katalogu danych. Odrzuca próby wyjścia poza niego."""
    kandydat = (KATALOG_DANYCH / Path(nazwa).name).resolve()
    if kandydat.parent != KATALOG_DANYCH.resolve() or not kandydat.exists():
        return None
    return kandydat


def wyczysc_stare(zostaw: int = 10) -> int:
    """Kasuje najstarsze wgrane pliki, zostawiając `zostaw` najnowszych."""
    pliki = sorted(KATALOG_DANYCH.glob("*__*.csv"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    usuniete = 0
    for p in pliki[zostaw:]:
        try:
            p.unlink()
            usuniete += 1
        except OSError:
            pass
    return usuniete


__all__ = ["STAN", "zajety", "zapisz_plik", "uruchom_w_tle", "historia",
           "wgrane_pliki", "sciezka_wgranego", "wyczysc_stare", "shutil"]
