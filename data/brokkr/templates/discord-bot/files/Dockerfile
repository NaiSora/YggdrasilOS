FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements*.txt ./
# requirements.txt, plus ceux des modules (requirements-musique.txt…), pas ceux des tests
RUN for f in requirements*.txt; do [ "$f" = requirements-dev.txt ] || pip install --no-cache-dir -r "$f"; done

COPY . .
RUN useradd --create-home --uid 1000 bot && mkdir -p data && chown bot:bot data
USER bot

CMD ["python", "bot.py"]
