"""Contrato de datos: estructura que el LLM está obligado a devolver."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator


# Valores que el modelo inventa cuando no encuentra datos y que no son tecnologías reales
PLACEHOLDERS = {"unknown", "desconocido", "desconocida", "n/a", "na", "none", "ninguna", "null", "-"}


class NivelCriticidad(str, Enum):
    BAJA = "baja"
    MEDIA = "media"
    ALTA = "alta"


class ExtraccionTecnica(BaseModel):
    """Entidades técnicas extraídas de un texto (log de error o descripción de arquitectura)."""

    tecnologias: list[str] = Field(
        min_length=1,
        description="Tecnologías, lenguajes, frameworks, bases de datos o servicios mencionados.",
    )
    nivel_de_criticidad: NivelCriticidad = Field(
        description="Criticidad del problema o situación descrita: baja, media o alta.",
    )
    resumen_tecnico: str = Field(
        min_length=10,
        max_length=300,
        description="Resumen técnico del texto en una o dos oraciones.",
    )

    @field_validator("tecnologias")
    @classmethod
    def limpiar_tecnologias(cls, valores: list[str]) -> list[str]:
        """Quita vacíos, duplicados y valores de relleno; si no queda ninguna, falla."""
        limpias = list(dict.fromkeys(v.strip() for v in valores if v.strip()))
        rellenos = [v for v in limpias if v.strip("<>[]() ").lower() in PLACEHOLDERS]
        if rellenos:
            raise ValueError(f"valores de relleno no permitidos: {rellenos}")
        if not limpias:
            raise ValueError("la lista de tecnologías no puede estar vacía")
        return limpias
