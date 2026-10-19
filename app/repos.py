"""Acceso a datos: usuarios, sesiones, plantillas de contexto y trabajos de transcripción."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from motor.acta import DatosActa
from motor.contexto import Contexto

from .db import BaseDatos, ahora
from .seguridad import hash_clave, hash_token, validar_clave


class NombreDuplicado(Exception):
    """Ya existe un contexto con ese nombre."""


class UsuarioDuplicado(Exception):
    """Ya existe un usuario con ese nombre de acceso."""


class SinPermiso(Exception):
    """El usuario ve el recurso pero no puede modificarlo."""


# ------------------------------------------------------------------ usuarios

def _usuario(fila: sqlite3.Row) -> dict:
    """Datos públicos del usuario (nunca incluye el hash de la contraseña)."""
    return {"id": fila["id"], "usuario": fila["usuario"], "nombre": fila["nombre"],
            "es_admin": bool(fila["es_admin"]), "activo": bool(fila["activo"]), "creado": fila["creado"]}


class RepoUsuarios:
    def __init__(self, bd: BaseDatos):
        self.bd = bd

    def crear(self, usuario: str, nombre: str, clave: str, es_admin: bool = False) -> dict:
        usuario, nombre = usuario.strip(), nombre.strip()
        if not usuario or not nombre:
            raise ValueError("El usuario y el nombre no pueden estar vacíos.")
        validar_clave(clave)
        try:
            with self.bd.conexion() as con:
                id_ = con.execute(
                    "INSERT INTO usuarios (usuario, nombre, clave_hash, es_admin, creado) VALUES (?, ?, ?, ?, ?)",
                    (usuario, nombre, hash_clave(clave), int(es_admin), ahora())).lastrowid
        except sqlite3.IntegrityError as e:
            raise UsuarioDuplicado(usuario) from e
        return self.obtener(id_)      # fuera del with: la transacción ya se confirmó

    def obtener(self, id_: int) -> dict | None:
        with self.bd.conexion() as con:
            fila = con.execute("SELECT * FROM usuarios WHERE id = ?", (id_,)).fetchone()
        return _usuario(fila) if fila else None

    def por_nombre(self, usuario: str) -> dict | None:
        with self.bd.conexion() as con:
            fila = con.execute("SELECT * FROM usuarios WHERE usuario = ?", (usuario.strip(),)).fetchone()
        return _usuario(fila) if fila else None

    def hash_de(self, usuario: str) -> str | None:
        """Hash guardado para verificar el acceso, o None si el usuario no existe o está inactivo."""
        with self.bd.conexion() as con:
            fila = con.execute("SELECT clave_hash, activo FROM usuarios WHERE usuario = ?",
                               (usuario.strip(),)).fetchone()
        return fila["clave_hash"] if fila and fila["activo"] else None

    def hash_por_id(self, id_: int) -> str | None:
        with self.bd.conexion() as con:
            fila = con.execute("SELECT clave_hash FROM usuarios WHERE id = ?", (id_,)).fetchone()
        return fila["clave_hash"] if fila else None

    def listar(self) -> list[dict]:
        with self.bd.conexion() as con:
            return [_usuario(f) for f in con.execute("SELECT * FROM usuarios ORDER BY usuario")]

    def cambiar_clave(self, id_: int, clave: str) -> None:
        validar_clave(clave)
        with self.bd.conexion() as con:
            con.execute("UPDATE usuarios SET clave_hash = ? WHERE id = ?", (hash_clave(clave), id_))

    def establecer_activo(self, usuario: str, activo: bool) -> bool:
        with self.bd.conexion() as con:
            cur = con.execute("UPDATE usuarios SET activo = ? WHERE usuario = ?", (int(activo), usuario.strip()))
            if cur.rowcount and not activo:       # al desactivar, se cierran sus sesiones
                con.execute("DELETE FROM sesiones WHERE usuario_id = "
                            "(SELECT id FROM usuarios WHERE usuario = ?)", (usuario.strip(),))
            return cur.rowcount > 0

    def establecer_admin(self, usuario: str, es_admin: bool) -> bool:
        with self.bd.conexion() as con:
            return con.execute("UPDATE usuarios SET es_admin = ? WHERE usuario = ?",
                               (int(es_admin), usuario.strip())).rowcount > 0

    def eliminar(self, usuario: str) -> bool:
        """Borra el usuario y, en cascada, sus sesiones, plantillas y trabajos (los archivos en
        disco los limpia quien llama: ver `ids_de_trabajos`)."""
        with self.bd.conexion() as con:
            return con.execute("DELETE FROM usuarios WHERE usuario = ?", (usuario.strip(),)).rowcount > 0

    def ids_de_trabajos(self, usuario: str) -> list[str]:
        with self.bd.conexion() as con:
            filas = con.execute("SELECT t.id FROM trabajos t JOIN usuarios u ON u.id = t.usuario_id "
                                "WHERE u.usuario = ?", (usuario.strip(),)).fetchall()
        return [f["id"] for f in filas]


# ------------------------------------------------------------------ sesiones

class RepoSesiones:
    def __init__(self, bd: BaseDatos, duracion_horas: float = 12):
        self.bd = bd
        self.duracion = timedelta(hours=duracion_horas)

    def crear(self, usuario_id: int, token: str) -> None:
        ahora_utc = datetime.now(timezone.utc)
        with self.bd.conexion() as con:
            con.execute("DELETE FROM sesiones WHERE expira < ?", (ahora_utc.isoformat(timespec="seconds"),))
            con.execute("INSERT INTO sesiones (token_hash, usuario_id, creada, expira) VALUES (?, ?, ?, ?)",
                        (hash_token(token), usuario_id, ahora_utc.isoformat(timespec="seconds"),
                         (ahora_utc + self.duracion).isoformat(timespec="seconds")))

    def usuario_de(self, token: str) -> dict | None:
        """El usuario dueño de la sesión, si el token es válido, no ha vencido y el usuario sigue activo."""
        with self.bd.conexion() as con:
            fila = con.execute(
                "SELECT u.* FROM sesiones s JOIN usuarios u ON u.id = s.usuario_id "
                "WHERE s.token_hash = ? AND s.expira > ? AND u.activo = 1",
                (hash_token(token), datetime.now(timezone.utc).isoformat(timespec="seconds"))).fetchone()
        return _usuario(fila) if fila else None

    def cerrar(self, token: str) -> None:
        with self.bd.conexion() as con:
            con.execute("DELETE FROM sesiones WHERE token_hash = ?", (hash_token(token),))

    def cerrar_otras(self, usuario_id: int, conservar_token: str) -> None:
        """Tras cambiar la contraseña se cierran las demás sesiones de esa persona."""
        with self.bd.conexion() as con:
            con.execute("DELETE FROM sesiones WHERE usuario_id = ? AND token_hash != ?",
                        (usuario_id, hash_token(conservar_token)))


# ----------------------------------------------------------------- contextos

def _fila_contexto(fila: sqlite3.Row, usuario: dict) -> dict:
    institucional = fila["usuario_id"] is None
    return {
        "id": fila["id"],
        "creado": fila["creado"],
        "actualizado": fila["actualizado"],
        "ambito": "institucional" if institucional else "personal",
        # Las institucionales las edita solo un administrador; las personales, su dueño
        "editable": usuario["es_admin"] if institucional else fila["usuario_id"] == usuario["id"],
        **json.loads(fila["datos"]),
    }


class RepoContextos:
    def __init__(self, bd: BaseDatos):
        self.bd = bd

    def _visible(self, con, id_: int, usuario: dict) -> sqlite3.Row | None:
        return con.execute("SELECT * FROM contextos WHERE id = ? AND (usuario_id IS NULL OR usuario_id = ?)",
                           (id_, usuario["id"])).fetchone()

    def listar(self, usuario: dict) -> list[dict]:
        with self.bd.conexion() as con:
            filas = con.execute(
                "SELECT * FROM contextos WHERE usuario_id IS NULL OR usuario_id = ? "
                "ORDER BY usuario_id IS NOT NULL, nombre", (usuario["id"],)).fetchall()
        return [_fila_contexto(f, usuario) for f in filas]

    def obtener(self, id_: int, usuario: dict) -> dict | None:
        with self.bd.conexion() as con:
            fila = self._visible(con, id_, usuario)
        return _fila_contexto(fila, usuario) if fila else None

    def crear(self, contexto: Contexto, usuario: dict, institucional: bool = False) -> dict:
        if institucional and not usuario["es_admin"]:
            raise SinPermiso("Solo un administrador puede crear plantillas institucionales.")
        t = ahora()
        try:
            with self.bd.conexion() as con:
                cur = con.execute(
                    "INSERT INTO contextos (usuario_id, nombre, datos, creado, actualizado) VALUES (?, ?, ?, ?, ?)",
                    (None if institucional else usuario["id"], contexto.nombre, contexto.model_dump_json(), t, t))
                id_ = cur.lastrowid
        except sqlite3.IntegrityError as e:
            raise NombreDuplicado(contexto.nombre) from e
        return self.obtener(id_, usuario)

    def actualizar(self, id_: int, contexto: Contexto, usuario: dict) -> dict | None:
        try:
            with self.bd.conexion() as con:
                fila = self._visible(con, id_, usuario)
                if fila is None:
                    return None
                if not _fila_contexto(fila, usuario)["editable"]:
                    raise SinPermiso("No tienes permiso para modificar esta plantilla.")
                con.execute("UPDATE contextos SET nombre = ?, datos = ?, actualizado = ? WHERE id = ?",
                            (contexto.nombre, contexto.model_dump_json(), ahora(), id_))
        except sqlite3.IntegrityError as e:
            raise NombreDuplicado(contexto.nombre) from e
        return self.obtener(id_, usuario)

    def eliminar(self, id_: int, usuario: dict) -> bool:
        with self.bd.conexion() as con:
            fila = self._visible(con, id_, usuario)
            if fila is None:
                return False
            if not _fila_contexto(fila, usuario)["editable"]:
                raise SinPermiso("No tienes permiso para eliminar esta plantilla.")
            con.execute("DELETE FROM contextos WHERE id = ?", (id_,))
        return True

    def sembrar_si_vacio(self, ruta_json: Path) -> int:
        """Carga las plantillas institucionales iniciales la primera vez. Devuelve cuántas insertó."""
        with self.bd.conexion() as con:
            if con.execute("SELECT COUNT(*) FROM contextos").fetchone()[0] > 0:
                return 0
        if not ruta_json.exists():
            return 0
        plantillas = json.loads(ruta_json.read_text(encoding="utf-8"))
        t = ahora()
        with self.bd.conexion() as con:
            for datos in plantillas:
                contexto = Contexto.model_validate(datos)
                con.execute("INSERT INTO contextos (usuario_id, nombre, datos, creado, actualizado) "
                            "VALUES (NULL, ?, ?, ?, ?)", (contexto.nombre, contexto.model_dump_json(), t, t))
        return len(plantillas)


# ------------------------------------------------------------------- trabajos

def _fila_trabajo(fila: sqlite3.Row) -> dict:
    d = dict(fila)
    d["sin_analisis"] = bool(d["sin_analisis"])
    d["advertencias"] = json.loads(d["advertencias"])
    d["contexto"] = json.loads(d["contexto"]) if d["contexto"] else None
    d["acta"] = ({"numero": d["acta_numero"] or "", "fecha": d["acta_fecha"], "hora": d["acta_hora"] or ""}
                 if d.pop("acta_generar") else None)
    for columna in ("acta_numero", "acta_fecha", "acta_hora"):
        d.pop(columna)
    return d


class RepoTrabajos:
    def __init__(self, bd: BaseDatos):
        self.bd = bd

    def crear(self, id_: str, usuario_id: int, archivo: str, contexto: Contexto | None,
              sin_analisis: bool, acta: DatosActa | None = None) -> dict:
        with self.bd.conexion() as con:
            con.execute(
                "INSERT INTO trabajos (id, usuario_id, estado, archivo, contexto, sin_analisis, acta_generar, "
                "acta_numero, acta_fecha, acta_hora, mensaje, creado) "
                "VALUES (?, ?, 'en_cola', ?, ?, ?, ?, ?, ?, ?, 'En cola', ?)",
                (id_, usuario_id, archivo, contexto.model_dump_json() if contexto else None, int(sin_analisis),
                 int(acta is not None), acta.numero if acta else None,
                 acta.fecha.isoformat() if acta else None, acta.hora if acta else None, ahora()),
            )
        return self.obtener(id_)

    def obtener(self, id_: str) -> dict | None:
        """Uso interno (la cola de procesamiento). Las rutas de la API usan `obtener_de`."""
        with self.bd.conexion() as con:
            fila = con.execute("SELECT * FROM trabajos WHERE id = ?", (id_,)).fetchone()
        return _fila_trabajo(fila) if fila else None

    def obtener_de(self, id_: str, usuario_id: int) -> dict | None:
        """El trabajo solo si pertenece a ese usuario; si es de otro, se comporta como si no existiera."""
        trabajo = self.obtener(id_)
        return trabajo if trabajo and trabajo["usuario_id"] == usuario_id else None

    def listar(self, usuario_id: int, limite: int = 50) -> list[dict]:
        with self.bd.conexion() as con:
            filas = con.execute(
                "SELECT * FROM trabajos WHERE usuario_id = ? ORDER BY creado DESC, rowid DESC LIMIT ?",
                (usuario_id, limite)).fetchall()
        return [_fila_trabajo(f) for f in filas]

    def en_cola(self) -> list[str]:
        with self.bd.conexion() as con:
            filas = con.execute(
                "SELECT id FROM trabajos WHERE estado = 'en_cola' ORDER BY creado, rowid"
            ).fetchall()
        return [f["id"] for f in filas]

    def marcar_procesando(self, id_: str) -> None:
        with self.bd.conexion() as con:
            con.execute(
                "UPDATE trabajos SET estado = 'procesando', iniciado = ?, mensaje = 'Iniciando', "
                "progreso = 0, error = NULL WHERE id = ?", (ahora(), id_))

    def actualizar_progreso(self, id_: str, etapa: str, mensaje: str, progreso: float) -> None:
        with self.bd.conexion() as con:
            con.execute("UPDATE trabajos SET etapa = ?, mensaje = ?, progreso = ? WHERE id = ?",
                        (etapa, mensaje, round(progreso, 3), id_))

    def marcar_completado(self, id_: str, carpeta: str, duracion: float, advertencias: list[str]) -> None:
        with self.bd.conexion() as con:
            con.execute(
                "UPDATE trabajos SET estado = 'completado', carpeta = ?, duracion = ?, advertencias = ?, "
                "progreso = 1, mensaje = 'Listo', terminado = ? WHERE id = ?",
                (carpeta, duracion, json.dumps(advertencias, ensure_ascii=False), ahora(), id_))

    def marcar_error(self, id_: str, error: str) -> None:
        with self.bd.conexion() as con:
            con.execute(
                "UPDATE trabajos SET estado = 'error', error = ?, mensaje = 'Falló', terminado = ? "
                "WHERE id = ?", (error, ahora(), id_))

    def reencolar_interrumpidos(self) -> list[str]:
        """Trabajos que quedaron 'procesando' porque el servidor se reinició."""
        with self.bd.conexion() as con:
            filas = con.execute("SELECT id FROM trabajos WHERE estado = 'procesando'").fetchall()
            con.execute("UPDATE trabajos SET estado = 'en_cola', mensaje = 'En cola (reintento)', "
                        "progreso = 0 WHERE estado = 'procesando'")
        return [f["id"] for f in filas]

    def eliminar(self, id_: str) -> bool:
        with self.bd.conexion() as con:
            return con.execute("DELETE FROM trabajos WHERE id = ?", (id_,)).rowcount > 0
