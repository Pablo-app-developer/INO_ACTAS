"""Acta de reunión: estructura de datos y generación con DeepSeek (salida JSON validada).

La estructura sigue el acta del INO: una sección fija de información general, secciones
temáticas libres (párrafos, listas con etiqueta, tablas) y una tabla final de compromisos.
"""
import json
from datetime import date
from typing import Annotated, Literal

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

from .config import ETAPA_ANALISIS, Progreso, clave_deepseek, sin_progreso

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]
PRIORIDADES = ("Alta", "Media", "Baja", "Recurrente")


class ErrorActa(Exception):
    """No se pudo generar el acta."""


def fecha_larga(fecha: date) -> str:
    """02 de septiembre de 2026"""
    return f"{fecha.day:02d} de {MESES[fecha.month - 1]} de {fecha.year}"


# ----------------------------------------------------------------- estructura

class Parrafo(BaseModel):
    tipo: Literal["parrafo"] = "parrafo"
    texto: str


class Subtitulo(BaseModel):
    tipo: Literal["subtitulo"] = "subtitulo"
    texto: str


class Punto(BaseModel):
    etiqueta: str = ""      # se muestra en negrita antes del texto (opcional)
    texto: str


class Lista(BaseModel):
    tipo: Literal["lista"] = "lista"
    puntos: list[Punto]


class Tabla(BaseModel):
    tipo: Literal["tabla"] = "tabla"
    columnas: list[str]
    filas: list[list[str]]


Bloque = Annotated[Parrafo | Subtitulo | Lista | Tabla, Field(discriminator="tipo")]


class Seccion(BaseModel):
    titulo: str
    bloques: list[Bloque]


class Compromiso(BaseModel):
    responsable: str
    compromiso: str
    prioridad: Literal["Alta", "Media", "Baja", "Recurrente"] = "Media"


class Acta(BaseModel):
    numero: str = ""                 # lo escribe el usuario, p. ej. "030"
    titulo_reunion: str              # p. ej. "Observatorio de Datos e Innovación Clínica"
    fecha: str                       # ya en formato largo: "02 de septiembre de 2026"
    hora: str = ""
    objetivo: str
    participantes: list[str]
    introduccion: str                # párrafo de la sección 1
    apertura: str = ""               # párrafo que cierra la sección 1
    secciones: list[Seccion]
    compromisos: list[Compromiso] = Field(default_factory=list)


class DatosActa(BaseModel):
    """Datos que aporta el usuario y que el modelo no debe inventar."""
    numero: str = ""
    fecha: date
    hora: str = ""


# ----------------------------------------------------------------- generación

PROMPT_SISTEMA = """Eres el redactor de actas del Instituto Neumológico del Oriente (INO).
Conviertes la transcripción de una reunión en un acta formal y la devuelves SOLO como un objeto JSON válido.

REGLAS DE REDACCIÓN
- Tono institucional, formal, en tercera persona y tiempo pasado. Español de Colombia.
- Usa únicamente lo que está en la transcripción y en el contexto. NO inventes cifras, fechas, nombres,
  acuerdos ni cargos. Si algo no queda claro, omítelo o dilo con cautela ("se mencionó que...").
- Los nombres y tratamientos (Ing., Dra., Dr.) deben escribirse como aparecen en el CONTEXTO.
- La transcripción es automática y puede tener errores de reconocimiento: corrige nombres y términos
  técnicos con ayuda del contexto.
- "participantes": solo quienes intervinieron o estuvieron presentes según la transcripción.
- "introduccion": un párrafo (4 a 6 oraciones) sobre el propósito y enfoque de la sesión.
- "objetivo": una frase con el objetivo de la sesión.
- "apertura": un párrafo breve sobre cómo se abrió la sesión (puede ir vacío si no hay nada relevante).
- "secciones": entre 3 y 8 secciones temáticas en el orden en que se trataron los temas. Cada una con
  "titulo" (sin numeración) y "bloques". No incluyas aquí información general ni compromisos.
- Tipos de bloque: {"tipo":"parrafo","texto":...}, {"tipo":"subtitulo","texto":...} (encabezado en negrita
  antes de una lista), {"tipo":"lista","puntos":[{"etiqueta":"Estado:","texto":"..."}]} (la etiqueta es opcional)
  y {"tipo":"tabla","columnas":[...],"filas":[[...],[...]]} (úsala para decisiones técnicas o comparaciones).
- "compromisos": tareas acordadas con responsable claro. "prioridad" solo puede ser "Alta", "Media", "Baja"
  o "Recurrente" (esta última para tareas que se repiten). Si no hubo compromisos, devuelve [].
- No incluyas ni "numero", ni "fecha", ni "hora": los pone el sistema.

FORMATO EXACTO DE SALIDA (solo JSON, sin texto adicional ni bloques de código):
{"titulo_reunion": "...", "objetivo": "...", "participantes": ["..."], "introduccion": "...", "apertura": "...",
 "secciones": [{"titulo": "...", "bloques": [{"tipo": "parrafo", "texto": "..."}]}],
 "compromisos": [{"responsable": "...", "compromiso": "...", "prioridad": "Alta"}]}"""


def _pedir_json(client: OpenAI, mensajes: list[dict]) -> str:
    respuesta = client.chat.completions.create(
        model="deepseek-chat", messages=mensajes, max_tokens=6000, temperature=0.2,
        response_format={"type": "json_object"},
    )
    return respuesta.choices[0].message.content or ""


def generar_acta(texto: str, nombre_reunion: str, datos: DatosActa, contexto: str = "",
                 progreso: Progreso = sin_progreso) -> Acta:
    """Genera el acta estructurada. Lanza ErrorActa si no hay clave o la salida no es válida."""
    api_key = clave_deepseek()
    if not api_key:
        raise ErrorActa("Sin DEEPSEEK_API_KEY: no se puede generar el acta.")
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    usuario = (
        (f"CONTEXTO DE LA REUNIÓN:\n---\n{contexto}\n---\n\n" if contexto else "")
        + f'TRANSCRIPCIÓN "{nombre_reunion}":\n---\n{texto}\n---\n\nRedacta el acta en JSON.'
    )
    mensajes = [{"role": "system", "content": PROMPT_SISTEMA}, {"role": "user", "content": usuario}]

    progreso(ETAPA_ANALISIS, "Redactando el acta", None)
    ultimo_error = ""
    for intento in range(2):
        bruto = _pedir_json(client, mensajes)
        try:
            datos_modelo = json.loads(bruto)
            if not isinstance(datos_modelo, dict):
                raise ValueError("la respuesta no es un objeto JSON")
            for campo in ("numero", "fecha", "hora"):   # los pone el sistema, nunca el modelo
                datos_modelo.pop(campo, None)
            return Acta.model_validate({
                **datos_modelo,
                "numero": datos.numero.strip(),
                "fecha": fecha_larga(datos.fecha),
                "hora": datos.hora.strip(),
            })
        except (ValueError, ValidationError) as e:
            ultimo_error = str(e)[:300]
            mensajes += [
                {"role": "assistant", "content": bruto},
                {"role": "user", "content": f"El JSON no es válido ({ultimo_error}). "
                                            "Devuelve de nuevo el objeto completo y corregido, solo JSON."},
            ]
    raise ErrorActa(f"El modelo no devolvió un acta válida: {ultimo_error}")
