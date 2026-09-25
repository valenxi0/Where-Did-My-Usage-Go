"""Block an export whose visible text looks like it leaks a secret or personal detail."""

import re

PATTERNS = {
    "API key or token": re.compile(r"\b(sk-(ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}"
                                   r"|xox[abprs]-[\w-]{10,}|AKIA[0-9A-Z]{16}|AIza[\w-]{30,}|eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,})"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "email address": re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}\b", re.I),
    "home folder path": re.compile(r"(/Users/|/home/|[A-Z]:\\Users\\)[^\s/\\]+"),
    "IP address": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
}


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)


def findings(card):
    """Return (kind, masked match) pairs for every suspicious string the card will show."""
    found = []
    for value in strings(card):
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(value):
                text = match.group(0)
                found.append((kind, text[:4] + "…" + text[-2:] if len(text) > 8 else "…"))
    return found
