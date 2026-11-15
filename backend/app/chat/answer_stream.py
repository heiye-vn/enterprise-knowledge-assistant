"""Expose only the top-level JSON answer string while the provider is streaming."""

import json


class AnswerDecoder:
    def __init__(self):
        self.depth, self.in_string, self.escaped = 0, False, False
        self.expect_key, self.key, self.kind = True, None, None
        self.token, self.encoded, self.text = "", "", ""
        self.started, self.ended, self.size = False, False, 0

    def feed(self, chunk):
        self.size += len(chunk)
        if self.size > 100_000:
            raise ValueError("回答超出流式内容限制")
        for char in chunk:
            if self.in_string:
                if not self.escaped and char == '"':
                    self.in_string = False
                    if self.kind == "key":
                        self.key = json.loads('"' + self.token + '"')
                    elif self.kind == "answer":
                        self.ended = True
                    continue
                if self.kind == "key":
                    self.token += char
                elif self.kind == "answer":
                    self.encoded += char
                if self.escaped:
                    self.escaped = False
                elif char == "\\":
                    self.escaped = True
                continue
            if char == '"':
                self.in_string, self.escaped, self.token = True, False, ""
                self.kind = "key" if self.depth == 1 and self.expect_key else "other"
                if self.depth == 1 and not self.expect_key and self.key == "answer":
                    if self.started:
                        raise ValueError("回答包含重复正文")
                    self.kind, self.started = "answer", True
            elif char in "{[":
                self.depth += 1
                if self.depth == 1:
                    self.expect_key = True
            elif char in "}]":
                self.depth -= 1
            elif char == "," and self.depth == 1:
                self.expect_key, self.key = True, None
            elif char == ":" and self.depth == 1:
                self.expect_key = False
        # A network block may end inside an escape (at most six encoded characters).
        for trim in range(min(6, len(self.encoded)) + 1):
            encoded = self.encoded[: len(self.encoded) - trim] if trim else self.encoded
            try:
                decoded = json.loads('"' + encoded + '"')
                if decoded and 0xD800 <= ord(decoded[-1]) <= 0xDBFF:
                    decoded = decoded[:-1]
                decoded.encode("utf-8")
            except (ValueError, UnicodeError):
                continue
            if not decoded.startswith(self.text):
                raise ValueError("流式回答正文不一致")
            delta, self.text = decoded[len(self.text) :], decoded
            return delta
        return ""
