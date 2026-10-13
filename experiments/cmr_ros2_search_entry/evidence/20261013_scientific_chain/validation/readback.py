from pathlib import Path
import json,hashlib,zipfile,subprocess
root=Path('/tmp/cmr_v7_scientific_replay_20261013_r2')
prior=Path('/tmp/cmr_v7_scientific_replay_20261013_r1')
repo=Path('/tmp/cmr_v7_scientific_source_3ae2a57_20261013_r2')
read=lambda p:json.loads(p.read_bytes())
raw=lambda v:(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
sha=lambda b:hashlib.sha256(b).hexdigest()
r=read(root/'scientific_chain_report.json');binding=read(root/'replay_binding.json')
assert r['status']=='PASSED' and r['scope']=='CMR_V7_REAL_SCIENTIFIC_PUBLICATION_REPLAY_ONLY'
assert r['new_method_workers']==r['planner_calls']==r['provider_calls']==r['dds_calls']==0
assert r['formal_campaign'] is False and r['default_changed'] is False
assert r['original_campaign_constructor']==r['worker_routing']=='UNRUN'
assert r['full_formal_campaign']=='UNVERIFIED' and r['version_binding']['version_binding_id']=='CMR_SEARCH_ENTRY_V1-888c808d63103337'
assert r['published']==r['restored']==3 and r['objectives']==['12','15','12']
assert r['positive_verifier_calls']==6 and r['rejected_certificate_calls']==1
calls=r['independent_verifier_calls'];assert len(calls)==7
assert calls[0]['status']=='REJECTED_EXCEPTION' and 'recomputed objective' in calls[0]['error']
assert all(c['status']=='PASS' for c in calls[1:])
for c in calls:assert sha(Path(c['path']).read_bytes())==c['expected_sha256']
for p,h in r['source_hashes'].items():assert sha(Path(p).read_bytes())==h
assert sha((root/'replay_binding.json').read_bytes())==r['replay_binding_sha256']
archive=repo/'experiments/cmr_ros2_search_entry/evidence/20261013_audit_real/raw_attempts.zip'
assert sha(archive.read_bytes())==r['source_archive_sha256']
with zipfile.ZipFile(archive) as z:
    inputs=json.loads(z.read('frozen_inputs_before.json'))
    for p,x in inputs.items():
        data=Path(p).read_bytes();assert len(data)==x['size'] and sha(data)==x['sha256'],p
    plan=json.loads(z.read('plan.json'));previous=None
    assert len(plan['source_closure'])==56
    for p,h in plan['source_closure'].items():assert sha(z.read('frozen_adapter/'+p))==h
    for c in binding['cells']:
        prefix=c['instance_id']+'_'+c['method']+'/ros2-v7/'
        original=json.loads(z.read(prefix+'result.json'))['row']
        folder=root/'completed'/c['cell_id'];row=read(folder/'validated_result.json')
        assert row==original and (folder/'validated_result.json').read_bytes()==raw(original)
        assert (folder/'rounds.jsonl').read_bytes()==b''.join(raw(rr) for rr in original['rounds'])
        assert (folder/'certificate.json').read_bytes()==z.read(prefix+'certificates/'+original['certificate_path'])
        record,body=read(folder/'pilot_record.json'),read(folder/'ledger_entry.json')
        assert record['worker_result']==original and record['replay_scope']==r['scope']
        assert record['execution_binding_sha256']==r['replay_binding_sha256']
        assert record['execution_identity_sha256']==c['execution_identity_sha256']
        assert record['source_version_binding']==r['version_binding'] and record['P2e_publication_gate']['status']=='PASS'
        assert body['previous_ledger_sha256']==previous
        assert record['ledger_commit_sha256']==sha(raw(body))
        assert body['record_payload_sha256']==sha(raw({k:v for k,v in record.items() if k!='ledger_commit_sha256'}))
        for name,h in read(folder/'commit_manifest.json').items():assert sha((folder/name).read_bytes())==h
        for name,h in body['validated_input_file_hashes'].items():assert sha((folder/name).read_bytes())==h
        previous=record['ledger_commit_sha256']
assert len(r['negative_checks'])==4
for name,x in r['negative_checks'].items():assert read(root/(name+'_rejection.json'))==x and x['status']=='REJECTED'
poison=root/'stale_restore/completed'/binding['cells'][0]['cell_id']
for name,h in read(poison/'commit_manifest.json').items():assert sha((poison/name).read_bytes())==h
record,body=read(poison/'pilot_record.json'),read(poison/'ledger_entry.json')
assert record['ledger_commit_sha256']==sha(raw(body)) and body['record_payload_sha256']==sha(raw({k:v for k,v in record.items() if k!='ledger_commit_sha256'}))
assert read(poison/'validated_result.json')['version_binding_id']=='STALE-V7-VERSION'
fatal=read(prior/'fatal.json')
assert fatal['status']=='FAILED' and not (prior/'completed').exists()
assert 'certificate_verifier_initial_label_v1.py' in fatal['traceback'] and 'certificate objective does not match recomputed objective' in fatal['traceback']
assert fatal['forbidden_method_calls']==0 and fatal['verifier_calls']==[]
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()=='3ae2a579ec5493c0c84bc042ff2c2b6391ad040b'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True)
assert sha((repo/'experiments/cmr_ros2_search_entry/scientific_chain_v7.py').read_bytes())==r['helper_sha256']
assert subprocess.check_output(['git','rev-parse','cmr-v7-baseline-00fc5a9^{commit}'],cwd=repo,text=True).strip()=='00fc5a91383b24f85d33aa81682af22e531234cf'
summary=dict(status='PASSED',original_rows=3,original_certificates=3,published=3,restored=3,positive_verifier_calls=6,current_rejected_verifier_calls=1,prior_unrecorded_negative_verifier_call=1,total_verifier_calls_across_attempts=8,new_method_workers=0,frozen_inputs=60,archived_source_closure=56,negative_checks=4,formal_campaign=False)
(root/'scientific_chain_readback.json').write_bytes(raw(summary))
print(json.dumps(summary))