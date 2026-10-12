"""Exact Office8 adapter for the frozen CMR-LTL Office10 factor model.

JSON inputs and the monitor compiler are byte-preserved from CMR-LTL
dad230c2f54d9d5eb85d5e8dfd01e2d6c229afbc (MIT). This adapter maps symbolic
values to the kernel's integer domains; it does not use Office exact_backend.
Office8 means D1--D8, not eight factors.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from importlib.resources import files
import hashlib
import json
from typing import Mapping, Sequence

from .vendor.ecc_p1.model import BuchiAutomaton, FormalAction, FormalFactorizedModel, State
from .vendor.office_monitor_dsl import _compile_monitor, _formula_propositions

SOURCE_COMMIT = "dad230c2f54d9d5eb85d5e8dfd01e2d6c229afbc"
SOURCE_REPOSITORY = "https://github.com/yhl4/CMR-LTL"
FAMILY_PRIOR = frozenset({0, 1, 2, 3})
OFFICE8_QUERY_IDS = tuple(f"D{i}" for i in range(1, 9))
ASSET_SHA256 = {
    "office_model.json": "8721d884aef3f24cb3e4969c2ea04aa089661578426c20b1732971cb87a5611e",
    "office_task_manifest.json": "2d60b53e54e939c92bbd68317aeed2eb9ca2fb83e0ff2223f28e6d2d180a673c",
}


def _load_asset(name: str) -> dict:
    data = files(__package__).joinpath("assets", name).read_bytes()
    if hashlib.sha256(data).hexdigest() != ASSET_SHA256[name]:
        raise ValueError(f"frozen Office source asset changed: {name}")
    return json.loads(data)


@dataclass(frozen=True)
class OfficeQuery:
    model: FormalFactorizedModel
    query_id: str
    hard_task: str
    task: Mapping
    dimension_names: tuple[str, ...]
    value_names: tuple[tuple[str, ...], ...]
    dimension_meanings: tuple[str, ...]
    family_prior: frozenset[int] = FAMILY_PRIOR

    def decode_state(self, state: Sequence[int]) -> tuple[str, ...]:
        """Return named values without discarding repeated lasso states."""
        encoded = _encode_initial(state, self.dimension_names, self.value_names)
        return tuple(values[value] for values, value in zip(self.value_names, encoded))

    @property
    def state_schema(self) -> tuple[dict, ...]:
        return tuple({"id": i, "name": name, "values": list(values), "meaning": meaning}
                     for i, (name, values, meaning) in enumerate(zip(
                         self.dimension_names, self.value_names, self.dimension_meanings)))

    @property
    def initial_named_state(self) -> dict[str, str]:
        if len(self.model.initial_states) != 1:
            raise ValueError("Office snapshot requires exactly one initial state")
        return dict(zip(self.dimension_names, self.decode_state(next(iter(self.model.initial_states)))))


def _encode_initial(initial_state, names, domains) -> State:
    if isinstance(initial_state, Mapping):
        if set(initial_state) != set(names):
            raise ValueError("Office initial snapshot must name all ten dimensions exactly")
        try:
            return tuple(domain.index(initial_state[name]) for name, domain in zip(names, domains))
        except ValueError as exc:
            raise ValueError("Office initial snapshot contains an unknown named value") from exc
    if isinstance(initial_state, (str, bytes)) or not isinstance(initial_state, Sequence):
        raise TypeError("Office initial snapshot must be a full named mapping or integer sequence")
    state = tuple(initial_state)
    if len(state) != len(names) or any(type(value) is not int for value in state):
        raise ValueError("Office initial snapshot must contain ten integer values")
    if any(value not in range(len(domain)) for value, domain in zip(state, domains)):
        raise ValueError("Office initial snapshot contains an out-of-domain integer")
    return state


def _compile_guard(node, positions, encodings):
    op = node[0]
    if op == "true":
        return lambda state: True
    if op == "and":
        children = tuple(_compile_guard(child, positions, encodings) for child in node[1:])
        return lambda state: all(predicate(state) for predicate in children)
    index = positions[node[1]]
    if op == "in":
        values = frozenset(encodings[index][value] for value in node[2])
        return lambda state: state[index] in values
    value = encodings[index][node[2]]
    if op == "eq":
        return lambda state: state[index] == value
    if op == "ne":
        return lambda state: state[index] != value
    raise ValueError(f"unsupported Office guard: {node!r}")


def load_office_query(query_id: str = "D2", initial_state=None) -> OfficeQuery:
    """Load D1--D8 from the frozen manifest and an optional exact full snapshot.

    FULL, AP and FAMILY pass this same model to engine.plan; only their initial
    precision differs. The fixed family prior is r,p,d,b. Constant action costs
    remain Fraction values and CostSupp is mapped separately from Read/Write.
    """
    if query_id not in OFFICE8_QUERY_IDS:
        raise ValueError(f"Office8 query must be one of {OFFICE8_QUERY_IDS}; got {query_id!r}")
    raw = _load_asset("office_model.json")
    task = next(task for task in _load_asset("office_task_manifest.json")["tasks"]
                if task["id"] == query_id)
    names = tuple(raw["factor_order"])
    if tuple(factor["id"] for factor in raw["factors"]) != names:
        raise ValueError("Office factor order does not match dimension metadata")
    domains = tuple(tuple(factor["domain"]) for factor in raw["factors"])
    meanings = tuple(factor["meaning"] for factor in raw["factors"])
    positions = {name: i for i, name in enumerate(names)}
    encodings = tuple({value: i for i, value in enumerate(domain)} for domain in domains)
    propositions = task["atomic_propositions"]
    if len(propositions) != len(set(propositions)) or set(propositions) != set(_formula_propositions(task["formula_ast"])):
        raise ValueError("Office formula AST/atomic proposition mismatch")
    aps = []
    for ap in propositions:
        parts = ap.split("=")
        if len(parts) != 2 or parts[0] not in positions:
            raise ValueError(f"invalid Office atomic proposition: {ap!r}")
        index = positions[parts[0]]
        if parts[1] not in encodings[index]:
            raise ValueError(f"invalid Office atomic proposition: {ap!r}")
        aps.append((ap, index, encodings[index][parts[1]]))
    if (any(type(d) is not int for d in task["AP_S"])
            or len(task["AP_S"]) != len(set(task["AP_S"]))
            or set(task["AP_S"]) != {index for _, index, _ in aps}):
        raise ValueError("Office formula AST/AP support mismatch")
    aps = tuple(aps)
    actions = []
    for action in raw["actions"]:
        assignments = tuple((positions[name], encodings[positions[name]][value])
                            for name, value in action["assignments"].items())
        def effect(state, assignments=assignments):
            target = list(state)
            for index, value in assignments:
                target[index] = value
            return tuple(target)
        cost = action["cost"]
        if type(cost) is not int:
            raise TypeError("frozen Office action costs must remain exact integer values")
        exact_cost = Fraction(cost)
        read = frozenset(positions[name] for name in action["Read"])
        write = frozenset(positions[name] for name in action["Write"])
        cost_support = frozenset(positions[name] for name in action["CostSupp"])
        if write != {index for index, _ in assignments}:
            raise ValueError(f"Office Write/assignments mismatch for {action['id']}")
        if read | write | cost_support != frozenset(positions[name] for name in action["K"]):
            raise ValueError(f"Office support metadata mismatch for {action['id']}")
        actions.append(FormalAction(action["id"], read, write, cost_support,
                                    _compile_guard(action["guard"], positions, encodings), effect,
                                    lambda source, target, cost=exact_cost: cost))
    monitor = _compile_monitor(task["formula_ast"])
    buchi = BuchiAutomaton(monitor.initial, frozenset(monitor.accepting),
                          lru_cache(maxsize=None)(monitor.transition))
    def label(state):
        return frozenset(ap for ap, index, value in aps if state[index] == value)
    initial = _encode_initial(raw["initial_state"] if initial_state is None else initial_state, names, domains)
    model = FormalFactorizedModel(
        tuple(range(len(names))), tuple(tuple(range(len(domain))) for domain in domains),
        frozenset({initial}), tuple(sorted(actions, key=lambda action: action.name)),
        label, buchi, frozenset(propositions),
        {ap: frozenset({index}) for ap, index, _ in aps})
    return OfficeQuery(model, query_id, task["formula"], task, names, domains, meanings)


__all__ = ["OfficeQuery", "load_office_query", "FAMILY_PRIOR", "OFFICE8_QUERY_IDS",
           "SOURCE_COMMIT", "SOURCE_REPOSITORY", "ASSET_SHA256"]
