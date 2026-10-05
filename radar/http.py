"""Tiny HTTP helpers on top of the standard library (no pip install needed)."""
import gzip
import json
import time
from urllib.error import HTTPError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
TIMEOUT = 25


def _request(url, data=None, headers=None, method=None, retries=2):
    h = {"User-Agent": UA, "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode() if not isinstance(data, bytes) else data
        h.setdefault("Content-Type", "application/json")
    last = None
    for attempt in range(retries + 1):
        try:
            r = urlopen(Request(url, data=body, headers=h, method=method), timeout=TIMEOUT)
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(r.headers.get_content_charset() or "utf-8", "replace")
        except HTTPError as e:
            last = e
            if e.code == 308 and e.headers.get("Location") and data is None:  # Python 3.9 doesn't follow 308
                url = urljoin(url, e.headers["Location"])
                continue
            if e.code in (400, 401, 403, 404, 405, 410, 422):
                break  # no point retrying
        except Exception as e:  # timeouts, resets...
            last = e
        time.sleep(1.5 * (attempt + 1))
    raise last


def get_text(url, headers=None):
    return _request(url, headers=headers)


def get_json(url, headers=None):
    h = {"Accept": "application/json"}
    h.update(headers or {})
    return json.loads(_request(url, headers=h))


def post_json(url, data, headers=None):
    h = {"Accept": "application/json"}
    h.update(headers or {})
    return json.loads(_request(url, data=data, headers=h, method="POST"))
