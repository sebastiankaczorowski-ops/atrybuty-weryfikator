"""Endpoint weryfikacji ręcznej.

FastAPI + Jinja2 + HTMX — ta sama konwencja co manager-dashboard, więc
przeniesienie na Mac Mini to później tylko Dockerfile.

    uvicorn atrybuty.app:app --reload --port 8083
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (config, db, eksport, importer, kategorie, reguly as reguly_mod,
               wizja, zapytania)
from .model import MIN_ATRYBUTOW, PROG_DO_WIZJI
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
    wizja.przygotuj_baze(con)   # tabele werdyktów istnieją też przed pierwszym L3
    return con


def _przebieg(con) -> int:
    p = db.ostatni_przebieg(con)
    return int(p["id"]) if p else 0


@app.get("/", response_class=HTMLResponse)
def start():
    return RedirectResponse("/anomalie")


@app.get("/anomalie", response_class=HTMLResponse)
def anomalie(request: Request,
             kategoria: str = "", producent: str = "", regula: str = "",
             warstwa: str = "", waga: str = "", atrybut: str = "",
             status: str = "otwarte", routing: str = "", ma_zdjecie: str = "",
             werdykt: str = "", szukaj: str = "", grupuj: str = "1", strona: int = 1):
    con = _con()
    przebieg = _przebieg(con)
    if not przebieg:
        con.close()
        return HTMLResponse("<p style='font-family:sans-serif;padding:2rem'>"
                            "Brak danych — uruchom <code>python -m atrybuty.pipeline "
                            "import dane/products.csv</code></p>")

    fl = zapytania.Filtr(
        kategoria=kategoria, producent=producent, regula=regula, warstwa=warstwa,
        waga=waga, atrybut=atrybut, status=status, routing=routing,
        ma_zdjecie=ma_zdjecie, werdykt=werdykt, szukaj=szukaj, grupuj=(grupuj == "1"),
        limit=50, offset=(max(1, strona) - 1) * 50)

    wiersze = zapytania.lista(con, przebieg, fl)
    ile = zapytania.policz(con, przebieg, fl)
    kontekst = {
        "request": request,
        "wiersze": wiersze,
        "ile": ile,
        "strona": strona,
        "stron": max(1, (ile + 49) // 50),
        "fl": fl,
        "slowniki": zapytania.slowniki_filtrow(con, przebieg),
        "stat": zapytania.statystyki(con, przebieg),
        "nazwy_kat": kategorie.nazwy_kategorii(),
        "przebieg": db.ostatni_przebieg(con),
        "prog": PROG_DO_WIZJI,
        "pytania_wizji": wizja.obslugiwane_atrybuty(),
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
    return szablony.TemplateResponse(request, "produkt.html", {
        "request": request, "p": p, "findingi": findingi,
        "nazwy_kat": kategorie.nazwy_kategorii()})


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
