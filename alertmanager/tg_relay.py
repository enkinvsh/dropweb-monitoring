#!/usr/bin/env python3
"""Вебхук Alertmanager -> Telegram в раскладке бота панели Remnawave (как у pena checker):
эмодзи + #тег, жирный заголовок, черта, строки `Key: value`.

Карточка уходит rich message (sendRichMessage); если Telegram её отвергает, те же события
идут простым HTML (sendMessage), чтобы алерт не потерялся. Только stdlib.

Одна группа Alertmanager = одна карточка. Повтор той же группы (repeat_interval) нового
сообщения не шлёт: карточка уже в чате. Новый алерт в группе — новая карточка со звуком.
Когда группа прошла целиком (send_resolved), relay правит её карточки в «Снят» вместо
нового сообщения. Номера отправленных сообщений лежат в TG_STATE_FILE.

TG_BUTTONS=1 вешает под карточку «🔕 1 ч» / «🔕 до утра». Нажатие ловит мост PENA
(pena-tgbridge опрашивает того же бота) и ставит silence в этом Alertmanager. Без моста
кнопки никто не обработает, поэтому по умолчанию их нет.

Оформление берётся из аннотаций алерта: emoji, tag, title, name, reason, provider, address.
Чего нет — подставляются alertname / summary. «Last status change» — startsAt алерта (UTC).

Env: TG_CHAT, TG_THREAD (необязательно), TG_TOKEN_FILE (/run/tg_bot_token), LISTEN (:8080),
TG_STATE_FILE (/data/messages.json), TG_BUTTONS.
Отладка: `tg_relay.py --render < webhook.json` печатает rich и plain HTML без отправки.
"""

import html
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SEPARATOR = "➖➖➖➖➖➖➖➖➖"
# The Remnawave bot's custom emoji (nodes.events.templates.ts); rich messages render them for any bot.
EMOJI_IDS = {"🚨": "5447183459602669338", "❇️": "5449683594425410231", "⚠️": "5447644880824181073"}
FIELDS = (("Name", "name"), ("Reason", "reason"), ("Last status change", None), ("Provider", "provider"),
          ("Address", "address"))  # fmt: skip
RESOLVED_EMOJI = "❇️"
# callback_data у Telegram не длиннее 64 байт; формат читает pena-tgbridge: am:<h|m>:<alertname>[:<node_name>].
CALLBACK_MAX = 64
_ALERTNAME = re.compile(r"[A-Za-z0-9_]{1,40}")
_NODE_NAME = re.compile(r"[A-Za-z0-9_.-]{1,32}")


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


