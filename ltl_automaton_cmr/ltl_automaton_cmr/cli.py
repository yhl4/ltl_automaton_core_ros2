"""Offline command line for one CMR request; no ROS or network is required."""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import sys

from .engine import CertificationError, plan


def _load_factory(specification):
    module_name, separator, callable_name = specification.partition(":")
    if not separator or not module_name or not callable_name:
        raise ValueError("model factory must be module:callable")
    factory = getattr(importlib.import_module(module_name), callable_name)
    if not callable(factory):
        raise TypeError("model factory is not callable")
    return factory()


def _prior(text):
    return tuple(int(value.strip()) for value in text.split(",") if value.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Plan one request through the frozen exact CMR kernel.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--office-query", metavar="ID",
                        help="frozen Office query, default D2")
    source.add_argument("--model-factory", metavar="MODULE:CALLABLE",
                        help="trusted zero-argument factory returning a formal model")
    parser.add_argument("--arm", choices=("FULL", "AP", "FAMILY"), default="AP")
    parser.add_argument("--family-prior", metavar="IDS",
                        help="comma-separated frozen RF; Office defaults to 0,1,2,3")
    parser.add_argument("--output", type=Path,
                        help="save the exact plan and per-round records as JSON")
    args = parser.parse_args(argv)

    try:
        if args.model_factory:
            source_model = _load_factory(args.model_factory)
        else:
            from .office import load_office_query
            source_model = load_office_query(args.office_query or "D2")
        model = getattr(source_model, "model", source_model)
        prior = (
            _prior(args.family_prior) if args.family_prior is not None
            else getattr(source_model, "family_prior", ())
        )
        result = plan(model, arm=args.arm, family_prior=prior)
        record = result.to_dict()
        if hasattr(source_model, "task"):
            record["query"] = {
                "id": source_model.task["id"],
                "formula": source_model.task["formula"],
            }
        return_code = 0 if result.status == "OPTIMALITY_CERTIFIED" else 1
    except CertificationError as error:
        record = error.to_dict()
        return_code = 2
    except (ValueError, TypeError, ImportError, AttributeError) as error:
        record = {
            "schema": "ltl-automaton-cmr-plan-v1",
            "status": "MODEL_ERROR",
            "error": str(error),
        }
        return_code = 2

    payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.write(payload)
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
