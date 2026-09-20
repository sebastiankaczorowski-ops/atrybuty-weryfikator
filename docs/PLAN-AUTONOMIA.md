# Plan: z narzędzia do klikania w strażnika jakości

Stan na 2026-09-20. Dokument koncepcyjny — nic z tego nie jest jeszcze
zbudowane. Ustalenia z rozmowy: plik przychodzi codziennie rano mailem,
na start **zero automatycznych zmian w sklepie**, raport ma iść mailem
do zespołu i być widoczny jako zakładka w narzędziu.

## 1. Co się właściwie zmienia

Dziś narzędzie jest kolejką: ktoś wgrywa plik, ktoś siada i klika. Wartość
powstaje wtedy, kiedy człowiek ma czas.

Docelowo narzędzie ma **pilnować jakości samo**, a człowieka wołać tylko do
rzeczy, których nie umie rozstrzygnąć. Zmiana nie polega na tym, że system
zacznie zgadywać za ludzi — polega na tym, że przestaje czekać.

Trzy rzeczy, które robi sam:

- **wie, że jest nowy plik** i przelicza go bez proszenia,
- **wie, co się zmieniło od wczoraj** — i tylko to pokazuje,
- **sprawdza własną robotę**: czy wczorajsze poprawki faktycznie weszły.

Autonomia jest w wykrywaniu i pilnowaniu, nie w zmienianiu sklepu. Zmienianie
przychodzi później i tylko wtedy, gdy liczby na to pozwolą (§7).

## 2. Pętla dzienna

Jeden przebieg, pięć kroków, bez udziału człowieka aż do ostatniego.

1. **Odbiór pliku** (rano, po godzinie dostarczenia przez sklep) — narzędzie
   samo bierze plik ze skrzynki. Szczegóły w §3.
2. **Bramka sanitarna** — zanim cokolwiek trafi do bazy, plik musi przejść
   test sensowności (§6). Plik podejrzany nie jest importowany; zamiast tego
   idzie alarm.
3. **Import i przeliczenie** — to, co dziś robi `/import`: normalizacja,
   warstwy L0–L2, findingi.
4. **Porównanie z wczoraj** — sedno całej zmiany. Narzędzie liczy różnicę
   między dzisiejszym a wczorajszym stanem i klasyfikuje każdy problem jako
   *nowy*, *znany*, *zniknął* albo *wrócił* (§5). Tu też wpada weryfikacja
   wysłanych partii, którą narzędzie już umie.
5. **Raport** — mail do zespołu i zakładka w narzędziu. Raport mówi, co się
   zmieniło i co wymaga decyzji. Nie powtarza codziennie tej samej listy.

Czas trwania: import 69 tys. findingów zajmuje dziś kilkadziesiąt sekund,
więc cała pętla mieści się w kilku minutach. Może chodzić o 6:00 i być
gotowa, zanim ktokolwiek usiądzie do pracy.

## 3. Skąd narzędzie weźmie plik

Dziś plik przychodzi **mailem na skrzynkę Sebastiana**. To działa dla
człowieka i nie działa dla automatu, z trzech powodów: skrzynka jest
prywatna, narzędzie musiałoby dostać do niej dostęp, a Mac Mini z panelem
stoi w sieci biurowej **bez logowania** (patrz WDROZENIE.md).

Trzy warianty, od najlepszego:

**A. Osobny adres, np. `atrybuty@oxm.pl` (rekomendacja).**
Sklep wysyła plik tam zamiast (albo obok) skrzynki prywatnej. Narzędzie
czyta tę skrzynkę po IMAP, zapisuje załącznik i uruchamia pętlę. Zalety:
żadnych poświadczeń do prywatnej poczty na maszynie bez logowania, wyraźny
ślad co i kiedy przyszło, łatwo dać komuś innemu podgląd. Koszt: założenie
aliasu i skrzynki, zmiana adresata po stronie sklepu.

**B. Reguła w programie pocztowym na Mac Mini.**
Mail przychodzi na skrzynkę, reguła zapisuje załącznik do katalogu, który
narzędzie obserwuje. Zalety: nic nie trzeba uzgadniać, działa od jutra.
Wady: zależy od jednego, zalogowanego komputera z otwartym klientem poczty —
gdy ktoś go uśpi albo przeloguje, pętla cicho staje. Dobre jako etap
przejściowy, złe jako stan docelowy.

