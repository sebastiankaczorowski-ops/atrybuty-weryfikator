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
    # Bez grupowania pole zapisuje wprost — i to jako decyzję, nie odłożenie.
    strona = klient.get("/anomalie?grupuj=0").text
    # formularz własnej wartości poznajemy po regule RECZNA
    i = strona.find('value="RECZNA"')
    assert i > 0
    formularz = strona[strona.rfind("<form", 0, i):strona.find("</form>", i)]
    assert 'name="status" value="zastosowana"' in formularz
    assert 'name="nowa"' in formularz

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


def test_konflikt_na_nieznanym_atrybucie_nie_blokuje_kolejki():
    """„Liczba miejsc" nie istnieje w panelu (sklep ma „Ilość osób") — takiej
    poprawki i tak nie da się wyeksportować, więc nie jest krytyczna."""
    from atrybuty import skladowe
    from atrybuty.model import INFO
    p = _prod_ze_skladowymi("1", {"Liczba miejsc": "2-osobowe"},
                            {"Liczba miejsc": "2 miejsca"})
    f = skladowe.znajdz([p], SLOWNIK_TESTOWY, {"Materiał": {}, "Podparcie": {}})
    assert len(f) == 1 and f[0].waga == INFO
    assert "panel nie zna" in f[0].dowod


def test_nowa_nazwa_kolumny_skladowych_jest_rozpoznawana():
    from atrybuty.pipeline import KOLUMNY_SKLADOWYCH
    assert "atrybuty-skladowe" in KOLUMNY_SKLADOWYCH
    assert "atrybuty z zakladki" in KOLUMNY_SKLADOWYCH   # stare pliki też


# --- domknięcie pętli: czy wysłane poprawki weszły ------------------------

def _dzien_pierwszy(tmp_path, monkeypatch):
    """Zrzut, decyzja, partia — stan na koniec dnia pierwszego."""
    import atrybuty.pipeline as pipeline
    from atrybuty import db, eksport_panelu, weryfikacja, wizja
    from atrybuty.model import Finding, Produkt

    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atr.yaml")
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))

    baza = tmp_path / "w.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    import atrybuty.app as app_mod
    monkeypatch.setattr(app_mod, "BAZA", baza)

    con = db.polacz(baza)
    wizja.przygotuj_baze(con)
    weryfikacja.przygotuj_baze(con)
    produkty = [Produkt(id=str(i), nazwa=f"Komoda {i}", producent="BRW", kolekcja="",
                        zdjecie="", styl="", kategoria="komoda",
                        kody={"kod produktu": f"K{i}"},
                        atrybuty={"Materiał": "plyta"},
                        atrybuty_surowe={"Materiał": "plyta"}) for i in (1, 2, 3, 4)]
    findingi = [Finding(str(i), "Materiał", "L1-SLOWNIK", "L1", "srednia", 0.9,
                        "plyta", "drewno", "poza słownikiem") for i in (1, 2, 3, 4)]
    db.zapisz_przebieg(con, "dzien1.csv", produkty, findingi)
    for i in (1, 2, 3, 4):
        db.zapisz_decyzje(con, str(i), "Materiał", "plyta", "zastosowana", "drewno", "L1")
    eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    return con, baza, produkty


def test_weryfikacja_rozpoznaje_co_weszlo_a_co_nie(tmp_path, monkeypatch):
    from atrybuty import db, weryfikacja
    con, baza, _ = _dzien_pierwszy(tmp_path, monkeypatch)

    # dzień drugi: 1 poprawione, 2 bez zmian, 3 zmienione na co innego, 4 zniknął
    from atrybuty.model import Produkt
    def prod(pid, wartosc):
        return Produkt(id=pid, nazwa=f"Komoda {pid}", producent="BRW", kolekcja="",
                       zdjecie="", styl="", kategoria="komoda",
                       atrybuty={"Materiał": wartosc}, atrybuty_surowe={"Materiał": wartosc})
    nowe = [prod("1", "drewno"), prod("2", "plyta"), prod("3", "metal")]
    wynik = weryfikacja.sprawdz(con, 2, nowe)

    assert wynik[weryfikacja.WESZLO] == 1
    assert wynik[weryfikacja.BEZ_ZMIAN] == 1
    assert wynik[weryfikacja.INNA] == 1
    assert wynik[weryfikacja.BRAK_PRODUKTU] == 1
    assert weryfikacja.podsumowanie(con)["skutecznosc"] == 25
    con.close()


def test_weryfikacja_wybacza_nieistotne_roznice(tmp_path, monkeypatch):
    """„46" i „46,0" to ta sama liczba, a lista w innej kolejności to ta sama
    lista — inaczej połowa poprawek wracałaby jako „zmienione na co innego"."""
    from atrybuty import weryfikacja
    assert weryfikacja._takie_same("46", "46,0")
    assert weryfikacja._takie_same("szkło, metal", "metal, szkło")
    assert not weryfikacja._takie_same("metal", "drewno")


def test_partia_mlodsza_od_zrzutu_nie_jest_liczona(tmp_path, monkeypatch):
    """Zrzut zrobiony przed wysłaniem partii nie mógł jej widzieć — liczenie
    go jako „nie weszło" dawałoby fałszywy alarm co rano."""
    from atrybuty import weryfikacja
    con, _, produkty = _dzien_pierwszy(tmp_path, monkeypatch)
    wynik = weryfikacja.sprawdz(con, 2, produkty, data_zrzutu="2000-01-01 00:00:00")
    assert wynik["sprawdzonych"] == 0
    con.close()


def test_strona_weryfikacji_pokazuje_co_nie_weszlo(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import weryfikacja
    from atrybuty.model import Produkt
    import atrybuty.app as app_mod
    con, _, _ = _dzien_pierwszy(tmp_path, monkeypatch)
    weryfikacja.sprawdz(con, 2, [Produkt(
        id="1", nazwa="Komoda 1", producent="BRW", kolekcja="", zdjecie="", styl="",
        kategoria="komoda", atrybuty={"Materiał": "plyta"},
        atrybuty_surowe={"Materiał": "plyta"})])
    con.close()

    strona = TestClient(app_mod.app).get("/weryfikacja").text
    assert "import nie wszedł" in strona and "Komoda 1" in strona


STATUSY_TESTOWE = {"Materiał": {"id": "1", "status": "ACTIVE"},
                   "Podparcie": {"id": "2", "status": "ACTIVE"},
                   "Szerokość": {"id": "3", "status": "ACTIVE"},
                   "Długość": {"id": "4", "status": "DISABLED"}}


def test_wymiary_ze_skladowych_tez_sa_przepisywane():
    """Szerokość nie ma wartości słownikowych i mieć nie będzie, ale jest
    normalnym polem sklepu — odcięcie jej zostawiało produkty bez wymiarów."""
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("78275", {"Długość": "110"},
                            {"Szerokość": "110", "Wysokość": "43", "Waga": "19.5"})
    f = {x.atrybut: x for x in skladowe.znajdz([p], SLOWNIK_TESTOWY, STATUSY_TESTOWE)}
    assert f["Szerokość"].proponowana_wartosc == "110"
    assert f["Szerokość"].regula_id == "L0-ZE-SKLADOWYCH"


def test_atrybut_wylaczony_w_panelu_nie_jest_przepisywany():
    """„Długość" jest w panelu DISABLED — nie ma dokąd tego wpisać."""
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {}, {"Długość": "200"})
    assert skladowe.znajdz([p], SLOWNIK_TESTOWY, STATUSY_TESTOWE) == []


def test_atrybut_nieznany_panelowi_nie_jest_przepisywany():
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {}, {"Liczba miejsc": "2 miejsca"})
    assert skladowe.znajdz([p], SLOWNIK_TESTOWY, STATUSY_TESTOWE) == []


def test_karta_produktu_zestawia_atrybuty_ze_skladowymi(tmp_path, monkeypatch):
    """Rozjazdy i braki na górze — po to się na tę kartę wchodzi."""
    from fastapi.testclient import TestClient
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    import atrybuty.app as app_mod

    baza = tmp_path / "k.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    p = _prod_ze_skladowymi("78275", {"Długość": "110", "Materiał": "metal"},
                            {"Szerokość": "110", "Materiał": "drewno"})
    db.zapisz_przebieg(con, "t.csv", [p], [])
    con.close()

    strona = TestClient(app_mod.app).get("/produkt/78275").text
    assert "Atrybuty produktu a składowe" in strona
    assert 'class="rozjazd"' in strona and 'class="tylko-skladowe"' in strona
    # rozjazd (Materiał) przed brakiem w atrybutach (Szerokość)
    assert strona.index("Materiał") < strona.index("Szerokość")


def test_finding_l0_mowi_ktora_wartosc_skad():
    from atrybuty import skladowe
    p = _prod_ze_skladowymi("1", {"Materiał": "metal"}, {"Materiał": "drewno"})
    f = skladowe.znajdz([p], SLOWNIK_TESTOWY, STATUSY_TESTOWE)[0]
    assert "W atrybutach produktu: „metal”" in f.dowod
    assert "W składowych: „drewno”" in f.dowod


# --- wymiary z rysunku technicznego ---------------------------------------

def test_wymiary_z_rysunku_przeliczaja_milimetry():
    """Rysunki bywają w mm, sklep trzyma centymetry."""
    from atrybuty import wizja
    assert wizja._na_centymetry("1100", "mm") == "110"
    assert wizja._na_centymetry("110", "cm") == "110"
    assert wizja._na_centymetry("", "cm") == ""          # brak to brak, nie zero


