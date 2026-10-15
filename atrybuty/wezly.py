"""Filtry sklepu według węzłów drzewa kategorii — źródło prawdy dla luk.

Dawniej filtry przypisywaliśmy do naszych typów (`komoda`, `wieszak`…), a typy
sklejają kategorie, które w drzewie panelu mają różne filtry. Skutek: fałszywe
luki — wieszakom liczyliśmy drzwi i drążki, zestawom kuchennym szuflady,
szafkom wiszącym nóżki (uwagi Ewy, 13.10.2026).

Teraz: konfiguracja filtrów 124 węzłów gałęzi Meble odczytana z panelu
(arkusz „Macierz filtrów per kategoria”, zakładka „Dane do importu”), a produkt
trafia do węzła po nazwach z eksportu:

* `typ` → węzeł o tej nazwie (zwykle poziom 2: „Komody”);
* `podtyp` → potomek tego węzła, dopasowany po nazwie także w starym,
  skróconym brzmieniu („Z szufladami” → „Komody z szufladami”).

Bierzemy najgłębszy dopasowany węzeł i nigdy jego przodków: grupa „Meble do
przechowywania” ma włączone filtry wszystkich dzieci — komoda dostałaby
„Liczbę drążków”. Podkategoria w panelu tylko odejmuje filtry względem
rodzica, więc najgłębszy węzeł jest zawsze najwęższy. (`typ` w eksporcie
nigdy nie jest nazwą grupy, więc grupy nie da się trafić wprost.)

Ograniczenie: eksport ma jeden `podtyp`, więc produkt w kilku węzłach naraz
dostaje filtry jednego. Pełna suma wymaga kolumny węzłów w eksporcie.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Any

import yaml

from . import config
from .tekst import bez_ogonkow, norm

PLIK = "wezly.yaml"

# Grupy z arkusza, które nie są atrybutami produktu do uzupełniania.
GRUPY_POMIJANE = {"Systemowe (nie z atrybutów produktu)"}
# Wspólne filtry spoza naszych danych: Kolor i Pomieszczenia nie są atrybutami
# eksportu, Styl jest wyjęty z obiegu (duplikaty w słowniku panelu).
FILTRY_POMIJANE = {"Kolor", "Pomieszczenia", "Styl"}


def slug(s: str) -> str:
    """„Szerokość pow. spania” i klucz `szerokosc-powierzchni-spania` → porównywalne."""
    return re.sub(r"[^a-z0-9]+", "-", bez_ogonkow(s or "").lower()).strip("-")


def _klucz_nazwy(s: str) -> str:
    return norm(re.sub(r"\[.*?\]", "", s or ""))


# --- budowa konfiguracji z arkusza ------------------------------------------

def z_arkusza(sciezka: str | Path, znane_atrybuty: set[str]) -> tuple[dict, dict]:
    """(konfiguracja, raport) z pliku xlsx z zakładkami „Macierz” i „Dane do importu”.

    Nazwy filtrów z arkusza („Szerokość pow. spania”) przechodzą na nasze nazwy
    atrybutów („Szerokość powierzchni spania”) po kluczu filtra z panelu.
    """
    import openpyxl
    wb = openpyxl.load_workbook(sciezka, read_only=True, data_only=True)

    # drzewo: kolejność wierszy + poziom wyznaczają rodzica
    wezly: dict[int, dict] = {}
    stos: list[tuple[int, int]] = []
    for r in list(wb["Macierz"].iter_rows(values_only=True))[4:]:
        if not r or r[0] in (None, ""):
            continue
        wid, poziom = int(r[0]), int(r[1])
        while stos and stos[-1][1] >= poziom:
            stos.pop()
        wezly[wid] = {"nazwa": re.sub(r"\s*\[.*?\]\s*", "", str(r[2])).strip(),
                      "poziom": poziom, "rodzic": stos[-1][0] if stos else None,
                      "sciezka": str(r[3] or "").strip(),
                      "ukryty": str(r[4] or "").strip().lower() == "tak", "filtry": []}
        stos.append((wid, poziom))

    po_slugu = {slug(a): a for a in znane_atrybuty}
    niezmapowane: set[str] = set()
    wiersze = list(wb["Dane do importu"].iter_rows(values_only=True))
    naglowek = [str(x or "") for x in wiersze[0]]
    for r in wiersze[1:]:
        if not r or r[0] in (None, ""):
            continue
        w = dict(zip(naglowek, r))
        if w.get("grupa") in GRUPY_POMIJANE or w.get("nazwa_filtra") in FILTRY_POMIJANE:
            continue
        atr = po_slugu.get(str(w.get("klucz_filtra") or "")) or po_slugu.get(slug(str(w.get("nazwa_filtra"))))
        if not atr:
            niezmapowane.add(str(w.get("nazwa_filtra")))
            continue
        wid = int(w["id_wezla"])
        if wid in wezly and atr not in wezly[wid]["filtry"]:
            wezly[wid]["filtry"].append(atr)
    for w in wezly.values():
        w["filtry"].sort()

    # Definicje filtrów (zakładka „Reguły filtrów”) — trafiają do pytań dla
    # Gemini, żeby model oceniał według definicji sklepu, a nie potocznie.
    definicje: dict[str, str] = {}
    if "Reguły filtrów" in wb.sheetnames:
        reguly = list(wb["Reguły filtrów"].iter_rows(values_only=True))
        nagl = [str(x or "") for x in reguly[0]]
        for r in reguly[1:]:
            w = dict(zip(nagl, r))
            tekst = str(w.get("definicja") or "").strip()
            atr = (po_slugu.get(str(w.get("klucz_filtra") or ""))
                   or po_slugu.get(slug(str(w.get("nazwa_filtra") or ""))))
            if tekst and atr:
                definicje[atr] = tekst

    raport = {"wezlow": len(wezly), "ukrytych": sum(w["ukryty"] for w in wezly.values()),
              "par": sum(len(w["filtry"]) for w in wezly.values()),
              "niezmapowane_filtry": sorted(niezmapowane)}
    raport["definicji"] = len(definicje)
    return {"wezly": wezly, "definicje": definicje}, raport


def zapisz(dane: dict, meta: dict, aliasy: dict | None = None) -> Path:
    sciezka = config.KATALOG_CONFIG / PLIK
    obecne = config._wczytaj(PLIK)
    tresc = {"meta": meta,
             # Aliasy typów eksportu bez odpowiednika w drzewie — do akceptacji
             # przez właścicielkę drzewa; zachowujemy przy ponownym wczytaniu arkusza.
             "aliasy_typow": aliasy if aliasy is not None else (obecne.get("aliasy_typow") or {}),
             "aliasy_par": obecne.get("aliasy_par") or {},
             # Decyzje właścicielki drzewa (Ewa, 14.10.2026) — też edytowane ręcznie.
             "wykluczone_typy": obecne.get("wykluczone_typy") or {},
             "poza_zakresem": obecne.get("poza_zakresem") or {},
             "definicje": dane.get("definicje") or {},
             "wezly": dane["wezly"]}
    with sciezka.open("w", encoding="utf-8") as f:
        f.write("# Filtry według węzłów drzewa kategorii panelu. Generowany komendą\n"
                "# `pipeline filtry-z-macierzy <xlsx>` — nie edytuj ręcznie węzłów;\n"
                "# zmieniaj arkusz i wczytaj ponownie. `aliasy_typow` wolno edytować.\n")
        yaml.safe_dump(tresc, f, allow_unicode=True, sort_keys=False, width=110)
    wyczysc_cache()
    return sciezka


# --- odczyt i przypisanie produktu ---------------------------------------------

@functools.lru_cache(maxsize=None)
def _konfig() -> dict[str, Any]:
    d = config._wczytaj(PLIK)
    if not d:
        return {}
    alias = config.zmiany_nazw()["atrybuty"]
    wezly = {}
    for wid, w in (d.get("wezly") or {}).items():
        w = dict(w)
        w["filtry"] = list(dict.fromkeys(alias.get(a, a) for a in w.get("filtry") or []))
        wezly[int(wid)] = w
    dzieci: dict[int, list[int]] = {}
    for wid, w in wezly.items():
        if w.get("rodzic") is not None:
            dzieci.setdefault(int(w["rodzic"]), []).append(wid)
    po_nazwie: dict[str, list[int]] = {}
    for wid, w in wezly.items():
        po_nazwie.setdefault(_klucz_nazwy(w["nazwa"]), []).append(wid)
    # „Typ / Podtyp” → nazwa węzła albo null (para jawnie bez węzła: akcesoria,
    # uchwyty — dostałyby filtry szafek i fałszywe luki)
    aliasy_par = {}
    for k, v in (d.get("aliasy_par") or {}).items():
        typ, _, pod = str(k).partition("/")
        aliasy_par[(_klucz_nazwy(typ), _klucz_nazwy(pod))] = v
    return {"wezly": wezly, "dzieci": dzieci, "po_nazwie": po_nazwie,
            "aliasy_typow": {_klucz_nazwy(k): v for k, v in (d.get("aliasy_typow") or {}).items()},
            "aliasy_par": aliasy_par,
            # typ → powód. Wykluczone: celowo bez luk (akcesoria, Konfigurator
            # Kuchni). Poza zakresem: błędny lub pusty typ — do przetypowania w panelu.
            "wykluczone_typy": {_klucz_nazwy(k): str(v or "")
                                for k, v in (d.get("wykluczone_typy") or {}).items()},
            "poza_zakresem": {_klucz_nazwy(k): str(v or "")
                              for k, v in (d.get("poza_zakresem") or {}).items()}}


def wyczysc_cache() -> None:
    _konfig.cache_clear()
    przypisz.cache_clear()


def meta() -> dict:
    return config._wczytaj(PLIK).get("meta") or {}


def aktywne() -> bool:
    return bool(_konfig().get("wezly"))


def wezly() -> dict[int, dict]:
    return _konfig().get("wezly") or {}


def _potomkowie(wid: int) -> list[int]:
    out, kolejka = [], list(_konfig()["dzieci"].get(wid, []))
    while kolejka:
        w = kolejka.pop(0)
        out.append(w)
        kolejka += _konfig()["dzieci"].get(w, [])
    return out


def _slowa(s: str) -> set[str]:
    # „komoda”/„komody”, „szafki”/„szafka” — porównujemy rdzenie (5 liter)
    return {w[:5] for w in _klucz_nazwy(s).split() if len(w) > 1}


def _dopasuj_podtyp(podtyp: str, kandydaci: list[int]) -> int | None:
    """Potomek, którego nazwa zawiera wszystkie słowa podtypu (po rdzeniach).

    „Z szufladami” → „Komody z szufladami”, ale nie „Komody z szufladami
    i drzwiczkami” — przy kilku pasujących wygrywa nazwa z najmniejszą
    liczbą słów spoza podtypu; remis = brak dopasowania (nie zgadujemy).
    """
    cel = _slowa(podtyp)
    if not cel:
        return None
    pasujace = []
    for wid in kandydaci:
        nazwa = _slowa(wezly()[wid]["nazwa"])
        if cel <= nazwa:
            pasujace.append((len(nazwa - cel), wid))
    if not pasujace:
        return None
    pasujace.sort()
    if len(pasujace) > 1 and pasujace[0][0] == pasujace[1][0]:
        return None
    return pasujace[0][1]


@functools.lru_cache(maxsize=None)
def przypisz(typ: str, podtyp: str) -> tuple[int | None, str]:
    """(id węzła, jak) dla produktu z eksportu.

    `jak`: podtyp | typ | alias | wykluczony | poza zakresem | ukryty | brak.
    Kolejność: para typ/podtyp z decyzji Ewy wygrywa z wykluczeniem całego typu —
    „Kuchnie / Szafki Górne” to samodzielna szafka z gałęzi Meble, choć reszta
    typu Kuchnie to wykluczony Konfigurator Kuchni.
    """
    k = _konfig()
    if not k:
        return None, "brak"
    para = (_klucz_nazwy(typ), _klucz_nazwy(podtyp))
    if para in k["aliasy_par"]:
        cel = k["aliasy_par"][para]
        if not cel:
            return None, "wykluczony"
        trafione = [w for w in k["po_nazwie"].get(_klucz_nazwy(cel), [])
                    if not k["wezly"][w].get("ukryty")]
        return (trafione[0], "alias") if len(trafione) == 1 else (None, "brak")
    if _klucz_nazwy(typ) in k["wykluczone_typy"]:
        return None, "wykluczony"
    if _klucz_nazwy(typ) in k["poza_zakresem"]:
        return None, "poza zakresem"
    nazwa_typu = k["aliasy_typow"].get(_klucz_nazwy(typ), typ)
    po_nazwie = k["po_nazwie"].get(_klucz_nazwy(nazwa_typu), [])
    kandydaci = [w for w in po_nazwie if not k["wezly"][w].get("ukryty")]
    if not kandydaci and po_nazwie:
        # węzeł ukryty ma włączone wszystkie filtry — luki byłyby fałszywe
        return None, "ukryty"
    if len(kandydaci) != 1:
        return None, "brak"
    wid = kandydaci[0]
    jak = "alias" if nazwa_typu != typ else "typ"
    if podtyp:
        potomkowie = [w for w in _potomkowie(wid) if not k["wezly"][w].get("ukryty")]
        dokladny = [w for w in potomkowie
                    if _klucz_nazwy(k["wezly"][w]["nazwa"]) == _klucz_nazwy(podtyp)]
        glebszy = dokladny[0] if len(dokladny) == 1 else _dopasuj_podtyp(podtyp, potomkowie)
        if glebszy:
            return glebszy, "podtyp"
    return wid, jak


def powod_bez_wezla(typ: str, podtyp: str) -> str:
    """Dlaczego produkt nie ma węzła — do tabeli na /filtry."""
    wid, jak = przypisz(typ, podtyp)
    if wid is not None:
        return ""
    k = _konfig()
    if jak == "wykluczony":
        return "wykluczony: " + (k["wykluczone_typy"].get(_klucz_nazwy(typ)) or "decyzja w wezly.yaml")
    if jak == "poza zakresem":
        return "do przetypowania w panelu: " + (k["poza_zakresem"].get(_klucz_nazwy(typ)) or "")
    if jak == "ukryty":
        return "węzeł ukryty w drzewie"
    return "brak dopasowania — do decyzji"


def definicja(atrybut: str) -> str:
    """Definicja filtra z arkusza (Reguły filtrów), po aliasach nazw."""
    d = config._wczytaj(PLIK).get("definicje") or {}
    alias = config.zmiany_nazw()["atrybuty"]
    for k, v in d.items():
        if alias.get(k, k) == atrybut:
            return str(v)
    return ""


def filtry_wezla(wid: int | None) -> list[str]:
    if wid is None:
        return []
    return list(wezly().get(int(wid), {}).get("filtry") or [])
