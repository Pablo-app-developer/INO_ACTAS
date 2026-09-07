# Transcriptor de Reuniones

Transcribe automáticamente audios de reuniones a texto y genera un informe estructurado con resumen, participantes, decisiones y tareas. Toda la carga computacional se ejecuta en servidores externos — la PC local solo envía el archivo y recibe el texto.

## Cómo funciona

```
Audio o video → ffmpeg (extrae audio) → API de transcripción → API de análisis → Informe .md
```

| Paso | Servicio | Costo |
|------|----------|-------|
| Transcripción | Groq (whisper-large-v3) | Gratis |
| Transcripción alternativa | OpenAI Whisper | ~$0.006/min |
| Análisis e informe | DeepSeek | ~$0.01/reunión |
| Fallback sin internet | Whisper local CPU | Gratis (lento) |

## Requisitos

- Python 3.9+
- Una cuenta en [Groq](https://console.groq.com) (gratis) para transcripción

## Instalación

```bash
git clone https://github.com/Pablo-app-developer/Transcripcion-audios.git
cd Transcripcion-audios
pip install -r requirements.txt
```

Copia el archivo de ejemplo y agrega tu API key:

```bash
cp .env.example .env
# Edita .env y pega tu GROQ_API_KEY
```

## Uso

```bash
# Transcribir todos los audios nuevos en /audios
python transcribir.py

# Transcribir un archivo específico
python transcribir.py "mi_reunion.m4a"

# Ver audios disponibles y cuáles ya fueron procesados
python transcribir.py --listar

# Reprocesar aunque ya exista transcripción
python transcribir.py --forzar

# Transcribir sin generar informe de análisis
python transcribir.py --sin-analisis
```

## Estructura del proyecto

```
Transcripcion-audios/
├── audios/                        ← Coloca aquí los archivos de audio o video
├── transcripciones/               ← Resultados (se generan automáticamente)
│   └── NOMBRE_YYYYMMDD_HHMMSS/
│       ├── transcripcion.txt          # Texto completo
│       ├── transcripcion_tiempos.txt  # Texto con marcas de tiempo
│       ├── informe.md                 # Informe + análisis IA
│       └── datos.json                 # Datos estructurados en JSON
├── transcribir.py                 ← Script principal
├── run_now.py                     ← Lanzador rápido
├── contexto.txt                   ← Editar antes de cada reunión
├── .env                           ← API keys (no se sube al repo)
├── .env.example                   ← Plantilla de configuración
└── requirements.txt
```

## Personalización por reunión: `contexto.txt`

Edita este archivo antes de procesar cada reunión para mejorar la precisión de la transcripción y la calidad del informe:

```
CONTEXTO DE LA REUNIÓN:
Reunión de planificación trimestral — Empresa ABC — 10 de junio de 2026.
Objetivo: revisar OKRs del Q2 y definir prioridades del Q3.

PARTICIPANTES:
- María: directora de producto
- Juan: líder técnico
- Ana: diseño UX

VOCABULARIO TÉCNICO FRECUENTE:
OKR, KPI, sprint, backlog, pipeline, nombre del producto, nombre del cliente
```

El vocabulario también se usa como prompt para que Whisper reconozca correctamente nombres propios, siglas y términos del sector.

## Modos de transcripción

El script elige automáticamente según las claves disponibles en `.env`:

1. **Groq API** — con `GROQ_API_KEY` (recomendado: gratis, rápido, muy preciso)
2. **OpenAI API** — con `OPENAI_API_KEY` ($0.006/min)
3. **Local CPU** — sin ninguna key (no requiere internet, pero es muy lento)

## Límites del plan gratuito de Groq

- 7 200 segundos de audio por día (= 2 horas)
- Archivos de hasta 25 MB por request
- El script divide automáticamente audios largos en chunks de 15 minutos

## Formatos soportados

**Audio:** `.mp3` `.wav` `.m4a` `.ogg` `.flac` `.opus` `.wma`

**Video:** `.mp4` `.webm` `.mkv` `.mov` `.avi`

En los videos, ffmpeg extrae solo la pista de audio y la convierte a MP3 mono 16 kHz antes de enviarla; el video nunca se sube ni cuenta extra en la cuota.

## Dependencias

| Paquete | Uso |
|---------|-----|
| `openai` | Cliente para Groq, OpenAI y DeepSeek |
| `pydub` | División del audio en chunks |
| `python-dotenv` | Carga de variables de entorno |
| `rich` | Interfaz de consola con colores y tablas |
| `faster-whisper` | Transcripción local (fallback sin API key) |
