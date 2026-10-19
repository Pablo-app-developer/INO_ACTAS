from fastapi.testclient import TestClient

from app.config import Ajustes
from app.db import BaseDatos
from app.main import create_app
from app.repos import RepoSesiones, RepoUsuarios

from .conftest import CLAVE, iniciar_sesion


def login(cliente, usuario="ana", clave=CLAVE):
    return cliente.post("/api/login", json={"usuario": usuario, "clave": clave})


# ------------------------------------------------------------ sin sesión

def test_rutas_protegidas_sin_sesion(anonimo):
    for ruta in ("/api/trabajos", "/api/contextos", "/api/config", "/api/yo", "/api/contextos/1",
                 "/api/trabajos/x", "/api/trabajos/x/archivos/informe.md"):
        assert anonimo.get(ruta).status_code == 401, ruta
    assert anonimo.post("/api/trabajos", files={"archivo": ("a.mp3", b"x")},
                        data={"sin_contexto": "true"}).status_code == 401
    assert anonimo.delete("/api/trabajos/x").status_code == 401
    assert anonimo.post("/api/cuenta/clave", json={"actual": "a", "nueva": "b"}).status_code == 401


def test_salud_y_estaticos_son_publicos(anonimo):
    assert anonimo.get("/api/salud").status_code == 200
    assert anonimo.get("/static/styles.css").status_code == 200
    assert anonimo.get("/login").status_code == 200 and "Iniciar sesión" in anonimo.get("/login").text


def test_la_pagina_principal_redirige_al_login(anonimo):
    r = anonimo.get("/")
    assert r.status_code == 302 and r.headers["location"] == "/login"


# ----------------------------------------------------------------- login

def test_login_correcto(anonimo):
    r = login(anonimo)
    assert r.status_code == 200
    assert r.json() == {"id": r.json()["id"], "usuario": "ana", "nombre": "Ana Pérez", "es_admin": False}
    assert "clave" not in r.text and "hash" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie

    assert anonimo.get("/api/yo").json()["usuario"] == "ana"
    assert anonimo.get("/").status_code == 200
    assert anonimo.get("/login").headers["location"] == "/"       # ya con sesión, no vuelve al login


def test_usuario_no_distingue_mayusculas(anonimo):
    assert login(anonimo, "ANA").status_code == 200


def test_error_de_login_no_revela_si_el_usuario_existe(anonimo):
    mala = login(anonimo, "ana", "otra-clave-larga")
    inexistente = login(anonimo, "fantasma", "otra-clave-larga")
    assert mala.status_code == inexistente.status_code == 401
    assert mala.json() == inexistente.json()


def test_bloqueo_tras_demasiados_intentos(anonimo):
    for _ in range(5):
        assert login(anonimo, "ana", "incorrecta-123").status_code == 401
    assert login(anonimo, "ana", "incorrecta-123").status_code == 429
    assert login(anonimo).status_code == 429          # ni siquiera la correcta, mientras dura el bloqueo
    assert login(anonimo, "luis").status_code == 200  # otro usuario no se ve afectado


def test_un_acierto_reinicia_el_contador(anonimo):
    for _ in range(4):
        login(anonimo, "ana", "incorrecta-123")
    assert login(anonimo).status_code == 200
    for _ in range(4):
        login(anonimo, "ana", "incorrecta-123")
    assert login(anonimo, "ana", "incorrecta-123").status_code == 401   # no 429: empezó de cero


def test_logout_invalida_la_sesion(client):
    token = client.cookies.get("sesion")
    assert client.post("/api/logout").status_code == 204
    assert client.get("/api/yo").status_code == 401
    client.cookies.set("sesion", token)                 # reutilizar el token viejo no sirve
    assert client.get("/api/yo").status_code == 401


def test_usuario_desactivado_pierde_la_sesion_y_no_entra(client, ajustes):
    RepoUsuarios(BaseDatos(ajustes.db_path)).establecer_activo("ana", False)
    assert client.get("/api/yo").status_code == 401
    assert login(TestClient(client.app), "ana").status_code == 401


def test_la_sesion_vence(tmp_path, motor):
    ajustes = Ajustes(datos_dir=tmp_path / "d", max_subida_bytes=1024, conservar_audio=False, sesion_horas=-1)
    with TestClient(create_app(ajustes, procesar=motor)) as c:
        RepoUsuarios(BaseDatos(ajustes.db_path)).crear("ana", "Ana", CLAVE)
        assert login(c).status_code == 200
        assert c.get("/api/yo").status_code == 401       # ya venció


def test_cookie_segura_cuando_hay_https(tmp_path, motor):
    ajustes = Ajustes(datos_dir=tmp_path / "d", max_subida_bytes=1024, conservar_audio=False, cookie_segura=True)
    with TestClient(create_app(ajustes, procesar=motor)) as c:
        RepoUsuarios(BaseDatos(ajustes.db_path)).crear("ana", "Ana", CLAVE)
        assert "secure" in login(c).headers["set-cookie"].lower()


def test_el_token_no_se_guarda_en_claro(client, ajustes):
    token = client.cookies.get("sesion")
    with BaseDatos(ajustes.db_path).conexion() as con:
        guardados = [f["token_hash"] for f in con.execute("SELECT token_hash FROM sesiones")]
    assert token not in guardados and len(guardados[0]) == 64


# --------------------------------------------------------- cambio de clave

def test_cambiar_clave(servidor, client):
    otra_sesion = iniciar_sesion(TestClient(servidor), "ana")
    assert client.post("/api/cuenta/clave", json={"actual": "mal-puesta-1", "nueva": "nueva-clave-segura"}).status_code == 403
    r = client.post("/api/cuenta/clave", json={"actual": CLAVE, "nueva": "corta"})
    assert r.status_code == 422 and "10 caracteres" in r.json()["detail"]

    assert client.post("/api/cuenta/clave", json={"actual": CLAVE, "nueva": "nueva-clave-segura"}).status_code == 204
    assert client.get("/api/yo").status_code == 200           # la sesión actual sigue
    assert otra_sesion.get("/api/yo").status_code == 401      # las demás se cierran
    assert login(TestClient(servidor), "ana", CLAVE).status_code == 401
    assert login(TestClient(servidor), "ana", "nueva-clave-segura").status_code == 200


# ------------------------------------------------------------------- CSRF

def test_rechaza_peticiones_de_otro_origen(client):
    ajeno = {"Origin": "https://sitio-malicioso.example"}
    assert client.post("/api/logout", headers=ajeno).status_code == 403
    assert client.post("/api/contextos", json={"nombre": "x"}, headers=ajeno).status_code == 403
    assert client.get("/api/yo", headers=ajeno).status_code == 200          # las lecturas no cambian nada
    propio = {"Origin": "http://testserver"}
    assert client.post("/api/contextos", json={"nombre": "x"}, headers=propio).status_code == 201


def test_login_tambien_verifica_el_origen(anonimo):
    r = anonimo.post("/api/login", json={"usuario": "ana", "clave": CLAVE},
                     headers={"Origin": "https://sitio-malicioso.example"})
    assert r.status_code == 403
