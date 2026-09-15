# Kontrola atrybutów OXM

System wykrywania i weryfikacji błędów w atrybutach produktów TwojeMeble.pl.
Wejście: cykliczny eksport CSV ze sklepu (od 15.09.2026 z kolumnami
`typ`/`podtyp`, więc bez osobnego eksportu kategorii).
Wyjście: plik poprawek do zaimportowania w sklepie (i plik cofający).

**Zasada nadrzędna: system nigdy nie zmienia danych sam.** Produkuje wyłącznie
propozycje. Do pliku wynikowego trafia tylko to, co człowiek kliknął.

**Zasada druga: rozwiązania płatne tylko dla przypadków spornych.** Warstwy
L1–L2 są deterministyczne i darmowe; Gemini (L3) dostaje tylko to, co
przepuści bramka kosztowa.

## Szybki start

```bash
pip install -r requirements.txt

# Jeśli projekt leży na dysku sieciowym albo w katalogu montowanym
# (np. folder udostępniony do Cowork), SQLite nie dostanie tam blokad
# plikowych i wywali się na "disk I/O error". Wtedy wskaż bazę poza montem:
export ATRYBUTY_DB=~/atrybuty.db

# 1. Wygeneruj zakresy statystyczne per kategoria (config/schema.yaml)
python -m atrybuty.pipeline schema dane/products-2026-09-15.csv

# 2. Wczytaj dane, uruchom detektory, zapisz do SQLite
#    (--kategorie tylko dla starszych eksportów bez kolumny `typ`)
python -m atrybuty.pipeline import dane/products-2026-09-15.csv

# 3. Odpal aplikację
uvicorn atrybuty.app:app --reload --port 8083
```

Podstrony:

| | |
|---|---|
| `/anomalie` | kolejka weryfikacji — filtry, grupowanie, akcje, link do panelu sklepu |
| `/braki` | produkty bez danych — do ponownego zaciągnięcia ze źródła, z eksportem CSV |
| `/reguly` | katalog reguł ze skutecznością — podgląd, dodawanie, usuwanie, wyłączanie |
| `/import` | wgranie nowego eksportu z przeglądarki, postęp na żywo, historia przebiegów |

Wdrożenie na Mac Mini (Docker + GitHub): **[WDROZENIE.md](WDROZENIE.md)**.

Testy: `python -m pytest tests/ -q`

## Wynik przebiegu na eksporcie z 15.09.2026 (32 229 produktów)

| | |
|---|---|
| kategoria ze sklepu / zgadnięta z nazwy | 31 707 / 522 |
| produkty bez danych (wyłączone, /braki) | 1 854 |
| findingów | 15 652 |
| grup decyzyjnych | 2 364 |
| gotowe do jednego kliknięcia (0 zł) | 4 150 |
| kandydaci do Gemini (L3) | 412 |

Grupowanie to najważniejsza liczba w tej tabeli: 15 652 findingi to 2 364
realne decyzje, bo ponad tysiąc produktów z `drewno, drewno` rozstrzyga się
jednym kliknięciem, nie tysiącem.

## Struktura

```
config/
  ustawienia.yaml              link do panelu sklepu, wielkość strony
  reguly.yaml                  reguły edytowalne z UI (NADPISYWANY przez aplikację)
  kategorie.yaml               klasyfikator kategorii z nazwy (fallback)
  mapa_kategorii_sklepu.yaml   taksonomia sklepu (BigQuery `type`) -> nasze klucze
  slowniki.yaml                typy atrybutów, wartości kanoniczne, sprzeczności, relacje
  schema.yaml                  GENEROWANY: zakresy liczbowe per kategoria
atrybuty/
  model.py        Produkt, Finding, bramka kosztowa (PROG_DO_WIZJI, WIDOCZNE_NA_ZDJECIU)
  tekst.py        normalizacja napisów, ekstraktory z nazwy produktu
  kategorie.py    przypisanie kategorii (sklep > nazwa)
  normalizacja.py wartości -> postać kanoniczna (+ findingi L1)
  schema_gen.py   generator zakresów: mediana + MAD, nie średnia
  detektory.py    reguły L1 i L2
  db.py           SQLite: produkty, findingi, decyzje, przebiegi
  zapytania.py    filtrowanie kolejki
  app.py          endpoint FastAPI + HTMX (htmx serwowany z atrybuty/static/)
  reguly.py       katalog reguł + operacje z podstrony /reguly
  importer.py     wgranie pliku z przeglądarki, przebieg w tle
  wizja.py        warstwa L3: pytania, klient Gemini, cache, kalibracja
  eksport.py      plik poprawek + plik cofający
```

