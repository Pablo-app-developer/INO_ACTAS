"""Orquesta transcripción + análisis y guarda los resultados en disco."""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .acta import Acta, DatosActa, ErrorActa, generar_acta
from .analisis import analizar, preparar_texto
from .config import Progreso, clave_deepseek, sin_progreso
from .transcripcion import transcribir


@dataclass
class OpcionesProceso:
    contexto: str = ""            # texto del contexto (ya resuelto, no una ruta)
    modelo_local: str = "base"    # solo aplica sin API key
    sin_analisis: bool = False
    acta: DatosActa | None = None  # si se indica, además se redacta el acta


@dataclass
class ResultadoReunion:
    archivo: str
    texto: str
    segmentos: list
    analisis: str
    duracion_segundos: float
    servicio: str
    advertencias: list[str] = field(default_factory=list)
    acta: Acta | None = None


def procesar_audio(ruta_audio: Path, opciones: OpcionesProceso | None = None,
                   progreso: Progreso = sin_progreso) -> ResultadoReunion:
    """Transcribe y analiza un audio. Lanza ErrorTranscripcion si no hay texto."""
    opciones = opciones or OpcionesProceso()
    trans = transcribir(ruta_audio, opciones.contexto, opciones.modelo_local, progreso)
    advertencias = list(trans.advertencias)

    analisis = ""
    acta = None
    if opciones.sin_analisis:
        pass
    elif not clave_deepseek():
        advertencias.append("Sin DEEPSEEK_API_KEY: se omitió el análisis.")
    else:
        # Un solo resumen (si el texto es largo) sirve para el informe y para el acta
        preparado = preparar_texto(trans.texto, progreso)
        analisis = analizar(trans.texto, ruta_audio.stem, opciones.contexto, progreso, preparado)
        if opciones.acta:
            try:
                acta = generar_acta(preparado, ruta_audio.stem, opciones.acta, opciones.contexto, progreso)
            except ErrorActa as e:
                advertencias.append(f"No se pudo generar el acta: {e}")

    return ResultadoReunion(
        archivo=ruta_audio.name, texto=trans.texto, segmentos=trans.segmentos,
        analisis=analisis, duracion_segundos=trans.duracion_segundos,
        servicio=trans.servicio, advertencias=advertencias, acta=acta,
    )


def formatear_tiempo(segundos: float) -> str:
    m, s = divmod(int(segundos), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def guardar_resultados(resultado: ResultadoReunion, directorio_base: Path) -> Path:
    """Escribe transcripcion.txt, transcripcion_tiempos.txt, informe.md y datos.json."""
    ahora = datetime.now()
    fecha = ahora.strftime("%d/%m/%Y %H:%M")
    nombre = Path(resultado.archivo).stem
    carpeta = directorio_base / f"{nombre}_{ahora.strftime('%Y%m%d_%H%M%S')}"
    carpeta.mkdir(parents=True, exist_ok=True)

    (carpeta / "transcripcion.txt").write_text(
        f"TRANSCRIPCIÓN: {resultado.archivo}\nFecha: {fecha}\n"
        + "=" * 60 + "\n\n" + resultado.texto,
        encoding="utf-8",
    )

    with open(carpeta / "transcripcion_tiempos.txt", "w", encoding="utf-8") as f:
        f.write(f"TRANSCRIPCIÓN CON TIEMPOS: {resultado.archivo}\n")
        f.write(f"Fecha: {fecha}\n" + "=" * 60 + "\n\n")
        for seg in resultado.segmentos:
            f.write(f"[{formatear_tiempo(seg['inicio'])} → {formatear_tiempo(seg['fin'])}]\n")
            f.write(f"{seg['texto']}\n\n")

    with open(carpeta / "informe.md", "w", encoding="utf-8") as f:
        f.write(f"# Informe de Reunión: {nombre}\n\n")
        f.write(f"**Archivo:** {resultado.archivo}  \n")
        f.write(f"**Fecha de procesamiento:** {fecha}  \n")
        f.write(f"**Segmentos transcritos:** {len(resultado.segmentos)}  \n\n---\n\n")
        if resultado.analisis:
            f.write(resultado.analisis + "\n\n---\n\n")
        f.write("## Transcripción Completa\n\n" + resultado.texto + "\n\n---\n\n")
        f.write("## Transcripción con Tiempos\n\n")
        for seg in resultado.segmentos:
            f.write(f"**[{formatear_tiempo(seg['inicio'])} → {formatear_tiempo(seg['fin'])}]**  \n")
            f.write(f"{seg['texto']}\n\n")

    with open(carpeta / "datos.json", "w", encoding="utf-8") as f:
        json.dump({
            "archivo": resultado.archivo,
            "fecha": ahora.isoformat(),
            "segmentos": resultado.segmentos,
            "texto_completo": resultado.texto,
            "analisis": resultado.analisis,
            "acta": resultado.acta.model_dump() if resultado.acta else None,
        }, f, ensure_ascii=False, indent=2)

    return carpeta
