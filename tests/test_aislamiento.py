"""Cada persona ve solo lo suyo; las plantillas institucionales las ve todo el mundo pero edita el admin."""
from .conftest import CONTEXTO_EJEMPLO, esperar_fin

AUDIO = {"archivo": ("reunion.m4a", b"datos-de-audio", "audio/mp4")}


def subir(cliente, **form):
    return cliente.post("/api/trabajos", files=AUDIO, data={"sin_contexto": "true", **form})


# ------------------------------------------------------------- transcripciones

def test_cada_usuario_ve_solo_sus_transcripciones(client, client_luis):
    de_ana = esperar_fin(client, subir(client).json()["id"])
    de_luis = esperar_fin(client_luis, subir(client_luis).json()["id"])

    assert [t["id"] for t in client.get("/api/trabajos").json()] == [de_ana["id"]]
    assert [t["id"] for t in client_luis.get("/api/trabajos").json()] == [de_luis["id"]]


def test_el_trabajo_ajeno_no_existe_para_los_demas(client, client_luis):
    ajeno = esperar_fin(client, subir(client).json()["id"])
    base = f"/api/trabajos/{ajeno['id']}"

    assert client_luis.get(base).status_code == 404
    assert client_luis.get(f"{base}/archivos/informe.md").status_code == 404
    assert client_luis.get(f"{base}/archivos/datos.json").status_code == 404
    assert client_luis.delete(base).status_code == 404
    # 404 y no 403: ni siquiera se confirma que ese identificador existe
    assert client_luis.get(base).json() == client_luis.get("/api/trabajos/inexistente").json()

    # y para su dueña sigue intacto
    assert client.get(base).status_code == 200
    assert client.get(f"{base}/archivos/informe.md").status_code == 200


def test_ni_el_admin_ve_las_transcripciones_de_otros(client, client_admin):
    esperar_fin(client, subir(client).json()["id"])
    assert client_admin.get("/api/trabajos").json() == []


def test_no_se_puede_usar_la_plantilla_personal_de_otro(client, client_luis):
    privada = client.post("/api/contextos", json=CONTEXTO_EJEMPLO).json()
    r = client_luis.post("/api/trabajos", files=AUDIO, data={"contexto_id": str(privada["id"])})
    assert r.status_code == 404
    assert client_luis.get("/api/trabajos").json() == []


# ------------------------------------------------------------------ plantillas

def test_las_institucionales_se_ven_pero_solo_el_admin_las_edita(client, client_admin):
    de_ana = {c["nombre"]: c for c in client.get("/api/contextos").json()}
    de_admin = {c["nombre"]: c for c in client_admin.get("/api/contextos").json()}
    assert set(de_ana) == set(de_admin) and len(de_ana) == 4
    assert all(c["ambito"] == "institucional" for c in de_ana.values())
    assert not any(c["editable"] for c in de_ana.values())
    assert all(c["editable"] for c in de_admin.values())


def test_un_usuario_normal_no_modifica_ni_borra_las_institucionales(client, client_admin):
    plantilla = client.get("/api/contextos").json()[0]
    cambio = {k: plantilla[k] for k in ("nombre", "descripcion", "participantes", "palabras_clave", "notas")}
    assert client.put(f"/api/contextos/{plantilla['id']}", json={**cambio, "notas": "vandalismo"}).status_code == 403
    assert client.delete(f"/api/contextos/{plantilla['id']}").status_code == 403
    assert client_admin.get(f"/api/contextos/{plantilla['id']}").json()["notas"] == plantilla["notas"]

    r = client_admin.put(f"/api/contextos/{plantilla['id']}", json={**cambio, "notas": "actualizada"})
    assert r.status_code == 200 and r.json()["notas"] == "actualizada"
    assert client.get(f"/api/contextos/{plantilla['id']}").json()["notas"] == "actualizada"   # todos la ven


def test_las_personales_son_privadas(client, client_luis, client_admin):
    mia = client.post("/api/contextos", json=CONTEXTO_EJEMPLO)
    assert mia.status_code == 201
    assert mia.json()["ambito"] == "personal" and mia.json()["editable"] is True

    for otro in (client_luis, client_admin):
        assert mia.json()["nombre"] not in [c["nombre"] for c in otro.get("/api/contextos").json()]
        assert otro.get(f"/api/contextos/{mia.json()['id']}").status_code == 404
        assert otro.put(f"/api/contextos/{mia.json()['id']}", json=CONTEXTO_EJEPLO_OTRO).status_code == 404
        assert otro.delete(f"/api/contextos/{mia.json()['id']}").status_code == 404
    assert client.get(f"/api/contextos/{mia.json()['id']}").status_code == 200


CONTEXTO_EJEPLO_OTRO = {**CONTEXTO_EJEMPLO, "notas": "ajeno"}


def test_el_nombre_es_unico_solo_dentro_de_cada_ambito(client, client_luis):
    assert client.post("/api/contextos", json=CONTEXTO_EJEMPLO).status_code == 201
    assert client.post("/api/contextos", json=CONTEXTO_EJEMPLO).status_code == 409        # misma persona
    assert client_luis.post("/api/contextos", json=CONTEXTO_EJEMPLO).status_code == 201   # otra persona: bien
    institucional = client.get("/api/contextos").json()[0]["nombre"]
    # una personal puede llamarse como una institucional (viven en ámbitos distintos)
    assert client.post("/api/contextos", json={**CONTEXTO_EJEMPLO, "nombre": institucional}).status_code == 201


def test_solo_el_admin_crea_institucionales(client, client_admin, client_luis):
    assert client.post("/api/contextos?institucional=true", json=CONTEXTO_EJEMPLO).status_code == 403
    r = client_admin.post("/api/contextos?institucional=true", json=CONTEXTO_EJEMPLO)
    assert r.status_code == 201 and r.json()["ambito"] == "institucional"
    visto = {c["nombre"]: c for c in client_luis.get("/api/contextos").json()}["Reunión de prueba"]
    assert visto["editable"] is False


def test_al_guardar_como_nueva_siempre_es_personal(client_admin):
    r = client_admin.post("/api/contextos", json=CONTEXTO_EJEMPLO)       # sin ?institucional
    assert r.json()["ambito"] == "personal"
