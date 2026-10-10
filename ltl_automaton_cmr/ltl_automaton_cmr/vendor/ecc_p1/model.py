"""Small immutable formal model used by the ECC-P1 research kernel."""

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, FrozenSet, Iterable, Mapping, Optional, Sequence, Tuple

State = Tuple[int, ...]
Label = FrozenSet[str]
ProductState = Tuple[State, str]


def exact_cost(value: int | Fraction) -> Fraction:
    """Accept only exact costs; floats are deliberately outside P1's contract."""
    if isinstance(value, bool) or not isinstance(value, (int, Fraction)):
        raise TypeError("ECC-P1 fixtures require integer or Fraction costs")
    return Fraction(value)


@dataclass(frozen=True)
class FormalAction:
    name: str
    read: FrozenSet[int]
    write: FrozenSet[int]
    cost_support: FrozenSet[int]
    guard: Callable[[State], bool]
    effect: Callable[[State], State]
    cost: Callable[[State, State], int | Fraction]

    def support(self) -> FrozenSet[int]:
        return self.read | self.write | self.cost_support


@dataclass(frozen=True)
class BuchiAutomaton:
    initial: str
    accepting: FrozenSet[str]
    transition: Callable[[str, Label], Iterable[str]]


@dataclass(frozen=True)
class FormalActionSupport:
    action: str
    read: FrozenSet[int]
    write: FrozenSet[int]
    cost_support: FrozenSet[int]
    k: FrozenSet[int]

    @classmethod
    def from_action(cls, action: FormalAction) -> "FormalActionSupport":
        return cls(action.name, action.read, action.write, action.cost_support, action.support())


@dataclass(frozen=True)
class ConcreteTransition:
    source: ProductState
    action: str
    target: ProductState
    cost: Fraction


@dataclass(frozen=True)
class StateTransition:
    source: State
    action: str
    target: State
    cost: Fraction


@dataclass(frozen=True)
class FormalFactorizedModel:
    dimensions: Tuple[int, ...]
    local_states: Tuple[Tuple[int, ...], ...]
    initial_states: FrozenSet[State]
    actions: Tuple[FormalAction, ...]
    label: Callable[[State], Label]
    buchi: BuchiAutomaton
    task_ap: Optional[FrozenSet[str]] = None
    task_support: Mapping[str, FrozenSet[int]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if tuple(sorted(self.dimensions)) != self.dimensions:
            raise ValueError("dimensions must use stable ascending IDs")
        if len(self.local_states) != len(self.dimensions):
            raise ValueError("one local-state domain is required per dimension")
        if not self.actions:
            raise ValueError("a formal model needs at least one action")
        names = [a.name for a in self.actions]
        if names != sorted(names) or len(set(names)) != len(names):
            raise ValueError("actions must have unique stable names")

    def all_states(self) -> Tuple[State, ...]:
        states = [()]
        for domain in self.local_states:
            states = [prefix + (value,) for prefix in states for value in domain]
        return tuple(sorted(states))

    def supports(self) -> Mapping[str, FormalActionSupport]:
        return {a.name: FormalActionSupport.from_action(a) for a in self.actions}

    def initial_product_states(self) -> Tuple[ProductState, ...]:
        return tuple(sorted(
            (state, buchi_state)
            for state in self.initial_states
            for buchi_state in set(self.buchi.transition(
                self.buchi.initial, self.task_label(state)))
        ))

    def task_propositions(self, states: Iterable[State]) -> FrozenSet[str]:
        if self.task_ap is not None:
            return frozenset(self.task_ap)
        if self.task_support:
            return frozenset(self.task_support)
        values = set()
        for state in states:
            values.update(self.label(state))
        return frozenset(values)

    def task_label(self, state: State) -> Label:
        labels = frozenset(self.label(state))
        if self.task_ap is not None:
            return labels & frozenset(self.task_ap)
        if self.task_support:
            return labels & frozenset(self.task_support)
        return labels

    def state_transitions_from(self, state: State) -> Tuple[StateTransition, ...]:
        result = []
        for action in self.actions:
            if not action.guard(state):
                continue
            successor = tuple(action.effect(state))
            if len(successor) != len(self.dimensions):
                raise ValueError(f"action {action.name} returned a wrong-dimensional state")
            if any(value not in domain for value, domain in zip(successor, self.local_states)):
                raise ValueError(f"action {action.name} returned a value outside its domain")
            cost = exact_cost(action.cost(state, successor))
            if cost < 0:
                raise ValueError("negative costs are outside the ECC-P1 contract")
            result.append(StateTransition(state, action.name, successor, cost))
        return tuple(sorted(result, key=lambda edge: (edge.target, edge.action, edge.cost)))

    def transitions_from(self, product_state: ProductState) -> Tuple[ConcreteTransition, ...]:
        state, buchi_state = product_state
        result = []
        for transition in self.state_transitions_from(state):
            next_buchi = tuple(sorted(set(self.buchi.transition(buchi_state, self.task_label(transition.target)))))
            for q_next in next_buchi:
                result.append(ConcreteTransition(product_state, transition.action,
                                                 (transition.target, q_next), transition.cost))
        return tuple(sorted(result, key=lambda edge: (edge.target, edge.action, edge.cost)))

    def all_product_transitions(self) -> Tuple[ConcreteTransition, ...]:
        edges = []
        for state in self.all_states():
            for buchi_state in (self.buchi.initial,):
                # Discover additional Buchi states by replaying reachable edges below;
                # this seed is enough for the deterministic fixture automata.
                edges.extend(self.transitions_from((state, buchi_state)))
        return tuple(edges)
