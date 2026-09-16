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


# --- źródła producenckie (L4) ---------------------------------------------

FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<offers>
  <offer id="26">
    <name><![CDATA[Rimini RI01 Kredens]]></name>
    <collection><![CDATA[Rimini]]></collection>
    <sku><![CDATA[RI01]]></sku>
    <attrs>
      <attr name="Szerokość (cm)"><![CDATA[154]]></attr>
      <attr name="Wysokość (cm)"><![CDATA[91]]></attr>
      <attr name="Waga (kg)"><![CDATA[70]]></attr>
    </attrs>
    <imges><imge>a.jpg</imge><imge>b.jpg</imge></imges>
  </offer>
  <offer id="27">
    <name><![CDATA[Rimini RI02 Regał]]></name>
    <collection><![CDATA[Rimini]]></collection>
    <sku><![CDATA[RI02]]></sku>
    <attrs>
      <attr name="Szerokość (cm)"><![CDATA[90]]></attr>
      <attr name="Wysokość (cm)"><![CDATA[179]]></attr>
      <attr name="Waga (kg)"><![CDATA[23]]></attr>
    </attrs>
  </offer>
</offers>"""


def test_rekord_to_najplytszy_powtarzajacy_sie_tag():
    """W tym feedzie <attr> występuje częściej niż <offer>, ale produktem
    jest <offer> — wybór „najczęstszego” dawał 10 126 atrybutów zamiast
    560 produktów."""
    from atrybuty import zrodla
    rek, tag = zrodla.rekordy_xml(FEED_XML.encode())
    assert tag == "offer" and len(rek) == 2


def test_pary_nazwa_wartosc_staja_sie_polami():
    """<attr name="Szerokość (cm)">154</attr> ma dać pole o tej nazwie,
    a nie bezużyteczne attrs.attr[1]."""
    from atrybuty import zrodla
    rek, _ = zrodla.rekordy_xml(FEED_XML.encode())
    assert rek[0]["attrs.attr:Szerokość (cm)"] == "154"
    assert rek[0]["sku"] == "RI01"
    assert rek[0]["imges.imge"] == "a.jpg" and rek[0]["imges.imge[2]"] == "b.jpg"


def test_zgadywanie_mapowania_woli_sku_nad_id():
    from atrybuty import zrodla
    rek, _ = zrodla.rekordy_xml(FEED_XML.encode())
    m = zrodla.zgadnij_mapowanie(zrodla.opisz_pola(rek))
    assert m["klucz"] == "sku"
    assert m["Szerokość"] == "attrs.attr:Szerokość (cm)"


def test_nazwa_do_porownania_wycina_kod_i_kolekcje():
    from atrybuty import zrodla
    assert zrodla._nazwa_do_porownania("Rimini RI01 Kredens", "Rimini") == "kredens"
    assert zrodla._nazwa_do_porownania("Kredens Rimini", "Rimini") == "kredens"


def _zrodlo_testowe(tmp_path, monkeypatch, produkty):
    from atrybuty import db, zrodla
    plik = tmp_path / "feed.xml"
    plik.write_text(FEED_XML, encoding="utf-8")
    con = db.polacz(tmp_path / "t.db")
    zrodla.przygotuj_baze(con)
    con.executemany(
        "INSERT INTO produkty (id,nazwa,producent,kolekcja,kompletnosc,atrybuty,liczby)"
        " VALUES (?,?,?,?,'ok',?,?)", produkty)
    con.commit()
    zid = zrodla.dodaj_zrodlo(con, "Test feed", "Livin Hill", plik="feed.xml")
    zrodla.zapisz_mapowanie(con, zid, {
        "klucz": "sku", "nazwa": "name", "kolekcja": "collection",
        "Szerokość": "attrs.attr:Szerokość (cm)", "Waga": "attrs.attr:Waga (kg)"})
    zrodla.odswiez(con, zid, tmp_path)
    return con


def test_dopasowanie_po_nazwie_gdy_kod_nie_pasuje(tmp_path, monkeypatch):
    """Nasze „Kredens Rimini” i feedowe „Rimini RI01 Kredens” to ten sam mebel,
    choć nasza nazwa nie zawiera kodu producenta."""
    from atrybuty import zrodla
    con = _zrodlo_testowe(tmp_path, monkeypatch, [
        ("1", "Kredens Rimini", "Livin Hill", "Rimini", '{"Szerokość":"140"}',
         '{"Szerokość":140.0}')])
    dop = zrodla.dopasuj(con)
    assert dop["1"]["sposob"] == "nazwa"
    assert dop["1"]["dane"]["Szerokość"] == "154"
    con.close()


def test_rozjazd_wymiaru_daje_finding(tmp_path, monkeypatch):
    from atrybuty import zrodla
    con = _zrodlo_testowe(tmp_path, monkeypatch, [
        ("1", "Kredens Rimini", "Livin Hill", "Rimini", '{"Szerokość":"140"}',
         '{"Szerokość":140.0}')])
    con.execute("INSERT INTO przebiegi (id,plik,utworzono,liczba_produktow,"
                "liczba_findingow) VALUES (1,'x','2026-09-15',1,0)")
    con.commit()
    assert zrodla.dopisz_findingi_l4(con, 1) >= 1
    r = con.execute("SELECT * FROM findingi WHERE regula_id='L4-ROZJAZD'").fetchone()
    assert r["proponowana_wartosc"] == "154" and r["stara_wartosc"] == "140"
    # dowód musi pokazywać, z CZYM porównaliśmy — inaczej nie da się odróżnić
    # błędu w danych od pomyłki dopasowania
    assert "Rimini RI01 Kredens" in r["dowod"]
    con.close()


def test_zgodny_wymiar_nie_daje_findingu(tmp_path, monkeypatch):
    from atrybuty import zrodla
    con = _zrodlo_testowe(tmp_path, monkeypatch, [
        ("1", "Kredens Rimini", "Livin Hill", "Rimini", '{"Szerokość":"154"}',
         '{"Szerokość":154.0}')])
    con.execute("INSERT INTO przebiegi (id,plik,utworzono,liczba_produktow,"
                "liczba_findingow) VALUES (1,'x','2026-09-15',1,0)")
    con.commit()
    zrodla.dopisz_findingi_l4(con, 1)
    assert con.execute("SELECT COUNT(*) FROM findingi WHERE atrybut='Szerokość'"
                       ).fetchone()[0] == 0
    con.close()


def test_dwa_podobne_meble_zostaja_bez_dopasowania(tmp_path, monkeypatch):
    """Gdy w kolekcji są dwie pozycje pasujące tak samo dobrze, nie zgadujemy."""
    from atrybuty import db, zrodla
    feed = FEED_XML.replace("Rimini RI02 Regał", "Rimini RI02 Kredens")
    plik = tmp_path / "feed.xml"
    plik.write_text(feed, encoding="utf-8")
    con = db.polacz(tmp_path / "t.db")
    zrodla.przygotuj_baze(con)
    con.execute("INSERT INTO produkty (id,nazwa,producent,kolekcja,kompletnosc,"
                "atrybuty,liczby) VALUES ('1','Kredens Rimini','Livin Hill','Rimini',"
                "'ok','{}','{}')")
    con.commit()
    zid = zrodla.dodaj_zrodlo(con, "Test", "Livin Hill", plik="feed.xml")
    zrodla.zapisz_mapowanie(con, zid, {"klucz": "sku", "nazwa": "name",
                                       "kolekcja": "collection"})
    zrodla.odswiez(con, zid, tmp_path)
    assert "1" not in zrodla.dopasuj(con)
    con.close()


def test_dopasowanie_po_nazwie_ma_nizsza_pewnosc():
    from atrybuty import zrodla
    assert zrodla._pewnosc({"sposob": "kod"}, 0.82) == 0.82
    assert zrodla._pewnosc({"sposob": "nazwa"}, 0.82) < 0.82


# --- podgląd grupy „te same problemy" -------------------------------------

def _klient_z_grupa(tmp_path, monkeypatch):
    """Trzy produkty z tym samym findingiem — jeden klucz grupy."""
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt

    baza = tmp_path / "g.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    import atrybuty.app as app_mod
    monkeypatch.setattr(app_mod, "BAZA", baza)

    con = db.polacz(baza)
    wizja.przygotuj_baze(con)
    produkty, findingi = [], []
    for i in (1, 2, 3):
        produkty.append(Produkt(
            id=str(i), nazwa=f"Komoda {i}", producent="BRW", kolekcja="K",
            zdjecie="", styl="", kategoria="komoda",
            atrybuty={"Materiał": "plyta"}))
        findingi.append(Finding(str(i), "Materiał", "L1-SLOWNIK", "L1", "srednia",
                                0.9, "plyta", "Płyta meblowa", "poza słownikiem",
                                grupa="L1-SLOWNIK|Materiał|plyta"))
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    con.close()

    from fastapi.testclient import TestClient
    return TestClient(app_mod.app)


def test_podglad_grupy_pokazuje_pozostale_produkty(tmp_path, monkeypatch):
    klient = _klient_z_grupa(tmp_path, monkeypatch)
    odp = klient.get("/grupa", params={"grupa": "L1-SLOWNIK|Materiał|plyta", "nr": "1"})
    assert odp.status_code == 200
    for i in (1, 2, 3):
        assert f"Komoda {i}" in odp.text
    assert "3</b> otwartych" in odp.text


def test_podglad_grupy_pomija_rozstrzygniete(tmp_path, monkeypatch):
    from atrybuty import db
    import atrybuty.app as app_mod

    klient = _klient_z_grupa(tmp_path, monkeypatch)
    con = db.polacz(app_mod.BAZA)
    db.zapisz_decyzje(con, "2", "Materiał", "plyta", "falszywy_alarm", None, None)
    con.close()

    odp = klient.get("/grupa", params={"grupa": "L1-SLOWNIK|Materiał|plyta"})
    assert "Komoda 2" not in odp.text and "Komoda 3" in odp.text


def test_zwiniecie_grupy_zwraca_pusto(tmp_path, monkeypatch):
    klient = _klient_z_grupa(tmp_path, monkeypatch)
    assert klient.get("/grupa", params={"grupa": ""}).text == ""


def test_kolejka_linkuje_do_podgladu_grupy(tmp_path, monkeypatch):
    klient = _klient_z_grupa(tmp_path, monkeypatch)
    odp = klient.get("/anomalie")
    assert "identycznych" in odp.text and "hx-get=\"/grupa?grupa=" in odp.text


# --- format panelu i eksport partiami -------------------------------------

def _plik_panelu(tmp_path, wiersze_danych, naglowki=None):
    """Minimalny plik w układzie eksportu z panelu (nagłówki w wierszu 6)."""
    import openpyxl
    naglowki = naglowki or ["ID", "Kod", "Kod producenta", "Nazwa", "Szerokość", "Materiał"]
    wb = openpyxl.Workbook()
    ws = wb.active
    for _ in range(4):
        ws.append([])
    ws.append(["Export date:", None, "2026-09-16", "Items: ", len(wiersze_danych)])
    ws.append(naglowki)
    for w in wiersze_danych:
        ws.append(w)
    sciezka = tmp_path / "panel.xlsx"
    wb.save(sciezka)
    return sciezka


def _panel_w_tmp(tmp_path, monkeypatch):
    from atrybuty import panel_format as pf
    monkeypatch.setattr(pf, "PLIK_SLOWNIKA", tmp_path / "slownik.yaml")
    monkeypatch.setattr(pf, "PLIK_WZORCA", tmp_path / "wzorzec.yaml")
    return pf


def test_nauka_z_panelu_rozpoznaje_kolumny_slownikowe(tmp_path, monkeypatch):
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    plik = _plik_panelu(tmp_path, [
        [101, "A1", "A1", "Komoda", 100, "2022|tapicerowane"],
        [102, "A2", "A2", "Szafka", 80, "2104|drewno"]])
    w = pf.naucz_z_pliku(plik)
    assert "Materiał" in w["kolumny_slownikowe"]
    assert "Szerokość" in w["kolumny_surowe"]
    assert pf.id_dla(pf.wczytaj_slownik(), "Materiał", "drewno")[0] == "2104|drewno"


def test_nieznana_kolumna_nie_wychodzi_jako_gola_etykieta(tmp_path, monkeypatch):
    """Najgroźniejszy przypadek: kolumna, której nigdy nie widzieliśmy.

    Wpisanie do niej gołej etykiety zakłada, że panel oczekuje tam tekstu —
    a gdy to kolumna słownikowa, w sklepie powstaje śmieciowa wartość."""
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[101, "A1", "A1", "Komoda", 100, "2022|tapicerowane"]]))
    s, wz = pf.wczytaj_slownik(), pf.wczytaj_wzorzec()
    wartosc, powod = pf.wartosc_do_pliku(s, "Rodzaj frontu", "pełny",
                                         set(s), set(wz.surowe))
    assert wartosc is None and "panelu" in powod


def test_niejednoznaczne_id_nie_jest_zgadywane(tmp_path, monkeypatch):
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [
        [101, "A1", "A1", "Fotel", 80, "101|tapicerowane"],
        [102, "A2", "A2", "Sofa", 90, "1797|tapicerowane"]]))
    wartosc, powod = pf.id_dla(pf.wczytaj_slownik(), "Materiał", "tapicerowane")
    assert wartosc is None and "niejednoznaczne" in powod


def _baza_z_decyzjami(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt

    baza = tmp_path / "e.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    import atrybuty.app as app_mod
    monkeypatch.setattr(app_mod, "BAZA", baza)

    con = db.polacz(baza)
    wizja.przygotuj_baze(con)
    produkty = [Produkt(id=str(i), nazwa=f"Komoda {i}", producent="BRW", kolekcja="",
                        zdjecie="", styl="", kategoria="komoda",
                        kody={"kod produktu": f"K{i}", "kod producenta": f"P{i}"},
                        atrybuty={"Materiał": "plyta"}) for i in (1, 2, 3)]
    findingi = [Finding(str(i), "Materiał", "L1-SLOWNIK", "L1", "srednia", 0.9,
                        "plyta", "drewno", "poza słownikiem",
                        grupa="L1-SLOWNIK|Materiał|plyta") for i in (1, 2, 3)]
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    for i in (1, 2, 3):
        db.zapisz_decyzje(con, str(i), "Materiał", "plyta", "zastosowana", "drewno", "L1-SLOWNIK")
    return con, baza


def test_partia_bierze_tylko_niewyeksportowane(tmp_path, monkeypatch):
    from atrybuty import eksport_panelu
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))
    con, _ = _baza_z_decyzjami(tmp_path, monkeypatch)

    w1 = eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=2)
    assert w1["ile"] == 2
    w2 = eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    assert w2["ile"] == 1                      # trzeci produkt, nie te same dwa
    assert eksport_panelu.zaplanuj(con, 50).pozycje == []
    con.close()


def test_wycofanie_partii_wraca_do_kolejki(tmp_path, monkeypatch):
    from atrybuty import eksport_panelu
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))
    con, _ = _baza_z_decyzjami(tmp_path, monkeypatch)

    w = eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    assert eksport_panelu.wycofaj(con, w["partia_id"]) == 3
    assert len(eksport_panelu.zaplanuj(con, 50).pozycje) == 3
    con.close()


def test_plik_partii_ma_uklad_panelu(tmp_path, monkeypatch):
    import openpyxl
    from atrybuty import eksport_panelu
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))
    con, _ = _baza_z_decyzjami(tmp_path, monkeypatch)

    w = eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=1)
    ws = openpyxl.load_workbook(w["plik"]).active
    naglowki = [c.value for c in ws[6]]
    assert naglowki[:4] == ["ID", "Kod", "Kod producenta", "Nazwa"]
    wiersz = dict(zip(naglowki, [c.value for c in ws[7]]))
    assert wiersz["ID"] == 1 and wiersz["Kod producenta"] == "P1"
    assert wiersz["Materiał"] == "2104|drewno"     # z ID, nie goła etykieta
    assert wiersz["Szerokość"] is None             # nie ruszamy kolumn bez zmian

    ws_c = openpyxl.load_workbook(w["plik_cofnij"]).active
    assert dict(zip(naglowki, [c.value for c in ws_c[7]]))["Materiał"] == "plyta"
    con.close()


def test_strona_rozstrzygnietych_pokazuje_zmiane(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import atrybuty.app as app_mod
    con, _ = _baza_z_decyzjami(tmp_path, monkeypatch)
    con.close()
    odp = TestClient(app_mod.app).get("/rozstrzygniete")
    assert odp.status_code == 200
    assert "plyta" in odp.text and "drewno" in odp.text and "Komoda 1" in odp.text


def test_cofniecie_decyzji_z_partii_jest_blokowane(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import db, eksport_panelu
    import atrybuty.app as app_mod
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))
    con, baza = _baza_z_decyzjami(tmp_path, monkeypatch)
    eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    con.close()

    klient = TestClient(app_mod.app)
    odp = klient.post("/rozstrzygniete/cofnij", data={
        "produkt_id": "1", "atrybut": "Materiał", "hasz": db.hasz("plyta")})
    assert "cofnij najpierw partię" in odp.text
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 3
    con.close()


# --- pełny słownik atrybutów ze sklepu ------------------------------------

def _plik_slownika(tmp_path, atrybuty, wartosci):
    """Eksport „Atrybuty" z panelu: arkusz atrybutów + arkusz wartości."""
    import openpyxl
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "Atrybuty"
    a.append(["id", "status", "title"])
    for w in atrybuty:
        a.append(list(w))
    b = wb.create_sheet("Wartości atrybutów słownikowych")
    b.append(["id", "title", "title"])
    for w in wartosci:
        b.append(list(w))
    sciezka = tmp_path / "slownik.xlsx"
    wb.save(sciezka)
    return sciezka


