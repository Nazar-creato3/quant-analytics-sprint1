"""GA16-266: a failed robot-plan lookup must not leave a hit stop open."""
from __future__ import annotations

import pytest

from app.services.portfolio.barrier_close import robot_plan_blocks_barrier


class _BoomDb:
    async def execute(self, *_a, **_k):
        raise RuntimeError("robot_plans missing")


@pytest.mark.asyncio
async def test_robot_check_failure_does_not_block_stop() -> None:
    assert await robot_plan_blocks_barrier(_BoomDb(), "m1") is False  # type: ignore[arg-type]
