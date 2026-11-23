"""Synthetic providers and a local JMovie consent, tasks, pricing and usage fixture."""

import argparse
import base64
from collections import Counter
from io import BytesIO
from pathlib import Path
import secrets

from aiohttp import web
from PIL import Image


API = "/api/v1/comfy"
SCOPES = {"image:generate", "video:generate", "audio:generate", "tasks:read"}


def image_bytes(size):
    buffer = BytesIO()
    Image.new("RGB", size, "#2566a8").save(buffer, "PNG")
    return buffer.getvalue()


class MockPlatform:
    def __init__(self, fixtures):
        self.video = (fixtures / "movie.mp4").read_bytes()
        self.audio = (fixtures / "audio.wav").read_bytes()
        self.image = image_bytes((320, 320))
        self.tasks = {}
        self.idempotency = {}
        self.device = None
        self.grant = None
        self.cost = 0
        self.expire_video = False
        self.counts = Counter()
        self.routes = web.RouteTableDef()
        self.routes.post(API + "/oauth/device/code")(self.device_code)
        self.routes.post(API + "/oauth/token")(self.device_token)
        self.routes.post(API + "/oauth/revoke")(self.revoke)
        self.routes.get(API + "/connection")(self.connection)
        self.routes.post(API + "/tasks")(self.submit_managed)
        self.routes.get(API + "/tasks/{task}")(self.query_managed)
        self.routes.get(API + "/tasks/{task}/result")(self.result)
        self.routes.get("/authorize")(self.authorization)
        self.routes.post("/authorize")(self.authorization)
        self.routes.post("/permissions/revoke")(self.browser_revoke)
        self.routes.route("*", "/provider/{provider}/{path:.*}")(self.provider)
        self.routes.get("/stats")(self.stats)
        self.routes.get("/supplier/video")(self.supplier_video)
        self.routes.post("/supplier/expire")(self.expire_supplier_video)

    async def device_code(self, request):
        form = await request.post()
        assert form["client_id"] == "jmovie-cloud" and set(form["scope"].split()) == SCOPES
        self.device = {"code": secrets.token_urlsafe(24), "approved": False, "used": False}
        return web.json_response({
            "device_code": self.device["code"], "user_code": "JMV-2206",
            "verification_uri": f"http://{request.host}/authorize", "interval": 1, "expires_in": 300,
        })

    async def device_token(self, request):
        form = await request.post()
        assert form["client_id"] == "jmovie-cloud"
        assert form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code"
        if self.device is None or form["device_code"] != self.device["code"] or self.device["used"]:
            return web.json_response({"error": "expired_token"}, status=400)
        if not self.device["approved"]:
            self.counts["authorization_pending"] += 1
            return web.json_response({"error": "authorization_pending"}, status=400)
        self.device["used"] = True
        self.grant = secrets.token_urlsafe(32)
        return web.json_response({
            "access_token": self.grant, "token_type": "Bearer", "scope": " ".join(sorted(SCOPES)),
            "expires_in": 3600, "account_id": "local-production-account",
        })

    async def authorization(self, request):
        if request.method == "POST":
            form = await request.post()
            if form.get("user_code") == "JMV-2206" and request.cookies.get("mock_login") == "signed-in":
                self.device["approved"] = True
                return web.Response(text="Authorized. Return to ComfyUI.")
            if form.get("account") != "test-creator" or form.get("password") != "test-password":
                raise web.HTTPUnauthorized()
            response = web.Response(text="""
                <!doctype html><title>JMovie local consent</title><h1>Authorize JMovie Cloud</h1>
                <p>Generate images, video and audio, and read plugin tasks on the test API account.</p>
                <form method="post"><label>Device code <input name="user_code"></label>
                <button>Authorize</button></form>
            """, content_type="text/html")
            response.set_cookie("mock_login", "signed-in", path="/authorize", httponly=True, samesite="Strict")
            return response
        return web.Response(text="""
            <!doctype html><title>JMovie local sign-in</title><h1>Sign in to JMovie (local fixture)</h1>
            <form method="post"><label>Account <input name="account"></label>
            <label>Password <input name="password" type="password"></label><button>Sign in</button></form>
        """, content_type="text/html")

    async def revoke(self, request):
        form = await request.post()
        if form["client_id"] == "jmovie-cloud" and form["token"] == self.grant:
            self.grant = None
        return web.Response(status=204)

    async def browser_revoke(self, request):
        self.grant = None
        return web.Response(status=204)

    def require_grant(self, request):
        if not self.grant or request.headers.get("Authorization") != f"Bearer {self.grant}":
            raise web.HTTPUnauthorized()

    async def connection(self, request):
        self.require_grant(request)
        return web.json_response({"active": True})

    def create_task(self, service, kind):
        identifier = f"{service}-{len(self.tasks) + 1}"
        self.tasks[identifier] = {"service": service, "kind": kind, "polls": 0}
        self.counts[f"{service}_submit"] += 1
        return identifier

    async def submit_managed(self, request):
        self.require_grant(request)
        payload = await request.json()
        kind = payload.get("kind")
        assert kind in {"image", "video", "audio"} and payload["prompt"]
        if payload["model"] == "MiniMax-H3":
            assert kind == "video" and payload["resolution"] in {"768P", "2K"}
            assert 4 <= payload["duration"] <= 15
        if payload["model"] == "gpt-image-2.5-flare":
            assert kind == "image" and "reference_image" not in payload
        if kind == "audio":
            assert payload["model"] == "seed-audio-1.0" and 1 <= payload["duration"] <= 120
        key = request.headers["Idempotency-Key"]
        if key not in self.idempotency:
            self.idempotency[key] = self.create_task("jmovie", kind)
            self.cost += {"image": 2, "video": 7, "audio": 3}[kind]
            if payload["prompt"] == "simulate-unknown":
                raise web.HTTPServiceUnavailable()
        return web.json_response({"id": self.idempotency[key]}, status=201)

    def lookup(self, task_id, service):
        task = self.tasks.get(task_id)
        if task is None or task["service"] != service:
            raise web.HTTPNotFound()
        return task

    async def query_managed(self, request):
        self.require_grant(request)
        task = self.lookup(request.match_info["task"], "jmovie")
        task["polls"] += 1
        return web.json_response({
            "kind": task["kind"], "status": "succeeded" if task["polls"] >= 2 else "queued",
        })

    async def result(self, request):
        self.require_grant(request)
        task = self.lookup(request.match_info["task"], "jmovie")
        assert task["polls"] >= 2
        if task["kind"] == "video":
            return web.json_response({"url": "https://video.supplier.example/video?token=a%2Bb%2Fc"})
        data = {"image": self.image, "audio": self.audio}[task["kind"]]
        return web.json_response({"base64": base64.b64encode(data).decode()})

    async def supplier_video(self, request):
        assert "Authorization" not in request.headers and "Cookie" not in request.headers
        assert request.raw_path.endswith("?token=a%2Bb%2Fc")
        if self.expire_video:
            raise web.HTTPGone()
        self.counts["supplier_video"] += 1
        return web.Response(body=self.video, content_type="video/mp4")

    async def expire_supplier_video(self, request):
        self.expire_video = True
        return web.Response(status=204)

    async def stats(self, _request):
        return web.json_response({"counts": dict(self.counts), "cost": self.cost, "tasks": list(self.tasks)})

    async def provider(self, request):
        assert request.match_info["provider"] == "openai"
        assert request.headers["Authorization"] == "Bearer mock-openai"
        path = request.match_info["path"]
        assert path in {"v1/images/generations", "v1/images/edits"}
        if path.endswith("edits"):
            form = await request.post()
            assert form["image[]"].file.read(8) == b"\x89PNG\r\n\x1a\n"
        else:
            form = await request.json()
        assert form["model"].startswith("gpt-image-") and form["prompt"]
        self.counts["openai_image"] += 1
        return web.json_response({"data": [{"b64_json": base64.b64encode(self.image).decode()}]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", type=Path)
    parser.add_argument("port", type=int)
    args = parser.parse_args()
    mock = MockPlatform(args.fixtures)
    application = web.Application(client_max_size=64 * 1024**2)
    application.add_routes(mock.routes)
    web.run_app(application, host="127.0.0.1", port=args.port, access_log=None)
