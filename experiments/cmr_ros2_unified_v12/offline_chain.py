"""Explicitly synthetic 510-row analysis and ledger checks; no real workers."""
import argparse
import ast
from pathlib import Path
from types import ModuleType, SimpleNamespace

from experiments.cmr_ros2_unified_v12 import runner


def run(args):
    plan = runner.load_plan(args.plan)
    if plan['profile'] != 'main':
        raise ValueError('offline population uses the normal qualification binding')
    path = runner.ROOT/'experiments/cmr_ros2_backend/offline_chain.py'
    tree = ast.parse(path.read_text(),filename=str(path))
    changes = []

    class Rebind(ast.NodeTransformer):
        def visit_Constant(self,node):
            values = {'ros2-v6':'ros2-v12',
                'CMR_UNIFIED_BACKEND_OFFLINE_CHAIN_V6':'CMR_UNIFIED_V12_SYNTHETIC_OFFLINE'}
            if isinstance(node.value,str) and node.value in values:
                changes.append(dict(line=node.lineno,old=node.value,new=values[node.value]))
                return ast.copy_location(ast.Constant(values[node.value]),node)
            return node

    tree = ast.fix_missing_locations(Rebind().visit(tree))
    if len(changes)!=6 or sum(c['old']=='ros2-v6' for c in changes)!=5:
        raise ValueError('frozen offline specialization boundary changed')
    module = ModuleType('cmr_unified_v12_synthetic_offline')
    module.__file__ = str(path)
    module.__package__ = 'experiments.cmr_ros2_backend'
    exec(compile(tree,str(path),'exec'),module.__dict__)
    module.load_backends = lambda:SimpleNamespace(describe=runner.describe,
        v6=SimpleNamespace(adapter=runner.adapter))
    report = module.qualify(args)
    report.update(specialization=changes,source_sha256=runner.v7.digest(path),
        harness_sha256=runner.v7.digest(Path(__file__)),real_results=0,
        source_execution_identity=plan['execution_identity'])
    runner.write(args.output/'offline_chain_evidence.json',report)
    return report


def main():
    parser = argparse.ArgumentParser()
    for key in ('plan','binding','version-binding','output'):
        parser.add_argument('--'+key,type=Path,required=True)
    args = parser.parse_args()
    run(args)


if __name__=='__main__':
    main()
