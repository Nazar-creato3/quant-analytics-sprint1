"""Optional GNN research spike via PyTorch Geometric (not promoted by default)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GnnSpikeResult:
    available: bool
    improvement_vs_baseline: float | None
    note: str
    promote: bool = False


def gnn_research_spike(
    correlation_matrix: Mapping[str, Mapping[str, float]] | None = None,
    *,
    baseline_accuracy: float = 0.5,
) -> GnnSpikeResult:
    """Evaluate whether a simple graph message-passing prior beats baseline.

    Requires ``torch_geometric``. Without it, returns unavailable. Promotion only
    when improvement >= 3pp on a toy correlation graph probe.
    """
    try:
        import torch
        import torch_geometric  # noqa: F401
        from torch_geometric.nn import GCNConv
    except Exception:
        return GnnSpikeResult(False, None, "torch_geometric_not_installed", False)

    try:
        symbols = list((correlation_matrix or {"A": {"A": 1.0, "B": 0.2}, "B": {"A": 0.2, "B": 1.0}}).keys())
        n = len(symbols)
        if n < 2:
            return GnnSpikeResult(True, 0.0, "too_few_nodes", False)
        idx = {s: i for i, s in enumerate(symbols)}
        edges: list[list[int]] = []
        for a, row in (correlation_matrix or {}).items():
            for b, corr in row.items():
                if a == b:
                    continue
                if abs(float(corr)) >= 0.3:
                    edges.append([idx[a], idx[b]])
        if not edges:
            return GnnSpikeResult(True, 0.0, "no_edges", False)
        edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()
        x = torch.randn(n, 8)
        conv = GCNConv(8, 4)
        out = conv(x, edge_index)
        score = float(torch.sigmoid(out.mean()).item())
        # Toy proxy: map score toward [0.45, 0.55]
        prox_acc = 0.45 + 0.1 * score
        improvement = prox_acc - baseline_accuracy
        promote = improvement >= 0.03
        return GnnSpikeResult(True, improvement, "gcn_toy_probe", promote)
    except Exception as exc:
        logger.debug("gnn_spike_failed", error=str(exc))
        return GnnSpikeResult(False, None, f"error:{exc}", False)
