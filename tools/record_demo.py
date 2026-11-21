#!/usr/bin/env python3
"""Record the narrated demo video: real questions through the running mesh, then the suite result.

usage: GEMINI_API_KEY=... UI_URL=http://localhost:3010 python3 tools/record_demo.py evidence/mesh-suite-local-2026-11-21.jsonl

Every answer on screen is a live reply from the stack at UI_URL. Every number
in a caption is read from the page or from the suite file given. The voice is
gemini-3.8-flash-tts, generated before recording starts; each caption stays up
for its clip, and the clips are mixed onto the screen recording at the moments
they played. Output: media/currency-mesh-demo.mp4 (1280x720, H.264 + AAC).
"""

import collections
import hashlib
import html
import json
import os
import pathlib
import subprocess
import sys
import time
import wave

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
VOICE_DIR = MEDIA / "voice"
UI = os.getenv("UI_URL", "http://localhost:3010")
REPO = "github.com/xbill9/currency-mesh-agui-a2ui1"
VOICE_MODEL = "gemini-3.8-flash-tts"
VOICE = "Kore"
PAD = 0.7  # seconds of quiet after each line

CSS = """
:root{--bg:#0f172a;--fg:#e2e8f0;--mute:#94a3b8;--line:#334155;--g:#4285f4;--a:#ff9900;--z:#0a84ff;--c:#10b981}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:22px/1.45 system-ui,sans-serif;height:720px;overflow:hidden}
.card{display:flex;flex-direction:column;justify-content:center;height:720px;padding:0 90px}
h1{font-size:60px;margin:0 0 14px;line-height:1.1} h2{font-size:38px;margin:0 0 22px} .mute{color:var(--mute)}
.big{font-size:28px;line-height:1.55}
.flow{display:grid;grid-template-columns:1fr 1fr 1.3fr;gap:26px;align-items:center;margin-top:10px}
.box{border:2px solid var(--line);border-radius:12px;padding:14px 18px;font-size:19px}
.box b{display:block;font-size:22px} .box span{color:var(--mute);font-size:16px}
.stack{display:flex;flex-direction:column;gap:14px}
.gcp{border-color:var(--g)} .aws{border-color:var(--a)} .azure{border-color:var(--z)} .co{border-color:var(--c)}
table{border-collapse:collapse;font-size:20px} td,th{padding:6px 16px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--mute);font-weight:600}
#cap{position:fixed;left:50%;transform:translateX(-50%);bottom:26px;max-width:1080px;background:#000d;color:#fff;
 font:600 23px/1.35 system-ui;padding:12px 22px;border-radius:10px;z-index:99999;text-align:center}
#cap:empty{display:none}
"""
CAP_CSS = CSS[CSS.index("#cap{"):]

# (cloud id, question, expected blocks, line before the answer, line after the answer)
QUESTIONS = [
    ("gcp", "How much is 250 USD in EUR?", 1,
     "A conversion is a rate job, so the coordinator sends it to Google Cloud.",
     "The rate card comes back from Google Cloud, built by Google ADK on Gemini."),
    ("aws", "Show me the USD to JPY trend over the last 90 days", 1,
     "A trend is a history job, so it goes to AWS.",
     "The line chart comes back from AWS, built by Strands Agents on Amazon Nova."),
    ("azure", "Compare 1 USD in EUR, GBP, JPY and CAD", 1,
     "Several currencies against one is a comparison job, so it goes to Azure.",
     "The bar chart comes back from Azure, built by Microsoft Agent Framework on G P T five point four mini."),
    ("all", "Ask all three clouds: how much is 100 USD in EUR?", 3,
     "Ask all three clouds, and the coordinator sends the question to every agent at once.",
     "Three answers in one turn, each labelled with the cloud, framework and model that built it."),
]
LABEL_PREFIX = {"gcp": "Google Cloud", "aws": "AWS", "azure": "Azure"}


def page_html(body):
    return f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body>{body}<div id=cap></div></body>"


