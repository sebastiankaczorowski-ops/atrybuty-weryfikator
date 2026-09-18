"""Wczytywanie konfiguracji z YAML-i.

Reguły mieszkają w config/*.yaml, nie w kodzie — stroisz je bez deploya.
"""
from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

KATALOG_CONFIG = Path(__file__).resolve().parent.parent / "config"


def _wczytaj(nazwa: str) -> dict[str, Any]:
    sciezka = KATALOG_CONFIG / nazwa
    if not sciezka.exists():
        return {}
    with sciezka.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@functools.lru_cache(maxsize=None)
def kategorie() -> dict[str, Any]:
    return _wczytaj("kategorie.yaml")


@functools.lru_cache(maxsize=None)
def slowniki() -> dict[str, Any]:
    return _wczytaj("slowniki.yaml")


@functools.lru_cache(maxsize=None)
def mapa_sklepu() -> dict[str, str]:
    """Taksonomia sklepu -> nasze klucze kategorii."""
    return _wczytaj("mapa_kategorii_sklepu.yaml").get("mapa", {})


@functools.lru_cache(maxsize=None)
def zmiany_nazw() -> dict[str, Any]:
    """Stara nazwa -> nowa, po przemianowaniach w panelu sklepu.

    Budowana po ID przy wgrywaniu słownika (`panel_format`). Potrzebna, bo
    eksporty produktów sprzed przemianowania niosą stare nazwy.
    """
    d = _wczytaj("zmiany_nazw.yaml")
    return {"atrybuty": d.get("atrybuty") or {}, "wartosci": d.get("wartosci") or {}}


@functools.lru_cache(maxsize=None)
def ustawienia() -> dict[str, Any]:
    return _wczytaj("ustawienia.yaml")


def link_produktu(pid: str) -> str:
    wzor = ustawienia().get("link_produktu", "")
    return wzor.replace("{id}", str(pid)) if wzor else ""


NAGLOWEK_REGUL = """# Reguły edytowalne z poziomu podstrony /reguly.
#
# UWAGA: ten plik jest NADPISYWANY przez aplikację przy każdej zmianie w UI,
# więc komentarze poza tym nagłówkiem nie przetrwają. Rzeczy, które chcesz
# opisać własnymi słowami, trzymaj w slowniki.yaml.
#
# klucze_do_usuniecia — klucze atrybutów, których w bazie być nie powinno
# sprzecznosci       — "jeśli atrybut ma wartość X, to atrybut Y nie może istnieć"
# relacje            — nierówności między atrybutami liczbowymi tego samego produktu
# wylaczone          — identyfikatory reguł (także wbudowanych), które mają nie działać
"""


@functools.lru_cache(maxsize=None)
def reguly() -> dict[str, Any]:
    """Reguły edytowalne z UI. Fallback do slowniki.yaml dla starszych instalacji."""
    d = _wczytaj("reguly.yaml")
    if d:
        return d
    s = slowniki()
    return {k: s.get(k, [] if k != "klucze_do_usuniecia" else {})
            for k in ("klucze_do_usuniecia", "sprzecznosci", "relacje", "wylaczone")}


def zapisz_reguly(dane: dict[str, Any]) -> Path:
    sciezka = KATALOG_CONFIG / "reguly.yaml"
    with sciezka.open("w", encoding="utf-8") as f:
        f.write(NAGLOWEK_REGUL)
        yaml.safe_dump(dane, f, allow_unicode=True, sort_keys=False, width=100)
    reguly.cache_clear()
    return sciezka


def wylaczone() -> set[str]:
    return set(reguly().get("wylaczone") or [])


@functools.lru_cache(maxsize=None)
def schema() -> dict[str, Any]:
    """Zakresy per kategoria. Generowany przez `schema_gen`, potem poprawiany ręcznie."""
    return _wczytaj("schema.yaml")


def zapisz_schema(dane: dict[str, Any]) -> Path:
    sciezka = KATALOG_CONFIG / "schema.yaml"
    with sciezka.open("w", encoding="utf-8") as f:
        yaml.safe_dump(dane, f, allow_unicode=True, sort_keys=False, width=100)
    schema.cache_clear()
    return sciezka


def wyczysc_cache() -> None:
    kategorie.cache_clear()
    mapa_sklepu.cache_clear()
    slowniki.cache_clear()
    zmiany_nazw.cache_clear()
    ustawienia.cache_clear()
    reguly.cache_clear()
    schema.cache_clear()
