import json,sys
r=json.load(open(sys.argv[1]))
ref=r['reference']['row']
print(json.dumps({'reference':{'instance_id':ref['instance_id'],'status':ref['terminal_status'],'objective':ref['objective'],'worker_exitcode':r['reference'].get('worker_exitcode'),'T_total':ref.get('T_total'),'certificate_verifier_status':ref.get('certificate_verifier_status')}},sort_keys=True))
for c in r['cases']:
 a=c['artifact']; d=a.get('driver') or {}; row=d.get('result') or {}; req=a.get('request',c.get('request',{}))
 print(json.dumps({'mode':c['mode'],'instance_id':req['instance_id'],'expected':c['expected_terminal'],'status':a['status'],'worker_exitcode':row.get('worker_exitcode'),'objective':row.get('objective'),'terminal_status':row.get('terminal_status'),'certificate_replay':(a.get('certificate_replay') or {}).get('status'),'commands':d.get('commands'),'completion_count':d.get('completion_count'),'T_total':row.get('T_total'),'right_censored':row.get('right_censored'),'timing_status':row.get('timing_status')},sort_keys=True))
