"""git push 直连被墙时的 API 推送：blob → tree → commit → 更新 main 引用。
仅推送指定提交里变更的文件，基于该提交的父提交树。"""
import base64
import json
import subprocess
import sys
import io

import requests

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

REPO = "HnoNoe/job-delivery-system"
BASE = "https://api.github.com"

tok = subprocess.run(
    ['git', 'credential', 'fill'], input="protocol=https\nhost=github.com\n\n",
    capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
TOKEN = [l.split("=", 1)[1] for l in tok.splitlines() if l.startswith("password=")][0].strip()
H = {"Authorization": "Bearer " + TOKEN, "Accept": "application/vnd.github+json"}

commit_sha = sys.argv[1]
files = sys.argv[2:]

# 提交元信息（消息取本地提交；父提交取远端 main 头，因本地 SHA 与远端 API 重建 SHA 不同链）
c = subprocess.run(["git", "show", "-s", "--format=%s%n%b", commit_sha],
                   capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
subject, _, body = c.partition("\n")
message = subject + ("\n\n" + body.rstrip("\n") if body.strip() else "")

r = requests.get(f"{BASE}/repos/{REPO}/git/ref/heads/main", headers=H, timeout=30)
r.raise_for_status()
parent = r.json()["object"]["sha"]
r = requests.get(f"{BASE}/repos/{REPO}/git/commits/{parent}", headers=H, timeout=30)
r.raise_for_status()
base_tree = r.json()["tree"]["sha"]
print("remote base:", parent[:8], "tree:", base_tree[:8])

entries = []
for path in files:
    data = open(path, "rb").read()
    r = requests.post(f"{BASE}/repos/{REPO}/git/blobs", headers=H, timeout=60, json={
        "content": base64.b64encode(data).decode(), "encoding": "base64"})
    r.raise_for_status()
    entries.append({"path": path, "mode": "100644", "type": "blob",
                    "sha": r.json()["sha"]})
    print("blob:", path, len(data), "bytes")

r = requests.post(f"{BASE}/repos/{REPO}/git/trees", headers=H, timeout=30, json={
    "base_tree": base_tree, "tree": entries})
r.raise_for_status()
tree_sha = r.json()["sha"]
print("new tree:", tree_sha[:8])

r = requests.post(f"{BASE}/repos/{REPO}/git/commits", headers=H, timeout=30, json={
    "message": message, "tree": tree_sha, "parents": [parent]})
r.raise_for_status()
new_commit = r.json()["sha"]
print("new commit:", new_commit[:8])

r = requests.patch(f"{BASE}/repos/{REPO}/git/refs/heads/main", headers=H, timeout=30,
                   json={"sha": new_commit})
r.raise_for_status()
print("=== main 已更新到", new_commit[:8], "===")

# 同步本地 remote 跟踪
subprocess.run(["git", "update-ref", "refs/remotes/origin/main", new_commit])
