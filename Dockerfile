# Obraz pod Mac Mini — ta sama konwencja co manager-dashboard.
FROM python:3.12-slim

WORKDIR /app

# Zależności osobno od kodu, żeby zmiana pliku .py nie przebudowywała warstwy
# z pip-em przy każdym deployu.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY atrybuty/ ./atrybuty/
COPY config/ ./config/

# Baza SQLite NIE leży w katalogu montowanym z hosta: na bind mountach
# Docker Desktop (macOS) brakuje blokad plikowych i SQLite wywala się na
# "disk I/O error". Katalog /app/baza to nazwany wolumen.
ENV ATRYBUTY_DB=/app/baza/atrybuty.db
RUN mkdir -p /app/baza /app/dane

EXPOSE 8084

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8084/import',timeout=4)" || exit 1

CMD ["uvicorn", "atrybuty.app:app", "--host", "0.0.0.0", "--port", "8084"]
