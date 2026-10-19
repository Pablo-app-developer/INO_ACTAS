"""Configuración y constantes del motor. Las API keys se leen del entorno (.env)."""
import os
from dataclasses import dataclass
from typing import Callable, Optional

from dotenv import load_dotenv

load_dotenv()

EXTENSIONES_AUDIO = {
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".opus", ".wma",   # audio
    ".mp4", ".webm", ".mkv", ".mov", ".avi",                    # video (ffmpeg extrae la pista de audio)
}

# Chunks de 15 min exportados a MP3 64kbps mono ≈ 7 MB (límite API: 25 MB)
CHUNK_API_MINUTOS = 15
MAX_CHARS_ANALISIS = 12000
# Whisper solo usa ~224 tokens del prompt; más texto se trunca igualmente
MAX_CHARS_PROMPT_WHISPER = 800
# Separador entre la cabecera del contexto (nombres y vocabulario) y el contexto ampliado
SEPARADOR_CONTEXTO = "\n\n---\n\n"

ETAPA_AUDIO = "audio"
ETAPA_TRANSCRIPCION = "transcripcion"
ETAPA_ANALISIS = "analisis"

# Callback de progreso: (etapa, mensaje, fracción 0..1 dentro de la etapa o None si no se conoce)
Progreso = Callable[[str, str, Optional[float]], None]


def sin_progreso(etapa: str, mensaje: str, fraccion: Optional[float] = None) -> None:
    """Callback nulo por defecto."""


@dataclass(frozen=True)
class ClienteTranscripcion:
    servicio: str          # nombre legible: "Groq (gratis)", "OpenAI", "local"
    modelo: str            # nombre del modelo remoto ("" si es local)
    base_url: Optional[str]
    api_key: Optional[str]

    @property
    def es_local(self) -> bool:
        return self.api_key is None


def clave_deepseek() -> Optional[str]:
    return os.getenv("DEEPSEEK_API_KEY")


def cliente_transcripcion() -> ClienteTranscripcion:
    """Elige el servicio de transcripción según las keys disponibles (Groq > OpenAI > local)."""
    groq = os.getenv("GROQ_API_KEY")
    if groq:
        return ClienteTranscripcion("Groq (gratis)", "whisper-large-v3",
                                    "https://api.groq.com/openai/v1", groq)
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return ClienteTranscripcion("OpenAI", "whisper-1", None, openai_key)
    return ClienteTranscripcion("local", "", None, None)
