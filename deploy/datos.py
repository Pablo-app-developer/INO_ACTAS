"""Copia de seguridad y restauración de los datos de la aplicación (para respaldar o migrar de servidor).

  python deploy/datos.py respaldar              # crea copias/copia-datos-AAAA-MM-DD_HHMM.tar.gz
  python deploy/datos.py respaldar mi-copia.tar.gz
  python deploy/datos.py restaurar copias/copia-datos-2026-10-20_0900.tar.gz

«Datos» es todo lo que importa: la base de datos (usuarios, plantillas, historial) y los resultados
de cada transcripción. Funciona igual en Windows, Linux y macOS; solo necesita Docker.
Se detiene la aplicación mientras se copia (para que la base de datos quede consistente) y se vuelve a iniciar.
"""
import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARCHIVOS = ["-f", "docker-compose.yml"]


def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *ARCHIVOS, *args], cwd=RAIZ, check=check)


def en_el_volumen(comando: str, carpeta: Path, como_root: bool = False) -> None:
    """Ejecuta un comando dentro de la imagen de la app, con el volumen de datos y la carpeta de copias montados."""
    # Se usa el volumen que define el propio compose, así no hay que adivinar su nombre
    extra = ["--user", "root"] if como_root else []
    compose("run", "--rm", "--no-deps", "-v", f"{carpeta.as_posix()}:/copia", *extra,
            "--entrypoint", "sh", "web", "-c", comando)


def estaba_en_marcha() -> bool:
    salida = subprocess.run(["docker", "compose", *ARCHIVOS, "ps", "--status", "running", "-q", "web"],
                            cwd=RAIZ, capture_output=True, text=True)
    return bool(salida.stdout.strip())


def respaldar(destino: str | None) -> Path:
    if destino:
        ruta = Path(destino).resolve()
    else:
        ruta = (RAIZ / "copias" / f"copia-datos-{datetime.now():%Y-%m-%d_%H%M}.tar.gz").resolve()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    reiniciar = estaba_en_marcha()
    if reiniciar:
        compose("stop", "web")
    try:
        en_el_volumen(f"tar czf /copia/{ruta.name} -C /datos .", ruta.parent, como_root=True)
    finally:
        if reiniciar:
            compose("start", "web")
    print(f"Copia creada: {ruta}  ({ruta.stat().st_size / 1024 / 1024:.1f} MB)")
    return ruta


def restaurar(origen: str) -> None:
    ruta = Path(origen).resolve()
    if not ruta.is_file():
        sys.exit(f"No existe el archivo: {ruta}")
    print("Se REEMPLAZARÁN todos los datos actuales (usuarios, plantillas e historial) por los de la copia.")
    if input("Escribe «restaurar» para continuar: ").strip() != "restaurar":
        sys.exit("Cancelado.")
    reiniciar = estaba_en_marcha()
    compose("stop", "web", check=False)
    try:
        en_el_volumen(
            f"find /datos -mindepth 1 -delete && tar xzf /copia/{ruta.name} -C /datos && chown -R 10001 /datos",
            ruta.parent, como_root=True)
    finally:
        compose("up", "-d", "web") if reiniciar else None
    print("Datos restaurados." + ("" if reiniciar else " Inicia la aplicación con: docker compose up -d"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Respaldar o restaurar los datos de la aplicación")
    sub = parser.add_subparsers(dest="orden", required=True)
    sub.add_parser("respaldar", help="Crear una copia de seguridad").add_argument("destino", nargs="?")
    sub.add_parser("restaurar", help="Restaurar una copia").add_argument("origen")
    args = parser.parse_args()
    respaldar(args.destino) if args.orden == "respaldar" else restaurar(args.origen)
