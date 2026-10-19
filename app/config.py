"""Configuración de la aplicación web. Todo se puede sobrescribir con variables de entorno."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS_INICIALES = Path(__file__).resolve().parent / "plantillas_iniciales.json"
ESTATICOS = Path(__file__).resolve().parent / "static"

# Archivos que el usuario puede descargar de un trabajo terminado
ARCHIVOS_DESCARGABLES = {
    "acta.docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "informe.md": "text/markdown",
    "transcripcion.txt": "text/plain",
    "transcripcion_tiempos.txt": "text/plain",
    "datos.json": "application/json",
}


def _bool(valor: str | None, defecto: bool) -> bool:
    if valor is None:
        return defecto
    return valor.strip().lower() in {"1", "true", "si", "sí", "yes"}


@dataclass(frozen=True)
class Ajustes:
    datos_dir: Path
    max_subida_bytes: int
    conservar_audio: bool
    sesion_horas: float = 12
    cookie_segura: bool = False   # True cuando se sirve por HTTPS

    @property
    def db_path(self) -> Path:
        return self.datos_dir / "app.db"

    @property
    def subidas_dir(self) -> Path:
        return self.datos_dir / "subidas"

    @property
    def resultados_dir(self) -> Path:
        return self.datos_dir / "resultados"

    @classmethod
    def desde_entorno(cls) -> "Ajustes":
        return cls(
            datos_dir=Path(os.getenv("DATOS_DIR", RAIZ / "datos")),
            max_subida_bytes=int(os.getenv("MAX_SUBIDA_MB", "2048")) * 1024 * 1024,
            # Por privacidad el audio se borra al terminar; solo se conserva si se pide.
            conservar_audio=_bool(os.getenv("CONSERVAR_AUDIO"), False),
            sesion_horas=float(os.getenv("SESION_HORAS", "12")),
            # Con HTTPS delante (recomendado), la cookie de sesión solo viaja cifrada
            cookie_segura=_bool(os.getenv("COOKIE_SEGURA"), False),
        )
