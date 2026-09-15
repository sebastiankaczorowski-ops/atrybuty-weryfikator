"""Narzędzia tekstowe: normalizacja napisów i ekstrakcja faktów z nazwy produktu.

Nazwa produktu jest w tym projekcie *niezależnym źródłem prawdy* — darmowym
drugim świadkiem. Gdy nazwa i atrybut się nie zgadzają, mamy finding o wysokiej
pewności, bo nie zgadzają się dwa niezależne źródła.
"""
from __future__ import annotations

import re
import unicodedata

OGONKI = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ", "acelnoszzACELNOSZZ")


def bez_ogonkow(s: str) -> str:
    return s.translate(OGONKI)


def norm(s: str) -> str:
    """Do porównań: małe litery, bez ogonków, pojedyncze spacje."""
    s = unicodedata.normalize("NFKC", s or "")
    s = bez_ogonkow(s).lower()
    s = re.sub(r"[^\w\s./x-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def do_liczby(s: str | None) -> float | None:
    """'46,5' -> 46.5 ; '46, 46' -> None (błąd formatu, nie zgadujemy) ; '120 cm' -> 120.0"""
    if s is None:
        return None
    t = str(s).strip().replace(" ", " ")
    t = re.sub(r"\s*(cm|mm|m|kg|g)\s*$", "", t, flags=re.I)
    t = t.strip()
    if not t:
        return None
    # "46, 46" albo "46,46,46" — zdublowana wartość, to nie jest liczba
    if t.count(",") + t.count(".") > 1:
        return None
    t = t.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", t):
        return None
    return float(t)


# --- ekstraktory z nazwy -------------------------------------------------

RE_WYMIARY = re.compile(r"(?<![\d.,])(\d{2,3})\s*[x×]\s*(\d{2,3})(?:\s*[x×]\s*(\d{2,3}))?(?![\d.,])")
RE_SREDNICA = re.compile(r"(?:sr\.?|śr\.?|fi|Ø)\s*(\d{2,3})", re.I)
# kody konfiguracji BRW i pochodne: 2d1w1s, 3d2s, 1d1sz
RE_KOD_BRW = re.compile(r"\b(\d)?d(\d)?(?:w(\d)?)?(?:s(\d)?)?\b", re.I)
RE_KOD_SZAFKI = re.compile(r"\b([DGSW])(\d{2,3})([A-Z]{0,2})\b")  # D60P, G80, S45

# Mebel nie ma stu szuflad. Wyższa liczba w nazwie to numer modelu
# ("Materac Space 1000S 90"), nie liczebnik — bez tego limitu reguła
# porównująca nazwę z atrybutem produkuje fałszywe alarmy.
MAKS_LICZEBNIK = 20

LICZEBNIKI_SLOWNE = {
    "jedno": 1, "dwu": 2, "trzy": 3, "cztero": 4, "piecio": 5, "szescio": 6,
}


def wymiary_z_nazwy(nazwa: str) -> dict[str, float]:
    """Wyciąga pary/trójki wymiarów z nazwy: 'Łóżko 140x200' -> {a:140, b:200}.

    Świadomie NIE przypisujemy ich do konkretnych atrybutów — dla łóżka
    '140x200' to powierzchnia spania, a nie wymiar zewnętrzny. Przypisaniem
    zajmuje się detektor, który zna kategorię.
    """
    out: dict[str, float] = {}
    m = RE_WYMIARY.search(nazwa or "")
    if m:
        out["a"] = float(m.group(1))
        out["b"] = float(m.group(2))
        if m.group(3):
            out["c"] = float(m.group(3))
    s = RE_SREDNICA.search(nazwa or "")
    if s:
        out["srednica"] = float(s.group(1))
    return out


def liczebniki_z_nazwy(nazwa: str) -> dict[str, int]:
    """'Szafa 3-drzwiowa z 2 szufladami' -> {'drzwi': 3, 'szuflady': 2}"""
    n = norm(nazwa)
    out: dict[str, int] = {}

    for cecha, slowo in (("drzwi", "drzwiow"), ("szuflady", "szuflad"),
                         ("polki", "polk"), ("drazki", "drazk")):
        m = re.search(rf"(\d+)\s*-?\s*{slowo}", n)
        if m and int(m.group(1)) <= MAKS_LICZEBNIK:
            out[cecha] = int(m.group(1))
            continue
        for przedrostek, wartosc in LICZEBNIKI_SLOWNE.items():
            if re.search(rf"{przedrostek}{slowo}", n):
                out[cecha] = wartosc
                break

    # forma opisowa bez liczby: "z szufladą", "z drzwiami"
    # UWAGA na liczbe gramatyczna: "z szuflada" znaczy jedna, ale
    # "z szufladami" znaczy tylko "ma szuflady" — ile, nie wiadomo.
    # Wyciaganie z tego jedynki dawalo 251 falszywych alarmow.
    if "szuflady" not in out and re.search(r"\bz szuflad(a|ka|ami)?\b", n):
        if re.search(r"\bz szuflad(a|ka)\b", n):
            out["szuflady"] = 1
        else:
            out["ma_szuflady"] = 1      # sa, ale liczby nie znamy
    if "drzwi" not in out and re.search(r"\bbez drzwi\b", n):
        out["drzwi"] = 0
    if "szuflady" not in out and re.search(r"\bbez szuflad\b", n):
        out["szuflady"] = 0

    # kod BRW: 2d1w1s = 2 drzwi, 1 witryna, 1 szuflada
    for token in n.split():
        if re.fullmatch(r"(\d+d)?(\d+w)?(\d+s)?", token) and any(c.isdigit() for c in token):
            for liczba, litera in re.findall(r"(\d+)([dws])", token):
                if int(liczba) > MAKS_LICZEBNIK:
                    continue
                if litera == "d":
                    out.setdefault("drzwi", int(liczba))
                elif litera == "s":
                    out.setdefault("szuflady", int(liczba))
    return out


def baza_nazwy(nazwa: str) -> str:
    """Nazwa bez wymiarów, kodów i wariantów — do grupowania rodzin produktów.

    'Komoda Avola 120x80 biała' i 'Komoda Avola 120x80 dąb' -> 'komoda avola'
    """
    n = norm(nazwa)
    n = RE_WYMIARY.sub(" ", n)
    n = re.sub(r"\b\d+\s*(cm|mm|kg)\b", " ", n)
    n = re.sub(r"\b\d{2,}\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()
