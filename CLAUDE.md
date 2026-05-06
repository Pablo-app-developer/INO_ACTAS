# Transcriptor de Reuniones

Transcribe audios de reuniones a texto y genera un informe estructurado con resumen, participantes, decisiones y tareas. Toda la carga computacional pesada se ejecuta en servidores externos — la PC local solo envía el archivo y recibe el texto.

## Arquitectura

```
Audio (.m4a/.mp3) → Groq/OpenAI API (transcripción) → DeepSeek API (análisis) → Informe .md
```

| Paso | Servicio | Costo |
|------|----------|-------|
| Transcripción | Groq (whisper-large-v3) | Gratis |
| Análisis | DeepSeek | ~$0.01 por reunión |

## Uso

```bash
python transcribir.py                    # Todos los audios nuevos
python transcribir.py "archivo.m4a"      # Archivo específico
python transcribir.py --listar           # Ver audios y estado
python transcribir.py --forzar           # Reprocesar aunque ya exista
python transcribir.py --sin-analisis     # Solo transcribir, sin DeepSeek
```

## Estructura de archivos

```
proyecto/
├── audios/                  ← Poner aquí los archivos de audio
├── transcripciones/         ← Resultados (generados automáticamente)
├── transcribir.py           ← Script principal
├── run_now.py               ← Lanzador rápido
├── contexto.txt             ← Editar antes de cada reunión
└── .env                     ← API keys
```

## Archivo `contexto.txt`

Editar antes de procesar cada reunión. Mejora la precisión de Whisper y la calidad del informe:
- Descripción breve de la reunión
- Lista de participantes con sus roles
- Vocabulario técnico frecuente (siglas, nombres propios, términos del sector)

## Modos de transcripción (prioridad automática)

1. **Groq API** — si hay `GROQ_API_KEY` en `.env` (recomendado: gratis, rápido, preciso)
2. **OpenAI API** — si hay `OPENAI_API_KEY` ($0.006/min)
3. **Local CPU** — sin ninguna key (muy lento, no recomendado en PCs de gama baja)

## Límites de Groq (plan gratuito)

- 7 200 segundos de audio / día (= 2 horas)
- 25 MB por archivo — el script divide automáticamente en chunks de 15 min

## Dependencias

```
openai           # Cliente para Groq, OpenAI y DeepSeek
pydub            # Split de audio en chunks
rich             # Interfaz de consola
python-dotenv
faster-whisper   # Solo necesario para modo local (fallback)
```
