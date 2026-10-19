import sqlite3

import pytest

from app.config import Ajustes
from app.db import BaseDatos
from app.repos import RepoTrabajos, RepoUsuarios
from app.seguridad import LimiteIntentos, hash_clave, hash_token, verificar_clave
from app.usuarios import ejecutar

CLAVE = "clave-de-prueba-1"


@pytest.fixture
def aj(tmp_path):
    return Ajustes(datos_dir=tmp_path / "datos", max_subida_bytes=1024, conservar_audio=False)


def cli(aj, *argv, claves=(), confirmacion=""):
    """Ejecuta la consola devolviendo (código, líneas impresas). `claves` simula lo que se teclea."""
    salida, teclado = [], iter(claves)
    codigo = ejecutar(list(argv), aj, leer_clave=lambda _: next(teclado), confirmar=lambda _: confirmacion,
                      salida=salida.append)
    return codigo, salida


# ---------------------------------------------------------------- consola

def test_crear_listar_y_clave(aj):
    assert cli(aj, "crear", "diego", "--nombre", "Diego Lozano", "--admin", claves=[CLAVE, CLAVE])[0] == 0
    assert cli(aj, "crear", "ana", "--clave", CLAVE)[0] == 0
    _, lineas = cli(aj, "listar")
    assert any("diego" in l and "administrador" in l for l in lineas)
    assert any("ana" in l and "administrador" not in l for l in lineas)

    usuarios = RepoUsuarios(BaseDatos(aj.db_path))
    assert verificar_clave(CLAVE, usuarios.hash_de("diego"))
    assert cli(aj, "clave", "diego", claves=["otra-clave-larga", "otra-clave-larga"])[0] == 0
    assert verificar_clave("otra-clave-larga", usuarios.hash_de("diego"))
    assert not verificar_clave(CLAVE, usuarios.hash_de("diego"))


def test_errores_de_creacion(aj):
    assert cli(aj, "crear", "ana", "--clave", CLAVE)[0] == 0
    codigo, lineas = cli(aj, "crear", "ANA", "--clave", CLAVE)
    assert codigo == 1 and "Ya existe" in lineas[0]
    codigo, lineas = cli(aj, "crear", "luis", "--clave", "corta")
    assert codigo == 1 and "10 caracteres" in lineas[0]
    with pytest.raises(SystemExit, match="no coinciden"):
        cli(aj, "crear", "luis", claves=[CLAVE, "distinta-clave-1"])
    assert [u["usuario"] for u in RepoUsuarios(BaseDatos(aj.db_path)).listar()] == ["ana"]


def test_desactivar_y_activar(aj):
    cli(aj, "crear", "ana", "--clave", CLAVE)
    usuarios = RepoUsuarios(BaseDatos(aj.db_path))
    assert cli(aj, "desactivar", "ana")[0] == 0 and usuarios.hash_de("ana") is None
    assert cli(aj, "activar", "ana")[0] == 0 and usuarios.hash_de("ana") is not None
    assert cli(aj, "desactivar", "fantasma")[0] == 1


def test_admin_dar_y_quitar(aj):
    cli(aj, "crear", "ana", "--clave", CLAVE)
    usuarios = RepoUsuarios(BaseDatos(aj.db_path))
    cli(aj, "admin", "ana")
    assert usuarios.por_nombre("ana")["es_admin"] is True
    cli(aj, "admin", "ana", "--quitar")
    assert usuarios.por_nombre("ana")["es_admin"] is False


def test_eliminar_borra_usuario_trabajos_y_archivos(aj):
    cli(aj, "crear", "ana", "--clave", CLAVE)
    cli(aj, "crear", "luis", "--clave", CLAVE)
    bd = BaseDatos(aj.db_path)
    ana, luis = (RepoUsuarios(bd).por_nombre(n)["id"] for n in ("ana", "luis"))
    trabajos = RepoTrabajos(bd)
    for id_, dueno in (("t_ana", ana), ("t_luis", luis)):
        trabajos.crear(id_, dueno, "x.mp3", None, False)
        (aj.resultados_dir / id_).mkdir(parents=True)
        (aj.resultados_dir / id_ / "informe.md").write_text("secreto")

    assert cli(aj, "eliminar", "ana", confirmacion="otra cosa")[0] == 1          # sin confirmar no borra
    assert RepoUsuarios(bd).por_nombre("ana") is not None

    codigo, lineas = cli(aj, "eliminar", "ana", confirmacion="ana")
    assert codigo == 0 and "1 transcripciones" in lineas[0]
    assert RepoUsuarios(bd).por_nombre("ana") is None
    assert trabajos.obtener("t_ana") is None and not (aj.resultados_dir / "t_ana").exists()
    assert trabajos.obtener("t_luis") is not None and (aj.resultados_dir / "t_luis").exists()   # no toca a otros


# --------------------------------------------------------------- seguridad

def test_hash_de_clave():
    h = hash_clave(CLAVE)
    assert h.startswith("scrypt$") and CLAVE not in h
    assert h != hash_clave(CLAVE)                       # sal distinta cada vez
    assert verificar_clave(CLAVE, h)
    assert not verificar_clave("clave-de-prueba-2", h)
    assert not verificar_clave(CLAVE, None)             # usuario inexistente
    assert not verificar_clave(CLAVE, "basura")         # hash corrupto: falla sin romper


def test_limite_de_intentos_por_ventana(monkeypatch):
    import app.seguridad as seg
    reloj = [1000.0]
    monkeypatch.setattr(seg.time, "monotonic", lambda: reloj[0])
    limite = LimiteIntentos(maximo=3, ventana_s=60)
    for _ in range(3):
        limite.fallo("ana")
    assert limite.bloqueado("ana") and not limite.bloqueado("luis")
    reloj[0] += 61                                       # pasa la ventana
    assert not limite.bloqueado("ana")


def test_hash_de_token_es_estable_y_no_reversible():
    assert hash_token("abc") == hash_token("abc") != hash_token("abd")
    assert "abc" not in hash_token("abc")


# --------------------------------------------------------------- migración

def test_migra_contextos_de_la_primera_version(tmp_path):
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE contextos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL UNIQUE COLLATE NOCASE,
            datos TEXT NOT NULL, creado TEXT NOT NULL, actualizado TEXT NOT NULL);
        INSERT INTO contextos (nombre, datos, creado, actualizado)
            VALUES ('Observatorio', '{"nombre": "Observatorio"}', 't', 't');
    """)
    con.close()
    bd = BaseDatos(ruta)
    bd.inicializar()
    bd.inicializar()                                     # repetir no rompe nada
    with bd.conexion() as c:
        fila = c.execute("SELECT nombre, usuario_id FROM contextos").fetchone()
    assert (fila["nombre"], fila["usuario_id"]) == ("Observatorio", None)    # queda como institucional
