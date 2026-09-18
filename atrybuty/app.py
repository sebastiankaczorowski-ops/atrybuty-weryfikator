"""Endpoint weryfikacji ręcznej.

FastAPI + Jinja2 + HTMX — ta sama konwencja co manager-dashboard, więc
przeniesienie na Mac Mini to później tylko Dockerfile.

    uvicorn atrybuty.app:app --reload --port 8083
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, HTMLResponse, RedirectResponse,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (config, db, eksport, eksport_panelu, importer, kategorie,
               panel_format, reguly as reguly_mod, weryfikacja as weryfikacja_mod,
               wizja, zapytania, zdjecia as zdjecia_mod, zrodla as zrodla_mod)
from .model import MIN_ATRYBUTOW, PROG_DO_WIZJI
from .tekst import norm
from .pipeline import BAZA

KATALOG = Path(__file__).resolve().parent
szablony = Jinja2Templates(directory=str(KATALOG / "templates"))
app = FastAPI(title="Kontrola atrybutów OXM")

# HTMX serwujemy z projektu, nie z CDN-a. Narzędzie ma działać też bez
# internetu i po LAN na Mac Mini — a bez htmx żaden przycisk w kolejce
# nie zadziała, co widać dopiero po kliknięciu.
app.mount("/static", StaticFiles(directory=str(KATALOG / "static")), name="static")

# Link do panelu sklepu jest dostępny w każdym szablonie jako `link_panelu(id)`.
szablony.env.globals["link_panelu"] = config.link_produktu


def _con():
    con = db.polacz(BAZA)
    wizja.przygotuj_baze(con)       # tabele werdyktów istnieją też przed pierwszym L3
    zrodla_mod.przygotuj_baze(con)  # to samo dla źródeł producenckich
    return con


def _przebieg(con) -> int:
    p = db.ostatni_przebieg(con)
    return int(p["id"]) if p else 0


@app.get("/", response_class=HTMLResponse)
def start():
    """Pusta baza = pierwsze uruchomienie. Wtedy sensowny start to import,
    a nie kolejka, w której nic nie ma."""
    con = _con()
    jest_przebieg = bool(db.ostatni_przebieg(con))
    con.close()
    return RedirectResponse("/anomalie" if jest_przebieg else "/import")


@app.get("/anomalie", response_class=HTMLResponse)
def anomalie(request: Request,
             kategoria: str = "", producent: str = "", regula: str = "",
             warstwa: str = "", waga: str = "", atrybut: str = "",
             status: str = "otwarte", routing: str = "", ma_zdjecie: str = "",
             werdykt: str = "", szukaj: str = "", grupuj: str = "1", strona: int = 1,
             widok: str = "findingi"):
    con = _con()
    przebieg = _przebieg(con)
    if not przebieg:
        con.close()
        return RedirectResponse("/import")

    fl = zapytania.Filtr(
        kategoria=kategoria, producent=producent, regula=regula, warstwa=warstwa,
        waga=waga, atrybut=atrybut, status=status, routing=routing,
        ma_zdjecie=ma_zdjecie, werdykt=werdykt, szukaj=szukaj, grupuj=(grupuj == "1"),
        limit=50, offset=(max(1, strona) - 1) * 50)

    if widok == "produkt":
        fl.grupuj = False
        fl.limit = 25                     # kafel produktu jest wyższy niż wiersz
        fl.offset = (max(1, strona) - 1) * 25
        produkty, ile = zapytania.lista_produktami(con, przebieg, fl)
        wiersze = [f for poz in produkty for f in poz["findingi"]]
    else:
        produkty = []
        wiersze = zapytania.lista(con, przebieg, fl)
        ile = zapytania.policz(con, przebieg, fl)

    # Podpowiedzi do „własnej wartości" — tylko dla atrybutów widocznych na tej
    # stronie, żeby nie wstawiać 473 wartości w każdy wiersz.
    slownik = panel_format.wczytaj_slownik()
    etykiety = panel_format.wczytaj_etykiety()
    listy_wartosci: dict[str, int] = {}
    wartosci_slownika: dict[str, list[str]] = {}
    for w in wiersze:
        atr = w["atrybut"]
        if atr in listy_wartosci or atr not in slownik:
            continue
        listy_wartosci[atr] = len(listy_wartosci) + 1
        mapa = etykiety.get(atr, {})
        wartosci_slownika[atr] = sorted(mapa.get(k, k) for k in slownik[atr])

    kontekst = {
        "request": request,
        "wiersze": wiersze,
        "ile": ile,
        "strona": strona,
        "stron": max(1, (ile + fl.limit - 1) // fl.limit),
        "widok": widok,
        "produkty": produkty,
        "fl": fl,
        "slowniki": zapytania.slowniki_filtrow(con, przebieg),
        "stat": zapytania.statystyki(con, przebieg),
        "nazwy_kat": kategorie.nazwy_kategorii(),
        "przebieg": db.ostatni_przebieg(con),
        "prog": PROG_DO_WIZJI,
        "pytania_wizji": wizja.obslugiwane_atrybuty(),
        "listy_wartosci": listy_wartosci,
        "wartosci_slownika": wartosci_slownika,
    }
    con.close()
    return szablony.TemplateResponse(request, "anomalie.html", kontekst)


@app.post("/decyzja", response_class=HTMLResponse)
def decyzja(request: Request,
            produkt_id: str = Form(...), atrybut: str = Form(...),
            stara: str = Form(""), nowa: str = Form(""),
            regula_id: str = Form(""), status: str = Form(...),
            grupa: str = Form(""), zakres: str = Form("pojedynczo")):
    """status: zastosowana | falszywy_alarm | odlozona

    zakres=grupa rozstrzyga wszystkie identyczne przypadki jedną decyzją —
    to ta rzecz, która zmienia 1081 kliknięć w jedno.
    """
    con = _con()
    przebieg = _przebieg(con)

    if zakres == "grupa" and grupa:
        czlonkowie = zapytania.czlonkowie_grupy(con, przebieg, grupa)
        # Blokada po stronie serwera, nie tylko w szablonie: grupa o różnych
        # wartościach nie jest jedną decyzją, choćby ktoś podrobił formularz.
        rozne = ({(c["stara_wartosc"] or "") for c in czlonkowie},
                 {(c["proponowana_wartosc"] or "") for c in czlonkowie})
        if len(rozne[0]) > 1 or len(rozne[1]) > 1:
            con.close()
            return HTMLResponse(
                '<div class="dowod">Ta grupa ma różne wartości — rozstrzygnij '
                'produkty osobno (rozwiń „×N podobnych").</div>')
        wiersze = [(c["produkt_id"], c["atrybut"], c["stara_wartosc"],
                    (c["proponowana_wartosc"] if status == "zastosowana" else None),
                    c["regula_id"]) for c in czlonkowie]
        ile = db.zapisz_decyzje_grupowo(con, wiersze, status)
        komunikat = f"{status}: {ile} produktów w grupie"
    else:
        db.zapisz_decyzje(con, produkt_id, atrybut, stara or None, status,
                          nowa or None, regula_id or None)
        ile, komunikat = 1, f"{status}: {produkt_id}"

    con.close()
    return HTMLResponse(
        f'<div class="zrobione">✓ {komunikat}</div>', status_code=200)


@app.post("/decyzja/produkt", response_class=HTMLResponse)
def decyzja_produkt(produkt_id: str = Form(...), status: str = Form("zastosowana")):
    """Rozstrzyga naraz wszystkie gotowe findingi jednego produktu.

    „Gotowe" to te z propozycją i pewnością powyżej progu — reszta zostaje
    otwarta, bo hurtowe zatwierdzanie czegoś, czego system sam nie jest
    pewien, byłoby klikaniem w ciemno.
    """
    con = _con()
    przebieg = _przebieg(con)
    wiersze = [dict(r) for r in con.execute(
        zapytania.BAZA_SQL + " AND f.produkt_id = :pid AND d.status IS NULL",
        {"przebieg": przebieg, "pid": produkt_id})]
    gotowe = [w for w in wiersze
              if w["proponowana_wartosc"] and w["pewnosc"] >= PROG_DO_WIZJI]
    ile = db.zapisz_decyzje_grupowo(
        con, [(w["produkt_id"], w["atrybut"], w["stara_wartosc"],
               (w["proponowana_wartosc"] if status == "zastosowana" else None),
               w["regula_id"]) for w in gotowe], status)
    zostalo = len(wiersze) - ile
    con.close()
    tresc = f"✓ {status}: {ile} poprawek"
    if zostalo:
        tresc += f" · {zostalo} zostaje do ręcznej oceny"
    return HTMLResponse(f'<div class="zrobione">{tresc}</div>')


@app.get("/grupa", response_class=HTMLResponse)
def grupa_podglad(request: Request, grupa: str = "", nr: str = ""):
    """Fragment HTMX: co dokładnie siedzi w tej grupie findingów."""
    if not grupa:                      # pusty klucz = „zwiń"
        return HTMLResponse("")
    con = _con()
    przebieg = _przebieg(con)
    czlonkowie = zapytania.podglad_grupy(con, przebieg, grupa) if przebieg else []
    ile = zapytania.policz_grupe(con, przebieg, grupa) if przebieg else 0
    con.close()
    return szablony.TemplateResponse(request, "_grupa.html", {
        "request": request, "czlonkowie": czlonkowie, "ile": ile,
        "grupa": grupa, "nr": nr, "nazwy_kat": kategorie.nazwy_kategorii()})


@app.get("/produkt/{pid}", response_class=HTMLResponse)
def produkt(request: Request, pid: str):
    con = _con()
    p = zapytania.produkt(con, pid)
    if not p:
        con.close()
        return HTMLResponse("Nie znaleziono", status_code=404)
    findingi = [dict(r) for r in con.execute(
        "SELECT * FROM findingi WHERE produkt_id=? AND przebieg_id=?",
        (pid, _przebieg(con)))]
    con.close()

    # Zestawienie obu miejsc obok siebie — najszybszy sposób, żeby zobaczyć,
    # co się rozjechało, bez przeskakiwania między zakładkami w panelu.
    atrybuty, skladowe_p = p["atrybuty_surowe"], p["skladowe"]
    wszystkie = sorted(set(atrybuty) | set(skladowe_p))
    zgodnosc = {}
    for k in wszystkie:
        a, s = atrybuty.get(k), skladowe_p.get(k)
        if a is None:
            zgodnosc[k] = "tylko-skladowe"
        elif s is None:
            zgodnosc[k] = "tylko-atrybuty"
        else:
            zgodnosc[k] = "zgodne" if norm(a) == norm(s) else "rozjazd"
    # rozjazdy i braki na górze — po to się tu wchodzi
    kolejnosc = {"rozjazd": 0, "tylko-skladowe": 1, "tylko-atrybuty": 2, "zgodne": 3}
    wszystkie.sort(key=lambda k: (kolejnosc[zgodnosc[k]], k))

    return szablony.TemplateResponse(request, "produkt.html", {
        "request": request, "p": p, "findingi": findingi,
        "wszystkie_atrybuty": wszystkie, "zgodnosc": zgodnosc,
        "nazwy_kat": kategorie.nazwy_kategorii()})


@app.get("/zrodla", response_class=HTMLResponse)
def strona_zrodel(request: Request, komunikat: str = "", blad: str = ""):
    con = _con()
    producenci = [r[0] for r in con.execute(
        "SELECT DISTINCT producent FROM produkty WHERE producent<>'' ORDER BY 1")]
    kontekst = {
        "request": request,
        "zrodla": zrodla_mod.lista_zrodel(con),
        "stat": zrodla_mod.statystyki(con),
        "producenci": producenci,
        "pola_docelowe": zrodla_mod.POLA_DOCELOWE,
        "podglad": None, "wybrane": None,
        "raport": zrodla_mod.raport_dopasowania(con),
        "komunikat": komunikat, "blad": bool(blad),
    }
    con.close()
    return szablony.TemplateResponse(request, "zrodla.html", kontekst)


@app.get("/zrodla/{zid}", response_class=HTMLResponse)
def podglad_zrodla(request: Request, zid: int):
    """Pobiera feed i pokazuje, co w nim jest — bez zapisywania pozycji."""
    con = _con()
    wybrane = zrodla_mod.zrodlo(con, zid)
    podglad = None
    komunikat, blad = "", False
    if not wybrane:
        komunikat, blad = "Nie ma takiego źródła.", True
    else:
        try:
            podglad = zrodla_mod.podglad(con, zid, importer.KATALOG_DANYCH)
        except zrodla_mod.BladZrodla as e:
            komunikat, blad = f"Nie udało się odczytać źródła: {e}", True
        except Exception as e:                               # noqa: BLE001
            komunikat, blad = f"Nie udało się odczytać źródła: {e}", True

    producenci = [r[0] for r in con.execute(
        "SELECT DISTINCT producent FROM produkty WHERE producent<>'' ORDER BY 1")]
    kontekst = {
        "request": request,
        "zrodla": zrodla_mod.lista_zrodel(con),
        "stat": zrodla_mod.statystyki(con),
        "producenci": producenci,
        "pola_docelowe": zrodla_mod.POLA_DOCELOWE,
        "podglad": podglad, "wybrane": wybrane,
        "raport": zrodla_mod.raport_dopasowania(con),
        "komunikat": komunikat, "blad": blad,
    }
    con.close()
    return szablony.TemplateResponse(request, "zrodla.html", kontekst)


def _wroc_zrodla(blad: str | None, ok: str, zid: int | None = None) -> RedirectResponse:
    from urllib.parse import urlencode
    baza = f"/zrodla/{zid}" if zid else "/zrodla"
    q = urlencode({"komunikat": blad or ok, "blad": "1" if blad else ""})
    return RedirectResponse(f"{baza}?{q}", status_code=303)


@app.post("/zrodla/dodaj")
async def dodaj_zrodlo(nazwa: str = Form(...), producent: str = Form(""),
                       url: str = Form(""), plik: UploadFile | None = File(None)):
    nazwa_pliku = ""
    if plik is not None and plik.filename:
        zapisany = importer.zapisz_plik(plik.filename, await plik.read())
        nazwa_pliku = zapisany.name
    if not url.strip() and not nazwa_pliku:
        return _wroc_zrodla("Podaj URL feedu albo wgraj plik.", "")

    con = _con()
    zid = zrodla_mod.dodaj_zrodlo(con, nazwa, producent, url, nazwa_pliku)
    con.close()
    return _wroc_zrodla(None, f"Dodano źródło „{nazwa}”. Podejrzyj je, żeby ustawić mapowanie.", zid)


@app.post("/zrodla/{zid}/mapowanie")
async def zapisz_mapowanie(request: Request, zid: int):
    """Mapowanie przychodzi jako pola pole__<nazwa docelowa>."""
    formularz = await request.form()
    mapowanie = {k[len("pole__"):]: v.strip()
                 for k, v in formularz.items()
                 if k.startswith("pole__") and isinstance(v, str) and v.strip()}
    if not mapowanie.get("klucz"):
        return _wroc_zrodla("Bez pola „klucz” nie ma jak połączyć feedu z produktami.", "", zid)

    con = _con()
    zrodla_mod.zapisz_mapowanie(con, zid, mapowanie)
    try:
        wynik = zrodla_mod.odswiez(con, zid, importer.KATALOG_DANYCH)
        komunikat = (f"Zapisano mapowanie. Pobrano {wynik['zapisanych']} pozycji "
                     f"z {wynik['rekordow']} rekordów. Przelicz dane na /import, "
                     f"żeby powstały findingi L4.")
        blad = None
    except zrodla_mod.BladZrodla as e:
        komunikat, blad = "", f"Mapowanie zapisane, ale pobranie się nie udało: {e}"
    con.close()
    return _wroc_zrodla(blad, komunikat, zid)


@app.post("/zrodla/{zid}/odswiez")
def odswiez_zrodlo(zid: int):
    con = _con()
    try:
        wynik = zrodla_mod.odswiez(con, zid, importer.KATALOG_DANYCH)
        if wynik["brak_klucza"]:
            odp = _wroc_zrodla("Źródło nie ma ustawionego pola „klucz” — "
                               "wejdź w podgląd i zmapuj pola.", "", zid)
        else:
            odp = _wroc_zrodla(None, f"Pobrano {wynik['zapisanych']} pozycji "
                                     f"z {wynik['rekordow']} rekordów.")
    except zrodla_mod.BladZrodla as e:
        odp = _wroc_zrodla(f"Nie udało się pobrać: {e}", "")
    except Exception as e:                                   # noqa: BLE001
        odp = _wroc_zrodla(f"Nie udało się pobrać: {e}", "")
    con.close()
    return odp


@app.post("/zrodla/{zid}/strategia")
def ustaw_strategie(zid: int, strategia: str = Form(...)):
    con = _con()
    zrodla_mod.ustaw_strategie(con, zid, strategia)
    con.close()
    return _wroc_zrodla(None, "Strategia zapisana. Przelicz dane na /import, "
                              "żeby findingi L4 powstały na nowo.", zid)


@app.post("/zrodla/{zid}/przelacz")
def przelacz_zrodlo(zid: int, aktywne: str = Form(...)):
    con = _con()
    zrodla_mod.przelacz_zrodlo(con, zid, aktywne == "1")
    con.close()
    return _wroc_zrodla(None, "Zmiana zapisze się w findingach przy następnym imporcie.")


@app.post("/zrodla/{zid}/usun")
def usun_zrodlo(zid: int):
    con = _con()
    zrodla_mod.usun_zrodlo(con, zid)
    con.close()
    return _wroc_zrodla(None, "Źródło usunięte wraz z pobranymi pozycjami.")


@app.get("/import", response_class=HTMLResponse)
def strona_importu(request: Request):
    con = _con()
    kontekst = {
        "request": request,
        "stan": importer.STAN,
        "trwa": importer.zajety(),
        "ostatni": db.ostatni_przebieg(con),
        "historia": importer.historia(con),
        "wgrane": importer.wgrane_pliki(),
        "katalog": str(importer.KATALOG_DANYCH),
        "sekundy": _ile_trwa(),
    }
    con.close()
    return szablony.TemplateResponse(request, "import.html", kontekst)


def _ile_trwa() -> int:
    start = importer.STAN.get("start")
    return int((datetime.now() - start).total_seconds()) if start and importer.zajety() else 0


@app.get("/import/stan", response_class=HTMLResponse)
def stan_importu(request: Request):
    """Fragment odpytywany co 2 s, dopóki przebieg trwa."""
    con = _con()
    ostatni = db.ostatni_przebieg(con)
    con.close()
    return szablony.TemplateResponse(request, "_stan_importu.html", {
        "request": request, "stan": importer.STAN, "ostatni": ostatni,
        "sekundy": _ile_trwa(),
    })


@app.post("/import")
async def wgraj_plik(plik: UploadFile = File(...),
                     plik_kategorii: UploadFile | None = File(None),
                     regeneruj_schema: str = Form("")):
    if importer.zajety():
        return RedirectResponse("/import", status_code=303)

    zapisany = importer.zapisz_plik(plik.filename or "products.csv", await plik.read())
    kategorie_plik = None
    if plik_kategorii is not None and plik_kategorii.filename:
        kategorie_plik = importer.zapisz_plik(plik_kategorii.filename,
                                              await plik_kategorii.read())
    importer.uruchom_w_tle(zapisany, kategorie_plik, regeneruj_schema == "1")
    return RedirectResponse("/import", status_code=303)


@app.post("/import/ponow")
def ponow_import(nazwa: str = Form(...), regeneruj_schema: str = Form("")):
    """Przeliczenie z pliku, który już leży w katalogu danych."""
    sciezka = importer.sciezka_wgranego(nazwa)
    if sciezka and not importer.zajety():
        importer.uruchom_w_tle(sciezka, None, regeneruj_schema == "1")
    return RedirectResponse("/import", status_code=303)


@app.post("/wizja/sprawdz", response_class=HTMLResponse)
def wizja_sprawdz(request: Request,
                  produkt_id: str = Form(...), atrybut: str = Form(...),
                  stara: str = Form(""), nr: str = Form("0"),
                  sporne: str = Form("")):
    """Sprawdzenie JEDNEGO findingu zdjęciem, na żądanie z kolejki.

    Płacisz tylko za to, co klikniesz — przebieg wsadowy (`pipeline wizja`)
    zostaje do momentu, gdy kalibracja pokaże, że wynikom można ufać.
    """
    con = _con()
    p = zapytania.produkt(con, produkt_id)
    if not p:
        con.close()
        return szablony.TemplateResponse(request, "_werdykt.html",
                                         {"request": request, "blad": "nie ma takiego produktu"})
    if not (p["zdjecie"] or "").strip():
        con.close()
        return szablony.TemplateResponse(request, "_werdykt.html",
                                         {"request": request, "blad": "produkt nie ma zdjęcia"})

    pytanie = wizja.pytanie_dla(atrybut)
    if not pytanie:
        con.close()
        return szablony.TemplateResponse(
            request, "_werdykt.html",
            {"request": request, "blad": f"brak pytania dla atrybutu „{atrybut}” "
                                         f"(to cecha, której nie widać na zdjęciu)"})

    model = wizja.MODEL_SPORNE if sporne else wizja.MODEL_WOLUMEN
    try:
        wizja.klucz_api()
    except wizja.BrakKlucza as e:
        con.close()
        return szablony.TemplateResponse(request, "_werdykt.html",
                                         {"request": request, "blad": str(e)})

    poz = [{"produkt_id": produkt_id, "atrybut": atrybut,
            "stara_wartosc": stara or p["atrybuty"].get(atrybut, ""),
            "zdjecie": p["zdjecie"]}]
    try:
        podsum = wizja.przetworz(con, poz, model=model, echo=lambda *_: None)
    except Exception as e:                                   # noqa: BLE001
        con.close()
        return szablony.TemplateResponse(request, "_werdykt.html",
                                         {"request": request, "blad": str(e)[:200]})

    r = con.execute(
        "SELECT * FROM werdykty_wizji WHERE produkt_id=? AND atrybut=? "
        "ORDER BY utworzono DESC LIMIT 1", (produkt_id, atrybut)).fetchone()
    con.close()
    if not r or r["werdykt"] == "blad":
        return szablony.TemplateResponse(
            request, "_werdykt.html",
            {"request": request, "blad": (r["uzasadnienie"] if r else "brak odpowiedzi")})

    return szablony.TemplateResponse(request, "_werdykt.html", {
        "request": request,
        "w": {"werdykt": r["werdykt"], "wartosc_ze_zdjecia": r["wartosc_ze_zdjecia"],
              "pewnosc": r["pewnosc"], "uzasadnienie": r["uzasadnienie"],
              "z_cache": podsum["z_cache"] > 0},
        "koszt": podsum["koszt_usd"],
        "model_krotki": "Pro" if sporne else "Flash",
        "produkt_id": produkt_id, "atrybut": atrybut, "stara": stara, "nr": nr,
        "blad": None,
    })


@app.post("/wizja/wymiary", response_class=HTMLResponse)
def wizja_wymiary(request: Request, produkt_id: str = Form(...), nr: str = Form("0")):
    """Odczyt wymiarów z rysunku technicznego — jedno zapytanie na trzy pola.

    Osobno od `/wizja/sprawdz`, bo to inne zadanie: tam model ocenia wartość
    z bazy, tu w bazie nie ma czego oceniać. Na rysunku wymiary są wypisane
    liczbami, więc model je odczytuje, a nie szacuje.
    """
    con = _con()
    p = zapytania.produkt(con, produkt_id)
    con.close()
    if not p:
        return szablony.TemplateResponse(request, "_wymiary.html",
                                         {"request": request, "blad": "nie ma takiego produktu"})

    galeria = [zdjecia_mod.Zdjecie(e, u) for e, u in json.loads(p.get("zdjecia") or "[]")]
    rysunek = next((z for z in galeria if z.rodzaj == "rysunek"), None)
    if rysunek is None:
        return szablony.TemplateResponse(
            request, "_wymiary.html",
            {"request": request,
             "blad": "ten produkt nie ma rysunku technicznego — wymiary trzeba wziąć skądinąd"})

    try:
        wizja.klucz_api()
        obraz = wizja.pobierz_zdjecie(rysunek.url, KATALOG.parent / "dane" / "cache_zdjec")
        odp = wizja.odczytaj_wymiary(obraz, p["nazwa"])
    except Exception as e:                                   # noqa: BLE001
        return szablony.TemplateResponse(request, "_wymiary.html",
                                         {"request": request, "blad": str(e)[:200]})

    # pokazujemy tylko te wymiary, których w bazie faktycznie brakuje
    braki = {k: v for k, v in odp.wymiary.items()
             if v and not (p["atrybuty_surowe"].get(k) or "").strip()}
    return szablony.TemplateResponse(request, "_wymiary.html", {
        "request": request, "odp": odp, "braki": braki, "rysunek": rysunek,
        "produkt_id": produkt_id, "nr": nr, "blad": None,
        "koszt": wizja.koszt_usd(wizja.MODEL_WOLUMEN, odp.tokenow_wejscia,
                                 odp.tokenow_wyjscia),
    })


@app.get("/braki", response_class=HTMLResponse)
def braki(request: Request, producent: str = "", kategoria: str = "", rodzaj: str = "",
          szukaj: str = "", strona: int = 1):
    """Produkty, których nie ma sensu analizować — do zaciągnięcia ze źródła."""
    from urllib.parse import urlencode
    con = _con()
    na_stronie = 100
    wiersze, ile = zapytania.braki(con, producent, kategoria, rodzaj, szukaj,
                                   limit=na_stronie, offset=(max(1, strona) - 1) * na_stronie)
    stat = zapytania.braki_statystyki(con)
    con.close()
    query = urlencode({k: v for k, v in
                       (("producent", producent), ("kategoria", kategoria),
                        ("rodzaj", rodzaj), ("szukaj", szukaj)) if v})
    return szablony.TemplateResponse(request, "braki.html", {
        "request": request, "wiersze": wiersze, "ile": ile, "stat": stat,
        "producent": producent, "kategoria": kategoria, "rodzaj": rodzaj,
        "szukaj": szukaj, "strona": strona,
        "stron": max(1, (ile + na_stronie - 1) // na_stronie),
        "query": query, "nazwy_kat": kategorie.nazwy_kategorii(),
        "min_atrybutow": MIN_ATRYBUTOW,
    })


@app.get("/braki/eksport")
def braki_eksport(producent: str = "", kategoria: str = "", rodzaj: str = "",
                  szukaj: str = ""):
    """Lista ID do ponownego zaciągnięcia — wprost do zapytania u źródła."""
    import csv as _csv
    import io
    con = _con()
    wiersze, _ = zapytania.braki(con, producent, kategoria, rodzaj, szukaj,
                                 limit=1_000_000, offset=0)
    con.close()

    bufor = io.StringIO()
    w = _csv.writer(bufor, delimiter=";")
    w.writerow(["id", "nazwa", "producent", "kolekcja", "kategoria",
                "ile_atrybutow", "rodzaj_braku", "ma_zdjecie", "link_panelu"])
    for r in wiersze:
        w.writerow([r["id"], r["nazwa"], r["producent"], r["kolekcja"], r["kategoria"],
                    r["ile_atrybutow"], r["kompletnosc"],
                    "tak" if r["zdjecie"] else "nie", config.link_produktu(r["id"])])
    bufor.seek(0)
    nazwa = f"braki_danych_{datetime.now():%Y-%m-%d_%H%M}.csv"
    return StreamingResponse(
        iter(["\ufeff" + bufor.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nazwa}"'})


@app.get("/reguly", response_class=HTMLResponse)
def lista_regul(request: Request, komunikat: str = "", blad: str = ""):
    con = _con()
    kat = reguly_mod.katalog(con, _przebieg(con))
    con.close()
    atr = config.slowniki().get("atrybuty", {})
    return szablony.TemplateResponse(request, "reguly.html", {
        "request": request,
        "katalog": kat,
        "komunikat": komunikat,
        "blad": bool(blad),
        "atrybuty_enum": sorted(k for k, v in atr.items()
                                if v.get("typ") in ("enum", "multi_enum")),
        "atrybuty_liczbowe": sorted(k for k, v in atr.items() if v.get("typ") == "liczba"),
    })


def _wroc(blad: str | None, ok: str) -> RedirectResponse:
    from urllib.parse import urlencode
    q = urlencode({"komunikat": blad or ok, "blad": "1" if blad else ""})
    return RedirectResponse(f"/reguly?{q}", status_code=303)


def _lista(tekst: str) -> list[str]:
    return [x.strip() for x in (tekst or "").split(",") if x.strip()]


@app.post("/reguly/przelacz")
def przelacz_regule(rid: str = Form(...), aktywna: str = Form(...)):
    reguly_mod.przelacz(rid, aktywna == "1")
    return _wroc(None, f"Reguła {rid} {'włączona' if aktywna == '1' else 'wyłączona'}. "
                       f"Zadziała przy następnym imporcie.")


@app.post("/reguly/usun")
def usun_regule(rid: str = Form(...)):
    if reguly_mod.usun(rid):
        return _wroc(None, f"Reguła {rid} usunięta.")
    return _wroc(f"Nie znaleziono reguły {rid} albo jest wbudowana.", "")


@app.post("/reguly/dodaj-sprzecznosc")
def dodaj_sprzecznosc(rid: str = Form(...), atrybut: str = Form(...),
                      wartosc: str = Form(...), nie_moze_miec: str = Form(""),
                      nazwa_zawiera: str = Form(""), opis: str = Form("")):
    blad = reguly_mod.dodaj_sprzecznosc(rid, atrybut, wartosc, _lista(nie_moze_miec),
                                        _lista(nazwa_zawiera), opis)
    return _wroc(blad, f"Dodano sprzeczność {rid.upper()}. Zadziała przy następnym imporcie.")


@app.post("/reguly/dodaj-relacje")
def dodaj_relacje(rid: str = Form(...), lewa: str = Form(...), operator: str = Form(...),
                  prawa: str = Form(...), opis: str = Form("")):
    blad = reguly_mod.dodaj_relacje(rid, lewa, operator, prawa, opis)
    return _wroc(blad, f"Dodano relację {rid.upper()}. Zadziała przy następnym imporcie.")


@app.post("/reguly/dodaj-klucz")
def dodaj_klucz(klucz: str = Form(...), powod: str = Form(""), propozycja: str = Form("")):
    blad = reguly_mod.dodaj_klucz(klucz, powod, propozycja)
    return _wroc(blad, f"Dodano klucz „{klucz}” do usunięcia. Zadziała przy następnym imporcie.")


@app.post("/eksport")
def zrob_eksport(paczka: int = Form(0)):
    con = _con()
    wynik = eksport.zapisz(con, KATALOG.parent / "dane" / "eksport",
                           paczka=paczka or None)
    con.close()
    return wynik


# --- rozstrzygnięte i eksport partiami ------------------------------------

KATALOG_PARTII = KATALOG.parent / "dane" / "eksport"


@app.get("/rozstrzygniete", response_class=HTMLResponse)
def strona_rozstrzygnietych(request: Request, status: str = "", atrybut: str = "",
                            regula: str = "", producent: str = "", eksport_stan: str = "",
                            szukaj: str = "", strona: int = 1):
    con = _con()
    offset = (max(1, strona) - 1) * 100
    wiersze, ile = zapytania.rozstrzygniete(
        con, status=status, atrybut=atrybut, regula=regula, producent=producent,
        eksport=eksport_stan, szukaj=szukaj, limit=100, offset=offset)
    kontekst = {
        "request": request, "wiersze": wiersze, "ile": ile, "strona": strona,
        "stron": max(1, (ile + 99) // 100),
        "fl": {"status": status, "atrybut": atrybut, "regula": regula,
               "producent": producent, "eksport_stan": eksport_stan, "szukaj": szukaj},
        "stat": zapytania.statystyki_decyzji(con),
        "slowniki": zapytania.slowniki_decyzji(con),
        "nazwy_kat": kategorie.nazwy_kategorii(),
    }
    con.close()
    return szablony.TemplateResponse(request, "rozstrzygniete.html", kontekst)


@app.post("/rozstrzygniete/cofnij", response_class=HTMLResponse)
def cofnij_decyzje(produkt_id: str = Form(...), atrybut: str = Form(...),
                   hasz: str = Form(...)):
    """Kasuje decyzję — finding wraca do kolejki jako otwarty.

    Decyzji z przypisaną partią nie ruszamy: plik już powstał, więc cofnięcie
    tutaj rozjechałoby bazę z tym, co poszło do sklepu. Najpierw wycofaj partię.
    """
    con = _con()
    wiersz = con.execute(
        "SELECT partia_id FROM decyzje WHERE produkt_id=? AND atrybut=? AND hasz_starej=?",
        (produkt_id, atrybut, hasz)).fetchone()
    if wiersz and wiersz["partia_id"]:
        con.close()
        return HTMLResponse(
            '<span class="dowod">w partii — cofnij najpierw partię</span>')
    con.execute("DELETE FROM decyzje WHERE produkt_id=? AND atrybut=? AND hasz_starej=?",
                (produkt_id, atrybut, hasz))
    con.commit()
    con.close()
    return HTMLResponse('<span class="zrobione">✓ cofnięte</span>')


@app.post("/zglos-produkt", response_class=HTMLResponse)
def zglos_produkt(produkt_id: str = Form(...), powod: str = Form("")):
    """Dopisuje produkt do najbliższej partii, choć nic w nim nie poprawiamy.

    Po to, żeby panel dostał jego wiersz i mógł mu postawić flagę „składowe
    już nieużywane". Produkt sprawdzony i uznany za poprawny też musi przez
    import przejść — inaczej zostanie ze składowymi na froncie na zawsze.

    Wiersz takiego produktu niesie KOMPLET jego legitnych atrybutów, nie
    pojedynczą poprawkę, więc powtórzenie importu niczego nie psuje.
    """
    con = _con()
    p = zapytania.produkt(con, produkt_id)
    if not p:
        con.close()
        return HTMLResponse('<span class="dowod">nie ma takiego produktu</span>')
    eksport_panelu.zglos_produkt(con, produkt_id, powod or "zweryfikowany ręcznie")
    ile = len(p["atrybuty_surowe"])
    con.close()
    return HTMLResponse(
        f'<span class="zrobione">✓ w kolejce do importu ({ile} atrybutów)</span>')


@app.post("/zglos-produkt/cofnij", response_class=HTMLResponse)
def cofnij_zgloszenie_produktu(produkt_id: str = Form(...)):
    con = _con()
    eksport_panelu.cofnij_zgloszenie(con, produkt_id)
    con.close()
    return HTMLResponse('<span class="dowod">wycofane z kolejki importu</span>')


@app.get("/eksport/partie", response_class=HTMLResponse)
def strona_partii(request: Request, komunikat: str = "", blad: str = ""):
    con = _con()
    plan = eksport_panelu.zaplanuj(con, limit_produktow=10**6)   # tylko podgląd
    kontekst = {
        "request": request,
        "partie": eksport_panelu.partie(con),
        "stat": zapytania.statystyki_decyzji(con),
        "plan": plan,
        "zgloszonych": eksport_panelu.czeka_zgloszonych(con),
        "wzorzec": panel_format.wczytaj_wzorzec(),
        "slownik_ile": sum(len(v) for v in panel_format.wczytaj_slownik().values()),
        "duplikaty": panel_format.duplikaty(),
        "komunikat": komunikat, "blad": blad,
    }
    con.close()
    return szablony.TemplateResponse(request, "eksport.html", kontekst)


@app.post("/eksport/partie")
def zrob_partie(rozmiar: int = Form(50), uwagi: str = Form("")):
    con = _con()
    try:
        wynik = eksport_panelu.zapisz_partie(con, KATALOG_PARTII,
                                             limit_produktow=max(1, rozmiar), uwagi=uwagi)
    except ValueError as e:
        con.close()
        return RedirectResponse(f"/eksport/partie?blad={quote(str(e))}", status_code=303)
    con.close()
    if not wynik["ile"]:
        return RedirectResponse(
            "/eksport/partie?blad=" + quote("Nic do wyeksportowania."), status_code=303)
    tresc = (f"Partia {wynik['partia_id']}: {wynik['ile']} produktów, "
             f"{wynik['zmian']} zmian.")
    return RedirectResponse(f"/eksport/partie?komunikat={quote(tresc)}", status_code=303)


@app.get("/eksport/partie/{partia_id}/plik")
def pobierz_partie(partia_id: int, cofnij: str = ""):
    con = _con()
    r = con.execute("SELECT plik FROM partie WHERE id=?", (partia_id,)).fetchone()
    con.close()
    if not r or not r["plik"]:
        return HTMLResponse("Nie znaleziono", status_code=404)
    sciezka = Path(r["plik"])
    if cofnij == "1":
        sciezka = sciezka.with_name(sciezka.stem + "_cofnij.xlsx")
    if not sciezka.exists():
        return HTMLResponse("Plik zniknął z dysku", status_code=404)
    return FileResponse(sciezka, filename=sciezka.name, media_type=
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.post("/eksport/partie/{partia_id}/wycofaj")
def wycofaj_partie(partia_id: int):
    con = _con()
    ile = eksport_panelu.wycofaj(con, partia_id)
    con.close()
    return RedirectResponse(
        "/eksport/partie?komunikat=" + quote(
            f"Partia {partia_id} wycofana — {ile} decyzji wraca do kolejki eksportu."),
        status_code=303)


@app.get("/weryfikacja", response_class=HTMLResponse)
def strona_weryfikacji(request: Request, partia: int = 0, stan: str = ""):
    """Czy to, co wysłaliśmy, faktycznie weszło do sklepu."""
    con = _con()
    kontekst = {
        "request": request,
        "stat": weryfikacja_mod.podsumowanie(con),
        "partie": weryfikacja_mod.wg_partii(con),
        "szczegoly": weryfikacja_mod.szczegoly(con, partia or None, stan),
        "opisy": weryfikacja_mod.OPISY,
        "wybrana": partia, "stan": stan,
        "ostatni": db.ostatni_przebieg(con),
    }
    con.close()
    return szablony.TemplateResponse(request, "weryfikacja.html", kontekst)


@app.post("/eksport/wzorzec")
async def wgraj_wzorzec(plik: UploadFile = File(...)):
    """Plik z panelu uczy nas formatu i mapowania etykieta → ID."""
    nazwa = plik.filename or "panel.xlsx"
    if not nazwa.lower().endswith((".xlsx", ".xlsm")):
        return RedirectResponse(
            "/eksport/partie?blad=" + quote("To musi być plik .xlsx z panelu."),
            status_code=303)
    katalog = KATALOG.parent / "dane" / "wzorce"
    katalog.mkdir(parents=True, exist_ok=True)
    sciezka = katalog / f"{datetime.now():%Y-%m-%d_%H%M%S}__{Path(nazwa).name}"
    sciezka.write_bytes(await plik.read())
    try:
        if panel_format.czy_plik_slownika(sciezka):
            w = panel_format.naucz_ze_slownika(sciezka)
            tresc = (f"Słownik sklepu wczytany: {w['atrybutow']} atrybutów "
                     f"({w['slownikowych']} słownikowych, {w['wolnych']} wolnych), "
                     f"{w['wartosci']} wartości. Wyłączonych atrybutów: {w['wylaczonych']}.")
        else:
            w = panel_format.naucz_z_pliku(sciezka)
            tresc = (f"Wzorzec zapisany: {w['kolumny']} kolumn, {w['produktow']} produktów. "
                     f"Słownik ID: +{w['nowych_wartosci']} nowych, "
                     f"{w['wartosci_razem']} wartości razem.")
    except Exception as e:  # noqa: BLE001 — komunikat ma trafić do użytkownika
        return RedirectResponse(
            "/eksport/partie?blad=" + quote(f"Nie udało się odczytać pliku: {e}"),
            status_code=303)
    return RedirectResponse("/eksport/partie?komunikat=" + quote(tresc), status_code=303)
