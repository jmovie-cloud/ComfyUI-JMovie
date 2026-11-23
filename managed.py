"""Device authorization and media tasks on the JMovie production-platform contract."""

import asyncio
from dataclasses import dataclass, field
import os
from threading import Lock
from time import monotonic

from aiohttp import web
from comfy.cli_args import args
from yarl import URL

from .tasks import run_task
from .transport import RequestError, client, request, request_json


CLIENT_ID = "jmovie-cloud"
SCOPES = {"image:generate", "video:generate", "tasks:read"}
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
API = "/api/v1/comfy"
MAX_LIFETIME = 86400


def local_comfy():
    return (
        not args.multi_user
        and args.enable_cors_header is None
        and all(host.strip() in LOOPBACK for host in args.listen.split(","))
    )


def platform():
    raw = os.environ.get("JMOVIE_CLOUD_BASE_URL", "").strip()
    if not raw:
        raise RuntimeError("JMovie connection is disabled. Set JMOVIE_CLOUD_BASE_URL on the ComfyUI server.")
    try:
        url = URL(raw)
        if (
            not url.host or url.user is not None or url.path != "/" or url.query_string or url.fragment
            or (url.scheme != "https" and not (url.scheme == "http" and url.host in LOOPBACK))
            or url.host == "api.j-movie.com"
        ):
            raise ValueError()
        return str(url.origin())
    except ValueError:
        raise RuntimeError("Use a JMovie production-platform HTTPS origin or an HTTP loopback test origin.") from None


@dataclass(frozen=True)
class Grant:
    origin: str
    account_id: str
    expires_at: float
    token: str = field(repr=False)


@dataclass
class Device:
    origin: str
    code: str = field(repr=False)
    user_code: str
    verification_url: str
    expires_at: float
    interval: int
    next_poll: float


def seconds(body, key, maximum, default=None):
    value = body.get(key, default)
    if type(value) is not int or not 1 <= value <= maximum:
        raise RuntimeError("The platform returned an invalid authorization lifetime.")
    return value


class Connection:
    def __init__(self):
        self._device = None
        self._grant = None
        self._grant_lock = Lock()
        self._device_lock = asyncio.Lock()

    def current(self):
        with self._grant_lock:
            if self._grant is not None and self._grant.expires_at <= monotonic():
                self._grant = None
            return self._grant

    def clear(self, grant):
        with self._grant_lock:
            if self._grant is grant:
                self._grant = None

    async def start(self):
        async with self._device_lock:
            if self.current():
                return {"state": "connected"}
            origin = platform()
            if self._device is None or self._device.expires_at <= monotonic():
                async with client(15) as session:
                    _, body = await request_json(
                        session, "POST", f"{origin}{API}/oauth/device/code",
                        data={"client_id": CLIENT_ID, "scope": " ".join(sorted(SCOPES))},
                    )
                code = body.get("device_code")
                user_code = body.get("user_code")
                verification = body.get("verification_uri")
                if (
                    not isinstance(code, str) or not 1 <= len(code) <= 1024
                    or not isinstance(user_code, str) or not 1 <= len(user_code) <= 32
                    or not isinstance(verification, str)
                ):
                    raise RuntimeError("The platform returned an invalid device code.")
                try:
                    verified_url = URL(verification)
                    if verified_url.user is not None or str(verified_url.origin()) != origin:
                        raise ValueError()
                except ValueError:
                    raise RuntimeError("The authorization page must be on the configured JMovie platform.") from None
                interval = seconds(body, "interval", 60, 5)
                expires_at = monotonic() + seconds(body, "expires_in", 1800)
                self._device = Device(
                    origin, code, user_code, str(verified_url), expires_at, interval, monotonic() + interval,
                )
            return {
                "state": "pending", "user_code": self._device.user_code,
                "verification_url": self._device.verification_url,
            }

    async def poll(self):
        async with self._device_lock:
            grant = self.current()
            if grant:
                await self._check(grant)
                return {"state": "connected" if self.current() else "disconnected"}
            device = self._device
            if device is None:
                return {"state": "disconnected"}
            if device.expires_at <= monotonic():
                self._device = None
                return {"state": "expired"}
            if device.next_poll > monotonic():
                return {"state": "pending"}
            async with client(15) as session:
                device.next_poll = monotonic() + device.interval
                status, body = await request_json(
                    session, "POST", f"{device.origin}{API}/oauth/token", statuses=(200, 400),
                    data={"client_id": CLIENT_ID, "device_code": device.code, "grant_type": DEVICE_GRANT},
                )
            device.next_poll = monotonic() + device.interval
            if status == 400:
                error = body.get("error")
                if error == "slow_down":
                    device.interval += 5
                    device.next_poll = monotonic() + device.interval
                elif error == "access_denied" or error == "expired_token":
                    self._device = None
                    return {"state": "denied" if error == "access_denied" else "expired"}
                elif error != "authorization_pending":
                    self._device = None
                    raise RuntimeError("JMovie rejected the device authorization.")
                return {"state": "pending"}
            self._device = None
            token = body.get("access_token")
            scope = body.get("scope")
            account = body.get("account_id")
            if (
                not isinstance(token, str) or not 1 <= len(token) <= 8192
                or not token.isascii() or not token.isprintable() or " " in token
                or not isinstance(account, str) or not 1 <= len(account) <= 160
                or not isinstance(scope, str) or set(scope.split()) != SCOPES
                or str(body.get("token_type")).lower() != "bearer"
            ):
                raise RuntimeError("JMovie did not return a scoped plugin grant.")
            expires_at = monotonic() + seconds(body, "expires_in", MAX_LIFETIME)
            with self._grant_lock:
                self._grant = Grant(device.origin, account, expires_at, token)
            return {"state": "connected"}

    async def _check(self, grant):
        try:
            async with client(15) as session:
                await request(session, "GET", f"{grant.origin}{API}/connection", token=grant.token)
        except RequestError as error:
            if error.status in {401, 403}:
                self.clear(grant)
            else:
                raise

    async def disconnect(self):
        async with self._device_lock:
            grant = self.current()
            if grant:
                async with client(15) as session:
                    await request(
                        session, "POST", f"{grant.origin}{API}/oauth/revoke",
                        data={"client_id": CLIENT_ID, "token": grant.token}, statuses=(200, 204),
                    )
                self.clear(grant)
            self._device = None
            return {"state": "disconnected"}


