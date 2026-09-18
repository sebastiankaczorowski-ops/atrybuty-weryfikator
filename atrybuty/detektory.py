"""Detektory L1 (struktura) i L2 (statystyka i spójność).

Wszystko deterministyczne i darmowe. Żaden detektor nie zmienia danych —
produkuje wyłącznie findingi z propozycją, a o zastosowaniu decyduje człowiek
w kolejce weryfikacji.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

from . import config, kategorie, schema_gen
from .model import INFO, KRYTYCZNA, L1, L2, SREDNIA, Finding, Produkt
from .tekst import baza_nazwy, liczebniki_z_nazwy, norm, wymiary_z_nazwy

# ---------------------------------------------------------------- L1


def l1_struktura(p: Produkt) -> list[Finding]:
    f: list[Finding] = []
    sl = config.slowniki()

    if not p.ma_zdjecie:
        f.append(Finding(p.id, "zdjecie", "L1-BRAK-ZDJECIA", L1, KRYTYCZNA, 0.99,
                         None, None, "Brak zdjęcia — produkt wypada też z warstwy wizyjnej",
                         grupa="L1-BRAK-ZDJECIA"))

    for klucz, wpis in (config.reguly().get("klucze_do_usuniecia") or {}).items():
        if klucz in p.atrybuty:
            f.append(Finding(p.id, klucz, "L1-KLUCZ-SMIEC", L1, KRYTYCZNA, 0.90,
                             p.atrybuty[klucz], None,
                             f"{wpis.get('powod', '').strip()} Propozycja: {wpis.get('propozycja', '')}",
                             grupa=f"L1-KLUCZ-SMIEC|{klucz}|{p.atrybuty[klucz]}"))

    # atrybuty wymagane dla kategorii — wyznaczone z pokrycia (schema.yaml)
    if not kategorie.jest_niemeblowa(p.kategoria):
        wpis = config.schema().get("kategorie", {}).get(p.kategoria, {})
        prog = config.slowniki().get("prog_wymagalnosci", 0.95)
        pokrycie = wpis.get("pokrycie", {})
        for klucz, udzial in pokrycie.items():
            if udzial < prog or klucz in p.atrybuty:
                continue
            waga = KRYTYCZNA if klucz in WYMIARY_KRYTYCZNE else SREDNIA
            f.append(Finding(p.id, klucz, "L1-BRAK-WYMAGANEGO", L1, waga, 0.85,
                             None, None,
                             f"Atrybut wypełniony u {udzial:.0%} produktów kategorii "
                             f"'{kategorie.nazwy_kategorii().get(p.kategoria, p.kategoria)}', tu go brak",
                             grupa=f"L1-BRAK-WYMAGANEGO|{p.kategoria}|{klucz}"))
    return f


WYMIARY_KRYTYCZNE = {"Szerokość", "Wysokość", "Głębokość", "Waga", "Materiał"}


def l1_sprzecznosci(p: Produkt) -> list[Finding]:
    f: list[Finding] = []
    for reg in config.reguly().get("sprzecznosci", []) or []:
        gdy = reg.get("gdy", {})
        if not gdy or not all(p.atrybuty.get(k) == v for k, v in gdy.items()):
            continue

        for zakazany in reg.get("nie_moze_miec", []):
            if zakazany in p.atrybuty:
                f.append(Finding(
                    p.id, zakazany, reg["id"], L2, KRYTYCZNA, 0.80,
                    p.atrybuty[zakazany], None,
                    f"{reg['opis']} ({list(gdy.items())[0][0]}={list(gdy.values())[0]}, "
                    f"{zakazany}={p.atrybuty[zakazany]})",
                    grupa=f"{reg['id']}|{zakazany}|{p.atrybuty[zakazany]}"))

        for fragment in reg.get("nazwa_zawiera", []) or []:
            if fragment in norm(p.nazwa):
                klucz = list(gdy.keys())[0]
                f.append(Finding(
                    p.id, klucz, reg["id"] + "-NAZWA", L2, KRYTYCZNA, 0.75,
                    p.atrybuty.get(klucz), None,
                    f"{reg['opis']} — nazwa zawiera '{fragment}'",
                    grupa=f"{reg['id']}-NAZWA|{klucz}"))
    return f


def l1_relacje(p: Produkt) -> list[Finding]:
    f: list[Finding] = []
    for reg in config.reguly().get("relacje", []) or []:
        a, b = p.liczby.get(reg["lewa"]), p.liczby.get(reg["prawa"])
        if a is None or b is None:
            continue
        ok = a <= b if reg["operator"] == "<=" else a < b
        if not ok:
            f.append(Finding(
                p.id, reg["lewa"], reg["id"], L2, KRYTYCZNA, 0.85,
                str(a), None,
                f"{reg['opis']}: {reg['lewa']}={a} {reg['operator']} {reg['prawa']}={b} niespełnione",
                grupa=f"{reg['id']}"))
    return f


# ---------------------------------------------------------------- L2

SKALE = [(10, "×10"), (0.1, "÷10"), (0.01, "÷100"), (100, "×100")]
MARGINES_SKALI = 1.5   # ile razy poza zakresem, żeby uznać to za pomyłkę jednostki


def l2_zakresy(p: Produkt) -> list[Finding]:
    """Outliery wymiarowe + test skali.

    Test skali jest ważniejszy od samego wykrycia outliera: jeśli wartość
    po przemnożeniu/podzieleniu wpada w normę kategorii, to nie jest dziwny
    produkt tylko pomyłka jednostki — i znamy konkretną propozycję poprawki.
    """
    f: list[Finding] = []
    if kategorie.jest_niemeblowa(p.kategoria):
        return f

    for klucz, wartosc in p.liczby.items():
        z = schema_gen.zakres(p.kategoria, klucz)
        if not z:
            continue
        lo, hi = z["min_dopuszczalne"], z["max_dopuszczalne"]
        if lo <= wartosc <= hi:
            continue

        # Propozycję zmiany skali wystawiamy tylko wtedy, gdy wartość jest
        # WYRAŹNIE poza zakresem. Fotel o wadze 85 kg wystaje ponad p99 (68),
        # ale "8.5 kg" jest gorsze niż zostawienie tego człowiekowi —
        # margines ratuje nas przed masowym psuciem poprawnych danych.
        wyraznie_poza = wartosc > hi * MARGINES_SKALI or wartosc < lo / MARGINES_SKALI
        for mnoznik, opis in (SKALE if wyraznie_poza else ()):
            kandydat = wartosc * mnoznik
            if z["p1"] <= kandydat <= z["p99"]:
                fmt = int(kandydat) if float(kandydat).is_integer() else round(kandydat, 1)
                f.append(Finding(
                    p.id, klucz, "L2-SKALA", L2, KRYTYCZNA, 0.88,
                    _s(wartosc), str(fmt),
                    f"Poza zakresem kategorii ({lo}-{hi}), ale po {opis} wpada w normę "
                    f"(mediana {z['mediana']}, p1-p99 {z['p1']}-{z['p99']})",
                    grupa=f"L2-SKALA|{klucz}|{opis}"))
                break
        else:
            f.append(Finding(
                p.id, klucz, "L2-OUTLIER", L2, SREDNIA, 0.55,
                _s(wartosc), None,
                f"Poza zakresem kategorii: {lo}-{hi} (mediana {z['mediana']}, n={z['n']})",
                grupa=f"L2-OUTLIER|{p.kategoria}|{klucz}"))
    return f


def _s(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


# Kategorie, w których wymiar z nazwy opisuje POWIERZCHNIĘ SPANIA,
# a nie wymiar zewnętrzny — "Łóżko 90x200" o szerokości 108 cm jest poprawne.
KATEGORIE_SPANIA = {"lozko", "lozko_dzieciece", "polkotapczan", "materac", "stelaz"}

MAPA_LICZEBNIKOW = {
    "drzwi": "Liczba drzwi",
    "szuflady": "Liczba szuflad",
    "polki": "Liczba półek",
    "drazki": "Liczba drążków",
}


def _liczba_z_enuma(wartosc: str | None) -> int | None:
    if not wartosc:
        return None
    n = norm(wartosc)
    if n.startswith("bez"):
        return 0
    m = re.match(r"(\d+)", n)
    if m:
        return int(m.group(1))
    if "i wiecej" in n:
        m = re.search(r"(\d+)", n)
        return int(m.group(1)) if m else None
    return None


def l2_nazwa_vs_atrybuty(p: Produkt) -> list[Finding]:
    """Nazwa jako niezależne źródło prawdy."""
    f: list[Finding] = []

    # --- liczebniki ---
    z_nazwy = liczebniki_z_nazwy(p.nazwa)

    # "z szufladami" — wiemy tylko, ze sa. To wystarczy, zeby zakwestionowac
    # "bez szuflad", ale nie zeby zaproponowac konkretna liczbe.
    if z_nazwy.pop("ma_szuflady", None) and p.atrybuty.get("Liczba szuflad") == "bez szuflad":
        f.append(Finding(
            p.id, "Liczba szuflad", "L2-NAZWA-ROZJAZD", L2, KRYTYCZNA, 0.80,
            "bez szuflad", None,
            "Nazwa mowi o szufladach, atrybut mowi 'bez szuflad'",
            grupa="L2-NAZWA-ROZJAZD|Liczba szuflad|bez"))

    for cecha, liczba in z_nazwy.items():
        klucz = MAPA_LICZEBNIKOW.get(cecha)
        if not klucz:
            continue
        obecna = p.atrybuty.get(klucz)
        if obecna is None:
            f.append(Finding(
                p.id, klucz, "L2-NAZWA-UZUPELNIA", L2, SREDNIA, 0.70,
                None, _enum_dla(klucz, liczba),
                f"Nazwa mówi o {liczba} ({cecha}), atrybut pusty",
                grupa=f"L2-NAZWA-UZUPELNIA|{klucz}"))
            continue
        w_atrybucie = _liczba_z_enuma(obecna)
        if w_atrybucie is not None and w_atrybucie != liczba:
            # "4 i więcej" kontra 5 z nazwy to nie sprzeczność
            if "wiecej" in norm(obecna) and liczba >= w_atrybucie:
                continue
            f.append(Finding(
                p.id, klucz, "L2-NAZWA-ROZJAZD", L2, KRYTYCZNA, 0.78,
                obecna, _enum_dla(klucz, liczba),
                f"Nazwa mówi o {liczba} ({cecha}), atrybut mówi '{obecna}'",
                grupa=f"L2-NAZWA-ROZJAZD|{klucz}"))

    # --- wymiary ---
    wym = wymiary_z_nazwy(p.nazwa)
    if wym and "a" in wym:
        pary = {wym["a"], wym["b"]}
        if p.kategoria in KATEGORIE_SPANIA:
            # porównujemy z powierzchnią spania, nie z wymiarem zewnętrznym
            szer = p.liczby.get("Szerokość powierzchni spania")
            dl = p.liczby.get("Długość powierzchni spania")
            if szer is not None and not any(abs(szer - v) <= 2 for v in pary):
                f.append(Finding(
                    p.id, "Szerokość powierzchni spania", "L2-NAZWA-WYMIAR", L2, SREDNIA, 0.65,
                    _s(szer), _s(min(pary)),
                    f"Nazwa podaje {int(wym['a'])}x{int(wym['b'])}, powierzchnia spania {_s(szer)}",
                    grupa="L2-NAZWA-WYMIAR|spanie-szer"))
            if szer is None and dl is None:
                f.append(Finding(
                    p.id, "Szerokość powierzchni spania", "L2-NAZWA-UZUPELNIA", L2, SREDNIA, 0.72,
                    None, _s(min(pary)),
                    f"Nazwa podaje wymiar spania {int(wym['a'])}x{int(wym['b'])}, atrybuty puste",
                    grupa="L2-NAZWA-UZUPELNIA|spanie"))
        else:
            szer = p.liczby.get("Szerokość")
            if szer is not None and not any(abs(szer - v) <= 3 for v in pary):
                gleb = p.liczby.get("Głębokość")
                wys = p.liczby.get("Wysokość")
                if not any(x is not None and any(abs(x - v) <= 3 for v in pary) for x in (gleb, wys)):
                    f.append(Finding(
                        p.id, "Szerokość", "L2-NAZWA-WYMIAR", L2, SREDNIA, 0.62,
                        _s(szer), None,
                        f"Nazwa podaje {int(wym['a'])}x{int(wym['b'])}, żaden wymiar się nie zgadza",
                        grupa="L2-NAZWA-WYMIAR|wymiar"))

    if "srednica" in wym and "Średnica" not in p.atrybuty:
        f.append(Finding(
            p.id, "Średnica", "L2-NAZWA-UZUPELNIA", L2, SREDNIA, 0.80,
            None, _s(wym["srednica"]),
            f"Nazwa podaje średnicę {_s(wym['srednica'])} cm, atrybut pusty",
            grupa="L2-NAZWA-UZUPELNIA|Średnica"))
    return f


def _enum_dla(klucz: str, liczba: int) -> str | None:
    """1 -> '1-drzwiowe' itd., na podstawie słownika atrybutu."""
    wartosci = config.slowniki().get("atrybuty", {}).get(klucz, {}).get("wartosci", [])
    for w in wartosci:
        if liczba == 0 and norm(w).startswith("bez"):
            return w
        m = re.match(r"(\d+)", w)
        if m and int(m.group(1)) == liczba and "wiecej" not in norm(w):
            return w
    for w in wartosci:
        m = re.match(r"(\d+)", w)
        if m and "wiecej" in norm(w) and liczba >= int(m.group(1)):
            return w
    return None


# --- spójność w rodzinie produktów --------------------------------------

ATRYBUTY_RODZINY = ["Materiał", "Stopień montażu", "Liczba drzwi", "Liczba szuflad",
                    "Liczba półek", "Styl", "Podparcie", "Rodzaj drzwi"]
MIN_RODZINA = 4
PROG_DOMINACJI = 0.8


def l2_rodzina(produkty: list[Produkt]) -> list[Finding]:
    """Wartość odstająca od reszty rodziny produktów.

    Łapie przypadek, którego nie widzi ani reguła, ani statystyka globalna:
    11 wariantów kolorystycznych ma 'płyta meblowa', dwunasty 'drewno'.
    """
    f: list[Finding] = []
    rodziny: dict[tuple[str, str, str], list[Produkt]] = defaultdict(list)
    for p in produkty:
        rodziny[(p.producent, p.kolekcja, baza_nazwy(p.nazwa))].append(p)

    for (prod, kol, baza), czlonkowie in rodziny.items():
        if len(czlonkowie) < MIN_RODZINA or not baza:
            continue
        for klucz in ATRYBUTY_RODZINY:
            wartosci = [p.atrybuty.get(klucz) for p in czlonkowie if p.atrybuty.get(klucz)]
            if len(wartosci) < MIN_RODZINA:
                continue
            licznik = Counter(wartosci)
            dominujaca, ile = licznik.most_common(1)[0]
            if len(licznik) < 2 or ile / len(wartosci) < PROG_DOMINACJI:
                continue
            for p in czlonkowie:
                w = p.atrybuty.get(klucz)
                if w and w != dominujaca:
                    f.append(Finding(
                        p.id, klucz, "L2-RODZINA", L2, SREDNIA, 0.72,
                        w, dominujaca,
                        f"W rodzinie '{baza}' ({prod}) {ile} z {len(wartosci)} produktów "
                        f"ma '{dominujaca}', ten ma '{w}'",
                        grupa=f"L2-RODZINA|{klucz}|{baza}"))
    return f


def l2_duplikaty(produkty: list[Produkt]) -> list[Finding]:
    """Identyczna nazwa u tego samego producenta — warianty czy realny duplikat."""
    f: list[Finding] = []
    grupy: dict[tuple[str, str], list[Produkt]] = defaultdict(list)
    for p in produkty:
        grupy[(p.producent, norm(p.nazwa))].append(p)

    for (prod, nazwa), czlonkowie in grupy.items():
        if len(czlonkowie) < 2:
            continue
        # jeśli różnią się wymiarami, to prawie na pewno warianty, nie duplikaty
        sygnatury = {tuple(sorted(p.liczby.items())) for p in czlonkowie}
        if len(sygnatury) > 1:
            continue
        ids = [p.id for p in czlonkowie]
        for p in czlonkowie:
            f.append(Finding(
                p.id, "nazwa", "L2-DUPLIKAT", L2, INFO, 0.50,
                p.nazwa, None,
                f"{len(czlonkowie)} produktów o tej samej nazwie i wymiarach u {prod}: "
                f"{', '.join(ids[:6])}{'…' if len(ids) > 6 else ''}",
                grupa=f"L2-DUPLIKAT|{prod}|{nazwa}"))
    return f


# ---------------------------------------------------------------- runner


def uruchom(produkty: list[Produkt], findingi_normalizacji: Iterable[Finding] = ()) -> list[Finding]:
    # Produkty bez danych nie idą przez detektory: "brak Szerokości" przy
    # produkcie, który nie ma ŻADNEGO atrybutu, to nie finding do poprawy
    # tylko brak danych u źródła. Lądują na osobnej liście (/braki).
    do_analizy = [p for p in produkty if not p.do_zrodla]
    bez_danych = {p.id for p in produkty if p.do_zrodla}

    out: list[Finding] = [f for f in findingi_normalizacji if f.produkt_id not in bez_danych]
    for p in do_analizy:
        out += l1_struktura(p)
        out += l1_sprzecznosci(p)
        out += l1_relacje(p)
        out += l2_zakresy(p)
        out += l2_nazwa_vs_atrybuty(p)
    out += l2_rodzina(do_analizy)
    out += l2_duplikaty(do_analizy)

    # Reguły wyłączone z podstrony /reguly nie trafiają do kolejki.
    # Filtrujemy na końcu, a nie w każdym detektorze osobno — jedno miejsce,
    # jedna prawda o tym, co jest aktywne.
    wylaczone = config.wylaczone()
    if wylaczone:
        out = [f for f in out if f.regula_id not in wylaczone]

    # Atrybut wyjęty z obiegu nie produkuje findingów w ogóle — żadna reguła,
    # żadna warstwa. Dzięki temu nie trafia też do wizji, więc nie płacimy za
    # zdjęcia, których i tak nie da się wykorzystać.
    bez_atrybutow = config.atrybuty_wylaczone()
    if bez_atrybutow:
        out = [f for f in out if f.atrybut not in bez_atrybutow]
    return out
