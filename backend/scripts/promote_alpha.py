"""Human promote-to-prod. Retrain never aliases live.

Example:
  python -m scripts.promote_alpha --name forecast_lgbm_AAPL --freeze AAPL_20260921 \\
      --lineage abc123 --n-train 400 --outer-acc 0.56 --outer-n 80 --confirm --reviewer you
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.alpha.model_card import build_card, human_promote, list_research_cards  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Promote a frozen alpha card after human review")
    p.add_argument("--list", action="store_true")
    p.add_argument("--name")
    p.add_argument("--freeze", dest="freeze_id")
    p.add_argument("--lineage", default="")
    p.add_argument("--n-train", type=int, default=0)
    p.add_argument("--outer-acc", type=float, default=0.0)
    p.add_argument("--outer-n", type=float, default=0.0)
    p.add_argument("--reviewer", default="")
    p.add_argument("--confirm", action="store_true")
    args = p.parse_args()
    if args.list:
        print(json.dumps(list_research_cards(), indent=2))
        return 0
    if not args.name or not args.freeze_id:
        p.error("--name and --freeze are required unless --list")
    card = build_card(
        name=args.name,
        metrics={
            "accuracy": args.outer_acc,
            "outer_accuracy": args.outer_acc,
            "outer_n": args.outer_n,
        },
        n_train=args.n_train,
        feature_lineage=args.lineage,
        feature_freeze_id=args.freeze_id,
        promoted=False,
    )
    result = human_promote(card, confirm=args.confirm, reviewer=args.reviewer)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
