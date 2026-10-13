import json,sys
p=sys.argv[1]
r=json.load(open(p))
for c in r['cases']:
    result=c.get('driver',{}).get('result',{})
    print(json.dumps({'instance_id':c['request']['instance_id'],'method':c['request']['method'],'status':c['status'],'worker_exitcode':result.get('worker_exitcode'),'objective':result.get('objective'),'certificate_replay':c.get('certificate_replay',{}).get('status'),'actions':c.get('driver',{}).get('commands'),'completion_count':c.get('driver',{}).get('completion_count'),'abstraction_feedback_count':c.get('driver',{}).get('abstraction_feedback_count'),'T_total':result.get('T_total')},sort_keys=True))
