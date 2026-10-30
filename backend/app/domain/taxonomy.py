"""Asset category hierarchy helpers."""
from __future__ import annotations

from app.domain.enums import CATEGORY_PARENTS, AssetCategory


def parent_of(category: AssetCategory) -> AssetCategory | None:
    return CATEGORY_PARENTS[category]


def is_root(category: AssetCategory) -> bool:
    return parent_of(category) is None


def ancestors_of(category: AssetCategory) -> tuple[AssetCategory, ...]:
    """Return root-to-parent chain excluding *category* itself."""
    chain: list[AssetCategory] = []
    current = parent_of(category)
    while current is not None:
        chain.append(current)
        current = parent_of(current)
    return tuple(reversed(chain))


def is_descendant_of(category: AssetCategory, ancestor: AssetCategory) -> bool:
    current = category
    while True:
        parent = parent_of(current)
        if parent is None:
            return False
        if parent == ancestor:
            return True
        current = parent


def children_of(category: AssetCategory) -> tuple[AssetCategory, ...]:
    return tuple(child for child, parent in CATEGORY_PARENTS.items() if parent == category)
