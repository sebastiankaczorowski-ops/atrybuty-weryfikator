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
---

# Część II: paczki z panelu a pętla dzienna

Analiza koncepcji weryfikacji przed aktywacją (panel OXM, ticket #2441)
w odniesieniu do planu pętli dziennej. 2026-09-23.

## 10. Dwie pętle, jeden silnik

Paczki i pętla dzienna nie konkurują — pilnują dwóch różnych momentów.

| | paczka z panelu | pętla dzienna |
|---|---|---|
| kiedy | zanim produkt trafi na front | codziennie, na całym asortymencie |
| co wyzwala | klik pracownika | nowy plik |
| zakres | kilkanaście–kilkadziesiąt produktów | 28 tys. |
| kto odpowiada | konkretna osoba, z nazwiska | zespół |
| po co | błąd nigdy nie dociera do klienta | błąd, który już tam jest, zostaje znaleziony |

Wspólne jest wszystko, co pod spodem: reguły, kolejka, grupowanie, decyzje,
format pliku, weryfikacja „czy weszło". **Nie budujemy drugiego narzędzia** —
dokładamy drugie wejście i drugi widok do tego samego.

Paczki są pierwszą linią i mają przewagę, której pętla dzienna mieć nie
będzie: **wiadomo, kto**. Pętla dzienna widzi błąd, ale nie wie, czyj. Paczka
wie i dlatego może uczyć — jeśli jedna osoba regularnie zostawia te same
braki, to informacja o szkoleniu, nie o produkcie.

Paczki nie zastępują pętli dziennej, bo dotyczą wyłącznie nowych produktów.
28 tys. już aktywnych nie przejdzie przez żadną paczkę.

## 11. Co się zmienia w planie pętli dziennej

- **Dwa źródła danych zamiast jednego.** Plik dzienny (cały asortyment)
  i BigQuery (paczki, na żądanie). Bramka sanitarna dotyczy pliku dziennego;
  paczka ma własną, prostszą: znane ID, niepusta, produkty istnieją.
- **Migawka i tożsamość findingu są potrzebne tym bardziej.** Produkt
  z paczki po aktywacji wpada w pętlę dzienną. Bez stabilnej tożsamości
  findingu nie da się powiedzieć „to ten sam problem, który przeszedł
  weryfikację w paczce 17" — a to jest dokładnie ta reguła, którą sami
  wpisaliście jako „do rozważenia po wdrożeniu".
- **Raport dzienny dostaje sekcję o paczkach:** otwarte, zalegające,
  zamknięte wczoraj, produkty czekające na aktywację.

## 12. Blokada edycji — proponuję odwrócić mechanizm

To Wasze ostatnie otwarte pytanie i jedyne, które w obecnym kształcie nie ma
dobrej odpowiedzi. Blokada edycji w otwartej paczce rozwiązuje realny problem
(import nie może nadpisać późniejszych zmian), ale tworzy zakleszczenie: część
błędów da się poprawić wyłącznie w panelu, a panel jest zamknięty.

Źródłem kłopotu jest **blokada pesymistyczna** — zabraniamy z góry, na wszelki
wypadek. Ten sam cel osiąga **blokada optymistyczna**: nie zabraniamy niczego,
ale przy imporcie sprawdzamy, czy produkt zmienił się od chwili wysłania do
weryfikacji. Jeśli tak — ten wiersz nie wchodzi i wraca jako konflikt do
rozstrzygnięcia.

Do tego potrzeba jednej rzeczy: **odcisku produktu** (hasz jego atrybutów)
zapisanego w paczce w momencie wysyłki. Panel przy imporcie porównuje odcisk
i przepuszcza tylko niezmienione.

Co to daje:

- pracownik poprawia w panelu, co chce i kiedy chce — brak zakleszczenia,
- import nigdy nie nadpisuje nowszej zmiany, bo ją widzi,
- znika stan „zablokowany", a z nim klasa pytań „a co, jeśli ktoś zapomni
  zamknąć paczkę".

**Bramką aktywacji przestaje być członkostwo w zamkniętej paczce, a staje się
pieczątka na produkcie:** „zweryfikowany, w tym kształcie". Pieczątka to
(produkt, odcisk atrybutów, data, paczka). Edycja w panelu zmienia odcisk,
więc pieczątka przestaje pasować i aktywacja znów jest zablokowana — sama,
bez dodatkowej logiki.

To ta sama zasada, na której działają decyzje w narzędziu: klucz
`(produkt, atrybut, hasz starej wartości)` przeżywa kolejne importy właśnie
dlatego, że opisuje stan, a nie moment.

Jeśli panel nie umie liczyć odcisku, wystarczy znacznik czasu ostatniej
edycji produktu — słabszy, ale wystarczający.

## 13. Kalibracja reguł dla produktów nieaktywnych

Zamiast ręcznej listy „reguły do wyłączenia w trybie paczki" — reguła
wyznaczana z danych: **reguła wchodzi do paczki tylko wtedy, gdy wszystkie
pola, na których się opiera, są wypełnione dla produktów tej paczki.** Jeśli
pole jest puste u wszystkich, reguła jest pomijana i mówimy o tym wprost
w raporcie paczki („pominięto 4 reguły: brak danych z frontu").

Dlaczego tak: lista dezaktualizuje się przy pierwszej zmianie w panelu
i nikt o tym nie wie. Wyznaczanie z danych psuje się głośno.

Uwaga, która może oszczędzić pracy: nasze reguły i tak liczą się z eksportu
panelu, nie z frontu. Realnie „danych z frontu" używa niewiele — warto
policzyć, ile reguł faktycznie odpada, zanim zaplanujemy osobną kalibrację.

## 14. Dziury w przepływie, które warto zatkać od razu

- **Paczka bez findingów musi zamykać się sama.** Produkt czysty nie może
  czekać na człowieka — inaczej dokładamy tarcie tam, gdzie nie ma błędu.
- **Paczki zalegające.** Produkt w otwartej paczce nie da się aktywować.
  Bez raportu wieku paczek i właściciela oferta cicho stoi.
- **Jeden produkt, jedna otwarta paczka.** Inaczej dwie osoby wyślą ten sam
  produkt i dwa pliki będą się nawzajem nadpisywać.
- **Pracownik, który nigdy nie zaimportuje pliku.** Paczka wisi, produkt
  zamrożony. Przy blokadzie optymistycznej problem znika sam.
- **Puste kolumny w pliku.** Czy pusta komórka w naszym pliku kasuje
  istniejącą wartość w panelu? Nierozstrzygnięte, dotyczy obu przepływów,
  trzeba sprawdzić na jednym produkcie, zanim ruszy którykolwiek.
- **Atrybuty nieaktywne w pliku.** W narzędziu to już działa przy
  przepisywaniu ze składowych; trzeba potwierdzić, że eksport też odrzuca
  DRAFT i DISABLED.
- **Link do paczki a brak logowania.** Narzędzie nie ma uwierzytelniania
  i stoi w sieci biurowej. Link „dla pracownika" zadziała dla każdego, kto go
  zna. Wewnętrznie do przyjęcia, ale niech to będzie decyzja, nie przeoczenie.
- **Poświadczenia do BigQuery na Mac Mini.** Maszyna bez logowania dostaje
  dostęp do hurtowni. Konto serwisowe z prawem odczytu jednego zbioru.

## 15. Kolejność

1. **Sprawdzić puste kolumny i flagę na jednym produkcie.** Blokuje wszystko
   inne, kosztuje pół godziny.
2. **Odcisk produktu i pieczątka weryfikacji** — ustalenie z Michałem, zanim
   powstanie blokada edycji, której potem trzeba będzie się pozbywać.
3. **Przegląd reguł pod kątem danych z frontu** — policzyć, ile odpada.
4. **Paczki w narzędziu:** pobranie z BigQuery, widok paczki, eksport.
5. **Pętla dzienna** — niezależnie, bo dotyczy innego zbioru.

Punkty 1–3 to ustalenia, nie kod. Warto je domknąć przed pisaniem czegokolwiek.
