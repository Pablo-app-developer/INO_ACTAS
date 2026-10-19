"""SQLite: una conexión por operación (seguro entre hilos) y creación/migración del esquema."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario     TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- nombre de acceso
    nombre      TEXT NOT NULL,                         -- nombre para mostrar
    clave_hash  TEXT NOT NULL,
    es_admin    INTEGER NOT NULL DEFAULT 0,
    activo      INTEGER NOT NULL DEFAULT 1,
    creado      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sesiones (
    token_hash  TEXT PRIMARY KEY,                      -- SHA-256 del token de la cookie
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    creada      TEXT NOT NULL,
    expira      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contextos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,  -- NULL = plantilla institucional
    nombre      TEXT NOT NULL COLLATE NOCASE,
    datos       TEXT NOT NULL,            -- JSON de motor.contexto.Contexto
    creado      TEXT NOT NULL,
    actualizado TEXT NOT NULL
);
-- El nombre es único dentro de cada ámbito: las institucionales, y las de cada usuario
CREATE UNIQUE INDEX IF NOT EXISTS idx_contextos_nombre ON contextos(COALESCE(usuario_id, 0), nombre);

CREATE TABLE IF NOT EXISTS trabajos (
    id            TEXT PRIMARY KEY,
    usuario_id    INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    estado        TEXT NOT NULL,          -- en_cola | procesando | completado | error
    archivo       TEXT NOT NULL,          -- nombre original que subió el usuario
    contexto      TEXT,                   -- copia (JSON) del contexto usado; NULL = sin contexto
    sin_analisis  INTEGER NOT NULL DEFAULT 0,
    acta_generar  INTEGER NOT NULL DEFAULT 0,
    acta_numero   TEXT,
    acta_fecha    TEXT,                   -- AAAA-MM-DD
    acta_hora     TEXT,
    etapa         TEXT,
    mensaje       TEXT,
    progreso      REAL NOT NULL DEFAULT 0,
    error         TEXT,
    advertencias  TEXT NOT NULL DEFAULT '[]',
    carpeta       TEXT,                   -- subcarpeta dentro de resultados/<id>
    duracion      REAL,
    creado        TEXT NOT NULL,
    iniciado      TEXT,
    terminado     TEXT
);
CREATE INDEX IF NOT EXISTS idx_trabajos_creado ON trabajos(creado DESC);
"""

# Columnas añadidas después de la primera versión: se agregan a bases de datos ya creadas
COLUMNAS_NUEVAS_TRABAJOS = {
    "usuario_id": "INTEGER REFERENCES usuarios(id) ON DELETE CASCADE",
    "acta_generar": "INTEGER NOT NULL DEFAULT 0",
    "acta_numero": "TEXT",
    "acta_fecha": "TEXT",
    "acta_hora": "TEXT",
}


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _columnas(con: sqlite3.Connection, tabla: str) -> set[str]:
    return {fila["name"] for fila in con.execute(f"PRAGMA table_info({tabla})")}


class BaseDatos:
    def __init__(self, ruta: Path):
        self.ruta = ruta

    @contextmanager
    def conexion(self):
        con = sqlite3.connect(self.ruta, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def inicializar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with self.conexion() as con:
            con.execute("PRAGMA foreign_keys=OFF")     # durante la migración, la tabla nueva aún no tiene a quién apuntar
            self._migrar_contextos(con)
            con.executescript(ESQUEMA)
            con.execute("PRAGMA foreign_keys=ON")
            existentes = _columnas(con, "trabajos")
            for nombre, definicion in COLUMNAS_NUEVAS_TRABAJOS.items():
                if nombre not in existentes:
                    con.execute(f"ALTER TABLE trabajos ADD COLUMN {nombre} {definicion}")

    @staticmethod
    def _migrar_contextos(con: sqlite3.Connection) -> None:
        """La primera versión tenía el nombre único a nivel global y sin propietario."""
        columnas = _columnas(con, "contextos")
        if not columnas or "usuario_id" in columnas:
            return
        con.executescript("""
            ALTER TABLE contextos RENAME TO contextos_anterior;
            CREATE TABLE contextos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                nombre TEXT NOT NULL COLLATE NOCASE,
                datos TEXT NOT NULL, creado TEXT NOT NULL, actualizado TEXT NOT NULL);
            INSERT INTO contextos (id, nombre, datos, creado, actualizado)
                SELECT id, nombre, datos, creado, actualizado FROM contextos_anterior;
            DROP TABLE contextos_anterior;
        """)
