"""Strategy Composer — lazy exports."""

from __future__ import annotations

from typing import Any

_LAZY: dict[str, tuple[str, str]] = {
    "apply_outcome_to_context": ("app.services.strategy.composer.compiler", "apply_outcome_to_context"),
    "compile_composer_config": ("app.services.strategy.composer.compiler", "compile_composer_config"),
    "resolve_from_root": ("app.services.strategy.composer.compiler", "resolve_from_root"),
    "ComposerConfig": ("app.services.strategy.composer.models", "ComposerConfig"),
    "ComposerValidationResult": ("app.services.strategy.composer.models", "ComposerValidationResult"),
    "CompiledStrategyConfig": ("app.services.strategy.composer.models", "CompiledStrategyConfig"),
    "StrategyComposerService": ("app.services.strategy.composer.service", "StrategyComposerService"),
    "validate_composer_config": ("app.services.strategy.composer.validator", "validate_composer_config"),
}

__all__ = list(_LAZY.keys())


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(target[0])
    return getattr(module, target[1])
