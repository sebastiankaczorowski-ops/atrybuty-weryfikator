"""Rozpoznanie arkusza „RAW FILES” — która zakładka, jaki klucz, jakie pola.

Ręczne mapowanie ~90 zakładek to dzień klikania i zgadywania, co autor
feedu miał na myśli. Zamiast zgadywać po nazwach pól, **mierzymy**:

* klucz — to pole, którego wartości najczęściej trafiają w kody naszych
  produktów (EAN, kod producenta). Bez naszego `id`: numer produktu
  u Bogartu (50979) potrafi się przypadkiem pokryć z id w sklepie;
* producent — ten, do którego należą trafione produkty;
* wymiary i waga — to pole, które na dopasowanych produktach **zgadza się
  z naszymi wartościami** w większości przypadków. Dzięki temu kolejność
  „wymiar 1/2/3” z opisu Halmaru rozstrzygają dane, a nie założenie.

Wynik to propozycja do zatwierdzenia w `/zrodla/rozpoznanie`. Nic nie
trafia do źródeł bez kliknięcia człowieka.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import arkusze, zrodla
from .tekst import do_liczby, norm

PLIK_RAPORTU = "rozpoznanie-arkusza.json"

# Pole uznajemy za „to samo co nasz atrybut”, gdy zgadza się na co najmniej
# połowie produktów, na których obie strony mają wartość. Niżej to już
# najpewniej inna wielkość (wymiar paczki, długość zamiast głębokości) —
# zmapowana dałaby kolejkę pełną fałszywych rozjazdów.
PROG_ZGODNOSCI = 0.5
MIN_PAR = 5
# Mniej trafionych produktów niż tyle — zakładka nie nadaje się na źródło
# (za mało, żeby ocenić pola, i za mało, żeby się opłacało).
MIN_TRAFIEN = 5

RE_SUFIKS_ZAKLADKI = re.compile(
    r"(stock|products?|logistics|fromimporter|ours|v\d+)+$", re.I)


# --- nasze produkty -------------------------------------------------------

def indeks_kodow(con: sqlite3.Connection) -> dict[str, set[str]]:
    """znormalizowany kod -> id naszych produktów.

    Bez `id` produktu z naszego sklepu — patrz docstring modułu.
    """
    out: dict[str, set[str]] = defaultdict(set)
    for r in con.execute("SELECT id, nazwa, kody FROM produkty"):
        kody = json.loads(r["kody"] or "{}")
        for k in zrodla.klucze_produktu(r["nazwa"], "", kody):
            out[k].add(r["id"])
    return out


def nasze_produkty(con: sqlite3.Connection) -> dict[str, dict]:
    return {r["id"]: {"producent": r["producent"] or "",
                      "liczby": json.loads(r["liczby"] or "{}")}
            for r in con.execute("SELECT id, producent, liczby FROM produkty")}


# --- analiza jednej zakładki ----------------------------------------------

def przeanalizuj(rek: list[dict], indeks: dict[str, set[str]],
                 produkty: dict[str, dict], producenci: list[str],
                 tytul: str = "") -> dict:
    pola = zrodla.opisz_pola(rek, maks=400)
    wynik: dict = {"rekordow": len(rek), "pol": len(pola), "uwagi": []}

    klucz, trafione = _najlepszy_klucz(rek, pola, indeks)
    wynik["klucz"] = klucz
    wynik["trafionych_produktow"] = len({p for ps in trafione.values() for p in ps})

    wynik["producent_z_nazwy"] = producent_z_nazwy(tytul, producenci)
    prod_licznik = Counter(produkty[p]["producent"] for ps in trafione.values()
                           for p in ps if p in produkty)
    if prod_licznik:
        prod, ile = prod_licznik.most_common(1)[0]
        wynik["producent"] = prod
        wynik["udzial_producenta"] = ile / sum(prod_licznik.values())
        if wynik["udzial_producenta"] < 0.9:
            wynik["uwagi"].append(
                "trafione produkty należą do kilku producentów: "
                + ", ".join(f"{p} ({n})" for p, n in prod_licznik.most_common(4)))
    else:
        wynik["producent"] = wynik["producent_z_nazwy"]
        wynik["udzial_producenta"] = 0.0

    mapowanie = {}
    if klucz:
        mapowanie["klucz"] = klucz
    podpowiedz = zrodla.zgadnij_mapowanie(pola)
    for pole in ("nazwa", "kolekcja"):
        if podpowiedz.get(pole):
            mapowanie[pole] = podpowiedz[pole]

    wynik["zgodnosc"] = {}
    if klucz and wynik["trafionych_produktow"] >= MIN_TRAFIEN:
        pary = _pary(rek, klucz, trafione, produkty)
        zgodnosc, uwagi = dobierz_pola_liczbowe(pary, pola)
        wynik["zgodnosc"] = zgodnosc
        wynik["uwagi"] += uwagi
        for docelowe, z in zgodnosc.items():
            if z["zmapowane"]:
                mapowanie[docelowe] = z["pole"]
    elif klucz:
        wynik["uwagi"].append(f"tylko {wynik['trafionych_produktow']} trafionych produktów "
                              "— za mało, żeby ocenić pola")
    else:
        wynik["uwagi"].append("żadne pole nie trafia w kody naszych produktów")

    wynik["mapowanie"] = mapowanie
    return wynik


def _najlepszy_klucz(rek: list[dict], pola: list, indeks: dict[str, set[str]]
                     ) -> tuple[str, dict[int, set[str]]]:
    """Pole, które trafia w najwięcej RÓŻNYCH naszych produktów.

    Zwraca też {nr rekordu: id produktów}, żeby dalej nie liczyć od nowa.
    """
    najlepsze, najlepsze_trafione, najwiecej = "", {}, 0
    for p in pola:
        if p.wypelnienie < 0.3:
            continue
        trafione: dict[int, set[str]] = {}
        for i, r in enumerate(rek):
            ps = indeks.get(norm(r.get(p.nazwa, "")))
            if ps:
                trafione[i] = ps
        ile = len({x for ps in trafione.values() for x in ps})
        if ile > najwiecej:
            najlepsze, najlepsze_trafione, najwiecej = p.nazwa, trafione, ile
    return najlepsze, najlepsze_trafione


def _pary(rek: list[dict], klucz: str, trafione: dict[int, set[str]],
          produkty: dict[str, dict]) -> list[tuple[dict, dict]]:
    """(rekord feedu, nasze liczby) dla każdego dopasowanego produktu."""
    out = []
    for i, ps in trafione.items():
        for p in ps:
            if p in produkty:
                out.append((rek[i], produkty[p]["liczby"]))
    return out


def dobierz_pola_liczbowe(pary: list[tuple[dict, dict]], pola: list
                          ) -> tuple[dict[str, dict], list[str]]:
    """Dla każdego z porównywanych atrybutów — pole feedu najbardziej zgodne
    z naszymi wartościami. Jedno pole feedu obsługuje najwyżej jeden atrybut.
    """
    # Pola paczki odpadają od razu, nie dopiero przy mapowaniu: szerokość
    # kartonu bywa przypadkiem równa szerokości mebla i wtedy wygrywała
    # z polem z opisu, a potem nie była mapowana — atrybut zostawał pusty.
    kandydaci = [p.nazwa for p in pola if p.wyglada_na_liczbe
                 and not zrodla._to_paczka(p.nazwa)]
    wyniki: list[tuple[float, int, str, str, int]] = []   # (udział, zgodnych, cel, pole, par)
    uwagi: list[str] = []
    for docelowe, tolerancja in zrodla.TOLERANCJA.items():
        for pole in kandydaci:
            par, zgodnych, zgodnych_mm = 0, 0, 0
            for r, nasze in pary:
                ref = do_liczby(r.get(pole, ""))
                nasza = nasze.get(docelowe)
                if ref is None or ref <= 0 or not nasza:
                    continue
                par += 1
                if abs(nasza - ref) / nasza <= tolerancja:
                    zgodnych += 1
                elif abs(nasza - ref / 10) / nasza <= tolerancja:
                    zgodnych_mm += 1
            if par >= MIN_PAR:
                wyniki.append((zgodnych / par, zgodnych, docelowe, pole, par))
                if zgodnych_mm / par >= PROG_ZGODNOSCI:
                    uwagi.append(f"{pole} zgadza się z naszym „{docelowe}” po podzieleniu "
                                 f"przez 10 — pole jest w mm, nie mapuję go automatycznie")

    zgodnosc: dict[str, dict] = {}
    uzyte: set[str] = set()
    for udzial, zgodnych, docelowe, pole, par in sorted(wyniki, reverse=True):
        if docelowe in zgodnosc or pole in uzyte:
            continue
        zmapowane = udzial >= PROG_ZGODNOSCI
        zgodnosc[docelowe] = {"pole": pole, "par": par, "zgodnych": zgodnych,
                              "udzial": udzial, "zmapowane": zmapowane}
        if zmapowane:
            uzyte.add(pole)
    # Najlepszy kandydat poniżej progu zostaje w raporcie jako informacja,
    # ale nie zajmuje pola — mógłby je odebrać innemu atrybutowi.
    return zgodnosc, uwagi


def producent_z_nazwy(tytul: str, producenci: list[str]) -> str:
    """„HalmarStock” -> „Halmar”, jeśli taki producent jest w naszej bazie."""
    rdzen = RE_SUFIKS_ZAKLADKI.sub("", tytul or "").lower()
    if len(rdzen) < 3:
        return ""
    for p in sorted(producenci, key=len):
        zwarty = norm(p).replace(" ", "")
        if zwarty and (zwarty.startswith(rdzen) or rdzen.startswith(zwarty)):
            return p
    return ""


# --- cały arkusz ----------------------------------------------------------

def rozpoznaj_arkusz(con: sqlite3.Connection, url: str, katalog_danych: Path,
                     pauza: float = 1.0, wypisz=print) -> dict:
    """Przechodzi wszystkie zakładki i zapisuje raport w katalogu danych."""
    id_arkusza, _ = arkusze.rozbierz_url(url)
    tok = arkusze.token()
    lista = arkusze.zakladki(id_arkusza, tok)
    indeks = indeks_kodow(con)
    produkty = nasze_produkty(con)
    producenci = sorted({p["producent"] for p in produkty.values() if p["producent"]})
    if not indeks:
        raise arkusze.BladArkusza("w bazie nie ma kodów produktów (EAN / kod producenta) — "
                                  "najpierw zaimportuj eksport z kolumnami kodów")

    zakladki = []
    for n, z in enumerate(lista, 1):
        wpis = {"gid": z["gid"], "tytul": z["tytul"],
                "url": f"https://docs.google.com/spreadsheets/d/{id_arkusza}/edit#gid={z['gid']}"}
        try:
            wiersze = arkusze.wartosci_zakladki(id_arkusza, z["tytul"], tok)
            dane = arkusze.zloz_zakladke(wiersze)
            fmt = zrodla.wykryj_format(dane)
            rek, tag = zrodla.rekordy(dane, fmt)
            wpis.update(format=fmt, tag=tag)
            wpis.update(przeanalizuj(rek, indeks, produkty, producenci, z["tytul"]))
        except (arkusze.BladArkusza, zrodla.BladZrodla) as e:
            wpis["blad"] = str(e)
        zakladki.append(wpis)
        wypisz(f"[{n}/{len(lista)}] {z['tytul']}: "
               + (wpis.get("blad") or f"{wpis.get('trafionych_produktow', 0)} trafionych, "
                                      f"klucz {wpis.get('klucz') or '—'}"))
        time.sleep(pauza)   # limit Sheets API: 60 odczytów na minutę

    wybierz_najlepsze(zakladki)
    raport = {"utworzono": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "arkusz": id_arkusza, "zakladki": zakladki}
    (katalog_danych / PLIK_RAPORTU).write_text(
        json.dumps(raport, ensure_ascii=False, indent=1), encoding="utf-8")
    return raport


def wybierz_najlepsze(zakladki: list[dict]) -> None:
    """Na producenta jedna polecana zakładka — ta z największą liczbą
    trafionych produktów, a przy remisie z większą liczbą zmapowanych pól.

    Kilka zakładek jednego producenta (Stock / Products / V2 / V3) to
    najczęściej kolejne wersje importera; porównywanie z każdą naraz
    dawałoby sprzeczne findingi dla tego samego produktu.
    """
    grupy: dict[str, list[dict]] = defaultdict(list)
    for z in zakladki:
        z["polecana"] = False
        if z.get("producent") and z.get("trafionych_produktow", 0) >= MIN_TRAFIEN:
            grupy[z["producent"]].append(z)
    for grupa in grupy.values():
        najlepsza = max(grupa, key=lambda z: (z["trafionych_produktow"],
                                              len(z.get("mapowanie", {}))))
        najlepsza["polecana"] = True


def wczytaj_raport(katalog_danych: Path) -> dict | None:
    sciezka = katalog_danych / PLIK_RAPORTU
    if not sciezka.exists():
        return None
    return json.loads(sciezka.read_text(encoding="utf-8"))


def zastosuj(con: sqlite3.Connection, zakladka: dict) -> tuple[int, bool]:
    """Tworzy albo aktualizuje źródło z zakładki. Zwraca (id, czy nowe).

    Źródło rozpoznajemy po adresie zakładki — ponowne rozpoznanie arkusza
    nie mnoży duplikatów, tylko poprawia mapowanie istniejących.
    """
    zrodla.przygotuj_baze(con)
    gid = f"gid={zakladka['gid']}"
    for z in zrodla.lista_zrodel(con):
        if arkusze.jest_arkuszem(z.get("url") or "") and z["url"].endswith(gid):
            con.execute("UPDATE zrodla SET producent=?, strategia='klucz' WHERE id=?",
                        (zakladka.get("producent") or "", z["id"]))
            zrodla.zapisz_mapowanie(con, z["id"], zakladka["mapowanie"])
            return z["id"], False
    zid = zrodla.dodaj_zrodlo(con, f"{zakladka['tytul']} (arkusz)",
                              zakladka.get("producent") or "", url=zakladka["url"])
    # Po kodzie, nie „auto”: dopasowanie po nazwie przy 38 producentach
    # naraz to proszenie się o pomyłki, a klucz jest tu zmierzony.
    zrodla.ustaw_strategie(con, zid, "klucz")
    zrodla.zapisz_mapowanie(con, zid, zakladka["mapowanie"])
    return zid, True