def test_slownik_sklepu_dzieli_atrybuty_na_slownikowe_i_wolne(tmp_path, monkeypatch):
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    plik = _plik_slownika(tmp_path,
        [(3.0, "ACTIVE", "Szerokość"), (2104.0, "ACTIVE", "Materiał"),
         (108.0, "DRAFT", "Ilość nóg")],
        [(1952.0, "Materiał", "metal"), (2104.0, "Materiał", "drewno"),
         (1735.0, "Ilość nóg", "1")])
    w = pf.naucz_ze_slownika(plik)
    assert w["slownikowych"] == 2 and w["wolnych"] == 1
    assert "Szerokość" in pf.wczytaj_wzorzec().surowe
    assert "Materiał" not in pf.wczytaj_wzorzec().surowe


def test_wartosc_wielokrotna_dostaje_id_dla_kazdego_czlonu(tmp_path, monkeypatch):
    """„ceramika, metal" to lista wartości — każda ma własne ID."""
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    pf.naucz_ze_slownika(_plik_slownika(tmp_path,
        [(1.0, "ACTIVE", "Materiał")],
        [(1952.0, "Materiał", "metal"), (2274.0, "Materiał", "ceramika")]))
    s, e = pf.wczytaj_slownik(), pf.wczytaj_etykiety()
    assert pf.wartosc_slownikowa(s, "Materiał", "ceramika, metal", e)[0] == \
        "2274|ceramika, 1952|metal"
    # jeden nieznany człon przekreśla całą wartość — pół listy to nie poprawka
    assert pf.wartosc_slownikowa(s, "Materiał", "ceramika, dąb", e)[0] is None


