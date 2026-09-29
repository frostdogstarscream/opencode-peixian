"""Police-facing live prose for table runs: the Chinese text a model writes before its JSON answer.

Only the prose before the first JSON/code start is shown; person references are revealed with
the run's identity mapping, and an unfinished reference at the end of an open part is held back.
"""
import re
import time

from .display_identity import reveal

JSON_START = re.compile(r'```|^[ \t]*[{\[]', re.M)
OPEN_TAIL = re.compile(r'(?:`{1,2}|p(?:e(?:r(?:s(?:o(?:n(?:-[0-9a-f]{0,31})?)?)?)?)?)?)$')
CJK = re.compile(r'[\u4e00-\u9fff]')
LATIN = re.compile(r'[A-Za-z]')
MIN_CJK_RATIO = 0.3
COMPOSING = ('composing', '正在整理结果…')


def visible(text, identities, open_part=False):
    """Return (displayable prose, whether the JSON answer has started)."""
    if not isinstance(text, str):
        return '', False
    match = JSON_START.search(text)
    body = text[:match.start()] if match else text
    if open_part and not match:
        body = OPEN_TAIL.sub('', body)
    body = reveal(body, identities).rstrip()
    cjk, latin = len(CJK.findall(body)), len(LATIN.findall(body))
    if not cjk or cjk / (cjk + latin) < MIN_CJK_RATIO:
        body = ''
    return body, match is not None


class Pushes:
    """Bounded per-part record of what was already pushed, so each delta carries only new prose."""

    def __init__(self, max_parts=512, ttl_seconds=900, clock=time.monotonic):
        self.max_parts, self.ttl, self.clock = max_parts, ttl_seconds, clock
        self.parts = {}
        self.targets = {}

    def target(self, uid, mid, value=None):
        key = (uid, mid)
        if value is not None:
            self.targets[key] = (value, self.clock())
            while len(self.targets) > self.max_parts:
                self.targets.pop(next(iter(self.targets)))
        entry = self.targets.get(key)
        if entry and self.clock() - entry[1] > self.ttl:
            self.targets.pop(key, None)
            return None
        return entry[0] if entry else None

    def forget(self, uid, mid):
        self.targets.pop((uid, mid), None)
        for key in [k for k in self.parts if k[:2] == (uid, mid)]:
            self.parts.pop(key)

    def advance(self, uid, mid, pid, body, composing):
        """(offset, new text, composing just started) or None when nothing new can be appended."""
        key = (uid, mid, pid)
        pushed, was_composing = self.parts.get(key, ('', False))
        started = composing and not was_composing
        if not body.startswith(pushed):
            self.parts[key] = (pushed, was_composing or composing)
            return (len(pushed), '', started) if started else None
        self.parts[key] = (body, was_composing or composing)
        while len(self.parts) > self.max_parts:
            self.parts.pop(next(iter(self.parts)))
        if len(body) == len(pushed) and not started:
            return None
        return len(pushed), body[len(pushed):], started
