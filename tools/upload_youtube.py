#!/usr/bin/env python3
"""Upload media/currency-mesh-demo.mp4 to YouTube with the Data API v3, and set its thumbnail.

usage: python3 tools/upload_youtube.py --privacy unlisted [--dry-run]

The OAuth client and cached token live in ~/.config/youtube-upload/ (token mode 0600);
a missing or revoked token opens a browser for consent. Writes media/youtube-upload.json.
"""

import argparse
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONF = pathlib.Path.home() / ".config/youtube-upload"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.force-ssl"]
VIDEO = ROOT / "media/currency-mesh-demo.mp4"
THUMB = ROOT / "builder-cover.4e73d8c2.jpg"

TITLE = "One Chat, Three Clouds: A2UI 1.0 Agents on Google Cloud, AWS and Azure over A2A"
DESCRIPTION = """Three A2UI 1.0 currency agents, one per cloud, answer in one chat. Google ADK with Gemini owns rate cards, Strands Agents with Amazon Nova owns history charts, and Microsoft Agent Framework with Azure OpenAI owns comparisons. An ADK coordinator behind AG-UI names a job for each question, a table in code maps the job to a cloud, and the question goes to that agent over A2A. Ask all three clouds, and three labelled answers share one turn.

Every answer in the video is a live reply from the running agents. The routing suite ran ten prompts ten times each through the same UI: 100 of 100 reached the right clouds with the right job.

Code, deploy scripts and evidence: https://github.com/xbill9/currency-mesh-agui-a2ui1

Narration: gemini-3.8-flash-tts."""
TAGS = ["A2UI", "A2A", "AG-UI", "CopilotKit", "Google ADK", "Gemini", "Strands Agents", "Amazon Nova",
        "Amazon Bedrock", "Microsoft Agent Framework", "Azure OpenAI", "multicloud", "AI agents"]


def creds():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    tok = CONF / "token.json"
    c = Credentials.from_authorized_user_file(str(tok), SCOPES) if tok.exists() else None
    if c and c.expired and c.refresh_token:
        c.refresh(Request())
    if not c or not c.valid:
        c = InstalledAppFlow.from_client_secrets_file(str(CONF / "client_secret.json"), SCOPES).run_local_server(
            port=0, open_browser=True
        )
    with open(os.open(tok, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
        f.write(c.to_json())
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--privacy", choices=["public", "unlisted", "private"], required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    assert len(TITLE) <= 100, len(TITLE)
    body = {
        "snippet": {"title": TITLE, "description": DESCRIPTION, "tags": TAGS, "categoryId": "28",
                    "defaultLanguage": "en", "defaultAudioLanguage": "en"},
        "status": {"privacyStatus": a.privacy, "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    if a.dry_run:
        print(json.dumps(body, indent=1))
        return
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=creds())
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(VIDEO), mimetype="video/mp4", resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    result = {"id": vid, "url": f"https://www.youtube.com/watch?v={vid}", "privacy": a.privacy}
    try:
        yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(THUMB), mimetype="image/jpeg")).execute()
        result["thumbnail"] = "set"
    except Exception as e:  # custom thumbnails need a verified channel
        result["thumbnail"] = f"failed: {str(e)[:200]}"
    (ROOT / "media/youtube-upload.json").write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
