# Plan: luki w filtrach

Stan: plan do recenzji (claudex-loop). Autor: Claude (koordynator i budujący).
Recenzent planu i inspektor kodu: Codex.

## Cel

Klient filtruje listę produktów po atrybutach („Na nóżkach”, „Oświetlenie”,
„Rodzaj obicia”…). Produkt bez wartości znika z wyników po zaznaczeniu filtra.
Diagnoza z 10.10.2026 (next.twojemeble.pl, 115 kategorii) pokazała duże luki:
„Na nóżkach” ma wartość u 19% łóżek, rodzaj obicia u 9% łóżek tapicerowanych,
oświetlenie u 7% szaf.

Narzędzie ma:
1. **trzymać konfigurację filtrów sklepu** — które atrybuty są filtrami w której
   naszej kategorii — edytowalną w UI;
2. **przy każdym imporcie eksportu** sprawdzać, czy produkty mają atrybuty
   potrzebne do filtrowania w swojej kategorii (pokrycie, braki, producenci);
3. **tam, gdzie się da, proponować wartość z danych, które już mamy**, z widocznym
   prawdopodobieństwem, do akceptacji w istniejącej kolejce;
4. **braki bez propozycji też wrzucać do kolejki** (decyzja użytkownika), ale
   pogrupowane tak, by rozstrzygać je grupą.

Zasady z CLAUDE.md obowiązują: system nigdy nie zmienia danych sam, licznik
przy akcji = jej zasięg, w razie wątpliwości nie proponujemy.

## Kryteria odbioru

1. `config/filtry.yaml` istnieje, jest zasilony z diagnozy 10.10 (filtry
   jednowartościowe z głównych kategorii strony, przemapowane na nasze klucze
   kategorii przez `config/mapa_kategorii_sklepu.yaml`) i jest edytowalny
   z zakładki `/filtry` (włącz/wyłącz filtr w kategorii, dodaj filtr spoza listy).
2. Import eksportu (`pipeline.komenda_import` i `importer` w UI) generuje findingi:
   - `L2-LUKA-PODTYP` — podkategoria sklepu wyznacza wartość, atrybut pusty;
   - `L2-LUKA-PODTYP-SPRZECZNE` — podkategoria mówi co innego niż atrybut;
   - `L2-LUKA-NAZWA` — słowo w nazwie wyznacza wartość (LED, welur, …);
   - `L2-LUKA-RODZINA` — rodzina produktów zgodnie ma wartość, ten jest pusty;
   - `L1-LUKA-BRAK` — filtr obowiązuje w kategorii, wartości brak i żadne
     źródło jej nie zna (bez propozycji).
   Najwyżej jeden finding luki na (produkt, atrybut); gdy kilka źródeł coś mówi,
   wygrywa najwyższe prawdopodobieństwo.
3. Dla atrybutów objętych `filtry.yaml` nie powstaje równolegle
   `L1-BRAK-WYMAGANEGO` (dziś powstaje przy pokryciu ≥95%) — brak jednej komórki
   = jedno zgłoszenie.
4. Każda propozycja ma prawdopodobieństwo w polu `pewnosc` (0–1), pokazywane
   w kolejce jako „prawdopodobieństwo NN%”, liczone z siły dowodu:
   - podkategoria: 0,92 (sprzeczność: 0,88);
   - nazwa: 0,80;
   - rodzina: `min(0,95, (zgodnych + 1) / (z_wartoscia + 2))`, czyli 3/3 → 0,80,
     12/12 → 0,93, 9/10 → 0,83; poniżej progu zgodności 0,9 — brak propozycji.
   Kalibracja na decyzjach to osobny krok, poza tym planem.
5. Propozycja ma wartość ze słownika panelu (`config/etykiety_panelu.yaml`,
   klucz `norm(etykieta)`), w zapisie kanonicznym („ekoskóra”). Reguła
   z wartością spoza słownika jest pomijana z ostrzeżeniem w logu.
6. Atrybuty wyjęte z obiegu (`config.atrybuty_wylaczone()`, np. `Styl`) i reguły
   wyłączone w `/reguly` nie produkują luk — przez istniejące filtrowanie na końcu
   `detektory.uruchom`.
