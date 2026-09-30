# Co się zmieniło

Wpis po każdym commicie. Format: data, tytuł, co z tego ma użytkownik.
Najnowsze na górze. Ten plik czyta zakładka „co nowego" w panelu.

## 2026-09-30 · Poprawka: mm Wójcika dalej szły jako cm

- **Co było źle:** jednostkę sprawdzaliśmy tylko na produktach dopasowanych
  po kodzie (EAN). Wójcik dopasowuje się po nazwie, więc narzędzie nie miało
  na czym sprawdzić i zostawiało mm. Wynik: ok. 650 witryn i komód
  z propozycją „Szerokość 500, u nas 50”.
- Jednostkę ustalamy teraz na tych samych dopasowaniach, których używa
  porównanie — po kodzie i po nazwie.
- **Bezpiecznik:** różnica dokładnie ×10, ×100 albo ×1000 względem naszej
  bazy nigdy nie trafia do kolejki. Ląduje w „Konfliktach między źródłami”
  ze znacznikiem „jednostki?”, bo to prawie zawsze mm zamiast cm.
- Po wdrożeniu: Odśwież źródło Wójcika i przelicz import — fałszywe rozjazdy
  znikną z kolejki.

## 2026-09-29 · Kilka źródeł na produkt: najpierw uzgadniamy, potem porównujemy

- Jeden produkt może mieć teraz kilka źródeł naraz (np. PIM Wójcika
  i zakładki arkusza V3/V4). Dawniej pierwsze dopasowane źródło „zabierało”
  produkt, a pozostałe nie miały głosu.
- Przy każdym przeliczeniu importu źródła są **najpierw porównywane między
  sobą**. Gdy się zgadzają (w tej samej tolerancji co porównanie z bazą),
  z naszą bazą porównujemy uzgodnioną wartość — dowód w kolejce wymienia
  każde źródło z jego wartością, a zgodność kilku podnosi pewność.
- Gdy źródła się kłócą, **nic nie trafia do kolejki** — nie wiadomo, która
  wersja jest prawdziwa. Produkt ląduje w nowej sekcji „Konflikty między
  źródłami” w `/zrodla`, razem z zestawieniem, które pary źródeł kłócą się
  najczęściej. Zwykle to stara wersja feedu albo inne jednostki — wyłącz
  źródło, które się myli, i przelicz import.
- Rozpoznanie arkusza poleca teraz wszystkie zakładki, które coś wnoszą,
  a nie jedną na producenta.

## 2026-09-29 · Wygląd w kolorach Twojemeble.pl

- Panel dostał paletę z design systemu sklepu: fioletowy nagłówek (Deep
  Violet), główne przyciski w kolorze marki, fokus z klawiatury na
  pomarańczowo (Vivid Orange), zaokrąglone karty i tabele z zebrą.
- Przycisk „sprawdź zdjęciem” (Gemini) ma fioletowy gradient — tak DS
  oznacza funkcje AI, żeby odróżniały się od zwykłych akcji.
- Kolory stanów (krytyczne, ostrzeżenia, zrobione) z tej samej palety,
  z tekstem w ciemniejszym odcieniu dla czytelności.

## 2026-09-29 · Jednostki w feedach wykrywane same (mm, m, g)

- Feed z wymiarami w mm (np. PIM Wójcika) nie daje już rozjazdów typu
  „1200 zamiast 120”. Przy każdym pobraniu narzędzie sprawdza na
  dopasowanych produktach, czy wartości zgadzają się z naszymi wprost,
  po podzieleniu przez 10 (mm) czy po pomnożeniu przez 100 (m); dla wagi
  także gramy. Gdy nie ma dopasowań, patrzy na nazwę pola („Szerokość (mm)”)
  i zapis wartości („1200 mm”).
- Przeliczenie widać: w komunikacie po pobraniu i jako znacznik przy
  źródle („Szerokość: mm → cm”). Pozycje zapisują się już w cm, więc
  propozycja w kolejce to od razu nasza wartość.
- Gdy liczby wyglądają na mm, ale nic tego nie potwierdza — narzędzie
  ostrzega i nie przelicza. Szafa 450 cm istnieje.

