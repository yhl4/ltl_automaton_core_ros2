import json, sys
from pathlib import Path
from experiments.cmr_ros2_search_entry import dds, runner
checks=[]
for root_text in sys.argv[1:]:
    root=Path(root_text); plan=runner.load_plan(root/'plan/plan.json')
    entry=runner.VerifiedEntry(plan, runner.source_closure, runner.schema_for)
    cells=dds._fixed_cells(plan)
    for key, cell in cells.items():
        request_id='check-'+key[0]+'-'+key[1]
        request=runner.request_for(plan, entry, cell, 'ros2-v7')
        request['request_id']=request_id
        record=next(r for r in plan['records'] if r['instance_id']==key[0])
        expected=dds._request_envelope(cell, entry.describe('ros2-v7'), plan['qualification_id'], plan['scope'], plan['execution_identity'], request_id, instance_sha256=record['instance_sha256'])
        dds._require_exact_envelope(request, expected)
        entry.validate_request({k:v for k,v in request.items() if k!='request_id'})
        checks.append({'root':str(root),'cell':list(key),'instance_sha256':record['instance_sha256'],'status':'PASSED'})
print(json.dumps({'status':'PASSED','checks':checks,'count':len(checks)},sort_keys=True))