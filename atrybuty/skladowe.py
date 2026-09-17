"""Warstwa L0 — porządek w źródle: atrybuty rozjechane między dwoma miejscami.

W sklepie ta sama cecha mebla może siedzieć w atrybutach produktu albo
w jego składowych, a front bierze ją stamtąd, gdzie znajdzie. Docelowo ma
być wyłącznie w atrybutach. Ta warstwa robi z tego dwie rzeczy:

  L0-ZE-SKLADOWYCH  atrybut jest tylko w składowych — propozycja przepisania
                    go w legitne miejsce
  L0-KONFLIKT       ten sam atrybut ma różne wartości w obu miejscach —
                    ktoś musi rozstrzygnąć, która jest prawdziwa

Przepisujemy to, co mieści się w słowniku ATRYBUTÓW sklepu i jest tam
włączone (ACTIVE) — a więc zarówno atrybuty słownikowe (wartość dostanie
ID przy eksporcie), jak i pola wolne: wymiary, wagę, udźwig. „Szerokość"
wartości słownikowych nie ma i mieć nie będzie, a jest normalnym polem
sklepu, więc odcinanie jej byłoby zwykłą dziurą.

Nie przepisujemy tego, czego panel nie zna („Liczba miejsc" przy sklepowym
„Ilość osób") ani tego, co ma wyłączone („Długość", „Do poprawy") — nie ma
dokąd tego wpisać.

Produkty z flagą `omit_components_in_attributes = 1` są pominięte: sklep
mówi, że u nich składowe są już odcięte od frontu, więc nie ma czego
przepisywać ani z czym porównywać.
"""
from __future__ import annotations

from . import panel_format
from .model import INFO, KRYTYCZNA, L0, SREDNIA, Finding, Produkt
from .tekst import do_liczby, norm

REGULA_PRZEPISZ = "L0-ZE-SKLADOWYCH"
REGULA_KONFLIKT = "L0-KONFLIKT"

# Różnica między wartościami bywa pozorna. Rozdzielamy je, bo „90,5 vs 90"
# i „Głębokość 102 vs 200" to dwa zupełnie różne problemy, a wrzucone do
# jednego worka utopią te drugie.
ROZBIEZNOSC_ZAOKRAGLENIA = 1.0


def _rodzaj_roznicy(a: str, b: str) -> tuple[str, str, float]:
    """(opis, waga, pewność) dla pary wartości."""
    la, lb = do_liczby(a), do_liczby(b)
    if la is not None and lb is not None:
        if la == lb:
            return "ta sama liczba, inny zapis", INFO, 0.95
        if abs(la - lb) <= ROZBIEZNOSC_ZAOKRAGLENIA:
            return "różnica zaokrąglenia", INFO, 0.6
        return "różne liczby", KRYTYCZNA, 0.5

    czlony_a = {norm(c) for c in a.split(",") if c.strip()}
    czlony_b = {norm(c) for c in b.split(",") if c.strip()}
    if czlony_a == czlony_b:
        return "ta sama lista, inna kolejność lub pisownia", INFO, 0.95
    if czlony_a > czlony_b:
        return "atrybuty mają więcej członów niż składowe", SREDNIA, 0.6
    if czlony_b > czlony_a:
        return "składowe mają więcej członów niż atrybuty", SREDNIA, 0.6
    return "różne wartości", KRYTYCZNA, 0.5


def _do_przepisania(atrybut: str, slownik: dict, statusy: dict) -> bool:
    """Czy wolno przepisać ten atrybut ze składowych do atrybutów produktu.

    Trzy przypadki i tylko pierwszy dwa razy przechodzą:
      atrybut słownikowy    — tak, wartość dostanie ID przy eksporcie
      atrybut wolny (liczba, tekst) — tak, jeśli panel go zna i ma włączony;
                              tu należą wymiary, waga, udźwig
      atrybut nieznany albo wyłączony w panelu — nie, nie ma gdzie tego wpisać
    """
    if statusy and statusy.get(atrybut, {}).get("status") != "ACTIVE":
        return False
    return bool(statusy) or atrybut in slownik


