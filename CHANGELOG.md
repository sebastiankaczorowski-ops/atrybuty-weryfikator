# Co się zmieniło

Wpis po każdym commicie. Format: data, tytuł, co z tego ma użytkownik.
Najnowsze na górze. Ten plik czyta zakładka „co nowego" w panelu.

## 2026-09-19 · Przemianowane atrybuty wracają do importu

- `Liczba miejsc` i `Rodzaj obicia` nie wchodziły do pliku importu. Powód:
  nagłówki kolumn pochodzą z eksportu produktów i zamarzają na dniu, w którym
  ten eksport powstał. Po przemianowaniu atrybutu w panelu słownik znał już
  nową nazwę, a nagłówek został stary — atrybut wypadał jako „kolumny nie ma
  w formacie panelu", po cichu, bo produkt i tak szedł do pliku.
- Mapa przemianowań jest teraz stosowana przy każdym odczycie układu pliku,
  więc naprawia się samo, bez ponownego wgrywania eksportu produktów.
- Dotyczyło wszystkich pięciu przemianowanych atrybutów: `Liczba miejsc`,
  `Rodzaj obicia`, `Twardość materaca`, `Z pojemnikiem`, `Marki własne`.

## 2026-09-19 · Grupa większa niż lista da się zapisać w całości

- Podgląd grupy pokazuje najwyżej 200 wierszy. Przy grupie na 298 produktów
  dało się zapisać widoczne 200 i **nie było jak wrócić po resztę**.
- Doszedł przycisk **„Zapisz całą grupę (N)"** — bierze wartość z pola nad
  listą i zapisuje ją na wszystkich produktach grupy, także tych spoza listy.
- Po zapisaniu części podgląd przelicza się sam i pokazuje resztę, od razu
  wypełnioną tą samą wartością — widać, ile jeszcze zostało.
- Przy okazji: formularz wysyłał pięć pól na wiersz, czyli przy 200 wierszach
  dokładnie 1000 — twardy limit serwera. Jedno pole więcej i zapis wracał
  błędem. Teraz wiersz niesie ID i wartość, resztę serwer dobiera sam.

## 2026-09-19 · Filtr kategorii w rozstrzygniętych

- Na `/rozstrzygniete` doszedł filtr po kategorii, a przy nazwie produktu
  widać kategorię obok producenta.
- Liczby przy filtrach liczą się w zakresie pozostałych filtrów — po
  wybraniu producenta kategorie pokazują jego kategorie, nie wszystkie.
  Wybrana opcja nie znika przy zerze, żeby dało się zmienić wybór.
- **Strona 2 nie gubi już filtrów.** Przejście dalej kasowało wybór i lista
  wyglądała, jakby zmieniła się sama.

## 2026-09-19 · Operator relacji da się zmienić z panelu

- Na `/reguly` przy każdej regule relacyjnej jest teraz wybór operatora:
  `<` (wartość równa = błąd) albo `<=` (błąd dopiero gdy lewa strona jest
  większa). Zmiana działa od następnego przeliczenia, bez wdrożenia.
- Po co: `REL-SIEDZ-SZER` zgłaszał jako błąd krytyczny meble, w których
  szerokość siedziska jest **równa** szerokości mebla — a to normalny mebel.
  Błędem jest dopiero siedzisko szersze od mebla. To samo dotyczyło
  `REL-SIEDZ-GLEB` (ławka bez oparcia) i `REL-WYS-SIEDZ` (taboret, pufa).
- Strony relacji zostają bez zmian — zamiana atrybutu robi z tego inną
  regułę, a na to jest „usuń" i „dodaj".

## 2026-09-18 · Atrybut można wyjąć z obiegu

- **Nowa sekcja na `/reguly`: „Atrybuty wyjęte z obiegu".** To coś innego niż
  wyłączona reguła. Regułę wyłącza się, gdy źle działa; atrybut — gdy nie da
  się go poprawić niezależnie od reguł, bo problem siedzi poza nami.
- Wyjęty atrybut **nie produkuje findingów** (żadna reguła, żadna warstwa),
  **nie idzie do wizji** (więc nie płacimy za zdjęcia, których i tak nie da
  się wykorzystać) i **nie wychodzi do importu** — także tam, gdzie decyzje
  zapadły przed wyłączeniem. Na stronie eksportu takie pozycje pokazują się
  jako pominięte z powodem, a nie znikają po cichu.
- **Nic nie jest kasowane.** Findingi i decyzje zostają w bazie. Przywrócenie
  to jedno kliknięcie „Przywróć"; findingi wracają przy najbliższym
  przeliczeniu przebiegu.
- Powód wprowadzenia: **Styl**. W słowniku panelu ta sama nazwa siedzi pod
  kilkoma ID (każdy polski styl w 2–3 egzemplarzach, plus wartości rumuńskie),
  więc nie da się ustalić, którą wpisać, i żadna poprawka i tak nie przeszłaby
  importem. Do czasu posprzątania słownika w panelu Styl jest wyjęty.
- Przełącznik siedzi w `config/reguly.yaml` (`atrybuty_wylaczone`) i jest
  sterowany z UI, więc wyłączenie i przywrócenie nie wymaga wdrożenia.

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
