"""Format eksportu/importu panelu sklepu.

Plik z panelu (`admin-product-product-*.xlsx`) ma stały układ:

    wiersz 1   hash eksportu (kolumna 27)
    wiersz 2   „Produkty - Produkty"
    wiersz 3   opis filtrów, z jakimi zrobiono eksport
    wiersz 4   Export date | data | Items: | N | Limit: 2000
    wiersz 5   pusty
    wiersz 6   NAGŁÓWKI (165 kolumn)
    wiersz 7+  dane

Najważniejsza rzecz w tym module: wartości słownikowe w panelu to
`ID|etykieta` („2022|tapicerowane"), a nasze źródło (eksport z BigQuery) ma
same etykiety. Bez ID plik się nie zaimportuje albo — gorzej — zaimportuje
się jako nowa wartość słownika. Dlatego mapowanie etykieta→ID wyciągamy
z prawdziwych plików z panelu i trzymamy w `config/slownik_idow.yaml`.

Konsekwencja, o której trzeba pamiętać: słownik zna tylko te wartości,
które kiedykolwiek widzieliśmy w jakimś eksporcie. Poprawki na wartości
spoza słownika nie trafiają do pliku — lądują na liście „bez ID" na
stronie eksportu, zamiast po cichu wyjść jako gołe etykiety.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import KATALOG_CONFIG
from .tekst import norm

PLIK_SLOWNIKA = KATALOG_CONFIG / "slownik_idow.yaml"
PLIK_WZORCA = KATALOG_CONFIG / "wzorzec_panelu.yaml"

WIERSZ_NAGLOWKA = 6
RE_ID_ETYKIETA = re.compile(r"^(\d+)\|(.+)$", re.S)

# Kolumny, po których panel rozpoznaje produkt — zawsze wypełniane.
KOLUMNY_KLUCZA = ("ID", "Kod", "Kod producenta", "Nazwa")

# Nasze nazwy atrybutów = nazwy kolumn w panelu, poza tymi wyjątkami.
ALIASY_KOLUMN: dict[str, str] = {
    "Na nóżkach": "Na nóżkach",
    "Liczba drzwi": "Liczba drzwi",
}


@dataclass
class Wzorzec:
    """Układ pliku z panelu — nagłówki, preambuła i charakter kolumn."""
    naglowki: list[str] = field(default_factory=list)
    preambula: list[list] = field(default_factory=list)   # wiersze 1-5
    # kolumny, w których widzieliśmy wartości surowe (liczby, teksty) — te
    # wolno przepisać jeden do jednego
    surowe: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.naglowki) and "ID" in self.naglowki


def wczytaj_wzorzec() -> Wzorzec:
    if not PLIK_WZORCA.exists():
        return Wzorzec()
    d = yaml.safe_load(PLIK_WZORCA.read_text(encoding="utf-8")) or {}
    return Wzorzec(naglowki=list(d.get("naglowki") or []),
                   preambula=[list(w) for w in (d.get("preambula") or [])],
                   surowe=list(d.get("surowe") or []))


def zapisz_wzorzec(w: Wzorzec) -> None:
    PLIK_WZORCA.parent.mkdir(parents=True, exist_ok=True)
    PLIK_WZORCA.write_text(yaml.safe_dump(
        {"naglowki": w.naglowki, "surowe": w.surowe, "preambula": w.preambula},
        allow_unicode=True, sort_keys=False), encoding="utf-8")


# --- słownik ID -----------------------------------------------------------

def wczytaj_slownik() -> dict[str, dict[str, list[str]]]:
    if not PLIK_SLOWNIKA.exists():
        return {}
    return yaml.safe_load(PLIK_SLOWNIKA.read_text(encoding="utf-8")) or {}


def zapisz_slownik(s: dict) -> None:
    PLIK_SLOWNIKA.parent.mkdir(parents=True, exist_ok=True)
    PLIK_SLOWNIKA.write_text(yaml.safe_dump(s, allow_unicode=True, sort_keys=True),
                             encoding="utf-8")


def id_dla(slownik: dict, kolumna: str, etykieta: str) -> tuple[str | None, str]:
    """(wartość do pliku, powód gdy się nie da).

    Zwraca `ID|etykieta`, gdy znamy dokładnie jedno ID. Gdy etykieta ma
    w panelu kilka ID (zdarza się — ta sama nazwa w różnych zestawach
    atrybutów), nie zgadujemy: lepiej zostawić to człowiekowi.
    """
    ids = (slownik.get(kolumna) or {}).get(norm(etykieta))
    if not ids:
        return None, "nieznane ID w panelu"
    if len(ids) > 1:
        return None, f"niejednoznaczne ID ({', '.join(ids)})"
    return f"{ids[0]}|{etykieta}", ""


def wartosc_do_pliku(slownik: dict, kolumna: str, wartosc: str,
                     kolumny_slownikowe: set[str],
                     kolumny_surowe: set[str] | None = None) -> tuple[str | None, str]:
    """Liczby i teksty idą jak są; słownikowe muszą dostać ID.

    Kolumna, której nigdy nie widzieliśmy w pliku z panelu, jest trzecim
    przypadkiem i najgroźniejszym: nie wiemy, czy panel oczekuje tam gołego
    tekstu, czy `ID|etykieta`. Wpisanie gołej etykiety do kolumny słownikowej
    kończy się nową, śmieciową wartością w słowniku sklepu — więc takiej
    poprawki po prostu nie wypuszczamy.
    """
    if kolumna in kolumny_slownikowe:
        return id_dla(slownik, kolumna, wartosc)
    if kolumny_surowe is None or kolumna in kolumny_surowe:
        return wartosc, ""
    return None, "kolumny nie było w żadnym pliku z panelu"


# --- nauka z pliku panelu -------------------------------------------------

def czy_plik_panelu(sciezka: str | Path) -> bool:
    """Czy to eksport z panelu (a nie nasz eksport produktów z BigQuery)."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(sciezka, read_only=True)
        ws = wb.active
        naglowki = [c.value for c in next(ws.iter_rows(
            min_row=WIERSZ_NAGLOWKA, max_row=WIERSZ_NAGLOWKA))]
        wb.close()
        return "ID" in naglowki and "Kod producenta" in naglowki
    except Exception:
        return False


