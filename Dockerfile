FROM python:3.12-slim

# ffmpeg: pydub lo usa para leer m4a, mp4, mkv, etc.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY motor ./motor
COPY app ./app

# No se ejecuta como root; los datos (base de datos, resultados) viven en el volumen /datos
RUN useradd --system --create-home --uid 10001 transcriptor \
    && mkdir /datos && chown transcriptor /datos
USER transcriptor

ENV DATOS_DIR=/datos HOST=0.0.0.0 PORT=8001 PYTHONUNBUFFERED=1
VOLUME /datos
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/api/salud', timeout=3)"

CMD ["python", "-m", "app"]
