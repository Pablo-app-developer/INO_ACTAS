"""API del transcriptor de reuniones.

Ejecutar:                python -m app      (puerto 8001; HOST y PORT se pueden cambiar)
Desarrollo con recarga:  uvicorn app.main:app --port 8001 --reload
Interfaz: http://localhost:8001/   Documentación de la API: http://localhost:8001/docs

Los usuarios se crean desde la consola:  python -m app.usuarios crear <usuario>
"""
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from motor import EXTENSIONES_AUDIO, DatosActa, procesar_audio
from motor.contexto import Contexto

from .cola import Cola
from .config import ARCHIVOS_DESCARGABLES, ESTATICOS, PLANTILLAS_INICIALES, Ajustes
from .db import BaseDatos
from .esquemas import ContextoOut, TrabajoOut, UsuarioOut
from .repos import (
    NombreDuplicado, RepoContextos, RepoSesiones, RepoTrabajos, RepoUsuarios, SinPermiso,
)
from .seguridad import ClaveInvalida, LimiteIntentos, nuevo_token, validar_clave, verificar_clave

log = logging.getLogger("transcriptor")

TAM_BLOQUE = 1024 * 1024  # 1 MB
COOKIE_SESION = "sesion"
MENSAJE_LOGIN = "Usuario o contraseña incorrectos."


class Credenciales(BaseModel):
    usuario: str
    clave: str


class CambioClave(BaseModel):
    actual: str
    nueva: str


