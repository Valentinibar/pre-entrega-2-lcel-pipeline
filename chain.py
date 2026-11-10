"""Pipeline LCEL: prompt | model.with_structured_output(Schema), con validación y reintentos."""

import logging
import os

import anthropic
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import OutputParserException
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from pydantic import ValidationError

from schemas import ExtraccionTecnica

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pipeline")


class SalidaIncompletaError(Exception):
    """El modelo cortó la respuesta (finish_reason / stop_reason = max_tokens)."""


# --- 1. Modelo (reutiliza la configuración por .env del Módulo 1) ---
model = ChatAnthropic(
    model=os.getenv("LLM_MODEL") or "claude-haiku-5-5",
    max_tokens=int(os.getenv("LLM_MAX_TOKENS", "1024")),
    max_retries=0,  # los reintentos los maneja .with_retry() de la cadena
)

# --- 2. Prompt modular: texto de entrada + instrucciones de formato ---
INSTRUCCIONES = """\
- tecnologias: solo nombres concretos (ej. "PostgreSQL", "Redis", "FastAPI"), sin repetir.
  Si el texto no nombra ninguna, usá los componentes genéricos que mencione
  (ej. "base de datos", "servidor"). Nunca uses valores como "unknown", "N/A" o "desconocido".
- nivel_de_criticidad:
  * alta: caída del servicio, pérdida de datos, problema de seguridad o impacto en usuarios.
  * media: degradación de rendimiento o errores intermitentes.
  * baja: información, advertencias o descripciones sin problema activo.
- resumen_tecnico: una o dos oraciones en español, máximo 300 caracteres."""

prompt = ChatPromptTemplate.from_messages([
    ("system",
     "Sos un ingeniero de software senior que analiza textos técnicos "
     "(logs de error y descripciones de arquitectura) y extrae información estructurada.\n"
     "Seguí estas instrucciones de formato:\n{instrucciones}"),
    ("human", "Texto a analizar:\n\n{texto}"),
]).partial(instrucciones=INSTRUCCIONES)

# include_raw=True devuelve también el mensaje crudo, para revisar el stop_reason
structured_model = model.with_structured_output(ExtraccionTecnica, include_raw=True)


# --- 3. Paso de validación: decide si la salida sirve o hay que reintentar ---
def validar_salida(resultado: dict) -> ExtraccionTecnica:
    raw = resultado["raw"]
    stop_reason = raw.response_metadata.get("stop_reason")
    log.info(f"Validando respuesta del modelo (stop_reason={stop_reason})")

    if stop_reason == "max_tokens":
        log.warning("Respuesta cortada por falta de tokens -> se reintenta")
        raise SalidaIncompletaError("el modelo cortó la respuesta por max_tokens")

    if resultado["parsing_error"] is not None:
        error = str(resultado["parsing_error"]).splitlines()[0]
        log.warning(f"JSON inválido o incompleto: {error} -> se reintenta")
        raise resultado["parsing_error"]

    if resultado["parsed"] is None:
        log.warning("El modelo no devolvió salida estructurada -> se reintenta")
        raise OutputParserException("salida estructurada vacía")

    log.info("Validación Pydantic OK")
    return resultado["parsed"]


# --- 4. Cadena LCEL completa con reintentos ---
# Solo se reintentan errores recuperables: formato (JSON mal formado/incompleto)
# y transitorios (rate limit, red, servidor). Una API key inválida NO se reintenta.
ERRORES_REINTENTABLES = (
    OutputParserException,
    ValidationError,
    SalidaIncompletaError,
    anthropic.RateLimitError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
)

chain = (
    prompt
    | structured_model
    | RunnableLambda(validar_salida)
).with_retry(
    retry_if_exception_type=ERRORES_REINTENTABLES,
    stop_after_attempt=3,          # 1 intento + 2 reintentos
    wait_exponential_jitter=True,  # backoff exponencial entre intentos
)


# --- 5. Función asíncrona de entrada ---
async def process_text(text: str) -> ExtraccionTecnica | None:
    """Procesa un texto y devuelve el objeto validado, o None si falló definitivamente."""
    log.info(f"Procesando texto ({len(text)} caracteres)")
    try:
        resultado = await chain.ainvoke({"texto": text})
        log.info("Extracción completada")
        return resultado
    except ERRORES_REINTENTABLES as e:
        log.error(f"Falló tras agotar los reintentos: {type(e).__name__}: {e}")
    except Exception as e:
        log.error(f"Error no recuperable (no se reintenta): {type(e).__name__}: {e}")
    return None
