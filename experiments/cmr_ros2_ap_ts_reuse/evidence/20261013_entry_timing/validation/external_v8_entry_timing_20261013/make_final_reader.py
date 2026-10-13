"""Keep the intermediate readback intact and extend it for charged delivery."""
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'read_entry_timing_r1.py').read_text(encoding='utf-8')
source = source.replace("'/tmp/cmr_v8_entry_timing_20261013'", "'/tmp/cmr_v8_entry_timing_final_20261013'")
source = source.replace("'/tmp/cmr_v8_entry_source_111ae6c_20261013'", "'/tmp/cmr_v8_entry_source_eb5e689_20261013'")
source = source.replace("'111ae6c4e35a961c779ebf2d7bda9680bafd8798'", "'eb5e6896c763559def6ac65641bb902592dd9eda'")
source = source.replace("(OUT/'readback.json')", "(OUT/'readback_final.json')")
needle = "    assert (interval[1]-interval[0])/1e9==row['post_runner_delivery_seconds']\n"
assert source.count(needle) == 1
source = source.replace(needle, needle + """    checkpoint=pt['entry_timing']['delivery_checkpoint']
    assert interval[0] <= checkpoint['release_started_ns'] < checkpoint['release_completed_ns']
    assert checkpoint['release_completed_ns'] == row['terminal_completion_ns'] == interval[1]
    assert row['T_total'] == (row['terminal_completion_ns']-row['method_start_ns'])/1e9
    assert checkpoint['release_completed_ns']-checkpoint['release_started_ns'] >= pt['entry_timing']['release_check']['elapsed_ns']
    assert row['post_runner_delivery_seconds'] >= pt['entry_timing']['release_check']['elapsed_ns']/1e9
    assert row['T_other'] >= raw['T_other'] + pt['entry_timing']['release_check']['elapsed_ns']/1e9
    assert row['right_censored'] is False and row['certificate_valid_for_terminal'] is True
""")
source = source.replace("        parent_release_seconds=pt['entry_timing']['release_check']['elapsed_ns']/1e9)",
"""        parent_release_seconds=pt['entry_timing']['release_check']['elapsed_ns']/1e9,
        parent_release_charged=True,
        certificate_canonical_record=core['certificate_canonical_record']['elapsed_ns']/1e9,
        certificate_payload=core['certificate__certificate_payload']['elapsed_ns']/1e9,
        certificate_hash=core['certificate_sha256_file']['elapsed_ns']/1e9,
        additional_replay_seconds=read(directory/'external_replay_timing.json')['elapsed_ns']/1e9)""")
source = source.replace("assert read(OUT/'entry_checks.json')['status']=='PASS'", "assert read(OUT/'entry_checks.json')['status']=='PASS'\nassert read(OUT/'hook_check.json')['status']=='PASS'")
destination = here / 'read_entry_timing_final.py'
assert not destination.exists()
destination.write_text(source, encoding='utf-8', newline='\n')
print(destination)