def test_odczyt_wymiarow_parsuje_odpowiedz():
    from atrybuty import wizja
    surowe = {"candidates": [{"content": {"parts": [{"text": json.dumps({
        "szerokosc": "1100", "wysokosc": "430", "glebokosc": "",
        "jednostka": "mm", "pewnosc": 0.9, "uzasadnienie": "wymiary na rzucie"})}]}}],
        "usageMetadata": {"promptTokenCount": 300, "candidatesTokenCount": 40}}
    o = wizja._zparsuj_wymiary(surowe)
    assert o.wymiary == {"Szerokość": "110", "Wysokość": "43", "Głębokość": ""}
    assert o.cokolwiek and o.pewnosc == 0.9


def test_wymiary_bez_rysunku_mowia_wprost(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    import atrybuty.app as app_mod
    baza = tmp_path / "r.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    db.zapisz_przebieg(con, "t.csv", [_prod_ze_skladowymi("1", {}, {})], [])
    con.close()

    odp = TestClient(app_mod.app).post("/wizja/wymiary", data={"produkt_id": "1"})
    assert "nie ma rysunku technicznego" in odp.text


# --- widok produktowy -----------------------------------------------------

def _kolejka_z_produktem(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding
    import atrybuty.app as app_mod
    baza = tmp_path / "v.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    p = _prod_ze_skladowymi("500", {}, {})
    findingi = [
        Finding("500", "Szerokość", "L0-ZE-SKLADOWYCH", "L0", "srednia", 0.9,
                None, "110", "ze składowych"),
        Finding("500", "Wysokość", "L0-ZE-SKLADOWYCH", "L0", "srednia", 0.9,
                None, "43", "ze składowych"),
        Finding("500", "Materiał", "L2-OUTLIER", "L2", "krytyczna", 0.4,
                "metal", None, "odstaje od kategorii"),
    ]
    db.zapisz_przebieg(con, "t.csv", [p], findingi)
    return con, baza, app_mod


def test_widok_produktowy_zbiera_bledy_jednego_produktu(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    con, _, app_mod = _kolejka_z_produktem(tmp_path, monkeypatch)
    con.close()
    strona = TestClient(app_mod.app).get("/anomalie?widok=produkt").text
    assert strona.count('class="karta-produktu"') == 1
    assert "3 błędów" in strona
    assert "Zastosuj 2 gotowych" in strona     # trzeci nie ma propozycji


def test_hurt_na_produkcie_omija_niepewne(tmp_path, monkeypatch):
    """Hurtowe zatwierdzanie bierze tylko to, czego system jest pewien —
    reszta zostaje otwarta, bo inaczej to klikanie w ciemno."""
    from fastapi.testclient import TestClient
    from atrybuty import db
    con, baza, app_mod = _kolejka_z_produktem(tmp_path, monkeypatch)
    con.close()
    odp = TestClient(app_mod.app).post("/decyzja/produkt", data={"produkt_id": "500"})
    assert "2 poprawek" in odp.text and "1 zostaje" in odp.text
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 2
    con.close()


# --- grupy niejednorodne: wymiary nie nadają się do decyzji hurtowych -----

def _kolejka_z_grupami(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt
    import atrybuty.app as app_mod
    baza = tmp_path / "g2.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    produkty = [Produkt(id=str(i), nazwa=f"Mebel {i}", producent="BRW", kolekcja="",
                        zdjecie="", styl="", kategoria="komoda") for i in range(1, 5)]
    findingi = [
        # jednorodna: ta sama stara wartość i ta sama poprawka
        Finding("1", "Materiał", "L1-SLOWNIK", "L1", "srednia", 0.9,
                "plyta", "płyta meblowa", "", grupa="G-JEDNORODNA"),
        Finding("2", "Materiał", "L1-SLOWNIK", "L1", "srednia", 0.9,
                "plyta", "płyta meblowa", "", grupa="G-JEDNORODNA"),
        # niejednorodna: każdy produkt ma inną wagę i inną poprawkę
        Finding("3", "Waga", "L1-FORMAT-DUBEL", "L1", "srednia", 0.9,
                "46, 46", "46", "", grupa="G-WAGI"),
        Finding("4", "Waga", "L1-FORMAT-DUBEL", "L1", "srednia", 0.9,
                "31, 31", "31", "", grupa="G-WAGI"),
    ]
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    return con, baza, app_mod


def test_grupa_o_roznych_wartosciach_nie_jest_jednorodna(tmp_path, monkeypatch):
    from atrybuty import db, zapytania
    con, _, _ = _kolejka_z_grupami(tmp_path, monkeypatch)
    wg = {w["grupa"]: w for w in zapytania.lista(con, 1, zapytania.Filtr(grupuj=True))}
    assert wg["G-JEDNORODNA"]["jednorodna"] is True
    assert wg["G-WAGI"]["jednorodna"] is False
    con.close()


def test_kolejka_nie_oferuje_hurtu_na_roznych_wartosciach(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    con, _, app_mod = _kolejka_z_grupami(tmp_path, monkeypatch)
    con.close()
    strona = TestClient(app_mod.app).get("/anomalie?atrybut=Waga").text
    assert "podobnych" in strona and "identycznych" not in strona
    assert 'name="zakres" value="grupa"' not in strona


def test_serwer_odrzuca_hurt_na_roznych_wartosciach(tmp_path, monkeypatch):
    """Blokada nie może być tylko w szablonie — decyzja hurtowa na 269
    produktach o 207 różnych wagach to zatwierdzenie ich w ciemno."""
    from fastapi.testclient import TestClient
    from atrybuty import db
    con, baza, app_mod = _kolejka_z_grupami(tmp_path, monkeypatch)
    con.close()
    odp = TestClient(app_mod.app).post("/decyzja", data={
        "produkt_id": "3", "atrybut": "Waga", "zakres": "grupa",
        "grupa": "G-WAGI", "status": "zastosowana"})
    assert "różne wartości" in odp.text
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 0
    con.close()


def test_hurt_dalej_dziala_na_jednorodnej_grupie(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import db
    con, baza, app_mod = _kolejka_z_grupami(tmp_path, monkeypatch)
    con.close()
    odp = TestClient(app_mod.app).post("/decyzja", data={
        "produkt_id": "1", "atrybut": "Materiał", "zakres": "grupa",
        "grupa": "G-JEDNORODNA", "status": "zastosowana"})
    assert "2 produktów w grupie" in odp.text
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 2
    con.close()


# --- zgłoszenie produktu do importu bez poprawek --------------------------

def _baza_do_zgloszen(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, eksport_panelu, wizja
    from atrybuty.model import Produkt
    import atrybuty.app as app_mod
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "e.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "a.yaml")
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))

    baza = tmp_path / "z.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con); eksport_panelu.przygotuj_baze(con)
    p = Produkt(id="77", nazwa="Ława Lavida", producent="Halmar", kolekcja="",
                zdjecie="", styl="", kategoria="lawa",
                kody={"kod produktu": "K77"},
                atrybuty={"Szerokość": "110", "Materiał": "drewno"},
                atrybuty_surowe={"Szerokość": "110", "Materiał": "drewno"})
    db.zapisz_przebieg(con, "t.csv", [p], [])
    return con, baza, app_mod


def test_zgloszony_produkt_niesie_komplet_atrybutow(tmp_path, monkeypatch):
    """Wiersz zgłoszenia to aktualny stan, nie poprawka — dzięki temu
    powtórzenie importu niczego nie rusza."""
    from atrybuty import eksport_panelu
    con, _, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    eksport_panelu.zglos_produkt(con, "77", "zweryfikowany")
    plan = eksport_panelu.zaplanuj(con, 50)
    poz = plan.pozycje[0]
    assert plan.zgloszonych == 1 and poz.komplet
    assert poz.zmiany["Szerokość"] == "110"
    assert poz.zmiany["Materiał"] == "2104|drewno"    # słownikowe dostaje ID
    assert poz.stare == poz.zmiany                    # cofka nic nie zmienia
    con.close()


def test_zgloszenie_znika_po_wyeksportowaniu(tmp_path, monkeypatch):
    from atrybuty import eksport_panelu
    con, _, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    eksport_panelu.zglos_produkt(con, "77")
    eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    assert eksport_panelu.czeka_zgloszonych(con) == 0
    assert eksport_panelu.zaplanuj(con, 50).pozycje == []
    con.close()


def test_wycofanie_partii_wraca_takze_zgloszenia(tmp_path, monkeypatch):
    from atrybuty import eksport_panelu
    con, _, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    eksport_panelu.zglos_produkt(con, "77")
    w = eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    eksport_panelu.wycofaj(con, w["partia_id"])
    assert eksport_panelu.czeka_zgloszonych(con) == 1
    con.close()


def test_produkt_z_wczesniejszej_partii_jest_oznaczony(tmp_path, monkeypatch):
    """Ten sam mebel może wrócić w kolejnej partii, gdy decyzje zapadły
    w różne dni — eksport ma to pokazać, a nie ukryć."""
    from atrybuty import db, eksport_panelu
    con, _, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    eksport_panelu.zglos_produkt(con, "77")
    eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)

    db.zapisz_decyzje(con, "77", "Materiał", "drewno", "zastosowana", "drewno", "R")
    plan = eksport_panelu.zaplanuj(con, 50)
    assert plan.powtorki and plan.powtorki[0].byl_w_partii == 1
    con.close()


def test_zgloszenie_z_karty_produktu(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import eksport_panelu
    con, baza, app_mod = _baza_do_zgloszen(tmp_path, monkeypatch)
    con.close()
    klient = TestClient(app_mod.app)
    assert "Dodaj do importu bez zmian" in klient.get("/produkt/77").text
    assert "w kolejce do importu" in klient.post(
        "/zglos-produkt", data={"produkt_id": "77"}).text

    from atrybuty import db
    con = db.polacz(baza)
    assert eksport_panelu.czeka_zgloszonych(con) == 1
    klient.post("/zglos-produkt/cofnij", data={"produkt_id": "77"})
    assert eksport_panelu.czeka_zgloszonych(con) == 0
    con.close()


def test_zgloszenie_bez_atrybutow_nie_wchodzi_do_partii(tmp_path, monkeypatch):
    """Panel stawia flagę odcięcia składowych przy zapisie atrybutów, więc
    pusty wiersz nic nie da — taki produkt zostaje w kolejce zgłoszeń."""
    from atrybuty import db, eksport_panelu
    from atrybuty.model import Produkt
    con, baza, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    pusty = Produkt(id="90", nazwa="Kosz na śmieci", producent="X", kolekcja="",
                    zdjecie="", styl="", kategoria="akcesoria")
    z_atrybutami = Produkt(id="77", nazwa="Ława", producent="Halmar", kolekcja="",
                           zdjecie="", styl="", kategoria="lawa",
                           atrybuty={"Szerokość": "110"},
                           atrybuty_surowe={"Szerokość": "110"})
    db.zapisz_przebieg(con, "t.csv", [pusty, z_atrybutami], [])

    eksport_panelu.zglos_produkt(con, "90")
    eksport_panelu.zglos_produkt(con, "77")
    plan = eksport_panelu.zaplanuj(con, 50)
    assert [z["produkt_id"] for z in plan.puste_zgloszenia] == ["90"]
    assert [p.produkt_id for p in plan.pozycje] == ["77"]

    # po wyeksportowaniu puste zgłoszenie dalej czeka, a nie znika po cichu
    eksport_panelu.zapisz_partie(con, tmp_path / "out", limit_produktow=50)
    assert eksport_panelu.czeka_zgloszonych(con) == 1
    con.close()


def test_zgloszenie_pustego_produktu_jest_odrzucane_od_razu(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import db, eksport_panelu
    from atrybuty.model import Produkt
    con, baza, app_mod = _baza_do_zgloszen(tmp_path, monkeypatch)
    db.zapisz_przebieg(con, "t.csv", [Produkt(
        id="90", nazwa="Kosz", producent="X", kolekcja="", zdjecie="", styl="",
        kategoria="akcesoria")], [])
    con.close()

    odp = TestClient(app_mod.app).post("/zglos-produkt", data={"produkt_id": "90"})
    assert "nie postawi flagi na pustym wierszu" in odp.text
    con = db.polacz(baza)
    assert eksport_panelu.czeka_zgloszonych(con) == 0    # nic nie zapisano
    con.close()


def test_zgloszenie_grupy_dodaje_wszystkie_produkty(tmp_path, monkeypatch):
    """Zgłoszenie do importu nie jest decyzją o wartości, więc wolno je zrobić
    hurtem także na grupie o różnych wartościach."""
    from fastapi.testclient import TestClient
    from atrybuty import db, eksport_panelu, wizja
    from atrybuty.model import Finding, Produkt
    import atrybuty.pipeline as pipeline
    import atrybuty.app as app_mod

    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "e.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "a.yaml")
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))

    baza = tmp_path / "gr.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    produkty = [Produkt(id=str(i), nazwa=f"Mebel {i}", producent="BRW", kolekcja="",
                        zdjecie="", styl="", kategoria="komoda",
                        atrybuty={"Szerokość": str(100 + i)},
                        atrybuty_surowe={"Szerokość": str(100 + i)}) for i in (1, 2, 3)]
    # celowo różne wartości — hurtowe „Zastosuj" byłoby zablokowane, to nie
    findingi = [Finding(str(i), "Waga", "L1-FORMAT-DUBEL", "L1", "srednia", 0.9,
                        f"{i}, {i}", str(i), "", grupa="G") for i in (1, 2, 3)]
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    con.close()

    odp = TestClient(app_mod.app).post("/zglos-grupe", data={"grupa": "G"})
    assert "3 produktów w kolejce" in odp.text
    con = db.polacz(baza)
    assert eksport_panelu.czeka_zgloszonych(con) == 3
    con.close()


