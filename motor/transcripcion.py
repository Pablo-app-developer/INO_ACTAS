"""Transcripción de audio: API en la nube (Groq/OpenAI) o Whisper local como respaldo."""
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI
from pydub import AudioSegment

from .config import (
    CHUNK_API_MINUTOS, ETAPA_AUDIO, ETAPA_TRANSCRIPCION, MAX_CHARS_PROMPT_WHISPER,
    SEPARADOR_CONTEXTO, ClienteTranscripcion, Progreso, cliente_transcripcion, sin_progreso,
)


class ErrorTranscripcion(Exception):
    """No se pudo obtener texto del audio."""


@dataclass
class ResultadoTranscripcion:
    texto: str
    segmentos: list
    duracion_segundos: float
    servicio: str
    advertencias: list[str] = field(default_factory=list)


def _cortar_en_chunks(audio: AudioSegment, formato: str, **export_kwargs) -> list[tuple[Path, float]]:
    """Divide el audio ya cargado en archivos temporales de CHUNK_API_MINUTOS."""
    chunk_ms = CHUNK_API_MINUTOS * 60 * 1000
    chunks = []
    for inicio in range(0, len(audio), chunk_ms):
        trozo = audio[inicio:min(inicio + chunk_ms, len(audio))]
        tmp = tempfile.NamedTemporaryFile(suffix=f".{formato}", delete=False)
        tmp.close()
        trozo.export(tmp.name, format=formato, **export_kwargs)
        chunks.append((Path(tmp.name), inicio / 1000))
    return chunks


def _agregar_segmentos(segs, offset: float, segmentos: list, textos: list) -> None:
    for seg in segs:
        texto = seg.text.strip()
        segmentos.append({
            "inicio": round(offset + seg.start, 2),
            "fin": round(offset + seg.end, 2),
            "texto": texto,
        })
        textos.append(texto)


def _transcribir_api(audio: AudioSegment, cliente: ClienteTranscripcion, contexto: str,
                     progreso: Progreso) -> tuple[str, list, list[str]]:
    api = OpenAI(api_key=cliente.api_key, base_url=cliente.base_url)
    # Whisper solo necesita la cabecera (nombres y vocabulario), no el contexto ampliado
    prompt = contexto.split(SEPARADOR_CONTEXTO)[0][:MAX_CHARS_PROMPT_WHISPER]
    mono = audio.set_channels(1).set_frame_rate(16000)
    chunks = _cortar_en_chunks(mono, "mp3", bitrate="64k")

    segmentos, textos, advertencias = [], [], []
    try:
        for i, (ruta_chunk, offset) in enumerate(chunks, 1):
            progreso(ETAPA_TRANSCRIPCION, f"Transcribiendo parte {i} de {len(chunks)}", (i - 1) / len(chunks))
            try:
                with open(ruta_chunk, "rb") as f:
                    resultado = api.audio.transcriptions.create(
                        model=cliente.modelo, file=f, language="es",
                        response_format="verbose_json", prompt=prompt,
                    )
                segs = getattr(resultado, "segments", None) or []
                if segs:
                    _agregar_segmentos(segs, offset, segmentos, textos)
                else:
                    # La API devolvió solo texto plano
                    texto = (getattr(resultado, "text", "") or "").strip()
                    if texto:
                        segmentos.append({"inicio": offset, "fin": offset, "texto": texto})
                        textos.append(texto)
            except Exception as e:
                advertencias.append(f"Falló la parte {i} de {len(chunks)}: {e}")
    finally:
        for ruta_chunk, _ in chunks:
            ruta_chunk.unlink(missing_ok=True)
    return " ".join(textos), segmentos, advertencias


def _transcribir_local(audio: AudioSegment, modelo: str,
                       progreso: Progreso) -> tuple[str, list, list[str]]:
    from faster_whisper import WhisperModel

    progreso(ETAPA_TRANSCRIPCION, f"Cargando modelo Whisper local '{modelo}' (lento en CPU)", None)
    whisper = WhisperModel(modelo, device="cpu", compute_type="int8")
    chunks = _cortar_en_chunks(audio, "wav")

    segmentos, textos, advertencias = [], [], []
    try:
        for i, (ruta_chunk, offset) in enumerate(chunks, 1):
            progreso(ETAPA_TRANSCRIPCION, f"Transcribiendo parte {i} de {len(chunks)}", (i - 1) / len(chunks))
            try:
                segs, _ = whisper.transcribe(
                    str(ruta_chunk), language="es", beam_size=5, vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 500},
                )
                _agregar_segmentos(segs, offset, segmentos, textos)
            except Exception as e:
                advertencias.append(f"Falló la parte {i} de {len(chunks)}: {e}")
    finally:
        for ruta_chunk, _ in chunks:
            ruta_chunk.unlink(missing_ok=True)
    return " ".join(textos), segmentos, advertencias


def transcribir(ruta_audio: Path, contexto: str = "", modelo_local: str = "base",
                progreso: Progreso = sin_progreso) -> ResultadoTranscripcion:
    """Transcribe un audio o video. `contexto` calibra el vocabulario de Whisper."""
    cliente = cliente_transcripcion()
    progreso(ETAPA_AUDIO, "Cargando audio", None)
    try:
        audio = AudioSegment.from_file(str(ruta_audio))
    except Exception as e:
        raise ErrorTranscripcion(f"No se pudo leer el archivo '{ruta_audio.name}': {e}") from e

    if cliente.es_local:
        texto, segmentos, advertencias = _transcribir_local(audio, modelo_local, progreso)
    else:
        texto, segmentos, advertencias = _transcribir_api(audio, cliente, contexto, progreso)

    if not texto.strip():
        detalle = f" Detalle: {advertencias[0]}" if advertencias else ""
        raise ErrorTranscripcion(f"No se obtuvo texto. Verifica el audio.{detalle}")

    return ResultadoTranscripcion(texto, segmentos, audio.duration_seconds,
                                  cliente.servicio, advertencias)
