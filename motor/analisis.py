"""Análisis de la transcripción con DeepSeek: resumen, decisiones y tareas."""
from openai import OpenAI

from .config import ETAPA_ANALISIS, MAX_CHARS_ANALISIS, Progreso, clave_deepseek, sin_progreso


def dividir_texto(texto: str, max_chars: int) -> list[str]:
    if len(texto) <= max_chars:
        return [texto]
    bloques = []
    inicio = 0
    while inicio < len(texto):
        fin = inicio + max_chars
        if fin >= len(texto):
            bloques.append(texto[inicio:])
            break
        corte = texto.rfind(". ", inicio, fin)
        if corte == -1:
            corte = texto.rfind(" ", inicio, fin)
        if corte == -1:
            corte = fin
        else:
            corte += 1
        bloques.append(texto[inicio:corte].strip())
        inicio = corte
    return [b for b in bloques if b]


def _cliente() -> OpenAI | None:
    api_key = clave_deepseek()
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com") if api_key else None


def preparar_texto(texto: str, progreso: Progreso = sin_progreso) -> str:
    """Si la transcripción es muy larga la resume por bloques; si no, la devuelve igual.

    Se hace una sola vez y el resultado sirve tanto para el informe como para el acta.
    """
    bloques = dividir_texto(texto, MAX_CHARS_ANALISIS)
    if len(bloques) == 1:
        return texto
    client = _cliente()
    if client is None:
        return texto
    resumenes = []
    for i, bloque in enumerate(bloques, 1):
        progreso(ETAPA_ANALISIS, f"Resumiendo bloque {i} de {len(bloques)}", (i - 1) / len(bloques))
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{
                "role": "user",
                "content": (
                    "Resume este fragmento de reunión conservando decisiones, "
                    f"compromisos, nombres y temas clave. Sé conciso.\n\n{bloque}"
                ),
            }],
            max_tokens=800,
            temperature=0.2,
        )
        resumenes.append(resp.choices[0].message.content)
    return "\n\n---\n\n".join(resumenes)


def analizar(texto: str, nombre_reunion: str, contexto: str = "",
             progreso: Progreso = sin_progreso, texto_preparado: str | None = None) -> str:
    """Devuelve el análisis en Markdown, o "" si no hay DEEPSEEK_API_KEY.

    `texto_preparado` es el resultado de `preparar_texto`; si no se da, se calcula aquí.
    """
    client = _cliente()
    if client is None:
        return ""

    texto_para_analisis = texto_preparado if texto_preparado is not None else preparar_texto(texto, progreso)

    bloque_contexto = ""
    if contexto:
        bloque_contexto = f"""\n\nCONTEXTO DE LA REUNIÓN (úsalo como referencia principal):
---
{contexto}
---\n"""

    prompt = f"""Eres un asistente especializado en análisis de reuniones de empresa.
Analiza la siguiente transcripción y extrae:
{bloque_contexto}
1. **RESUMEN EJECUTIVO** (3-5 oraciones)
2. **PARTICIPANTES IDENTIFICADOS**
3. **TEMAS TRATADOS**
4. **DECISIONES TOMADAS**
5. **TAREAS Y COMPROMISOS** (quién, qué, cuándo)
6. **PRÓXIMOS PASOS**

Transcripción "{nombre_reunion}":
---
{texto_para_analisis}
---

Responde en español, formato Markdown."""

    progreso(ETAPA_ANALISIS, "Generando el informe", None)
    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.3,
    )
    return response.choices[0].message.content
