"""Abstract interfaces (ports).

These Protocols and ABCs define the contracts that infrastructure adapters
must satisfy. The core and service layers depend only on these abstractions,
never on concrete implementations.
"""

from mutagen.core.interfaces.coverage import CoverageCollector
from mutagen.core.interfaces.llm import LLMClient, LLMResponse
from mutagen.core.interfaces.mutation import MutationGenerator, MutationOperator
from mutagen.core.interfaces.repository import RunRepository
from mutagen.core.interfaces.reporter import Reporter
from mutagen.core.interfaces.sandbox import Sandbox, SandboxContext
from mutagen.core.interfaces.storage import ArtifactStore
from mutagen.core.interfaces.test_runner import TestRunner

__all__ = [
    "CoverageCollector",
    "LLMClient",
    "LLMResponse",
    "MutationGenerator",
    "MutationOperator",
    "RunRepository",
    "Reporter",
    "Sandbox",
    "SandboxContext",
    "ArtifactStore",
    "TestRunner",
]