## 2026-09-29 · Rozpoznanie arkusza: źródła dobierają się same, do zatwierdzenia

- Nowa strona `/zrodla/rozpoznanie`. Komenda na Mini przechodzi wszystkie
  zakładki arkusza „RAW FILES” i dla każdej **mierzy**: które pole trafia
  w kody naszych produktów (klucz), do którego producenta należą trafione
  produkty i które pole feedu **zgadza się z naszymi wymiarami i wagą**.
- Dzięki temu kolejność „wymiar 1/2/3” z opisów (Halmar) rozstrzygają dane.
  Pole mapujemy dopiero, gdy zgadza się na co najmniej połowie produktów —
  słabszy kandydat jest pokazany przekreślony, żeby było widać, czemu go nie ma.
- Na producenta polecana jest jedna zakładka (najwięcej trafień) — V2/V3
  i Stock/Products naraz dałyby sprzeczne propozycje dla tego samego mebla.
- Nic nie zmienia się samo: zaznaczasz zakładki, klikasz „Załóż”, a źródła
  powstają (albo poprawiają się istniejące) i pobierają pozycje w tle.

## 2026-09-29 · Feedy producentów prosto z arkusza „RAW FILES”

- W `/zrodla` jako adres źródła można wkleić **zakładkę arkusza Google**
  (adres z `#gid=`). Narzędzie czyta ją kontem serwisowym tylko do odczytu,
  składa wiersze z `<item>` w jeden feed i dalej działa jak dotąd: podgląd
  pól, mapowanie, dopasowanie do naszych produktów, rozjazdy w kolejce.
- Jeden producent = jedna zakładka = jedno źródło. Adres bez `#gid=` nie
  zgaduje — odpowiada listą zakładek w arkuszu.
- Zakładka może trzymać XML w komórkach (jak Bogart), JSON w komórkach
  albo zwykłą tabelę z nagłówkami w pierwszym wierszu (jak Wójcik) —
  narzędzie rozpoznaje to samo.
- **Wymiary z opisu.** Gdy producent (np. Halmar) podaje wymiary tylko
  w opisie („wymiary: 99/210/89 cm, materiał: …, kolor: …”), w podglądzie
  pojawiają się pola `description » wymiar 1/2/3`, `» materiał`, `» kolor`.
  Kolejności liczb narzędzie nie zgaduje — w mapowaniu wskazujesz, który
  wymiar jest szerokością, a który wysokością.
- **Wymiary paczki nie udają wymiarów mebla.** Podpowiedź mapowania pomija
  pola z `<package>` i wagę brutto — inaczej szerokość kartonu trafiałaby
  do porównania z szerokością łóżka.
- Pusta zakładka to błąd, a nie zero pozycji — inaczej po cichu zniknęłyby
  wszystkie dane producenta.

Po co to jest: arkusz odświeża się po każdym imporcie, więc porównanie
„co podał producent” z „co jest w sklepie” nie wymaga już ręcznego wgrywania
plików.

## 2026-09-25 · Porządek w repo: blokady gita poza wersjonowaniem

- Pliki z `_smieci/` (stare `index.lock`, `HEAD.lock`) zniknęły z repo —
  były zacommitowane, zanim katalog trafił do `.gitignore`, więc sam wpis
  niczego nie ignorował.
- Aplikacja działa bez zmian; zakładki i przyciski zachowują się jak dotąd.

## 2026-09-23 · Zakładka „producenci" — kto te błędy produkuje

- Nowa podstrona `/producenci`. Dla każdego producenta: ile produktów, ile
  findingów, ile z nich okazało się **potwierdzonym błędem** (ktoś zapisał
  poprawkę), ile **fałszywym alarmem** (myliła się nasza reguła), ile produktów
  przepuszczono bez zmian, błędy na produkt i trafność reguł.
- Klik w producenta rozbija go na reguły i atrybuty — żeby rozmowa dotyczyła
  konkretnej rzeczy, a nie „macie dużo błędów".