def test_zgloszenie_do_importu_zamyka_finding(tmp_path, monkeypatch):
    """„Do importu" to rozstrzygnięcie, nie notatka na boku.

    Bez tego finding zostawał otwarty i wracał na listę przy każdym
    odświeżeniu — ta sama praca do zrobienia drugi raz.
    """
    from fastapi.testclient import TestClient
    from atrybuty import db, zapytania
    from atrybuty.model import Finding, Produkt
    con, baza, app_mod = _baza_do_zgloszen(tmp_path, monkeypatch)
    p = Produkt(id="77", nazwa="Ława Lavida", producent="Halmar", kolekcja="",
                zdjecie="", styl="", kategoria="lawa", kody={"kod produktu": "K77"},
                atrybuty={"Szerokość": "110", "Materiał": "drewno"},
                atrybuty_surowe={"Szerokość": "110", "Materiał": "drewno"})
    f = Finding("77", "Styl", "L1-BRAK", "L1", "srednia", 0.4, "", None, "",
                grupa="G")
    przebieg = db.zapisz_przebieg(con, "t2.csv", [p], [f])
    w = zapytania.lista(con, przebieg, zapytania.Filtr(grupuj=False))[0]
    con.close()

    odp = TestClient(app_mod.app).post("/zglos-produkt", data={
        "produkt_id": w["produkt_id"], "atrybut": w["atrybut"],
        "stara": w["stara_wartosc"] or ""})
    assert "findingów zamkniętych" in odp.text

    con = db.polacz(baza)
    assert not [r for r in zapytania.lista(con, przebieg, zapytania.Filtr(grupuj=False))
                if r["produkt_id"] == w["produkt_id"]
                and r["atrybut"] == w["atrybut"]]
    wiersze, _ = zapytania.rozstrzygniete(con, status="do_importu")
    assert [r["produkt_id"] for r in wiersze] == [w["produkt_id"]]
    assert zapytania.statystyki_decyzji(con)["do_importu"] == 1
    # zgłoszenie nie jest zmianą wartości — nic nie może wejść do pliku
    assert wiersze[0]["nowa_wartosc"] is None
    con.close()


def test_partia_da_sie_zawezic_do_kategorii(tmp_path, monkeypatch):
    """Trzy osoby, trzy rozłączne zakresy — nikt nie wgrywa cudzych produktów."""
    from atrybuty import db, eksport_panelu
    from atrybuty.model import Produkt
    con, baza, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    db.zapisz_przebieg(con, "t.csv", [
        Produkt(id="1", nazwa="Ława", producent="Halmar", kolekcja="", zdjecie="",
                styl="", kategoria="lawa", atrybuty={"Szerokość": "110"},
                atrybuty_surowe={"Szerokość": "110"}),
        Produkt(id="2", nazwa="Komoda", producent="BRW", kolekcja="", zdjecie="",
                styl="", kategoria="komoda", atrybuty={"Szerokość": "90"},
                atrybuty_surowe={"Szerokość": "90"}),
    ], [])
    eksport_panelu.zglos_produkt(con, "1")
    eksport_panelu.zglos_produkt(con, "2")

    assert len(eksport_panelu.zaplanuj(con, 50).pozycje) == 2
    tylko_lawy = eksport_panelu.zaplanuj(con, 50, kategoria="lawa")
    assert [p.produkt_id for p in tylko_lawy.pozycje] == ["1"]
    tylko_brw = eksport_panelu.zaplanuj(con, 50, producent="BRW")
    assert [p.produkt_id for p in tylko_brw.pozycje] == ["2"]

    # partia z zakresu nie zabiera cudzych zgłoszeń
    eksport_panelu.zapisz_partie(con, tmp_path / "out", 50, kategoria="lawa")
    assert eksport_panelu.czeka_zgloszonych(con) == 1
    assert [p.produkt_id for p in eksport_panelu.zaplanuj(con, 50).pozycje] == ["2"]
    con.close()


def test_lista_zakresow_pokazuje_tylko_to_co_czeka(tmp_path, monkeypatch):
    from atrybuty import db, eksport_panelu
    from atrybuty.model import Produkt
    con, _, _ = _baza_do_zgloszen(tmp_path, monkeypatch)
    db.zapisz_przebieg(con, "t.csv", [
        Produkt(id="1", nazwa="Ława", producent="Halmar", kolekcja="", zdjecie="",
                styl="", kategoria="lawa", atrybuty_surowe={"Szerokość": "110"}),
        Produkt(id="2", nazwa="Szafa", producent="BRW", kolekcja="", zdjecie="",
                styl="", kategoria="szafa", atrybuty_surowe={"Szerokość": "200"}),
    ], [])
    eksport_panelu.zglos_produkt(con, "1")
    z = eksport_panelu.zakresy_do_wyboru(con)
    assert z["kategorie"] == [("lawa", 1)]          # szafa nic nie czeka
    assert z["producenci"] == [("Halmar", 1)]
    con.close()


# --- zasięg licznika grupy i zapis wartości per produkt -------------------