7. Produkty `do_zrodla` (puste/szczątkowe) nie dostają luk — są na `/braki`.
7a. **Składowe** (recenzja LUKI-01): wartość widoczna dla frontu to atrybut
   produktu **albo** wartość z nieodciętych składowych (`skladowe_odciete=False`).
   Komórka z wartością tylko w składowych nie jest luką — obsługuje ją L0
   (`L0-ZE-SKLADOWYCH`/konflikt). Przy odciętych składowych liczy się wyłącznie
   atrybut. Rodzina i pokrycie używają tej samej „wartości efektywnej”.
   Dodatkowo w `pipeline.wszystkie_findingi` (wspólny punkt obu ścieżek importu)
   finding luki odpada, gdy dla tego samego (produkt, atrybut) jest finding L0 —
   bo oba mają ten sam klucz decyzji (produkt, atrybut, hasz pustej starej).
8. Zakładka `/filtry`:
   - tabela pokrycia: nasza kategoria × filtr z konfiguracji, odsetek z wartością,
     liczba braków, ile z nich ma propozycję (wg źródła), link do kolejki
     zawężonej do `kategoria` + `atrybut` + reguły luk;
   - rozbicie braków na producentów dla wybranej pary kategoria–filtr
     (producent, braki / jego produkty) i eksport CSV listy produktów bez
     wartości (id, nazwa, producent, kolekcja, link do panelu);
   - edycja konfiguracji (pkt 1).
9. Reguły luk są w `reguly.WBUDOWANE` (widoczne i wyłączalne w `/reguly`).
10. Grupowanie w kolejce: `grupa` dla `L1-LUKA-BRAK` = `L1-LUKA-BRAK|kategoria|atrybut|producent`;
    dla propozycji — wg źródła, atrybutu i wartości (identyczne przypadki jedną
    decyzją, w zakresie aktywnych filtrów — istniejąca mechanika).
11. Wszystkie testy przechodzą; nowe testy opisują zachowanie po polsku.

## Podejście

- `config/filtry.yaml` — `{kategoria: [atrybuty-filtry]}` + meta (skąd, kiedy).
  Ziarno generuje jednorazowy skrypt z `docs/diagnoza-filtrow-2026-10-10.csv`
  (zapisujemy surowe pomiary w repo: małe, bez danych osobowych) i mapy kategorii.
  Odczyt i zapis przez `config.py` (wzór: `wielowartosciowe.yaml` — lru_cache
  + `cache_clear` po zapisie).
- `config/luki.yaml` — reguły źródeł (podtyp, nazwa, rodzina) — już szkic.
  Lista `filtry` i `prog_filtra` z luki.yaml znika: obowiązywanie filtra bierze
  się z `filtry.yaml`.
- `atrybuty/luki.py` — już szkic; zmiany: obowiązywanie z `filtry.yaml`,
  `L1-LUKA-BRAK`, wzór prawdopodobieństwa rodziny, `pokrycie()` do zakładki,
  wartość efektywna ze składowych, identyfikator modelu.
- **Słownik bez trwałego cache** (recenzja LUKI-04): etykiety panelu czytane
  świeżo raz na przebieg `luki.uruchom` (przekazywane w dół), nie w `lru_cache`.
  Konfiguracje `filtry.yaml`/`luki.yaml` — `lru_cache` z `cache_clear` po zapisie
  i w `config.wyczysc_cache`. Test: import → zmiana etykiet → ponowny import
  w tym samym procesie używa nowych etykiet.
- **Przemianowania** (recenzja LUKI-05): `panel_format.migruj_config` przepisuje
  też `filtry.yaml` i `luki.yaml` (te same reguły co `reguly.yaml`: klucze
  i wartości-napisy będące nazwą atrybutu); dodatkowo przy odczycie konfiguracji
  nazwy przechodzą przez `config.zmiany_nazw()['atrybuty']`, a wartości reguł
  przez `zmiany_nazw()['wartosci']` (gdy mapa jest). **Unieważnianie cache**
  (recenzja LUKI-07): `panel_format.dopisz_zmiany_nazw` po zapisie pliku woła
  `config.zmiany_nazw.cache_clear()` oraz czyszczenie cache `filtry.yaml`
  i `luki.yaml` — przed `migruj_config` i przed kolejną normalizacją; to samo
  w każdej ścieżce zapisu mapy (`naucz_ze_slownika`, `naucz_z_pliku`, jeśli ją
  piszą). Test w jednym procesie: import starego eksportu (rozgrzewa cache) →
  wgranie słownika z przemianowaniem „Na nóżkach” → „Nóżki” rzeczywistą ścieżką
  zapisu → ponowny import starego eksportu → produkty mają „Nóżki”, pokrycie
  i luki liczone dla „Nóżki”, brak pozornych braków.
- `detektory.uruchom` — po istniejących detektorach: `out += luki.uruchom(do_analizy)`;
  usunięcie `L1-BRAK-WYMAGANEGO` dla (produkt, atrybut) objętych `filtry.yaml`.
  Przed końcowym filtrem `wylaczone`/`atrybuty_wylaczone`.
