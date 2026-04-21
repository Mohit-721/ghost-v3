"""
Prompt version management.

Tools are pinned to the prompt version that generated them.
When prompts change, tools can be flagged for regeneration.
"""

import logging
from importlib import import_module

logger = logging.getLogger(__name__)

# Registry of prompt versions
PROMPT_VERSIONS = {
    "v1": "ghost.brain.prompts.v1",
}

CURRENT_VERSION = "v1"


def get_prompt(name: str, version: str | None = None) -> str:
    """
    Get a prompt template by name and version.

    Args:
        name: Prompt name (e.g., "forge", "triage", "analyze")
        version: Version string (e.g., "v1"). Defaults to current.

    Returns:
        Prompt template string
    """
    version = version or CURRENT_VERSION

    if version not in PROMPT_VERSIONS:
        raise ValueError(
            f"Unknown prompt version: {version}. Available: {list(PROMPT_VERSIONS.keys())}"
        )

    module_path = f"{PROMPT_VERSIONS[version]}.{name}"

    try:
        module = import_module(module_path)
        return module.PROMPT
    except (ImportError, AttributeError) as e:
        raise ValueError(f"Prompt '{name}' not found in version '{version}': {e}")