def test_etykieta_idzie_w_pisowni_sklepu(tmp_path, monkeypatch):
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    pf.naucz_ze_slownika(_plik_slownika(tmp_path,
        [(1.0, "ACTIVE", "Kierunek otwierania")],
        [(1893.0, "Kierunek otwierania", "W lewą stronę")]))
    s, e = pf.wczytaj_slownik(), pf.wczytaj_etykiety()
    assert pf.id_dla(s, "Kierunek otwierania", "w lewa strone", e)[0] == "1893|W lewą stronę"


def test_wpisy_null_w_slowniku_sa_odrzucane(tmp_path, monkeypatch):
    """Słownik sklepu ma pozycje o tytule NULL — to śmieć po imporcie."""
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    w = pf.naucz_ze_slownika(_plik_slownika(tmp_path,
        [(1.0, "ACTIVE", "Styl")],
        [(1695.0, "Styl", "nowoczesny"), (2033.0, "Styl", "NULL")]))
    assert w["wartosci"] == 1 and w["smieci"] == 1
    assert "null" not in pf.wczytaj_slownik()["Styl"]


def test_duplikaty_slownika_sa_raportowane(tmp_path, monkeypatch):
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    w = pf.naucz_ze_slownika(_plik_slownika(tmp_path,
        [(1.0, "ACTIVE", "Styl")],
        [(1695.0, "Styl", "nowoczesny"), (2291.0, "Styl", "nowoczesny")]))
    assert w["duplikaty"] and w["duplikaty"][0]["ids"] == ["1695", "2291"]
    s, e = pf.wczytaj_slownik(), pf.wczytaj_etykiety()
    assert pf.id_dla(s, "Styl", "nowoczesny", e)[0] is None


