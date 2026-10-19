import io
import sqlite3
from datetime import date

from docx import Document

from app.db import BaseDatos
from motor.acta import DatosActa

from .conftest import esperar_fin

AUDIO = {"archivo": ("reunion.m4a", b"datos-de-audio", "audio/mp4")}


def subir(client, **form):
    return client.post("/api/trabajos", files=AUDIO, data=form)


def test_flujo_con_acta_genera_word_descargable(client, motor):
    r = subir(client, sin_contexto="true", generar_acta="true", acta_numero="031",
              acta_fecha="2026-09-09", acta_hora="9:00 a. m.")
    assert r.status_code == 202
    assert r.json()["acta"] == {"numero": "031", "fecha": "2026-09-09", "hora": "9:00 a. m."}

    final = esperar_fin(client, r.json()["id"])
    assert final["estado"] == "completado"
    assert "acta.docx" in final["archivos"]
    # El motor recibió los datos que escribió el usuario
    assert motor.llamadas[0][1].acta == DatosActa(numero="031", fecha=date(2026, 9, 9), hora="9:00 a. m.")

    descarga = client.get(f"/api/trabajos/{final['id']}/archivos/acta.docx")
    assert descarga.status_code == 200
    assert "wordprocessingml" in descarga.headers["content-type"]
    doc = Document(io.BytesIO(descarga.content))
    textos = [p.text for p in doc.paragraphs]
    assert textos[0] == "ACTA 031"
    assert "Acta de Reunión: Reunión de prueba - 09 de septiembre de 2026" in textos
    assert [c.text for c in doc.tables[0].rows[1].cells] == ["Ana", "Hacer algo.", "Alta"]


def test_sin_acta_no_hay_word(client):
    final = esperar_fin(client, subir(client, sin_contexto="true").json()["id"])
    assert "acta.docx" not in final["archivos"] and final["acta"] is None


def test_acta_exige_fecha_valida(client):
    assert subir(client, sin_contexto="true", generar_acta="true").status_code == 422
    r = subir(client, sin_contexto="true", generar_acta="true", acta_fecha="02/09/2026")
    assert r.status_code == 422 and "fecha" in r.json()["detail"].lower()
    assert client.get("/api/trabajos").json() == []        # no queda un trabajo a medias


def test_acta_no_va_con_solo_transcribir(client):
    r = subir(client, sin_contexto="true", sin_analisis="true", generar_acta="true", acta_fecha="2026-09-09")
    assert r.status_code == 422 and "solo transcribir" in r.json()["detail"]


def test_si_falla_el_acta_se_entrega_lo_demas_con_aviso(client, motor):
    motor.advertencias = ["No se pudo generar el acta: el modelo no devolvió un acta válida"]
    # El motor falso igualmente devuelve acta; simulamos el fallo del Word borrando la plantilla
    from unittest import mock
    with mock.patch("app.cola.construir_docx", side_effect=RuntimeError("plantilla dañada")):
        r = subir(client, sin_contexto="true", generar_acta="true", acta_fecha="2026-09-09")
        final = esperar_fin(client, r.json()["id"])
    assert final["estado"] == "completado"
    assert "acta.docx" not in final["archivos"] and "informe.md" in final["archivos"]
    assert any("documento Word" in a for a in final["advertencias"])
    assert any("No se pudo generar el acta" in a for a in final["advertencias"])


def test_migra_una_base_de_datos_anterior(tmp_path):
    ruta = tmp_path / "vieja.db"
    con = sqlite3.connect(ruta)
    con.executescript("""
        CREATE TABLE trabajos (id TEXT PRIMARY KEY, estado TEXT NOT NULL, archivo TEXT NOT NULL,
            contexto TEXT, sin_analisis INTEGER NOT NULL DEFAULT 0, etapa TEXT, mensaje TEXT,
            progreso REAL NOT NULL DEFAULT 0, error TEXT, advertencias TEXT NOT NULL DEFAULT '[]',
            carpeta TEXT, duracion REAL, creado TEXT NOT NULL, iniciado TEXT, terminado TEXT);
        INSERT INTO trabajos (id, estado, archivo, creado) VALUES ('a', 'completado', 'x.mp3', '2026-01-01');
    """)
    con.close()

    bd = BaseDatos(ruta)
    bd.inicializar()
    bd.inicializar()                                        # repetirlo no debe fallar
    from app.repos import RepoTrabajos
    antiguo = RepoTrabajos(bd).obtener("a")
    assert antiguo["acta"] is None and antiguo["estado"] == "completado"
