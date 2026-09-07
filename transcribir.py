import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from openai import OpenAI
from pydub import AudioSegment

load_dotenv()

console = Console()

AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".wma",   # audio
    ".mp4", ".webm", ".mkv", ".mov", ".avi",                    # video (ffmpeg extrae la pista de audio)
}
TRANSCRIPCIONES_DIR = Path(__file__).parent / "transcripciones"
AUDIOS_DIR = Path(__file__).parent / "audios"
CONTEXTO_FILE = Path(__file__).parent / "contexto.txt"

GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# Chunks de 15 min exportados a MP3 64kbps mono ≈ 7 MB (límite API: 25 MB)
CHUNK_API_MINUTOS = 15
MAX_CHARS_ANALISIS = 12000


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------

def cargar_contexto() -> str:
    if CONTEXTO_FILE.exists():
        contenido = CONTEXTO_FILE.read_text(encoding="utf-8").strip()
        if contenido:
            console.print(f"[dim]Contexto cargado ({len(contenido)} caracteres)[/dim]")
            return contenido
    return ""


# ---------------------------------------------------------------------------
# Cliente de transcripción (Groq > OpenAI > local)
# ---------------------------------------------------------------------------

def _get_cliente_transcripcion() -> tuple:
    """Devuelve (client, model_name, nombre_servicio) según las keys disponibles."""
    if GROQ_API_KEY:
        client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
        return client, "whisper-large-v3", "Groq (gratis)"
    if OPENAI_API_KEY:
        client = OpenAI(api_key=OPENAI_API_KEY)
        return client, "whisper-1", "OpenAI"
    return None, None, "local"


# ---------------------------------------------------------------------------
# Split de audio para API (MP3 64 kbps mono → archivos pequeños)
# ---------------------------------------------------------------------------

def split_audio_para_api(ruta_audio: Path) -> list[tuple[Path, float]]:
    """Divide el audio en chunks ligeros para enviar a la API."""
    console.print("[dim]Cargando audio...[/dim]")
    audio = AudioSegment.from_file(str(ruta_audio))
    audio = audio.set_channels(1).set_frame_rate(16000)  # mono, 16 kHz
    duracion_ms = len(audio)
    chunk_ms = CHUNK_API_MINUTOS * 60 * 1000

    chunks = []
    for i, inicio in enumerate(range(0, duracion_ms, chunk_ms)):
        fin = min(inicio + chunk_ms, duracion_ms)
        trozo = audio[inicio:fin]
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        trozo.export(tmp.name, format="mp3", bitrate="64k")
        size_mb = Path(tmp.name).stat().st_size / 1_048_576
        chunks.append((Path(tmp.name), inicio / 1000))
        console.print(
            f"  [dim]Chunk {i+1}: {inicio/1000:.0f}s → {fin/1000:.0f}s  ({size_mb:.1f} MB)[/dim]"
        )

    return chunks


# ---------------------------------------------------------------------------
# Transcripción con API en la nube
# ---------------------------------------------------------------------------

def _build_whisper_prompt() -> str:
    """Usa contexto.txt como prompt de vocabulario para Whisper.
    Whisper calibra su vocabulario con este texto (no lo interpreta como instrucción).
    Límite efectivo: ~224 tokens; el texto se trunca automáticamente."""
    contexto = cargar_contexto()
    # Limitar a ~800 caracteres para no superar el límite de tokens de Whisper
    return contexto[:800] if contexto else ""


def transcribir_con_api(ruta_audio: Path, client, model_name: str) -> tuple[str, list]:
    duracion_total = AudioSegment.from_file(str(ruta_audio)).duration_seconds
    console.print(f"[green]Duración total:[/green] {duracion_total/60:.1f} minutos")

    chunks = split_audio_para_api(ruta_audio)
    total_chunks = len(chunks)
    console.print(f"[cyan]Enviando {total_chunks} chunk(s) a la API...[/cyan]")

    whisper_prompt = _build_whisper_prompt()
    segmentos = []
    texto_completo = []

    for i, (chunk_path, offset) in enumerate(chunks, 1):
        console.print(f"\n[yellow]--- Chunk {i}/{total_chunks} ---[/yellow]")
        try:
            with open(chunk_path, "rb") as f:
                resultado = client.audio.transcriptions.create(
                    model=model_name,
                    file=f,
                    language="es",
                    response_format="verbose_json",
                    prompt=whisper_prompt,
                )

            segs = getattr(resultado, "segments", None) or []
            if segs:
                for seg in segs:
                    segmentos.append({
                        "inicio": round(offset + seg.start, 2),
                        "fin":    round(offset + seg.end,   2),
                        "texto":  seg.text.strip(),
                    })
                    texto_completo.append(seg.text.strip())
            else:
                # Fallback: la API devolvió solo texto plano
                texto = (getattr(resultado, "text", "") or "").strip()
                if texto:
                    segmentos.append({"inicio": offset, "fin": offset, "texto": texto})
                    texto_completo.append(texto)

            console.print(f"  [green]Chunk {i} completado[/green]")
        except Exception as e:
            console.print(f"  [red]Error en chunk {i}: {e}[/red]")
        finally:
            chunk_path.unlink(missing_ok=True)

    return " ".join(texto_completo), segmentos


