"""Warstwa L3 — weryfikacja atrybutu po zdjęciu produktu (Gemini).

Trzy zasady, które trzymają koszt i jakość w ryzach:

1. **Jedno zamknięte pytanie na wywołanie.** Nigdy "opisz produkt". Model ma
   policzyć szuflady albo powiedzieć, że ich nie widać — nic więcej.
2. **Wymuszony schemat odpowiedzi.** `response_schema` zamiast parsowania
   prozy, plus obowiązkowa opcja `nie_widac`: model, który nie może czegoś
   stwierdzić, ma to powiedzieć wprost, a nie zgadywać.
3. **Cache po haszu (zdjęcie + pytanie + model).** Kolejne wgranie eksportu
   nie płaci drugi raz za niezmieniony produkt.

Klucz API bierzemy ze zmiennej GEMINI_API_KEY (albo z pliku wskazanego przez
GEMINI_API_KEY_FILE). Klucz NIE trafia do repo ani do bazy.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import config, zdjecia as zdjecia_mod
from .model import WIDOCZNE_NA_ZDJECIU
from .tekst import do_liczby

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Flash do wolumenu, Pro tylko do spornych — zgodnie z zasadą "płatne
# rozwiązania tylko dla przypadków spornych".
MODEL_WOLUMEN = "gemini-flash-latest"
MODEL_SPORNE = "gemini-pro-latest"

# Zdjęcie skalujemy przed wysłaniem. Do policzenia szuflad 512 px w zupełności
# wystarcza, a obraz do 384 px to jeden kafelek (258 tokenów) zamiast czterech.
MAKS_BOK = 512

WERDYKTY = ("zgodne", "niezgodne", "nie_widac")

SCHEMAT_ODPOWIEDZI = {
    "type": "object",
    "properties": {
        "werdykt": {"type": "string", "enum": list(WERDYKTY)},
        "wartosc_ze_zdjecia": {"type": "string"},
        "pewnosc": {"type": "number"},
        "uzasadnienie": {"type": "string"},
    },
    "required": ["werdykt", "wartosc_ze_zdjecia", "pewnosc", "uzasadnienie"],
}

INSTRUKCJA = (
    "Jesteś kontrolerem jakości danych produktowych w sklepie meblowym. "
    "Dostajesz zdjęcie produktu i JEDNO pytanie o konkretną cechę. "
    "Odpowiadasz wyłącznie na podstawie tego, co widać na zdjęciu.\n\n"
    "Zasady:\n"
    "- Jeśli cechy nie da się jednoznacznie stwierdzić ze zdjęcia (zasłonięta, "
    "ujęcie z innej strony, zdjęcie aranżacyjne albo detal) — werdykt "
    "'nie_widac'. To pełnoprawna odpowiedź, nie porażka.\n"
    "- 'zgodne' tylko wtedy, gdy to, co widzisz, potwierdza wartość z bazy.\n"
    "- 'niezgodne' tylko wtedy, gdy widzisz co innego — wtedy w polu "
    "'wartosc_ze_zdjecia' podaj wartość ze zdjęcia, wybraną z listy dozwolonych.\n"
    "- 'pewnosc' to liczba 0-1: jak pewny jesteś tego werdyktu.\n"
    "- 'uzasadnienie' to jedno krótkie zdanie po polsku, mówiące CO widać "
    "(np. 'widoczne trzy fronty szuflad jeden nad drugim')."
)

# Pytania zamknięte per atrybut. Klucz musi być w WIDOCZNE_NA_ZDJECIU,
# inaczej finding i tak nie przejdzie bramki kosztowej.
PYTANIA: dict[str, str] = {
    "Liczba szuflad": "Ile szuflad ma ten mebel? Licz tylko fronty szuflad widoczne na zdjęciu.",
    "Liczba drzwi": "Ile drzwi (frontów otwieranych lub przesuwnych) ma ten mebel?",
    "Liczba półek": "Ile półek widać w tym meblu?",
    "Liczba szafek": "Ile zamykanych sekcji (szafek) ma ten mebel?",
    "Liczba drążków": "Ile drążków na ubrania widać w tym meblu?",
    "Materiał": "Z jakich materiałów wykonany jest widoczny mebel?",
    "Podparcie": "Na czym stoi ten mebel: nóżki, kółka, płozy, cokół, czy jest wiszący?",
    "Rodzaj drzwi": "Jakiego rodzaju są drzwi tego mebla: uchylne, przesuwne czy klapowe?",
    "Oświetlenie": "Czy mebel ma wbudowane oświetlenie?",
    "Kształt blatu": "Jaki kształt ma blat tego mebla?",
    "Tapicerowane": "Czy ten mebel jest tapicerowany?",
    "Zagłówek": "Czy ten mebel ma zagłówek?",
    "Podłokietniki": "Czy ten mebel ma podłokietniki?",
    "Na nóżkach": "Czy ten mebel stoi na widocznych nóżkach?",
    "Rodzaj frontu": "Jakie są fronty tego mebla: pełne, ryflowane, przeszklone, z lustrem, ażurowe?",
    "Dekoracje": "Jakie zdobienia widać na tym meblu?",
    "Styl": "W jakim stylu utrzymany jest ten mebel?",
    # Wymiary da się odczytać TYLKO z rysunku technicznego — dobór ujęcia
    # (zdjecia.UJECIE_DLA_ATRYBUTU) pilnuje, żeby model dostał właśnie jego.
    "Szerokość": "Jaka szerokość mebla jest podana na rysunku technicznym? "
                 "Odczytaj liczbę z wymiarowania, w centymetrach.",
    "Wysokość": "Jaka wysokość mebla jest podana na rysunku technicznym? "
                "Odczytaj liczbę z wymiarowania, w centymetrach.",
    "Głębokość": "Jaka głębokość mebla jest podana na rysunku technicznym? "
                 "Odczytaj liczbę z wymiarowania, w centymetrach.",
}


def pytanie_dla(atrybut: str) -> str | None:
    return PYTANIA.get(atrybut)


def obslugiwane_atrybuty() -> set[str]:
    return set(PYTANIA) & WIDOCZNE_NA_ZDJECIU


# --- klucz API ------------------------------------------------------------

class BrakKlucza(RuntimeError):
    pass


def klucz_api() -> str:
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    plik = os.environ.get("GEMINI_API_KEY_FILE", "").strip()
    if plik and Path(plik).expanduser().exists():
        return Path(plik).expanduser().read_text(encoding="utf-8").strip()
    domyslny = Path.home() / ".atrybuty-gemini-key"
    if domyslny.exists():
        return domyslny.read_text(encoding="utf-8").strip()
    raise BrakKlucza(
        "Brak klucza Gemini. Ustaw GEMINI_API_KEY albo zapisz klucz "
        f"w pliku {domyslny} (chmod 600). Klucza nie wkładaj do repo.")


# --- baza: cache i werdykty ----------------------------------------------

SCHEMA_WIZJA = """
CREATE TABLE IF NOT EXISTS werdykty_wizji (
    produkt_id TEXT NOT NULL,
    atrybut TEXT NOT NULL,
    hasz_pytania TEXT NOT NULL,
    model TEXT,
    werdykt TEXT,               -- zgodne | niezgodne | nie_widac | blad
    wartosc_ze_zdjecia TEXT,
    pewnosc REAL,
    uzasadnienie TEXT,
    wartosc_w_bazie TEXT,
    tokenow_wejscia INTEGER,
    tokenow_wyjscia INTEGER,
    utworzono TEXT,
    PRIMARY KEY (produkt_id, atrybut, hasz_pytania)
);
CREATE INDEX IF NOT EXISTS ix_w_produkt ON werdykty_wizji(produkt_id);
CREATE INDEX IF NOT EXISTS ix_w_werdykt ON werdykty_wizji(werdykt);