def test_wlasna_wartosc_zapisuje_poprawke_a_nie_odklada(tmp_path, monkeypatch):
    """Pole „własna wartość" to decyzja, nie odłożenie jej na później."""
    from fastapi.testclient import TestClient
    from atrybuty import db
    import atrybuty.app as app_mod
    con, baza = _baza_z_decyzjami(tmp_path, monkeypatch)
    con.execute("DELETE FROM decyzje"); con.commit(); con.close()

    klient = TestClient(app_mod.app)
    strona = klient.get("/anomalie").text
    assert 'placeholder="własna wartość"' in strona
    # formularz z tym polem musi wysyłać status zastosowana
    kawalek = strona[:strona.find('placeholder="własna wartość"')]
    assert kawalek.rsplit('name="status"', 1)[1].startswith(' value="zastosowana"')

    klient.post("/decyzja", data={
        "produkt_id": "1", "atrybut": "Materiał", "stara": "plyta",
        "nowa": "dąb", "regula_id": "RECZNA", "status": "zastosowana",
        "zakres": "pojedynczo"})
    con = db.polacz(baza)
    r = con.execute("SELECT status, nowa_wartosc FROM decyzje WHERE produkt_id='1'").fetchone()
    con.close()
    assert r["status"] == "zastosowana" and r["nowa_wartosc"] == "dąb"


