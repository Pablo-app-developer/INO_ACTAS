"""Contraseñas, tokens de sesión y límite de intentos de acceso (solo biblioteca estándar)."""
import base64
import hashlib
import hmac
import secrets
import threading
import time

# scrypt: costo recomendado por OWASP para contraseñas interactivas (N=2^14, r=8, p=1)
_N, _R, _P = 2**14, 8, 1
MIN_LARGO_CLAVE = 10


class ClaveInvalida(ValueError):
    """La contraseña no cumple los requisitos."""


def validar_clave(clave: str) -> None:
    if len(clave) < MIN_LARGO_CLAVE:
        raise ClaveInvalida(f"La contraseña debe tener al menos {MIN_LARGO_CLAVE} caracteres.")


def _derivar(clave: str, sal: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(clave.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=32,
                          maxmem=128 * n * r * 2)


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    derivado = _derivar(clave, sal, _N, _R, _P)
    b64 = lambda b: base64.b64encode(b).decode("ascii")
    return f"scrypt${_N}${_R}${_P}${b64(sal)}${b64(derivado)}"


# Se compara contra este hash cuando el usuario no existe, para que tardar lo mismo
# no revele qué usuarios están creados.
_HASH_FALSO = hash_clave(secrets.token_urlsafe(16))


def verificar_clave(clave: str, guardado: str | None) -> bool:
    try:
        _, n, r, p, sal, esperado = (guardado or _HASH_FALSO).split("$")
        derivado = _derivar(clave, base64.b64decode(sal), int(n), int(r), int(p))
        coincide = hmac.compare_digest(derivado, base64.b64decode(esperado))
    except (ValueError, TypeError):
        return False
    return coincide and guardado is not None


def nuevo_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """En la base de datos solo se guarda el hash: si se filtra, las sesiones no sirven."""
    return hashlib.sha256(token.encode("ascii", "ignore")).hexdigest()


class LimiteIntentos:
    """Bloquea temporalmente un usuario tras varios intentos fallidos (en memoria, un proceso)."""

    def __init__(self, maximo: int = 5, ventana_s: int = 600):
        self.maximo, self.ventana_s = maximo, ventana_s
        self._fallos: dict[str, list[float]] = {}
        self._cerrojo = threading.Lock()

    def _recientes(self, clave: str, ahora: float) -> list[float]:
        recientes = [t for t in self._fallos.get(clave, []) if ahora - t < self.ventana_s]
        if recientes:
            self._fallos[clave] = recientes
        else:
            self._fallos.pop(clave, None)
        return recientes

    def bloqueado(self, clave: str) -> bool:
        with self._cerrojo:
            return len(self._recientes(clave, time.monotonic())) >= self.maximo

    def fallo(self, clave: str) -> None:
        with self._cerrojo:
            ahora = time.monotonic()
            self._recientes(clave, ahora)
            self._fallos.setdefault(clave, []).append(ahora)

    def exito(self, clave: str) -> None:
        with self._cerrojo:
            self._fallos.pop(clave, None)