def znajdz(produkty: list[Produkt], slownik: dict | None = None,
           atrybuty_panelu: dict | None = None) -> list[Finding]:
    slownik = panel_format.wczytaj_slownik() if slownik is None else slownik
    # Atrybut, którego panel w ogóle nie zna, bywa w eksporcie pod inną nazwą
    # („Liczba miejsc" przy sklepowym „Ilość osób"). Konfliktu na takim polu
    # i tak nie da się wyeksportować, więc nie ma po co blokować nim kolejki.
    statusy = (panel_format.wczytaj_atrybuty_panelu() if atrybuty_panelu is None
               else atrybuty_panelu)
    znane_w_panelu = set(statusy)
    out: list[Finding] = []

    for p in produkty:
        if p.skladowe_odciete or not p.skladowe:
            continue

        for atrybut, wartosc in p.skladowe.items():
            w_atrybutach = p.atrybuty_surowe.get(atrybut)

            if w_atrybutach is None:
                # Brak w legitnym miejscu — przepisujemy, o ile panel zna ten
                # atrybut i ma go włączonego. Kryterium to słownik ATRYBUTÓW,
                # nie słownik wartości: „Szerokość" wartości słownikowych nie
                # ma i mieć nie będzie, a jest normalnym polem sklepu.
                if not _do_przepisania(atrybut, slownik, statusy):
                    continue
                out.append(Finding(
                    produkt_id=p.id, atrybut=atrybut, regula_id=REGULA_PRZEPISZ,
                    warstwa=L0, waga=SREDNIA, pewnosc=0.9,
                    stara_wartosc=None, proponowana_wartosc=wartosc,
                    dowod=f"W składowych: „{wartosc}”. W atrybutach produktu: brak.",
                    grupa=f"{REGULA_PRZEPISZ}|{atrybut}|{norm(wartosc)}"))
                continue

            if norm(w_atrybutach) == norm(wartosc):
                continue

            opis, waga, pewnosc = _rodzaj_roznicy(w_atrybutach, wartosc)
            if znane_w_panelu and atrybut not in znane_w_panelu:
                waga = INFO
                opis += "; panel nie zna tego atrybutu, więc poprawka nie wyjdzie eksportem"
            out.append(Finding(
                produkt_id=p.id, atrybut=atrybut, regula_id=REGULA_KONFLIKT,
                warstwa=L0, waga=waga, pewnosc=pewnosc,
                stara_wartosc=w_atrybutach, proponowana_wartosc=wartosc,
                dowod=(f"W atrybutach produktu: „{w_atrybutach}”. "
                       f"W składowych: „{wartosc}”. Rozbieżność: {opis}."),
                # grupujemy po parze wartości: te same dwie wartości to ta sama
                # decyzja, niezależnie od produktu
                grupa=f"{REGULA_KONFLIKT}|{atrybut}|{norm(w_atrybutach)}=>{norm(wartosc)}"))

    return out


def podsumowanie(produkty: list[Produkt], findingi: list[Finding]) -> dict:
    l0 = [f for f in findingi if f.warstwa == L0]
    return {
        "produktow_ze_skladowymi": sum(1 for p in produkty if p.skladowe),
        "juz_odcietych": sum(1 for p in produkty if p.skladowe_odciete),
        "do_przepisania": sum(1 for f in l0 if f.regula_id == REGULA_PRZEPISZ),
        "konfliktow": sum(1 for f in l0 if f.regula_id == REGULA_KONFLIKT),
        "konfliktow_krytycznych": sum(1 for f in l0
                                      if f.regula_id == REGULA_KONFLIKT
                                      and f.waga == KRYTYCZNA),
        "grup": len({f.grupa for f in l0}),
    }