def test_kolejka_podpowiada_wartosci_ze_slownika(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import atrybuty.app as app_mod
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    pf.naucz_ze_slownika(_plik_slownika(tmp_path,
        [(1.0, "ACTIVE", "Materiał")],
        [(2104.0, "Materiał", "drewno"), (1952.0, "Materiał", "metal")]))
    con, _ = _baza_z_decyzjami(tmp_path, monkeypatch)
    con.execute("DELETE FROM decyzje"); con.commit(); con.close()

    strona = TestClient(app_mod.app).get("/anomalie").text
    assert "<datalist" in strona and 'value="drewno"' in strona and 'value="metal"' in strona


# --- L0: atrybuty rozjechane między atrybutami a składowymi ---------------

def _prod_ze_skladowymi(pid, atrybuty, skladowe, odciete=False):
    from atrybuty.model import Produkt
    return Produkt(id=pid, nazwa=f"Komoda {pid}", producent="BRW", kolekcja="",
                   zdjecie="", styl="", kategoria="komoda",
                   atrybuty=dict(atrybuty), atrybuty_surowe=dict(atrybuty),
                   skladowe=dict(skladowe), skladowe_odciete=odciete)


SLOWNIK_TESTOWY = {"Materiał": {"drewno": ["2104"], "metal": ["1952"]},
                   "Podparcie": {"na nozkach": ["1956"]}}


def test_atrybut_ze_skladowych_trafia_do_przepisania():
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {"Materiał": "drewno"}, {"Podparcie": "na nóżkach"})
    f = skladowe.znajdz([p], SLOWNIK_TESTOWY)
    assert len(f) == 1
    assert f[0].regula_id == "L0-ZE-SKLADOWYCH"
    assert f[0].atrybut == "Podparcie" and f[0].proponowana_wartosc == "na nóżkach"