**C. Plik wystawiany przez sklep w ustalonym miejscu.**
SFTP, katalog sieciowy, Dysk albo link HTTP z tokenem. Najczystsze
technicznie — mail przestaje być kanałem transportu danych, którym nigdy
nie miał być. Wymaga rozmowy z IT.

Niezależnie od wariantu zostaje **ręczne wgranie przez `/import`** jako
awaryjne wejście. Automat ma odciążać, nie zabierać kierownicy.

### Do zapytania IT

1. Czy da się założyć `atrybuty@oxm.pl` (skrzynka albo alias z dostępem IMAP)?
2. Czy eksport może iść równolegle na ten adres, żeby przełączenie nie
   przerwało obecnego obiegu?
3. Czy zamiast maila sklep może wystawiać plik przez SFTP/HTTP — i czy
   Mac Mini ma do tego dojście z sieci biurowej?
4. Czy plik jest zawsze kompletny (wszystkie produkty), czy bywa przyrostowy?
   To zmienia bramkę sanitarną z §6.
5. Kto po stronie sklepu dostaje alarm, gdy plik nie przyjdzie?

## 4. Raport dzienny

Raport, który codziennie mówi „69 507 problemów", przestanie być czytany
w trzy dni. Dlatego raport jest **różnicowy**: domyślnie pokazuje to, co
zmieniło się od wczoraj.

Szkic treści, w kolejności ważności:

**Nagłówek — czy jest się czym przejmować.**
Jedno zdanie: plik przyszedł o której, ile produktów, czy coś wymaga reakcji
dzisiaj.

**Co poszło nie tak z wczorajszą wysyłką.**
Najpilniejsze, bo dotyczy pracy już wykonanej. Ile poprawek weszło, ile nie,
i — najważniejsze — **regresje**: poprawka, która weszła, a potem wróciła do
starej wartości. To sygnał, że ktoś albo coś po drugiej stronie pracuje
przeciwko nam, i bez tego można miesiącami poprawiać w kółko to samo.

**Nowe problemy.**
Produkty, które wczoraj były w porządku, a dziś nie są. Zwykle: nowe
produkty w ofercie albo edycja w panelu, która coś zepsuła. Pogrupowane, jak
w kolejce, z liczbą i jednym kliknięciem do kolejki z ustawionym filtrem.

**Co zniknęło samo.**
Problemy, które rozwiązały się bez naszego udziału — ktoś poprawił w panelu.
Warto widzieć, bo to zmienia ocenę, ile pracy zostało.

**Stan zapasu.**
Ile otwartych zostało, ile czeka na eksport, ile w kolejce zgłoszeń. Trend
tygodniowy zamiast liczby z jednego dnia.

**Czego raport NIE zawiera:** pełnej listy znanych problemów. Ta jest
w kolejce i nie zmienia się na tyle, żeby ją codziennie przepisywać.

Ten sam raport w dwóch miejscach: mail (krótki, z linkami) i zakładka
w narzędziu (pełna, klikalna, z historią poprzednich dni).

## 5. Czego brakuje w danych

Dzisiejszy model pamięta **stan ostatniego przebiegu** i decyzje. Żeby
odpowiedzieć na pytanie „co się zmieniło od wczoraj", trzeba dwóch rzeczy:

**Migawka dzienna.** Dziś import kasuje tabelę produktów i wstawia nową
zawartość. Historii nie ma. Potrzebny jest zapis na tyle, żeby porównać dwa
kolejne dni — niekoniecznie pełna kopia: wystarczy odcisk (hasz) atrybutów
produktu i lista findingów per przebieg. Findingi już są per przebieg, więc
połowa roboty jest zrobiona.

**Tożsamość problemu w czasie.** Finding dostaje dziś nowe `id` przy każdym
imporcie. Żeby powiedzieć „ten problem jest znany od 11 dni", potrzebny jest
klucz stabilny między przebiegami — naturalnie: `(produkt, atrybut, reguła)`.
Decyzje mają już taki klucz (`produkt + atrybut + hasz starej wartości`),
więc wzorzec jest sprawdzony.

Mając to, klasyfikacja jest prosta i tania: *nowy* (nie było wczoraj),
*znany* (był i jest), *zniknął* (był, nie ma), *wrócił* (był, zniknął po
naszej poprawce, jest znowu → regresja).

## 6. Bezpieczniki

Automat, który raz dziennie dotyka wszystkiego, musi mieć hamulce. Rzeczy,
które pójdą nie tak, i co system ma wtedy zrobić:

