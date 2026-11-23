"""Bounded HTTP for cloud media. Provider bodies and URLs stay out of errors."""

import json
import os

import aiohttp


class RequestError(RuntimeError):
    def __init__(self, status=None):
        self.status = status
        if status is None:
            super().__init__("Cloud request interrupted or returned an invalid response.")
        else:
            super().__init__(f"Cloud request returned HTTP {status}.")


def api_key(name):
    key = os.environ.get(name, "").strip()
    if not key:
        raise RuntimeError(f"Set {name} in the ComfyUI server environment.")
    return key


def client(timeout=45, *, connector=None):
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        cookie_jar=aiohttp.DummyCookieJar(),
        connector=connector,
    )


async def request(session, method, url, *, token=None, limit=512 * 1024, statuses=(200,), **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with session.request(method, url, headers=headers, allow_redirects=False, **kwargs) as response:
            if response.status not in statuses:
                raise RequestError(response.status)
            if response.content_length is not None and response.content_length > limit:
                raise RequestError()
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > limit:
                    raise RequestError()
            return response.status, bytes(data)
    except (aiohttp.ClientError, TimeoutError, ValueError):
        raise RequestError() from None


async def request_json(session, method, url, **kwargs):
    status, raw = await request(session, method, url, **kwargs)
    try:
        body = json.loads(raw)
        if isinstance(body, dict):
            return status, body
    except (ValueError, RecursionError):
        pass
    raise RequestError()
