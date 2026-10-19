"""Lanzador del servidor web:  python -m app

Variables de entorno opcionales:
  HOST   (por defecto 127.0.0.1, solo este equipo; usa 0.0.0.0 para abrirlo a la red)
  PORT   (por defecto 8001)
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8001")))
