"""Deliver original supplier output without forwarding the JMovie grant."""

import base64
import binascii
import ipaddress
import re

import aiohttp
from aiohttp.abc import AbstractResolver
from aiohttp.resolver import DefaultResolver
from yarl import URL

from .tasks import ResultExpired
from .transport import RequestError, client, request


DNS_NAME = re.compile(r"(?:[A-Za-z0-9-]+\.)+[A-Za-z][A-Za-z0-9-]*")


def public_address(address):
    return address.is_global and not address.is_multicast and not address.is_reserved


class PublicResolver(AbstractResolver):
    async def resolve(self, host, port=0, family=0):
        resolver = DefaultResolver()
        try:
            addresses = await resolver.resolve(host, port, family)
            if not addresses or any(not public_address(ipaddress.ip_address(item["host"])) for item in addresses):
                raise OSError("The supplier did not resolve to a public address.")
            return addresses
        finally:
            await resolver.close()

    async def close(self):
        pass


def supplier_url(raw):
    try:
        url = URL(raw, encoded=True)
        if (
            url.scheme != "https" or not url.host or url.user is not None or url.raw_fragment
            or url.port != 443 or "%" in url.host or "\\" in raw or any(ord(character) < 33 for character in raw)
        ):
            raise ValueError()
        # aiohttp bypasses its resolver for numeric addresses.
        try:
            address = ipaddress.ip_address(url.host)
        except ValueError:
            if DNS_NAME.fullmatch(url.host):
                return url
        else:
            if public_address(address):
                return url
    except (TypeError, ValueError):
        pass
    raise RequestError()


async def supplier_media(result, limit):
    encoded, link = result.get("base64"), result.get("url")
    if isinstance(encoded, str) and link is None:
        if len(encoded) > 4 * ((limit + 2) // 3):
            raise RequestError()
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise RequestError() from None
        if data and len(data) <= limit:
            return data
    if isinstance(link, str) and encoded is None and len(link) <= 16384:
        url = supplier_url(link)
        try:
            async with client(120, connector=aiohttp.TCPConnector(resolver=PublicResolver())) as session:
                _, data = await request(session, "GET", url, limit=limit)
                if data:
                    return data
        except RequestError as error:
            if error.status in {403, 404, 410}:
                raise ResultExpired() from None
            raise
    raise RequestError()
