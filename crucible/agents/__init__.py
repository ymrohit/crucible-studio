"""The five non-colluding LLM roles plus the shared Cerebras client.

Anti-collusion is enforced at the function-signature level (see CRUCIBLE_SPEC.md):
the Adversary receives the Spec only and never the candidate code; the Implementer
receives the Spec only and never the Oracle. The forbidden object is simply not a parameter.
"""

from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a role's verbatim system prompt from agents/prompts/<name>.txt."""
    path = _PROMPT_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8").strip()
