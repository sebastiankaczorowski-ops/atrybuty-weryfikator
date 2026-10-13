"""Luki w filtrach — propozycje dla pustych atrybutów, po których klient filtruje.

Diagnoza z 10.10.2026: „Na nóżkach” ma wartość u 19% łóżek na stronie, rodzaj
obicia u 9% łóżek tapicerowanych. Produkt bez wartości znika z wyników, gdy
klient zaznaczy filtr — niezależnie od tego, czy mebel ma nóżki.

Które atrybuty są filtrami w której kategorii — `config/filtry.yaml`
(zakładka /filtry). Skąd brać propozycje — `config/luki.yaml`, od najpewniejszego:

* **podkategoria** — „Komoda na nóżkach” sama mówi „Na nóżkach: tak”;
* **nazwa** — „LED” w nazwie to oświetlenie w zestawie;
* **rodzina** — reszta kolekcji albo wariantów tego samego modelu.

Brak, dla którego żadne źródło nic nie wie, też idzie do kolejki
(`L1-LUKA-BRAK`, bez propozycji) — pogrupowany po kategorii, atrybucie
i producencie, żeby rozstrzygać go grupą. Nic nie zmienia się samo.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict

from . import config, panel_format, wezly
from .model import INFO, KRYTYCZNA, L1, L2, L3, SREDNIA, Finding, Produkt
from .tekst import norm

log = logging.getLogger(__name__)

# Prawdopodobieństwo (pole `pewnosc`) z siły dowodu. Podkategoria przechodzi
# próg automatycznego zatwierdzania (PROG_AUTO 0,85), nazwa nie.
PEWNOSC_PODTYP = 0.92
PEWNOSC_PODTYP_SPRZECZNE = 0.88
PEWNOSC_NAZWA = 0.80
# Rodzina: (zgodnych + 1) / (z wartością + 2), z sufitem. Wyposażenie bywa
# różne nawet przy jednym kodzie producenta (wariant z LED i bez), więc jego
# sufit leży pod progiem automatu — zawsze ocena człowieka.
SUFIT_RODZINA = 0.95
SUFIT_WYPOSAZENIE = 0.80
# Brak bez propozycji jest pewny jako brak. 1,0 trzyma go też z dala od
# bramki do Gemini (pewność < 0,85 + atrybut widoczny = kandydat płatny) —
# tysiące takich braków nie mogą po cichu trafić do płatnej warstwy.
PEWNOSC_BRAK = 1.0

REGULY_PROPOZYCJI = ("L2-LUKA-PODTYP", "L2-LUKA-PODTYP-SPRZECZNE",
                     "L2-LUKA-NAZWA", "L2-LUKA-RODZINA", "L2-LUKA-ZDJECIE")
# Odczyt ze zdjęcia (Gemini) — najwyżej tyle, czyli zawsze pod progiem automatu:
# model bywa pewny siebie także wtedy, gdy nóżki zasłania narzuta.
SUFIT_ZDJECIE = 0.80
REGULA_BRAKU = "L1-LUKA-BRAK"
REGULY = REGULY_PROPOZYCJI + (REGULA_BRAKU,)

KLUCZ_KODU_PRODUCENTA = "kod producenta"


# --- które filtry obowiązują produkt -----------------------------------------

def konfiguracja_aktywna() -> bool:
    return wezly.aktywne() or bool(config.filtry())


def filtry_produktu(p: Produkt) -> set[str]:
    """Filtry z węzła drzewa panelu (wezly.py), gdy konfiguracja węzłów jest
    wczytana — wtedy to jedyne źródło prawdy. Inaczej stara konfiguracja według
    naszych typów (config/filtry.yaml). Produkt bez węzła: żadnych luk —
    nie wiadomo, które filtry go dotyczą."""
    if wezly.aktywne():
        return set(wezly.filtry_wezla(p.wezel))
    return set(config.filtry().get(p.kategoria, ()))


def zakres_braku(p: Produkt) -> str:
    """Część klucza grupy braków: węzeł drzewa (gdy jest) albo nasza kategoria."""
    if wezly.aktywne() and p.wezel is not None:
        return f"w{p.wezel}"
    return p.kategoria


# --- wartości --------------------------------------------------------------

def wartosci_efektywne(p: Produkt) -> dict[str, str]:
    """To, co widzi front: atrybut produktu, a gdy go nie ma — nieodcięte składowe.

    Komórka z wartością tylko w składowych nie jest luką w filtrze; przeniesienie
    jej do atrybutów obsługuje L0 (recenzja LUKI-01).
    """
    # Pusty napis („Na nóżkach: ”) to brak, nie wartość — inaczej produkt
    # liczyłby się jako pokryty i znikałby z listy braków (inspekcja R04).
    atrybuty = {k: v for k, v in p.atrybuty.items() if v and str(v).strip()}
    if p.skladowe_odciete or not p.skladowe:
        return atrybuty
    skladowe = {k: v for k, v in p.skladowe.items() if v and str(v).strip()}
    return {**skladowe, **atrybuty}


def kanoniczna(atrybut: str, wartosc: str, etykiety: dict) -> str | None:
    """Wartość w zapisie panelu („ekoskóra”), albo None, gdy spoza słownika.

    Bez słownika nie proponujemy nic: zaakceptowana propozycja spoza słownika
    i tak odpadłaby przy imporcie do panelu (inspekcja R01). Luka zostaje
    wtedy jako brak bez propozycji.
    """
    slownik = (etykiety or {}).get(atrybut)
    if not slownik:
        return None
    return slownik.get(norm(wartosc))


def kod_producenta(p: Produkt) -> str:
    for k, v in p.kody.items():
        if norm(k) == KLUCZ_KODU_PRODUCENTA and v:
            return norm(v)
    return ""


def prawdopodobienstwo_rodziny(zgodnych: int, z_wartoscia: int, wyposazenie: bool) -> float:
    """3/3 → 0,80; 12/12 → 0,93; 9/10 → 0,83 — więcej zgodnych dawców, większa pewność."""
    sufit = SUFIT_WYPOSAZENIE if wyposazenie else SUFIT_RODZINA
    return round(min(sufit, (zgodnych + 1) / (z_wartoscia + 2)), 3)


# --- źródła propozycji -----------------------------------------------------

def z_podtypu(p: Produkt, wartosci: dict[str, str], filtry: set[str],
              etykiety: dict) -> list[Finding]:
    f: list[Finding] = []
    for r in config.luki().get("podtyp") or []:
        if not p.podtyp or norm(p.podtyp) != norm(r["podtyp"]):
            continue
        atr = r["atrybut"]
        # Filtr zdjęty w /filtry nie produkuje niczego — żadne źródło nie
        # obchodzi konfiguracji (inspekcja R02).
        if atr not in filtry:
            continue
        wartosc = kanoniczna(atr, r["wartosc"], etykiety)
        if wartosc is None:
            log.warning("luki.yaml: wartość %r spoza słownika %r — reguła pominięta",
                        r["wartosc"], atr)
            continue
        obecna = wartosci.get(atr)
        dopuszczalne = {norm(wartosc)} | {norm(x) for x in r.get("dopuszczalne") or []}
        if obecna is None:
            f.append(Finding(
                p.id, atr, "L2-LUKA-PODTYP", L2, SREDNIA, PEWNOSC_PODTYP, None, wartosc,
                f"Produkt jest w podkategorii „{p.podtyp}”, a „{atr}” jest puste",
                grupa=f"L2-LUKA-PODTYP|{p.podtyp}|{atr}"))
        elif norm(obecna) not in dopuszczalne:
            f.append(Finding(
                p.id, atr, "L2-LUKA-PODTYP-SPRZECZNE", L2, KRYTYCZNA, PEWNOSC_PODTYP_SPRZECZNE,
                obecna, wartosc,
                f"Podkategoria „{p.podtyp}” mówi „{wartosc}”, atrybut mówi „{obecna}”",
                grupa=f"L2-LUKA-PODTYP-SPRZECZNE|{p.podtyp}|{atr}|{obecna}"))
    return f


def z_nazwy(p: Produkt, wartosci: dict[str, str], filtry: set[str],
            etykiety: dict) -> list[Finding]:
    f: list[Finding] = []
    nazwa = norm(p.nazwa)
    zajete: set[str] = set()
    for r in config.luki().get("nazwa") or []:
        atr = r["atrybut"]
        if atr in zajete or atr in wartosci:
            continue
        kategorie = r.get("kategorie")
        # Lista kategorii reguły to dodatkowe zawężenie, nie obejście
        # konfiguracji filtrów (inspekcja R02).
        if atr not in filtry or (kategorie and p.kategoria not in kategorie):
            continue
        if not re.search(r["wzorzec"], nazwa):
            continue
        # „bez LED”, „LED opcjonalnie” — słowo jest, ale mówi odwrotnie (R18)
        if r.get("wyklucz") and re.search(r["wyklucz"], nazwa):
            continue
        wartosc = kanoniczna(atr, r["wartosc"], etykiety)
        if wartosc is None:
            log.warning("luki.yaml: wartość %r spoza słownika %r — reguła pominięta",
                        r["wartosc"], atr)
            continue
        zajete.add(atr)   # pierwsza pasująca wygrywa: „welur boucle” to nie dwa obicia
        f.append(Finding(
            p.id, atr, "L2-LUKA-NAZWA", L2, SREDNIA, PEWNOSC_NAZWA, None, wartosc,
            f"Nazwa „{p.nazwa}” wskazuje „{wartosc}”, atrybut „{atr}” pusty",
            grupa=f"L2-LUKA-NAZWA|{atr}|{wartosc}"))
    return f


def _klucz_rodziny(p: Produkt, rodzaj: str) -> tuple | None:
    """Kto jest „tą samą rodziną” — konserwatywnie (recenzja LUKI-02, LUKI-06).

    `model` tylko po kodzie producenta: `baza_nazwy` łączyła szafę 100 z 200,
    a same wymiary nie odróżniają łóżka z materacem od łóżka bez.
    """
    if rodzaj == "model":
        kod = kod_producenta(p)
        return (p.producent, p.kategoria, "model", kod) if kod else None
    if not p.kolekcja:
        return None
    return (p.producent, p.kategoria, "kolekcja", norm(p.kolekcja))


def z_rodziny(produkty: list[Produkt], wartosci: dict[str, dict[str, str]],
              etykiety: dict) -> list[Finding]:
    """Pusty członek rodziny dostaje wartość, na którą zgadza się reszta.

    Wymagamy `min_z_wartoscia` członków z wartością i zgodności `prog_zgodnosci`
    — przy rozbieżnej rodzinie nie zgadujemy. `grupa` niesie identyfikator
    rodziny, więc „Zastosuj ×N” dotyczy wariantów jednego mebla (LUKI-08).
    """
    u = config.luki().get("rodzina") or {}
    minimum = int(u.get("min_z_wartoscia", 3))
    prog = float(u.get("prog_zgodnosci", 0.9))
    wyposazenie = set(u.get("wyposazenie") or [])
    f: list[Finding] = []

    for atr, rodzaj in (u.get("atrybuty") or {}).items():
        rodziny: dict[tuple, list[Produkt]] = defaultdict(list)
        for p in produkty:
            if atr not in filtry_produktu(p):
                continue
            klucz = _klucz_rodziny(p, rodzaj)
            if klucz:
                rodziny[klucz].append(p)

        for klucz, czlonkowie in rodziny.items():
            puste = [p for p in czlonkowie if atr not in wartosci[p.id]]
            z_wart = [wartosci[p.id][atr] for p in czlonkowie if atr in wartosci[p.id]]
            if not puste or len(z_wart) < minimum:
                continue
            dominujaca, ile = Counter(z_wart).most_common(1)[0]
            if ile / len(z_wart) < prog:
                continue
            # Dawcy mogą mieć wartość, której panel już nie zna (stary słownik,
            # składowe) — taka propozycja odpadłaby przy imporcie (R01).
            dominujaca = kanoniczna(atr, dominujaca, etykiety)
            if dominujaca is None:
                continue
            pewnosc = prawdopodobienstwo_rodziny(ile, len(z_wart), atr in wyposazenie)
            producent, kat, _rodzaj, ident = klucz
            opis = (f"model „{czlonkowie[0].kody.get('kod producenta') or ident}”"
                    if rodzaj == "model" else f"kolekcja „{czlonkowie[0].kolekcja}”")
            for p in puste:
                f.append(Finding(
                    p.id, atr, "L2-LUKA-RODZINA", L2, SREDNIA, pewnosc, None, dominujaca,
                    f"{opis} ({producent}): {ile} z {len(z_wart)} produktów "
                    f"z wartością ma „{dominujaca}”, ten jest pusty",
                    # pełna tożsamość rodziny — ta sama kolekcja w komodach
                    # i szafkach nocnych to dwie rodziny (inspekcja R10)
                    grupa=f"L2-LUKA-RODZINA|{atr}|{dominujaca}|{producent}|{kat}|{rodzaj}|{ident}"))
    return f


def propozycja_ze_zdjecia(produkt_id: str, atrybut: str, kategoria: str, producent: str,
                          odczyt: dict, etykiety: dict) -> Finding | None:
    """Odczyt Gemini dla pustego pola → propozycja, o ile wartość jest w słowniku."""
    wartosc = kanoniczna(atrybut, odczyt.get("wartosc") or "", etykiety)
    if wartosc is None:
        return None
    pewnosc = round(min(SUFIT_ZDJECIE, float(odczyt.get("pewnosc") or 0)), 3)
    return Finding(
        produkt_id, atrybut, "L2-LUKA-ZDJECIE", L3, SREDNIA, pewnosc, None, wartosc,
        f"Odczyt ze zdjęcia: „{odczyt.get('uzasadnienie') or wartosc}”",
        grupa=f"L2-LUKA-ZDJECIE|{kategoria}|{atrybut}|{wartosc}|{producent}")


def ze_zdjec(p: Produkt, wartosci: dict[str, str], filtry: set[str],
             odczyty: dict, etykiety: dict) -> list[Finding]:
    f: list[Finding] = []
    for atr in filtry:
        if atr in wartosci or (p.id, atr) not in odczyty:
            continue
        prop = propozycja_ze_zdjecia(p.id, atr, p.kategoria, p.producent,
                                     odczyty[(p.id, atr)], etykiety)
        if prop:
            f.append(prop)
    return f


# --- całość ----------------------------------------------------------------

def uruchom(produkty: list[Produkt], wylaczone: set[str] | None = None,
            odczyty_zdjec: dict | None = None) -> list[Finding]:
    """Propozycje dla luk + braki bez propozycji, najwyżej jedno na komórkę.

    Gdy kilka źródeł coś mówi o tym samym (produkt, atrybut), wygrywa najwyższe
    prawdopodobieństwo — dwie propozycje dla jednej komórki to dwa kliknięcia
    i ten sam klucz decyzji.
    """
    if not konfiguracja_aktywna():
        return []
    # Świeżo, raz na przebieg: słownik mógł się zmienić między importami
    # w tym samym procesie (recenzja LUKI-04).
    etykiety = panel_format.wczytaj_etykiety()
    wartosci = {p.id: wartosci_efektywne(p) for p in produkty}

    kandydaci: list[Finding] = []
    for p in produkty:
        filtry_p = filtry_produktu(p)
        kandydaci += z_podtypu(p, wartosci[p.id], filtry_p, etykiety)
        kandydaci += z_nazwy(p, wartosci[p.id], filtry_p, etykiety)
        if odczyty_zdjec:
            kandydaci += ze_zdjec(p, wartosci[p.id], filtry_p, odczyty_zdjec, etykiety)
    kandydaci += z_rodziny(produkty, wartosci, etykiety)
    # Źródło wyłączone w /reguly nie wygrywa komórki — wtedy wchodzi następne
    # źródło albo brak bez propozycji (inspekcja R09).
    wylaczone = wylaczone or set()
    kandydaci = [f for f in kandydaci if f.regula_id not in wylaczone]

    najlepsze: dict[tuple[str, str], Finding] = {}
    for f in kandydaci:
        k = (f.produkt_id, f.atrybut)
        if k not in najlepsze or f.pewnosc > najlepsze[k].pewnosc:
            najlepsze[k] = f

    if REGULA_BRAKU in wylaczone:
        return list(najlepsze.values())
    opcjonalne = set(config.luki().get("cechy_opcjonalne") or [])
    for p in produkty:
        for atr in sorted(filtry_produktu(p) - opcjonalne):
            if atr in wartosci[p.id] or (p.id, atr) in najlepsze:
                continue
            najlepsze[(p.id, atr)] = Finding(
                p.id, atr, REGULA_BRAKU, L1, INFO, PEWNOSC_BRAK, None, None,
                f"„{atr}” to filtr w kategorii, wartości brak, a żadne źródło jej nie zna "
                f"— produkt znika z wyników po zaznaczeniu filtra",
                grupa=f"{REGULA_BRAKU}|{zakres_braku(p)}|{atr}|{p.producent}")
    return list(najlepsze.values())


def _pusta(stara: str | None) -> bool:
    """Ta sama „pustość” co w kluczu decyzji (`db.hasz`: None i '' to jedno) —
    inaczej „Oświetlenie: ” z eksportu i luka dla tej samej komórki
    przechodziły obok siebie z jednym kluczem (inspekcja R16)."""
    return stara is None or not str(stara).strip()


# Gdy dwa źródła proponują różne wartości dla tej samej pustej komórki,
# zostaje jedna propozycja, ale z pewnością poniżej progu automatu —
# rozstrzyga człowiek, widząc obie wersje w dowodzie (inspekcja R03).
PEWNOSC_SPOR = 0.60


def uzgodnij(istniejace: list[Finding], luki_: list[Finding]) -> list[Finding]:
    """Jedno zgłoszenie na pusty (produkt, atrybut) między lukami a resztą detektorów.

    Inne detektory też proponują wartości dla pustych pól (np. L2-NAZWA-UZUPELNIA
    z „Szafa 3-drzwiowa”). Wszystkie zgłoszenia z pustą starą wartością mają ten
    sam klucz decyzji, więc odłożenie braku ukryłoby konkretną propozycję:
    * brak bez propozycji ustępuje każdej propozycji;
    * zgodne wartości — zostaje pewniejsze zgłoszenie;
    * sprzeczne — zostaje pewniejsze, z pewnością PEWNOSC_SPOR i drugą wersją
      w dowodzie.
    Zwraca (istniejące po uzgodnieniu) + (luki po uzgodnieniu).
    """
    # Także zgłoszenia bez propozycji: brak wartości z L2-NAZWA-UZUPELNIA bez
    # słownikowego odpowiednika ma ten sam klucz decyzji co luka.
    puste = {}
    for i, f in enumerate(istniejace):
        if _pusta(f.stara_wartosc):
            puste.setdefault((f.produkt_id, f.atrybut), []).append(i)
    usun_ist: set[int] = set()
    wynik_luk: list[Finding] = []
    for f in luki_:
        if not _pusta(f.stara_wartosc):
            wynik_luk.append(f)
            continue
        indeksy = puste.get((f.produkt_id, f.atrybut))
        if not indeksy:
            wynik_luk.append(f)
            continue
        z_propozycja = [i for i in indeksy if istniejace[i].proponowana_wartosc is not None]
        if f.proponowana_wartosc is None:
            if z_propozycja:
                continue              # brak ustępuje konkretnej propozycji
            # Obie strony bez propozycji: zostaje brak luki — jego grupa, link
            # z /filtry i ochrona przed „do importu” — z tamtym dowodem (REVIEW-01).
            f.dowod += " · Także: " + "; ".join(istniejace[i].dowod for i in indeksy)
            usun_ist.update(indeksy)
            wynik_luk.append(f)
            continue
        if not z_propozycja:
            # inne zgłoszenie tylko sygnalizuje brak — luka niesie wartość, więc
            # zostaje ona, z tamtym dowodem dopisanym dla kontekstu
            f.dowod += " · Także: " + "; ".join(istniejace[i].dowod for i in indeksy)
            usun_ist.update(indeksy)
            wynik_luk.append(f)
            continue
        inne = istniejace[z_propozycja[0]]
        lepsze, gorsze = (f, inne) if f.pewnosc > inne.pewnosc else (inne, f)
        if norm(lepsze.proponowana_wartosc) != norm(gorsze.proponowana_wartosc):
            lepsze.pewnosc = min(lepsze.pewnosc, PEWNOSC_SPOR)
            lepsze.dowod += (f" · Uwaga: {gorsze.regula_id} proponuje "
                             f"„{gorsze.proponowana_wartosc}” — źródła się nie zgadzają")
            # sporna komórka nie może jechać na „Zastosuj ×N” razem z niespornymi
            # wariantami tej samej rodziny (inspekcja R17)
            lepsze.grupa += f"|SPOR|{gorsze.regula_id}|{gorsze.proponowana_wartosc}"
        if lepsze is f:
            usun_ist.update(indeksy)
            wynik_luk.append(f)
        # w przeciwnym razie zostaje istniejące (już na liście), luka odpada
    return [f for i, f in enumerate(istniejace) if i not in usun_ist] + wynik_luk


# --- ziarno konfiguracji z diagnozy strony ---------------------------------

# Kategorie strony, które w mapie kategorii sklepu mają inną nazwę.
ALIASY_KATEGORII_STRONY = {"Stelaże do łóżek": "Stelaże", "Szafki nocne": "Szafki Nocne"}
# Filtry, przy których brak wartości bywa prawdą (mebel tego nie ma) —
# z diagnozy „cecha opcjonalna”. Nie robimy z nich luk.
RODZAJE_LUK = {"pewna", "obicie"}


def ziarno_z_diagnozy(wiersze: list[dict], mapa: dict[str, str]) -> tuple[dict, list[str]]:
    """{nasza kategoria: [filtry]} z pomiarów strony + lista niedopasowanych kategorii."""
    mapa_norm = {norm(k): v for k, v in mapa.items()}
    out: dict[str, set[str]] = defaultdict(set)
    nieznane: set[str] = set()
    for w in wiersze:
        if w.get("poziom") not in ("grupa", "kategoria") or w.get("rodzaj") not in RODZAJE_LUK:
            continue
        nazwa = ALIASY_KATEGORII_STRONY.get(w["kategoria"], w["kategoria"])
        nasza = mapa_norm.get(norm(nazwa))
        if not nasza:
            if w.get("poziom") == "kategoria":
                nieznane.add(w["kategoria"])
            continue
        out[nasza].add(w["filtr"])
    return {k: sorted(v) for k, v in sorted(out.items())}, sorted(nieznane)