CREATE TABLE IF NOT EXISTS cache_wizji (
    hasz TEXT PRIMARY KEY,      -- sha1(url zdjęcia + pytanie + wartość + model)
    odpowiedz TEXT,
    tokenow_wejscia INTEGER,
    tokenow_wyjscia INTEGER,
    utworzono TEXT
);
"""


def przygotuj_baze(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA_WIZJA)
    con.commit()


def hasz_zapytania(url: str, pytanie: str, wartosc: str, model: str) -> str:
    surowe = f"{url}|{pytanie}|{wartosc}|{model}".encode("utf-8")
    return hashlib.sha1(surowe).hexdigest()[:16]


# --- zdjęcia --------------------------------------------------------------

def pobierz_zdjecie(url: str, katalog_cache: Path, timeout: int = 20) -> bytes:
    """Pobiera i skaluje zdjęcie; trzyma kopię na dysku, żeby nie ciągnąć dwa razy."""
    katalog_cache.mkdir(parents=True, exist_ok=True)
    plik = katalog_cache / (hashlib.sha1(url.encode()).hexdigest()[:20] + ".jpg")
    if plik.exists():
        return plik.read_bytes()

    zadanie = urllib.request.Request(url, headers={"User-Agent": "atrybuty-oxm/1.0"})
    with urllib.request.urlopen(zadanie, timeout=timeout) as odp:
        surowe = odp.read()

    dane = _przeskaluj(surowe)
    plik.write_bytes(dane)
    return dane


def _przeskaluj(surowe: bytes) -> bytes:
    """Zmniejsza dłuższy bok do MAKS_BOK. Bez Pillow zwraca oryginał."""
    try:
        from PIL import Image
    except ImportError:
        return surowe
    try:
        obraz = Image.open(io.BytesIO(surowe))
        obraz = obraz.convert("RGB")
        if max(obraz.size) > MAKS_BOK:
            wsp = MAKS_BOK / max(obraz.size)
            nowy = (max(1, int(obraz.width * wsp)), max(1, int(obraz.height * wsp)))
            obraz = obraz.resize(nowy, Image.LANCZOS)
        bufor = io.BytesIO()
        obraz.save(bufor, format="JPEG", quality=85)
        return bufor.getvalue()
    except Exception:
        return surowe


# --- wywołanie modelu -----------------------------------------------------

@dataclass
class Odpowiedz:
    werdykt: str
    wartosc_ze_zdjecia: str
    pewnosc: float
    uzasadnienie: str
    tokenow_wejscia: int = 0
    tokenow_wyjscia: int = 0
    z_cache: bool = False


def _tresc_pytania(pytanie: str, atrybut: str, wartosc_w_bazie: str,
                   dozwolone: list[str], ujecie: str = "") -> str:
    lista = ", ".join(f"„{d}”" for d in dozwolone) if dozwolone else "(wartość opisowa)"
    return ((f"Rodzaj zdjęcia: {ujecie}\n" if ujecie else "")
            + f"Pytanie: {pytanie}\n"
            f"Atrybut w bazie: {atrybut}\n"
            f"Wartość zapisana w bazie: {wartosc_w_bazie or '(pusta)'}\n"
            f"Dozwolone wartości: {lista}\n\n"
            f"Oceń, czy wartość z bazy zgadza się ze zdjęciem.")


def zapytaj(zdjecie: bytes, pytanie: str, atrybut: str, wartosc_w_bazie: str,
            dozwolone: list[str], model: str = MODEL_WOLUMEN,
            timeout: int = 60, prob: int = 3, ujecie: str = "") -> Odpowiedz:
    ciało = {
        "systemInstruction": {"parts": [{"text": INSTRUKCJA}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(zdjecie).decode("ascii")}},
                {"text": _tresc_pytania(pytanie, atrybut, wartosc_w_bazie, dozwolone, ujecie)},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMAT_ODPOWIEDZI,
        },
    }
    dane = json.dumps(ciało).encode("utf-8")
    zadanie = urllib.request.Request(
        API_URL.format(model=model), data=dane,
        headers={"Content-Type": "application/json", "x-goog-api-key": klucz_api()})

    ostatni: Exception | None = None
    for proba in range(prob):
        try:
            with urllib.request.urlopen(zadanie, timeout=timeout) as odp:
                surowe = json.loads(odp.read())
            return _zparsuj(surowe)
        except urllib.error.HTTPError as e:
            ostatni = e
            if e.code in (429, 500, 503):        # limit albo chwilowa awaria
                time.sleep(2 ** proba * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            ostatni = e
            time.sleep(2 ** proba)
    raise RuntimeError(f"Gemini nie odpowiedział po {prob} próbach: {ostatni}")


def _zparsuj(surowe: dict) -> Odpowiedz:
    kandydaci = surowe.get("candidates") or []
    if not kandydaci:
        raise RuntimeError(f"Pusta odpowiedź modelu: {json.dumps(surowe)[:300]}")
    czesci = kandydaci[0].get("content", {}).get("parts") or []
    tekst = "".join(c.get("text", "") for c in czesci)
    dane = json.loads(tekst)
    uzycie = surowe.get("usageMetadata") or {}
    werdykt = dane.get("werdykt", "nie_widac")
    if werdykt not in WERDYKTY:
        werdykt = "nie_widac"
    return Odpowiedz(
        werdykt=werdykt,
        wartosc_ze_zdjecia=str(dane.get("wartosc_ze_zdjecia") or "").strip(),
        pewnosc=float(dane.get("pewnosc") or 0.0),
        uzasadnienie=str(dane.get("uzasadnienie") or "").strip(),
        tokenow_wejscia=int(uzycie.get("promptTokenCount") or 0),
        tokenow_wyjscia=int(uzycie.get("candidatesTokenCount") or 0),
    )


# --- koszt ----------------------------------------------------------------

# USD za 1M tokenów, cennik płatnego tiera (wrzesień 2026).
CENNIK = {
    MODEL_WOLUMEN: {"wejscie": 0.75, "wyjscie": 3.75},
    MODEL_SPORNE: {"wejscie": 2.00, "wyjscie": 12.00},
}


def koszt_usd(model: str, tok_we: int, tok_wy: int) -> float:
    c = CENNIK.get(model, CENNIK[MODEL_WOLUMEN])
    return tok_we / 1_000_000 * c["wejscie"] + tok_wy / 1_000_000 * c["wyjscie"]


# --- przebieg po kandydatach ---------------------------------------------

from datetime import datetime, timezone  # noqa: E402

from .model import PROG_DO_WIZJI  # noqa: E402


def _teraz() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def kandydaci(con: sqlite3.Connection, przebieg: int, limit: int | None = None,
              atrybut: str = "", producent: str = "", tylko_nowe: bool = True,
              losowo: bool = False) -> list[dict]:
    """Findingi, które przepuszcza bramka kosztowa: niska pewność + atrybut
    widoczny na zdjęciu + produkt ma zdjęcie."""
    obslugiwane = ",".join(f"'{a}'" for a in sorted(obslugiwane_atrybuty()))
    q = f"""
      SELECT f.produkt_id, f.atrybut, f.stara_wartosc, f.regula_id, f.pewnosc,
             p.nazwa, p.producent, p.kategoria, p.zdjecie, p.zdjecia
      FROM findingi f JOIN produkty p ON p.id = f.produkt_id
      LEFT JOIN werdykty_wizji w
             ON w.produkt_id = f.produkt_id AND w.atrybut = f.atrybut
      WHERE f.przebieg_id = :przebieg
        AND f.pewnosc < :prog
        AND p.zdjecie <> ''
        AND f.atrybut IN ({obslugiwane})
    """
    par: dict = {"przebieg": przebieg, "prog": PROG_DO_WIZJI}
    if tylko_nowe:
        q += " AND w.werdykt IS NULL"
    if atrybut:
        q += " AND f.atrybut = :atrybut"; par["atrybut"] = atrybut
    if producent:
        q += " AND p.producent = :producent"; par["producent"] = producent
    q += " GROUP BY f.produkt_id, f.atrybut"
    q += " ORDER BY RANDOM()" if losowo else " ORDER BY f.produkt_id"
    if limit:
        q += " LIMIT :limit"; par["limit"] = limit
    return [dict(r) for r in con.execute(q, par)]


def wybierz_zdjecie(poz: dict, atrybut: str) -> tuple[str, str]:
    """Które ujęcie wysłać do modelu. Zwraca (url, opis ujęcia).

    Do liczenia szuflad idzie wnętrze, do wymiarów rysunek techniczny.
    Wcześniej model dostawał zdjęcie główne — często aranżację — i słusznie
    odpowiadał „nie widać".
    """
    import json as _json
    surowe = poz.get("zdjecia")
    galeria = []
    if surowe:
        galeria = [zdjecia_mod.Zdjecie(e, u) for e, u in _json.loads(surowe)]
    wybrane = zdjecia_mod.wybierz(galeria, atrybut, poz.get("zdjecie") or "")
    if not wybrane:
        return "", ""
    opis = wybrane.etykieta or "zdjęcie główne"
    return wybrane.url, opis


def _dozwolone(atrybut: str) -> list[str]:
    return config.slowniki().get("atrybuty", {}).get(atrybut, {}).get("wartosci", []) or []


def przetworz(con: sqlite3.Connection, pozycje: Iterable[dict],
              model: str = MODEL_WOLUMEN, katalog_zdjec: Path | None = None,
              na_sucho: bool = False, echo=print) -> dict:
    """Przepuszcza kandydatów przez Gemini. Zwraca podsumowanie z kosztem.

    `na_sucho=True` liczy tylko, ile zapytań i ile by to kosztowało —
    bez ani jednego wywołania API.
    """
    przygotuj_baze(con)
    katalog_zdjec = katalog_zdjec or (Path(__file__).resolve().parent.parent
                                      / "dane" / "zdjecia")
    podsumowanie = {"zapytan": 0, "z_cache": 0, "bledow": 0, "tok_we": 0, "tok_wy": 0,
                    "werdykty": {}, "pominietych": 0}
    pozycje = list(pozycje)

    if na_sucho:
        # szacunek: ~258 tokenów za zdjęcie 512px + ~250 promptu, ~80 wyjścia
        podsumowanie["zapytan"] = len(pozycje)
        podsumowanie["tok_we"] = len(pozycje) * 508
        podsumowanie["tok_wy"] = len(pozycje) * 80
        podsumowanie["koszt_usd"] = koszt_usd(model, podsumowanie["tok_we"],
                                              podsumowanie["tok_wy"])
        podsumowanie["szacunek"] = True
        return podsumowanie

    for i, poz in enumerate(pozycje, 1):
        pytanie = pytanie_dla(poz["atrybut"])
        if not pytanie:
            podsumowanie["pominietych"] += 1
            continue

        url, ujecie = wybierz_zdjecie(poz, poz["atrybut"])
        if not url:
            podsumowanie["pominietych"] += 1
            continue
        h = hasz_zapytania(url, pytanie, poz["stara_wartosc"] or "", model)
        z_cache = con.execute(
            "SELECT odpowiedz, tokenow_wejscia, tokenow_wyjscia FROM cache_wizji WHERE hasz=?",
            (h,)).fetchone()

        if z_cache:
            dane = json.loads(z_cache["odpowiedz"])
            odp = Odpowiedz(**dane, z_cache=True)
            podsumowanie["z_cache"] += 1
        else:
            try:
                zdjecie = pobierz_zdjecie(url, katalog_zdjec)
                odp = zapytaj(zdjecie, pytanie, poz["atrybut"],
                              poz["stara_wartosc"] or "", _dozwolone(poz["atrybut"]),
                              model=model, ujecie=ujecie)
            except Exception as e:                       # noqa: BLE001
                podsumowanie["bledow"] += 1
                echo(f"  [{i}/{len(pozycje)}] BŁĄD {poz['produkt_id']} {poz['atrybut']}: {e}")
                con.execute(
                    "INSERT OR REPLACE INTO werdykty_wizji (produkt_id,atrybut,hasz_pytania,"
                    "model,werdykt,wartosc_ze_zdjecia,pewnosc,uzasadnienie,wartosc_w_bazie,"
                    "tokenow_wejscia,tokenow_wyjscia,utworzono)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (poz["produkt_id"], poz["atrybut"], h, model, "blad", "", 0.0,
                     str(e)[:300], poz["stara_wartosc"], 0, 0, _teraz()))
                con.commit()
                continue

            con.execute(
                "INSERT OR REPLACE INTO cache_wizji (hasz,odpowiedz,tokenow_wejscia,"
                "tokenow_wyjscia,utworzono) VALUES (?,?,?,?,?)",
                (h, json.dumps({"werdykt": odp.werdykt,
                                "wartosc_ze_zdjecia": odp.wartosc_ze_zdjecia,
                                "pewnosc": odp.pewnosc,
                                "uzasadnienie": odp.uzasadnienie,
                                "tokenow_wejscia": odp.tokenow_wejscia,
                                "tokenow_wyjscia": odp.tokenow_wyjscia},
                               ensure_ascii=False),
                 odp.tokenow_wejscia, odp.tokenow_wyjscia, _teraz()))
            podsumowanie["tok_we"] += odp.tokenow_wejscia
            podsumowanie["tok_wy"] += odp.tokenow_wyjscia

        con.execute(
            "INSERT OR REPLACE INTO werdykty_wizji (produkt_id,atrybut,hasz_pytania,"
            "model,werdykt,wartosc_ze_zdjecia,pewnosc,uzasadnienie,wartosc_w_bazie,"
            "tokenow_wejscia,tokenow_wyjscia,utworzono) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (poz["produkt_id"], poz["atrybut"], h, model, odp.werdykt,
             odp.wartosc_ze_zdjecia, odp.pewnosc, odp.uzasadnienie,
             poz["stara_wartosc"], odp.tokenow_wejscia, odp.tokenow_wyjscia, _teraz()))
        con.commit()

        podsumowanie["zapytan"] += 1
        podsumowanie["werdykty"][odp.werdykt] = podsumowanie["werdykty"].get(odp.werdykt, 0) + 1
        if i % 25 == 0 or i == len(pozycje):
            echo(f"  [{i}/{len(pozycje)}] {odp.werdykt:10s} "
                 f"koszt dotąd ${koszt_usd(model, podsumowanie['tok_we'], podsumowanie['tok_wy']):.3f}")

    podsumowanie["koszt_usd"] = koszt_usd(model, podsumowanie["tok_we"],
                                          podsumowanie["tok_wy"])
    return podsumowanie


def statystyki(con: sqlite3.Connection) -> dict:
    przygotuj_baze(con)
    wg_werdyktu = {r[0]: r[1] for r in con.execute(
        "SELECT werdykt, COUNT(*) FROM werdykty_wizji GROUP BY 1")}
    wg_atrybutu = [(r[0], r[1], r[2]) for r in con.execute(
        "SELECT atrybut, COUNT(*), SUM(werdykt='niezgodne') FROM werdykty_wizji "
        "GROUP BY 1 ORDER BY 2 DESC")]
    koszt = con.execute(
        "SELECT COALESCE(SUM(tokenow_wejscia),0), COALESCE(SUM(tokenow_wyjscia),0) "
        "FROM cache_wizji").fetchone()
    return {"werdykty": wg_werdyktu, "atrybuty": wg_atrybutu,
            "tok_we": koszt[0], "tok_wy": koszt[1],
            "koszt_usd": koszt_usd(MODEL_WOLUMEN, koszt[0], koszt[1])}


# --- kalibracja -----------------------------------------------------------

NAGLOWEK_KALIBRACJI = [
    "produkt_id", "nazwa", "producent", "kategoria", "atrybut",
    "wartosc_w_bazie", "werdykt_gemini", "wartosc_ze_zdjecia", "pewnosc",
    "uzasadnienie", "link_panelu", "zdjecie",
    "TWOJA_OCENA",   # do wypełnienia ręcznie: trafny / nietrafny / niejasny
    "UWAGI",
]


def eksport_kalibracji(con: sqlite3.Connection, sciezka: Path) -> int:
    """CSV z werdyktami do ręcznej oceny.

    Bez tego kroku nie wiadomo, czy wynikom wolno ufać — a przy 671 findingach
    ocena 200 sztuk to godzina pracy, która decyduje o wartości całej warstwy.
    """
    import csv as _csv
    sciezka.parent.mkdir(parents=True, exist_ok=True)
    wiersze = con.execute("""
        SELECT w.*, p.nazwa, p.producent, p.kategoria, p.zdjecie
        FROM werdykty_wizji w JOIN produkty p ON p.id = w.produkt_id
        WHERE w.werdykt <> 'blad'
        ORDER BY w.atrybut, w.werdykt""").fetchall()

    with sciezka.open("w", encoding="utf-8-sig", newline="") as f:
        pis = _csv.writer(f, delimiter=";")
        pis.writerow(NAGLOWEK_KALIBRACJI)
        for r in wiersze:
            pis.writerow([
                r["produkt_id"], r["nazwa"], r["producent"], r["kategoria"],
                r["atrybut"], r["wartosc_w_bazie"], r["werdykt"],
                r["wartosc_ze_zdjecia"], round(r["pewnosc"] or 0, 2),
                r["uzasadnienie"], config.link_produktu(r["produkt_id"]),
                r["zdjecie"], "", "",
            ])
    return len(wiersze)


def raport_kalibracji(sciezka: Path) -> dict:
    """Czyta wypełniony CSV i liczy trafność — globalnie i per atrybut."""
    import csv as _csv
    from collections import defaultdict

    per_atrybut: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_werdykt: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ogolem = {"trafny": 0, "nietrafny": 0, "niejasny": 0, "bez_oceny": 0}

    with sciezka.open(encoding="utf-8-sig", newline="") as f:
        for r in _csv.DictReader(f, delimiter=";"):
            ocena = (r.get("TWOJA_OCENA") or "").strip().lower()
            if ocena not in ("trafny", "nietrafny", "niejasny"):
                ogolem["bez_oceny"] += 1
                continue
            ogolem[ocena] += 1
            per_atrybut[r["atrybut"]][ocena] += 1
            per_werdykt[r["werdykt_gemini"]][ocena] += 1

    def trafnosc(d: dict[str, int]) -> float | None:
        baza = d.get("trafny", 0) + d.get("nietrafny", 0)
        return d.get("trafny", 0) / baza if baza else None

    return {
        "ogolem": ogolem,
        "trafnosc": trafnosc(ogolem),
        "per_atrybut": {k: {"n": sum(v.values()), "trafnosc": trafnosc(v)}
                        for k, v in sorted(per_atrybut.items())},
        "per_werdykt": {k: {"n": sum(v.values()), "trafnosc": trafnosc(v)}
                        for k, v in sorted(per_werdykt.items())},
    }


# --- wymiary z rysunku technicznego ---------------------------------------
#
# Osobna ścieżka, bo to inne zadanie niż reszta warstwy L3. Tam model ocenia
# JEDNĄ cechę i odpowiada zgodne/niezgodne. Tu nie ma czego oceniać — wymiaru
# w bazie po prostu nie ma — a na rysunku technicznym wymiary są WYPISANE
# liczbami, więc model ich nie szacuje, tylko odczytuje.
#
# Trzy wymiary lecą jednym zapytaniem: są na tym samym rysunku, a trzy osobne
# wywołania to trzykrotny koszt za to samo zdjęcie.

WYMIARY = ("Szerokość", "Wysokość", "Głębokość")

SCHEMAT_WYMIARY = {
    "type": "object",
    "properties": {
        "szerokosc": {"type": "string"},
        "wysokosc": {"type": "string"},
        "glebokosc": {"type": "string"},
        "jednostka": {"type": "string"},
        "pewnosc": {"type": "number"},
        "uzasadnienie": {"type": "string"},
    },
    "required": ["szerokosc", "wysokosc", "glebokosc", "jednostka",
                 "pewnosc", "uzasadnienie"],
}

INSTRUKCJA_WYMIARY = (
    "Odczytujesz wymiary mebla z rysunku technicznego albo schematu. "
    "Wymiary są na nim WYPISANE liczbami — masz je przepisać, nie szacować.\n\n"
    "Zasady:\n"
    "- Podaj samą liczbę, bez jednostki (np. „110”, nie „110 cm”).\n"
    "- Jednostkę podaj osobno w polu 'jednostka': cm albo mm.\n"
    "- Jeśli któregoś wymiaru na rysunku NIE MA, zostaw to pole puste. "
    "Pusta odpowiedź jest poprawna — zmyślona liczba trafi wprost do sklepu.\n"
    "- Szerokość to wymiar poziomy widoku z przodu, wysokość pionowy, "
    "głębokość to wymiar z widoku z boku albo z góry.\n"
    "- Gdy rysunek pokazuje zakres albo kilka wariantów, zostaw pole puste.\n"
    "- 'pewnosc' 0-1 dotyczy całego odczytu.\n"
    "- 'uzasadnienie' to jedno krótkie zdanie po polsku: skąd te liczby."
)


@dataclass
class OdpowiedzWymiary:
    wymiary: dict[str, str]          # nazwa atrybutu -> wartość w cm
    jednostka: str
    pewnosc: float
    uzasadnienie: str
    tokenow_wejscia: int = 0
    tokenow_wyjscia: int = 0

    @property
    def cokolwiek(self) -> bool:
        return any(self.wymiary.values())


def _na_centymetry(wartosc: str, jednostka: str) -> str:
    """Sklep trzyma wymiary w centymetrach; rysunki bywają w milimetrach."""
    liczba = do_liczby(wartosc)
    if liczba is None:
        return ""
    if jednostka.strip().lower() in ("mm", "milimetry", "milimetr"):
        liczba = liczba / 10
    return f"{liczba:g}"


def odczytaj_wymiary(zdjecie: bytes, nazwa_produktu: str = "",
                     model: str = MODEL_WOLUMEN, timeout: int = 60,
                     prob: int = 3) -> OdpowiedzWymiary:
    ciało = {
        "systemInstruction": {"parts": [{"text": INSTRUKCJA_WYMIARY}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "image/jpeg",
                                 "data": base64.b64encode(zdjecie).decode("ascii")}},
                {"text": f"Mebel: {nazwa_produktu}\n"
                         "Odczytaj z rysunku szerokość, wysokość i głębokość."},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": SCHEMAT_WYMIARY,
        },
    }
    dane = json.dumps(ciało).encode("utf-8")
    zadanie = urllib.request.Request(
        API_URL.format(model=model), data=dane,
        headers={"Content-Type": "application/json", "x-goog-api-key": klucz_api()})

    ostatni: Exception | None = None
    for proba in range(prob):
        try:
            with urllib.request.urlopen(zadanie, timeout=timeout) as odp:
                surowe = json.loads(odp.read())
            return _zparsuj_wymiary(surowe)
        except urllib.error.HTTPError as e:
            ostatni = e
            if e.code in (429, 500, 503):
                time.sleep(2 ** proba * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            ostatni = e
            time.sleep(2 ** proba)
    raise RuntimeError(f"Gemini nie odpowiedział po {prob} próbach: {ostatni}")


def _zparsuj_wymiary(surowe: dict) -> OdpowiedzWymiary:
    kand = surowe.get("candidates") or []
    if not kand:
        raise RuntimeError(f"Pusta odpowiedź modelu: {json.dumps(surowe)[:300]}")
    tekst = "".join(c.get("text", "") for c in
                    (kand[0].get("content", {}).get("parts") or []))
    dane = json.loads(tekst)
    uzycie = surowe.get("usageMetadata") or {}
    jednostka = str(dane.get("jednostka") or "cm").strip()
    return OdpowiedzWymiary(
        wymiary={
            "Szerokość": _na_centymetry(str(dane.get("szerokosc") or ""), jednostka),
            "Wysokość": _na_centymetry(str(dane.get("wysokosc") or ""), jednostka),
            "Głębokość": _na_centymetry(str(dane.get("glebokosc") or ""), jednostka),
        },
        jednostka=jednostka,
        pewnosc=float(dane.get("pewnosc") or 0.0),
        uzasadnienie=str(dane.get("uzasadnienie") or "").strip(),
        tokenow_wejscia=int(uzycie.get("promptTokenCount") or 0),
        tokenow_wyjscia=int(uzycie.get("candidatesTokenCount") or 0),
    )
