#!/usr/bin/env python3
"""Alertmanager webhook -> Telegram, in the Remnawave panel bot layout (same as the pena checker):
emoji + #tag heading, bold title, divider, `Key: value` lines.

Sends a rich message (Bot API sendRichMessage); if Telegram rejects it, the same events go out as
plain HTML (sendMessage) so no alert is lost. Stdlib only.

Presentation comes from the alert's annotations: emoji, tag, title, name, reason, provider, address.
Missing ones fall back to alertname / summary. "Last status change" is the alert's startsAt (UTC).

Env: TG_CHAT, TG_THREAD (optional), TG_TOKEN_FILE (default /run/tg_bot_token), LISTEN (default :8080).
Debug: `tg_relay.py --render < webhook.json` prints the rich and plain HTML without sending.
"""

import html
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SEPARATOR = "➖➖➖➖➖➖➖➖➖"
# The Remnawave bot's custom emoji (nodes.events.templates.ts); rich messages render them for any bot.
EMOJI_IDS = {"🚨": "5447183459602669338", "❇️": "5449683594425410231", "⚠️": "5447644880824181073"}
FIELDS = (("Name", "name"), ("Reason", "reason"), ("Last status change", None), ("Provider", "provider"),
          ("Address", "address"))  # fmt: skip


@dataclass(frozen=True, slots=True)
class Event:
    emoji: str
    tag: str
    title: str
    fields: list[tuple[str, str]]

    def rows(self) -> list[str]:
        return [f"<b>{key}:</b> <code>{html.escape(value)}</code>" for key, value in self.fields]

    def plain(self) -> str:
        head = [f"{self.emoji} <b>#{html.escape(self.tag)}</b>", f"<b>{html.escape(self.title)}</b>", SEPARATOR]
        return "\n".join([*head, *self.rows()])

    def rich(self) -> str:
        emoji_id = EMOJI_IDS.get(self.emoji)
        icon = f'<tg-emoji emoji-id="{emoji_id}">{self.emoji}</tg-emoji>' if emoji_id else self.emoji
        title = html.escape(self.title)
        return f"<h4>{icon} #{html.escape(self.tag)}</h4><p><b>{title}</b></p><hr><p>{'<br>'.join(self.rows())}</p>"


def _when(starts_at: str) -> str:
    """Alertmanager RFC3339 (nanoseconds, Z) -> `dd.mm.yyyy HH:MM` UTC, like the panel bot."""
    try:
        ts = datetime.fromisoformat(starts_at[:19]).replace(tzinfo=timezone.utc)
    except ValueError:
        return starts_at
    return ts.strftime("%d.%m.%Y %H:%M")


def to_event(alert: dict[str, Any]) -> Event:
    labels: dict[str, str] = alert.get("labels", {})
    notes: dict[str, str] = alert.get("annotations", {})
    alertname = labels.get("alertname", "alert")
    fields: list[tuple[str, str]] = []
    for key, source in FIELDS:
        value = _when(alert.get("startsAt", "")) if source is None else notes.get(source, "").strip()
        if value:
            fields.append((key, value))
    title = notes.get("title") or notes.get("summary") or alertname
    return Event(notes.get("emoji", "⚠️"), notes.get("tag", alertname), title.strip(), fields)


def render(payload: dict[str, Any]) -> tuple[str, str]:
    """(rich html, plain html) for the firing alerts of one webhook call; empty if nothing fires."""
    events = [to_event(a) for a in payload.get("alerts", []) if a.get("status") == "firing"]
    return "".join(e.rich() for e in events), "\n\n".join(e.plain() for e in events)


@dataclass(frozen=True, slots=True)
class Target:
    token: str
    chat: str
    thread: str


def _tg_post(target: Target, method: str, payload: dict[str, Any]) -> bool:
    body: dict[str, Any] = {"chat_id": target.chat, **payload}
    if target.thread:
        body["message_thread_id"] = int(target.thread)
    req = urllib.request.Request(f"https://api.telegram.org/bot{target.token}/{method}",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status == 200 and json.loads(resp.read()).get("ok") is True
    except urllib.error.HTTPError as e:
        print(f"telegram {method}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}", file=sys.stderr)
        return False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"telegram {method}: send failed: {type(e).__name__}", file=sys.stderr)
        return False
    if not ok:
        print(f"telegram {method}: response not ok", file=sys.stderr)
    return ok


def send(target: Target, rich: str, plain: str) -> bool:
    """Rich message first; if Telegram rejects it, the same events go as plain HTML."""
    if _tg_post(target, "sendRichMessage", {"rich_message": {"html": rich, "skip_entity_detection": True}}):
        return True
    return _tg_post(target, "sendMessage", {"text": plain, "parse_mode": "HTML", "disable_web_page_preview": True})


def serve(target: Target, listen: str) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            except (ValueError, json.JSONDecodeError):
                self.send_error(400, "bad json")
                return
            rich, plain = render(payload)
            ok = not rich or send(target, rich, plain)
            # non-2xx makes Alertmanager retry the notification
            self.send_response(200 if ok else 502)
            self.end_headers()

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} {fmt % args}", file=sys.stderr)

    host, _, port = listen.rpartition(":")
    ThreadingHTTPServer((host or "0.0.0.0", int(port)), Handler).serve_forever()


def main() -> int:
    if sys.argv[1:] == ["--render"]:
        rich, plain = render(json.load(sys.stdin))
        print(rich, plain, sep="\n\n")
        return 0
    with open(os.environ.get("TG_TOKEN_FILE", "/run/tg_bot_token"), encoding="utf-8") as f:
        token = f.read().strip()
    target = Target(token, os.environ["TG_CHAT"], os.environ.get("TG_THREAD", ""))
    serve(target, os.environ.get("LISTEN", ":8080"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
