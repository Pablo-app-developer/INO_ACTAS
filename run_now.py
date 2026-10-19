"""Lanzador rápido: procesa todos los audios nuevos con el modelo 'small'.

Uso: python run_now.py <contexto>
Ejemplo: python run_now.py observatorio
"""
import sys
import transcribir

MODELO = "small"

if len(sys.argv) < 2:
    print("Falta indicar el contexto.\n")
    disponibles = transcribir.listar_contextos()
    if disponibles:
        print("Contextos disponibles:")
        for alias, ruta in disponibles.items():
            print(f"  {alias}  ->  {ruta.name}")
        print(f"\nEjemplo: python run_now.py {next(iter(disponibles))}")
    else:
        print(f"No hay archivos contexto*.txt en {transcribir.PROYECTO_DIR}")
    sys.exit(1)

# resolver_contexto aborta con un mensaje claro si el alias no coincide
transcribir.CONTEXTO_FILE = transcribir.resolver_contexto(sys.argv[1])

audios = transcribir.listar_audios()
if not audios:
    print(f"No se encontraron audios en: {transcribir.AUDIOS_DIR}")
    sys.exit(0)

print(f"Audios encontrados: {len(audios)}")
for audio in audios:
    print(f"\nProcesando: {audio.name}")
    transcribir.procesar_archivo(audio, modelo=MODELO)

print("\nProceso completado.")
