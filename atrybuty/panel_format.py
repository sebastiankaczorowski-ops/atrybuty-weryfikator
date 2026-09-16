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


PLIK_ETYKIET = KATALOG_CONFIG / "etykiety_panelu.yaml"


def wczytaj_etykiety() -> dict[str, dict[str, str]]:
    if not PLIK_ETYKIET.exists():
        return {}
    return yaml.safe_load(PLIK_ETYKIET.read_text(encoding="utf-8")) or {}


def zapisz_etykiety(e: dict) -> None:
    PLIK_ETYKIET.parent.mkdir(parents=True, exist_ok=True)
    PLIK_ETYKIET.write_text(yaml.safe_dump(e, allow_unicode=True, sort_keys=True),
                            encoding="utf-8")


def id_dla(slownik: dict, kolumna: str, etykieta: str,
           etykiety: dict | None = None) -> tuple[str | None, str]:
    """(wartość do pliku, powód gdy się nie da).

    Zwraca `ID|etykieta`, gdy znamy dokładnie jedno ID. Gdy etykieta ma
    w panelu kilka ID (zdarza się — ta sama nazwa w różnych zestawach
    atrybutów), nie zgadujemy: lepiej zostawić to człowiekowi.
    """
    klucz = norm(etykieta)
    ids = (slownik.get(kolumna) or {}).get(klucz)
    if not ids:
        return None, "wartość spoza słownika sklepu"
    if len(ids) > 1:
        return None, f"niejednoznaczne ID ({', '.join(ids)})"
    kanoniczna = ((etykiety or {}).get(kolumna) or {}).get(klucz, etykieta)
    return f"{ids[0]}|{kanoniczna}", ""


# Wartości wielokrotne: nasz eksport podaje je jako „ceramika, metal".
# Każdy człon ma własne ID, więc mapujemy je po kolei i sklejamy z powrotem.
ROZDZIELACZ = ", "


def wartosc_slownikowa(slownik: dict, kolumna: str, wartosc: str,
                       etykiety: dict | None = None) -> tuple[str | None, str]:
    czlony = [c.strip() for c in str(wartosc).split(",") if c.strip()]
    if len(czlony) <= 1:
        return id_dla(slownik, kolumna, wartosc, etykiety)

    wyniki = []
    for c in czlony:
        w, powod = id_dla(slownik, kolumna, c, etykiety)
        if powod:
            return None, f"{powod}: „{c}”"
        wyniki.append(w)
    return ROZDZIELACZ.join(wyniki), ""


def wartosc_do_pliku(slownik: dict, kolumna: str, wartosc: str,
                     kolumny_slownikowe: set[str],
                     kolumny_surowe: set[str] | None = None,
                     etykiety: dict | None = None) -> tuple[str | None, str]:
    """Liczby i teksty idą jak są; słownikowe muszą dostać ID.

    Kolumna, której nigdy nie widzieliśmy w pliku z panelu, jest trzecim
    przypadkiem i najgroźniejszym: nie wiemy, czy panel oczekuje tam gołego
    tekstu, czy `ID|etykieta`. Wpisanie gołej etykiety do kolumny słownikowej
    kończy się nową, śmieciową wartością w słowniku sklepu — więc takiej
    poprawki po prostu nie wypuszczamy.
    """
    if kolumna in kolumny_slownikowe:
        return wartosc_slownikowa(slownik, kolumna, wartosc, etykiety)
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


# --- pełny słownik atrybutów ze sklepu ------------------------------------
#
# Eksport „Atrybuty" z panelu ma dwa arkusze: listę atrybutów (id, status,
# title) i listę wartości słownikowych (id, atrybut, wartość). To jest
# źródło prawdy, w przeciwieństwie do uczenia się z eksportów produktów,
# które pokazują tylko te wartości, które akurat gdzieś wystąpiły.

PLIK_ATRYBUTOW = KATALOG_CONFIG / "atrybuty_panelu.yaml"


def czy_plik_slownika(sciezka: str | Path) -> bool:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(sciezka, read_only=True)
        if len(wb.worksheets) < 2:
            wb.close()
            return False
        naglowki = [next(ws.iter_rows(values_only=True)) for ws in wb.worksheets[:2]]
        wb.close()
        return (tuple(naglowki[0][:3]) == ("id", "status", "title")
                and tuple(naglowki[1][:3]) == ("id", "title", "title"))
    except Exception:
        return False