- Rodzina liczona tylko na `do_analizy` (bez produktów do źródła) — tak jak
  `l2_rodzina`.
- `app.py` — `GET /filtry`, `GET /filtry/producenci?kategoria=&atrybut=`,
  `GET /filtry/braki.csv?kategoria=&atrybut=&producent=`,
  `POST /filtry/konfiguracja` (włącz/wyłącz/dodaj). Szablon `templates/filtry.html`
  z `_motyw.html`. Link w nawigacji.
- Kolejka: etykieta „prawdopodobieństwo NN%” zamiast gołego „NN%” przy regułach
  luk (`anomalie.html`, linia z `w.pewnosc`).
- **Filtr kolejki po rodzinie reguł** (recenzja LUKI-03): `Filtr.regula` przyjmuje
  prefiks zakończony `*` (np. `L2-LUKA-*`), a `zapytania._warunki` zamienia go na
  `f.regula_id LIKE 'L2-LUKA-%'`; bez gwiazdki — równość jak dziś. Ponieważ
  wszystkie zapytania kolejki (lista, liczniki, statystyki grup, podgląd grupy,
  zasięg akcji grupowych przez `Filtr.z_query`) idą przez `_warunki`, link
  z `/filtry` i zasięg decyzji obejmują ten sam zbiór. Linki z `/filtry`:
  `regula=L2-LUKA-*` (propozycje) i `regula=L1-LUKA-BRAK` (braki), zawsze
  z `kategoria` i `atrybut`. Test: licznik „×N” grupy pod filtrem z gwiazdką
  = liczba findingów, które akcja zmieni.
- Eksport do panelu bez zmian: `L1-LUKA-BRAK` nie ma propozycji, więc „do importu”
  wymaga własnej wartości — tak jak dziś przy findingach bez propozycji.

### Kluczowe decyzje i kompromisy

- **Konfiguracja z diagnozy, nie z progu w danych** — decyzja użytkownika.
  Filtr, którego prawie nikt nie wypełnił (obicie w pufach: 2%), byłby przez
  próg przeoczony, a to właśnie największe luki.
- **Braki bez propozycji do kolejki** — decyzja użytkownika. Ryzyko: kilkadziesiąt
  tysięcy findingów. Łagodzimy grupowaniem po kategorii/atrybucie/producencie
  (~kilkaset grup) i niższą wagą (`info`), żeby nie spychały w dół zgłoszeń
  z propozycją.
- **Rodzina: kolekcja vs model** — liczebniki (drzwi, szuflady, półki, drążki),
  oświetlenie i zestawy (materac, stelaż, pojemnik) różnią się między wersjami
  z tej samej kolekcji, więc dla nich rodzina = **model**; cechy linii (nóżki,
  obicie) = kolekcja. **Model** (recenzja LUKI-02) nie jest `baza_nazwy`
  (łączy „Szafa Alfa 100” z „200”, a rozdziela kolory). Identyfikator modelu,
  konserwatywnie:
  1. `kod producenta` z eksportu (np. „IMPERIAL TYP 01” — wspólny dla wariantów
     kolorystycznych, różny dla konstrukcji), znormalizowany, + producent + kategoria;
  2. gdy go brak — **żadnej propozycji z rodziny** dla atrybutów modelowych
     (recenzja LUKI-06: same wymiary nie dowodzą tożsamości — łóżko z materacem
     i bez ma te same wymiary zewnętrzne; szafa z LED i bez — też). Luka
     zostaje wtedy jako `L1-LUKA-BRAK`.
  Dodatkowo dla atrybutów **wyposażenia** (Oświetlenie, Materac w zestawie,
  Stelaż w zestawie, Z pojemnikiem) — gdzie nawet jeden kod producenta bywa
  sprzedawany w wariantach z wyposażeniem i bez — prawdopodobieństwo z rodziny
  jest ograniczone do 0,80, czyli zawsze poniżej `PROG_AUTO` (0,85). Co to daje
  (recenzja LUKI-08 — doprecyzowanie): propozycja nie trafia do kubełka
  automatycznego (`routing=auto`) ani do akcji „zatwierdź gotowe” produktu.
  **Nie blokuje** świadomego zatwierdzenia grupy „Zastosuj ×N” przez człowieka —
  to decyzja człowieka z widocznym prawdopodobieństwem i podglądem grupy,
  a jej zablokowanie uniemożliwiłoby praktyczne uzupełnienie tysięcy luk.
  Żeby taka decyzja dotyczyła jednego mebla, a nie całej kategorii, `grupa`
  propozycji z rodziny zawiera identyfikator rodziny:
  `L2-LUKA-RODZINA|atrybut|wartość|producent|kod producenta` (dla kolekcji:
  `…|producent|kolekcja`). „Zastosuj ×N” obejmuje więc tylko warianty jednego
  modelu. Liczebniki (drzwi, szuflady, półki, drążki) przy wspólnym kodzie
  producenta — do 0,95.
  Testy: warianty kolorystyczne z tym samym kodem producenta dzielą wartość;
  dwa produkty z jednej kolekcji o identycznych wymiarach, bez kodu producenta,
  różniące się wyposażeniem — brak propozycji; propozycja wyposażenia
  z rodziny 12/12 ma prawdopodobieństwo 0,80 i routing inny niż `auto`;
  dwie rodziny (dwa kody producenta) z tą samą propozycją „Materac w zestawie:
  tak” są w dwóch różnych grupach, a akcja grupowa na jednej nie zmienia drugiej.
