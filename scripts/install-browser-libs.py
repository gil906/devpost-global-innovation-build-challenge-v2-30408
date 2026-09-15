"""Optional workspace-only Chromium libraries for minimal glibc 2.36+ Linux.

Downloads Debian bookworm packages over HTTPS, checks their index SHA-256, and
extracts files without root, package installation, or maintainer-script execution.
The normal application does not need these libraries.
"""

import hashlib
import lzma
import platform
import subprocess
import urllib.request
from pathlib import Path

BASE = "https://deb.debian.org/debian/"
CACHE = Path("node_modules/.cache")
PACKAGES = (
    "libglib2.0-0 libnspr4 libnss3 libatk1.0-0 libdbus-1-3 libatspi2.0-0 "
    "libx11-6 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 "
    "libxcb1 libxkbcommon0 libasound2 libffi8 libpcre2-8-0 libmount1 libselinux1 "
    "libblkid1 libsystemd0 libcap2 libgcrypt20 libgpg-error0 liblz4-1 liblzma5 "
    "libzstd1 libdrm2 libwayland-server0 libxau6 libxdmcp6 libbsd0 libmd0 "
    "libfontconfig1 libfreetype6 libpng16-16 libbrotli1 fonts-dejavu-core libxi6 libxrender1"
).split()


def main():
    architecture = {"aarch64": "arm64", "x86_64": "amd64"}.get(platform.machine())
    if architecture is None or platform.system() != "Linux":
        raise SystemExit("This optional helper supports arm64/amd64 Linux only.")
    libc, version = platform.libc_ver()
    if libc != "glibc" or tuple(map(int, version.split(".")[:2])) < (2, 36):
        raise SystemExit("This optional helper requires glibc 2.36 or later.")
    cache = CACHE / "browser-debs"
    root = CACHE / "browser-sysroot"
    cache.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)
    index_path = cache / f"Packages-{architecture}.xz"
    with urllib.request.urlopen(BASE + f"dists/bookworm/main/binary-{architecture}/Packages.xz", timeout=90) as response:
        index_path.write_bytes(response.read())
    index = {}
    for block in lzma.decompress(index_path.read_bytes()).decode().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(" "))
        if fields.get("Package") in PACKAGES:
            index[fields["Package"]] = fields
    for name in PACKAGES:
        package = index[name]
        filename = package["Filename"]
        if not filename.startswith("pool/") or ".." in filename:
            raise SystemExit("Invalid package index path.")
        archive = cache / Path(filename).name
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != package["SHA256"]:
            with urllib.request.urlopen(BASE + filename, timeout=90) as response:
                archive.write_bytes(response.read())
        if hashlib.sha256(archive.read_bytes()).hexdigest() != package["SHA256"]:
            raise SystemExit(f"Checksum mismatch for {name}")
        subprocess.run(["dpkg-deb", "-x", str(archive), str(root)], check=True, capture_output=True)
        print(f"Extracted {name}")
    print("Workspace browser libraries are ready.")


if __name__ == "__main__":
    main()
