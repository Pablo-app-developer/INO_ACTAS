"""Cola de trabajos en segundo plano: un hilo trabajador procesa un audio a la vez.

Se procesa en serie a propósito: Groq limita las horas de audio por día y pydub/ffmpeg
consumen CPU, así que varios audios en paralelo no darían ventaja.
"""
import logging
import queue
import shutil
import threading
from pathlib import Path
from typing import Callable

from motor import DatosActa, OpcionesProceso, guardar_resultados, procesar_audio
from motor.config import ETAPA_ANALISIS, ETAPA_AUDIO, ETAPA_TRANSCRIPCION
from motor.contexto import Contexto
from motor.docx_acta import construir_docx
from motor.transcripcion import ErrorTranscripcion

from .config import Ajustes
from .repos import RepoTrabajos

log = logging.getLogger("transcriptor.cola")

# Cada etapa ocupa un tramo de la barra de progreso global (0..1)
TRAMOS = {
    ETAPA_AUDIO: (0.00, 0.05),
    ETAPA_TRANSCRIPCION: (0.05, 0.80),
    ETAPA_ANALISIS: (0.80, 0.98),
}


def progreso_global(etapa: str, fraccion: float | None) -> float:
    inicio, fin = TRAMOS.get(etapa, (0.0, 0.98))
    return inicio + (fin - inicio) * (fraccion or 0.0)


def ruta_subida(ajustes: Ajustes, id_trabajo: str) -> Path | None:
    carpeta = ajustes.subidas_dir / id_trabajo
    archivos = sorted(carpeta.glob("original.*")) if carpeta.exists() else []
    return archivos[0] if archivos else None


class Cola:
    def __init__(self, ajustes: Ajustes, trabajos: RepoTrabajos,
                 procesar: Callable = procesar_audio):
        self.ajustes = ajustes
        self.trabajos = trabajos
        self.procesar = procesar
        self._cola: queue.Queue[str | None] = queue.Queue()
        self._hilo: threading.Thread | None = None

    def iniciar(self) -> None:
        """Arranca el hilo y reencola lo que quedó pendiente antes de un reinicio."""
        self.trabajos.reencolar_interrumpidos()
        for id_ in self.trabajos.en_cola():
            self._cola.put(id_)
        self._hilo = threading.Thread(target=self._bucle, name="cola-transcripcion", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._cola.put(None)
        if self._hilo:
            self._hilo.join(timeout=5)

    def encolar(self, id_trabajo: str) -> None:
        self._cola.put(id_trabajo)

    def _bucle(self) -> None:
        while True:
            id_ = self._cola.get()
            if id_ is None:
                return
            try:
                self._ejecutar(id_)
            except Exception:  # un trabajo defectuoso nunca debe matar al trabajador
                log.exception("Fallo no controlado en el trabajo %s", id_)
                self.trabajos.marcar_error(id_, "Error inesperado del servidor.")

    def _ejecutar(self, id_: str) -> None:
        trabajo = self.trabajos.obtener(id_)
        if trabajo is None or trabajo["estado"] != "en_cola":
            return  # fue eliminado o ya se procesó
        audio = ruta_subida(self.ajustes, id_)
        if audio is None:
            self.trabajos.marcar_error(id_, "No se encontró el archivo de audio subido.")
            return

        self.trabajos.marcar_procesando(id_)
        contexto = Contexto.model_validate(trabajo["contexto"]) if trabajo["contexto"] else None
        opciones = OpcionesProceso(
            contexto=contexto.a_texto() if contexto else "",
            sin_analisis=trabajo["sin_analisis"],
            acta=DatosActa.model_validate(trabajo["acta"]) if trabajo["acta"] else None,
        )

        def progreso(etapa: str, mensaje: str, fraccion: float | None = None) -> None:
            self.trabajos.actualizar_progreso(id_, etapa, mensaje, progreso_global(etapa, fraccion))

        try:
            resultado = self.procesar(audio, opciones, progreso)
            # El nombre original (no "original.mp3") es el que aparece en los informes
            resultado.archivo = trabajo["archivo"]
            carpeta = guardar_resultados(resultado, self.ajustes.resultados_dir / id_)
            advertencias = list(resultado.advertencias)
            if resultado.acta:
                try:
                    construir_docx(resultado.acta, carpeta / "acta.docx")
                except Exception as e:  # el informe y la transcripción no deben perderse por esto
                    log.exception("No se pudo construir el Word del trabajo %s", id_)
                    advertencias.append(f"No se pudo crear el documento Word del acta: {e}")
            self.trabajos.marcar_completado(id_, carpeta.name, resultado.duracion_segundos, advertencias)
        except ErrorTranscripcion as e:
            self.trabajos.marcar_error(id_, str(e))
        except Exception as e:
            log.exception("Error procesando el trabajo %s", id_)
            self.trabajos.marcar_error(id_, f"Error procesando el audio: {e}")
        finally:
            if not self.ajustes.conservar_audio:
                shutil.rmtree(self.ajustes.subidas_dir / id_, ignore_errors=True)
