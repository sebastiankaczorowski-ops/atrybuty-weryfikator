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
    # „wnetrze” ogólnie: w danych są też „Wnętrze szafy – otwarte obie sekcje”,
    # „– rozsunięte lewe drzwi”, „- z ubraniami” (półpauza, różne końcówki).
    "wnetrze": ("otwarty - front", "wnetrze szafy - bez drzwi", "otwarty", "wnetrze",
                "prezentacja schowka", "przekroj", "schemat / przekroj mebla"),
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
    "Liczba półek": ("wnetrze",),
    "Liczba drążków": ("wnetrze",),
    "Liczba szafek": ("front", "wnetrze", "rysunek"),
    "Liczba drzwi": ("front", "wnetrze"),
    "Rodzaj drzwi": ("front", "wnetrze"),
    "Rodzaj frontu": ("front",),
    "Podparcie": ("front", "rysunek"),
    "Na nóżkach": ("front", "rysunek"),
    # schowek widać na zdjęciu otwartym („Narożnik - prezentacja schowka”,
    # podniesiony stelaż łóżka); zamknięty front zwykle nic nie mówi
    "Z pojemnikiem": ("wnetrze",),
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


# Półki i drążki widać wyłącznie we wnętrzu. Z frontu albo aranżacji model
# zgadywał; bez zdjęcia wnętrza nie pytamy wcale — i nie płacimy.
# „Z pojemnikiem” tak samo: z zamkniętego frontu schowka nie widać — próbka 30
# (15.10.2026) dała 29× „nie widać” za pieniądze. Pytamy tylko przy zdjęciu
# otwartego mebla albo „prezentacji schowka”.
TYLKO_WNETRZE = {"Liczba półek", "Liczba drążków", "Z pojemnikiem"}


def wybierz(zdjecia: list[Zdjecie], atrybut: str, zapasowe: str = "") -> Zdjecie | None:
    """Najlepsze ujęcie do pytania o ten atrybut.

    Gdy nie ma pasującego rodzaju, zwracamy pierwsze zdjęcie albo zapasowy
    URL (kolumna `zdjecie`) — lepiej zapytać o cokolwiek niż wcale.
    Wyjątek: atrybuty z TYLKO_WNETRZE — bez zdjęcia wnętrza nic (None).
    """
    tylko_wnetrze = atrybut in TYLKO_WNETRZE
    if not zdjecia:
        return None if tylko_wnetrze else (Zdjecie("", zapasowe) if zapasowe else None)

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

    return None if tylko_wnetrze else zdjecia[0]


# Dodatkowe ujęcia dołączane do pytania (Ewa, 14.10.2026): przy zestawach
# Gemini widział tylko element ze zdjęcia „Otwarty…” i zaniżał liczbę półek
# (590115, meblościanka RISE, garderoby przedpokojowe). Rysunek techniczny
# pokazuje wszystkie elementy, prezentacja zestawu — półki wiszące.
DODATKOWE_UJECIA: dict[str, tuple[str, ...]] = {
    "Liczba półek": ("rysunek techniczny", "technical drawing", "prezentacja zestawu"),
}
MAKS_DODATKOWYCH = 2


def dodatkowe(zdjecia: list[Zdjecie], atrybut: str, glowne_url: str) -> list[Zdjecie]:
    """Po jednym zdjęciu każdego wzorca z DODATKOWE_UJECIA, bez głównego i bez powtórek."""
    out: list[Zdjecie] = []
    uzyte = {glowne_url}
    for wzorzec in DODATKOWE_UJECIA.get(atrybut, ()):
        z = next((z for z in zdjecia if wzorzec in norm(z.etykieta) and z.url not in uzyte), None)
        if z and len(out) < MAKS_DODATKOWYCH:
            out.append(z)
            uzyte.add(z.url)
    return out


def ma_wnetrze(zdjecia: list[Zdjecie]) -> bool:
    return any(z.rodzaj == "wnetrze" for z in zdjecia)


def ma_rysunek(zdjecia: list[Zdjecie]) -> bool:
    return any(z.rodzaj == "rysunek" for z in zdjecia)


def podsumowanie(zdjecia: list[Zdjecie]) -> dict[str, int]:
    out: dict[str, int] = {}
    for z in zdjecia:
        out[z.rodzaj] = out.get(z.rodzaj, 0) + 1
    return out
