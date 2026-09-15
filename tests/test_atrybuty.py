"""Testy detektorów i normalizacji.

Nacisk na te miejsca, gdzie łatwo o fałszywy alarm — bo to one decydują,
czy zespół zaufa kolejce, czy zacznie ją ignorować.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from atrybuty import detektory, kategorie, normalizacja, tekst  # noqa: E402
from atrybuty.model import Produkt  # noqa: E402


# --- parser i normalizacja ------------------------------------------------

def test_parser_atrybutow():
    d = normalizacja.parsuj_atrybuty("Szerokość: 60 | Waga: 36 | Styl: klasyczny")
    assert d == {"Szerokość": "60", "Waga": "36", "Styl": "klasyczny"}


def test_parser_ignoruje_kawalki_bez_dwukropka():
    assert normalizacja.parsuj_atrybuty("Szerokość: 60 | smiec | Waga: 36") == {
        "Szerokość": "60", "Waga": "36"}


def test_liczba_przecinek_dziesietny():
    assert tekst.do_liczby("46,5") == 46.5
    assert tekst.do_liczby("120 cm") == 120.0


def test_liczba_zdublowana_nie_jest_liczba():
    # "46, 46" to błąd formatu, nie liczba — nie wolno tego po cichu zgadnąć
    assert tekst.do_liczby("46, 46") is None


def test_waga_zdublowana_daje_propozycje():
    _, liczby, f = normalizacja.normalizuj_produkt("1", {"Waga": "46, 46"})
    assert liczby["Waga"] == 46.0
    assert f[0].regula_id == "L1-FORMAT-DUBEL"
    assert f[0].proponowana_wartosc == "46"


def test_waga_rozne_wartosci_nie_daje_propozycji():
    _, _, f = normalizacja.normalizuj_produkt("1", {"Waga": "46, 52"})
    assert f[0].regula_id == "L1-FORMAT-ROZNE"
    assert f[0].proponowana_wartosc is None


def test_material_deduplikacja_i_kolejnosc():
    znorm, _, f = normalizacja.normalizuj_produkt("1", {"Materiał": "drewno, drewno"})
    assert znorm["Materiał"] == "drewno"
    assert f[0].regula_id == "L1-LISTA-DUBEL"

    znorm, _, _ = normalizacja.normalizuj_produkt("2", {"Materiał": "metal, płyta meblowa"})
    znorm2, _, _ = normalizacja.normalizuj_produkt("3", {"Materiał": "płyta meblowa, metal"})
    assert znorm["Materiał"] == znorm2["Materiał"]


def test_niespojny_zapis_wartosci():
    znorm, _, f = normalizacja.normalizuj_produkt("1", {"Styl": "Minimalistyczny"})
    assert znorm["Styl"] == "minimalistyczny"
    assert f[0].regula_id == "L1-ZAPIS"


def test_enum_zdublowany():
    znorm, _, f = normalizacja.normalizuj_produkt("1", {"Styl": "nowoczesny, nowoczesny"})
    assert znorm["Styl"] == "nowoczesny"
    assert any(x.regula_id == "L1-ENUM-DUBEL" for x in f)


def test_poprawna_wartosc_nie_daje_findingu():
    _, _, f = normalizacja.normalizuj_produkt("1", {"Styl": "nowoczesny", "Szerokość": "60"})
    assert f == []


# --- ekstrakcja z nazwy ---------------------------------------------------

def test_wymiary_z_nazwy():
    assert tekst.wymiary_z_nazwy("Łóżko Graja 140x70")["a"] == 140.0
    assert tekst.wymiary_z_nazwy("Stół ST-0006 (sr. 80cm)")["srednica"] == 80.0


def test_liczebniki_z_nazwy():
    assert tekst.liczebniki_z_nazwy("Szafa 3-drzwiowa")["drzwi"] == 3
    assert tekst.liczebniki_z_nazwy("Szafka stojąca z szufladą cargo")["szuflady"] == 1
    assert tekst.liczebniki_z_nazwy("Komoda bez drzwi")["drzwi"] == 0


def test_baza_nazwy_laczy_warianty():
    a = tekst.baza_nazwy("Komoda Avola 120x80 biała")
    b = tekst.baza_nazwy("Komoda Avola 120x80 dąb")
    assert a.startswith("komoda avola") and b.startswith("komoda avola")


# --- kategorie ------------------------------------------------------------

def test_kategoria_z_nazwy_omija_przymiotnik():
    assert kategorie.z_nazwy("Nowoczesna szafka RTV do salonu Larona") == "szafka_rtv"


def test_kategoria_ze_sklepu_ma_pierwszenstwo():
    kat, zrodlo = kategorie.przypisz("Komoda Avola", "Szafki Nocne")
    assert (kat, zrodlo) == ("szafka_nocna", "sklep")


def test_kategoria_z_nazwy_gdy_brak_typu():
    kat, zrodlo = kategorie.przypisz("Komoda Avola", None)
    assert (kat, zrodlo) == ("komoda", "nazwa")


# --- detektory ------------------------------------------------------------

def _p(**kw) -> Produkt:
    baza = dict(id="1", nazwa="Test", producent="X", kolekcja="", zdjecie="http://x/1.jpg",
                styl="", kategoria="komoda", atrybuty={}, liczby={})
    baza.update(kw)
    return Produkt(**baza)


def test_sprzecznosc_bez_drzwi():
    p = _p(atrybuty={"Liczba drzwi": "bez drzwi", "Rodzaj drzwi": "uchylne"})
    f = detektory.l1_sprzecznosci(p)
    assert f and f[0].regula_id == "SPR-DRZWI"


def test_brak_sprzecznosci_gdy_drzwi_sa():
    p = _p(atrybuty={"Liczba drzwi": "2-drzwiowe", "Rodzaj drzwi": "uchylne"})
    assert detektory.l1_sprzecznosci(p) == []


def test_relacja_wysokosci():
    p = _p(liczby={"Wysokość do ziemi": 90.0, "Wysokość": 80.0})
    f = detektory.l1_relacje(p)
    assert f and f[0].regula_id == "REL-WYS-ZIEMIA"


def test_relacja_spelniona_nie_zglasza():
    p = _p(liczby={"Wysokość do ziemi": 70.0, "Wysokość": 80.0})
    assert detektory.l1_relacje(p) == []


def test_lozko_z_nazwy_nie_jest_bledem():
    """Łóżko 90x200 o szerokości 108 cm jest POPRAWNE — nazwa opisuje
    powierzchnię spania, atrybut wymiar zewnętrzny. To najczęstszy
    fałszywy alarm, jaki naiwna reguła by wygenerowała."""
    p = _p(nazwa="Łóżko 80265 (90x200)", kategoria="lozko",
           liczby={"Szerokość": 108.0,
                   "Szerokość powierzchni spania": 90.0,
                   "Długość powierzchni spania": 200.0})
    f = detektory.l2_nazwa_vs_atrybuty(p)
    assert not [x for x in f if x.regula_id == "L2-NAZWA-WYMIAR"]


def test_rozjazd_liczby_drzwi():
    p = _p(nazwa="Szafa 3-drzwiowa Kent", atrybuty={"Liczba drzwi": "2-drzwiowe"})
    f = detektory.l2_nazwa_vs_atrybuty(p)
    assert any(x.regula_id == "L2-NAZWA-ROZJAZD" for x in f)


def test_i_wiecej_nie_jest_rozjazdem():
    p = _p(nazwa="Komoda 5-szufladowa", atrybuty={"Liczba szuflad": "4 i więcej"})
    f = detektory.l2_nazwa_vs_atrybuty(p)
    assert not any(x.regula_id == "L2-NAZWA-ROZJAZD" for x in f)


def test_rodzina_wykrywa_odstajacy_material():
    czlonkowie = [
        _p(id=str(i), nazwa="Komoda Avola", producent="BRW", kolekcja="Avola",
           atrybuty={"Materiał": "płyta meblowa"}) for i in range(8)]
    czlonkowie.append(_p(id="99", nazwa="Komoda Avola", producent="BRW",
                         kolekcja="Avola", atrybuty={"Materiał": "drewno"}))
    f = detektory.l2_rodzina(czlonkowie)
    assert [x for x in f if x.produkt_id == "99"]


def test_rodzina_milczy_gdy_wartosci_rozne_po_polowie():
    a = [_p(id=str(i), nazwa="Komoda X", producent="BRW", kolekcja="X",
            atrybuty={"Materiał": "płyta meblowa"}) for i in range(4)]
    b = [_p(id=f"b{i}", nazwa="Komoda X", producent="BRW", kolekcja="X",
            atrybuty={"Materiał": "drewno"}) for i in range(4)]
    assert detektory.l2_rodzina(a + b) == []


def test_grupa_findingu_laczy_identyczne_przypadki():
    _, _, f1 = normalizacja.normalizuj_produkt("1", {"Materiał": "drewno, drewno"})
    _, _, f2 = normalizacja.normalizuj_produkt("2", {"Materiał": "drewno, drewno"})
    assert f1[0].grupa == f2[0].grupa


def test_skala_nie_psuje_wartosci_tuz_za_zakresem(monkeypatch):
    """Fotel 85 kg wystaje ponad p99 (68), ale propozycja '8.5 kg' byłaby
    gorsza niż brak propozycji — ma wyjść zwykły outlier do oceny."""
    from atrybuty import schema_gen
    monkeypatch.setattr(schema_gen, "zakres", lambda k, a: {
        "n": 500, "mediana": 23.0, "mad": 6.0, "p1": 5.3, "p99": 68.0,
        "min_dopuszczalne": 0.0, "max_dopuszczalne": 77.0})
    p = _p(kategoria="fotel", liczby={"Waga": 85.0})
    f = detektory.l2_zakresy(p)
    assert f and f[0].regula_id == "L2-OUTLIER"


def test_skala_lapie_wyrazna_pomylke_jednostki(monkeypatch):
    from atrybuty import schema_gen
    monkeypatch.setattr(schema_gen, "zakres", lambda k, a: {
        "n": 500, "mediana": 40.0, "mad": 6.0, "p1": 28.5, "p99": 56.4,
        "min_dopuszczalne": 27.4, "max_dopuszczalne": 56.4})
    p = _p(kategoria="szafka_nocna", liczby={"Głębokość": 4.3})
    f = detektory.l2_zakresy(p)
    assert f and f[0].regula_id == "L2-SKALA" and f[0].proponowana_wartosc == "43"


# --- kompletność danych ---------------------------------------------------

def test_kompletnosc_pusty():
    from atrybuty.model import oszacuj_kompletnosc
    assert oszacuj_kompletnosc({}) == "pusty"


def test_kompletnosc_szczatkowy():
    from atrybuty.model import oszacuj_kompletnosc
    assert oszacuj_kompletnosc({"Styl": "nowoczesny", "Materiał": "drewno"}) == "szczatkowy"


def test_bez_wymiarow_zostaje_w_analizie():
    """Produkt z siedmioma atrybutami, ale bez wymiarów, ma dość danych,
    żeby reguły miały co sprawdzać — nie wypada z kolejki."""
    from atrybuty.model import Produkt, oszacuj_kompletnosc
    a = {"Styl": "nowoczesny", "Materiał": "drewno", "Waga": "12"}
    assert oszacuj_kompletnosc(a) == "bez_wymiarow"
    assert not Produkt(id="1", nazwa="x", producent="", kolekcja="", zdjecie="",
                       styl="", atrybuty=a, kompletnosc="bez_wymiarow").do_zrodla


def test_kompletnosc_ok():
    from atrybuty.model import oszacuj_kompletnosc
    assert oszacuj_kompletnosc({"Szerokość": "60", "Wysokość": "90",
                                "Materiał": "drewno"}) == "ok"


def test_produkt_bez_danych_nie_generuje_findingow():
    """Produkt bez atrybutów ma trafić na listę braków, a nie zaśmiecać
    kolejkę zgłoszeniami „brak Szerokości”."""
    from atrybuty.model import oszacuj_kompletnosc
    pusty = _p(id="pusty", atrybuty={}, kompletnosc=oszacuj_kompletnosc({}))
    pelny = _p(id="pelny", atrybuty={"Liczba drzwi": "bez drzwi", "Rodzaj drzwi": "uchylne",
                                     "Szerokość": "60"},
               kompletnosc=oszacuj_kompletnosc({"Liczba drzwi": "x", "Rodzaj drzwi": "y",
                                                "Szerokość": "60"}))
    wynik = detektory.uruchom([pusty, pelny])
    assert not [f for f in wynik if f.produkt_id == "pusty"]
    assert [f for f in wynik if f.produkt_id == "pelny"]


def test_findingi_normalizacji_pomijane_dla_pustych():
    from atrybuty.model import Finding
    pusty = _p(id="x", atrybuty={}, kompletnosc="pusty")
    f = Finding("x", "Waga", "L1-NIE-LICZBA", "L1", "krytyczna", 0.9, "abc", None, "test")
    assert detektory.uruchom([pusty], [f]) == []


def test_migracja_dokłada_brakujaca_kolumne(tmp_path):
    """Stara baza (bez kolumny kompletnosc) ma się domigrować, a nie wywalić —
    kasowanie jej kosztowałoby wszystkie zapisane decyzje."""
    import sqlite3
    from atrybuty import db
    sciezka = tmp_path / "stara.db"
    stara = sqlite3.connect(sciezka)
    stara.execute("CREATE TABLE produkty (id TEXT PRIMARY KEY, nazwa TEXT, producent TEXT,"
                  " kolekcja TEXT, zdjecie TEXT, styl TEXT, kategoria TEXT,"
                  " zrodlo_kategorii TEXT, atrybuty TEXT, atrybuty_surowe TEXT, liczby TEXT)")
    stara.execute("INSERT INTO produkty (id, nazwa) VALUES ('1','Komoda')")
    stara.commit(); stara.close()

    con = db.polacz(sciezka)
    kolumny = {r["name"] for r in con.execute("PRAGMA table_info(produkty)")}
    assert "kompletnosc" in kolumny
    # istniejące wiersze przeżywają migrację
    assert con.execute("SELECT nazwa FROM produkty WHERE id='1'").fetchone()[0] == "Komoda"
    con.close()


# --- warstwa wizyjna (L3) -------------------------------------------------

def test_parsowanie_odpowiedzi_gemini():
    from atrybuty import wizja
    surowe = {
        "candidates": [{"content": {"parts": [{"text": json.dumps({
            "werdykt": "niezgodne", "wartosc_ze_zdjecia": "3-szuflady",
            "pewnosc": 0.9, "uzasadnienie": "widoczne trzy fronty szuflad"})}]}}],
        "usageMetadata": {"promptTokenCount": 510, "candidatesTokenCount": 40},
    }
    o = wizja._zparsuj(surowe)
    assert o.werdykt == "niezgodne"
    assert o.wartosc_ze_zdjecia == "3-szuflady"
    assert (o.tokenow_wejscia, o.tokenow_wyjscia) == (510, 40)


def test_nieznany_werdykt_ladzie_jako_nie_widac():
    """Model, który wymyśli własną etykietę, nie może udawać rozstrzygnięcia."""
    from atrybuty import wizja
    surowe = {"candidates": [{"content": {"parts": [{"text": json.dumps({
        "werdykt": "chyba_tak", "wartosc_ze_zdjecia": "", "pewnosc": 0.5,
        "uzasadnienie": ""})}]}}]}
    assert wizja._zparsuj(surowe).werdykt == "nie_widac"


def test_koszt_liczony_wg_cennika():
    from atrybuty import wizja
    # 1M tokenów wejścia Flash = $0.75, 1M wyjścia = $3.75
    assert abs(wizja.koszt_usd(wizja.MODEL_WOLUMEN, 1_000_000, 0) - 0.75) < 1e-9
    assert abs(wizja.koszt_usd(wizja.MODEL_WOLUMEN, 0, 1_000_000) - 3.75) < 1e-9


def test_hasz_cache_rozroznia_pytanie_i_model():
    from atrybuty import wizja
    a = wizja.hasz_zapytania("u", "ile szuflad", "2-szuflady", "flash")
    assert a != wizja.hasz_zapytania("u", "ile drzwi", "2-szuflady", "flash")
    assert a != wizja.hasz_zapytania("u", "ile szuflad", "2-szuflady", "pro")
    assert a == wizja.hasz_zapytania("u", "ile szuflad", "2-szuflady", "flash")


def test_cache_oszczedza_drugie_wywolanie(tmp_path, monkeypatch):
    """Drugi przebieg na tych samych danych nie może zapłacić po raz drugi."""
    from atrybuty import db, wizja
    con = db.polacz(tmp_path / "t.db")
    wizja.przygotuj_baze(con)

    wywolania = {"n": 0}

    def udawany_zapytaj(*a, **k):
        wywolania["n"] += 1
        return wizja.Odpowiedz("niezgodne", "3-szuflady", 0.9, "trzy fronty", 500, 40)

    monkeypatch.setattr(wizja, "zapytaj", udawany_zapytaj)
    monkeypatch.setattr(wizja, "pobierz_zdjecie", lambda *a, **k: b"x")

    poz = [{"produkt_id": "1", "atrybut": "Liczba szuflad", "stara_wartosc": "2-szuflady",
            "zdjecie": "http://x/1.jpg"}]
    w1 = wizja.przetworz(con, poz, echo=lambda *_: None)
    w2 = wizja.przetworz(con, poz, echo=lambda *_: None)

    assert wywolania["n"] == 1
    assert w1["z_cache"] == 0 and w2["z_cache"] == 1
    assert w2["koszt_usd"] == 0.0
    con.close()


def test_blad_nie_przerywa_przebiegu(tmp_path, monkeypatch):
    from atrybuty import db, wizja
    con = db.polacz(tmp_path / "t.db")
    wizja.przygotuj_baze(con)

    def wybuchowy(*a, **k):
        raise RuntimeError("timeout")

    monkeypatch.setattr(wizja, "pobierz_zdjecie", wybuchowy)
    poz = [{"produkt_id": "1", "atrybut": "Liczba drzwi", "stara_wartosc": "bez drzwi",
            "zdjecie": "http://x/1.jpg"},
           {"produkt_id": "2", "atrybut": "Liczba drzwi", "stara_wartosc": "bez drzwi",
            "zdjecie": "http://x/2.jpg"}]
    w = wizja.przetworz(con, poz, echo=lambda *_: None)
    assert w["bledow"] == 2 and w["zapytan"] == 0
    assert con.execute("SELECT COUNT(*) FROM werdykty_wizji WHERE werdykt='blad'"
                       ).fetchone()[0] == 2
    con.close()


def test_pytania_pokrywaja_tylko_atrybuty_widoczne():
    """Pytanie o atrybut spoza WIDOCZNE_NA_ZDJECIU byłoby pieniędzmi w błoto —
    taki finding i tak nie przechodzi bramki kosztowej."""
    from atrybuty import wizja
    from atrybuty.model import WIDOCZNE_NA_ZDJECIU
    assert set(wizja.PYTANIA) <= WIDOCZNE_NA_ZDJECIU


def test_numer_modelu_nie_jest_liczebnikiem():
    """„Materac Space 1000S 90" nie ma tysiąca szuflad — bez limitu ta nazwa
    generowała fałszywy alarm o rozjeździe z atrybutem."""
    assert "szuflady" not in tekst.liczebniki_z_nazwy("Materac Space 1000S 90")
    assert tekst.liczebniki_z_nazwy("Komoda 3-szufladowa")["szuflady"] == 3


# --- weryfikacja na żądanie z kolejki -------------------------------------

def _klient_z_baza(tmp_path, monkeypatch):
    """Aplikacja wpięta w świeżą bazę z jednym produktem i jednym findingiem."""
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt

    baza = tmp_path / "t.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    import atrybuty.app as app_mod
    monkeypatch.setattr(app_mod, "BAZA", baza)

    con = db.polacz(baza)
    wizja.przygotuj_baze(con)
    p = Produkt(id="1", nazwa="Komoda Test", producent="BRW", kolekcja="K",
                zdjecie="http://x/1.jpg", styl="", kategoria="komoda",
                atrybuty={"Liczba szuflad": "2-szuflady", "Szerokość": "100"},
                liczby={"Szerokość": 100.0})
    f = Finding("1", "Liczba szuflad", "L2-NAZWA-ROZJAZD", "L2", "krytyczna", 0.7,
                "2-szuflady", None, "nazwa mówi o 3")
    db.zapisz_przebieg(con, "test.csv", [p], [f])
    con.close()

    from fastapi.testclient import TestClient
    return TestClient(app_mod.app)


def test_sprawdz_zdjeciem_zwraca_werdykt_i_przycisk(tmp_path, monkeypatch):
    from atrybuty import wizja
    monkeypatch.setattr(wizja, "pobierz_zdjecie", lambda *a, **k: b"x")
    monkeypatch.setattr(wizja, "klucz_api", lambda: "udawany")
    monkeypatch.setattr(wizja, "zapytaj", lambda *a, **k: wizja.Odpowiedz(
        "niezgodne", "3-szuflady", 0.92, "widoczne trzy fronty", 508, 40))

    klient = _klient_z_baza(tmp_path, monkeypatch)
    odp = klient.post("/wizja/sprawdz", data={
        "produkt_id": "1", "atrybut": "Liczba szuflad",
        "stara": "2-szuflady", "nr": "1"})
    assert odp.status_code == 200
    assert "niezgodne" in odp.text
    assert "3-szuflady" in odp.text
    assert "Zastosuj" in odp.text          # gotowa poprawka jednym kliknięciem


def test_sprawdz_zdjeciem_bez_klucza_nie_wywala_strony(tmp_path, monkeypatch):
    from atrybuty import wizja

    def brak():
        raise wizja.BrakKlucza("brak klucza")

    monkeypatch.setattr(wizja, "klucz_api", brak)
    klient = _klient_z_baza(tmp_path, monkeypatch)
    odp = klient.post("/wizja/sprawdz", data={
        "produkt_id": "1", "atrybut": "Liczba szuflad", "nr": "1"})
    assert odp.status_code == 200 and "brak klucza" in odp.text


def test_sprawdz_zdjeciem_drugi_raz_idzie_z_cache(tmp_path, monkeypatch):
    """Drugie kliknięcie na tym samym findingu nie może kosztować ponownie."""
    from atrybuty import wizja
    wywolan = {"n": 0}

    def licz(*a, **k):
        wywolan["n"] += 1
        return wizja.Odpowiedz("zgodne", "2-szuflady", 0.9, "dwa fronty", 508, 40)

    monkeypatch.setattr(wizja, "pobierz_zdjecie", lambda *a, **k: b"x")
    monkeypatch.setattr(wizja, "klucz_api", lambda: "udawany")
    monkeypatch.setattr(wizja, "zapytaj", licz)

    klient = _klient_z_baza(tmp_path, monkeypatch)
    dane = {"produkt_id": "1", "atrybut": "Liczba szuflad",
            "stara": "2-szuflady", "nr": "1"}
    klient.post("/wizja/sprawdz", data=dane)
    druga = klient.post("/wizja/sprawdz", data=dane)
    assert wywolan["n"] == 1
    assert "z cache, 0 zł" in druga.text


def test_liczba_mnoga_nie_oznacza_jednej_szuflady():
    """„Komoda z szufladami" nie znaczy „jedna szuflada" — ta pomyłka
    generowała 251 fałszywych alarmów w samym tym atrybucie."""
    mnoga = tekst.liczebniki_z_nazwy("Elegancka komoda z szufladami do salonu")
    assert "szuflady" not in mnoga
    assert mnoga.get("ma_szuflady") == 1

    poj = tekst.liczebniki_z_nazwy("Szafka nocna z szufladą")
    assert poj["szuflady"] == 1


def test_szuflady_w_nazwie_kwestionuja_bez_szuflad():
    p = _p(nazwa="Komoda z szufladami Rainer", atrybuty={"Liczba szuflad": "bez szuflad"})
    f = detektory.l2_nazwa_vs_atrybuty(p)
    assert any(x.regula_id == "L2-NAZWA-ROZJAZD" for x in f)


def test_szuflady_w_nazwie_nie_kwestionuja_konkretnej_liczby():
    p = _p(nazwa="Komoda z szufladami Rainer", atrybuty={"Liczba szuflad": "4 i więcej"})
    assert detektory.l2_nazwa_vs_atrybuty(p) == []


def test_htmx_serwowany_lokalnie_a_nie_z_cdn(tmp_path, monkeypatch):
    """Bez htmx żaden przycisk w kolejce nie działa, a awarii CDN-a nie widać
    aż do kliknięcia — więc plik musi jechać z projektu."""
    from pathlib import Path as P
    szablon = (P(__file__).resolve().parent.parent / "atrybuty" / "templates"
               / "anomalie.html").read_text(encoding="utf-8")
    assert "/static/htmx.min.js" in szablon
    assert "unpkg.com" not in szablon and "cdn" not in szablon.lower().split("<style>")[0]
    assert (P(__file__).resolve().parent.parent / "atrybuty" / "static"
            / "htmx.min.js").exists()


def test_nieudana_proba_nie_blokuje_kolejnej():
    """Werdykt 'blad' musi przywracać przycisk — inaczej jeden timeout
    zamyka drogę do ponownego sprawdzenia."""
    from pathlib import Path as P
    szablon = (P(__file__).resolve().parent.parent / "atrybuty" / "templates"
               / "anomalie.html").read_text(encoding="utf-8")
    assert "w.werdykt_wizji == 'blad'" in szablon


# --- import z przeglądarki ------------------------------------------------

def test_kategoria_z_kolumny_typ(tmp_path):
    """Nowy eksport ma kategorię w kolumnie `typ` — nie może już być
    potrzebny osobny plik z BigQuery."""
    from atrybuty.pipeline import wczytaj_csv
    plik = tmp_path / "p.csv"
    plik.write_text(
        "id;nazwa;producent;kolekcja;typ;podtyp;zdjecie;style;atrybuty\n"
        "1;Komoda X;BRW;K;Szafki Nocne;Nocne małe;http://x/1.jpg;nowoczesny;"
        "Szerokość: 50 | Wysokość: 60 | Materiał: drewno\n",
        encoding="utf-8")
    produkty, _ = wczytaj_csv(plik)
    assert produkty[0].kategoria == "szafka_nocna"
    assert produkty[0].zrodlo_kategorii == "sklep"
    assert produkty[0].podtyp == "Nocne małe"


def test_pusty_typ_wraca_do_nazwy(tmp_path):
    from atrybuty.pipeline import wczytaj_csv
    plik = tmp_path / "p.csv"
    plik.write_text(
        "id;nazwa;producent;kolekcja;typ;podtyp;zdjecie;style;atrybuty\n"
        "1;Komoda Avola;BRW;K;;;http://x/1.jpg;;Szerokość: 50 | Wysokość: 60 | Materiał: drewno\n",
        encoding="utf-8")
    produkty, _ = wczytaj_csv(plik)
    assert (produkty[0].kategoria, produkty[0].zrodlo_kategorii) == ("komoda", "nazwa")


def test_sciezka_wgranego_nie_wypuszcza_poza_katalog():
    """Nazwa pliku z formularza nie może prowadzić poza katalog danych."""
    from atrybuty import importer
    assert importer.sciezka_wgranego("../../etc/passwd") is None
    assert importer.sciezka_wgranego("nie_ma_takiego.csv") is None


def test_zapisz_plik_wymusza_rozszerzenie(tmp_path, monkeypatch):
    from atrybuty import importer
    monkeypatch.setattr(importer, "KATALOG_DANYCH", tmp_path)
    p = importer.zapisz_plik("eksport", b"id;nazwa\n1;X\n")
    assert p.suffix == ".csv" and p.parent == tmp_path and p.read_bytes().startswith(b"id;")


def test_pusta_baza_prowadzi_do_importu(tmp_path, monkeypatch):
    """Na świeżej instalacji `/` i `/anomalie` mają prowadzić do wgrania pliku,
    a nie pokazywać komendy z konsoli."""
    import atrybuty.app as app_mod
    import atrybuty.pipeline as pipeline
    from fastapi.testclient import TestClient

    baza = tmp_path / "pusta.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    klient = TestClient(app_mod.app)

    for sciezka in ("/", "/anomalie"):
        odp = klient.get(sciezka, follow_redirects=False)
        assert odp.status_code in (303, 307) and odp.headers["location"] == "/import"
