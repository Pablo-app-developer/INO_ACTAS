"""Lanzador rápido: procesa todos los audios nuevos con el modelo 'small'."""
import sys
import transcribir

MODELO = "small"

audios = transcribir.listar_audios()
if not audios:
    print(f"No se encontraron audios en: {transcribir.AUDIOS_DIR}")
    sys.exit(0)

print(f"Audios encontrados: {len(audios)}")
for audio in audios:
    print(f"\nProcesando: {audio.name}")
    transcribir.procesar_archivo(audio, modelo=MODELO)

print("\nProceso completado.")
