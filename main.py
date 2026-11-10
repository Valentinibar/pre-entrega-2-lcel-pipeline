"""Mini-script de prueba: ejecuta el pipeline sobre tres textos, incluido uno ambiguo."""

import asyncio

from chain import process_text

EJEMPLOS = {
    "Log de error": (
        "2026-11-10 14:32:01 ERROR [api-gateway] FastAPI worker timeout: "
        "psycopg2.OperationalError: could not connect to PostgreSQL at db:5432. "
        "Redis cache miss rate 98%. 500 Internal Server Error devuelto a 1.200 usuarios."
    ),
    "Descripción de arquitectura": (
        "El frontend en React consume una API REST en Node.js con Express, desplegada en "
        "contenedores Docker sobre Kubernetes. Los archivos se guardan en Amazon S3 y las "
        "métricas se monitorean con Prometheus y Grafana."
    ),
    "Texto ambiguo (prueba de estrés)": (
        "Anoche algo anduvo lento, creo que fue la base o el servidor, no estoy seguro."
    ),
}


async def main() -> None:
    for titulo, texto in EJEMPLOS.items():
        print(f"\n{'=' * 60}\n{titulo}\n{'=' * 60}")
        resultado = await process_text(texto)
        if resultado:
            print(resultado.model_dump_json(indent=2))
        else:
            print("No se pudo obtener una salida válida (ver logs).")


if __name__ == "__main__":
    asyncio.run(main())
