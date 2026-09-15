"""Model danych: produkt, atrybut, finding.

Jeden wspólny kształt findingu dla wszystkich warstw detekcji (L1-L4) —
to on steruje routingiem do warstwy płatnej i kolejką weryfikacji.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Wagi — decydują o kolejności w kolejce weryfikacji.
KRYTYCZNA = "krytyczna"
SREDNIA = "srednia"
INFO = "info"

# Warstwy detekcji.
L1 = "L1"  # struktura i słowniki (deterministyczne)
L2 = "L2"  # statystyka i spójność (deterministyczne)
L3 = "L3"  # model wizyjny (płatne)
L4 = "L4"  # źródła zewnętrzne


@dataclass
class Produkt:
    id: str
    nazwa: str
    producent: str
    kolekcja: str
    zdjecie: str
    styl: str
    kategoria: str = "nieznana"
    atrybuty: dict[str, str] = field(default_factory=dict)      # po normalizacji
    atrybuty_surowe: dict[str, str] = field(default_factory=dict)
    liczby: dict[str, float] = field(default_factory=dict)      # atrybuty liczbowe
    zrodlo_kategorii: str = "nazwa"                             # nazwa | sklep
    podtyp: str = ""                               # podkategoria sklepu, do filtrowania
    kody: dict[str, str] = field(default_factory=dict)   # kod produktu/producenta/EAN
    zdjecia: list = field(default_factory=list)          # [(etykieta, url)]
    kompletnosc: str = "ok"                        # ok | bez_wymiarow | szczatkowy | pusty

    @property
    def ma_zdjecie(self) -> bool:
        return bool(self.zdjecie and self.zdjecie.strip())

    @property
    def do_zrodla(self) -> bool:
        """Czy produkt nadaje się tylko do ponownego zaciągnięcia ze źródła."""
        return self.kompletnosc in ("pusty", "szczatkowy")


@dataclass
class Finding:
    """Jedno zgłoszenie do weryfikacji.

    `pewnosc` (0-1) steruje bramką kosztową:
      >= PROG_AUTO  i jest `proponowana`  -> jedno kliknięcie w kolejce, zero kosztu
      <  PROG_AUTO  i atrybut widoczny     -> kandydat do L3 (Gemini)
      atrybut niewidoczny na zdjęciu       -> omija L3, czeka na L4 albo człowieka
    """
    produkt_id: str
    atrybut: str
    regula_id: str
    warstwa: str
    waga: str
    pewnosc: float
    stara_wartosc: str | None
    proponowana_wartosc: str | None
    dowod: str
    # klucz grupowania: identyczne przypadki rozstrzygane jedną decyzją
    grupa: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.grupa:
            self.grupa = f"{self.regula_id}|{self.atrybut}|{self.stara_wartosc}"


# Progi kompletności. Produkt, który nie ma danych, nie jest "produktem
# z błędami" — analizowanie go zaśmieca kolejkę fałszywymi brakami. Takie
# produkty odkładamy na listę do ponownego zaciągnięcia ze źródła.
MIN_ATRYBUTOW = 3          # poniżej: szczątkowy
WYMIARY_PODSTAWOWE = ("Szerokość", "Wysokość", "Głębokość")


def oszacuj_kompletnosc(atrybuty: dict[str, str]) -> str:
    """pusty / szczatkowy — wyłączone z analizy; bez_wymiarow — analizowane dalej.

    Rozróżnienie jest celowe. Produkt z siedmioma atrybutami, ale bez wymiarów,
    ma dość danych, żeby reguły miały co sprawdzać, a sam brak wymiaru JEST
    findingiem do poprawy. Produkt z zerem albo dwoma atrybutami nie daje się
    naprawić ręcznie — jego miejsce jest na liście do zaciągnięcia ze źródła.
    """
    if not atrybuty:
        return "pusty"
    if len(atrybuty) < MIN_ATRYBUTOW:
        return "szczatkowy"
    if not any(k in atrybuty for k in WYMIARY_PODSTAWOWE):
        return "bez_wymiarow"
    return "ok"


PROG_AUTO = 0.85          # powyżej: propozycja gotowa do jednego kliknięcia
PROG_DO_WIZJI = 0.85      # poniżej: kandydat do warstwy wizyjnej

# Atrybuty, które da się rozstrzygnąć ze zdjęcia. Reszta omija L3 —
# wagi ani klasy płyty nie widać, więc nie ma po co za to płacić.
#
# Wymiary doszły po eksporcie z 15.09: produkty mają rysunki techniczne,
# a na nich wymiary są po prostu napisane. Bez rysunku i tak wypadną,
# bo dobór ujęcia nie znajdzie dla nich nic sensownego.
WIDOCZNE_NA_ZDJECIU = {
    "Szerokość", "Wysokość", "Głębokość",
    "Liczba drzwi", "Liczba szuflad", "Liczba półek", "Liczba szafek",
    "Liczba drążków", "Materiał", "Oświetlenie", "Rodzaj drzwi",
    "Kształt blatu", "Podparcie", "Tapicerowane", "Zagłówek",
    "Na nóżkach", "Podłokietniki", "Styl", "Dekoracje", "Rodzaj frontu",
}
