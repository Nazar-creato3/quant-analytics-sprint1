"""Validate Strategy Composer configs — cycles and unreachable branches."""
from __future__ import annotations

from collections import deque

from app.services.strategy.composer.models import (
    ComposerConfig,
    ComposerValidationResult,
)


def validate_composer_config(config: ComposerConfig) -> ComposerValidationResult:
    """Run structural validation beyond pydantic reference checks."""
    errors: list[str] = []
    warnings: list[str] = []

    branch_map = {branch.id: branch for branch in config.branches}
    outcome_ids = {outcome.id for outcome in config.outcomes}

    cycle = _detect_branch_cycle(config.root_branch_id, branch_map)
    if cycle:
        errors.append(f"condition cycle detected: {' -> '.join(cycle)}")

    reachable_branches, reachable_outcomes = _collect_reachable(config, branch_map)
    unreachable_branches = set(branch_map) - reachable_branches
    if unreachable_branches:
        errors.append(
            "unreachable branches: " + ", ".join(sorted(unreachable_branches))
        )

    unreachable_outcomes = outcome_ids - reachable_outcomes - {config.default_outcome_id}
    if unreachable_outcomes:
        errors.append(
            "unreachable outcomes: " + ", ".join(sorted(unreachable_outcomes))
        )

    for branch in config.branches:
        if branch.else_branch_id is None and branch.else_outcome_id is None:
            errors.append(f"branch {branch.id} has no else path")

    return ComposerValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def _detect_branch_cycle(
    root_id: str,
    branch_map: dict[str, object],
) -> list[str] | None:
    """Return cycle path if branch->else_branch graph contains a cycle."""
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def dfs(branch_id: str) -> list[str] | None:
        if branch_id in visiting:
            cycle_start = stack.index(branch_id)
            return stack[cycle_start:] + [branch_id]
        if branch_id in visited:
            return None
        if branch_id not in branch_map:
            return None

        visiting.add(branch_id)
        stack.append(branch_id)
        branch = branch_map[branch_id]
        next_id = getattr(branch, "else_branch_id", None)
        if next_id:
            cycle = dfs(next_id)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(branch_id)
        visited.add(branch_id)
        return None

    return dfs(root_id)


def _collect_reachable(
    config: ComposerConfig,
    branch_map: dict[str, object],
) -> tuple[set[str], set[str]]:
    """Breadth-first traversal from root through then/else paths."""
    reachable_branches: set[str] = set()
    reachable_outcomes: set[str] = set()
    queue: deque[str] = deque([config.root_branch_id])

    while queue:
        branch_id = queue.popleft()
        if branch_id in reachable_branches:
            continue
        if branch_id not in branch_map:
            continue

        reachable_branches.add(branch_id)
        branch = branch_map[branch_id]
        reachable_outcomes.add(branch.then_outcome_id)

        if branch.else_outcome_id:
            reachable_outcomes.add(branch.else_outcome_id)
        elif branch.else_branch_id:
            queue.append(branch.else_branch_id)

    return reachable_branches, reachable_outcomes
