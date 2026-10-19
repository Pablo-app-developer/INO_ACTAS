"""Contexto estructurado de una reunión y su conversión a texto para Whisper y DeepSeek."""
from pydantic import BaseModel, Field, field_validator

from .config import SEPARADOR_CONTEXTO


class Participante(BaseModel):
    nombre: str
    cargo: str = ""
    asiste: bool = True       # False = solo es mencionado en la reunión
    nota: str = ""            # aclaraciones, p. ej. "no es médica, no usar 'Dra.'"

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre del participante no puede estar vacío")
        return v


class Contexto(BaseModel):
    nombre: str                                     # p. ej. "Reunión semanal del Observatorio"
    descripcion: str = ""
    participantes: list[Participante] = Field(default_factory=list)
    palabras_clave: list[str] = Field(default_factory=list)
    notas: str = ""                                 # información adicional para el análisis

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El nombre no puede estar vacío")
        return v

    @field_validator("palabras_clave")
    @classmethod
    def _limpiar_palabras(cls, v: list[str]) -> list[str]:
        """Quita espacios, vacíos y duplicados (sin distinguir mayúsculas), conservando el orden."""
        vistas, limpias = set(), []
        for palabra in v:
            palabra = palabra.strip()
            if palabra and palabra.lower() not in vistas:
                vistas.add(palabra.lower())
                limpias.append(palabra)
        return limpias

    def a_texto(self) -> str:
        """Texto de contexto para el motor.

        Whisper solo lee los primeros ~800 caracteres, así que lo esencial para el
        reconocimiento (nombres y vocabulario) va primero. El resto alimenta el análisis.
        """
        asisten = [p.nombre for p in self.participantes if p.asiste]
        mencionados = [p.nombre for p in self.participantes if not p.asiste]

        cabecera = [f"{self.nombre}."]
        if asisten:
            cabecera.append(f"Hablan: {', '.join(asisten)}.")
        if mencionados:
            cabecera.append(f"Mencionan a: {', '.join(mencionados)}.")
        if self.palabras_clave:
            cabecera.append(f"Términos: {', '.join(self.palabras_clave)}.")

        ampliado = []
        if self.descripcion.strip():
            ampliado.append("DESCRIPCIÓN\n" + self.descripcion.strip())
        for titulo, grupo in (("PARTICIPANTES Y ROLES", [p for p in self.participantes if p.asiste]),
                              ("MENCIONADOS (no asisten)", [p for p in self.participantes if not p.asiste])):
            lineas = [_linea_participante(p) for p in grupo if p.cargo or p.nota]
            if lineas:
                ampliado.append(titulo + "\n" + "\n".join(lineas))
        if self.notas.strip():
            ampliado.append("NOTAS\n" + self.notas.strip())

        texto = " ".join(cabecera)
        if ampliado:
            texto += (
                SEPARADOR_CONTEXTO + "CONTEXTO AMPLIADO (alimenta el análisis posterior; "
                "Whisper solo lee la cabecera de arriba)\n\n"
                + "\n\n".join(ampliado)
            )
        return texto


def _linea_participante(p: Participante) -> str:
    linea = f"- {p.nombre}"
    if p.cargo:
        linea += f" — {p.cargo}"
    if p.nota:
        linea += f" ({p.nota})"
    return linea
