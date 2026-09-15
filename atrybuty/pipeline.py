"""Potok: CSV -> normalizacja -> detektory -> SQLite.

Uruchomienie:
    python -m atrybuty.pipeline import dane/products.csv
    python -m atrybuty.pipeline schema dane/products.csv   # regeneruje config/schema.yaml
    python -m atrybuty.pipeline raport
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import Counter
from pathlib import Path

from . import config, db, detektory, kategorie, normalizacja, schema_gen, wizja, zrodla
from .model import Finding, Produkt, oszacuj_kompletnosc

csv.field_size_limit(10_000_000)

def _sciezka_bazy() -> Path:
    """Gdzie trzymamy SQLite.

    Domyślnie `dane/atrybuty.db` obok projektu. Zmienna ATRYBUTY_DB pozwala
    to przenieść — i jest konieczna, gdy projekt leży na dysku sieciowym albo
    na montowanym katalogu (np. folder udostępniony do Cowork): SQLite
    wymaga blokad plikowych, których takie systemy plików nie dają, i wywala
    się na "disk I/O error".
    """
    z_env = os.environ.get("ATRYBUTY_DB")
    if z_env:
        return Path(z_env).expanduser()
    return Path(__file__).resolve().parent.parent / "dane" / "atrybuty.db"


BAZA = _sciezka_bazy()

# Nazwy kolumn, pod którymi może przyjść kategoria. Eksport z 15.09.2026
# ma ją wprost jako `typ` (+ `podtyp`), starsze pliki wymagały osobnego
# eksportu z BigQuery — obie drogi zostają.
KOLUMNY_KATEGORII = ("typ", "kategoria", "kategorie", "category", "kategoria_glowna")
KOLUMNY_PODTYPU = ("podtyp", "subtype")


def wczytaj_kategorie(sciezka: str | Path) -> dict[str, dict]:
    """Eksport kategorii z BigQuery: short_id;name;type;subtype;...

    Zwraca {id: {"type": ..., "subtype": ..., "manufacturer": ...}}.
    Separator wykrywamy sam — BigQuery daje przecinki, eksport sklepu średniki.
    """
    out: dict[str, dict] = {}
    with open(sciezka, encoding="utf-8-sig", newline="") as f:
        probka = f.read(4096)
        f.seek(0)
        sep = ";" if probka.count(";") > probka.count(",") else ","
        for w in csv.DictReader(f, delimiter=sep):
            pid = (w.get("short_id") or w.get("id") or "").strip()
            if pid:
                out[pid] = {k: (v or "").strip() for k, v in w.items()}
    return out


def wczytaj_csv(sciezka: str | Path, plik_kategorii: str | Path | None = None
                ) -> tuple[list[Produkt], list[Finding]]:
    produkty: list[Produkt] = []
    findingi: list[Finding] = []
    mapa_kat = wczytaj_kategorie(plik_kategorii) if plik_kategorii else {}

    with open(sciezka, encoding="utf-8-sig", newline="") as f:
        czytnik = csv.DictReader(f, delimiter=";")
        pola = czytnik.fieldnames or []
        kol_kat = next((k for k in pola if k.lower() in KOLUMNY_KATEGORII), None)
        kol_podtyp = next((k for k in pola if k.lower() in KOLUMNY_PODTYPU), None)

        for wiersz in czytnik:
            surowe = normalizacja.parsuj_atrybuty(wiersz.get("atrybuty", ""))
            pid = (wiersz.get("id") or "").strip()
            if not pid:
                continue
            znorm, liczby, f_norm = normalizacja.normalizuj_produkt(pid, surowe)
            ze_sklepu = None
            podtyp = (wiersz.get(kol_podtyp) or "").strip() if kol_podtyp else ""
            if kol_kat and (wiersz.get(kol_kat) or "").strip():
                ze_sklepu = wiersz[kol_kat].strip()
            elif pid in mapa_kat:
                ze_sklepu = mapa_kat[pid].get("type") or None
                podtyp = podtyp or mapa_kat[pid].get("subtype", "")
            kat, zrodlo = kategorie.przypisz(wiersz.get("nazwa", ""), ze_sklepu)
            if kat == kategorie.NIEZNANA and zrodlo != "nazwa":
                # typ sklepu nie ma odpowiednika w mapie — ratujemy się nazwą,
                # ale zapamiętujemy, że mapa wymaga uzupełnienia
                kat = kategorie.z_nazwy(wiersz.get("nazwa", ""))

            produkty.append(Produkt(
                id=pid,
                nazwa=(wiersz.get("nazwa") or "").strip(),
                producent=(wiersz.get("producent") or "").strip(),
                kolekcja=(wiersz.get("kolekcja") or "").strip(),
                zdjecie=(wiersz.get("zdjecie") or "").strip(),
                styl=(wiersz.get("style") or "").strip(),
                kategoria=kat, zrodlo_kategorii=zrodlo, podtyp=podtyp,
                atrybuty=znorm, atrybuty_surowe=surowe, liczby=liczby,
                kompletnosc=oszacuj_kompletnosc(znorm)))
            findingi += f_norm

    return produkty, findingi


def komenda_schema(sciezka: str, plik_kategorii: str | None = None) -> None:
    produkty, _ = wczytaj_csv(sciezka, plik_kategorii)
    dane = schema_gen.zbuduj(produkty)
    plik = config.zapisz_schema(dane)
    print(f"Zapisano {plik}")
    print(f"  kategorie ze statystykami: {len(dane['kategorie'])}")
    print(f"  grupy nadrzędne: {len(dane['grupy'])}")


def komenda_import(sciezka: str, plik_kategorii: str | None = None) -> None:
    produkty, f_norm = wczytaj_csv(sciezka, plik_kategorii)
    print(f"Wczytano {len(produkty)} produktów")

    if not config.schema():
        print("Brak config/schema.yaml — generuję z tych danych…")
        config.zapisz_schema(schema_gen.zbuduj(produkty))

    findingi = detektory.uruchom(produkty, f_norm)
    print(f"Findingów: {len(findingi)}")

    BAZA.parent.mkdir(parents=True, exist_ok=True)
    con = db.polacz(BAZA)
    przebieg = db.zapisz_przebieg(con, str(sciezka), produkty, findingi)
    # L4 dopiero teraz: dopasowanie do feedów potrzebuje produktów w bazie
    l4 = zrodla.dopisz_findingi_l4(con, przebieg)
    con.close()
    print(f"Zapisano przebieg #{przebieg} do {BAZA}")
    if l4:
        print(f"Findingów z feedów producentów (L4): {l4}")
    _podsumowanie(produkty, findingi)


def _podsumowanie(produkty: list[Produkt], findingi: list[Finding]) -> None:
    from .model import PROG_DO_WIZJI, WIDOCZNE_NA_ZDJECIU

    print("\nKategorie (top 15):")
    for kat, n in Counter(p.kategoria for p in produkty).most_common(15):
        print(f"  {n:6d}  {kategorie.nazwy_kategorii().get(kat, kat)}")
    nieznane = sum(1 for p in produkty if p.kategoria == "nieznana")
    print(f"  nieprzypisane: {nieznane} ({nieznane / max(1, len(produkty)):.1%})")
    zrodla_kat = Counter(p.zrodlo_kategorii for p in produkty)
    print("  źródło kategorii: " + ", ".join(f"{k}={v}" for k, v in zrodla_kat.most_common()))

    kompl = Counter(p.kompletnosc for p in produkty)
    print("\nKompletność danych:")
    print(f"  {kompl.get('ok', 0):6d}  produkty z kompletem podstaw — analizowane")
    print(f"  {kompl.get('bez_wymiarow', 0):6d}  bez wymiarów, ale z resztą danych — analizowane dalej")
    print(f"  {kompl.get('szczatkowy', 0):6d}  szczątkowe (mniej niż 3 atrybuty) — wyłączone z analizy")
    print(f"  {kompl.get('pusty', 0):6d}  bez żadnych atrybutów — wyłączone z analizy")
    print(f"         → {kompl.get('szczatkowy', 0) + kompl.get('pusty', 0)} produktów "
          f"do ponownego zaciągnięcia ze źródła (podstrona /braki)")

    print("\nFindingi wg reguły:")
    for reg, n in Counter(f.regula_id for f in findingi).most_common(30):
        print(f"  {n:6d}  {reg}")

    print("\nBramka kosztowa:")
    zdjecia = {p.id: p.ma_zdjecie for p in produkty}
    auto = [f for f in findingi if f.pewnosc >= PROG_DO_WIZJI and f.proponowana_wartosc]
    do_wizji = [f for f in findingi
                if f.pewnosc < PROG_DO_WIZJI
                and f.atrybut in WIDOCZNE_NA_ZDJECIU
                and zdjecia.get(f.produkt_id)]
    reszta = len(findingi) - len(auto) - len(do_wizji)
    print(f"  {len(auto):6d}  gotowe do jednego kliknięcia (0 zł)")
    print(f"  {len(do_wizji):6d}  kandydaci do Gemini (L3)")
    print(f"  {reszta:6d}  do oceny człowieka / L4")
    print(f"\n  grup decyzyjnych: {len({f.grupa for f in findingi})} "
          f"(zamiast {len(findingi)} pojedynczych kliknięć)")


def komenda_wizja(limit: int | None, atrybut: str, producent: str, model: str,
                  na_sucho: bool, losowo: bool, wszystko: bool) -> None:
    """Warstwa L3 — Gemini na kandydatach przepuszczonych przez bramkę kosztową."""
    con = db.polacz(BAZA)
    wizja.przygotuj_baze(con)
    p = db.ostatni_przebieg(con)
    if not p:
        print("Brak przebiegów — uruchom najpierw `import`.")
        return

    poz = wizja.kandydaci(con, int(p["id"]), limit=limit, atrybut=atrybut,
                          producent=producent, tylko_nowe=not wszystko, losowo=losowo)
    print(f"Kandydatów do sprawdzenia: {len(poz)}")
    if not poz:
        con.close()
        return

    if na_sucho:
        w = wizja.przetworz(con, poz, model=model, na_sucho=True)
        print(f"  szacunek: {w['zapytan']} zapytań, ~{w['tok_we']:,} tok. wejścia, "
              f"~{w['tok_wy']:,} wyjścia → ~${w['koszt_usd']:.2f}")
        con.close()
        return

    try:
        wizja.klucz_api()
    except wizja.BrakKlucza as e:
        print(e)
        con.close()
        return

    w = wizja.przetworz(con, poz, model=model)
    print(f"\nZapytań: {w['zapytan']} (z cache: {w['z_cache']}, błędów: {w['bledow']})")
    for k, n in sorted(w["werdykty"].items(), key=lambda x: -x[1]):
        print(f"  {n:5d}  {k}")
    print(f"Tokeny: {w['tok_we']:,} wejścia / {w['tok_wy']:,} wyjścia "
          f"→ ${w['koszt_usd']:.3f}")
    con.close()


def komenda_kalibracja(akcja: str, plik: str | None) -> None:
    con = db.polacz(BAZA)
    wizja.przygotuj_baze(con)
    katalog = BAZA.parent / "kalibracja"
    if akcja == "eksport":
        sciezka = Path(plik) if plik else katalog / "kalibracja.csv"
        ile = wizja.eksport_kalibracji(con, sciezka)
        print(f"Zapisano {ile} werdyktów do {sciezka}")
        print("Wypełnij kolumnę TWOJA_OCENA: trafny / nietrafny / niejasny, "
              "potem `kalibracja raport`.")
    else:
        sciezka = Path(plik) if plik else katalog / "kalibracja.csv"
        if not sciezka.exists():
            print(f"Nie ma {sciezka} — najpierw `kalibracja eksport`.")
            return
        r = wizja.raport_kalibracji(sciezka)
        o = r["ogolem"]
        print(f"Ocenionych: {o['trafny'] + o['nietrafny'] + o['niejasny']} "
              f"(bez oceny: {o['bez_oceny']})")
        if r["trafnosc"] is not None:
            print(f"Trafność ogółem: {r['trafnosc']:.0%}  "
                  f"({o['trafny']} trafnych / {o['nietrafny']} nietrafnych)")
        print("\nPer atrybut:")
        for k, v in r["per_atrybut"].items():
            t = f"{v['trafnosc']:.0%}" if v["trafnosc"] is not None else "—"
            print(f"  {v['n']:5d}  {k:22s} {t}")
        print("\nPer werdykt:")
        for k, v in r["per_werdykt"].items():
            t = f"{v['trafnosc']:.0%}" if v["trafnosc"] is not None else "—"
            print(f"  {v['n']:5d}  {k:12s} {t}")
    con.close()


def komenda_raport() -> None:
    con = db.polacz(BAZA)
    p = db.ostatni_przebieg(con)
    if not p:
        print("Brak przebiegów — uruchom najpierw `import`.")
        return
    print(f"Przebieg #{p['id']} z {p['utworzono']}: {p['liczba_produktow']} produktów, "
          f"{p['liczba_findingow']} findingów, plik {p['plik']}")
    for w in con.execute(
            "SELECT regula_id, waga, COUNT(*) n FROM findingi WHERE przebieg_id=? "
            "GROUP BY regula_id, waga ORDER BY n DESC", (p["id"],)):
        print(f"  {w['n']:6d}  {w['regula_id']:24s} {w['waga']}")
    con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="atrybuty")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import", help="wczytaj CSV, uruchom detektory, zapisz do bazy")
    a.add_argument("plik")
    a.add_argument("--kategorie", default=None, help="CSV z kategoriami (short_id,type,subtype)")
    b = sub.add_parser("schema", help="wygeneruj config/schema.yaml z danych")
    b.add_argument("plik")
    b.add_argument("--kategorie", default=None)
    sub.add_parser("raport", help="podsumowanie ostatniego przebiegu")

    w = sub.add_parser("wizja", help="warstwa L3 — weryfikacja po zdjęciu (Gemini)")
    w.add_argument("--limit", type=int, default=None, help="ile zapytań maksymalnie")
    w.add_argument("--atrybut", default="", help="tylko ten atrybut")
    w.add_argument("--producent", default="", help="tylko ten producent")
    w.add_argument("--model", default=wizja.MODEL_WOLUMEN)
    w.add_argument("--sporne", action="store_true",
                   help=f"użyj modelu do spornych ({wizja.MODEL_SPORNE})")
    w.add_argument("--na-sucho", action="store_true",
                   help="policz koszt bez ani jednego wywołania API")
    w.add_argument("--losowo", action="store_true", help="losowa kolejność (do próbki)")
    w.add_argument("--wszystko", action="store_true",
                   help="także te, które mają już werdykt")

    k = sub.add_parser("kalibracja", help="próbka do ręcznej oceny i raport trafności")
    k.add_argument("akcja", choices=["eksport", "raport"])
    k.add_argument("--plik", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "import":
        komenda_import(args.plik, args.kategorie)
    elif args.cmd == "schema":
        komenda_schema(args.plik, args.kategorie)
    elif args.cmd == "wizja":
        model = wizja.MODEL_SPORNE if args.sporne else args.model
        komenda_wizja(args.limit, args.atrybut, args.producent, model,
                      args.na_sucho, args.losowo, args.wszystko)
    elif args.cmd == "kalibracja":
        komenda_kalibracja(args.akcja, args.plik)
    else:
        komenda_raport()
    return 0


if __name__ == "__main__":
    sys.exit(main())
