"""Local BYOK settings with an optional startup environment fallback."""

import json
import os
from pathlib import Path
import tempfile

from aiohttp import web
import folder_paths

from .local_access import local_comfy, require_local_request


PROVIDERS = {"openai": ("OpenAI", "OPENAI_API_KEY"), "minimax": ("MiniMax", "MINIMAX_API_KEY")}
MINIMAX_HOSTS = {"global": "https://api.minimax.io", "cn": "https://api.minimax.cn"}
DEFAULT_MINIMAX_REGION = "global"
MAX_KEY_LENGTH = 4096
MAX_BODY_LENGTH = 8192


def key_file(provider):
    return Path(folder_paths.get_user_directory()) / "jmovie-cloud" / "keys" / f"{provider}.key"


def environment_key(provider):
    return os.environ.get(PROVIDERS[provider][1], "").strip()


def minimax_region(value):
    if not isinstance(value, str) or value not in MINIMAX_HOSTS:
        raise ValueError("Choose International or Mainland China for the MiniMax API key.")
    return value


def saved_credential(provider):
    try:
        with key_file(provider).open(encoding="ascii") as file:
            contents = file.read(MAX_BODY_LENGTH + 1).strip()
        if provider != "minimax":
            return contents, None
        if not contents.startswith("{"):
            return contents, DEFAULT_MINIMAX_REGION
        saved = json.loads(contents)
        if not isinstance(saved.get("key"), str) or not saved["key"]:
            raise ValueError()
        return saved["key"], minimax_region(saved.get("region"))
    except FileNotFoundError:
        return "", None
    except (OSError, ValueError):
        raise RuntimeError("Could not read the saved API key.") from None


def key_configuration(provider):
    if local_comfy():
        key, region = saved_credential(provider)
        if key:
            return key, region, "saved"
    key = environment_key(provider)
    region = None
    if provider == "minimax":
        region = os.environ.get("MINIMAX_API_REGION", "").strip() or DEFAULT_MINIMAX_REGION
    return key, region, "environment" if key else "none"


def api_key(provider):
    key, region, _ = key_configuration(provider)
    if key:
        return key, minimax_region(region) if provider == "minimax" else None
    name, variable = PROVIDERS[provider]
    raise RuntimeError(f"Select Set {name} API key on the node, or set {variable} in the ComfyUI environment.")


def save_key(provider, value, region):
    key = value.strip() if isinstance(value, str) else ""
    if not 1 <= len(key) <= MAX_KEY_LENGTH or not key.isascii() or any(not 33 <= ord(char) <= 126 for char in key):
        raise ValueError("Paste a complete API key without spaces.")
    contents = key
    if provider == "minimax":
        contents = json.dumps({"key": key, "region": minimax_region(region)})
    path = key_file(provider)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as file:
            file.write(contents)
        os.replace(filename, path)
    finally:
        Path(filename).unlink(missing_ok=True)


def key_status(provider):
    _, region, source = key_configuration(provider)
    status = {"source": source}
    if provider == "minimax":
        status["region"] = region if region in MINIMAX_HOSTS else DEFAULT_MINIMAX_REGION
    return status


def add_key_routes(server):
    @server.routes.post("/jmovie-cloud/keys/{provider}/{action}")
    async def key_action(request):
        require_local_request(request)
        provider, action = request.match_info["provider"], request.match_info["action"]
        if provider not in PROVIDERS or action not in {"status", "save", "remove"}:
            raise web.HTTPNotFound()
        headers = {"Cache-Control": "no-store"}
        try:
            if action == "save":
                if request.content_type != "application/json" or not 0 < (request.content_length or 0) <= MAX_BODY_LENGTH:
                    raise ValueError("Paste a valid API key and try again.")
                payload = await request.json()
                if not isinstance(payload, dict):
                    raise ValueError("Paste a valid API key and try again.")
                save_key(provider, payload.get("key"), payload.get("region", DEFAULT_MINIMAX_REGION))
            elif action == "remove":
                key_file(provider).unlink(missing_ok=True)
            return web.json_response(key_status(provider), headers=headers)
        except (json.JSONDecodeError, UnicodeError):
            error = "Paste a valid API key and try again."
        except ValueError as exc:
            error = str(exc)
        except (OSError, RuntimeError):
            error = "Could not access the local API key settings."
        return web.json_response({"error": error}, status=400, headers=headers)