def create_app(ajustes: Ajustes | None = None, procesar: Callable = procesar_audio,
               iniciar_cola: bool = True) -> FastAPI:
    ajustes = ajustes or Ajustes.desde_entorno()
    bd = BaseDatos(ajustes.db_path)
    usuarios = RepoUsuarios(bd)
    sesiones = RepoSesiones(bd, ajustes.sesion_horas)
    contextos = RepoContextos(bd)
    trabajos = RepoTrabajos(bd)
    cola = Cola(ajustes, trabajos, procesar)
    intentos = LimiteIntentos()

    @asynccontextmanager
    async def ciclo_de_vida(_: FastAPI):
        ajustes.subidas_dir.mkdir(parents=True, exist_ok=True)
        ajustes.resultados_dir.mkdir(parents=True, exist_ok=True)
        bd.inicializar()
        sembradas = contextos.sembrar_si_vacio(PLANTILLAS_INICIALES)
        if sembradas:
            log.info("Se cargaron %d plantillas de contexto iniciales", sembradas)
        if not usuarios.listar():
            log.warning("No hay usuarios. Crea el primero con: python -m app.usuarios crear <usuario> --admin")
        if iniciar_cola:
            cola.iniciar()
        yield
        if iniciar_cola:
            cola.detener()

    # ----------------------------------------------------------- seguridad
    def mismo_origen(request: Request) -> None:
        """Defensa contra CSRF: un POST/PUT/DELETE desde otra web trae un Origin distinto al nuestro."""
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origen = request.headers.get("origin")
            if origen and urlparse(origen).netloc != request.headers.get("host"):
                raise HTTPException(403, "Origen no permitido.")

    def usuario_opcional(request: Request) -> dict | None:
        token = request.cookies.get(COOKIE_SESION)
        return sesiones.usuario_de(token) if token else None

    def usuario_actual(usuario: dict | None = Depends(usuario_opcional)) -> dict:
        if usuario is None:
            raise HTTPException(401, "Inicia sesión para continuar.")
        return usuario

    app = FastAPI(title="Transcriptor de Reuniones — INO", version="0.2.0", lifespan=ciclo_de_vida,
                  dependencies=[Depends(mismo_origen)])

    def _con_archivos(trabajo: dict) -> dict:
        archivos = []
        if trabajo["estado"] == "completado" and trabajo["carpeta"]:
            carpeta = ajustes.resultados_dir / trabajo["id"] / trabajo["carpeta"]
            archivos = [n for n in ARCHIVOS_DESCARGABLES if (carpeta / n).exists()]
        return {**trabajo, "archivos": archivos}

    def _trabajo_o_404(id_: str, usuario: dict) -> dict:
        # Un trabajo ajeno responde igual que uno inexistente: no se revela que existe
        trabajo = trabajos.obtener_de(id_, usuario["id"])
        if trabajo is None:
            raise HTTPException(404, "Trabajo no encontrado.")
        return trabajo

    # ------------------------------------------------------------------ salud
    @app.get("/api/salud")
    def salud() -> dict:
        return {"estado": "ok"}

    # ---------------------------------------------------------------- sesión
    @app.post("/api/login", response_model=UsuarioOut)
    def iniciar_sesion(datos: Credenciales, response: Response):
        clave_limite = datos.usuario.strip().lower()
        if intentos.bloqueado(clave_limite):
            raise HTTPException(429, "Demasiados intentos fallidos. Espera unos minutos e inténtalo de nuevo.")
        guardado = usuarios.hash_de(datos.usuario)
        # Se verifica siempre (aunque el usuario no exista) para no revelar qué usuarios hay
        if not verificar_clave(datos.clave, guardado):
            intentos.fallo(clave_limite)
            raise HTTPException(401, MENSAJE_LOGIN)
        intentos.exito(clave_limite)
        usuario = usuarios.por_nombre(datos.usuario)
        token = nuevo_token()
        sesiones.crear(usuario["id"], token)
        response.set_cookie(COOKIE_SESION, token, max_age=int(ajustes.sesion_horas * 3600), httponly=True,
                            samesite="lax", secure=ajustes.cookie_segura, path="/")
        return usuario

    @app.post("/api/logout", status_code=204)
    def cerrar_sesion(request: Request, response: Response):
        token = request.cookies.get(COOKIE_SESION)
        if token:
            sesiones.cerrar(token)
        response.delete_cookie(COOKIE_SESION, path="/")

    @app.get("/api/yo", response_model=UsuarioOut)
    def quien_soy(usuario: dict = Depends(usuario_actual)):
        return usuario

    @app.post("/api/cuenta/clave", status_code=204)
    def cambiar_clave(datos: CambioClave, request: Request, usuario: dict = Depends(usuario_actual)):
        if not verificar_clave(datos.actual, usuarios.hash_por_id(usuario["id"])):
            raise HTTPException(403, "La contraseña actual no es correcta.")
        try:
            validar_clave(datos.nueva)
        except ClaveInvalida as e:
            raise HTTPException(422, str(e))
        usuarios.cambiar_clave(usuario["id"], datos.nueva)
        sesiones.cerrar_otras(usuario["id"], request.cookies[COOKIE_SESION])

    @app.get("/api/config")
    def configuracion(_: dict = Depends(usuario_actual)) -> dict:
        """Datos que la interfaz necesita conocer del servidor."""
        return {
            "formatos": sorted(EXTENSIONES_AUDIO),
            "max_subida_mb": ajustes.max_subida_bytes // (1024 * 1024),
            "conservar_audio": ajustes.conservar_audio,
        }

    # -------------------------------------------------------------- contextos
    @app.get("/api/contextos", response_model=list[ContextoOut])
    def listar_contextos(usuario: dict = Depends(usuario_actual)):
        return contextos.listar(usuario)

    @app.post("/api/contextos", response_model=ContextoOut, status_code=201)
    def crear_contexto(contexto: Contexto, institucional: bool = False, usuario: dict = Depends(usuario_actual)):
        try:
            return contextos.crear(contexto, usuario, institucional)
        except NombreDuplicado:
            raise HTTPException(409, f"Ya existe un contexto llamado '{contexto.nombre}'.")
        except SinPermiso as e:
            raise HTTPException(403, str(e))

    @app.get("/api/contextos/{id_}", response_model=ContextoOut)
    def obtener_contexto(id_: int, usuario: dict = Depends(usuario_actual)):
        contexto = contextos.obtener(id_, usuario)
        if contexto is None:
            raise HTTPException(404, "Contexto no encontrado.")
        return contexto

    @app.put("/api/contextos/{id_}", response_model=ContextoOut)
    def actualizar_contexto(id_: int, contexto: Contexto, usuario: dict = Depends(usuario_actual)):
        try:
            actualizado = contextos.actualizar(id_, contexto, usuario)
        except NombreDuplicado:
            raise HTTPException(409, f"Ya existe un contexto llamado '{contexto.nombre}'.")
        except SinPermiso as e:
            raise HTTPException(403, str(e))
        if actualizado is None:
            raise HTTPException(404, "Contexto no encontrado.")
        return actualizado

    @app.delete("/api/contextos/{id_}", status_code=204)
    def eliminar_contexto(id_: int, usuario: dict = Depends(usuario_actual)):
        try:
            existia = contextos.eliminar(id_, usuario)
        except SinPermiso as e:
            raise HTTPException(403, str(e))
        if not existia:
            raise HTTPException(404, "Contexto no encontrado.")

    # --------------------------------------------------------------- trabajos
    @app.post("/api/trabajos", response_model=TrabajoOut, status_code=202)
    async def crear_trabajo(
        request: Request,
        usuario: dict = Depends(usuario_actual),
        archivo: UploadFile = File(..., description="Audio o video de la reunión"),
        contexto_id: int | None = Form(None, description="ID de una plantilla guardada"),
        contexto: str | None = Form(None, description="Contexto completo en JSON (editado para esta reunión)"),
        sin_contexto: bool = Form(False, description="Transcribir sin contexto (menor precisión)"),
        sin_analisis: bool = Form(False, description="Solo transcribir, sin generar el informe"),
        generar_acta: bool = Form(False, description="Redactar además el acta en Word (formato del INO)"),
        acta_numero: str = Form("", description="Número del acta, p. ej. 030"),
        acta_fecha: str | None = Form(None, description="Fecha de la reunión, AAAA-MM-DD (obligatoria con acta)"),
        acta_hora: str = Form("", description="Hora de inicio, p. ej. 8:30 a. m. (opcional)"),
    ):
        # Validar todo lo barato antes de aceptar gigas de datos
        indicadas = (contexto_id is not None) + (contexto is not None) + sin_contexto
        if indicadas != 1:
            raise HTTPException(422, "Indica exactamente una opción de contexto: "
                                     "contexto_id, contexto o sin_contexto.")

        datos_acta: DatosActa | None = None
        if generar_acta:
            if sin_analisis:
                raise HTTPException(422, "El acta necesita el análisis: desmarca «solo transcribir».")
            try:
                datos_acta = DatosActa(numero=acta_numero, fecha=date.fromisoformat(acta_fecha or ""),
                                       hora=acta_hora)
            except ValueError:
                raise HTTPException(422, "Indica la fecha de la reunión para el acta (AAAA-MM-DD).")

        ctx: Contexto | None = None
        if contexto_id is not None:
            guardado = contextos.obtener(contexto_id, usuario)
            if guardado is None:
                raise HTTPException(404, "Contexto no encontrado.")
            ctx = Contexto.model_validate(guardado)
        elif contexto is not None:
            try:
                ctx = Contexto.model_validate_json(contexto)
            except ValidationError as e:
                raise HTTPException(422, f"El contexto no es válido: {e.errors()[0]['msg']}")

        nombre = Path(archivo.filename or "").name
        extension = Path(nombre).suffix.lower()
        if extension not in EXTENSIONES_AUDIO:
            permitidas = ", ".join(sorted(EXTENSIONES_AUDIO))
            raise HTTPException(415, f"Formato no admitido ({extension or 'sin extensión'}). "
                                     f"Formatos válidos: {permitidas}")

        declarado = request.headers.get("content-length")
        if declarado and declarado.isdigit() and int(declarado) > ajustes.max_subida_bytes + TAM_BLOQUE:
            raise HTTPException(413, _mensaje_limite(ajustes))

        id_ = uuid.uuid4().hex
        carpeta = ajustes.subidas_dir / id_
        carpeta.mkdir(parents=True)
        destino = carpeta / f"original{extension}"
        total = 0
        try:
            with open(destino, "wb") as f:
                while bloque := await archivo.read(TAM_BLOQUE):
                    total += len(bloque)
                    if total > ajustes.max_subida_bytes:
                        raise HTTPException(413, _mensaje_limite(ajustes))
                    f.write(bloque)
            if total == 0:
                raise HTTPException(422, "El archivo está vacío.")
            trabajo = trabajos.crear(id_, usuario["id"], nombre, ctx, sin_analisis, datos_acta)
        except BaseException:
            shutil.rmtree(carpeta, ignore_errors=True)
            raise
        cola.encolar(id_)
        return _con_archivos(trabajo)

    @app.get("/api/trabajos", response_model=list[TrabajoOut])
    def listar_trabajos(limite: int = 50, usuario: dict = Depends(usuario_actual)):
        return [_con_archivos(t) for t in trabajos.listar(usuario["id"], min(max(limite, 1), 200))]

    @app.get("/api/trabajos/{id_}", response_model=TrabajoOut)
    def obtener_trabajo(id_: str, usuario: dict = Depends(usuario_actual)):
        return _con_archivos(_trabajo_o_404(id_, usuario))

    @app.get("/api/trabajos/{id_}/archivos/{nombre}")
    def descargar(id_: str, nombre: str, usuario: dict = Depends(usuario_actual)):
        trabajo = _trabajo_o_404(id_, usuario)
        if nombre not in ARCHIVOS_DESCARGABLES or trabajo["estado"] != "completado":
            raise HTTPException(404, "Archivo no disponible.")
        ruta = ajustes.resultados_dir / id_ / trabajo["carpeta"] / nombre
        if not ruta.exists():
            raise HTTPException(404, "Archivo no disponible.")
        stem = Path(trabajo["archivo"]).stem
        return FileResponse(ruta, media_type=ARCHIVOS_DESCARGABLES[nombre],
                            filename=f"{stem} - {nombre}")

    @app.delete("/api/trabajos/{id_}", status_code=204)
    def eliminar_trabajo(id_: str, usuario: dict = Depends(usuario_actual)):
        trabajo = _trabajo_o_404(id_, usuario)
        if trabajo["estado"] == "procesando":
            raise HTTPException(409, "El trabajo se está procesando; espera a que termine.")
        trabajos.eliminar(id_)
        shutil.rmtree(ajustes.subidas_dir / id_, ignore_errors=True)
        shutil.rmtree(ajustes.resultados_dir / id_, ignore_errors=True)

    # --------------------------------------------------------------- interfaz
    @app.get("/", include_in_schema=False)
    def inicio(usuario: dict | None = Depends(usuario_opcional)):
        if usuario is None:
            return RedirectResponse("/login", status_code=302)
        return FileResponse(ESTATICOS / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/login", include_in_schema=False)
    def pagina_login(usuario: dict | None = Depends(usuario_opcional)):
        if usuario is not None:
            return RedirectResponse("/", status_code=302)
        return FileResponse(ESTATICOS / "login.html", headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")

    return app


def _mensaje_limite(ajustes: Ajustes) -> str:
    return f"El archivo supera el límite de {ajustes.max_subida_bytes // (1024 * 1024)} MB."


app = create_app()
