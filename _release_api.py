"""替换 Release 资源：删旧 asset → 上传新 exe → 校验。"""
import os
import subprocess
import sys
import io

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO = "HnoNoe/job-delivery-system"
RELEASE_ID = "452483154"
ASSET_NAME = "JobDeliverySystem-v0.2.0.exe"
EXE = sys.argv[1] if len(sys.argv) > 1 else os.path.join("dist", "JobDeliverySystem.exe")

tok = subprocess.run(
    ['git', 'credential', 'fill'], input="protocol=https\nhost=github.com\n\n",
    capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
TOKEN = [l.split("=", 1)[1] for l in tok.splitlines() if l.startswith("password=")][0].strip()
H = {"Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json"}

size = os.path.getsize(EXE)
print("uploading:", EXE, size, "bytes")

r = requests.get(f"https://api.github.com/repos/{REPO}/releases/{RELEASE_ID}",
                 headers=H, timeout=30)
r.raise_for_status()
rel = r.json()
print("release:", rel["tag_name"])
for a in rel["assets"]:
    print("  existing asset:", a["name"], a["size"])
    if a["name"] == ASSET_NAME:
        r = requests.delete(f"https://api.github.com/repos/{REPO}/releases/assets/{a['id']}",
                            headers=H, timeout=60)
        print("  deleted old:", r.status_code)

# 上传（大文件流式）
with open(EXE, "rb") as f:
    r = requests.post(
        f"https://uploads.github.com/repos/{REPO}/releases/{RELEASE_ID}/assets?name={ASSET_NAME}",
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/octet-stream",
                 "Accept": "application/vnd.github+json"},
        data=f, timeout=1800)
r.raise_for_status()
up = r.json()
print("uploaded:", up["name"], up["size"], up["browser_download_url"])
assert up["size"] == size, "size mismatch!"
print("=== Release 资源替换完成 ===")
