# Transcriptor de Reuniones

Transcribe audios de reuniones a texto y genera un informe estructurado con resumen, participantes, decisiones y tareas. Toda la carga computacional pesada se ejecuta en servidores externos — la PC local solo envía el archivo y recibe el texto.

## Arquitectura

```
Audio o video → ffmpeg (extrae audio) → Groq/OpenAI API (transcripción) → DeepSeek API (análisis) → Informe .md
```

| Paso | Servicio | Costo |
|------|----------|-------|
| Transcripción | Groq (whisper-large-v3) | Gratis |
| Análisis | DeepSeek | ~$0.01 por reunión |

## Uso

```bash
python transcribir.py --listar-contextos              # Ver contextos disponibles
python transcribir.py -c observatorio                 # Todos los audios nuevos
python transcribir.py "archivo.m4a" -c observatorio   # Archivo específico
python transcribir.py "entrega.mp4" -c entregas       # Otro contexto
python transcribir.py --listar                        # Ver audios y estado
python transcribir.py "a.m4a" -c entregas --forzar    # Reprocesar aunque ya exista
python transcribir.py "a.m4a" -c entregas --sin-analisis  # Solo transcribir, sin DeepSeek
python transcribir.py "a.m4a" --sin-contexto          # Sin contexto (menor precisión)
```

**`--contexto` / `-c` es obligatorio** (salvo con `--listar`, `--listar-contextos` o
`--sin-contexto`). Acepta un alias parcial o la ruta a un `.txt`; si no coincide o es
ambiguo, el script aborta y lista las opciones en vez de continuar en silencio.

## Estructura de archivos

```
proyecto/
├── audios/                  ← Poner aquí los archivos de audio o video
├── transcripciones/         ← Resultados (generados automáticamente)
├── motor/                   ← Lógica reutilizable (sin consola ni web): config, transcripcion, analisis, pipeline
├── app/                     ← API web (FastAPI): main, cola, repos, db, plantillas_iniciales.json
├── tests/                   ← pytest (motor simulado, sin gastar APIs)
├── transcribir.py           ← CLI delgado que usa motor/
├── run_now.py               ← Lanzador rápido
├── contexto_*.txt           ← Un archivo por tipo de reunión (ver abajo)
└── .env                     ← API keys
```

## Archivos `contexto_*.txt`

Cada tipo de reunión tiene su propio contexto. El script descubre automáticamente
todos los `contexto*.txt` de la raíz del proyecto y deriva el alias del nombre:

| Archivo | Alias | Contenido |
|---------|-------|-----------|
| `contexto_reuniones_observatorio.txt` | `reuniones_observatorio` | Reuniones semanales del Observatorio (INO) |
| `contexto_entregas_diego.txt` | `entregas_diego` | Entregables semanales del desarrollo de Datamet 2.0 |

Basta un fragmento del alias: `-c observatorio` o `-c entregas`. Para agregar un tipo
nuevo, crear otro `contexto_<lo-que-sea>.txt`; no hay que tocar el script.

Cada archivo mejora la precisión de Whisper y la calidad del informe, e incluye:
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

## API web (en desarrollo)

```bash
python -m app                     # puerto 8001; API en http://localhost:8001/docs
uvicorn app.main:app --port 8001 --reload   # desarrollo con recarga
python -m pytest                  # 75 pruebas, no usan las APIs reales
# Interfaz web: http://localhost:8001/  (HTML/CSS/JS puros en app/static, sin compilación)
```

- Contextos estructurados (participantes, palabras clave, notas) en SQLite; `app/plantillas_iniciales.json`
  se carga la primera vez desde los antiguos `contexto_*.txt`.
- Subida hasta 2 GB (`MAX_SUBIDA_MB`); un hilo trabajador procesa un audio a la vez.
- El audio se borra al terminar (`CONSERVAR_AUDIO=true` para conservarlo).
- Interfaz: una sola página (`app/static/`), tema claro/oscuro automático, accesible por teclado, responsive.
- Acta en Word: `motor/acta.py` (DeepSeek devuelve JSON validado con pydantic, 1 reintento si es inválido) y
  `motor/docx_acta.py` (arma el .docx sobre `motor/plantillas/acta_ino.docx`, copia exacta del acta 030:
  Arial Narrow, justificado, viñetas con etiqueta en negrita, tablas sin bordes). Número, fecha y hora los
  escribe el usuario; el modelo nunca los inventa. Si el acta falla, se entregan igual informe y transcripción.
  Para cambiar el formato: ajustar las constantes de `docx_acta.py` o reemplazar la plantilla.
- Acceso: usuarios creados por el administrador con `python -m app.usuarios` (sin registro público). Sesión con
  cookie HttpOnly (el token se guarda solo como hash), contraseñas scrypt, bloqueo tras 5 intentos fallidos,
  verificación de `Origin` contra CSRF. Cada persona ve **solo sus transcripciones** (lo ajeno responde 404).
  Plantillas: las institucionales (`usuario_id` NULL) las ven todos y solo las edita un admin; las personales,
  solo su dueño. Rutas de la API: siempre `Depends(usuario_actual)` y consultar con `obtener_de(id, usuario_id)`.
- Despliegue: `Dockerfile`, `docker-compose.yml` (+ `docker-compose.https.yml` con Caddy). Ver `DESPLIEGUE.md`.
  La imagen Docker aún no se ha construido ni probado (Docker Desktop no estaba en marcha al desarrollarlo).
- Dependencias: `requirements-web.txt` (servidor) y `requirements.txt` (todo, incluye CLI y pruebas).
- Pendiente: migrar las API keys personales (Groq/DeepSeek) a cuentas corporativas del INO.