def naucz_z_pliku(sciezka: str | Path) -> dict:
    """Wyciąga z pliku panelu układ kolumn i wszystkie pary ID|etykieta.

    Scala ze stanem na dysku — każdy kolejny eksport z panelu dokłada
    wartości, których wcześniej nie widzieliśmy.
    """
    import openpyxl
    wb = openpyxl.load_workbook(sciezka, read_only=True)
    ws = wb.active

    wiersze = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(wiersze) < WIERSZ_NAGLOWKA:
        raise ValueError("plik nie wygląda na eksport z panelu")

    naglowki = [(h or "") for h in wiersze[WIERSZ_NAGLOWKA - 1]]
    preambula = [[("" if c is None else c) for c in w]
                 for w in wiersze[:WIERSZ_NAGLOWKA - 1]]

    slownik = wczytaj_slownik()
    stary_wzorzec = wczytaj_wzorzec()
    nowych = 0
    kolumny_slownikowe: set[str] = set()
    surowe: set[str] = set(stary_wzorzec.surowe)

    for wiersz in wiersze[WIERSZ_NAGLOWKA:]:
        for naglowek, wartosc in zip(naglowki, wiersz):
            if not naglowek or wartosc is None or str(wartosc).strip() == "":
                continue
            m = RE_ID_ETYKIETA.match(str(wartosc).strip())
            if not m:
                surowe.add(naglowek)
                continue
            kolumny_slownikowe.add(naglowek)
            ident, etykieta = m.group(1), m.group(2).strip()
            kubelek = slownik.setdefault(naglowek, {})
            lista = kubelek.setdefault(norm(etykieta), [])
            if ident not in lista:
                lista.append(ident)
                nowych += 1

    zapisz_slownik(slownik)
    # kolumna, która kiedykolwiek wystąpiła jako ID|etykieta, zostaje
    # słownikowa — nawet jeśli gdzie indziej trafiła się w niej surowa wartość
    surowe -= set(slownik.keys())
    zapisz_wzorzec(Wzorzec(naglowki=naglowki, preambula=preambula,
                           surowe=sorted(surowe)))

    return {
        "kolumny": len(naglowki),
        "produktow": len(wiersze) - WIERSZ_NAGLOWKA,
        "kolumny_slownikowe": sorted(kolumny_slownikowe),
        "kolumny_surowe": sorted(surowe),
        "nowych_wartosci": nowych,
        "wartosci_razem": sum(len(v) for v in slownik.values()),
        "nierozpoznanych": len([h for h in naglowki
                                if h and h not in slownik and h not in surowe]),
    }


def kolumny_slownikowe(slownik: dict | None = None) -> set[str]:
    return set((slownik if slownik is not None else wczytaj_slownik()).keys())
