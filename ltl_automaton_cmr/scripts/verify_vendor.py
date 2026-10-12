"""Verify frozen source bytes without fetching or importing the planner."""
import hashlib
import json
from pathlib import Path

def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    for row in manifest["files"]:
        content = (root / row["local_path"]).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if blob != row["git_blob"] or hashlib.sha256(content).hexdigest() != row["sha256"]:
            raise SystemExit("Frozen source mismatch: " + row["local_path"])
    print("Verified", len(manifest["files"]), "frozen files at", manifest["commit"])

if __name__ == "__main__":
    main()
