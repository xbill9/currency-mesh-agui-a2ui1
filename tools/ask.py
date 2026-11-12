"""Ask one or more mesh agents a question over A2A and print what came back.

usage: python3 tools/ask.py CLOUD=URL [CLOUD=URL ...] -- QUESTION
"""
import asyncio, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mesh.client import ask

async def main():
    i = sys.argv.index("--")
    targets = [a.split("=", 1) for a in sys.argv[1:i]]
    q = " ".join(sys.argv[i + 1:])
    answers = await asyncio.gather(*(ask(c, u, q) for c, u in targets))
    for a in answers:
        comps = [x.get("component") for m in a.a2ui for x in (m.get("createSurface") or {}).get("components", [])]
        print(json.dumps({"cloud": a.cloud, "seconds": a.seconds, "metadata": a.metadata,
                          "text": a.text[:200], "a2ui_messages": len(a.a2ui), "components": comps, "error": a.error}))

asyncio.run(main())
