"""One directed final-precision solve; not a method or campaign timing result."""
import cProfile
import hashlib
import json
from pathlib import Path
import pstats
import subprocess
import sys
import time
import tracemalloc

source = Path('/tmp/cmr_v10_source_7a3ddc1_20261022')
assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip() == '7a3ddc1d0b8ed22fb75c069085b8ffa3ff357ffc'
assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip()
sys.path.insert(0, str(source))
from experiments.cmr_ros2_suffix_reuse import runner
from experiments.cmr_ros2_reduction_reuse.builder import FullTSContext
from experiments.cmr_ros2_suffix_reuse.search import solve_cmr_lasso
from ltl_automaton_planner_core.ltl_tools import discrete_plan

out = Path('/mnt/c/Users/Yuhling/.codex/worktrees/v7-audit-dds-regression/v11_hotspot_20261023')
output = out / 'profile_search.json'
if output.exists():
    raise ValueError('directed diagnostic output already exists')
plan = runner.load_plan(Path('/tmp/cmr_v10_suffix_reuse_7a3ddc1_20261022/plan.json'))
receipt = runner.adapter._native_path(plan['authority_receipt'])
kernel = Path('/mnt/c/Users/Yuhling/.codex/worktrees/cmr-p1b-initial-label/Robotics4LLM/ltl_planning_studio/ecc_p1_formal_kernel')
formal, bound, manifest, records = runner.original.authority(plan, receipt, kernel)
instance = formal.load_instance(records['C3-T4'], benchmark_root=runner.adapter._native_path(bound['benchmark_root']))
context = FullTSContext(instance.model)
try:
    abstract = context.build(instance.model, instance.model.dimensions, work={})
finally:
    context.close()

profile = cProfile.Profile()
work = {}
tracemalloc.start()
started = time.perf_counter_ns()
result = profile.runcall(solve_cmr_lasso, abstract, work=work)
elapsed = time.perf_counter_ns() - started
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
assert elapsed < 180_000_000_000
assert result is not None and result.lower_bound == 12
stats = pstats.Stats(profile)
rows = [dict(file=k[0], line=k[1], name=k[2], primitive_calls=v[0], calls=v[1], self_seconds=v[2], cumulative_seconds=v[3]) for k, v in stats.stats.items()]
value = dict(schema='cmr-v11-directed-search-profile-v1', status='PASSED', source_commit=plan['source_head'], source_closure=plan['source_closure'], instance='C3-T4', precision=list(instance.model.dimensions), scope='one final-precision abstract solve only; no method T_total or speedup claim', solver_calls=1, real_cmr_workers=0, verifier_calls=0, dds_requests=0, provider_calls=0, formal_campaign=False, tracemalloc=True, elapsed_ns=elapsed, peak_tracemalloc_bytes=peak, objective=str(result.lower_bound), product_states=len(abstract.states), product_edges=len(abstract.transitions), search_work=work, discrete_plan_path=str(discrete_plan.__file__), discrete_plan_sha256=hashlib.sha256(Path(discrete_plan.__file__).read_bytes()).hexdigest(), functions=sorted(rows, key=lambda r:r['cumulative_seconds'], reverse=True))
output.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')
profile.dump_stats(str(out / 'profile_search.pstats'))
print(json.dumps({k:v for k,v in value.items() if k not in ('functions','source_closure','search_work')}, sort_keys=True))
print(json.dumps(value['functions'][:22], sort_keys=True))