# ---------------------------------------------------------------------------
# Transcripción local (fallback sin ninguna API key)
# ---------------------------------------------------------------------------

def transcribir_local(ruta_audio: Path, modelo: str = "base") -> tuple[str, list]:
    from faster_whisper import WhisperModel
    from pydub import AudioSegment as AS

    console.print(f"[cyan]Cargando modelo Whisper local '{modelo}'...[/cyan]")
    console.print("[yellow]AVISO: la transcripción local en CPU puede ser muy lenta.[/yellow]")
    whisper = WhisperModel(modelo, device="cpu", compute_type="int8")

    duracion_total = AS.from_file(str(ruta_audio)).duration_seconds
    console.print(f"[green]Duración total:[/green] {duracion_total/60:.1f} minutos")

    chunk_ms = CHUNK_API_MINUTOS * 60 * 1000
    audio = AS.from_file(str(ruta_audio))
    duracion_ms = len(audio)

    segmentos = []
    texto_completo = []

    for i, inicio in enumerate(range(0, duracion_ms, chunk_ms)):
        fin = min(inicio + chunk_ms, duracion_ms)
        trozo = audio[inicio:fin]
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        trozo.export(tmp.name, format="wav")
        chunk_path = Path(tmp.name)
        offset = inicio / 1000

        console.print(f"\n[yellow]--- Chunk {i+1} ---[/yellow]")
        try:
            segs, _ = whisper.transcribe(
                str(chunk_path),
                language="es",
                beam_size=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
            )
            for seg in segs:
                segmentos.append({
                    "inicio": round(offset + seg.start, 2),
                    "fin":    round(offset + seg.end,   2),
                    "texto":  seg.text.strip(),
                })
                texto_completo.append(seg.text.strip())
            console.print(f"  [green]Chunk {i+1} completado[/green]")
        except Exception as e:
            console.print(f"  [red]Error en chunk {i+1}: {e}[/red]")
        finally:
            chunk_path.unlink(missing_ok=True)

    return " ".join(texto_completo), segmentos


# ---------------------------------------------------------------------------
# Análisis con DeepSeek
# ---------------------------------------------------------------------------

def _dividir_texto(texto: str, max_chars: int) -> list[str]:
    if len(texto) <= max_chars:
        return [texto]
    bloques = []
    inicio = 0
    while inicio < len(texto):
        fin = inicio + max_chars
        if fin >= len(texto):
            bloques.append(texto[inicio:])
            break
        corte = texto.rfind(". ", inicio, fin)
        if corte == -1:
            corte = texto.rfind(" ", inicio, fin)
        if corte == -1:
            corte = fin
        else:
            corte += 1
        bloques.append(texto[inicio:corte].strip())
        inicio = corte
    return [b for b in bloques if b]


def analizar_con_deepseek(texto: str, nombre_reunion: str) -> dict:
    if not DEEPSEEK_API_KEY:
        console.print("[yellow]Sin DEEPSEEK_API_KEY — se omite el análisis.[/yellow]")
        return {}

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
    contexto = cargar_contexto()

    bloque_contexto = ""
    if contexto:
        bloque_contexto = f"""\n\nCONTEXTO DE LA REUNIÓN (úsalo como referencia principal):
---
{contexto}
---\n"""

    bloques = _dividir_texto(texto, MAX_CHARS_ANALISIS)
    if len(bloques) > 1:
        console.print(
            f"[cyan]Texto largo ({len(texto):,} chars) — resumiendo {len(bloques)} bloques...[/cyan]"
        )
        resumenes = []
        for i, bloque in enumerate(bloques, 1):
            console.print(f"  [dim]Resumiendo bloque {i}/{len(bloques)}...[/dim]")
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{
                    "role": "user",
                    "content": (
                        "Resume este fragmento de reunión conservando decisiones, "
                        f"compromisos, nombres y temas clave. Sé conciso.\n\n{bloque}"
                    ),
                }],
                max_tokens=800,
                temperature=0.2,
            )
            resumenes.append(resp.choices[0].message.content)
        texto_para_analisis = "\n\n---\n\n".join(resumenes)
    else:
        texto_para_analisis = texto

    prompt = f"""Eres un asistente especializado en análisis de reuniones de empresa.
Analiza la siguiente transcripción y extrae:
{bloque_contexto}
1. **RESUMEN EJECUTIVO** (3-5 oraciones)
2. **PARTICIPANTES IDENTIFICADOS**
3. **TEMAS TRATADOS**
4. **DECISIONES TOMADAS**
5. **TAREAS Y COMPROMISOS** (quién, qué, cuándo)
6. **PRÓXIMOS PASOS**

Transcripción "{nombre_reunion}":
---
{texto_para_analisis}
---

Responde en español, formato Markdown."""

    console.print("[cyan]Analizando con DeepSeek...[/cyan]")
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.3,
    )
    return {"analisis": response.choices[0].message.content}


