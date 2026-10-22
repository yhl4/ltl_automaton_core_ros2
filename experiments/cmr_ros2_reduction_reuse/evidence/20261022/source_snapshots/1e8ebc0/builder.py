"""V9 reduction adapter with per-build projection memoization."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional

from experiments.cmr_ros2_ap_ts_reuse.builder import (
    FullTSContext as _V8FullTSContext,
)
from experiments.cmr_ros2_product_perf import builder as _v6_builder
from experiments.cmr_ros2_real.bound_runner import _clone_function


class FullTSContext(_V8FullTSContext):
    """Reuse one full TS while keeping each precision reduction isolated."""

    def __init__(self, model, *, reuse_projection: bool = True):
        super().__init__(model)
        self.reuse_projection = bool(reuse_projection)
        self._projection_cache: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        self._projection_positions: tuple[int, ...] | None = None
        self._projection_work: dict[str, Any] | None = None
        self._build = _clone_function(
            _v6_builder.build_optimistic_abstraction,
            {
                "_reachable_full_ts": self._reachable_full_ts,
                "project_state": self._project_state,
            },
        )

    def _project_state(self, state, visible, dimensions):
        work = self._projection_work
        if work is None:
            raise RuntimeError("projection wrapper is outside a build")
        work["projection_requests"] += 1

        if not self.reuse_projection:
            work["projection_computations"] += 1
            work["position_map_builds"] += 1
            return _v6_builder.project_state(state, visible, dimensions)

        state_key = tuple(state)
        cached = self._projection_cache.get(state_key)
        if cached is not None:
            work["projection_cache_hits"] += 1
            return cached

        if self._projection_positions is None:
            position_by_dimension = {
                dimension: index
                for index, dimension in enumerate(dimensions)
            }
            self._projection_positions = tuple(
                position_by_dimension[dimension]
                for dimension in sorted(visible)
            )
            work["position_map_builds"] += 1

        projected = tuple(
            state[index] for index in self._projection_positions
        )
        self._projection_cache[state_key] = projected
        work["projection_computations"] += 1
        return projected

    def build_optimistic_abstraction(
        self,
        model,
        precision: Iterable[int],
        *,
        timing: Optional[dict[str, Any]] = None,
        work: Optional[dict[str, Any]] = None,
    ):
        if self.closed:
            raise RuntimeError("FullTSContext is closed")
        if model is not self.model:
            raise ValueError("FullTSContext cannot accept a different model")
        if work is None:
            work = {}
        work.update({
            "projection_requests": 0,
            "projection_computations": 0,
            "projection_cache_hits": 0,
            "position_map_builds": 0,
        })
        self._projection_cache = {}
        self._projection_positions = None
        self._projection_work = work
        try:
            return super().build_optimistic_abstraction(
                model,
                precision,
                timing=timing,
                work=work,
            )
        finally:
            self._projection_work = None

    build = build_optimistic_abstraction

    def close(self) -> None:
        self._projection_cache = {}
        self._projection_positions = None
        self._projection_work = None
        super().close()


def build_optimistic_abstraction(
    model,
    precision,
    *,
    context: FullTSContext,
    timing=None,
    work=None,
):
    """Build one precision through an explicit per-attempt context."""
    if not isinstance(context, FullTSContext):
        raise TypeError("context must be FullTSContext")
    return context.build(
        model,
        precision,
        timing=timing,
        work=work,
    )


__all__ = ["FullTSContext", "build_optimistic_abstraction"]
