def test_config_expone_formatos_y_limite(client, ajustes):
    cfg = client.get("/api/config").json()
    assert ".m4a" in cfg["formatos"] and ".mkv" in cfg["formatos"]
    assert cfg["max_subida_mb"] == ajustes.max_subida_bytes // (1024 * 1024)


def test_pagina_principal_y_estaticos(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "Transcriptor de reuniones" in r.text
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