# ---------------------------------------------------------------------------
# Guardado de resultados
# ---------------------------------------------------------------------------

def formatear_tiempo(segundos: float) -> str:
    m, s = divmod(int(segundos), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def guardar_resultados(ruta_audio: Path, texto: str, segmentos: list, analisis: dict) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    carpeta_salida = TRANSCRIPCIONES_DIR / f"{ruta_audio.stem}_{timestamp}"
    carpeta_salida.mkdir(parents=True, exist_ok=True)

    (carpeta_salida / "transcripcion.txt").write_text(
        f"TRANSCRIPCIÓN: {ruta_audio.name}\n"
        f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        + "=" * 60 + "\n\n" + texto,
        encoding="utf-8",
    )

    with open(carpeta_salida / "transcripcion_tiempos.txt", "w", encoding="utf-8") as f:
        f.write(f"TRANSCRIPCIÓN CON TIEMPOS: {ruta_audio.name}\n")
        f.write(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n")
        f.write("=" * 60 + "\n\n")
        for seg in segmentos:
            f.write(f"[{formatear_tiempo(seg['inicio'])} → {formatear_tiempo(seg['fin'])}]\n")
            f.write(f"{seg['texto']}\n\n")

    with open(carpeta_salida / "informe.md", "w", encoding="utf-8") as f:
        f.write(f"# Informe de Reunión: {ruta_audio.stem}\n\n")
        f.write(f"**Archivo:** {ruta_audio.name}  \n")
        f.write(f"**Fecha de procesamiento:** {datetime.now().strftime('%d/%m/%Y %H:%M')}  \n")
        f.write(f"**Segmentos transcritos:** {len(segmentos)}  \n\n---\n\n")
        if analisis.get("analisis"):
            f.write(analisis["analisis"])
            f.write("\n\n---\n\n")
        f.write("## Transcripción Completa\n\n" + texto + "\n\n---\n\n")
        f.write("## Transcripción con Tiempos\n\n")
        for seg in segmentos:
            f.write(f"**[{formatear_tiempo(seg['inicio'])} → {formatear_tiempo(seg['fin'])}]**  \n")
            f.write(f"{seg['texto']}\n\n")

    with open(carpeta_salida / "datos.json", "w", encoding="utf-8") as f:
        json.dump({
            "archivo": ruta_audio.name,
            "fecha": datetime.now().isoformat(),
            "segmentos": segmentos,
            "texto_completo": texto,
            "analisis": analisis.get("analisis", ""),
        }, f, ensure_ascii=False, indent=2)

    return carpeta_salida


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def ya_fue_procesado(ruta_audio: Path) -> bool:
    if not TRANSCRIPCIONES_DIR.exists():
        return False
    return any(
        d.is_dir() and d.name.startswith(ruta_audio.stem)
        for d in TRANSCRIPCIONES_DIR.iterdir()
    )


def listar_audios() -> list[Path]:
    if not AUDIOS_DIR.exists():
        return []
    return sorted(f for f in AUDIOS_DIR.iterdir() if f.suffix.lower() in AUDIO_EXTENSIONS)


# ---------------------------------------------------------------------------
# Procesamiento principal
# ---------------------------------------------------------------------------

def procesar_archivo(ruta_audio: Path, modelo: str = "base", forzar: bool = False, sin_analisis: bool = False) -> None:
    if not forzar and ya_fue_procesado(ruta_audio):
        console.print(
            f"[yellow]Omitiendo '{ruta_audio.name}' — ya transcrito. "
            "Usa --forzar para reprocesar.[/yellow]"
        )
        return

    console.print(Panel(f"[bold]Procesando:[/bold] {ruta_audio.name}", style="blue"))

    client, model_name, servicio = _get_cliente_transcripcion()

    if client:
        console.print(f"[green]Modo:[/green] API en la nube — [bold]{servicio}[/bold] (sin carga local)")
        texto, segmentos = transcribir_con_api(ruta_audio, client, model_name)
    else:
        console.print("[yellow]Modo:[/yellow] Whisper local en CPU (lento — agrega GROQ_API_KEY al .env para acelerar)")
        texto, segmentos = transcribir_local(ruta_audio, modelo)

    if not texto.strip():
        console.print("[red]No se obtuvo texto. Verifica el audio.[/red]")
        return

    if sin_analisis:
        console.print("[dim]Análisis DeepSeek omitido (--sin-analisis).[/dim]")
        analisis = {}
    else:
        analisis = analizar_con_deepseek(texto, ruta_audio.stem)
    carpeta = guardar_resultados(ruta_audio, texto, segmentos, analisis)

    tabla = Table(title="Archivos generados")
    tabla.add_column("Archivo", style="cyan")
    tabla.add_column("Descripción")
    tabla.add_row("transcripcion.txt",        "Texto completo")
    tabla.add_row("transcripcion_tiempos.txt","Texto con marcas de tiempo")
    tabla.add_row("informe.md",               "Informe + análisis IA")
    tabla.add_row("datos.json",               "Datos estructurados")
    console.print(tabla)
    console.print(f"\n[green bold]Guardado en:[/green bold] {carpeta}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Transcribe audios de reuniones — Whisper API (Groq/OpenAI) + análisis DeepSeek",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python transcribir.py                              # Todos los audios nuevos
  python transcribir.py "AUDIO REUNION.m4a"          # Archivo específico
  python transcribir.py --listar                     # Ver audios y estado
  python transcribir.py --forzar                     # Re-procesar aunque ya exista

Modos de transcripción (en orden de preferencia):
  1. Groq API     — agrega GROQ_API_KEY en .env  (gratis, rápido)
  2. OpenAI API   — agrega OPENAI_API_KEY en .env ($0.006/min)
  3. Local CPU    — sin API key (lento, no recomendado en PCs lentas)
        """,
    )
    parser.add_argument("archivo", nargs="?", help="Archivo de audio")
    parser.add_argument(
        "--modelo", "-m",
        default="base",
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Modelo local (solo aplica sin API key). Default: base",
    )
    parser.add_argument("--listar", "-l", action="store_true", help="Listar audios disponibles")
    parser.add_argument("--forzar", "-f", action="store_true", help="Reprocesar aunque ya exista transcripción")
    parser.add_argument("--sin-analisis", action="store_true", help="Omitir análisis con DeepSeek")

    args = parser.parse_args()

    _, _, servicio = _get_cliente_transcripcion()
    analisis_label = "Ninguno (--sin-analisis)" if args.sin_analisis else "DeepSeek"
    console.print(Panel(
        f"[bold cyan]Transcriptor de Reuniones[/bold cyan]\n"
        f"Transcripción: [bold]{servicio}[/bold]  |  Análisis: {analisis_label}",
        style="cyan",
    ))

    if args.listar:
        audios = listar_audios()
        if not audios:
            console.print(f"[yellow]No hay audios en:[/yellow] {AUDIOS_DIR}")
        else:
            tabla = Table(title=f"Audios disponibles ({len(audios)})")
            tabla.add_column("#", style="dim")
            tabla.add_column("Archivo", style="cyan")
            tabla.add_column("Tamaño")
            tabla.add_column("Procesado")
            for i, a in enumerate(audios, 1):
                size_mb = a.stat().st_size / 1_048_576
                procesado = "[green]Sí[/green]" if ya_fue_procesado(a) else "[yellow]No[/yellow]"
                tabla.add_row(str(i), a.name, f"{size_mb:.1f} MB", procesado)
            console.print(tabla)
        return

    if args.archivo:
        ruta = Path(args.archivo)
        if not ruta.is_absolute():
            candidato = AUDIOS_DIR / ruta
            if candidato.exists():
                ruta = candidato
        if not ruta.exists():
            console.print(f"[red]Archivo no encontrado:[/red] {args.archivo}")
            sys.exit(1)
        procesar_archivo(ruta, args.modelo, forzar=args.forzar, sin_analisis=args.sin_analisis)
    else:
        audios = listar_audios()
        if not audios:
            console.print(f"[yellow]No hay audios en:[/yellow] {AUDIOS_DIR}")
            sys.exit(0)
        console.print(f"[green]{len(audios)} archivo(s) encontrado(s).[/green]\n")
        for ruta in audios:
            procesar_archivo(ruta, args.modelo, forzar=args.forzar, sin_analisis=args.sin_analisis)

    console.print("\n[bold green]Proceso completado.[/bold green]")


if __name__ == "__main__":
    main()
