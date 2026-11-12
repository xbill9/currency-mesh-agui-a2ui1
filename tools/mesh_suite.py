"""Run routing prompts N times each through Next.js and check which clouds answered.

usage: python3 mesh_suite.py RUNS LABEL OUT.jsonl

A prompt passes when the coordinator called the expected tool with the expected
job, exactly the expected clouds answered, every one of them answered with A2UI
(text is accepted where the prompt allows it), and no raw "<a2ui" text reached
the chat. The routing is read from the job the coordinator sent, not inferred
from the card that rendered.
"""

import collections
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from demo_probe import run

ALL = ("aws", "azure", "gcp")
# (prompt, tool, job, clouds, text_ok)
CASES = [
    ("How much is 250 USD in EUR?", "route_to_cloud", "rate", ("gcp",), False),
    ("What's a thousand euros in dollars?", "route_to_cloud", "rate", ("gcp",), False),
    ("Show me the USD to JPY trend over the last 90 days", "route_to_cloud", "history", ("aws",), False),
    ("Show me EUR to USD for the past 6 months and the current rate", "route_to_cloud", "history", ("aws",), False),
    ("Compare the euro, pound and Swiss franc against the dollar in a bar chart", "route_to_cloud", "comparison", ("azure",), False),
    ("Compare 1 USD in EUR, GBP, JPY and CAD", "route_to_cloud", "comparison", ("azure",), False),
    ("Ask all three clouds: how much is 100 USD in EUR?", "ask_all_clouds", None, ALL, False),
    ("Compare the clouds: show me the USD to JPY trend over the last 90 days", "ask_all_clouds", None, ALL, False),
    ("What's the weather in Paris?", None, None, (), True),
    ("Convert 100 USD to XYZ", "route_to_cloud", "rate", ("gcp",), True),
]


def verdict(case, r: dict) -> str:
    _prompt, tool, job, clouds, text_ok = case
    if "<a2ui" in r.get("text", ""):
        return "fail: raw <a2ui> text in the chat"
    if r.get("errors"):
        return "fail: " + "; ".join(e[:80] for e in r["errors"])
    called = r.get("tools") or []
    if tool is None:
        return "pass" if not called and r.get("text") else f"fail: called {called}"
    if called != [tool]:
        return f"fail: called {called}, expected [{tool}]"
    if job is not None:
        try:
            sent = json.loads(r.get("tool_args") or "{}").get("job")
        except json.JSONDecodeError:
            sent = None
        if sent != job:
            return f"fail: job {sent!r}, expected {job!r}"
    answered = tuple(sorted(c["cloud"] for c in r.get("clouds", [])))
    if answered != tuple(sorted(clouds)):
        return f"fail: answered by {answered}, expected {clouds}"
    for c in r["clouds"]:
        if c.get("error"):
            return f"fail: {c['cloud']} error {c['error'][:80]}"
        if not c.get("a2ui") and not text_ok:
            return f"fail: {c['cloud']} sent no A2UI"
    return "pass"


if __name__ == "__main__":
    runs, label, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    tally = collections.Counter()
    with open(out, "w") as fh:
        for case in CASES:
            for _ in range(runs):
                r = run(case[0])
                v = verdict(case, r)
                fh.write(json.dumps({"label": label, "verdict": v, **r}) + "\n")
                fh.flush()
                tally[(case[0], v)] += 1
    total = sum(tally.values())
    passed = sum(n for (_, v), n in tally.items() if v == "pass")
    print(f"# {label}: {passed} of {total} routed and rendered as expected ({runs} runs per prompt)")
    for (prompt, v), n in sorted(tally.items()):
        print(f"{n} of {runs}: {v} | {prompt}")
