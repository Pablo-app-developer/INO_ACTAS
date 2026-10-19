"""Modelos de respuesta de la API."""
from typing import Literal

from pydantic import BaseModel

from motor.acta import DatosActa
from motor.contexto import Contexto


class UsuarioOut(BaseModel):
    id: int
    usuario: str
    nombre: str
    es_admin: bool


class ContextoOut(Contexto):
    id: int
    creado: str
    actualizado: str
    ambito: Literal["institucional", "personal"]
    editable: bool          # si el usuario actual puede modificarla


class TrabajoOut(BaseModel):
    id: str
    estado: Literal["en_cola", "procesando", "completado", "error"]
    archivo: str
    contexto: Contexto | None
    sin_analisis: bool
    acta: DatosActa | None
    etapa: str | None
    mensaje: str | None
    progreso: float
    error: str | None
    advertencias: list[str]
    duracion: float | None
    creado: str
    iniciado: str | None
    terminado: str | None
    archivos: list[str] = []      # archivos descargables (solo si está completado)
