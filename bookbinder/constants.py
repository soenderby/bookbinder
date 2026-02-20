from __future__ import annotations

from typing import Final

PAPER_SIZES: Final[dict[str, tuple[float, float]]] = {
    "A3": (841.8898, 1190.551),
    "A4": (595.2756, 841.8898),
    "A5": (419.5276, 595.2756),
    "Legal": (612.0, 1008.0),
    "Letter": (612.0, 792.0),
    "Tabloid": (792.0, 1224.0),
}

DEFAULT_ARTIFACT_DIR: Final[str] = "generated"
DEFAULT_ARTIFACT_RETENTION_SECONDS: Final[int] = 24 * 60 * 60
