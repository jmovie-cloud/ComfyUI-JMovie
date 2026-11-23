"""MiniMax H3 video tasks billed to the user's MiniMax account."""

from .credentials import MINIMAX_HOSTS, api_key
from .delivery import supplier_media
from .tasks import fingerprint, run_task
from .transport import RequestError, client, request_json
from .video import H3, MAX_VIDEO_BYTES


async def generate_h3(settings, run_number=0, resume_id=""):
    key, region = api_key("minimax")
    api = f"{MINIMAX_HOSTS[region]}/v2"
    payload = {}
    if not resume_id:
        payload = {name: settings[name] for name in ("model", "resolution", "duration", "ratio", "generate_audio")}
        payload["content"] = [{"type": "text", "text": settings["prompt"]}]
        payload["content"].extend(
            {"type": "image_url", "role": image["role"], "image_url": {"url": image["data"]}}
            for image in settings["images"]
        )

    async with client(90) as session:
        async def submit(_request_key):
            _, result = await request_json(session, "POST", f"{api}/video_generation", token=key, json=payload)
            return result.get("task_id")

        async def query(remote_id):
            _, result = await request_json(session, "GET", f"{api}/query/video_generation/{remote_id}", token=key)
            task = result.get("task", result)
            if not isinstance(task, dict) or task.get("id") != remote_id or task.get("model") != H3:
                raise RuntimeError("MiniMax returned an invalid H3 task.")
            return task.get("status"), task.get("content")

        async def download(content):
            if not isinstance(content, dict) or not isinstance(content.get("url"), str):
                raise RuntimeError("MiniMax returned no video download link.")
            return await supplier_media({"url": content["url"]}, MAX_VIDEO_BYTES)

        # Preserve the original International namespace so saved task IDs remain reusable.
        scope = "minimax-h3" if region == "global" else "minimax-h3-cn"
        try:
            return await run_task(
                scope=(scope, fingerprint(key)), payload=payload, run_number=run_number,
                resume_id=resume_id, submit=submit, query=query, download=download,
            )
        except RequestError as error:
            if error.status in {401, 403}:
                raise RuntimeError(
                    "MiniMax rejected the API key. In Set MiniMax API key, choose the platform that issued it."
                ) from None
            raise
