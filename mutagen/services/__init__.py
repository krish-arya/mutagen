"""Application services layer.

Services orchestrate domain models and ports to fulfil the test-generation use
case. They depend only on abstractions from :mod:`mutagen.core.interfaces`,
never on concrete infrastructure, and perform no I/O of their own.

The :class:`PipelineOrchestrator` drives a whole run; :class:`TargetProcessor`
drives a single target through its lifecycle; :class:`BudgetTracker` enforces
the run's budget and cost limits.
"""

from mutagen.services.budget import BudgetReason, BudgetTracker
from mutagen.services.generation_service import GenerationService
from mutagen.services.orchestrator import PipelineOrchestrator
from mutagen.services.progress import (
    ProgressEvent,
    ProgressListener,
    ProgressPhase,
)
from mutagen.services.reporting_service import ReportingService
from mutagen.services.selection_service import SelectionService
from mutagen.services.target_processor import ProcessResult, TargetProcessor

__all__ = [
    "PipelineOrchestrator",
    "TargetProcessor",
    "ProcessResult",
    "BudgetTracker",
    "BudgetReason",
    "ProgressEvent",
    "ProgressPhase",
    "ProgressListener",
    "SelectionService",
    "GenerationService",
    "ReportingService",
]
