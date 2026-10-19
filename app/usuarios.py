"""Administración de usuarios desde la consola.

  python -m app.usuarios crear pablo --nombre "Pablo Ramírez" --admin
  python -m app.usuarios listar
  python -m app.usuarios clave pablo              # restablecer la contraseña
  python -m app.usuarios desactivar pablo         # bloquea el acceso sin borrar nada
  python -m app.usuarios activar pablo
  python -m app.usuarios admin pablo              # dar permisos de administrador (--quitar para retirarlos)
  python -m app.usuarios eliminar pablo           # borra el usuario y TODAS sus transcripciones

Con Docker:  docker compose exec web python -m app.usuarios crear pablo --admin
La contraseña se pide por teclado sin mostrarse. Úsala con --clave solo en scripts: queda en el historial.
"""
import argparse
import getpass
import shutil
import sys

from .config import Ajustes
from .db import BaseDatos
from .repos import RepoUsuarios, UsuarioDuplicado
from .seguridad import ClaveInvalida, MIN_LARGO_CLAVE


def _pedir_clave(clave: str | None, leer=getpass.getpass) -> str:
    if clave:
        return clave
    primera = leer(f"Contraseña (mínimo {MIN_LARGO_CLAVE} caracteres): ")
    if primera != leer("Repite la contraseña: "):
        raise SystemExit("Las contraseñas no coinciden.")
    return primera


def ejecutar(argv: list[str], ajustes: Ajustes | None = None, leer_clave=getpass.getpass,
             confirmar=input, salida=print) -> int:
    ajustes = ajustes or Ajustes.desde_entorno()
    bd = BaseDatos(ajustes.db_path)
    bd.inicializar()
    usuarios = RepoUsuarios(bd)

    parser = argparse.ArgumentParser(prog="python -m app.usuarios", description="Administrar usuarios")
    sub = parser.add_subparsers(dest="orden", required=True)
    crear = sub.add_parser("crear", help="Crear un usuario")
    crear.add_argument("usuario")
    crear.add_argument("--nombre", help="Nombre para mostrar (por defecto, el usuario)")
    crear.add_argument("--admin", action="store_true", help="Puede editar las plantillas institucionales")
    crear.add_argument("--clave", help="Contraseña (si se omite, se pide por teclado)")
    sub.add_parser("listar", help="Ver los usuarios")
    clave = sub.add_parser("clave", help="Restablecer la contraseña")
    clave.add_argument("usuario")
    clave.add_argument("--clave")
    for nombre, ayuda in (("activar", "Permitir el acceso"), ("desactivar", "Bloquear el acceso")):
        sub.add_parser(nombre, help=ayuda).add_argument("usuario")
    admin = sub.add_parser("admin", help="Dar o quitar permisos de administrador")
    admin.add_argument("usuario")
    admin.add_argument("--quitar", action="store_true")
    eliminar = sub.add_parser("eliminar", help="Borrar el usuario y todas sus transcripciones")
    eliminar.add_argument("usuario")
    eliminar.add_argument("--si", action="store_true", help="No pedir confirmación")
    args = parser.parse_args(argv)

    def no_existe() -> int:
        salida(f"No existe el usuario «{args.usuario}».")
        return 1

    if args.orden == "crear":
        try:
            nuevo = usuarios.crear(args.usuario, args.nombre or args.usuario,
                                   _pedir_clave(args.clave, leer_clave), args.admin)
        except UsuarioDuplicado:
            salida(f"Ya existe el usuario «{args.usuario}».")
            return 1
        except (ClaveInvalida, ValueError) as e:
            salida(str(e))
            return 1
        salida(f"Usuario «{nuevo['usuario']}» creado{' como administrador' if nuevo['es_admin'] else ''}.")
    elif args.orden == "listar":
        lista = usuarios.listar()
        if not lista:
            salida("No hay usuarios. Crea el primero con: python -m app.usuarios crear <usuario> --admin")
        for u in lista:
            marcas = ", ".join(m for m in ("administrador" if u["es_admin"] else "", "" if u["activo"] else "INACTIVO") if m)
            salida(f"{u['usuario']:<20} {u['nombre']:<28} {marcas}")
    elif args.orden == "clave":
        if usuarios.por_nombre(args.usuario) is None:
            return no_existe()
        try:
            usuarios.cambiar_clave(usuarios.por_nombre(args.usuario)["id"], _pedir_clave(args.clave, leer_clave))
        except ClaveInvalida as e:
            salida(str(e))
            return 1
        salida("Contraseña actualizada.")
    elif args.orden in ("activar", "desactivar"):
        if not usuarios.establecer_activo(args.usuario, args.orden == "activar"):
            return no_existe()
        salida(f"Usuario «{args.usuario}» {'activado' if args.orden == 'activar' else 'desactivado (sus sesiones se cerraron)'}.")
    elif args.orden == "admin":
        if not usuarios.establecer_admin(args.usuario, not args.quitar):
            return no_existe()
        salida(f"«{args.usuario}» {'ya no es' if args.quitar else 'ahora es'} administrador.")
    elif args.orden == "eliminar":
        if usuarios.por_nombre(args.usuario) is None:
            return no_existe()
        trabajos = usuarios.ids_de_trabajos(args.usuario)
        if not args.si:
            respuesta = confirmar(f"Se borrarán el usuario «{args.usuario}» y sus {len(trabajos)} transcripciones. "
                                  f"Escribe el nombre del usuario para confirmar: ")
            if respuesta.strip() != args.usuario:
                salida("Cancelado.")
                return 1
        usuarios.eliminar(args.usuario)
        for id_ in trabajos:
            shutil.rmtree(ajustes.subidas_dir / id_, ignore_errors=True)
            shutil.rmtree(ajustes.resultados_dir / id_, ignore_errors=True)
        salida(f"Usuario «{args.usuario}» eliminado ({len(trabajos)} transcripciones borradas).")
    return 0


if __name__ == "__main__":
    sys.exit(ejecutar(sys.argv[1:]))
