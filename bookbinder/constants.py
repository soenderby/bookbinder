from __future__ import annotations

from typing import Final

PAPER_SIZES: Final[dict[str, tuple[float, float]]] = {
    "A4": (595.2756, 841.8898),
    "Letter": (612.0, 792.0),
}

DEFAULT_ARTIFACT_DIR: Final[str] = "generated"