- **Jedno zgłoszenie na komórkę** — najsilniejsze źródło wygrywa; dowód opisuje
  to źródło.

### Poza zakresem (kolejne etapy)

- Etap 2: feedy producentów (L4) dla atrybutów tekstowych — mapowanie pól feedu
  na atrybuty słownikowe.
- Etap 3: Gemini po zdjęciu dla cech wizualnych (nóżki, obicie) — płatne, za zgodą.
- Kalibracja prawdopodobieństw na decyzjach.
- Automatyczny odczyt filtrów ze strony (wymaga hasła do next w `.env`).

## Założenia (z źródłami)

- Podtyp jest w eksporcie (`pipeline.KOLUMNY_PODTYPU`, `Produkt.podtyp`) — eksport
  30.09: „Komoda na nóżkach” 947, „Łóżka z pojemnikiem” 613, „Stoły rozkładane” 498.
- Słownik wartości: `config/etykiety_panelu.yaml` `{atrybut: {norm: etykieta}}`,
  klucz `tekst.norm` — jak w `panel_format.id_dla`.
- Kolejka pokazuje `pewnosc` jako procent (`templates/anomalie.html:442`).
- Próg „jednego kliknięcia”: `model.PROG_AUTO = 0.85` — podkategoria nad progiem,
  nazwa i większość rodzin pod nim.
- Wydajność na eksporcie 30.09 (szacunek): rodzina ~6 tys. propozycji, podtyp
  ~130 + 26 sprzeczności, nazwa ~500 (głównie LED).
- Filtry wielowartościowe strony (kolor, materiał, styl, pomieszczenie) są poza
  zakresem — ich suma nie mówi o brakach.

## Ryzyka

- Rozmiar kolejki po `L1-LUKA-BRAK`. Miara: liczba findingów i grup po imporcie
  eksportu 30.09 — raportujemy w wynikach.
- Czas importu: rodzina to grupowanie O(n) na atrybut — pomijalne przy 32 tys.
- Mapowanie kategorii strony → nasze może mieć dziury (nasze `lawa`, `stolik`…);
  ziarno raportuje kategorie bez mapowania, a UI pozwala dodać filtr ręcznie.

## Weryfikacja

1. `python3 -m pytest -q` — wszystko zielone, nowe testy (także te z sekcji
   recenzji: składowe, model, filtr z gwiazdką, świeży słownik, przemianowanie):
   podtyp (luka + sprzeczność + dopuszczalne), nazwa (LED, kategoria spoza listy),
   rodzina (kolekcja vs model, próg zgodności, wzór prawdopodobieństwa),
   `L1-LUKA-BRAK` bez propozycji, dedup z `L1-BRAK-WYMAGANEGO`, jedna propozycja
   na komórkę, wartość spoza słownika pominięta, atrybut wyłączony pominięty,
   `/filtry` renderuje się i edycja konfiguracji zapisuje plik, CSV braków.
2. Import eksportu 30.09 do bazy tymczasowej:
   `ATRYBUTY_DB=<scratch>/luki.db python3 -m atrybuty.pipeline import ~/Downloads/products-2026-09-30_050101.csv`
   — oczekiwane: liczby findingów `L2-LUKA-*` i `L1-LUKA-BRAK` w raporcie,
   import kończy się bez błędu, czas porównywalny z obecnym (±30%).
3. Ręcznie: `/filtry` na bazie tymczasowej — tabela pokrycia, rozbicie producentów
   dla „łóżko · Na nóżkach”, CSV braków; kolejka zawężona linkiem z `/filtry`.