def _ident(v) -> str:
    """'2022.0' i 2022 to ten sam identyfikator — arkusz podaje je jako float."""
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return str(v).strip()


def wczytaj_atrybuty_panelu() -> dict[str, dict]:
    if not PLIK_ATRYBUTOW.exists():
        return {}
    return yaml.safe_load(PLIK_ATRYBUTOW.read_text(encoding="utf-8")) or {}


def naucz_ze_slownika(sciezka: str | Path) -> dict:
    """Wgrywa kompletny słownik: atrybuty + ich dozwolone wartości.

    Nadpisuje wartości poznane wcześniej z eksportów produktów — ten plik
    jest pełny, tamte były wyrywkowe.
    """
    import openpyxl
    wb = openpyxl.load_workbook(sciezka, read_only=True)
    ark_atrybuty, ark_wartosci = wb.worksheets[0], wb.worksheets[1]

    atrybuty: dict[str, dict] = {}
    for r in list(ark_atrybuty.iter_rows(values_only=True))[1:]:
        if r[0] is None or not r[2]:
            continue
        atrybuty[str(r[2]).strip()] = {"id": _ident(r[0]), "status": str(r[1] or "")}

    slownik: dict[str, dict[str, list[str]]] = {}
    etykiety: dict[str, dict[str, str]] = {}
    ile_wartosci = 0
    smieci = 0
    for r in list(ark_wartosci.iter_rows(values_only=True))[1:]:
        if r[0] is None or not r[1] or r[2] is None:
            continue
        kolumna, etykieta = str(r[1]).strip(), str(r[2]).strip()
        # w słowniku sklepu siedzą pozycje o tytule „NULL" — to śmieć po
        # imporcie, nigdy poprawny cel poprawki
        if not etykieta or etykieta.upper() == "NULL":
            smieci += 1
            continue
        lista = slownik.setdefault(kolumna, {}).setdefault(norm(etykieta), [])
        # do pliku ma iść pisownia sklepu, nie nasza z eksportu BigQuery
        etykiety.setdefault(kolumna, {})[norm(etykieta)] = etykieta
        ident = _ident(r[0])
        if ident not in lista:
            lista.append(ident)
            ile_wartosci += 1
    wb.close()

    zapisz_slownik(slownik)
    zapisz_etykiety(etykiety)
    PLIK_ATRYBUTOW.parent.mkdir(parents=True, exist_ok=True)
    PLIK_ATRYBUTOW.write_text(yaml.safe_dump(atrybuty, allow_unicode=True, sort_keys=True),
                              encoding="utf-8")

    # atrybut z listy, którego nie ma w wartościach, jest polem wolnym
    # (liczba albo tekst) — te wolno przepisywać jeden do jednego
    wzorzec = wczytaj_wzorzec()
    wzorzec.surowe = sorted(set(wzorzec.surowe) |
                            {k for k in atrybuty if k not in slownik})
    wzorzec.surowe = [k for k in wzorzec.surowe if k not in slownik]
    zapisz_wzorzec(wzorzec)

    wylaczone = [k for k, v in atrybuty.items() if v["status"] != "ACTIVE"]
    return {
        "atrybutow": len(atrybuty),
        "slownikowych": len(slownik),
        "wartosci": ile_wartosci,
        "wolnych": len([k for k in atrybuty if k not in slownik]),
        "wylaczonych": len(wylaczone),
        "wylaczone": sorted(wylaczone),
        "smieci": smieci,
        "duplikaty": duplikaty(slownik),
    }


def duplikaty(slownik: dict | None = None) -> list[dict]:
    """Ta sama etykieta pod kilkoma ID w jednym atrybucie.

    To problem po stronie sklepu, nie nasz: dopóki „nowoczesny" ma trzy ID,
    nie da się rozstrzygnąć, które wpisać, więc takie poprawki wypadają
    z eksportu. Lista jest po to, żeby dało się to posprzątać w panelu.
    """
    s = slownik if slownik is not None else wczytaj_slownik()
    etykiety = wczytaj_etykiety()
    out = [{"atrybut": k, "wartosc": (etykiety.get(k) or {}).get(v, v), "ids": ids}
           for k, m in s.items() for v, ids in m.items() if len(ids) > 1]
    return sorted(out, key=lambda w: (w["atrybut"], w["wartosc"]))
