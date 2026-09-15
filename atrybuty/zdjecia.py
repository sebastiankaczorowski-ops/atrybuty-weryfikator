"""Zdjęcia produktu z etykietami — i dobór właściwego ujęcia do pytania.

Eksport z 15.09 ma kolumnę `zdjecia` w formacie
`Etykieta: URL | Etykieta: URL`, a etykiety realnie opisują ujęcie:
„Otwarty - front", „Rysunek techniczny", „Aranżacja".

To zmienia jakość warstwy wizyjnej. Wcześniej model dostawał jedno zdjęcie
główne — często aranżację, na której nie widać ani szuflad, ani wymiarów,
i słusznie odpowiadał „nie widać". Teraz do pytania o liczbę szuflad idzie
zdjęcie wnętrza, a do pytania o wymiary — rysunek techniczny, na którym
wymiary są po prostu napisane.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .tekst import norm

# Grupy ujęć. Kolejność w krotce to priorytet przy wyborze.
UJECIA: dict[str, tuple[str, ...]] = {
    # wnętrze — do liczenia szuflad, półek, drążków
    "wnetrze": ("otwarty - front", "wnetrze szafy - bez drzwi", "otwarty",
                "naroznik - prezentacja schowka", "przekroj", "schemat / przekroj mebla"),
    # rysunek techniczny — wymiary są na nim wypisane
    "rysunek": ("rysunek techniczny", "schemat/infografika", "schemat / przekroj mebla",
                "rysunek techniczny (szkic bez wymiarow)"),
    # front zamknięty — drzwi, fronty, nóżki, materiał
    "front": ("zamkniety - front", "zamkniety", "zamkniety - widok pod katem (front)",
              "widok z boku", "tylem"),
    # aranżacja jest najgorsza do weryfikacji, ale lepsza niż nic
    "aranzacja": ("aranzacja", "prezentacja zestawu", "szczegoly"),
}

# Który rodzaj ujęcia pasuje do którego pytania. Pierwszy trafiony wygrywa.
UJECIE_DLA_ATRYBUTU: dict[str, tuple[str, ...]] = {
    "Liczba szuflad": ("wnetrze", "front", "rysunek"),
    "Liczba półek": ("wnetrze", "rysunek", "front"),
    "Liczba drążków": ("wnetrze", "rysunek"),
    "Liczba szafek": ("front", "wnetrze", "rysunek"),
    "Liczba drzwi": ("front", "wnetrze"),
    "Rodzaj drzwi": ("front", "wnetrze"),
    "Rodzaj frontu": ("front",),
    "Podparcie": ("front", "rysunek"),
    "Na nóżkach": ("front", "rysunek"),
    "Materiał": ("front", "aranzacja"),
    "Dekoracje": ("front", "aranzacja"),
    "Styl": ("aranzacja", "front"),
    "Oświetlenie": ("wnetrze", "front"),
    "Kształt blatu": ("front", "rysunek", "aranzacja"),
    "Tapicerowane": ("front", "aranzacja"),
    "Zagłówek": ("front", "aranzacja"),
    "Podłokietniki": ("front", "aranzacja"),
    # wymiary da się odczytać wyłącznie z rysunku technicznego
    "Szerokość": ("rysunek",),
    "Wysokość": ("rysunek",),
    "Głębokość": ("rysunek",),
}


@dataclass
class Zdjecie:
    etykieta: str
    url: str

    @property
    def rodzaj(self) -> str:
        e = norm(self.etykieta)
        for rodzaj, wzorce in UJECIA.items():
            if any(w in e for w in wzorce):
                return rodzaj
        return "inne"


RE_URL = re.compile(r"https?://\S+")


def parsuj(surowe: str) -> list[Zdjecie]:
    """'Otwarty - front: http://… | Aranżacja: http://…' -> lista zdjęć.

    Etykieta bywa pusta albo sama w sobie jest URL-em (w danych trafia się
    pozycja zaczynająca się od „https"), więc rozdzielamy po URL-u, a nie po
    pierwszym dwukropku.
    """
    out: list[Zdjecie] = []
    for kawalek in (surowe or "").split("|"):
        kawalek = kawalek.strip()
        if not kawalek:
            continue
        m = RE_URL.search(kawalek)
        if not m:
            continue
        url = m.group(0).rstrip(" ,;")
        etykieta = kawalek[:m.start()].rstrip(": ").strip()
        out.append(Zdjecie(etykieta=etykieta, url=url))
    return out


def wybierz(zdjecia: list[Zdjecie], atrybut: str, zapasowe: str = "") -> Zdjecie | None:
    """Najlepsze ujęcie do pytania o ten atrybut.

    Gdy nie ma pasującego rodzaju, zwracamy pierwsze zdjęcie albo zapasowy
    URL (kolumna `zdjecie`) — lepiej zapytać o cokolwiek niż wcale.
    """
    if not zdjecia:
        return Zdjecie("", zapasowe) if zapasowe else None

    wg_rodzaju: dict[str, list[Zdjecie]] = {}
    for z in zdjecia:
        wg_rodzaju.setdefault(z.rodzaj, []).append(z)

    for rodzaj in UJECIE_DLA_ATRYBUTU.get(atrybut, ()):
        kandydaci = wg_rodzaju.get(rodzaj)
        if not kandydaci:
            continue
        wzorce = UJECIA[rodzaj]
        kandydaci.sort(key=lambda z: next(
            (i for i, w in enumerate(wzorce) if w in norm(z.etykieta)), len(wzorce)))
        return kandydaci[0]

    return zdjecia[0]


def ma_rysunek(zdjecia: list[Zdjecie]) -> bool:
    return any(z.rodzaj == "rysunek" for z in zdjecia)


def podsumowanie(zdjecia: list[Zdjecie]) -> dict[str, int]:
    out: dict[str, int] = {}
    for z in zdjecia:
        out[z.rodzaj] = out.get(z.rodzaj, 0) + 1
    return out
