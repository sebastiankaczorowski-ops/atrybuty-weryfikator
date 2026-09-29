# Wdrożenie na Mac Mini

Ten sam flow co `manager-dashboard`: edycja na MacBooku → push do GitHuba →
pull i restart na Mac Mini.

- **Repo**: `https://github.com/sebastiankaczorowski-ops/atrybuty-weryfikator.git`
- **Gałąź**: `main`
- **Port**: `8084` (8082 zajęty przez dashboard prywatny, 8081 przez nginx biurowy)
- **Katalog na Mac Mini**: `~/atrybuty-weryfikator/`

## Pierwsze uruchomienie na Mac Mini

```bash
cd ~
git clone git@github.com:sebastiankaczorowski-ops/atrybuty-weryfikator.git
cd atrybuty-weryfikator

cp .env.example .env
# wpisz GEMINI_API_KEY (klucz z Google AI Studio)

docker compose up -d --build
docker compose logs -f atrybuty
```

### Dostęp po LAN

Kontener nasłuchuje na wszystkich interfejsach, więc z dowolnego komputera
w sieci biurowej wchodzi się po adresie IP Mac Mini:

```
http://<IP-Mac-Mini>:8084
```

IP sprawdzisz na Mac Mini: `ipconfig getifaddr en0` (Wi-Fi) albo
`ipconfig getifaddr en1` (Ethernet). Warto zarezerwować je na stałe
w routerze, żeby adres nie zmieniał się po restarcie.

Pierwszy ekran to `/import` — wgraj tam eksport ze sklepu, zaznacz
„przelicz zakresy per kategoria" (świeża instalacja nie ma jeszcze policzonych
progów) i poczekaj kilkanaście sekund.

**Aplikacja nie ma logowania.** Każdy w sieci biurowej może zatwierdzać
poprawki i wywoływać płatne zapytania do Gemini przyciskiem „Sprawdź
zdjęciem". Dla narzędzia wewnętrznego w biurze to zwykle w porządku, ale
warto o tym wiedzieć — dołożenie hasła (jak `DASHBOARD_PASSWORD`
w manager-dashboard) to kilkanaście linii, jeśli okaże się potrzebne.

Gdybyś chciał zamknąć dostęp do samego Mac Mini i wystawiać przez Tailscale,
zmień mapowanie portu w `docker-compose.yml` na `"127.0.0.1:8084:8084"` i uruchom
`tailscale serve --bg --https=8443 8084` (8443, bo 443 zajmuje dashboard).

## Aktualizacja

```bash
cd ~/atrybuty-weryfikator
git pull origin main
docker compose up -d --build       # zmiany w .py wymagają przebudowy
```

Szablony i pliki statyczne są w obrazie, więc po ich zmianie też potrzebny
jest `--build`. To celowa różnica wobec `manager-dashboard`: tutaj nie
montujemy kodu z hosta, żeby na produkcji działała dokładnie ta wersja,
która jest w repo.

### Gdy `git push` zgłosi lock

```bash
rm ~/atrybuty-weryfikator/.git/index.lock
rm ~/atrybuty-weryfikator/.git/HEAD.lock
```

## Co gdzie leży

| Ścieżka | Zawartość | Kopia zapasowa |
|---|---|---|
| wolumen `atrybuty-baza` | SQLite: produkty, findingi, **decyzje**, werdykty i cache Gemini | **tak — tu są wszystkie decyzje zespołu** |
| `./config/` (bind) | reguły i słowniki, edytowalne z `/reguly` | tak, przez git |
| `./dane/` (bind) | wgrane eksporty, pliki poprawek, cache zdjęć | nie trzeba |
| `.env` | klucz Gemini | poza repo |

Baza celowo nie leży na bind mouncie: SQLite potrzebuje blokad plikowych,
których bind mount Docker Desktop na macOS nie daje — kończy się to błędem
`disk I/O error` przy starcie. Kopia zapasowa bazy:

```bash
docker compose exec atrybuty sh -c "sqlite3 /app/baza/atrybuty.db .dump" \
  > ~/kopie/atrybuty_$(date +%F).sql
```

Reguły zmienione z UI lądują w `config/reguly.yaml` na hoście — po sesji
strojenia warto je zacommitować:

```bash
git add config/reguly.yaml && git commit -m "reguly: strojenie po sesji" && git push
```

## Klucz Gemini

Wyłącznie w `.env` na Mac Mini (i lokalnie w `~/.atrybuty-gemini-key` na
MacBooku). Nigdy w repo — `.gitignore` i `.dockerignore` to blokują.
Bez klucza działa wszystko poza „Sprawdź zdjęciem".

## Konto serwisowe Google (feedy z arkusza)

Zakładka `/zrodla` czyta surowe feedy producentów z arkusza
„Imports - RAW FILES automat” kontem
`manager-dashboard-reader@ai-agents-analytics-491415.iam.gserviceaccount.com`
— tym samym co `manager-dashboard`.

- Uprawnienie w arkuszu: **Wyświetlający**. Zakres tokenu:
  `spreadsheets.readonly`. Narzędzie nie pisze do arkusza.
- Klucz JSON leży w `~/manager-dashboard/secrets/` na Mini. Do kontenera
  trafia **sam plik**, tylko do odczytu, jako `/app/klucz-google.json`.
  Ścieżkę na hoście podaje `KLUCZ_GOOGLE` w `.env`, np.
  `KLUCZ_GOOGLE=/Users/<ty>/manager-dashboard/secrets/<plik>.json`.
  Bez tej zmiennej `docker compose` odmówi startu. Nigdy w repo ani w obrazie.
- **Wymiana klucza w manager-dashboard wyłącza też feedy tutaj** — po
  rotacji sprawdź `/zrodla` (źródło pokaże błąd 403 albo „brak klucza”).
- Bez klucza działa wszystko poza odświeżaniem źródeł z arkusza.

## Kolejne kroki

Import produktów nie dotyka BigQuery — eksport wgrywasz ręcznie. Eksport
produktów wgrywasz ręcznie przez `/import`. Gdyby miało to chodzić samo,
naturalny krok to zapytanie do BQ w harmonogramie i wywołanie importu
tokenem — wtedy potrzebne będą `GOOGLE_APPLICATION_CREDENTIALS` i
`BQ_PROJECT_ID` jak w `manager-dashboard`.