def _grupa_z_filtrem(tmp_path, monkeypatch):
    """Grupa rozłożona na dwie kategorie — filtr pokazuje część, decyzja
    obejmuje całość."""
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt
    import atrybuty.app as app_mod
    baza = tmp_path / "z.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    produkty, findingi = [], []
    for i in range(1, 6):
        kat = "lozko" if i <= 2 else "komoda"
        produkty.append(Produkt(id=str(i), nazwa=f"Mebel {i}", producent="BRW",
                                kolekcja="", zdjecie="", styl="", kategoria=kat))
        findingi.append(Finding(str(i), "Styl", "L0-KONFLIKT", "L0", "krytyczna", 0.5,
                                "tkanina", "tapicerowane", "", grupa="G"))
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    return con, baza, app_mod


def test_licznik_grupy_znaczy_to_samo_co_zasieg_decyzji(tmp_path, monkeypatch):
    """×N i zasięg decyzji to ta sama liczba — i obie idą za filtrem.

    Filtrując łóżka człowiek rozstrzyga łóżka. Licznik po przefiltrowanych
    wierszach obiecywał ×8 przy grupie na 1569 produktów; licznik po całej
    grupie obiecywał ruszenie komód przy filtrze na łóżka. Jedno i drugie
    to rozjazd między tym, co widać, a tym, co się wykona.
    """
    from atrybuty import zapytania
    con, _, _ = _grupa_z_filtrem(tmp_path, monkeypatch)

    fl = zapytania.Filtr(grupuj=True, kategoria="lozko")   # 2 z 5
    wiersz = zapytania.lista(con, 1, fl)[0]
    assert wiersz["ile_w_grupie"] == 2
    assert len(zapytania.czlonkowie_grupy(con, 1, "G", fl)) == 2
    assert zapytania.policz_grupe(con, 1, "G", fl) == 2
    assert len(zapytania.podglad_grupy(con, 1, "G", fl=fl)) == 2

    bez = zapytania.Filtr(grupuj=True)                     # bez filtra: cała grupa
    assert zapytania.lista(con, 1, bez)[0]["ile_w_grupie"] == 5
    assert len(zapytania.czlonkowie_grupy(con, 1, "G", bez)) == 5
    con.close()


def test_decyzja_hurtowa_nie_wychodzi_poza_filtr(tmp_path, monkeypatch):
    """„Zastosuj ×N" z widoku łóżek nie może ruszyć komód z tej samej grupy."""
    from fastapi.testclient import TestClient
    from atrybuty import db, zapytania
    con, baza, app_mod = _grupa_z_filtrem(tmp_path, monkeypatch)
    con.close()
    fl = zapytania.Filtr(grupuj=True, kategoria="lozko")
    odp = TestClient(app_mod.app).post("/decyzja", data={
        "produkt_id": "1", "atrybut": "Styl", "stara": "tkanina",
        "regula_id": "L0-KONFLIKT", "status": "zastosowana",
        "grupa": "G", "zakres": "grupa", "filtr": fl.jako_query()})
    assert "2 produktów" in odp.text

    con = db.polacz(baza)
    ruszone = {r[0] for r in con.execute("SELECT produkt_id FROM decyzje")}
    con.close()
    assert ruszone == {"1", "2"}            # komody (3,4,5) nietknięte