def test_nieslownikowe_ze_skladowych_sa_pomijane():
    """Liczby i teksty bez słownika zostają, gdzie były — nie ma czym
    potwierdzić, że wartość jest sensowna."""
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {}, {"Długość": "200", "Do poprawy": "stojące"})
    assert skladowe.znajdz([p], SLOWNIK_TESTOWY) == []


def test_flaga_odciecia_wylacza_produkt():
    """omit_components_in_attributes=1 znaczy, że składowe są już przepisane."""
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {}, {"Podparcie": "na nóżkach"}, odciete=True)
    assert skladowe.znajdz([p], SLOWNIK_TESTOWY) == []


def test_konflikt_realny_jest_krytyczny_a_zaokraglenie_nie():
    from atrybuty import skladowe
    from atrybuty.model import INFO, KRYTYCZNA
    realny = _prod_ze_skladowymi("1", {"Materiał": "metal"}, {"Materiał": "drewno"})
    zaokr = _prod_ze_skladowymi("2", {"Wysokość": "90,5"}, {"Wysokość": "90"})
    zapis = _prod_ze_skladowymi("3", {"Głębokość": "41,9"}, {"Głębokość": "41.9"})
    f = {x.produkt_id: x for x in skladowe.znajdz([realny, zaokr, zapis], SLOWNIK_TESTOWY)}
    assert f["1"].waga == KRYTYCZNA and f["1"].regula_id == "L0-KONFLIKT"
    assert f["2"].waga == INFO
    assert f["3"].waga == INFO       # 41,9 i 41.9 to ta sama liczba


