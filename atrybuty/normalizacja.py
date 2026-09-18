"""Normalizacja wartości atrybutów.

Normalizacja jest *deterministyczna i darmowa* — to ona sama, bez żadnej
decyzji człowieka, porządkuje ponad tysiąc rekordów (zdublowane materiały,
odwrócona kolejność listy, separatory dziesiętne).

Zwraca parę: (wartość znormalizowana, lista findingów).
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz, process

from . import config
from .model import INFO, KRYTYCZNA, L1, SREDNIA, Finding
from .tekst import do_liczby, norm


def _def_atrybutu(klucz: str) -> dict:
    return config.slowniki().get("atrybuty", {}).get(klucz, {})


def _bool_mapa() -> dict[str, str]:
    out = {}
    for kanon, warianty in config.slowniki().get("bool_aliasy", {}).items():
        for w in warianty:
            out[norm(str(w))] = kanon
    return out


def _po_przemianowaniu(klucz: str, wartosc: str) -> tuple[str, str]:
    """Stara nazwa atrybutu/wartości -> obecna nazwa ze sklepu.

    Cicho, bez findingu: to nie jest błąd w danych, tylko ślad po zmianie
    tytułu w panelu. ID w sklepie się nie zmieniło, więc świeży eksport
    ma już nową nazwę — przepisujemy wyłącznie starsze wgrania, żeby reguły
    i schema w ogóle ten atrybut zobaczyły.
    """
    mapa = config.zmiany_nazw()
    klucz = mapa["atrybuty"].get(klucz, klucz)
    pary = mapa["wartosci"].get(klucz) or {}
    if pary and wartosc:
        czlony = [c.strip() for c in wartosc.split(",")]
        if len(czlony) > 1:
            wartosc = ", ".join(pary.get(c, c) for c in czlony if c)
        else:
            wartosc = pary.get(wartosc, wartosc)
    return klucz, wartosc


def parsuj_atrybuty(surowe: str) -> dict[str, str]:
    """'Szerokość: 60 | Waga: 36' -> {'Szerokość': '60', 'Waga': '36'}"""
    out: dict[str, str] = {}
    for kawalek in (surowe or "").split("|"):
        if ":" not in kawalek:
            continue
        klucz, wartosc = kawalek.split(":", 1)
        klucz, wartosc = klucz.strip(), wartosc.strip()
        if klucz:
            klucz, wartosc = _po_przemianowaniu(klucz, wartosc)
            out[klucz] = wartosc
    return out


def normalizuj_produkt(produkt_id: str, surowe: dict[str, str]) -> tuple[dict[str, str], dict[str, float], list[Finding]]:
    wynik: dict[str, str] = {}
    liczby: dict[str, float] = {}
    findingi: list[Finding] = []

    for klucz, wartosc in surowe.items():
        d = _def_atrybutu(klucz)
        typ = d.get("typ", "tekst")

        if typ == "liczba":
            nowa, f = _norm_liczba(produkt_id, klucz, wartosc)
            if nowa is not None:
                liczby[klucz] = nowa
                wynik[klucz] = _fmt(nowa)
            else:
                wynik[klucz] = wartosc
            findingi += f

        elif typ == "multi_enum":
            nowa, f = _norm_multi(produkt_id, klucz, wartosc, d)
            wynik[klucz] = nowa
            findingi += f

        elif typ == "enum":
            nowa, f = _norm_enum(produkt_id, klucz, wartosc, d)
            wynik[klucz] = nowa
            findingi += f

        elif typ == "bool":
            nowa, f = _norm_bool(produkt_id, klucz, wartosc)
            wynik[klucz] = nowa
            findingi += f

        else:
            wynik[klucz] = re.sub(r"\s+", " ", wartosc).strip()

    return wynik, liczby, findingi


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:g}"


def _norm_liczba(pid: str, klucz: str, wartosc: str) -> tuple[float | None, list[Finding]]:
    v = do_liczby(wartosc)
    if v is not None:
        return v, []

    # "46, 46" — zdublowana wartość po migracji. Jeśli obie połówki są równe,
    # propozycja jest oczywista; jeśli nie, zostawiamy decyzję człowiekowi.
    czesci = [c.strip() for c in re.split(r"[;,]", wartosc or "") if c.strip()]
    liczbowe = [do_liczby(c) for c in czesci]
    if len(liczbowe) > 1 and all(x is not None for x in liczbowe):
        if len(set(liczbowe)) == 1:
            return liczbowe[0], [Finding(
                pid, klucz, "L1-FORMAT-DUBEL", L1, KRYTYCZNA, 0.95,
                wartosc, _fmt(liczbowe[0]),
                "Wartość zdublowana przecinkiem, obie połówki identyczne",
                grupa=f"L1-FORMAT-DUBEL|{klucz}")]
        return None, [Finding(
            pid, klucz, "L1-FORMAT-ROZNE", L1, KRYTYCZNA, 0.40,
            wartosc, None,
            f"Kilka różnych wartości w jednym polu: {czesci}",
            grupa=f"L1-FORMAT-ROZNE|{klucz}")]

    if (wartosc or "").strip():
        return None, [Finding(
            pid, klucz, "L1-NIE-LICZBA", L1, KRYTYCZNA, 0.90,
            wartosc, None, f"Pole liczbowe ({klucz}) zawiera tekst",
            grupa=f"L1-NIE-LICZBA|{klucz}|{wartosc}")]
    return None, []


def _norm_multi(pid: str, klucz: str, wartosc: str, d: dict) -> tuple[str, list[Finding]]:
    czesci = [c.strip() for c in (wartosc or "").split(",") if c.strip()]
    kanon: list[str] = []
    findingi: list[Finding] = []
    for c in czesci:
        w, f = _dopasuj(pid, klucz, c, d)
        findingi += f
        if w and w not in kanon:
            kanon.append(w)

    kanon.sort()
    nowa = ", ".join(kanon)
    stara_posortowana = ", ".join(sorted(czesci))

    if len(kanon) < len(czesci) and len(set(czesci)) < len(czesci):
        findingi.append(Finding(
            pid, klucz, "L1-LISTA-DUBEL", L1, SREDNIA, 0.98,
            wartosc, nowa, "Powtórzona wartość na liście",
            grupa=f"L1-LISTA-DUBEL|{klucz}|{wartosc}"))
    elif nowa != wartosc and nowa == stara_posortowana:
        findingi.append(Finding(
            pid, klucz, "L1-LISTA-KOLEJNOSC", L1, INFO, 0.99,
            wartosc, nowa, "Ta sama lista w innej kolejności — ujednolicenie",
            grupa=f"L1-LISTA-KOLEJNOSC|{klucz}|{wartosc}"))
    return nowa or wartosc, findingi


def _norm_enum(pid: str, klucz: str, wartosc: str, d: dict) -> tuple[str, list[Finding]]:
    tekst = (wartosc or "").strip()
    findingi: list[Finding] = []

    # "nowoczesny, nowoczesny" — wartość zdublowana przy migracji
    czesci = [c.strip() for c in tekst.split(",") if c.strip()]
    if len(czesci) > 1 and len(set(norm(c) for c in czesci)) == 1:
        findingi.append(Finding(
            pid, klucz, "L1-ENUM-DUBEL", L1, SREDNIA, 0.97,
            tekst, czesci[0], "Wartość powtórzona w polu jednowartościowym",
            grupa=f"L1-ENUM-DUBEL|{klucz}|{tekst}"))
        tekst = czesci[0]

    w, f = _dopasuj(pid, klucz, tekst, d)
    findingi += f
    return (w or tekst), findingi


def _norm_bool(pid: str, klucz: str, wartosc: str) -> tuple[str, list[Finding]]:
    mapa = _bool_mapa()
    w = mapa.get(norm(wartosc or ""))
    if w:
        return w, []
    if (wartosc or "").strip():
        return wartosc, [Finding(
            pid, klucz, "L1-BOOL", L1, SREDNIA, 0.70,
            wartosc, None, "Pole tak/nie z nietypową wartością",
            grupa=f"L1-BOOL|{klucz}|{wartosc}")]
    return wartosc, []


def _dopasuj(pid: str, klucz: str, wartosc: str, d: dict) -> tuple[str | None, list[Finding]]:
    """Wartość -> wartość kanoniczna. Kolejno: słownik, alias, rapidfuzz."""
    slownik: list[str] = d.get("wartosci", [])
    if not slownik:
        return wartosc, []

    aliasy = {norm(k): v for k, v in (d.get("aliasy") or {}).items()}
    n = norm(wartosc)

    for kanon in slownik:
        if norm(kanon) == n:
            if kanon != wartosc:
                # ta sama wartość, inny zapis ("Minimalistyczny" vs "minimalistyczny")
                return kanon, [Finding(
                    pid, klucz, "L1-ZAPIS", L1, INFO, 0.99,
                    wartosc, kanon, "Niespójny zapis tej samej wartości",
                    grupa=f"L1-ZAPIS|{klucz}|{wartosc}")]
            return kanon, []
    if n in aliasy:
        return aliasy[n], [Finding(
            pid, klucz, "L1-ALIAS", L1, INFO, 0.95,
            wartosc, aliasy[n], "Wariant zapisu zdefiniowany w słowniku",
            grupa=f"L1-ALIAS|{klucz}|{wartosc}")]

    progi = config.slowniki().get("progi_fuzzy", {"auto": 92, "sugestia": 78})
    trafienie = process.extractOne(n, [norm(x) for x in slownik], scorer=fuzz.WRatio)
    if trafienie:
        _, wynik, idx = trafienie
        kanon = slownik[idx]
        if wynik >= progi["auto"]:
            return kanon, [Finding(
                pid, klucz, "L1-SLOWNIK-AUTO", L1, INFO, 0.95,
                wartosc, kanon, f"Wariant zapisu, dopasowanie {wynik:.0f}%",
                grupa=f"L1-SLOWNIK-AUTO|{klucz}|{wartosc}")]
        if wynik >= progi["sugestia"]:
            return wartosc, [Finding(
                pid, klucz, "L1-SLOWNIK-SUGESTIA", L1, SREDNIA, 0.60,
                wartosc, kanon, f"Prawdopodobna literówka, dopasowanie {wynik:.0f}%",
                grupa=f"L1-SLOWNIK-SUGESTIA|{klucz}|{wartosc}")]

    return wartosc, [Finding(
        pid, klucz, "L1-SPOZA-SLOWNIKA", L1, SREDNIA, 0.50,
        wartosc, None, f"Wartość spoza słownika atrybutu {klucz}",
        grupa=f"L1-SPOZA-SLOWNIKA|{klucz}|{wartosc}")]