def test_podglad_grupy_rozdaje_wpisana_wartosc(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    con, _, app_mod = _grupa_z_filtrem(tmp_path, monkeypatch)
    con.close()
    strona = TestClient(app_mod.app).get(
        "/grupa", params={"grupa": "G", "nr": "1", "wartosc": "welur"}).text
    assert strona.count('name="nowa"') == 5
    assert strona.count('value="welur"') >= 5          # w każdym wierszu
    assert "Zapisz wszystkie (5)" in strona


def test_wlasna_wartosc_przy_grupie_nie_zapisuje_jednego_produktu(
        tmp_path, monkeypatch):
    """W widoku grupowym pole „własna wartość" prowadzi do podglądu całej
    grupy, a nie do cichego zapisu dla pierwszego produktu."""
    from fastapi.testclient import TestClient
    con, _, app_mod = _grupa_z_filtrem(tmp_path, monkeypatch)
    con.close()
    strona = TestClient(app_mod.app).get("/anomalie").text
    i = strona.find('placeholder="własna wartość"')
    assert i > 0
    formularz = strona[strona.rfind("<form", 0, i):strona.find("</form>", i)]
    assert 'hx-get="/grupa"' in formularz
    assert 'name="status"' not in formularz          # nic się nie zapisuje
    assert "rozdaj na ×" in formularz


def test_zapis_grupy_bierze_wartosc_z_kazdego_wiersza(tmp_path, monkeypatch):
    """Wartość rozdana na grupę, ale jeden produkt poprawiony ręcznie
    i jeden zostawiony pusty."""
    from fastapi.testclient import TestClient
    from atrybuty import db
    con, baza, app_mod = _grupa_z_filtrem(tmp_path, monkeypatch)
    con.close()
    odp = TestClient(app_mod.app).post("/decyzja/grupa-reczna", data={
        "grupa": "G", "nr": "1",
        "produkt_id": ["1", "2", "3"], "nowa": ["welur", "skóra", "  "]})
    assert "zapisano 2 poprawek" in odp.text and "1 zostawionych" in odp.text

    con = db.polacz(baza)
    wg = {r["produkt_id"]: r["nowa_wartosc"] for r in con.execute(
        "SELECT produkt_id, nowa_wartosc FROM decyzje")}
    assert wg == {"1": "welur", "2": "skóra"}          # pusty nie zapisany
    con.close()


def test_zakladka_co_nowego_pokazuje_changelog(tmp_path, monkeypatch):
    """Trzy osoby pracują równolegle, a wdrożenie potrafi zmienić zachowanie
    przycisku w środku dnia — muszą mieć gdzie to przeczytać."""
    from fastapi.testclient import TestClient
    import atrybuty.app as app_mod
    strona = TestClient(app_mod.app).get("/zmiany").text
    assert "Co nowego" in strona
    assert "do importu" in strona                  # najnowszy wpis
    assert "<li>" in strona and "<h2>" in strona   # markdown poszedł na HTML
    assert "co nowego" in TestClient(app_mod.app).get("/zmiany").text


def test_changelog_nie_wpuszcza_html_z_pliku(tmp_path, monkeypatch):
    """Plik jest nasz, ale renderowanie ma być bezpieczne samo z siebie."""
    import atrybuty.app as app_mod
    wynik = app_mod._markdown_lite("- **a** `b` <script>alert(1)</script>")
    assert "<b>a</b>" in wynik and "<code>b</code>" in wynik
    assert "<script>" not in wynik and "&lt;script&gt;" in wynik


def _baza_do_czyszczenia(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, eksport_panelu, wizja
    from atrybuty.model import Finding, Produkt
    baza = tmp_path / "c.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con); eksport_panelu.przygotuj_baze(con)
    p = Produkt(id="1", nazwa="Ława", producent="BRW", kolekcja="", zdjecie="",
                styl="", kategoria="lawa", atrybuty={"Szerokość": "110"},
                atrybuty_surowe={"Szerokość": "110"})
    f = Finding("1", "Styl", "L1-BRAK", "L1", "srednia", 0.4, "", None, "", grupa="G")
    db.zapisz_przebieg(con, "t.csv", [p], [f])
    db.zapisz_decyzje(con, "1", "Styl", None, "zastosowana", "nowoczesny", "R")
    eksport_panelu.zglos_produkt(con, "1", "test")
    con.execute("INSERT INTO cache_wizji (hasz, odpowiedz, utworzono)"
                " VALUES ('k','{}','2026-01-01')")
    con.commit()
    return con, baza, pipeline


def test_czyszczenie_zostawia_cache_wizji_i_liczy_co_ubylo(tmp_path, monkeypatch):
    """Reset po testach. Cache Gemini zostaje — kasowanie go znaczy płacenie
    drugi raz za te same zdjęcia."""
    con, _, pipeline = _baza_do_czyszczenia(tmp_path, monkeypatch)
    ubylo = pipeline.wyczysc(con, pipeline.TABELE_DO_CZYSZCZENIA)
    assert ubylo["decyzje"] == 1 and ubylo["przebiegi"] == 1
    assert ubylo["findingi"] == 1 and ubylo["produkty"] == 1 and ubylo["zgloszenia"] == 1
    assert con.execute("SELECT COUNT(*) FROM cache_wizji").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 0
    con.close()


def test_czyszczenie_samej_historii_nie_rusza_decyzji(tmp_path, monkeypatch):
    con, _, pipeline = _baza_do_czyszczenia(tmp_path, monkeypatch)
    pipeline.wyczysc(con, pipeline.TABELE_HISTORII)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM przebiegi").fetchone()[0] == 0
    con.close()


def test_czyszczenie_bez_potwierdzenia_nic_nie_kasuje(tmp_path, monkeypatch, capsys):
    """Komenda kasuje bazę produkcyjną — samo wpisanie jej to za mało."""
    con, baza, pipeline = _baza_do_czyszczenia(tmp_path, monkeypatch)
    con.close()
    pipeline.main(["wyczysc"])
    assert "Nic nie skasowano" in capsys.readouterr().out
    from atrybuty import db
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 1
    con.close()


def test_czyszczenie_robi_kopie_bazy(tmp_path, monkeypatch, capsys):
    """Jedyna droga powrotu, gdy ktoś się rozpędzi."""
    con, baza, pipeline = _baza_do_czyszczenia(tmp_path, monkeypatch)
    con.close()
    pipeline.main(["wyczysc", "--potwierdzam", "TAK"])
    assert "Kopia bazy" in capsys.readouterr().out
    kopie = list(baza.parent.glob("c-przed-czyszczeniem-*.db"))
    assert len(kopie) == 1

    from atrybuty import db
    stara = db.polacz(kopie[0])
    assert stara.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 1
    stara.close()
    nowa = db.polacz(baza)
    assert nowa.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 0
    nowa.close()


# --- słownik z wieloma zrzutami + przemianowania -------------------------

def _plik_slownika_wielo(tmp_path, zrzuty):
    """Eksport „Atrybuty" z kilkoma zrzutami — tak, jak robi to panel."""
    import openpyxl
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for nazwa, atrybuty, wartosci in zrzuty:
        a = wb.create_sheet(f"atrybuty {nazwa}")
        a.append(["id", "status", "title"])
        for w in atrybuty:
            a.append(list(w))
        b = wb.create_sheet(f"wartości {nazwa}")
        b.append(["id", "title", "title"])
        for w in wartosci:
            b.append(list(w))
    sciezka = tmp_path / f"slownik_{len(zrzuty)}.xlsx"
    wb.save(sciezka)
    return sciezka


def _slownik_w_tmp(tmp_path, monkeypatch):
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    monkeypatch.setattr(pf, "PLIK_ETYKIET", tmp_path / "etykiety.yaml")
    monkeypatch.setattr(pf, "PLIK_ATRYBUTOW", tmp_path / "atrybuty.yaml")
    monkeypatch.setattr(pf, "PLIK_ZMIAN_NAZW", tmp_path / "zmiany.yaml")
    return pf


def test_slownik_uczy_sie_z_najnowszego_zrzutu_a_nie_pierwszego(tmp_path, monkeypatch):
    """Panel dokłada nowe arkusze obok starych.

    Branie dwóch pierwszych to uczenie się nieaktualnego słownika — plik
    wygląda na wgrany, a zmiany z panelu nie wchodzą.
    """
    pf = _slownik_w_tmp(tmp_path, monkeypatch)
    plik = _plik_slownika_wielo(tmp_path, [
        ("9.01", [(318.0, "ACTIVE", "Materiał obicia")],
                 [(2307.0, "Materiał obicia", "welur")]),
        ("9.18", [(318.0, "ACTIVE", "Rodzaj obicia")],
                 [(2307.0, "Rodzaj obicia", "welur")]),
    ])
    w = pf.naucz_ze_slownika(plik)
    assert w["arkusze"] == "atrybuty 9.18 + wartości 9.18"
    assert "Rodzaj obicia" in pf.wczytaj_atrybuty_panelu()
    assert "Materiał obicia" not in pf.wczytaj_atrybuty_panelu()


def test_przemianowanie_w_panelu_laduje_w_mapie_starych_nazw(tmp_path, monkeypatch):
    """ID przeżywa zmianę tytułu — i tylko po nim da się poznać przemianowanie."""
    pf = _slownik_w_tmp(tmp_path, monkeypatch)
    pf.naucz_ze_slownika(_plik_slownika_wielo(tmp_path, [
        ("9.01", [(221.0, "ACTIVE", "Ilość osób")],
                 [(1829.0, "Ilość osób", "2-osobowe")])]))
    w = pf.naucz_ze_slownika(_plik_slownika_wielo(tmp_path, [
        ("9.18", [(221.0, "ACTIVE", "Liczba miejsc")],
                 [(1829.0, "Liczba miejsc", "2 miejsca")])]))

    assert w["zmiany_nazw"]["atrybuty"] == {"Ilość osób": "Liczba miejsc"}
    assert w["zmiany_nazw"]["wartosci"] == {"Liczba miejsc": {"2-osobowe": "2 miejsca"}}
    mapa = pf.wczytaj_zmiany_nazw()
    assert mapa["atrybuty"]["Ilość osób"] == "Liczba miejsc"


def test_kolejne_przemianowanie_przepina_najstarsza_nazwe(tmp_path, monkeypatch):
    """A -> B -> C: eksport sprzed roku ma trafić na C, nie zatrzymać się na B."""
    pf = _slownik_w_tmp(tmp_path, monkeypatch)
    for nazwa in ("A", "B", "C"):
        pf.naucz_ze_slownika(_plik_slownika_wielo(
            tmp_path, [(nazwa, [(7.0, "ACTIVE", nazwa)], [(70.0, nazwa, "x")])]))
    assert pf.wczytaj_zmiany_nazw()["atrybuty"] == {"A": "C", "B": "C"}


def test_stary_eksport_czyta_sie_pod_nowa_nazwa(tmp_path, monkeypatch):
    """Bez tego przemianowany atrybut wypada z walidacji — nie ma go
    w definicjach, więc żadna reguła go nie dotyka."""
    from atrybuty import config, normalizacja
    monkeypatch.setattr(config, "_wczytaj", lambda _n: {
        "atrybuty": {"Ilość osób": "Liczba miejsc"},
        "wartosci": {"Liczba miejsc": {"2-osobowe": "2 miejsca"}}})
    config.zmiany_nazw.cache_clear()
    try:
        assert normalizacja.parsuj_atrybuty("Ilość osób: 2-osobowe | Waga: 12") == {
            "Liczba miejsc": "2 miejsca", "Waga": "12"}
    finally:
        config.zmiany_nazw.cache_clear()


# --- liczniki przy filtrach ----------------------------------------------

def _baza_do_licznikow(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt

    baza = tmp_path / "l.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    con = db.polacz(baza)
    wizja.przygotuj_baze(con)

    def prod(pid, kat, producent):
        return Produkt(id=pid, nazwa=f"Mebel {pid}", producent=producent, kolekcja="",
                       zdjecie="", styl="", kategoria=kat,
                       kody={"kod produktu": pid, "kod producenta": pid},
                       atrybuty={"Materiał": "plyta"})

    produkty = [prod("1", "stolik", "BRW"), prod("2", "stolik", "BRW"),
                prod("3", "komoda", "Signal")]
    findingi = [Finding(p.id, "Materiał", "L1-SLOWNIK", "L1", "srednia", 0.9,
                        "plyta", "drewno", "poza słownikiem",
                        grupa=f"L1-SLOWNIK|Materiał|plyta|{p.id}")
                for p in produkty]
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    return con, db.ostatni_przebieg(con)["id"]


def test_licznik_kategorii_schodzi_wraz_z_rozstrzyganiem(tmp_path, monkeypatch):
    """„Stolik (39)" długo po rozstrzygnięciu wszystkich 39 to zaproszenie
    do kliknięcia w pustą listę."""
    from atrybuty import db, zapytania

    con, przebieg = _baza_do_licznikow(tmp_path, monkeypatch)
    assert dict(zapytania.slowniki_filtrow(con, przebieg).kategorie)["stolik"] == 2

    db.zapisz_decyzje(con, "1", "Materiał", "plyta", "zastosowana", "drewno", "L1-SLOWNIK")
    assert dict(zapytania.slowniki_filtrow(con, przebieg).kategorie)["stolik"] == 1

    db.zapisz_decyzje(con, "2", "Materiał", "plyta", "zastosowana", "drewno", "L1-SLOWNIK")
    assert "stolik" not in dict(zapytania.slowniki_filtrow(con, przebieg).kategorie)
    con.close()


def test_licznik_liczy_w_zakresie_pozostalych_filtrow(tmp_path, monkeypatch):
    """Po wybraniu producenta kategorie mają pokazywać JEGO kategorie —
    inaczej liczba obiecuje coś, czego po kliknięciu nie ma."""
    from atrybuty import zapytania

    con, przebieg = _baza_do_licznikow(tmp_path, monkeypatch)
    sl = zapytania.slowniki_filtrow(con, przebieg, zapytania.Filtr(producent="Signal"))
    assert dict(sl.kategorie) == {"komoda": 1}
    # własny wymiar zostaje pełny, bo inaczej nie dałoby się zmienić wyboru
    assert dict(sl.producenci) == {"BRW": 2, "Signal": 1}
    con.close()


def test_wybrana_opcja_zostaje_w_liscie_mimo_zera(tmp_path, monkeypatch):
    """Gdyby znikła, select gubiłby swoją wartość przy pierwszym przeładowaniu."""
    from atrybuty import db, zapytania

    con, przebieg = _baza_do_licznikow(tmp_path, monkeypatch)
    for pid in ("1", "2"):
        db.zapisz_decyzje(con, pid, "Materiał", "plyta", "zastosowana", "drewno", "L1-SLOWNIK")
    sl = zapytania.slowniki_filtrow(con, przebieg, zapytania.Filtr(kategoria="stolik"))
    assert dict(sl.kategorie)["stolik"] == 0
    con.close()


# --- atrybut wyjęty z obiegu ---------------------------------------------

def _reguly_w_tmp(tmp_path, monkeypatch, dane):
    import yaml
    from atrybuty import config
    monkeypatch.setattr(config, "KATALOG_CONFIG", tmp_path)
    (tmp_path / "reguly.yaml").write_text(yaml.safe_dump(dane, allow_unicode=True),
                                          encoding="utf-8")
    config.wyczysc_cache()
    return config


def test_wylaczony_atrybut_nie_produkuje_findingow(tmp_path, monkeypatch):
    """Styl: słownik w panelu ma tę samą nazwę pod kilkoma ID, więc żadna
    poprawka i tak nie przejdzie importem — nie ma po co jej pokazywać."""
    from atrybuty import detektory
    _reguly_w_tmp(tmp_path, monkeypatch, {"atrybuty_wylaczone": ["Styl"]})
    try:
        produkty = [_p(id="1", nazwa="Komoda", kategoria="komoda",
                       atrybuty={"Styl": "Nowoczesny", "Materiał": "plyta"})]
        atrybuty = {f.atrybut for f in detektory.uruchom(produkty)}
        assert "Styl" not in atrybuty
    finally:
        from atrybuty import config
        config.wyczysc_cache()


def test_wylaczony_atrybut_nie_wychodzi_do_importu(tmp_path, monkeypatch):
    """Decyzje sprzed wyłączenia zostają w bazie, ale nie wsiąkają do pliku."""
    from atrybuty import config, eksport_panelu
    pf = _panel_w_tmp(tmp_path, monkeypatch)
    pf.naucz_z_pliku(_plik_panelu(tmp_path, [[9, "A", "A", "X", 10, "2104|drewno"]]))
    con, _ = _baza_z_decyzjami(tmp_path, monkeypatch)

    monkeypatch.setattr(config, "atrybuty_wylaczone", lambda: {"Materiał"})
    plan = eksport_panelu.zaplanuj(con, 50)
    assert plan.pozycje == []
    assert plan.pominiete and "wyłączony z obiegu" in plan.pominiete[0]["powod"]
    con.close()


def test_przywrocenie_atrybutu_zdejmuje_go_z_listy(tmp_path, monkeypatch):
    """Wyjęcie ma być odwracalne jednym kliknięciem, bez deploya."""
    from atrybuty import reguly as reguly_mod
    config = _reguly_w_tmp(tmp_path, monkeypatch, {"wylaczone": []})
    try:
        reguly_mod.przelacz_atrybut("Styl", aktywny=False)
        config.wyczysc_cache()
        assert config.atrybuty_wylaczone() == {"Styl"}

        reguly_mod.przelacz_atrybut("Styl", aktywny=True)
        config.wyczysc_cache()
        assert config.atrybuty_wylaczone() == set()
        # reguły obok zostają nietknięte
        assert "wylaczone" in config.reguly()
    finally:
        config.wyczysc_cache()


def test_operator_relacji_decyduje_o_rownosci(tmp_path, monkeypatch):
    """Siedzisko RÓWNE szerokości mebla to normalny mebel, nie błąd.

    Przy `<` taki produkt leciał jako krytyczny; przy `<=` błędem jest
    dopiero siedzisko szersze od mebla.
    """
    from atrybuty import detektory, reguly
    relacja = {"id": "REL-SIEDZ-SZER", "lewa": "Szerokość siedziska",
               "operator": "<", "prawa": "Szerokość", "opis": "test"}
    _reguly_w_tmp(tmp_path, monkeypatch, {"relacje": [relacja], "wylaczone": []})
    try:
        rowne = _p(liczby={"Szerokość siedziska": 60.0, "Szerokość": 60.0})
        szersze = _p(liczby={"Szerokość siedziska": 70.0, "Szerokość": 60.0})
        wezsze = _p(liczby={"Szerokość siedziska": 50.0, "Szerokość": 60.0})

        assert detektory.l1_relacje(rowne), "przy < równość jest błędem"

        assert reguly.zmien_relacje("REL-SIEDZ-SZER", "<=", "") is None
        assert detektory.l1_relacje(rowne) == []      # równe — już nie błąd
        assert detektory.l1_relacje(wezsze) == []
        f = detektory.l1_relacje(szersze)
        assert f and f[0].regula_id == "REL-SIEDZ-SZER"   # szersze — nadal błąd

        assert reguly.relacja("REL-SIEDZ-SZER")["operator"] == "<="
    finally:
        from atrybuty import config
        config.wyczysc_cache()


def test_zmiana_relacji_pilnuje_operatora_i_istnienia(tmp_path, monkeypatch):
    from atrybuty import reguly
    _reguly_w_tmp(tmp_path, monkeypatch, {"relacje": [
        {"id": "R1", "lewa": "A", "operator": "<", "prawa": "B", "opis": "o"}]})
    try:
        assert "Operator" in reguly.zmien_relacje("R1", ">", "")
        assert "Nie ma relacji" in reguly.zmien_relacje("R2", "<=", "")
        assert reguly.relacja("R1")["operator"] == "<"     # nic się nie zmieniło
        # pusty opis zostawia stary, nie kasuje go
        reguly.zmien_relacje("R1", "<=", "")
        assert reguly.relacja("R1")["opis"] == "o"
    finally:
        from atrybuty import config
        config.wyczysc_cache()


def _decyzje_w_dwoch_kategoriach(tmp_path, monkeypatch):
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt
    import atrybuty.app as app_mod
    baza = tmp_path / "r.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    produkty, findingi = [], []
    for i in range(1, 6):
        kat = "lozko" if i <= 2 else "komoda"
        prod = "BRW" if i != 5 else "Halmar"
        produkty.append(Produkt(id=str(i), nazwa=f"Mebel {i}", producent=prod,
                                kolekcja="", zdjecie="", styl="", kategoria=kat))
        findingi.append(Finding(str(i), "Styl", "L1-BRAK", "L1", "srednia", 0.5,
                                "stary", "nowy", "", grupa="G"))
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    for i in range(1, 6):
        db.zapisz_decyzje(con, str(i), "Styl", "stary", "zastosowana", "nowy", "L1-BRAK")
    return con, baza, app_mod


def test_rozstrzygniete_filtruja_sie_po_kategorii(tmp_path, monkeypatch):
    from atrybuty import zapytania
    con, _, _ = _decyzje_w_dwoch_kategoriach(tmp_path, monkeypatch)
    wszystkie, ile = zapytania.rozstrzygniete(con)
    assert ile == 5 and len(wszystkie) == 5

    lozka, ile_lozek = zapytania.rozstrzygniete(con, kategoria="lozko")
    assert ile_lozek == 2
    assert {w["produkt_id"] for w in lozka} == {"1", "2"}
    con.close()


def test_licznik_kategorii_liczy_w_zakresie_innych_filtrow(tmp_path, monkeypatch):
    """Po wybraniu producenta kategorie mają pokazywać JEGO kategorie.

    Licznik liczony globalnie obiecywał „komoda (3)" przy producencie, który
    ma tam jeden produkt — i lista po kliknięciu nie zgadzała się z liczbą.
    """
    from atrybuty import zapytania
    con, _, _ = _decyzje_w_dwoch_kategoriach(tmp_path, monkeypatch)
    wg = dict(zapytania.slowniki_decyzji(con)["kategorie"])
    assert wg == {"lozko": 2, "komoda": 3}

    halmar = dict(zapytania.slowniki_decyzji(con, {"producent": "Halmar"})["kategorie"])
    assert halmar == {"komoda": 1}

    # własny wymiar zostaje pełny, żeby dało się zmienić wybór
    przy_lozku = zapytania.slowniki_decyzji(con, {"kategoria": "lozko"})
    assert dict(przy_lozku["kategorie"]) == {"lozko": 2, "komoda": 3}
    con.close()


def test_strona_druga_nie_gubi_filtrow(tmp_path, monkeypatch):
    """Przejście na stronę 2 kasowało wybór filtrów — lista wyglądała, jakby
    zmieniła się sama."""
    from fastapi.testclient import TestClient
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt
    import atrybuty.app as app_mod
    baza = tmp_path / "s.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    produkty = [Produkt(id=str(i), nazwa=f"Łóżko {i}", producent="BRW", kolekcja="",
                        zdjecie="", styl="", kategoria="lozko") for i in range(1, 106)]
    findingi = [Finding(str(i), "Styl", "L1-BRAK", "L1", "srednia", 0.5,
                        "stary", "nowy", "", grupa="G") for i in range(1, 106)]
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    for i in range(1, 106):
        db.zapisz_decyzje(con, str(i), "Styl", "stary", "zastosowana", "nowy", "L1-BRAK")
    con.close()

    strona = TestClient(app_mod.app).get("/rozstrzygniete?kategoria=lozko").text
    stopka = strona.split('class="strony"')[-1]
    assert "następna" in stopka
    assert "kategoria=lozko" in stopka


def _wielka_grupa(tmp_path, monkeypatch, ile=250):
    """Grupa większa niż limit podglądu (200)."""
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja
    from atrybuty.model import Finding, Produkt
    import atrybuty.app as app_mod
    baza = tmp_path / "w.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    produkty = [Produkt(id=str(i), nazwa=f"Szafa {i}", producent="ADRK", kolekcja="",
                        zdjecie="", styl="", kategoria="szafa") for i in range(1, ile + 1)]
    findingi = [Finding(str(i), "Materiał", "L1-LISTA-KOLEJNOSC", "L1", "info", 0.99,
                        "szkło, płyta meblowa", "płyta meblowa, szkło", "", grupa="G")
                for i in range(1, ile + 1)]
    db.zapisz_przebieg(con, "t.csv", produkty, findingi)
    con.close()
    return baza, app_mod


