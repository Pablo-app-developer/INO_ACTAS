from motor.config import SEPARADOR_CONTEXTO
from motor.contexto import Contexto, Participante

from .conftest import CONTEXTO_EJEMPLO


def test_plantillas_iniciales_se_cargan_una_sola_vez(client):
    lista = client.get("/api/contextos").json()
    nombres = [c["nombre"] for c in lista]
    assert len(lista) == 4
    assert "Reunión semanal del Observatorio" in nombres


def test_crud_contexto(client):
    r = client.post("/api/contextos", json=CONTEXTO_EJEMPLO)
    assert r.status_code == 201
    id_ = r.json()["id"]

    assert client.get(f"/api/contextos/{id_}").json()["nombre"] == "Reunión de prueba"

    cambio = {**CONTEXTO_EJEMPLO, "palabras_clave": ["otra"]}
    r = client.put(f"/api/contextos/{id_}", json=cambio)
    assert r.status_code == 200 and r.json()["palabras_clave"] == ["otra"]

    assert client.delete(f"/api/contextos/{id_}").status_code == 204
    assert client.get(f"/api/contextos/{id_}").status_code == 404
    assert client.delete(f"/api/contextos/{id_}").status_code == 404


def test_nombre_duplicado_sin_distinguir_mayusculas(client):
    client.post("/api/contextos", json=CONTEXTO_EJEMPLO)
    r = client.post("/api/contextos", json={**CONTEXTO_EJEMPLO, "nombre": "REUNIÓN DE PRUEBA".lower().replace("reunión", "reunión")})
    assert r.status_code == 409


def test_validacion(client):
    assert client.post("/api/contextos", json={**CONTEXTO_EJEMPLO, "nombre": "  "}).status_code == 422
    malo = {**CONTEXTO_EJEMPLO, "participantes": [{"nombre": ""}]}
    assert client.post("/api/contextos", json=malo).status_code == 422


def test_palabras_clave_se_limpian():
    c = Contexto(nombre="x", palabras_clave=[" CPAP ", "cpap", "", "BPAP"])
    assert c.palabras_clave == ["CPAP", "BPAP"]


def test_a_texto_pone_lo_esencial_primero():
    c = Contexto(
        nombre="Reunión X",
        descripcion="Texto largo " * 200,
        participantes=[Participante(nombre="Ana", cargo="jefa"),
                       Participante(nombre="Luis", asiste=False, cargo="externo")],
        palabras_clave=["CPAP", "BPAP"],
        notas="Algo importante",
    )
    texto = c.a_texto()
    cabecera = texto.split(SEPARADOR_CONTEXTO)[0]
    assert "Hablan: Ana." in cabecera and "Mencionan a: Luis." in cabecera
    assert "Términos: CPAP, BPAP." in cabecera
    assert "Texto largo" not in cabecera          # la descripción larga no ocupa el prompt de Whisper
    assert len(cabecera) < 800
    assert "- Ana — jefa" in texto and "- Luis — externo" in texto
    assert "Algo importante" in texto


def test_a_texto_minimo():
    assert Contexto(nombre="Solo nombre").a_texto() == "Solo nombre."
