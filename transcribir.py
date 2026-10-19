"""CLI del transcriptor de reuniones. La lógica vive en el paquete `motor`."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from motor import EXTENSIONES_AUDIO, OpcionesProceso, guardar_resultados, procesar_audio
from motor.config import cliente_transcripcion
from motor.transcripcion import ErrorTranscripcion

console = Console()

TRANSCRIPCIONES_DIR = Path(__file__).parent / "transcripciones"
AUDIOS_DIR = Path(__file__).parent / "audios"
PROYECTO_DIR = Path(__file__).parent
# Se resuelve en main() a partir de --contexto. None = transcribir sin contexto.
CONTEXTO_FILE = None


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------

def listar_contextos() -> dict:
    """Mapea alias -> ruta de cada contexto_*.txt de la carpeta del proyecto."""
    contextos = {}
    for ruta in sorted(PROYECTO_DIR.glob("contexto*.txt")):
        alias = ruta.stem.removeprefix("contexto").strip("_-").lower()
        contextos[alias or "contexto"] = ruta
    return contextos


def resolver_contexto(valor: str):
    """Traduce el valor de --contexto a una ruta concreta.

    Acepta una ruta directa o un alias (basta un fragmento del nombre:
    'observatorio' encuentra contexto_reuniones_observatorio.txt).
    Aborta con un mensaje claro si no hay coincidencia o si es ambigua.
    """
    disponibles = listar_contextos()

    def _abortar(mensaje: str):
        console.print(f"[red]{mensaje}[/red]")
        if disponibles:
            console.print("\n[bold]Contextos disponibles:[/bold]")
            for alias, ruta in disponibles.items():
                console.print(f"  [cyan]{alias}[/cyan]  →  {ruta.name}")
            console.print("\nEjemplo: [dim]python transcribir.py \"audio.m4a\" --contexto "
                          f"{next(iter(disponibles))}[/dim]")
        else:
            console.print(f"[yellow]No se encontró ningún archivo contexto*.txt en {PROYECTO_DIR}[/yellow]")
        console.print("\nPara transcribir sin contexto: [dim]--sin-contexto[/dim]")
        sys.exit(1)

    ruta_directa = Path(valor)
    if ruta_directa.suffix.lower() == ".txt":
        if not ruta_directa.is_absolute():
            ruta_directa = PROYECTO_DIR / ruta_directa
        if ruta_directa.exists():
            return ruta_directa
        _abortar(f"Archivo de contexto no encontrado: {valor}")

    clave = valor.strip().lower()
    if clave in disponibles:
        return disponibles[clave]

    coincidencias = [alias for alias in disponibles if clave in alias]
    if len(coincidencias) == 1:
        return disponibles[coincidencias[0]]
    if len(coincidencias) > 1:
        _abortar(f"'{valor}' es ambiguo, coincide con: {', '.join(coincidencias)}")
    _abortar(f"No hay ningún contexto que coincida con '{valor}'.")


def cargar_contexto() -> str:
    if CONTEXTO_FILE is None:
        return ""
    contenido = CONTEXTO_FILE.read_text(encoding="utf-8").strip()
    if not contenido:
        console.print(f"[yellow]Aviso: {CONTEXTO_FILE.name} está vacío.[/yellow]")
        return ""
    console.print(f"[dim]Contexto cargado desde {CONTEXTO_FILE.name} ({len(contenido)} caracteres)[/dim]")
    return contenido


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
    return sorted(f for f in AUDIOS_DIR.iterdir() if f.suffix.lower() in EXTENSIONES_AUDIO)


def _mostrar_progreso(etapa: str, mensaje: str, fraccion) -> None:
    console.print(f"  [dim]{mensaje}[/dim]")


# ---------------------------------------------------------------------------
# Procesamiento principal
# ---------------------------------------------------------------------------

def procesar_archivo(ruta_audio: Path, modelo: str = "base", forzar: bool = False,
                     sin_analisis: bool = False) -> None:
    if not forzar and ya_fue_procesado(ruta_audio):
        console.print(
            f"[yellow]Omitiendo '{ruta_audio.name}' — ya transcrito. "
            "Usa --forzar para reprocesar.[/yellow]"
        )
        return

    console.print(Panel(f"[bold]Procesando:[/bold] {ruta_audio.name}", style="blue"))

    cliente = cliente_transcripcion()
    if cliente.es_local:
        console.print("[yellow]Modo:[/yellow] Whisper local en CPU (lento — agrega GROQ_API_KEY al .env para acelerar)")
    else:
        console.print(f"[green]Modo:[/green] API en la nube — [bold]{cliente.servicio}[/bold] (sin carga local)")

    opciones = OpcionesProceso(contexto=cargar_contexto(), modelo_local=modelo, sin_analisis=sin_analisis)
    try:
        resultado = procesar_audio(ruta_audio, opciones, _mostrar_progreso)
    except ErrorTranscripcion as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print(f"[green]Duración total:[/green] {resultado.duracion_segundos/60:.1f} minutos")
    for aviso in resultado.advertencias:
        console.print(f"[yellow]Aviso: {aviso}[/yellow]")

    carpeta = guardar_resultados(resultado, TRANSCRIPCIONES_DIR)

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
    global CONTEXTO_FILE
    import argparse

    parser = argparse.ArgumentParser(
        description="Transcribe audios de reuniones — Whisper API (Groq/OpenAI) + análisis DeepSeek",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python transcribir.py --listar-contextos                        # Ver contextos disponibles
  python transcribir.py -c observatorio                           # Todos los audios nuevos
  python transcribir.py "AUDIO REUNION.m4a" -c observatorio       # Archivo específico
  python transcribir.py "Entregable.mp4" -c entregas              # Otro contexto
  python transcribir.py "audio.m4a" --sin-contexto                # Sin contexto
  python transcribir.py --listar                                  # Ver audios y estado
  python transcribir.py "audio.m4a" -c observatorio --forzar      # Re-procesar

El contexto (--contexto/-c) es obligatorio: mejora la precisión de Whisper con los
nombres propios y el vocabulario técnico, y alimenta el análisis posterior.

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
    parser.add_argument(
        "--contexto", "-c",
        help="Contexto a usar: alias (ej. observatorio, entregas) o ruta a un .txt. "
             "Obligatorio salvo con --sin-contexto o --listar",
    )
    parser.add_argument(
        "--sin-contexto", action="store_true",
        help="Transcribir sin contexto (menor precisión en nombres y vocabulario técnico)",
    )
    parser.add_argument(
        "--listar-contextos", action="store_true",
        help="Listar los contextos disponibles y salir",
    )

    args = parser.parse_args()

    if args.listar_contextos:
        disponibles = listar_contextos()
        if not disponibles:
            console.print(f"[yellow]No hay archivos contexto*.txt en:[/yellow] {PROYECTO_DIR}")
            return
        tabla = Table(title=f"Contextos disponibles ({len(disponibles)})")
        tabla.add_column("Alias", style="cyan")
        tabla.add_column("Archivo")
        tabla.add_column("Primera línea", style="dim")
        for alias, ruta in disponibles.items():
            primera = ruta.read_text(encoding="utf-8").strip().splitlines()
            resumen = (primera[0][:70] + "…") if primera and len(primera[0]) > 70 else (primera[0] if primera else "(vacío)")
            tabla.add_row(alias, ruta.name, resumen)
        console.print(tabla)
        return

    if not args.listar:
        if args.contexto and args.sin_contexto:
            console.print("[red]--contexto y --sin-contexto son mutuamente excluyentes.[/red]")
            sys.exit(1)
        if args.contexto:
            CONTEXTO_FILE = resolver_contexto(args.contexto)
        elif not args.sin_contexto:
            console.print("[red]Falta indicar el contexto de la transcripción (--contexto).[/red]")
            disponibles = listar_contextos()
            if disponibles:
                console.print("\n[bold]Contextos disponibles:[/bold]")
                for alias, ruta in disponibles.items():
                    console.print(f"  [cyan]{alias}[/cyan]  →  {ruta.name}")
                console.print(f"\nEjemplo: [dim]python transcribir.py \"audio.m4a\" --contexto "
                              f"{next(iter(disponibles))}[/dim]")
            else:
                console.print(f"[yellow]No hay archivos contexto*.txt en {PROYECTO_DIR}[/yellow]")
            console.print("\nPara transcribir sin contexto: [dim]--sin-contexto[/dim]")
            sys.exit(1)

    analisis_label = "Ninguno (--sin-analisis)" if args.sin_analisis else "DeepSeek"
    console.print(Panel(
        f"[bold cyan]Transcriptor de Reuniones[/bold cyan]\n"
        f"Transcripción: [bold]{cliente_transcripcion().servicio}[/bold]  |  Análisis: {analisis_label}",
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