def test_grupa_wieksza_niz_podglad_da_sie_zapisac_w_calosci(tmp_path, monkeypatch):
    """298 produktów, podgląd pokazuje 200 — reszty nie było jak zapisać."""
    from fastapi.testclient import TestClient
    from atrybuty import db, zapytania
    baza, app_mod = _wielka_grupa(tmp_path, monkeypatch, ile=250)
    klient = TestClient(app_mod.app)

    podglad = klient.get("/grupa", params={"grupa": "G", "nr": "1"}).text
    assert podglad.count('name="nowa"') == 200          # lista przycięta
    assert "Zapisz całą grupę (250)" in podglad         # ale jest wyjście

    odp = klient.post("/decyzja/grupa-wartosc", data={
        "grupa": "G", "nr": "1", "wartosc": "płyta meblowa"})
    assert "zapisano 250 poprawek w całej grupie" in odp.text

    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 250
    assert con.execute(
        "SELECT COUNT(DISTINCT nowa_wartosc) FROM decyzje").fetchone()[0] == 1
    assert zapytania.policz_grupe(con, 1, "G") == 0     # nic nie zostało otwarte
    con.close()


def test_zapis_czesci_grupy_pokazuje_reszte(tmp_path, monkeypatch):
    """Po zapisaniu widocznych 200 kolejne wchodzą na listę od razu —
    bez tego trzeba było zgadywać, że grupa ma jeszcze resztę."""
    from fastapi.testclient import TestClient
    baza, app_mod = _wielka_grupa(tmp_path, monkeypatch, ile=250)
    klient = TestClient(app_mod.app)

    dane = {
        "grupa": "G", "nr": "1", "filtr": "", "wartosc": "płyta meblowa",
        "produkt_id": [str(i) for i in range(1, 201)],
        "nowa": ["płyta meblowa"] * 200,
    }
    odp = klient.post("/decyzja/grupa-reczna", data=dane).text

    assert "zapisano 200 poprawek" in odp
    assert "<b>50</b> otwartych produktów" in odp       # reszta już na liście
    assert odp.count('name="nowa"') == 50
    assert odp.count('value="płyta meblowa"') >= 50     # i od razu wypełniona