def _parse(stamp: str) -> datetime | None:
    try:
        return datetime.fromisoformat(stamp[:19]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _when(starts_at: str) -> str:
    """Alertmanager RFC3339 (nanoseconds, Z) -> `dd.mm.yyyy HH:MM` UTC, like the panel bot."""
    ts = _parse(starts_at)
    return ts.strftime("%d.%m.%Y %H:%M") if ts else starts_at


def _lasted(starts_at: str, ends_at: str) -> str:
    start, end = _parse(starts_at), _parse(ends_at)
    if start is None or end is None or end < start:
        return ""
    hours, minutes = divmod(int((end - start).total_seconds() // 60), 60)
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


def to_event(alert: dict[str, Any], *, resolved: bool = False) -> Event:
    labels: dict[str, str] = alert.get("labels", {})
    notes: dict[str, str] = alert.get("annotations", {})
    alertname = labels.get("alertname", "alert")
    fields: list[tuple[str, str]] = []
    for key, source in FIELDS:
        value = _when(alert.get("startsAt", "")) if source is None else notes.get(source, "").strip()
        if value:
            fields.append((key, value))
    title = (notes.get("title") or notes.get("summary") or alertname).strip()
    emoji = notes.get("emoji", "⚠️")
    if resolved:
        emoji, title = RESOLVED_EMOJI, f"Снят: {title}"
        lasted = _lasted(alert.get("startsAt", ""), alert.get("endsAt", ""))
        if lasted:
            fields.append(("Duration", lasted))
    return Event(emoji, notes.get("tag", alertname), title, fields)


def cards(alerts: list[dict[str, Any]], *, resolved: bool = False) -> tuple[str, str]:
    events = [to_event(a, resolved=resolved) for a in alerts]
    return "".join(e.rich() for e in events), "\n\n".join(e.plain() for e in events)


def render(payload: dict[str, Any]) -> tuple[str, str]:
    """(rich html, plain html) for the firing alerts of one webhook call; empty if nothing fires."""
    return cards([a for a in payload.get("alerts", []) if a.get("status") == "firing"])


def silence_markup(alerts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Кнопки тишины под карточкой. Глушим то, что на карточке: одна нода — только её,
    несколько — весь алерт (группа Alertmanager собрана по alertname)."""
    names = {str(a.get("labels", {}).get("alertname", "")) for a in alerts}
    if len(names) != 1:
        return None
    name = names.pop()
    if not _ALERTNAME.fullmatch(name):
        return None
    tail = name
    if len(alerts) == 1:
        node = str(alerts[0].get("labels", {}).get("node_name", ""))
        if _NODE_NAME.fullmatch(node) and len(f"am:h:{name}:{node}".encode()) <= CALLBACK_MAX:
            tail = f"{name}:{node}"
    return {"inline_keyboard": [[
        {"text": "🔕 1 ч", "callback_data": f"am:h:{tail}"},
        {"text": "🔕 до утра", "callback_data": f"am:m:{tail}"},
    ]]}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Target:
    token: str
    chat: str
    thread: str


def _tg_call(target: Target, method: str, payload: dict[str, Any], *, in_thread: bool = True) -> Any:
    """Результат метода Bot API или None, если вызов не прошёл."""
    body: dict[str, Any] = {"chat_id": target.chat, **payload}
    if target.thread and in_thread:
        body["message_thread_id"] = int(target.thread)
    req = urllib.request.Request(f"https://api.telegram.org/bot{target.token}/{method}",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})  # fmt: skip
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")[:300]
        # Правка тем же текстом — не сбой: карточка уже такая, как надо.
        if e.code == 400 and "not modified" in text:
            return True
        print(f"telegram {method}: HTTP {e.code}: {text}", file=sys.stderr)
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        print(f"telegram {method}: send failed: {type(e).__name__}", file=sys.stderr)
        return None
    if data.get("ok") is not True:
        print(f"telegram {method}: response not ok", file=sys.stderr)
        return None
    return data.get("result")


def send(target: Target, rich: str, plain: str, markup: dict[str, Any] | None = None) -> tuple[int, bool] | None:
    """(message_id, rich?) отправленной карточки: сначала rich, при отказе — plain HTML."""
    extra = {"reply_markup": markup} if markup else {}
    result = _tg_call(target, "sendRichMessage",
                      {"rich_message": {"html": rich, "skip_entity_detection": True}, **extra})  # fmt: skip
    if isinstance(result, dict):
        return int(result.get("message_id", 0)), True
    result = _tg_call(target, "sendMessage",
                      {"text": plain, "parse_mode": "HTML", "disable_web_page_preview": True, **extra})  # fmt: skip
    if isinstance(result, dict):
        return int(result.get("message_id", 0)), False
    return None


def edit(target: Target, message_id: int, rich: bool, rich_html: str, plain: str) -> bool:
    """Переписать карточку; кнопки при этом снимаются (reply_markup не передаём)."""
    if rich:
        body: dict[str, Any] = {"rich_message": {"html": rich_html, "skip_entity_detection": True}}
    else:
        body = {"text": plain, "parse_mode": "HTML", "disable_web_page_preview": True}
    return _tg_call(target, "editMessageText", {"message_id": message_id, **body}, in_thread=False) is not None


@dataclass
class Store:
    """groupKey -> отправленные карточки [{id, rich, fps}]. Без записи на диск relay
    продолжает работать: после перезапуска «Снят» для старых карточек просто не придёт."""

    path: str
    data: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def load(cls, path: str) -> "Store":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            data = {}
        except (OSError, ValueError) as e:
            print(f"state {path}: unreadable ({type(e).__name__}), starting empty", file=sys.stderr)
            data = {}
        return cls(path, data if isinstance(data, dict) else {})

    def save(self) -> None:
        tmp = f"{self.path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except OSError as e:
            print(f"state {self.path}: not saved ({type(e).__name__})", file=sys.stderr)


def handle(target: Target, store: Store, payload: dict[str, Any], *, buttons: bool = False) -> bool:
    """Одна доставка Alertmanager. False = Telegram не принял, Alertmanager повторит."""
    key = str(payload.get("groupKey") or "")
    alerts: list[dict[str, Any]] = payload.get("alerts", [])
    firing = [a for a in alerts if a.get("status") == "firing"]
    with store.lock:
        sent = store.data.get(key, []) if key else []
        if not firing:
            for msg in sent:
                mine = [a for a in alerts if a.get("fingerprint") in msg.get("fps", [])] or alerts
                rich_html, plain = cards(mine, resolved=True)
                if not edit(target, int(msg["id"]), bool(msg.get("rich")), rich_html, plain):
                    print(f"card {msg['id']}: resolved edit failed", file=sys.stderr)
            if sent:
                store.data.pop(key, None)
                store.save()
            return True
        fps = sorted(str(a.get("fingerprint", "")) for a in firing)
        known = {fp for msg in sent for fp in msg.get("fps", [])}
        if known and set(fps) <= known:
            return True
        rich_html, plain = cards(firing)
        res = send(target, rich_html, plain, silence_markup(firing) if buttons else None)
        if res is None:
            return False
        message_id, rich = res
        if key and message_id:
            store.data[key] = [*sent, {"id": message_id, "rich": rich, "fps": fps}]
            store.save()
        return True


def serve(target: Target, store: Store, listen: str, *, buttons: bool) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 (http.server API)
            try:
                payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            except (ValueError, json.JSONDecodeError):
                self.send_error(400, "bad json")
                return
            ok = handle(target, store, payload, buttons=buttons)
            # non-2xx makes Alertmanager retry the notification
            self.send_response(200 if ok else 502)
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (имя из http.server)
            print(f"{self.address_string()} {format % args}", file=sys.stderr)

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
    store = Store.load(os.environ.get("TG_STATE_FILE", "/data/messages.json"))
    buttons = os.environ.get("TG_BUTTONS", "") == "1"
    serve(target, store, os.environ.get("LISTEN", ":8080"), buttons=buttons)
    return 0


if __name__ == "__main__":
    sys.exit(main())