| Co się dzieje | Reakcja |
|---|---|
| Plik nie przyszedł do ustalonej godziny | Alarm mailem, stan „czekam", **nie** podmieniamy danych |
| Plik dużo krótszy niż wczoraj (np. −20% produktów) | Import wstrzymany, alarm z liczbami — to klasyczny sposób na wyczyszczenie bazy obciętym eksportem |
| Nagły skok findingów (np. ×3 w dobę) | Import przechodzi, ale raport otwiera się ostrzeżeniem: to prawie zawsze zmiana po stronie sklepu (nowy słownik, przemianowany atrybut), a nie nagły spadek jakości |
| Ten sam plik co wczoraj | Wykryty po odcisku, pominięty, krótka notka w raporcie |
| Słownik panelu się zmienił | Wykryte przemianowania trafiają do raportu jako osobna sekcja — to już się zdarzyło i kosztowało dzień dochodzenia |
| Pętla się wywaliła | Alarm z treścią błędu; ostatni dobry stan zostaje nietknięty |

Zasada nadrzędna: **w razie wątpliwości nie ruszaj danych i powiedz
człowiekowi.** Cicha porażka jest gorsza niż brak przebiegu.

## 7. Etapy

Trzy etapy, każdy użyteczny sam w sobie. Nie przechodzimy dalej, dopóki
poprzedni nie działa przez ustalony czas.

**Etap 1 — pętla dzienna bez automatycznych zmian.**
Pobranie pliku, bramka sanitarna, import, porównanie z wczoraj, raport mailem
i w narzędziu. Zero zmian w sklepie poza tym, co człowiek kliknie ręcznie.
*Kryterium wyjścia:* dwa tygodnie przebiegów bez ręcznego dotykania, raport
czytany i uznany za wiarygodny.

**Etap 2 — propozycje partii.**
Narzędzie samo składa gotową partię do eksportu z rozstrzygnięć, które
zapadły, i kładzie ją do zatwierdzenia. Człowiek klika „wyślij" zamiast
budować partię. Nadal żadna zmiana nie idzie bez kliknięcia.
*Kryterium wyjścia:* skuteczność z zakładki „postęp" utrzymana wysoko przez
miesiąc — wtedy wiadomo, że to, co wysyłamy, faktycznie wchodzi.

**Etap 3 — wąska autonomia (do osobnej decyzji).**
Dopiero tu automat zmienia coś sam, i tylko w jednej klasie: **przepisanie
atrybutu ze składowych**, gdy w legitnych atrybutach jest pusto, a wartość
mieści się w słowniku. To nie jest zgadywanie — wartość już jest w sklepie,
tylko w złym miejscu. Wszystko inne dalej przez człowieka.
*Warunek wstępny:* z etapu 1 i 2 mamy zmierzoną skuteczność tej konkretnej
reguły, nie ogólne przeczucie. *I hamulec:* dzienny limit produktów oraz
możliwość cofnięcia całej partii jednym kliknięciem (już istnieje).

Sebastian wybrał na teraz „tylko raport" — etap 3 jest w tym dokumencie po
to, żeby wiadomo było, dokąd to prowadzi, a nie żeby to teraz robić.

## 8. Co to zmienia w pracy zespołu

Dziś: ktoś pamięta, żeby wgrać plik, potem trzy osoby przeglądają tę samą
wielką kolejkę i nie wiadomo, czy praca z wczoraj przyniosła skutek.

Po etapie 1: rano w skrzynce jest lista tego, co nowe i co się popsuło.
Kolejka przestaje być workiem bez dna, a staje się zaległością, która ma
widoczny trend. Pytanie „czy nam idzie" ma odpowiedź liczbową w zakładce
„postęp".

Rzecz, o której warto powiedzieć zespołowi wprost: **raport codziennie
pokazujący zero nowych problemów to sukces, nie awaria narzędzia.**

## 9. Rzeczy nierozstrzygnięte

- Adres i sposób dostarczania pliku (§3) — blokuje etap 1.
- Czy raport ma iść codziennie, czy tylko w dni robocze.
- Kto dostaje alarmy techniczne (brak pliku, błąd pętli) — to inna lista
  odbiorców niż raport merytoryczny.
- Retencja migawek: ile dni historii trzymamy, zanim baza zacznie puchnąć.
- Panel nadal nie ma logowania, a przybędzie mu dostęp do skrzynki pocztowej.
  Przed etapem 1 trzeba to rozstrzygnąć — osobny adres (wariant A) załatwia
  większość problemu, ale nie cały.
