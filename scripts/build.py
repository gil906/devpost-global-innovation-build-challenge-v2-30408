"""Build a portable source archive, then exercise the extracted HTTP application."""

import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "app.py", "planner.py", "store.py", "README.md", "SUBMISSION.md",
    "LICENSE", ".env.example", "package.json", "package-lock.json",
]
for directory in ("data", "web", "tests", "scripts", "docs"):
    FILES.extend(str(path.relative_to(ROOT)) for path in sorted((ROOT / directory).rglob("*"))
                 if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")


def main():
    runtime = Path(os.environ.get("APP_DATA_DIR", ".runtime")).resolve()
    output = runtime / "build"
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "commontable-1.0.0.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative in FILES:
            bundle.write(ROOT / relative, relative)
        manifest = {relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() for relative in FILES}
        bundle.writestr("MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", 8764)) == 0:
            raise SystemExit("Port 8764 is occupied; refusing to interact with an unrelated service.")
    with tempfile.TemporaryDirectory(prefix="archive-smoke-", dir=output) as directory:
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(directory)
        env = dict(os.environ, APP_DATA_DIR=str(Path(directory) / ".runtime"))
        log = output / "archive-smoke.log"
        with log.open("w") as stream:
            child = subprocess.Popen(["python3", "app.py", "--host", "0.0.0.0", "--port", "8764"],
                                     cwd=directory, env=env, stdout=stream, stderr=stream)
            try:
                for _ in range(100):
                    if child.poll() is not None:
                        raise RuntimeError(f"Extracted server exited; see {log}")
                    try:
                        with urllib.request.urlopen("http://127.0.0.1:8764/health", timeout=1) as response:
                            if json.load(response)["status"] == "ok":
                                break
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.05)
                else:
                    raise RuntimeError("Extracted server did not become healthy.")
                scenario = json.loads((ROOT / "data/demo.json").read_text())
                request = urllib.request.Request("http://127.0.0.1:8764/api/plan",
                                                 data=json.dumps(scenario).encode(),
                                                 headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    result = json.load(response)
                if result["summary"]["allocated"] != 230 or result["improvement"] != 60:
                    raise RuntimeError("Extracted archive failed the known allocation case.")
                for path, marker in (("/", b"CommonTable"), ("/app.js", b"renderResults"), ("/style.css", b".metric")):
                    with urllib.request.urlopen("http://127.0.0.1:8764" + path, timeout=5) as response:
                        if marker not in response.read():
                            raise RuntimeError(f"Extracted archive missing usable asset {path}")
            finally:
                child.terminate()
                child.wait(timeout=10)
    print(f"Built {archive.relative_to(runtime)} ({archive.stat().st_size:,} bytes)")
    print("PASS: extracted archive serves all UI assets and assigns 230 servings (+60 versus baseline).")


if __name__ == "__main__":
    main()