def test_zgodne_wartosci_nie_daja_findingu():
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {"Materiał": "drewno"}, {"Materiał": "drewno"})
    assert skladowe.znajdz([p], SLOWNIK_TESTOWY) == []


def test_przepisania_grupuja_sie_po_wartosci():
    """6616 produktów z „Podparcie = na nóżkach" to jedna decyzja."""
    from atrybuty import skladowe
    produkty = [_prod_ze_skladowymi(str(i), {}, {"Podparcie": "na nóżkach"})
                for i in range(5)]
    f = skladowe.znajdz(produkty, SLOWNIK_TESTOWY)
    assert len(f) == 5 and len({x.grupa for x in f}) == 1


def test_obie_sciezki_importu_licza_te_same_warstwy():
    """Import ze strony i z konsoli muszą dawać ten sam komplet findingów —
    L0 weszło kiedyś tylko do jednej i nie było go widać w kolejce."""
    import inspect
    from atrybuty import importer, pipeline
    assert "wszystkie_findingi" in inspect.getsource(importer._przebieg)
    assert "wszystkie_findingi" in inspect.getsource(pipeline.komenda_import)
    zrodlo = inspect.getsource(pipeline.wszystkie_findingi)
    assert "detektory.uruchom" in zrodlo and "skladowe.znajdz" in zrodlo


def test_wszystkie_findingi_dokladaja_l0():
    from atrybuty import pipeline
    from atrybuty.model import L0
    p = _prod_ze_skladowymi("1", {"Materiał": "drewno"}, {"Podparcie": "na nóżkach"})
    f = pipeline.wszystkie_findingi([p], [])
    assert any(x.warstwa == L0 for x in f)
