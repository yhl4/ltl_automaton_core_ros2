"""Per-attempt full-transition-system reuse for the V8 AP experiment.

The V6 grouped builder is cloned with a private ``_reachable_full_ts`` global.
Only the immutable full-state/edge tuples are reused; reduction, Buchi Product,
and all returned objects are rebuilt by the cloned V6 function on every call.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional

from experiments.cmr_ros2_product_perf import builder as v6_builder
from experiments.cmr_ros2_real.bound_runner import _clone_function


class FullTSContext:
    """One-model, one-attempt cache for the full reachable TS.

    A context is intentionally single-use after :meth:`close`.  Model identity
    is checked with ``is`` so equal-shaped or equal-valued models cannot share a
    cache accidentally.
    """

    def __init__(self, model):
        self.model = model
        self._states: tuple[Any, ...] | None = None
        self._edges: tuple[Any, ...] | None = None
        self._closed = False
        self._calls = 0
        self._hits = 0
        self._build = _clone_function(
            v6_builder.build_optimistic_abstraction,
            {"_reachable_full_ts": self._reachable_full_ts},
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def cached(self) -> bool:
        return self._states is not None

    def _reachable_full_ts(self, model):
        if self._closed:
            raise RuntimeError("FullTSContext is closed")
        if model is not self.model:
            raise ValueError("FullTSContext cannot accept a different model")
        if self._states is not None:
            self._hits += 1
            return self._states, self._edges
        # Count the authority call before entering it.  A raised call is still
        # real work, while the cache is published only after both tuples exist.
        self._calls += 1
        states, edges = v6_builder._reachable_full_ts(model)
        states = tuple(states)
        edges = tuple(edges)
        self._states = states
        self._edges = edges
        return states, edges

    def build_optimistic_abstraction(
        self,
        model,
        precision: Iterable[int],
        *,
        timing: Optional[dict[str, Any]] = None,
        work: Optional[dict[str, Any]] = None,
    ):
        if self._closed:
            raise RuntimeError("FullTSContext is closed")
        if model is not self.model:
            raise ValueError("FullTSContext cannot accept a different model")
        if work is None:
            work = {}
        calls_before, hits_before = self._calls, self._hits
        try:
            return self._build(model, precision, timing=timing, work=work)
        finally:
            # This also records rejected precision, failed TS construction, and
            # failed reduction without reusing a previous build's lookup.
            work["full_ts_rebuild_calls"] = self._calls - calls_before
            work["full_ts_cache_hits"] = self._hits - hits_before
            work["full_ts_callback_calls"] = (
                self._calls - calls_before + self._hits - hits_before)
            work["full_ts_source_states"] = len(self._states or ())
            work["full_ts_source_edges"] = len(self._edges or ())

    build = build_optimistic_abstraction

    def close(self) -> None:
        if self._closed:
            return
        self._states = None
        self._edges = None
        self.model = None
        self._closed = True


def build_optimistic_abstraction(model, precision, *, context: FullTSContext,
                                 timing=None, work=None):
    """Explicit-context adapter for callers that expect a module function."""
    if not isinstance(context, FullTSContext):
        raise TypeError("context must be FullTSContext")
    return context.build_optimistic_abstraction(model, precision,
                                                timing=timing, work=work)
