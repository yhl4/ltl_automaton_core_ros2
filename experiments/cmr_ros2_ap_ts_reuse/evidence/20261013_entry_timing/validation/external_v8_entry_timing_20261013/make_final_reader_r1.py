"""Correct aggregate status literals; preserve the first failed reader."""
from pathlib import Path
here = Path(__file__).resolve().parent
source = (here/'read_entry_timing_final.py').read_text(encoding='utf-8')
for name in ('entry_checks.json', 'hook_check.json'):
    before = f"read(OUT/'{name}')['status']=='PASS'"
    assert source.count(before) == 1
    source = source.replace(before, f"read(OUT/'{name}')['status']=='PASSED'")
destination = here/'read_entry_timing_final_r1.py'
assert not destination.exists()
destination.write_text(source, encoding='utf-8', newline='\n')
print(destination)
