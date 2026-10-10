"""Unmodified AST source slices of frozen E2.2R1 generic monitor compiler."""
import json
from typing import Any, Iterable

class _Monitor:
    def __init__(self, initial: str, accepting: Iterable[str], transition):
        self.initial = initial
        self.accepting = set(accepting)
        self.transition = transition

def _freeze_formula(node: Any) -> Any:
    if isinstance(node, str):
        return node
    if isinstance(node, (list, tuple)) and node:
        return tuple(_freeze_formula(child) for child in node)
    raise ValueError(f"invalid frozen formula AST: {node!r}")

def _formula_subformulas(node: Any) -> set[Any]:
    if isinstance(node, str):
        return {node}
    result = {node}
    for child in node[1:]:
        result.update(_formula_subformulas(child))
    return result

def _formula_fairness_obligations(node: Any) -> tuple[Any, ...]:
    """Return strong eventuality obligations (F and Until) in stable order."""
    return tuple(sorted((subformula for subformula in _formula_subformulas(node)
                         if isinstance(subformula, tuple) and subformula[0] in {"F", "U"}),
                        key=repr))

def _generic_monitor(ast: Any) -> _Monitor:
    """Compile the frozen grammar by nondeterministic formula progression.

    A transition expands conjunctions in parallel and chooses one branch for
    disjunctions, Until, and Eventually.  The phase component is the standard
    generalized-Buchi-to-Buchi counter: every Until obligation must be
    discharged in round-robin order.  This preserves both a current Until
    candidate and a later candidate instead of committing to the first one.
    """
    root = _freeze_formula(ast)
    fairness = _formula_fairness_obligations(root)
    initial = None
    monitor = None

    def encode(obligations: frozenset[Any], phase: int, fulfilled: frozenset[Any], tick: bool) -> str:
        ordered = lambda values: sorted(values, key=repr)
        return json.dumps([ordered(obligations), phase, ordered(fulfilled), tick],
                          separators=(",", ":"))

    def decode(state: str) -> tuple[frozenset[Any], int, frozenset[Any], bool]:
        obligations, phase, fulfilled, tick = json.loads(state)
        def restore(value):
            if isinstance(value, list):
                return tuple(restore(child) for child in value)
            return value
        return (frozenset(restore(value) for value in obligations), int(phase),
                frozenset(restore(value) for value in fulfilled), bool(tick))

    def expand(node: Any, label: frozenset[str]) -> tuple[tuple[frozenset[Any], frozenset[Any]], ...]:
        if isinstance(node, str):
            return ((frozenset(), frozenset()),) if node in label else ()
        op, *args = node
        if op == "not":
            if not isinstance(args[0], str):
                raise ValueError("R5 frozen grammar permits negation only on atoms")
            return ((frozenset(), frozenset()),) if args[0] not in label else ()
        if op == "X":
            return ((frozenset({args[0]}), frozenset()),)
        if op == "or":
            return tuple(choice for child in args for choice in expand(child, label))
        if op == "and":
            choices = ((frozenset(), frozenset()),)
            for child in args:
                combined = []
                for left_next, left_done in choices:
                    for right_next, right_done in expand(child, label):
                        combined.append((left_next | right_next, left_done | right_done))
                choices = tuple(combined)
            return choices
        if op == "F":
            fulfilled = frozenset({node})
            return tuple((next_obligations, done | fulfilled)
                          for next_obligations, done in expand(args[0], label)) \
                + ((frozenset({node}), frozenset()),)
        if op == "G":
            return tuple((next_obligations | frozenset({node}), fulfilled)
                          for next_obligations, fulfilled in expand(args[0], label))
        if op == "U":
            right_choices = tuple((next_obligations, fulfilled | frozenset({node}))
                                  for next_obligations, fulfilled in expand(args[1], label))
            left_choices = tuple((next_obligations | frozenset({node}), fulfilled)
                                 for next_obligations, fulfilled in expand(args[0], label))
            return right_choices + left_choices
        raise ValueError(f"unsupported frozen formula AST operator: {op!r}")

    def transition(state: str, label: frozenset[str]) -> tuple[str, ...]:
        obligations, phase, _previous_fulfilled, _previous_tick = decode(state)
        choices = ((frozenset(), frozenset()),)
        for obligation in sorted(obligations, key=repr):
            combined = []
            for left_next, left_done in choices:
                for right_next, right_done in expand(obligation, label):
                    combined.append((left_next | right_next, left_done | right_done))
            choices = tuple(combined)
        successors = set()
        for next_obligations, fulfilled in choices:
            next_phase = phase
            tick = False
            if fairness:
                for _ in range(len(fairness)):
                    current = fairness[next_phase]
                    if current in next_obligations and current not in fulfilled:
                        break
                    next_phase = (next_phase + 1) % len(fairness)
                    if next_phase == 0:
                        tick = True
                # Once no strong eventuality remains pending, the fairness
                # bookkeeping is no longer part of the formula state.  Fold
                # it to one accepting canonical state so a one-edge lasso
                # does not pay for an artificial monitor-counter cycle.
                if not any(item in next_obligations for item in fairness):
                    next_phase = 0
                    fulfilled = frozenset()
                    tick = True
            successor = encode(next_obligations, next_phase, fulfilled, tick)
            successors.add(successor)
            if not fairness or tick:
                monitor.accepting.add(successor)
        return tuple(sorted(successors))

    monitor = _Monitor(encode(frozenset({root}), 0, frozenset(), False), set(), transition)
    initial = monitor.initial
    # Discover the finite monitor language over all valuations before it is
    # handed to the product builder, so accepting membership is immutable in
    # practice and conjunctions do not observe a partially built acceptance set.
    atoms = sorted(value for value in _formula_subformulas(root) if isinstance(value, str))
    valuations = [frozenset(atom for index, atom in enumerate(atoms) if mask & (1 << index))
                  for mask in range(1 << len(atoms))]
    seen = {initial}
    queue = [initial]
    while queue:
        current = queue.pop()
        for label in valuations:
            for successor in transition(current, label):
                if successor not in seen:
                    seen.add(successor)
                    queue.append(successor)
    return monitor

def _compile_monitor(ast: Any) -> _Monitor:
    return _generic_monitor(ast)

def _formula_propositions(ast: Any) -> frozenset[str]:
    """Extract AP_phi from the already parsed frozen formula AST."""
    if isinstance(ast, str):
        return frozenset({ast})
    if not isinstance(ast, list) or not ast:
        raise ValueError(f"invalid frozen formula AST: {ast!r}")
    propositions: set[str] = set()
    for child in ast[1:]:
        propositions.update(_formula_propositions(child))
    return frozenset(propositions)
