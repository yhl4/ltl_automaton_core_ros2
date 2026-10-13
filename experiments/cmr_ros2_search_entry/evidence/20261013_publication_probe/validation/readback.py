from pathlib import Path
import hashlib,json,subprocess
root=Path(r'\\wsl.localhost\Ubuntu-22.04-D\tmp\cmr_v7_publication_probe_20261013_r1')
repo=Path(r'C:\Users\Yuhling\.codex\worktrees\v7-audit-dds-regression\ltl_automaton_core-ros2')
sha=lambda b:hashlib.sha256(b).hexdigest()
raw=lambda v:(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
read=lambda p:json.loads(p.read_bytes())
def native(s):
    if s.startswith('/mnt/'):return Path(s[5].upper()+':/'+s[7:])
    if s.startswith('/tmp/'):return Path(r'\\wsl.localhost\Ubuntu-22.04-D')/s.lstrip('/')
    return Path(s)
r=read(root/'publication_report.json')
assert r['status']=='PASSED' and r['scope']=='SYNTHETIC_PUBLICATION_ONLY'
assert r['calls']==dict(external_process=0,kernel_loader=0,network=0)
assert r['formal_campaign'] is False and r['real_results']==0
assert r['formal_campaign_chain']=='UNVERIFIED'
for key in ('formal_campaign_driver_execution','full_Campaign_restore_receipts','scientific_gate','certificate_replay'):assert r[key]=='UNRUN'
assert r['functions_invoked']=={'coordinator.Campaign.receipt':5,'driver._BASE.run_cell':1,'driver._read_committed':6,'driver.atomic_publish':4}
assert r['published']==r['linked_receipts']==2 and r['previous_links_checked']==1
for p,h in r['source_hashes'].items():assert sha(native(p).read_bytes())==h,p
source=native('/tmp/cmr_v7_failure_dds_chain_20261013_r2/offline_chain/synthetic_results.jsonl').read_bytes()
assert sha(source)==r['source_rows_sha256']
source_lines=source.splitlines(keepends=True)
previous=None
for i,c in enumerate(r['cells']):
    f=root/'completed'/c['cell_id'];manifest=read(f/'commit_manifest.json')
    assert len(manifest)==9 and len(list(f.iterdir()))==10
    for name,h in manifest.items():assert sha((f/name).read_bytes())==h
    b,record,row=read(f/'ledger_entry.json'),read(f/'pilot_record.json'),read(f/'validated_result.json')
    assert b['previous_ledger_sha256']==previous
    assert record['ledger_commit_sha256']==sha(raw(b))
    assert b['record_payload_sha256']==sha(raw({k:v for k,v in record.items() if k!='ledger_commit_sha256'}))
    assert all(record[k]==v for k,v in dict(r['version_binding'],**c).items())
    assert (f/'validated_result.json').read_bytes()==source_lines[i]==(root/f'source_row_{i}.jsonl').read_bytes()
    assert (f/'rounds.jsonl').read_bytes()==b''.join(raw(rr) for rr in row['rounds'])
    assert row['result_hash']==sha(raw({k:v for k,v in row.items() if k!='result_hash'}).rstrip(b'\n'))
    previous=record['ledger_commit_sha256']
assert len(r['negative_cases'])==10
for name,info in r['negative_cases'].items():assert read(root/'negative'/name/'rejection.json')==info and info['status']=='REJECTED'
stale=root/'negative/stale_v6/completed'/r['cells'][0]['cell_id']
for name,h in read(stale/'commit_manifest.json').items():assert sha((stale/name).read_bytes())==h
stale_record,stale_body=read(stale/'pilot_record.json'),read(stale/'ledger_entry.json')
assert stale_record['backend']=='ros2-v6' and stale_record['ledger_commit_sha256']==sha(raw(stale_body))
assert stale_body['record_payload_sha256']==sha(raw({k:v for k,v in stale_record.items() if k!='ledger_commit_sha256'}))
assert r['stale_v6_original_receipt']=='ACCEPTS_HASHES_ONLY' and r['stale_v6_wrapper']=='REJECTED'
assert r['negative_cases']['formal_v7_route']['error']=='backend hash mismatch'
assert not (root/'never_dispatched').exists()
helper=repo/'experiments/cmr_ros2_search_entry/publication_v7.py'
assert sha(helper.read_bytes())==r['helper_sha256']
assert subprocess.check_output(['git','show','90949079a77e26a36eceb1bd38a30b4858f1c3f8:experiments/cmr_ros2_search_entry/publication_v7.py'],cwd=repo)==helper.read_bytes()
plan=read(native('/tmp/cmr_v7_failure_dds_chain_20261013_r2/plan.json'))
assert len(plan['source_closure'])==56
for p,h in plan['source_closure'].items():assert sha((repo/p).read_bytes())==h
assert subprocess.check_output(['git','rev-parse','cmr-v7-baseline-00fc5a9^{commit}'],cwd=repo,text=True).strip()=='00fc5a91383b24f85d33aa81682af22e531234cf'
summary=dict(status='PASSED',published=2,linked_receipts=2,negative_cases=10,source_files=56,method_workers=0,certificate_verifier_calls=0,formal_campaign=False)
(root/'publication_readback.json').write_bytes(raw(summary))
print(json.dumps(summary))