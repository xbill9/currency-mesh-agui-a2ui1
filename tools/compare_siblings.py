"""Compare each mesh agent's currency_agent/ package with its single-cloud sibling repo's.

usage: python3 tools/compare_siblings.py
Reads the sibling at git HEAD and this repo's working tree; prints changed lines per file.
"""
import difflib, pathlib, subprocess

HOME = pathlib.Path.home()
ROOT = pathlib.Path(__file__).resolve().parent.parent
SIBLINGS = {
    "gcp": ("currency-claude-agui-a2ui1", "currency_agent"),
    "aws": ("currency-strands-agui-a2ui1", "app/agent/currency_agent"),
    "azure": ("currency-maf-agui-a2ui1", "app/agent/currency_agent"),
}

def git_files(repo, pkg):
    out = subprocess.run(["git", "-C", str(repo), "ls-files", pkg], capture_output=True, text=True, check=True).stdout
    return [l for l in out.splitlines() if l.endswith((".py", ".json"))]

def head(repo, path):
    return subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{path}"], capture_output=True, text=True).stdout

for cloud, (name, pkg) in SIBLINGS.items():
    repo = HOME / name
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    print(f"== {cloud}: agents/{cloud}/currency_agent vs {name}@{sha}")
    total = 0
    for path in git_files(repo, pkg):
        mine = ROOT / "agents" / cloud / "currency_agent" / path[len(pkg) + 1:]
        a = head(repo, path).splitlines()
        b = mine.read_text().splitlines() if mine.exists() else []
        d = [l for l in difflib.unified_diff(a, b, lineterm="", n=0) if l[:1] in "+-" and l[:3] not in ("+++", "---")]
        total += len(d)
        print(f"{path}: {len(a)} lines, {len(d)} changed" + ("" if mine.exists() else " (absent here)"))
        for l in d:
            if len(d) <= 12:
                print("   ", l[:110])
    print(f"total changed lines: {total}")