## Warstwy detekcji

**L1 — struktura i słowniki.** Format wartości (`Waga: 46, 46`), wartości spoza
słownika, literówki (rapidfuzz), duplikaty i kolejność w listach, klucze-śmieci
(`Do poprawy`), braki atrybutów wymaganych dla kategorii.

**L2 — statystyka i spójność.** Zakresy per kategoria liczone medianą i MAD
(nie średnią — przy tym poziomie zaśmiecenia średnia sama jest zepsuta przez
outliery). Test skali: jeśli wartość ×10 lub ÷10 wpada w normę kategorii, to
nie outlier tylko pomyłka jednostki — i znamy propozycję. Sprzeczności logiczne,
relacje między wymiarami, nazwa produktu jako niezależne źródło prawdy,
spójność w rodzinie produktów.

**L3 — Gemini.** Jedno zamknięte pytanie na wywołanie (nigdy „opisz produkt"),
wymuszony `response_schema` z obowiązkową opcją `nie_widac`, zdjęcie skalowane
do 512 px przed wysłaniem, cache po haszu (zdjęcie + pytanie + wartość + model).
Flash do wolumenu, Pro do spornych. Szczegóły niżej.

**L4 — źródła zewnętrzne (do zrobienia).** Feedy i katalogi producentów jako
referencja wymiarów i wag.

## Bramka kosztowa

Każdy finding ma `pewnosc` (0–1), która decyduje o routingu:

| warunek | trafia |
|---|---|
| `pewnosc >= 0.85` i jest propozycja | kolejka, przycisk „zastosuj”, 0 zł |
| `pewnosc < 0.85`, atrybut w `WIDOCZNE_NA_ZDJECIU`, produkt ma zdjęcie | kandydat do Gemini |
| atrybut niewidoczny na zdjęciu (waga, udźwig, klasa płyty) | omija L3, człowiek albo L4 |

Bez tej bramki do Gemini poszłoby 41 tys. zdjęć zamiast 777.

## Warstwa wizyjna (Gemini)

Klucz API **nie trafia do repo**. Ustaw go raz:

```bash
export GEMINI_API_KEY="..."            # albo:
echo "..." > ~/.atrybuty-gemini-key && chmod 600 ~/.atrybuty-gemini-key
```

```bash
# ile to będzie kosztować — bez ani jednego wywołania API
python -m atrybuty.pipeline wizja --na-sucho

# próbka 200 sztuk w losowej kolejności (kalibracja przed pełnym przebiegiem)
python -m atrybuty.pipeline wizja --limit 200 --losowo

# CSV do ręcznej oceny → wypełnij kolumnę TWOJA_OCENA → raport trafności
python -m atrybuty.pipeline kalibracja eksport
python -m atrybuty.pipeline kalibracja raport

# dopiero po kalibracji: reszta kandydatów
python -m atrybuty.pipeline wizja
```

Przydatne przełączniki: `--atrybut "Liczba szuflad"`, `--producent Halmar`,
`--sporne` (model Pro zamiast Flash), `--wszystko` (także te z werdyktem).

### Weryfikacja na żądanie (bez przebiegu wsadowego)

Przy każdym findingu, którego atrybut da się rozstrzygnąć ze zdjęcia, jest
przycisk **„Sprawdź zdjęciem"** — jedno zapytanie do Gemini (~$0,0007) dla
tego jednego przypadku, werdykt wraca w miejscu bez przeładowania strony.
Płacisz wyłącznie za to, co klikniesz, więc można zacząć od tego, a przebieg
wsadowy odpalić dopiero wtedy, gdy kalibracja pokaże, że wynikom warto ufać.

W trakcie zapytania przycisk zmienia się w „Sprawdzam…" ze spinnerem, reszta
akcji w wierszu gaśnie, a pod findingiem miga szkielet „Gemini ogląda zdjęcie".
Nieudana próba (timeout, zły klucz) przywraca przycisk, żeby dało się powtórzyć.

Po werdykcie od razu jest właściwa akcja: przy `niezgodne` przycisk
**„Zastosuj «3-szuflady»"**, przy `zgodne` — **„Zdjęcie potwierdza — zamknij"**
(zamyka finding jako fałszywy alarm, co liczy się do skuteczności reguły).
Drugie kliknięcie tego samego findingu idzie z cache i kosztuje zero.

Werdykty widać też w filtrze „werdykt Gemini" i na kaflu z niezgodnościami.

Koszt liczony jest na bieżąco z `usageMetadata` i pokazywany po przebiegu.
Cache sprawia, że kolejne wgranie eksportu nie płaci za niezmienione produkty.

## Produkty bez danych

Produkt z zerem albo dwoma atrybutami nie jest „produktem z błędami" — nie da
się go naprawić ręcznie, bo nie ma czego poprawiać. Takie produkty (1 876 przy
pierwszym przebiegu) są wyłączone z detektorów i lądują na `/braki`, skąd
eksportujesz listę ID z linkami do panelu i wracasz z nią do źródła.

Osobny kubełek to `bez_wymiarow` (219) — produkt ma dość danych, żeby reguły
miały co sprawdzać, a sam brak wymiaru jest normalnym findingiem, więc zostaje
w analizie i na `/braki` figuruje tylko informacyjnie.

Progi: `MIN_ATRYBUTOW` i `WYMIARY_PODSTAWOWE` w `atrybuty/model.py`.

## Stan między wgraniami pliku

Decyzje są kluczowane po `(produkt_id, atrybut, hasz starej wartości)`, więc
przeżywają wgranie kolejnego eksportu. Po nowym pliku system sam rozpoznaje:
poprawione (wartość się zmieniła), ignorowane (oznaczone jako fałszywy alarm),
wciąż otwarte.

## Strojenie reguł

Reguły mieszkają w `config/*.yaml`, nie w kodzie — zmieniasz je bez deploya.
Najczęstsze zmiany:

- nowa sprzeczność / relacja / klucz-śmieć, albo wyłączenie reguły → podstrona `/reguly`
- nowa wartość słownikowa → `config/slowniki.yaml`, sekcja `atrybuty`
- nowy typ kategorii ze sklepu → `config/mapa_kategorii_sklepu.yaml`
- za ostry / za luźny zakres wymiaru → `config/schema.yaml`, pole
  `min_dopuszczalne` / `max_dopuszczalne` w danej kategorii
- reguła generuje za dużo fałszywych alarmów → filtruj po niej w kolejce,
  zobacz udział „fałszywy alarm”, popraw próg albo wyłącz

Po zmianie `schema.yaml` regeneracja go nadpisze — dlatego ręczne korekty
warto trzymać w commicie i po regeneracji sprawdzić diff.

## Do zrobienia

- [x] L3: integracja z Gemini (`wizja.py`) — zostaje kalibracja na próbce
- [ ] L4: feedy producentów
- [ ] potwierdzenie formatu pliku importu w panelu sklepu
- [ ] przeniesienie na Mac Mini (Docker + deploy z GitHuba, jak `terminowosc`)
- [ ] wskaźnik jakości danych per producent
