import json

from urllib.parse import unquote

from motor.transcripcion import ErrorTranscripcion

from .conftest import CONTEXTO_EJEMPLO, esperar_fin

AUDIO = {"archivo": ("reunion.m4a", b"datos-de-audio", "audio/mp4")}


def subir(client, files=AUDIO, **form):
    return client.post("/api/trabajos", files=files, data=form)


def test_flujo_completo_con_contexto_guardado(client, motor, ajustes):
    plantilla_id = client.get("/api/contextos").json()[0]["id"]
    r = subir(client, contexto_id=str(plantilla_id))
    assert r.status_code == 202
    trabajo = r.json()
    assert trabajo["estado"] == "en_cola" and trabajo["archivo"] == "reunion.m4a"

    final = esperar_fin(client, trabajo["id"])
    assert final["estado"] == "completado" and final["progreso"] == 1
    assert final["duracion"] == 90.0
    assert set(final["archivos"]) == {"informe.md", "transcripcion.txt",
                                      "transcripcion_tiempos.txt", "datos.json"}

    # El motor recibió el contexto convertido a texto y el audio con su extensión
    ruta, opciones = motor.llamadas[0]
    assert ruta.name == "original.m4a"
    assert opciones.contexto.startswith(client.get(f"/api/contextos/{plantilla_id}").json()["nombre"])

    # El audio se borra al terminar (privacidad)
    assert not (ajustes.subidas_dir / trabajo["id"]).exists()

    informe = client.get(f"/api/trabajos/{trabajo['id']}/archivos/informe.md")
    assert informe.status_code == 200
    assert "## Resumen" in informe.text
    assert "reunion.m4a" in informe.text          # nombre original, no "original.m4a"
    assert "reunion - informe.md" in unquote(informe.headers["content-disposition"])


def test_contexto_editado_en_el_momento(client, motor):
    r = subir(client, contexto=json.dumps(CONTEXTO_EJEMPLO))
    esperar_fin(client, r.json()["id"])
    assert "Hablan: Ana Pérez." in motor.llamadas[0][1].contexto
    assert r.json()["contexto"]["nombre"] == "Reunión de prueba"


def test_sin_contexto_y_sin_analisis(client, motor):
    r = subir(client, sin_contexto="true", sin_analisis="true")
    final = esperar_fin(client, r.json()["id"])
    assert final["estado"] == "completado"
    opciones = motor.llamadas[0][1]
    assert opciones.contexto == "" and opciones.sin_analisis is True


def test_exige_exactamente_una_opcion_de_contexto(client):
    assert subir(client).status_code == 422
    assert subir(client, sin_contexto="true", contexto=json.dumps(CONTEXTO_EJEMPLO)).status_code == 422


def test_contexto_invalido_o_inexistente(client):
    assert subir(client, contexto="no es json").status_code == 422
    assert subir(client, contexto=json.dumps({"nombre": ""})).status_code == 422
    assert subir(client, contexto_id="9999").status_code == 404


def test_formato_no_admitido(client):
    r = subir(client, files={"archivo": ("virus.exe", b"x", "application/octet-stream")},
              sin_contexto="true")
    assert r.status_code == 415 and ".mp3" in r.json()["detail"]


def test_archivo_vacio(client):
    r = subir(client, files={"archivo": ("a.mp3", b"", "audio/mpeg")}, sin_contexto="true")
    assert r.status_code == 422


def test_limite_de_tamano_y_limpieza(client, ajustes):
    grande = {"archivo": ("a.mp3", b"x" * (ajustes.max_subida_bytes + 10), "audio/mpeg")}
    r = subir(client, files=grande, sin_contexto="true")
    assert r.status_code == 413
    # No debe quedar basura en disco ni trabajos fantasma
    assert list(ajustes.subidas_dir.iterdir()) == []
    assert client.get("/api/trabajos").json() == []


def test_nombre_de_archivo_con_ruta_se_sanea(client):
    r = subir(client, files={"archivo": ("../../etc/passwd.mp3", b"x", "audio/mpeg")},
              sin_contexto="true")
    assert r.json()["archivo"] == "passwd.mp3"


def test_error_de_transcripcion_se_informa(client, motor):
    motor.error = ErrorTranscripcion("No se obtuvo texto. Verifica el audio.")
    r = subir(client, sin_contexto="true")
    final = esperar_fin(client, r.json()["id"])
    assert final["estado"] == "error" and "No se obtuvo texto" in final["error"]
    assert final["archivos"] == []


def test_error_inesperado_no_mata_la_cola(client, motor):
    motor.error = RuntimeError("boom")
    malo = esperar_fin(client, subir(client, sin_contexto="true").json()["id"])
    assert malo["estado"] == "error"

    motor.error = None
    bueno = esperar_fin(client, subir(client, sin_contexto="true").json()["id"])
    assert bueno["estado"] == "completado"


def test_descarga_solo_archivos_permitidos(client):
    final = esperar_fin(client, subir(client, sin_contexto="true").json()["id"])
    base = f"/api/trabajos/{final['id']}/archivos"
    assert client.get(f"{base}/datos.json").status_code == 200
    assert client.get(f"{base}/..%2F..%2Fapp.db").status_code == 404
    assert client.get(f"{base}/app.db").status_code == 404
    assert client.get("/api/trabajos/no-existe/archivos/informe.md").status_code == 404


def test_listar_y_eliminar(client, ajustes):
    a = esperar_fin(client, subir(client, sin_contexto="true").json()["id"])
    b = esperar_fin(client, subir(client, sin_contexto="true").json()["id"])
    ids = [t["id"] for t in client.get("/api/trabajos").json()]
    assert ids == [b["id"], a["id"]]                   # más reciente primero

    assert client.delete(f"/api/trabajos/{a['id']}").status_code == 204
    assert client.get(f"/api/trabajos/{a['id']}").status_code == 404
    assert not (ajustes.resultados_dir / a["id"]).exists()
    assert client.delete(f"/api/trabajos/{a['id']}").status_code == 404
