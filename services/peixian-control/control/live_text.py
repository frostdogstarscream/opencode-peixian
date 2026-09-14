"""Bounded transient assistant-text overlay; never a message/history store.

One native stream owner per account preserves wire delta order. Event identifiers
are used only for deduplication, not sorting. A stream handover discards unfinished
text because native delta events have no replay guarantee.
"""
from collections import OrderedDict
from dataclasses import dataclass
from threading import RLock
import re
import time

RESOURCE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
EVENT = re.compile(r"^evt_[A-Za-z0-9_-]{1,128}$")


def valid_id(value):
    return isinstance(value, str) and RESOURCE.fullmatch(value) is not None


def completed(value):
    timing = value.get("time")
    return bool(value.get("error")) or (isinstance(timing, dict) and timing.get("completed") is not None)


@dataclass
class Part:
    text: str
    size: int
    touched: float


class LiveTextCache:
    def __init__(self, *, max_part_bytes=256 * 1024, max_total_bytes=4 * 1024 * 1024,
                 max_account_bytes=1024 * 1024, max_parts=128, max_messages=256,
                 max_seen_events=8192, max_owners=32, ttl_seconds=300,
                 owner_ttl_seconds=15, clock=time.monotonic):
        limits = (max_part_bytes, max_total_bytes, max_account_bytes, max_parts,
                  max_messages, max_seen_events, max_owners, ttl_seconds, owner_ttl_seconds)
        if any(not isinstance(value, (int, float)) or value <= 0 for value in limits):
            raise ValueError("Cache bounds must be positive")
        self.max_part_bytes, self.max_total_bytes = max_part_bytes, max_total_bytes
        self.max_account_bytes, self.max_parts = max_account_bytes, max_parts
        self.max_messages, self.max_seen_events, self.max_owners = max_messages, max_seen_events, max_owners
        self.ttl, self.owner_ttl, self.clock = ttl_seconds, owner_ttl_seconds, clock
        self.parts, self.messages, self.seen, self.owners = (OrderedDict() for _ in range(4))
        self.account_bytes = {}
        self.total_bytes = 0
        self.lock = RLock()

    def _drop_part(self, key):
        previous = self.parts.pop(key, None)
        if previous is not None:
            self.total_bytes -= previous.size
            remaining = self.account_bytes.get(key[0], 0) - previous.size
            if remaining:
                self.account_bytes[key[0]] = remaining
            else:
                self.account_bytes.pop(key[0], None)

    def _drop_message(self, key):
        self.messages.pop(key, None)
        for part_key in list(self.parts):
            if part_key[:3] == key:
                self._drop_part(part_key)

    def _clear_account(self, uid):
        for key in list(self.parts):
            if key[0] == uid:
                self._drop_part(key)
        for mapping in (self.messages, self.seen):
            for key in list(mapping):
                if key[0] == uid:
                    mapping.pop(key, None)

    def _purge(self, now):
        for uid, (_, touched) in list(self.owners.items()):
            if now - touched >= self.owner_ttl:
                self.owners.pop(uid, None)
                self._clear_account(uid)
        for key, part in list(self.parts.items()):
            if now - part.touched >= self.ttl:
                self._drop_part(key)
        for key, (_, touched) in list(self.messages.items()):
            if now - touched >= self.ttl:
                self._drop_message(key)
        while self.seen:
            key, touched = next(iter(self.seen.items()))
            if now - touched < self.ttl:
                break
            self.seen.pop(key)

    def acquire(self, uid, stream_id):
        """Acquire or renew the account's single feeder; call during heartbeats."""
        if not valid_id(uid) or not valid_id(stream_id):
            return False
        with self.lock:
            now = self.clock()
            self._purge(now)
            owner = self.owners.get(uid)
            if owner is not None and owner[0] != stream_id:
                return False
            if owner is None:
                if len(self.owners) >= self.max_owners:
                    return False
                # Never splice an unobserved stream interval onto an old prefix.
                self._clear_account(uid)
            self.owners[uid] = (stream_id, now)
            return True

    def release(self, uid, stream_id):
        """Release only this feeder, discarding incomplete account text."""
        with self.lock:
            owner = self.owners.get(uid)
            if owner is not None and owner[0] == stream_id:
                self.owners.pop(uid)
                self._clear_account(uid)

    def _remember(self, uid, event_id, now):
        key = (uid, event_id)
        if key in self.seen:
            return False
        self.seen[key] = now
        while len(self.seen) > self.max_seen_events:
            self.seen.popitem(last=False)
        return True

    def _put(self, key, text, now):
        if len(text) > self.max_part_bytes:
            self._drop_part(key)
            return False
        size = len(text.encode("utf-8"))
        if size > min(self.max_part_bytes, self.max_account_bytes, self.max_total_bytes):
            self._drop_part(key)
            return False
        self._drop_part(key)
        while self.parts and (len(self.parts) >= self.max_parts
                              or self.total_bytes + size > self.max_total_bytes):
            self._drop_part(next(iter(self.parts)))
        while self.account_bytes.get(key[0], 0) + size > self.max_account_bytes:
            victim = next((item for item in self.parts if item[0] == key[0]), None)
            if victim is None:
                return False
            self._drop_part(victim)
        self.parts[key] = Part(text, size, now)
        self.total_bytes += size
        self.account_bytes[key[0]] = self.account_bytes.get(key[0], 0) + size
        return True

    def observe(self, uid, envelope, stream_id):
        """Accept only known assistant text from the current owner's native stream."""
        if not isinstance(envelope, dict) or envelope.get("directory") != "/workspace":
            return False
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            return False
        event_id, kind, props = payload.get("id"), payload.get("type"), payload.get("properties")
        if (not isinstance(event_id, str) or not EVENT.fullmatch(event_id)
                or kind not in ("message.updated", "message.part.updated", "message.part.delta")
                or not isinstance(props, dict)):
            return False
        with self.lock:
            now = self.clock()
            self._purge(now)
            owner = self.owners.get(uid)
            if owner is None or owner[0] != stream_id:
                return False
            self.owners[uid] = (stream_id, now)
            if not self._remember(uid, event_id, now):
                return False
            sid = props.get("sessionID")
            if not valid_id(sid):
                return False
            if kind == "message.updated":
                info = props.get("info")
                if not isinstance(info, dict) or info.get("sessionID") != sid or not valid_id(info.get("id")):
                    return False
                key = (uid, sid, info["id"])
                allowed = info.get("role") == "assistant" and not completed(info)
                if not allowed:
                    self._drop_message(key)
                self.messages[key] = (allowed, now)
                self.messages.move_to_end(key)
                while len(self.messages) > self.max_messages:
                    self._drop_message(next(iter(self.messages)))
                return allowed
            if kind == "message.part.updated":
                part = props.get("part")
                if (not isinstance(part, dict) or part.get("sessionID") != sid
                        or not valid_id(part.get("messageID")) or not valid_id(part.get("id"))):
                    return False
                key = (uid, sid, part["messageID"], part["id"])
                timing = part.get("time")
                if (part.get("type") != "text" or part.get("synthetic") is True or part.get("ignored") is True
                        or not isinstance(part.get("text"), str)
                        or (isinstance(timing, dict) and timing.get("end") is not None)):
                    self._drop_part(key)
                    return False
                message = self.messages.get(key[:3])
                if message is None or not message[0]:
                    return False
                return self._put(key, part["text"], now)
            mid, pid, delta = props.get("messageID"), props.get("partID"), props.get("delta")
            if not valid_id(mid) or not valid_id(pid) or props.get("field") != "text" or not isinstance(delta, str):
                return False
            key = (uid, sid, mid, pid)
            part = self.parts.get(key)
            message = self.messages.get(key[:3])
            if part is None or message is None or not message[0]:
                return False
            if not delta:
                return False
            if len(delta) > self.max_part_bytes:
                self._drop_part(key)
                return False
            if part.size + len(delta.encode("utf-8")) > self.max_part_bytes:
                self._drop_part(key)
                return False
            self.messages[key[:3]] = (True, now)
            self.messages.move_to_end(key[:3])
            return self._put(key, part.text + delta, now)

    def overlay(self, uid, sid, values):
        """Overlay existing native assistant/text parts only; native completion wins.

        Caller must first verify session ownership. The result preserves native
        completion/role metadata and must still pass through public_messages.
        """
        if not valid_id(uid) or not valid_id(sid) or not isinstance(values, list):
            return values
        with self.lock:
            self._purge(self.clock())
            result = list(values)
            for index, value in enumerate(values):
                if not isinstance(value, dict):
                    continue
                info, native_parts = value.get("info"), value.get("parts")
                if (not isinstance(info, dict) or info.get("sessionID") != sid
                        or not valid_id(info.get("id")) or not isinstance(native_parts, list)):
                    continue
                message_key = (uid, sid, info["id"])
                if info.get("role") != "assistant" or completed(info):
                    self._drop_message(message_key)
                    continue
                copied_parts = None
                for part_index, native in enumerate(native_parts):
                    if not isinstance(native, dict) or not valid_id(native.get("id")):
                        continue
                    key = (*message_key, native["id"])
                    if native.get("sessionID") != sid or native.get("messageID") != info["id"]:
                        continue
                    timing = native.get("time")
                    if (native.get("type") != "text" or native.get("synthetic") is True or native.get("ignored") is True
                            or (isinstance(timing, dict) and timing.get("end") is not None)):
                        self._drop_part(key)
                        continue
                    part = self.parts.get(key)
                    text = native.get("text")
                    if part is None or not isinstance(text, str):
                        continue
                    if text and (len(text) >= len(part.text) or not part.text.startswith(text)):
                        self._drop_part(key)
                        continue
                    if len(part.text) <= len(text):
                        continue
                    if copied_parts is None:
                        copied_parts = list(native_parts)
                    copied_parts[part_index] = {**native, "text": part.text}
                if copied_parts is not None:
                    result[index] = {**value, "parts": copied_parts}
            return result

    def stats(self):
        """Non-sensitive counts for tests/diagnostics; never returns text or IDs."""
        with self.lock:
            self._purge(self.clock())
            return {"parts": len(self.parts), "messages": len(self.messages), "seen_events": len(self.seen),
                    "owners": len(self.owners), "text_bytes": self.total_bytes,
                    "maximum_account_bytes": max(self.account_bytes.values(), default=0)}
