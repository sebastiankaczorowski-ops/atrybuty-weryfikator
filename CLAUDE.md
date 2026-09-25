# Kontrola atrybutów OXM — pamięć projektu

Narzędzie wykrywa i pomaga poprawiać błędy w atrybutach produktów
TwojeMeble.pl. Wejście: cykliczny eksport CSV ze sklepu. Wyjście: plik
poprawek do zaimportowania w panelu sklepu.

## Zasady nadrzędne (nie łamać bez rozmowy)

1. **System nigdy nie zmienia danych sam.** Produkuje propozycje. Do pliku
   wynikowego trafia wyłącznie to, co człowiek kliknął.
2. **Rozwiązania płatne tylko dla spornych.** L0–L2 są deterministyczne
   i darmowe. Gemini (L3) dostaje tylko to, co przepuści bramka kosztowa.
3. **W razie wątpliwości nie ruszaj danych i powiedz człowiekowi.** Cicha
   porażka jest gorsza niż brak przebiegu.
4. **Licznik musi znaczyć zasięg akcji.** Jeśli przycisk mówi „×8", to ma
   ruszyć 8 rzeczy — nie 1569. Ten błąd zdarzył się już dwa razy.

## Gdzie co stoi

| | |
|---|---|
| repo | `github.com/sebastiankaczorowski-ops/atrybuty-weryfikator` |
| MacBook (dev) | `~/filtry/atrybuty` |
| Mac Mini (prod) | `~/atrybuty-weryfikator`, Docker, port 8084 |
| adres w biurze | `http://10.10.60.245:8084` — **bez logowania**, sieć LAN |
| baza | SQLite; w kontenerze `/app/baza/atrybuty.db` (nazwany wolumen — bind mount na macOS nie daje SQLite blokad i wywala „disk I/O error") |
| dane, cache zdjęć, pliki partii | `./dane` (bind mount) |
| konfiguracja | `./config` (bind mount **i** w repo — patrz „Znane bolączki") |

## Wdrożenie

Zawsze podawaj komendy **osobno dla MacBooka i osobno dla Mac Mini** — to
stała prośba Sebastiana, nie jednorazowa.

```bash
# MacBook
cd ~/filtry/atrybuty && git push

# Mac Mini
cd ~/atrybuty-weryfikator && git pull && docker compose up -d --build
```

Gdy zmiana dotyka `config/`, na Mini trzeba tańca ze stashem, bo tamtejsze
pliki bywają świeższe:

```bash
cd ~/atrybuty-weryfikator && git stash push -- config/ && git pull \
  && git checkout stash@{0} -- config/schema.yaml config/reguly.yaml \
  && docker compose up -d --build
```

## Po każdym commicie

1. **Wpis w `CHANGELOG.md`** — co doszło i co z tego ma użytkownik. Czyta go
   zakładka „co nowego" (`/zmiany`) w panelu.
2. **Gotowa notatka do wysłania zespołowi** — w odpowiedzi, nie w repo.
   Trzy osoby pracują na tym równolegle i wdrożenie potrafi zmienić im
   zachowanie przycisku w środku dnia.
3. Komendy wdrożeniowe jak wyżej.

Sebastian nie ma poświadczeń GitHuba w tej sesji — `git push` robi sam.

## Architektura

Python 3.12 · FastAPI · Jinja2 · HTMX · SQLite. Bez frontendowego
frameworka, bez ORM-a. 50 tras, 167 testów (`python3 -m pytest -q`).

### Warstwy wykrywania

| | co robi |
|---|---|
| **L0** | atrybuty rozjechane między `atrybuty` a `atrybuty-skladowe` — co przepisać, gdzie konflikt (`skladowe.py`) |
| **L1** | struktura i słowniki: braki, wartości spoza słownika, sprzeczności, relacje liczbowe (`detektory.py`) |
| **L2** | statystyka: outliery wymiarowe, test skali (`detektory.py`) |
| **L3** | zdjęcie przez Gemini — tylko dla spornych (`wizja.py`) |
| **L4** | feedy producenckie (`zrodla.py`) |

### Moduły

- `pipeline.py` — CSV → normalizacja → detektory → SQLite. Komendy:
  `import`, `schema`, `raport`, `wizja`, `kalibracja`, `wyczysc`.
- `app.py` — wszystkie trasy. Duże, ale celowo jedno miejsce.
- `zapytania.py` — zapytania do kolejki, rozstrzygniętych, postępu,
  producentów. `Filtr` niesie stan kolejki i serializuje się do query stringa.
- `db.py` — schemat i migracje. `MIGRACJE` dokłada kolumny w miejscu, bo
  kasowanie bazy kosztowałoby wszystkie decyzje.
- `panel_format.py` — format pliku panelu: nagłówki, słowniki `ID|etykieta`,
  przemianowania, wykrywanie atrybutów wielowartościowych.
- `eksport_panelu.py` — planowanie i zapis partii.
- `weryfikacja.py` — domknięcie pętli: czy wysłana poprawka faktycznie weszła.
- `reguly.py`, `config.py` — reguły i konfiguracja z YAML-i, sterowane z UI.

### Pojęcia dziedzinowe

- **finding** — pojedynczy wykryty problem `(produkt, atrybut, reguła)`.
- **decyzja** — rozstrzygnięcie człowieka. Klucz
  `(produkt_id, atrybut, hasz starej wartości)` — dzięki temu przeżywa
  kolejne importy i sama rozpoznaje, czy poprawka weszła.
  Statusy: `zastosowana`, `falszywy_alarm`, `odlozona`, `do_importu`.
- **grupa** — findingi o tym samym `(reguła, atrybut, wartość)`. Jedna
  decyzja rozstrzyga całą grupę **w zakresie aktywnych filtrów**.
- **partia** — plik eksportu dla panelu; da się wycofać.
- **zgłoszenie** — produkt wysłany do importu bez zmian, żeby panel postawił
  mu flagę `omit_components_in_attributes`. Wiersz niesie komplet obecnych
  atrybutów, więc powtórzenie importu niczego nie psuje.

### Konfiguracja (`config/`)

| plik | co |
|---|---|
| `reguly.yaml` | sprzeczności, relacje, klucze do usunięcia, `wylaczone`, `atrybuty_wylaczone` — sterowane z `/reguly` |
| `schema.yaml` | zakresy i pokrycie per kategoria — **wyliczany z danych**, nie konfiguracja |
| `slownik_idow.yaml`, `etykiety_panelu.yaml`, `atrybuty_panelu.yaml` | słownik panelu, wgrywany przez `/import` |
| `wzorzec_panelu.yaml` | układ pliku panelu (165 kolumn, preambuła) |
| `zmiany_nazw.yaml` | mapa przemianowań stara→nowa, budowana po ID |
| `wielowartosciowe.yaml` | atrybuty przyjmujące kilka wartości — z `/atrybuty` |
| `slowniki.yaml`, `kategorie.yaml`, `ustawienia.yaml` | pisane ręcznie |

## Styl kodu

- **Nazewnictwo i komentarze po polsku.** Kod czyta Sebastian, nie
  anglojęzyczny zespół.
- **Komentarz mówi, DLACZEGO, nie co.** Najcenniejsze są te opisujące błąd,
  który już się zdarzył — nie kasować ich przy refaktorze.
- **Test do każdej poprawki błędu**, z docstringiem mówiącym, co było źle.
  Testy są po polsku i opisują zachowanie, nie implementację.
- Bez zależności, których nie trzeba. `_markdown_lite` w `app.py` istnieje
  po to, żeby nie dokładać biblioteki do renderowania changeloga.

## Znane bolączki i pułapki

- **`config/schema.yaml` jest jednocześnie w repo i nadpisywany przez
  aplikację na mouncie** → konflikt przy każdym wdrożeniu. Rekomendacja:
  zdjąć z wersjonowania (to plik wyliczany), zostawić `schema.example.yaml`.
  Nierozstrzygnięte.
- **`CHANGELOG.md` jest kopiowany do obrazu, nie montowany** — zakładka
  „co nowego" odświeża się dopiero po `--build`.
- **Panel stawia flagę odcięcia składowych przy zapisie atrybutów**, ale
  nie na pustym wierszu. Produkt bez ani jednego legitnego atrybutu wypada
  z partii z wyraźnym powodem.
- **Formularz ma twardy limit 1000 pól (Starlette).** Podgląd grupy wysyła
  2 pola na wiersz; nie zwiększać bez liczenia.
- **Nagłówki pliku panelu zamarzają na dniu eksportu.** Po przemianowaniu
  atrybutu mapa `zmiany_nazw` jest stosowana przy odczycie wzorca — bez tego
  atrybut po cichu wypada z importu.
- **`_smieci/`** — katalog na blokady gita. Powłoka na Macu nie może kasować
  plików w mouncie, więc `.git/index.lock` i `HEAD.lock` przenosi się tam
  przed commitem. Do wyczyszczenia i dopisania do `.gitignore`.
- **Brak logowania.** Panel stoi w sieci biurowej bez uwierzytelniania
  (opisane w `WDROZENIE.md`). Każdy nowy dostęp (skrzynka, BigQuery) dokłada
  do tego ryzyka.
- **Klucz Gemini nigdy do repo.** Czytany z `GEMINI_API_KEY` albo
  `~/.atrybuty-gemini-key`. `.env` jest w `.gitignore` i `.dockerignore`.
  Produkty, baza i cache zdjęć też zostają poza gitem.

## Otwarte tematy po stronie sklepu

- Zduplikowane wartości `Styl` (20 etykiet pod kilkoma ID + wartości
  rumuńskie) blokują poprawki tego atrybutu — dlatego jest wyjęty z obiegu.
- `Ilość nóg` ma status DRAFT, a siedzi w składowych → nigdy nie zostanie
  przepisany i zniknie po postawieniu flagi. Podejrzenie, że takich jest więcej.
- `Długość` jest DISABLED, choć bywa jedynym legitnym atrybutem produktu.
- Z `Marki własne` (dawniej `Status produktu`) zniknęły wartości `nowość`
  i `polski produkt`.
- **Niesprawdzone i blokujące:** czy pusta komórka w naszym pliku kasuje
  istniejącą wartość w panelu, i kiedy dokładnie panel stawia flagę.
  Do sprawdzenia na jednym produkcie przed wysłaniem większej partii.

## Co dalej — patrz `docs/PLAN-AUTONOMIA.md`

Część I: pętla dzienna (pobranie pliku, bramka sanitarna, import, porównanie
z wczoraj, raport różnicowy). Część II: paczki z panelu przed aktywacją
(ticket #2441) i propozycja zastąpienia blokady edycji odciskiem produktu.

Świeży wątek: zakładka `/producenci` liczy, ilu dostawców odpowiada za połowę
potwierdzonych błędów. Od tej liczby zależy, czy sens ma rozmowa z dostawcami,
czy budowanie kolejnych bramek. **Priorytetem jest przyczyna, nie skutek** —
narzędzie długo mierzyło wyłącznie skutki.
