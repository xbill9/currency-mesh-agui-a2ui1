#!/usr/bin/env python3
"""Summarise a mesh_suite.py run: passes per prompt, the job the coordinator sent, and seconds per cloud.

usage: python3 tools/summarize_suite.py evidence/OUT.jsonl
"""

import collections
import json
import statistics
import sys

rows = [json.loads(l) for l in open(sys.argv[1])]
by = collections.OrderedDict()
for r in rows:
    by.setdefault(r["prompt"], []).append(r)

passed = sum(r["verdict"] == "pass" for r in rows)
print(f"{rows[0]['label']}: {passed} of {len(rows)} passed")
print()
print("| Prompt | Tool, job sent | Clouds | Passed | Turn median s |")
for prompt, rs in by.items():
    sent = collections.Counter()
    for r in rs:
        job = json.loads(r["tool_args"]).get("job") if r.get("tool_args") else None
        tool = ",".join(r["tools"]) or "none"
        sent[f"{tool}" + (f" {job}" if job else "")] += 1
    clouds = sorted({c["cloud"] for r in rs for c in r["clouds"]})
    ok = sum(r["verdict"] == "pass" for r in rs)
    med = statistics.median(r["seconds"] for r in rs)
    sends = "; ".join(f"{k} x{v}" for k, v in sent.items())
    print(f"| {prompt} | {sends} | {'+'.join(clouds) or '-'} | {ok} of {len(rs)} | {med:.1f} |")

print()
print("| Cloud | Model | Calls | With A2UI | Agent median s | Agent max s |")
calls = collections.defaultdict(list)
for r in rows:
    for c in r["clouds"]:
        calls[(c["cloud"], c["model"])].append(c)
for (cloud, model), cs in sorted(calls.items()):
    secs = [c["seconds"] for c in cs]
    print(f"| {cloud} | {model} | {len(cs)} | {sum(1 for c in cs if c['a2ui'])} | "
          f"{statistics.median(secs):.1f} | {max(secs):.1f} |")

fails = [r for r in rows if r["verdict"] != "pass"]
if fails:
    print()
    for r in fails:
        print(f"FAIL {r['prompt']}: {r['verdict'][:140]}")
