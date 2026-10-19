import time

import pytest
from fastapi.testclient import TestClient

from app.config import Ajustes
from app.db import BaseDatos
from app.main import create_app
from app.repos import RepoUsuarios
from motor import ResultadoReunion
from motor.acta import Acta, Compromiso, Lista, Parrafo, Punto, Seccion
from motor.config import ETAPA_ANALISIS, ETAPA_AUDIO, ETAPA_TRANSCRIPCION
from motor.transcripcion import ErrorTranscripcion


class MotorFalso:
    """Sustituye a procesar_audio: no llama a ninguna API."""

    def __init__(self):
        self.llamadas = []
        self.error: Exception | None = None
        self.advertencias: list[str] = []

    def __call__(self, ruta, opciones, progreso):
        self.llamadas.append((ruta, opciones))
        if self.error:
            raise self.error
        progreso(ETAPA_AUDIO, "Cargando audio", None)
        progreso(ETAPA_TRANSCRIPCION, "Transcribiendo parte 1 de 1", 0.0)
        progreso(ETAPA_ANALISIS, "Generando el informe", None)
        return ResultadoReunion(
            archivo=ruta.name, texto="hola mundo", analisis="" if opciones.sin_analisis else "## Resumen\nOK",
            segmentos=[{"inicio": 0.0, "fin": 1.5, "texto": "hola mundo"}],
            duracion_segundos=90.0, servicio="Falso",
            acta=self._acta(opciones.acta) if opciones.acta else None,
            advertencias=self.advertencias,
        )

    @staticmethod
    def _acta(datos):
        from motor.acta import fecha_larga
        return Acta(
            numero=datos.numero, titulo_reunion="Reunión de prueba", fecha=fecha_larga(datos.fecha),
            hora=datos.hora, objetivo="Probar.", participantes=["Ana"], introduccion="Intro.",
            secciones=[Seccion(titulo="Tema", bloques=[Parrafo(texto="Texto."),
                                                       Lista(puntos=[Punto(etiqueta="A:", texto="b")])])],
            compromisos=[Compromiso(responsable="Ana", compromiso="Hacer algo.", prioridad="Alta")],
        )


@pytest.fixture
def motor():
    return MotorFalso()


@pytest.fixture
def ajustes(tmp_path):
    return Ajustes(datos_dir=tmp_path / "datos", max_subida_bytes=1024 * 1024, conservar_audio=False)


CLAVE = "clave-de-prueba-1"


def iniciar_sesion(cliente: TestClient, usuario: str, clave: str = CLAVE) -> TestClient:
    r = cliente.post("/api/login", json={"usuario": usuario, "clave": clave})
    assert r.status_code == 200, r.text
    return cliente


@pytest.fixture
def app_web(ajustes, motor):
    return create_app(ajustes, procesar=motor)


@pytest.fixture
def servidor(app_web, ajustes):
    """App en marcha con tres usuarios: admin (administrador), ana y luis."""
    with TestClient(app_web):
        usuarios = RepoUsuarios(BaseDatos(ajustes.db_path))
        usuarios.crear("admin", "Administrador", CLAVE, es_admin=True)
        usuarios.crear("ana", "Ana Pérez", CLAVE)
        usuarios.crear("luis", "Luis Gómez", CLAVE)
        yield app_web


@pytest.fixture
def anonimo(servidor):
    """Cliente sin sesión (no sigue redirecciones, para ver las respuestas tal cual)."""
    return TestClient(servidor, follow_redirects=False)


@pytest.fixture
def client(servidor):
    """Cliente con sesión de ana (usuaria normal)."""
    return iniciar_sesion(TestClient(servidor), "ana")


@pytest.fixture
def client_luis(servidor):
    return iniciar_sesion(TestClient(servidor), "luis")


@pytest.fixture
def client_admin(servidor):
    return iniciar_sesion(TestClient(servidor), "admin")


def esperar_fin(client, id_trabajo, timeout=10):
    """Espera a que el trabajo salga de en_cola/procesando."""
    limite = time.time() + timeout
    while time.time() < limite:
        trabajo = client.get(f"/api/trabajos/{id_trabajo}").json()
        if trabajo["estado"] in ("completado", "error"):
            return trabajo
        time.sleep(0.05)
    raise AssertionError(f"El trabajo no terminó: {trabajo}")


CONTEXTO_EJEMPLO = {
    "nombre": "Reunión de prueba",
    "descripcion": "Descripción",
    "participantes": [
        {"nombre": "Ana Pérez", "cargo": "coordinadora"},
        {"nombre": "Luis Gómez", "asiste": False, "nota": "no asiste"},
    ],
    "palabras_clave": ["Datamet", "BigQuery"],
}
