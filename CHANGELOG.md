# Co się zmieniło

Wpis po każdym commicie. Format: data, tytuł, co z tego ma użytkownik.
Najnowsze na górze. Ten plik czyta zakładka „co nowego" w panelu.

## 2026-09-18 · Nowy słownik z panelu i liczniki, które nie kłamią

- **Słownik wczytuje się z najnowszego zrzutu.** Panel dokłada kolejne zrzuty
  jako nowe arkusze („atrybuty 9.18", „wartości 9.18") i zostawia stare obok.
  Braliśmy dwa pierwsze — plik wyglądał na wgrany, a zmiany z panelu nie
  wchodziły. Teraz arkusze są rozpoznawane po nagłówku, a brana jest ostatnia
  para. Komunikat po wgraniu mówi wprost, z których arkuszy.
- **Przemianowania w panelu są zapamiętywane.** Gdy atrybut albo wartość
  zmienia tytuł, ID zostaje — i tylko po nim da się to poznać. Mapa
  stara→nowa ląduje w `config/zmiany_nazw.yaml`, a stare eksporty produktów
  czytają się pod nowymi nazwami. Bez tego przemianowany atrybut po cichu
  wypadał z walidacji: nie ma go w definicjach, więc żadna reguła go nie
  dotykała. Kolejne przemianowanie (A→B→C) przepina też najstarszą nazwę.
  `schema.yaml` i `reguly.yaml` są przy okazji przepisywane na nowe nazwy.
- **Wgrany słownik z 18.09:** 5 przemianowanych atrybutów
  (`Materiał obicia`→`Rodzaj obicia`, `Ilość osób`→`Liczba miejsc`,
  `Twardość`→`Twardość materaca`, `Z pojemnikiem na pościel`→`Z pojemnikiem`,
  `Status produktu`→`Marki własne`) i 12 przemianowanych wartości
  (`2-osobowe`→`2 miejsca`, `miękkie`→`miękki (H1)` itd.).
- **Licznik przy filtrze pokazuje, ile zostało.** „Stolik (39)" wisiał długo
  po rozstrzygnięciu wszystkich 39 — kliknięcie kończyło się pustą listą.
  Teraz liczone są tylko otwarte findingi, i to w zakresie pozostałych
  filtrów: po wybraniu producenta kategorie pokazują jego kategorie. Własny
  wymiar zostaje pełny, żeby dało się zmienić raz podjęty wybór, a wybrana
  opcja nie znika z listy, nawet gdy spadnie do zera.

## 2026-09-18 · Reset bazy po testach

- Komenda `wyczysc` czyści bazę po fazie testów: decyzje, zgłoszenia do
  importu, partie eksportu, historię importów, findingi, produkty,
  weryfikacje i werdykty wizji.
- **Reguły zostają** — siedzą w `config/reguly.yaml`, baza ich nie dotyczy.
  Słowniki panelu też zostają.
- **Cache odpowiedzi Gemini zostaje** domyślnie: kasowanie go znaczy
  płacenie drugi raz za te same zdjęcia (`--z-wizja`, jeśli mimo to trzeba).
- Przed kasowaniem powstaje kopia bazy, a bez `--potwierdzam TAK` komenda
  nie kasuje niczego.
- `--zakres historia` czyści samą historię eksportów i importów, zostawiając
  rozstrzygnięcia.
- `--pliki-partii` usuwa też wygenerowane xlsx-y z `dane/eksport`.

## 2026-09-18 · Grupy idą za filtrem, a „do importu" zamyka finding

- **Grupa nie wychodzi poza filtr.** Filtrując kategorię „łóżka" licznik ×N,
  podgląd grupy, „Zastosuj ×N" i „do importu ×N" dotyczą tylko łóżek.
  Wcześniej licznik obiecywał całą grupę i decyzja ruszała też komody.
- **„Do importu" to rozstrzygnięcie.** Produkt uznany za poprawny i wysłany
  po flagę odcięcia składowych znika z kolejki i wchodzi na listę
  rozstrzygniętych jako „bez zmian → import". Wcześniej finding zostawał
  otwarty i wracał przy każdym odświeżeniu.
  Zasięg zamknięcia zależy od miejsca kliknięcia: wiersz kolejki zamyka ten
  jeden finding, grupa — findingi tej grupy, karta produktu — wszystkie
  otwarte findingi produktu.
- **Zakładka „co nowego"** — ta lista.

## 2026-09-18 · Własna wartość przy grupie rozdaje się na wszystkie

- Przy zgrupowanym findingu było jedno pole za dużo: „własna wartość"
  zapisywała jeden produkt, obok stało „wartość na całą grupę". Zostaje
  jedno — przy grupie prowadzi do podglądu, gdzie widać każdy produkt
  osobno, można poprawić pojedyncze i zapisać całość jednym kliknięciem.

## 2026-09-18 · Licznik grupy kłamał

- Licznik ×N liczył wiersze pasujące do filtra, a decyzja obejmowała całą
  grupę: badge ×8 przy grupie rozstrzygającej 1569 produktów.
- Grupa o różnych wartościach nie da się rozstrzygnąć jednym kliknięciem
  (blokada w panelu i po stronie serwera).
- Strona kolejki: 4,94 s → 0,36 s.

## 2026-09-18 · Zgłoszenie do importu w kolejce, hurtem i w zakresie

- Przycisk „do importu" na liście findingów, hurtem dla grup.
- Wiersz bez ani jednego atrybutu jest odrzucany — panel nie postawi flagi
  na pustym wierszu (dotyczy 1516 produktów, są wylistowane przy eksporcie).
- Partia do eksportu da się zawęzić do kategorii i producenta — trzy osoby,
  trzy rozłączne zakresy.

## 2026-09-18 · Wymiary z rysunku technicznego i widok produktowy

- Brakujące wymiary można odczytać ze schematu (Gemini), z przeliczeniem
  na centymetry.
- Kolejkę da się przełączyć na widok produktowy: wszystkie błędy jednego
  mebla w jednym miejscu.

## 2026-09-17 · Domknięcie pętli i źródła wartości

- Przy każdym nowym zrzucie z bazy sprawdzamy, co się stało z wysłanymi
  partiami: weszło / bez zmian / inna wartość / brak atrybutu / brak produktu.
- Przy rozbieżnościach widać, która wartość pochodzi z atrybutów, a która
  ze składowych; karta produktu pokazuje obie listy obok siebie.
- Wymiary też są przepisywane ze składowych.

## 2026-09-16 · Warstwa L0

- Porównanie „atrybuty" i „atrybuty-składowe": co przepisać do legitnych
  atrybutów, gdzie jest rozbieżność do rozstrzygnięcia.
- Przepisujemy tylko to, co mieści się w słowniku atrybutów sklepu i jest
  ACTIVE; produkty z flagą `omit_components_in_attributes=1` pomijamy.