- U góry jedna liczba, która decyduje o strategii: **ilu producentów odpowiada
  za połowę potwierdzonych błędów.** Mała liczba znaczy, że przyczynę da się
  ruszyć rozmową o formacie danych zamiast kolejnym tysiącem kliknięć.
- Kolumna **pokrycie** pilnuje uczciwości liczb: rozstrzygano w kolejności
  wygodnej dla człowieka, nie losowej, więc przy niskim pokryciu to wskazówka,
  a nie wyrok.

Po co to jest: dotąd całe narzędzie mierzyło skutki. To pierwszy widok, który
patrzy na źródło — 30 tys. rozstrzygnięć to nie tylko odklikana praca, tylko
pomiar jakości danych wejściowych, którego nigdy nie odczytaliśmy.

## 2026-09-20 · Zakładka „atrybuty" i wartości po przecinku

- Nowa podstrona `/atrybuty`: wszystkie atrybuty sklepu z ich wartościami
  słownikowymi, stanem (ACTIVE / DRAFT / DISABLED) i przełącznikiem **„ile
  wartości naraz"**. Panel tego nie rozróżnia — atrybut na jedną wartość
  wygląda w jego słowniku tak samo jak ten na kilka — więc ta strona jest
  jedynym miejscem, gdzie ta wiedza powstaje.
- **„Sprawdź w danych sklepu"** przegląda ostatni wgrany plik i pokazuje,
  które atrybuty naprawdę bywają wypełnione kilkoma wartościami. Dowodem
  jest wartość z przecinkiem, której wszystkie człony są w słowniku —
  „Szafa 3-drzwiowa, biała" w polu tekstowym się nie liczy. Jedno kliknięcie
  zaznacza wykryte, zamiast odklikiwać 68 atrybutów na ślepo.
- W kolejce pole własnej wartości przy takim atrybucie przyjmuje listę po
  przecinku i tak się podpisuje. Przy pozostałych wpisanie kilku wartości
  jest odrzucane z wyjaśnieniem — bez tego w słowniku sklepu powstałaby nowa
  wartość o nazwie „welur, tkanina".
- Zaczyn listy bierze się z `slowniki.yaml` (7 atrybutów oznaczonych tam jako
  `multi_enum`), ale właściwa lista mieszka w `config/wielowartosciowe.yaml`
  i jest sterowana z UI — bez wdrożenia.

## 2026-09-20 · Zakładka „postęp" — statystyki dzienne

- Nowa podstrona `/postep`: dzień po dniu widać, ile rozstrzygnięto w kolejce
  (z podziałem na poprawki, fałszywe alarmy, „bez zmian" i odłożone), ile
  poprawek i produktów poszło tego dnia partiami do sklepu, i ile kolejny
  zrzut z bazy potwierdził jako faktycznie wprowadzone — ze skutecznością
  w procentach.
- U góry stan na teraz: otwarte findingi, rozstrzygnięcia razem, ile czeka
  na eksport, ile wysłano, ile sprawdzono i jaki procent wszedł.
- **Jak to czytać:** trzy grupy kolumn to trzy różne momenty życia jednej
  poprawki — decyzja, wysyłka, potwierdzenie — i zdarzają się w różne dni.
  Liczby w jednym wierszu dotyczą różnych poprawek i nie wolno ich od siebie
  odejmować.
- Przy okazji: na świeżej bazie brakowało tabel weryfikacji i zgłoszeń, więc
  część stron wywalała się błędem 500, zanim cokolwiek je wypełniło.

## 2026-09-20 · Karta produktu mówi, co jest otwarte, a co już rozstrzygnięte

- Karta pokazuje **wszystkie** findingi produktu, także te rozstrzygnięte,
  a kolejka weryfikacji tylko otwarte. Karta o tym nie mówiła, więc produkt
  z 13 pozycjami i jednym wierszem w kolejce wyglądał na błąd kolejki.
- Teraz nad listą jest „N otwartych · M rozstrzygniętych", rozstrzygnięte są
  wyszarzone i opisane (co zapadło, kiedy, w której partii), a otwarte idą
  na górę.
- Doszły linki: „pokaż je w kolejce" i przejście do rozstrzygniętych tego
  produktu.

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
