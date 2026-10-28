"""interfaces: Pure behavioral contracts and strategies for zipdir."""

from zipdir.interfaces.evaluator import (
    IPathEvaluator,
    IRemapStrategy,
    IRuleTransition,
)
from zipdir.interfaces.glob import IGlobCompiler
from zipdir.interfaces.interpreter import (
    IRuleInterpreter,
    IRuleSqueezer,
    ISqueezeStrategy,
    SqueezeBuffer,
)
from zipdir.interfaces.output import (
    IOutputResolver,
    IOutputTargetStrategy,
)
from zipdir.interfaces.packager import (
    IArchiveEntryWriter,
    IPackager,
)
from zipdir.interfaces.presets import IPresetCatalog
from zipdir.interfaces.ui import IReporter
from zipdir.models import EvaluationState, RemapContext

__all__ = [
    "EvaluationState",
    "IArchiveEntryWriter",
    "IGlobCompiler",
    "IOutputResolver",
    "IOutputTargetStrategy",
    "IPackager",
    "IPathEvaluator",
    "IPresetCatalog",
    "IRemapStrategy",
    "IReporter",
    "IRuleInterpreter",
    "IRuleSqueezer",
    "IRuleTransition",
    "ISqueezeStrategy",
    "RemapContext",
    "SqueezeBuffer",
]
