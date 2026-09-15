"""Klasyfikator kategorii.

Dopóki eksport nie ma kolumny `kategoria`, wyznaczamy ją z nazwy. Gdy kolumna
się pojawi — ma pierwszeństwo, a klasyfikator służy już tylko do uzupełniania
braków. Dzięki temu jutrzejsze dane niczego nie psują.
"""
from __future__ import annotations

import functools
import re

from . import config
from .tekst import norm

NIEZNANA = "nieznana"


@functools.lru_cache(maxsize=None)
def _reguly() -> list[tuple[str, list[re.Pattern[str]]]]:
    out: list[tuple[str, list[re.Pattern[str]]]] = []
    for wpis in config.kategorie().get("kategorie", []):
        wzorce = [re.compile(rf"\b{re.escape(norm(w))}\w*") for w in wpis.get("wzorce", [])]
        out.append((wpis["klucz"], wzorce))
    return out


@functools.lru_cache(maxsize=None)
def nazwy_kategorii() -> dict[str, str]:
    d = {w["klucz"]: w.get("nazwa", w["klucz"]) for w in config.kategorie().get("kategorie", [])}
    d[NIEZNANA] = "Nieznana"
    return d


@functools.lru_cache(maxsize=None)
def grupa_nadrzedna(kategoria: str) -> str:
    for grupa, czlonkowie in config.kategorie().get("grupy", {}).items():
        if kategoria in czlonkowie:
            return grupa
    return "pozostale"


@functools.lru_cache(maxsize=None)
def jest_niemeblowa(kategoria: str) -> bool:
    return kategoria in set(config.kategorie().get("niemeblowe", []))


@functools.lru_cache(maxsize=100_000)
def z_nazwy(nazwa: str) -> str:
    """Pierwsze dopasowanie wygrywa — kolejność w YAML-u niesie priorytet."""
    n = norm(nazwa)
    for klucz, wzorce in _reguly():
        for wz in wzorce:
            if wz.search(n):
                return klucz
    return NIEZNANA


def przypisz(nazwa: str, kategoria_ze_sklepu: str | None = None) -> tuple[str, str]:
    """Zwraca (kategoria, źródło).

    Taksonomia sklepu ma pierwszeństwo. Klasyfikator z nazwy zostaje jako
    zapasowy — dla produktów spoza eksportu kategorii i dla pustego typu.
    """
    if kategoria_ze_sklepu and kategoria_ze_sklepu.strip():
        zmapowana = _mapa_zrodlowa().get(norm(kategoria_ze_sklepu))
        if zmapowana:
            return zmapowana, "sklep"
        # typ spoza mapy — nie zgadujemy, oznaczamy do uzupełnienia mapy
        return NIEZNANA, "sklep_niezmapowany"
    return z_nazwy(nazwa), "nazwa"


@functools.lru_cache(maxsize=None)
def _mapa_zrodlowa() -> dict[str, str]:
    """Taksonomia sklepu (`type` z BigQuery) -> nasze klucze."""
    out = {norm(k): v for k, v in config.mapa_sklepu().items()}
    for wpis in config.kategorie().get("kategorie", []):
        for zr in wpis.get("zrodlowe", []) or []:
            out[norm(zr)] = wpis["klucz"]
    return out
