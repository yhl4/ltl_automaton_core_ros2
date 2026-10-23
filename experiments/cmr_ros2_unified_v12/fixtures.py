"""Small binding/request and inherited exact-search qualification checks."""
import copy
import json
from pathlib import Path

from experiments.cmr_ros2_unified_v12 import runner


def run(plan_path, receipt, kernel, output):
    plan = runner.load_plan(plan_path)
    checks = []

    def reject(name, operation):
        try:
            operation()
        except (ValueError, TypeError, KeyError):
            checks.append(dict(name=name,status='REJECTED'))
        else:
            raise AssertionError('invalid boundary accepted: '+name)

    for name in runner.NAMES:
        for method in runner.METHODS:
            entry = runner.AttemptEntry(plan_path)
            cell = next(c for c in plan['cells'] if c['method']==method)
            request = entry.request(name,cell)
            entry.validate(plan,request,name)
            for field, value in (('backend','auto'),('method','UNKNOWN'),('instance_sha256','0'*64),
                                 ('execution_identity','stale'),('planner_budget_seconds',179),
                                 ('outer_watchdog_seconds',194),('backend_sha256','0'*64),
                                 ('version_binding_id','stale')):
                changed = dict(request);changed[field]=value
                reject(name+'_'+method+'_'+field,lambda:entry.validate(plan,changed,name))
            receipt_value = json.loads(runner.adapter._native_path(receipt).read_bytes())
            first = entry.schema(receipt_value,name)
            if first is not entry.schema(receipt_value,name):
                raise AssertionError('schema not reused in one attempt')
            altered = dict(receipt_value,fixture_changed=True)
            reject('receipt_change_'+name+'_'+method,lambda:entry.schema(altered,name))
            entry.release_check()
            checks.append(dict(name='selected_'+name+'_'+method,status='PASSED'))
    entry = runner.AttemptEntry(plan_path)
    reject('unknown_backend',lambda:entry.describe(entry.binding_path,'auto'))
    for name in runner.NAMES:
        formal,_,_,_ = runner.authority(plan,receipt,kernel)
        capture = entry.configure(formal,name,entry.binding_path)
        if any(capture[k]!=entry.describe(entry.binding_path,name)[k] for k in ('backend_id','backend_sha256')):
            raise AssertionError('configured identity differs')
        if not all(capture[k] for k in ('original_loop_code_preserved','original_local_code_preserved','original_builder_global_preserved')):
            raise AssertionError('frozen method code changed')
    arithmetic = None
    if plan['profile']=='main':
        from experiments.cmr_ros2_compact_cost import fixtures as previous
        arithmetic = previous.run(kernel)
    report = dict(schema='cmr-unified-v12-fixtures-v1',status='PASSED',checks=checks,
        execution_identity=plan['execution_identity'],version_binding_id=plan['version_binding_id'],
        version_binding_sha256=plan['version_binding_sha256'],inherited_arithmetic=arithmetic,
        real_workers=0,dds_requests=0,provider_calls=0)
    runner.write(Path(output),report)
    return report