connection = Connection()


def add_routes(server):
    async def connection_action(request):
        try:
            local_origin = URL(f"{request.scheme}://{request.host}")
            if (
                not local_comfy() or local_origin.host not in LOOPBACK
                or request.remote not in {"127.0.0.1", "::1"}
                or request.headers.get("Origin") != str(local_origin.origin())
                or request.headers.get("Sec-Fetch-Site", "same-origin") != "same-origin"
            ):
                raise ValueError()
        except ValueError:
            raise web.HTTPForbidden()
        action = {"start": connection.start, "poll": connection.poll, "disconnect": connection.disconnect}
        handler = action.get(request.match_info["action"])
        if handler is None:
            raise web.HTTPNotFound()
        headers = {"Cache-Control": "no-store"}
        try:
            return web.json_response(await handler(), headers=headers)
        except RuntimeError as error:
            return web.json_response({"error": str(error)}, status=400, headers=headers)

    server.routes.post("/jmovie-cloud/connection/{action}")(connection_action)


async def managed_media(kind, payload, limit, run_number=0, resume_id=""):
    if not local_comfy():
        raise RuntimeError("JMovie account access requires a single-user loopback ComfyUI server.")
    grant = connection.current()
    if grant is None:
        raise RuntimeError("Use Connect JMovie to authorize this ComfyUI server.")
    base = f"{grant.origin}{API}/tasks"
    async with client(120) as session:
        async def authorized(fetch, method, url, **kwargs):
            try:
                return await fetch(session, method, url, token=grant.token, **kwargs)
            except RequestError as error:
                if error.status == 401:
                    connection.clear(grant)
                raise

        async def submit(key):
            _, body = await authorized(
                request_json, "POST", base, headers={"Idempotency-Key": key},
                json={"kind": kind, **payload}, statuses=(200, 201, 202),
            )
            return body.get("id")

        async def query(task):
            _, body = await authorized(request_json, "GET", f"{base}/{task}")
            if body.get("kind") != kind:
                raise RuntimeError("The JMovie task is for a different media type.")
            return body.get("status"), task

        async def download(task):
            _, media = await authorized(request, "GET", f"{base}/{task}/result", limit=limit)
            return media

        return await run_task(
            scope=(grant.origin, grant.account_id, kind), payload=payload, run_number=run_number,
            resume_id=resume_id, submit=submit, query=query, download=download, idempotent=True,
        )
