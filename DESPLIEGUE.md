# Despliegue y administración

Guía para poner el Transcriptor de reuniones en un servidor y mantenerlo. Requiere un equipo
con **Docker** (Docker Desktop en Windows, o Docker Engine en Linux).

## 1. Primera instalación

```bash
git clone <repositorio> transcriptor && cd transcriptor
cp .env.example .env          # y completa las claves (ver sección 2)
docker compose up -d --build
docker compose exec web python -m app.usuarios crear <tu-usuario> --nombre "Tu Nombre" --admin
```

Abre `http://<servidor>:8001/` e inicia sesión. Si hay un problema: `docker compose logs -f web`.

## 2. Configuración (`.env`)

| Variable | Para qué sirve | Por defecto |
|---|---|---|
| `GROQ_API_KEY` | Transcripción (Whisper en Groq) | — |
| `DEEPSEEK_API_KEY` | Informe y acta | — |
| `MAX_SUBIDA_MB` | Tamaño máximo por archivo | 2048 |
| `CONSERVAR_AUDIO` | `true` = no borrar el audio al terminar | `false` |
| `SESION_HORAS` | Duración de una sesión | 12 |
| `COOKIE_SEGURA` | `true` cuando hay HTTPS (lo activa solo `docker-compose.https.yml`) | `false` |
| `DOMINIO` | Solo con HTTPS: el nombre con el que se accede | — |

> Las claves son del servicio contratado por el INO. **No se suben al repositorio** (`.env` está ignorado).
> Cambiar de proveedor o de claves es solo editar este archivo y ejecutar `docker compose up -d`.

## 3. HTTPS (necesario fuera de un equipo de confianza)

Sin HTTPS, las contraseñas y los audios viajan sin cifrar por la red. Con un nombre de dominio
apuntando al servidor:

```bash
echo "DOMINIO=transcriptor.tu-dominio.org" >> .env
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
```

Caddy obtiene y renueva el certificado solo (puertos 80 y 443 abiertos). Para una intranet sin dominio
público, descomenta `tls internal` en `deploy/Caddyfile`. La guía de Caddy explica cómo instalar su certificado
raíz en los equipos para evitar el aviso del navegador.

## 4. Usuarios

Los crea la persona que administra; no hay registro público.

```bash
docker compose exec web python -m app.usuarios crear ana --nombre "Ana Pérez"
docker compose exec web python -m app.usuarios listar
docker compose exec web python -m app.usuarios clave ana          # restablecer contraseña
docker compose exec web python -m app.usuarios desactivar ana     # bloquea el acceso sin borrar nada
docker compose exec web python -m app.usuarios activar ana
docker compose exec web python -m app.usuarios admin ana          # dar permisos de administrador (--quitar)
docker compose exec web python -m app.usuarios eliminar ana       # borra al usuario y TODAS sus transcripciones
```

- Contraseña de al menos 10 caracteres. Se pide por teclado sin mostrarse.
- Cada persona ve **solo sus propias transcripciones**; ni siquiera un administrador ve las de otros.
- Las plantillas de contexto del INO las ve todo el mundo; **solo un administrador las modifica**. Cada
  usuario puede guardar plantillas propias, que solo él ve.
- Tras 5 intentos fallidos, el usuario queda bloqueado 10 minutos.
- Cada persona puede cambiar su contraseña desde la pantalla principal; eso cierra sus otras sesiones.

## 5. Actualizar

```bash
git pull
docker compose up -d --build
```

Las bases de datos de versiones anteriores se actualizan solas al arrancar. Los datos están en el volumen
`datos` y no se pierden al reconstruir.

## 6. Copia de seguridad y restauración

Todo lo que importa está en el volumen `datos`: la base de datos (usuarios, plantillas, historial)
y los resultados de cada transcripción. El script lo respalda sin que tengas que conocer Docker:

```bash
python deploy/datos.py respaldar                 # crea copias/copia-datos-AAAA-MM-DD_HHMM.tar.gz
python deploy/datos.py restaurar copias/copia-datos-2026-10-20_0900.tar.gz
```

Para la copia se detiene la aplicación unos segundos (así la base de datos queda consistente) y se vuelve a
iniciar sola. La carpeta `copias/` está fuera de Git porque contiene usuarios y transcripciones reales.
**Guarda las copias fuera del servidor** (otro equipo, unidad de red) y prueba restaurarlas de vez en cuando.

## 7. Seguridad: qué está resuelto y qué depende del servidor

Resuelto en la aplicación: contraseñas con hash `scrypt`, sesiones con cookie `HttpOnly` y `SameSite`, tokens de
sesión guardados solo como hash, protección contra CSRF (verificación de `Origin`), bloqueo por intentos fallidos,
aislamiento estricto entre usuarios (lo ajeno responde «no encontrado»), audios borrados al terminar el
procesamiento y proceso sin privilegios de administrador dentro del contenedor.

Depende de quien instala: HTTPS (sección 3), mantener el sistema operativo y Docker actualizados, restringir el acceso
al servidor por red o VPN si no debe ser público, y las copias de seguridad (sección 6).

**Privacidad de los audios:** mientras se transcribe, el audio se envía a Groq (o al proveedor configurado) y el texto
a DeepSeek. Confirma que esto es compatible con la política de datos del INO antes de usar la herramienta con
reuniones sensibles.

## 8. Instalación temporal en un PC con Windows (solo red interna, HTTP)

Sirve mientras se aprueban los recursos de un servidor. Funciona igual que en un servidor, con estas diferencias:
el PC debe estar **encendido y sin suspenderse**, y Docker Desktop solo arranca cuando alguien inicia sesión en Windows.

1. Instala Docker Desktop y ábrelo. En *Settings → General* deja marcado *Start Docker Desktop when you sign in*.
2. Sigue la sección 1 (clonar, `.env`, `docker compose up -d --build`, crear el administrador).
3. **Permite el acceso desde la red** (una sola vez; PowerShell *como administrador*):
   ```powershell
   New-NetFirewallRule -DisplayName "Transcriptor INO (8001)" -Direction Inbound -Protocol TCP -LocalPort 8001 -Action Allow -Profile Domain,Private
   ```
4. **Evita que el PC se suspenda** (PowerShell como administrador):
   ```powershell
   powercfg /change standby-timeout-ac 0
   ```
5. Los usuarios entran por `http://<nombre-o-IP-del-PC>:8001/`. Averigua la IP con `ipconfig`. Pide a TI que le
   **reserve esa IP al equipo** (o una IP fija); si cambia, la dirección que compartiste deja de funcionar.

Como es HTTP, las contraseñas viajan sin cifrar dentro de la red interna: aceptable en una red de confianza, pero
no la expongas a internet. Para un servidor definitivo, usa HTTPS (sección 3).

## 9. Migrar al servidor definitivo

La aplicación no depende del PC donde corre: los datos están en un volumen y la configuración en `.env`.

```bash
# En el PC actual
python deploy/datos.py respaldar                  # genera copias/copia-datos-....tar.gz

# En el servidor nuevo (con Docker instalado)
git clone <repositorio> transcriptor && cd transcriptor
cp .env.example .env                              # o copia el .env del PC anterior
docker compose up -d --build
python deploy/datos.py restaurar copia-datos-....tar.gz     # copia el archivo al servidor primero
```

Después: avisa a los usuarios de la nueva dirección, activa HTTPS (sección 3) y apaga el PC temporal
(`docker compose down`). Los usuarios, las plantillas y todo el historial pasan tal cual.