def test_zapis_calej_grupy_wymaga_wartosci(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import db
    baza, app_mod = _wielka_grupa(tmp_path, monkeypatch, ile=210)
    odp = TestClient(app_mod.app).post("/decyzja/grupa-wartosc", data={
        "grupa": "G", "nr": "1", "wartosc": "   "})
    assert "Wpisz wartość" in odp.text
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 0
    con.close()


def test_zapis_grupy_miesci_sie_w_limicie_pol_formularza(tmp_path, monkeypatch):
    """Starlette przyjmuje najwyżej 1000 pól formularza. Przy pięciu polach
    na wiersz 200 wierszy trafiało w limit co do jednego — jedno pole więcej
    i zapis wracał błędem „Too many fields". Dwa pola na wiersz dają zapas."""
    from fastapi.testclient import TestClient
    from atrybuty import db
    baza, app_mod = _wielka_grupa(tmp_path, monkeypatch, ile=250)
    dane = {"grupa": "G", "nr": "1", "filtr": "", "wartosc": "płyta meblowa",
            "produkt_id": [str(i) for i in range(1, 201)],
            "nowa": ["płyta meblowa"] * 200}
    pol = 4 + 200 * 2
    assert pol < 1000, "zapas na limit pól zniknął"

    odp = TestClient(app_mod.app).post("/decyzja/grupa-reczna", data=dane)
    assert odp.status_code == 200 and "Too many fields" not in odp.text
    con = db.polacz(baza)
    assert con.execute("SELECT COUNT(*) FROM decyzje").fetchone()[0] == 200
    con.close()


def test_zapis_grupy_ignoruje_obce_id(tmp_path, monkeypatch):
    """Serwer dobiera atrybut i starą wartość z otwartych findingów grupy,
    więc ID spoza grupy nie może niczego zapisać."""
    from fastapi.testclient import TestClient
    from atrybuty import db
    baza, app_mod = _wielka_grupa(tmp_path, monkeypatch, ile=210)
    odp = TestClient(app_mod.app).post("/decyzja/grupa-reczna", data={
        "grupa": "G", "nr": "1",
        "produkt_id": ["1", "999999"], "nowa": ["płyta meblowa", "cokolwiek"]})
    assert "zapisano 1 poprawek" in odp.text
    con = db.polacz(baza)
    assert [r[0] for r in con.execute("SELECT produkt_id FROM decyzje")] == ["1"]
    con.close()


def test_przemianowany_atrybut_ma_swoja_kolumne_w_pliku(tmp_path, monkeypatch):
    """Nagłówki pliku panelu zamarzają na dniu eksportu produktów.

    Po przemianowaniu atrybutu w panelu („Ilość osób" → „Liczba miejsc")
    słownik znał nową nazwę, a nagłówek został stary — i atrybut wypadał
    z importu jako „kolumny nie ma w formacie panelu". Po cichu, bo produkt
    i tak szedł do pliku, tylko bez tej kolumny.
    """
    import yaml
    from atrybuty import config, panel_format as pf
    monkeypatch.setattr(config, "KATALOG_CONFIG", tmp_path)
    for atryb in ("PLIK_WZORCA", "PLIK_ZMIAN_NAZW"):
        monkeypatch.setattr(pf, atryb, tmp_path / {
            "PLIK_WZORCA": "wzorzec_panelu.yaml",
            "PLIK_ZMIAN_NAZW": "zmiany_nazw.yaml"}[atryb])
    (tmp_path / "wzorzec_panelu.yaml").write_text(yaml.safe_dump(
        {"naglowki": ["ID", "Ilość osób", "Szerokość"], "surowe": ["Szerokość"],
         "preambula": []}, allow_unicode=True), encoding="utf-8")
    (tmp_path / "zmiany_nazw.yaml").write_text(yaml.safe_dump(
        {"atrybuty": {"Ilość osób": "Liczba miejsc"}, "wartosci": {}},
        allow_unicode=True), encoding="utf-8")
    config.wyczysc_cache()
    try:
        wz = pf.wczytaj_wzorzec()
        assert "Liczba miejsc" in wz.naglowki
        assert "Ilość osób" not in wz.naglowki
        assert wz.ok                      # kolumna ID nietknięta
    finally:
        config.wyczysc_cache()


def test_karta_produktu_odroznia_otwarte_od_rozstrzygnietych(tmp_path, monkeypatch):
    """Karta pokazuje WSZYSTKIE findingi produktu, kolejka tylko otwarte.

    Produkt z 13 pozycjami na karcie i jednym wierszem w kolejce wyglądał
    na błąd kolejki — a to były 24 rozstrzygnięcia, o których karta milczała.
    """
    from fastapi.testclient import TestClient
    import atrybuty.pipeline as pipeline
    from atrybuty import db, wizja, zapytania
    from atrybuty.model import Finding, Produkt
    import atrybuty.app as app_mod
    baza = tmp_path / "k.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)

    atrybuty = ["Szerokość", "Wysokość", "Głębokość", "Waga", "Kształt",
                "Materiał", "Typ drążka", "Rodzaj drzwi", "Liczba półek"]
    p = Produkt(id="137487", nazwa="Szafa przesuwna 220 Maxi", producent="Lenart",
                kolekcja="Maxi", zdjecie="", styl="", kategoria="szafa")
    # każdy atrybut to osobna grupa — inny atrybut, inna wartość
    findingi = [Finding("137487", a, "L0-ZE-SKLADOWYCH", "L0", "srednia", 0.9,
                        None, f"w{i}", "", grupa=f"L0-ZE-SKLADOWYCH|{a}|w{i}")
                for i, a in enumerate(atrybuty)]
    db.zapisz_przebieg(con, "t.csv", [p], findingi)

    # wszystkie otwarte: kolejka pokazuje każdy osobno, bo to różne grupy
    assert len(zapytania.lista(con, 1, zapytania.Filtr(szukaj="137487"))) == 9

    # rozstrzygamy 8 z 9 — zostaje jeden
    db.zapisz_decyzje_grupowo(
        con, [("137487", a, None, f"w{i}", "L0-ZE-SKLADOWYCH")
              for i, a in enumerate(atrybuty[:-1])], "zastosowana")
    otwarte = zapytania.lista(con, 1, zapytania.Filtr(szukaj="137487"))
    assert len(otwarte) == 1 and otwarte[0]["atrybut"] == "Liczba półek"
    con.close()

    strona = TestClient(app_mod.app).get("/produkt/137487").text
    assert "Findingi (9)" in strona                    # karta pokazuje komplet
    assert "1 otwartych · 8 rozstrzygniętych" in strona
    assert strona.count('class="f zamkniety"') == 8    # i widać które


def test_statystyki_dzienne_licza_trzy_strumienie_osobno(tmp_path, monkeypatch):
    """Poprawka rozstrzygnięta w poniedziałek idzie w partii we wtorek,
    a potwierdzenie przychodzi w środę — trzy daty, trzy wiersze."""
    from atrybuty import db, eksport_panelu, weryfikacja, wizja, zapytania
    import atrybuty.pipeline as pipeline
    from atrybuty.model import Produkt
    baza = tmp_path / "p.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con); eksport_panelu.przygotuj_baze(con)
    weryfikacja.przygotuj_baze(con) if hasattr(weryfikacja, "przygotuj_baze") else \
        con.executescript(weryfikacja.SCHEMA)
    db.zapisz_przebieg(con, "t.csv", [Produkt(
        id="1", nazwa="Szafa", producent="BRW", kolekcja="", zdjecie="", styl="",
        kategoria="szafa")], [])

    con.execute("INSERT INTO decyzje (produkt_id,atrybut,hasz_starej,status,"
                "nowa_wartosc,regula_id,uzytkownik,utworzono,partia_id) "
                "VALUES ('1','Materiał','h1','zastosowana','dąb','R','local',"
                "'2026-09-14T10:00:00',7)")
    con.execute("INSERT INTO decyzje (produkt_id,atrybut,hasz_starej,status,"
                "nowa_wartosc,regula_id,uzytkownik,utworzono) "
                "VALUES ('1','Styl','h2','falszywy_alarm',NULL,'R','local',"
                "'2026-09-14T11:00:00')")
    con.execute("INSERT INTO partie (id,utworzono,plik,ile,wycofana) "
                "VALUES (7,'2026-09-15T09:00:00','p.xlsx',1,0)")
    con.execute("INSERT INTO weryfikacje (partia_id,produkt_id,atrybut,hasz_starej,"
                "stan,sprawdzono) VALUES (7,'1','Materiał','h1','weszlo',"
                "'2026-09-16T08:00:00')")
    con.commit()

    wg = {w["dzien"]: w for w in zapytania.statystyki_dzienne(con)}
    assert wg["2026-09-14"]["decyzji"] == 2
    assert wg["2026-09-14"]["poprawek"] == 1 and wg["2026-09-14"]["falszywych"] == 1
    assert wg["2026-09-14"]["w_partiach"] == 0      # wysyłka to inny dzień
    assert wg["2026-09-15"]["partii"] == 1 and wg["2026-09-15"]["w_partiach"] == 1
    assert wg["2026-09-15"]["decyzji"] == 0
    assert wg["2026-09-16"]["sprawdzonych"] == 1
    assert wg["2026-09-16"]["weszlo"] == 1
    assert wg["2026-09-16"]["skutecznosc"] == 1.0
    assert wg["2026-09-14"]["skutecznosc"] is None   # nic nie sprawdzano

    r = zapytania.postep_razem(con, 1)
    assert r["decyzji"] == 2 and r["w_partiach"] == 1 and r["weszlo"] == 1
    assert r["czeka_na_eksport"] == 0               # jedyna poprawka już poszła
    con.close()


def test_strona_postepu_sie_renderuje(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from atrybuty import db, eksport_panelu, wizja
    import atrybuty.pipeline as pipeline, atrybuty.app as app_mod
    from atrybuty.model import Produkt
    baza = tmp_path / "ps.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con); eksport_panelu.przygotuj_baze(con)
    db.zapisz_przebieg(con, "t.csv", [Produkt(
        id="1", nazwa="Szafa", producent="BRW", kolekcja="", zdjecie="", styl="",
        kategoria="szafa")], [])
    db.zapisz_decyzje(con, "1", "Materiał", None, "zastosowana", "dąb", "R")
    con.close()

    strona = TestClient(app_mod.app).get("/postep").text
    assert "Postęp prac" in strona
    assert "rozstrzygnięte w kolejce" in strona
    assert "potwierdzone w kolejnym pliku" in strona
    # link w nawigacji innych stron
    assert '/postep' in TestClient(app_mod.app).get("/rozstrzygniete").text


def _panel_z_wartosciami(tmp_path, monkeypatch):
    """Słownik panelu: Materiał (3 wartości) i Kształt (2)."""
    import yaml
    from atrybuty import config, panel_format as pf
    monkeypatch.setattr(config, "KATALOG_CONFIG", tmp_path)
    for atryb, nazwa in (("PLIK_SLOWNIKA", "slownik_idow.yaml"),
                         ("PLIK_ETYKIET", "etykiety_panelu.yaml"),
                         ("PLIK_ATRYBUTOW", "atrybuty_panelu.yaml"),
                         ("PLIK_WZORCA", "wzorzec_panelu.yaml"),
                         ("PLIK_ZMIAN_NAZW", "zmiany_nazw.yaml")):
        if hasattr(pf, atryb):
            monkeypatch.setattr(pf, atryb, tmp_path / nazwa)
    (tmp_path / "slownik_idow.yaml").write_text(yaml.safe_dump({
        "Materiał": {"plyta meblowa": ["1"], "szklo": ["2"], "metal": ["3"]},
        "Kształt": {"prostokatny": ["4"], "owalny": ["5"]}},
        allow_unicode=True), encoding="utf-8")
    (tmp_path / "etykiety_panelu.yaml").write_text(yaml.safe_dump({
        "Materiał": {"plyta meblowa": "płyta meblowa", "szklo": "szkło",
                     "metal": "metal"},
        "Kształt": {"prostokatny": "prostokątny", "owalny": "owalny"}},
        allow_unicode=True), encoding="utf-8")
    (tmp_path / "atrybuty_panelu.yaml").write_text(yaml.safe_dump({
        "Materiał": {"id": "10", "status": "ACTIVE"},
        "Kształt": {"id": "11", "status": "ACTIVE"},
        "Szerokość": {"id": "12", "status": "ACTIVE"}}, allow_unicode=True),
        encoding="utf-8")
    config.wyczysc_cache()
    return config, pf


def test_lista_wielowartosciowych_zapisuje_sie_i_wraca(tmp_path, monkeypatch):
    """Panel nie mówi, które atrybuty biorą kilka wartości — odklikujemy to
    sami i musi przeżyć restart."""
    config, _ = _panel_z_wartosciami(tmp_path, monkeypatch)
    try:
        config.przelacz_wielowartosciowy("Materiał", True)
        assert "Materiał" in config.wielowartosciowe()
        assert (tmp_path / "wielowartosciowe.yaml").exists()

        config.wyczysc_cache()                    # jak po restarcie
        assert config.wielowartosciowe() == {"Materiał"}

        config.przelacz_wielowartosciowy("Materiał", False)
        assert config.wielowartosciowe() == set()
    finally:
        config.wyczysc_cache()


def test_kilka_wartosci_tylko_tam_gdzie_wolno(tmp_path, monkeypatch):
    """Wpisanie „szkło, metal” w atrybut jednowartościowy zrobiłoby w sklepie
    nową, śmieciową wartość o takiej nazwie."""
    import atrybuty.app as app_mod
    config, _ = _panel_z_wartosciami(tmp_path, monkeypatch)
    try:
        config.zapisz_wielowartosciowe(["Materiał"])
        assert app_mod._zle_wielokrotnosci("Materiał", "szkło, metal") == ""
        assert app_mod._zle_wielokrotnosci("Kształt", "prostokątny") == ""
        blad = app_mod._zle_wielokrotnosci("Kształt", "prostokątny, owalny")
        assert "przyjmuje jedną wartość" in blad
        assert "/atrybuty" in blad            # mówi, gdzie to zmienić
    finally:
        config.wyczysc_cache()


def test_wykrywanie_wielowartosciowych_z_danych(tmp_path, monkeypatch):
    """Dowodem jest wartość, której WSZYSTKIE człony są w słowniku.

    Przecinek w polu tekstowym („Szafa 3-drzwiowa, biała”) listą nie jest.
    """
    _, pf = _panel_z_wartosciami(tmp_path, monkeypatch)
    try:
        wykryte = pf.wykryj_wielowartosciowe([
            ("Materiał", "płyta meblowa, szkło"),
            ("Materiał", "płyta meblowa, metal"),
            ("Materiał", "płyta meblowa"),            # jedna wartość
            ("Kształt", "prostokątny, coś dziwnego"),  # człon spoza słownika
            ("Szerokość", "220, 240"),                 # atrybut bez słownika
        ])
        assert set(wykryte) == {"Materiał"}
        assert wykryte["Materiał"]["ile"] == 2
    finally:
        from atrybuty import config
        config.wyczysc_cache()


def test_strona_atrybutow_pokazuje_wartosci_i_przelacznik(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import atrybuty.pipeline as pipeline, atrybuty.app as app_mod
    from atrybuty import db, wizja
    from atrybuty.model import Produkt
    config, _ = _panel_z_wartosciami(tmp_path, monkeypatch)
    baza = tmp_path / "a.db"
    monkeypatch.setattr(pipeline, "BAZA", baza)
    monkeypatch.setattr(app_mod, "BAZA", baza)
    con = db.polacz(baza); wizja.przygotuj_baze(con)
    db.zapisz_przebieg(con, "t.csv", [Produkt(
        id="1", nazwa="Komoda", producent="BRW", kolekcja="", zdjecie="", styl="",
        kategoria="komoda",
        atrybuty_surowe={"Materiał": "płyta meblowa, szkło"})], [])
    con.close()
    try:
        config.zapisz_wielowartosciowe([])
        klient = TestClient(app_mod.app)
        strona = klient.get("/atrybuty").text
        assert "Materiał" in strona and "płyta meblowa" in strona
        assert "Szerokość" in strona and "pole wolne" in strona   # bez słownika
        assert strona.count("jedna wartość") >= 2

        # przełącznik zapisuje od razu
        odp = klient.post("/atrybuty/przelacz",
                          data={"atrybut": "Materiał", "wiele": "1"})
        assert "wiele wartości" in odp.text
        assert "Materiał" in config.wielowartosciowe()

        # wykrywanie z danych proponuje to samo
        config.zapisz_wielowartosciowe([])
        z_danych = klient.get("/atrybuty?wykryj=1").text
        assert "1 prod." in z_danych
        klient.post("/atrybuty/wykryte", follow_redirects=False)
        assert config.wielowartosciowe() == {"Materiał"}
    finally:
        config.wyczysc_cache()
