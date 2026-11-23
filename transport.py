"""Bounded HTTP for cloud media. Provider bodies and URLs stay out of errors."""

import ipaddress
import json
import os
import socket

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL


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


def client(timeout=45):
    return aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        cookie_jar=aiohttp.DummyCookieJar(),
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


class PublicResolver(AbstractResolver):
    def __init__(self):
        self.resolver = aiohttp.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        results = await self.resolver.resolve(host, port, family)
        if not results or any(not ipaddress.ip_address(item["host"]).is_global for item in results):
            raise OSError("Non-public download address")
        return results

    async def close(self):
        await self.resolver.close()


async def download_public(raw_url, limit):
    try:
        url = URL(raw_url, encoded=True)
        host = url.host
        if url.scheme != "https" or not host or url.user is not None or url.port != 443:
            raise ValueError()
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError()
    except (ValueError, TypeError):
        raise RuntimeError("The provider did not return a public HTTPS result URL.") from None

    resolver = PublicResolver()
    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=resolver),
            timeout=aiohttp.ClientTimeout(total=180),
            cookie_jar=aiohttp.DummyCookieJar(),
        ) as session:
            _, data = await request(session, "GET", url, limit=limit)
            return data
    finally:
        await resolver.close()