def suite_summary(path):
    rows = [json.loads(l) for l in open(path)]
    by = collections.OrderedDict()
    for r in rows:
        by.setdefault(r["prompt"], []).append(r["verdict"] == "pass")
    passed = sum(r["verdict"] == "pass" for r in rows)
    runs = len(next(iter(by.values())))
    return rows, by, passed, runs


def tts(text):
    """Synthesize one line, cached by its text. Only the words are sent: the model reads instructions aloud."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    path = VOICE_DIR / (hashlib.sha256(f"{VOICE_MODEL}|{VOICE}|{text}".encode()).hexdigest()[:16] + ".wav")
    if not path.exists():
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        r = client.models.generate_content(
            model=VOICE_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE))
                ),
            ),
        )
        pcm = r.candidates[0].content.parts[0].inline_data.data
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(24000)
            w.writeframes(pcm)
    with wave.open(str(path)) as w:
        return path, w.getnframes() / w.getframerate()


class Narrator:
    def __init__(self, lines):
        self.clips = {t: tts(t) for t in lines}
        self.t0 = None
        self.played = []  # (seconds into the video, wav path)

    def say(self, p, text, caption=None):
        """Show the caption, log the clip at this moment, and hold for its length."""
        path, dur = self.clips[text]
        p.evaluate("t=>{document.getElementById('cap').textContent=t}", caption or text.replace("G P T five point four mini", "gpt-5.4-mini"))
        self.played.append((time.monotonic() - self.t0, path))
        p.wait_for_timeout(int((dur + PAD) * 1000))

    def say_async(self, p, text):
        """Show the caption and log the clip, without waiting: the next step runs while it plays."""
        path, dur = self.clips[text]
        p.evaluate("t=>{document.getElementById('cap').textContent=t}", text)
        self.played.append((time.monotonic() - self.t0, path))
        return time.monotonic() + dur + PAD


def ask(p, question, expect_blocks):
    before = p.locator(".mesh-source").count()
    box = p.locator("textarea").first
    box.click()
    box.type(question, delay=28)
    p.wait_for_timeout(400)
    box.press("Enter")
    p.wait_for_function(
        "n=>document.querySelectorAll('.mesh-source').length>=n", arg=before + expect_blocks, timeout=180_000
    )
    p.wait_for_timeout(2500)  # let the charts draw
    blocks = p.locator(".mesh-source")
    labels = [blocks.nth(i).locator("p").first.inner_text() for i in range(before, blocks.count())]
    blocks.nth(before).scroll_into_view_if_needed()
    return labels


def main():
    rows, by, passed, runs = suite_summary(sys.argv[1])
    suite_line = (f"In the routing suite, ten prompts ran {runs} times each through this same UI, "
                  f"and {passed} of {len(rows)} reached the right clouds with the right job.")
    lines = [
        "One chat, three clouds. Currency agents on Google Cloud, AWS and Azure, joined over A2A behind one coordinator.",
        "Each agent uses a different framework and a different model, and each one answers with A2UI cards and charts.",
        "The coordinator model names a job. A table in code maps that job to a cloud.",
        "Each agent answers over A2A, with A2UI data parts tagged with its cloud, framework and model.",
        "Here is the chat, running live against the three agents.",
        *[q[3] for q in QUESTIONS], *[q[4] for q in QUESTIONS],
        suite_line,
        "The code, the deploy scripts and the evidence are on GitHub. Cross-cloud calls start from the coordinator's Google identity, with no stored keys.",
    ]
    n = Narrator(lines)
    MEDIA.mkdir(exist_ok=True)
    with sync_playwright() as w:
        b = w.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(
            viewport=dict(width=1280, height=720),
            record_video_dir=str(MEDIA / "raw"),
            record_video_size=dict(width=1280, height=720),
        )
        p = ctx.new_page()
        n.t0 = time.monotonic()

        p.set_content(page_html(
            "<div class=card><h1>One chat, three clouds</h1>"
            "<div class='big mute'>A2UI 1.0 currency agents on Google Cloud, AWS and Azure,<br>"
            "joined over A2A behind one AG-UI coordinator.</div></div>"))
        p.wait_for_timeout(1500)
        n.say(p, lines[0])
        n.say(p, lines[1])

        p.set_content(page_html(
            "<div class=card><h2>How a question travels</h2><div class=flow>"
            "<div class=box><b>Browser</b><span>CopilotKit + @a2ui/react</span></div>"
            "<div class='box co'><b>Coordinator</b><span>Google ADK · gemini-3.8-flash<br>AG-UI in, A2A out</span></div>"
            "<div class=stack>"
            "<div class='box gcp'><b>Google Cloud · rate</b><span>Google ADK · gemini-3.8-flash</span></div>"
            "<div class='box aws'><b>AWS · history</b><span>Strands Agents · Amazon Nova 2 Lite</span></div>"
            "<div class='box azure'><b>Azure · comparison</b><span>Agent Framework · gpt-5.4-mini</span></div>"
            "</div></div></div>"))
        n.say(p, lines[2])
        n.say(p, lines[3])

        p.goto(UI)
        p.wait_for_selector("textarea", timeout=60_000)
        # captions sit in the open area left of the chat sidebar; hide the dev badge and CopilotKit's banner
        p.add_style_tag(content=CAP_CSS + "#cap{left:400px;max-width:720px}nextjs-portal{display:none!important}")
        p.evaluate("""()=>{for(const el of document.querySelectorAll('body *')){
            if(el.children.length===0 && /AG-UI 1.0 is here/.test(el.textContent||'')){
                let n=el; for(let i=0;i<3&&n.parentElement;i++) n=n.parentElement; n.style.visibility='hidden'}}}""")
        p.evaluate("()=>{const d=document.createElement('div');d.id='cap';document.body.append(d)}")
        p.wait_for_timeout(1000)
        n.say(p, lines[4])

        for cloud, question, blocks, before, after in QUESTIONS:
            done_at = n.say_async(p, before)
            labels = ask(p, question, blocks)
            want = list(LABEL_PREFIX.values()) if cloud == "all" else [LABEL_PREFIX[cloud]]
            got = [l.split(" · ")[0] for l in labels]
            if sorted(got) != sorted(want):
                raise SystemExit(f"{question!r}: answered by {got}, expected {want}")
            p.wait_for_timeout(max(0, int((done_at - time.monotonic()) * 1000)))
            n.say(p, after, caption=" | ".join(labels) if cloud == "all" else labels[0])
            p.wait_for_timeout(2500)

        trs = "".join(f"<tr><td>{html.escape(q)}</td><td>{sum(v)} of {len(v)}</td></tr>" for q, v in by.items())
        p.set_content(page_html(
            f"<div style='padding:36px 70px'><h2>Routing suite: {passed} of {len(rows)}</h2>"
            f"<table><tr><th>Prompt</th><th>Passed</th></tr>{trs}</table></div>"))
        n.say(p, suite_line)
        p.wait_for_timeout(2500)

        p.set_content(page_html(
            "<div class=card><h2>Code, deploy scripts and evidence</h2>"
            f"<div class=big>{REPO}<br><br><span class=mute>Cloud Run · AgentCore Runtime · Container Apps<br>"
            "Cross-cloud calls start from the coordinator's Google identity: no stored keys.</span></div></div>"))
        n.say(p, lines[-1], caption="")
        p.wait_for_timeout(1500)
        video = p.video.path()
        ctx.close()
        b.close()

    # one audio track: each clip delayed to the moment its caption appeared
    inputs, filters = [], []
    for i, (at, path) in enumerate(n.played):
        inputs += ["-i", str(path)]
        ms = int(at * 1000)
        filters.append(f"[{i + 1}:a]adelay={ms}|{ms}[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(n.played)))
    filters.append(f"{mix}amix=inputs={len(n.played)}:normalize=0[aout]")
    out = MEDIA / "currency-mesh-demo.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video, *inputs, "-filter_complex", ";".join(filters),
         "-map", "0:v", "-map", "[aout]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)],
        check=True,
    )
    pathlib.Path(video).unlink()
    json.dump([{"at": round(a, 2), "clip": p.name} for a, p in n.played], open(MEDIA / "narration-timing.json", "w"), indent=1)
    print("wrote", out)


if __name__ == "__main__":
    main()
