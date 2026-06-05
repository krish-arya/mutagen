"""Abstract interfaces (ports).

These ABCs define the contracts that infrastructure adapters must satisfy. The
core and service layers depend only on these abstractions, never on concrete
implementations. Together they describe the test-generation pipeline:

    RepoIngestor -> TargetSelector -> TestGenerator -> SandboxRunner
                                                    \\-> MutationGate -> Reporter

with :class:`LLMClient` powering generation and :class:`Store` persisting
artifacts and results across runs.
"""

from mutagen.core.interfaces.checkpoint_store import CheckpointStore
from mutagen.core.interfaces.llm import LLMClient, LLMResponse
from mutagen.core.interfaces.mutation_gate import MutationGate
from mutagen.core.interfaces.repo_ingestor import RepoIngestor
from mutagen.core.interfaces.reporter import Reporter
from mutagen.core.interfaces.sandbox_runner import SandboxRunner
from mutagen.core.interfaces.store import Store
from mutagen.core.interfaces.target_selector import TargetSelector
from mutagen.core.interfaces.test_generator import TestGenerator

__all__ = [
    "RepoIngestor",
    "TargetSelector",
    "TestGenerator",
    "SandboxRunner",
    "MutationGate",
    "LLMClient",
    "LLMResponse",
    "Reporter",
    "Store",
    "CheckpointStore",
]
