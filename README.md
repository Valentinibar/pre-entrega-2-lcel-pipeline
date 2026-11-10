# Pre-entrega Módulo 2 — Pipeline de Extracción de Entidades Técnicas

Pipeline en **LangChain (LCEL)** que recibe un texto técnico sin procesar (un log de error o una descripción de arquitectura) y devuelve un objeto **validado con Pydantic**, con reintentos automáticos si el modelo devuelve un JSON mal formado o incompleto.

## Estructura

| Archivo | Contenido |
|---|---|
| `schemas.py` | Contrato de datos `ExtraccionTecnica`: `tecnologias` (lista no vacía, sin duplicados), `nivel_de_criticidad` (enum `baja`/`media`/`alta`) y `resumen_tecnico` (10 a 300 caracteres) |
| `chain.py` | `ChatPromptTemplate` modular, modelo `ChatAnthropic`, cadena LCEL `prompt \| model.with_structured_output(...)`, validación, `.with_retry()` y la función asíncrona `process_text()` |
| `main.py` | Mini-script de prueba asíncrono con tres textos: un log de error, una descripción de arquitectura y un texto ambiguo (prueba de estrés) |

## Cómo ejecutarlo

Requiere Python 3.12+.

```bash
python -m venv .venv
# Windows (Git Bash)
source .venv/Scripts/activate
# Linux / Mac
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env     # completar ANTHROPIC_API_KEY
python main.py
```

## Variables de entorno

| Variable | Obligatoria | Descripción |
|---|---|---|
| `ANTHROPIC_API_KEY` | Sí | API key de Anthropic |
| `LLM_MODEL` | No (default `claude-haiku-5-5`) | Modelo a usar |
| `LLM_MAX_TOKENS` | No (default `1024`) | Máximo de tokens de salida |

## Cómo funciona la cadena

```
prompt | model.with_structured_output(ExtraccionTecnica, include_raw=True) | validar_salida
        └──────────────────────── .with_retry(stop_after_attempt=3) ────────────────────────┘
```

1. **Prompt:** `ChatPromptTemplate` con rol `system` y `human`. Recibe `{texto}`, y las reglas de formato y criticidad entran como variable `{instrucciones}` mediante `.partial()`. No se usan f-strings.
2. **Salida estructurada:** `with_structured_output` obliga al modelo a responder con el esquema Pydantic (Anthropic lo resuelve con tool calling). Con `include_raw=True` se conserva también el mensaje crudo.
3. **Validación (`validar_salida`):**
   - Si `stop_reason == "max_tokens"`, la respuesta quedó cortada y se lanza `SalidaIncompletaError`.
   - Si el JSON no se pudo parsear o no cumple el esquema, se relanza el error de parseo.
   - Si todo está bien, devuelve el objeto `ExtraccionTecnica` validado.
4. **Resiliencia (`.with_retry`):** hasta 3 intentos con backoff exponencial, solo ante errores recuperables: formato (JSON mal formado o incompleto, respuesta cortada) y transitorios (rate limit 429, red, error 5xx). Los errores permanentes, como una API key inválida, **no se reintentan**, para no gastar dinero ni latencia.
5. **`process_text()`:** función asíncrona que ejecuta la cadena con `.ainvoke()`, registra cada paso en los logs y devuelve `None` (sin crash) si la extracción falla definitivamente.

## Ejemplo de salida

Entrada (log de error):

```
ERROR [api-gateway] FastAPI worker timeout: psycopg2.OperationalError: could not connect
to PostgreSQL at db:5432. Redis cache miss rate 98%. 500 Internal Server Error devuelto a 1.200 usuarios.
```

Salida validada:

```json
{
  "tecnologias": ["FastAPI", "PostgreSQL", "psycopg2", "Redis"],
  "nivel_de_criticidad": "alta",
  "resumen_tecnico": "El api-gateway con FastAPI agota el timeout de sus workers al no poder conectar con PostgreSQL en db:5432, devolviendo 500 a 1.200 usuarios. Además, Redis muestra una tasa de cache miss del 98%."
}
```

Logs del proceso:

```
19:10:39 [INFO] Procesando texto (214 caracteres)
19:10:41 [INFO] HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
19:10:41 [INFO] Validando respuesta del modelo (stop_reason=tool_use)
19:10:41 [INFO] Validación Pydantic OK
19:10:41 [INFO] Extracción completada
```

## Prueba de estrés: texto ambiguo

Con el texto *"Anoche algo anduvo lento, creo que fue la base o el servidor, no estoy seguro."* (que no nombra ninguna tecnología), la primera versión del pipeline devolvió:

```json
{ "tecnologias": ["<UNKNOWN>"], "nivel_de_criticidad": "media", ... }
```

El modelo cumplió el esquema (lista no vacía) inventando un valor de relleno. Para evitarlo:

- El validador de `schemas.py` rechaza valores de relleno (`unknown`, `N/A`, `desconocido`, etc.), lo que provoca un `ValidationError` y dispara el reintento.
- El prompt indica que, si no hay tecnologías concretas, use los componentes genéricos mencionados (ej. "base de datos", "servidor").

Si tras 3 intentos el modelo sigue sin cumplir el contrato, `process_text()` registra el error y devuelve `None` en lugar de propagar datos inválidos.

Ejemplo de logs cuando el modelo falla y se recupera:

```
[INFO] Validando respuesta del modelo (stop_reason=max_tokens)
[WARNING] Respuesta cortada por falta de tokens -> se reintenta
[INFO] Validando respuesta del modelo (stop_reason=tool_use)
[WARNING] JSON inválido o incompleto: JSON mal formado -> se reintenta
[INFO] Validando respuesta del modelo (stop_reason=tool_use)
[INFO] Validación Pydantic OK
```
