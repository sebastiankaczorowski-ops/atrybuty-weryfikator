"""Źródło L4 z arkusza Google — zakładka z surowymi feedami producenta.

Arkusz „Imports - RAW FILES automat” trzyma feed każdego producenta w osobnej
zakładce, po jednym `<item>` z XML-a w komórce kolumny A. Zamiast pisać drugi
parser, sklejamy komórki z powrotem w jeden dokument XML i oddajemy go
istniejącej ścieżce w `zrodla.py` — wykrywanie rekordu, mapowanie w UI
i dopasowanie działają wtedy bez zmian.

Dostęp idzie przez konto serwisowe z uprawnieniem **tylko do odczytu**
(zakres `spreadsheets.readonly`). Narzędzie nigdy nie pisze do arkusza.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ZAKRES = "https://www.googleapis.com/auth/spreadsheets.readonly"
API = "https://sheets.googleapis.com/v4/spreadsheets"

RE_ARKUSZ = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
RE_GID = re.compile(r"[#?&]gid=(\d+)")

# `&` bez encji rozwala parser na całej zakładce, a jedna nieucieknięta
# ampersanda w URL-u zdjęcia to w feedach norma. Uciekamy tylko te, które
# nie są już początkiem encji.
RE_GOLA_AMPERSANDA = re.compile(r"&(?!(?:[A-Za-z]+|#\d+|#x[0-9A-Fa-f]+);)")
RE_DEKLARACJA = re.compile(r"<\?xml[^>]*\?>")


class BladArkusza(RuntimeError):
    pass


def jest_arkuszem(url: str) -> bool:
    return bool(RE_ARKUSZ.search(url or ""))


def rozbierz_url(url: str) -> tuple[str, int | None]:
    """URL arkusza -> (id arkusza, gid zakładki albo None)."""
    m = RE_ARKUSZ.search(url or "")
    if not m:
        raise BladArkusza("to nie jest adres arkusza Google")
    g = RE_GID.search(url)
    return m.group(1), int(g.group(1)) if g else None


def zloz_xml(komorki: list[str]) -> bytes:
    """Komórki z fragmentami XML -> jeden dokument z korzeniem <arkusz>.

    Puste komórki pomijamy, deklaracje `<?xml ...?>` wycinamy — w środku
    dokumentu byłyby błędem składni.
    """
    fragmenty = []
    for k in komorki:
        k = RE_DEKLARACJA.sub("", (k or "")).strip()
        if k:
            fragmenty.append(RE_GOLA_AMPERSANDA.sub("&amp;", k))
    if not fragmenty:
        raise BladArkusza("zakładka jest pusta")
    return ("<arkusz>\n" + "\n".join(fragmenty) + "\n</arkusz>").encode("utf-8")


# --- uwierzytelnienie -----------------------------------------------------

def sciezka_klucza() -> Path:
    """Klucz konta serwisowego: ta sama zmienna co w manager-dashboard."""
    z_env = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    sciezka = Path(z_env) if z_env else Path.home() / ".atrybuty-google-key.json"
    if not sciezka.is_file():
        raise BladArkusza(
            "Brak klucza konta serwisowego Google. Ustaw GOOGLE_APPLICATION_CREDENTIALS "
            f"albo zapisz klucz w {Path.home() / '.atrybuty-google-key.json'}.")
    return sciezka


def token(sciezka: Path | None = None) -> str:
    """Token dostępu z klucza konta serwisowego (JWT bearer, bez `requests`)."""
    from google.auth import crypt, jwt   # import tu: bez arkuszy biblioteka niepotrzebna

    info = json.loads((sciezka or sciezka_klucza()).read_text(encoding="utf-8"))
    teraz = int(time.time())
    asercja = jwt.encode(crypt.RSASigner.from_service_account_info(info), {
        "iss": info["client_email"], "scope": ZAKRES, "aud": info["token_uri"],
        "iat": teraz, "exp": teraz + 3600})
    tresc = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": asercja.decode() if isinstance(asercja, bytes) else asercja,
    }).encode()
    odp = _zapytanie(urllib.request.Request(info["token_uri"], data=tresc))
    return odp["access_token"]


def _zapytanie(req: urllib.request.Request, timeout: int = 60) -> dict:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as odp:
            return json.loads(odp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise BladArkusza(
                "Google odmówił dostępu (403) — arkusz nie jest udostępniony "
                "kontu serwisowemu albo Sheets API nie jest włączone w projekcie.") from e
        if e.code == 404:
            raise BladArkusza("Google nie widzi takiego arkusza (404).") from e
        raise BladArkusza(f"Google zwrócił {e.code} {e.reason}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise BladArkusza(f"nie udało się połączyć z Google: {e}") from e


def _get(url: str, tok: str) -> dict:
    return _zapytanie(urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"}))


# --- odczyt ---------------------------------------------------------------

def zakladki(id_arkusza: str, tok: str) -> list[dict]:
    """[{gid, tytul}] — wszystkie zakładki arkusza."""
    dane = _get(f"{API}/{id_arkusza}?fields=sheets.properties(sheetId,title)", tok)
    return [{"gid": s["properties"]["sheetId"], "tytul": s["properties"]["title"]}
            for s in dane.get("sheets", [])]


def pobierz_zakladke(url: str) -> tuple[bytes, str]:
    """Zwraca (dokument XML albo JSON, nazwa zakładki) dla zakładki z `gid`.

    Bez `gid` nie zgadujemy — pierwsza zakładka to feed jednego producenta,
    a źródło jest przypisane do konkretnego. Zamiast tego podajemy listę.
    """
    id_arkusza, gid = rozbierz_url(url)
    tok = token()
    lista = zakladki(id_arkusza, tok)
    if gid is None:
        nazwy = ", ".join(f"{z['tytul']} (gid={z['gid']})" for z in lista)
        raise BladArkusza(f"W adresie brakuje #gid= zakładki. Zakładki w arkuszu: {nazwy}")
    tytul = next((z["tytul"] for z in lista if z["gid"] == gid), None)
    if tytul is None:
        raise BladArkusza(f"w arkuszu nie ma zakładki gid={gid}")

    zakres = urllib.parse.quote(f"'{tytul}'", safe="")
    dane = _get(f"{API}/{id_arkusza}/values/{zakres}", tok)
    return zloz_zakladke(dane.get("values") or []), tytul


def zloz_zakladke(wiersze: list[list[str]]) -> bytes:
    """Wiersze zakładki -> dokument, który zrozumie `zrodla.rekordy`.

    Zakładki nie mają jednego formatu: Bogart trzyma po jednym <item> XML-a
    w komórce, a WojcikProductsV4Ours to zwykła tabela z nagłówkami.
    Czytanie samej kolumny A dawało z tabeli tekst bez struktury i błąd
    „XML nie zawiera powtarzających się elementów”.
    """
    kolumna_a = [(w[0] if w else "").strip() for w in wiersze]
    niepuste = [k for k in kolumna_a if k]
    if not niepuste:
        raise BladArkusza("zakładka jest pusta")

    if _wiekszosc(niepuste, lambda k: k.startswith("<")):
        return zloz_xml(kolumna_a)
    if _wiekszosc(niepuste, lambda k: k.startswith("{")):
        try:
            return json.dumps([json.loads(k) for k in niepuste],
                              ensure_ascii=False).encode("utf-8")
        except json.JSONDecodeError as e:
            raise BladArkusza(f"komórki wyglądają na JSON, ale nie dają się odczytać: {e}") from e
    return zloz_tabele(wiersze)


def _wiekszosc(komorki: list[str], warunek) -> bool:
    probka = komorki[:200]
    return sum(1 for k in probka if warunek(k)) > len(probka) / 2


def zloz_tabele(wiersze: list[list[str]]) -> bytes:
    """Tabela z nagłówkami w pierwszym wierszu -> lista rekordów w JSON-ie.

    JSON, nie CSV: `rekordy_csv` zgaduje separator z liczby średników
    i przecinków, a wartości typu „szary,grafitowy” by go zmyliły.
    """
    naglowki = [(n or "").strip() for n in wiersze[0]]
    if not any(naglowki):
        raise BladArkusza("pierwszy wiersz zakładki nie ma nagłówków")
    # Arkusz ucina puste komórki na końcu wiersza, więc wiersz bywa krótszy
    # od nagłówka — dopełniamy, zamiast gubić ostatnie kolumny.
    rekordy = []
    for w in wiersze[1:]:
        r = {n: (w[i] if i < len(w) else "").strip()
             for i, n in enumerate(naglowki) if n}
        if any(r.values()):
            rekordy.append(r)
    if not rekordy:
        raise BladArkusza("zakładka ma nagłówki, ale żadnego wiersza danych")
    return json.dumps(rekordy, ensure_ascii=False).encode("utf-8")
