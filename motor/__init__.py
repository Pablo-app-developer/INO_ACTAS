"""Motor de transcripción y análisis de reuniones (sin dependencias de consola ni de web)."""
from .acta import Acta, DatosActa
from .config import EXTENSIONES_AUDIO
from .pipeline import OpcionesProceso, ResultadoReunion, procesar_audio, guardar_resultados

__all__ = [
    "Acta",
    "DatosActa",
    "EXTENSIONES_AUDIO",
    "OpcionesProceso",
    "ResultadoReunion",
    "procesar_audio",
    "guardar_resultados",
]
