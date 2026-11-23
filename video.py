"""MiniMax H3 V2 and BytePlus ModelArk video adapters."""

import base64
from dataclasses import dataclass

from .tasks import fingerprint, run_task, task_id
from .transport import api_key, client, download_public, request_json


H3 = "MiniMax-H3"
SEEDANCE = "dreamina-seedance-2-5-260628"
VIDEO_MODELS = (H3, SEEDANCE)
MAX_VIDEO_BYTES = 192 * 1024 * 1024
MAX_INLINE_BYTES = 45_000_000
MINIMAX_URL = "https://api.minimax.io"
ARK_TASKS = "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
VIDEO_RATIOS = {
    H3: ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
    SEEDANCE: ("16:9", "9:16", "1:1", "4:3", "3:4", "21:9"),
}
VIDEO_RESOLUTIONS = {H3: ("768P", "2K"), SEEDANCE: ("720p", "480p", "1080p", "4k")}


def inline_media(mime, data):
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def video_settings(model, prompt, duration, ratio, resolution, generate_audio, frames, references):
    if model not in VIDEO_MODELS:
        raise ValueError("Select a supported video model.")
    prompt = prompt.strip()
    if not 1 <= len(prompt) <= 7000:
        raise ValueError("Enter a video prompt between 1 and 7000 characters.")
    if resolution == "model default":
        resolution = VIDEO_RESOLUTIONS[model][0]
    if resolution not in VIDEO_RESOLUTIONS[model]:
        raise ValueError(f"Select a resolution supported by {model}.")
    if not 4 <= duration <= (15 if model == H3 else 30):
        raise ValueError(f"Select a duration supported by {model}.")
    if frames:
        ratio = "adaptive"
    elif ratio not in VIDEO_RATIOS[model]:
        raise ValueError("Select a supported video aspect ratio.")
    if frames and references:
        raise ValueError("Use frame anchors or reference images in a single run.")
    if model == SEEDANCE and frames and frames[0][0] == "last_frame":
        raise ValueError("Connect a first frame to use a last frame with Seedance.")
    images = frames + references
    if any(len(data) >= 30_000_000 for _, data in images):
        raise ValueError("Each video reference image must be smaller than 30 MB.")
    if sum(len(data) for _, data in images) > MAX_INLINE_BYTES:
        raise ValueError("The reference images would exceed the request size limit.")
    return {
        "model": model, "prompt": prompt, "ratio": ratio, "resolution": resolution,
        "duration": duration, "generate_audio": generate_audio,
        "images": [{"role": role, "data": inline_media("image/png", png)} for role, png in images],
    }


def provider_payload(settings):
    content = [{"type": "text", "text": settings["prompt"]}]
    content.extend(
        {"type": "image_url", "role": item["role"], "image_url": {"url": item["data"]}}
        for item in settings["images"]
    )
    payload = {
        name: settings[name] for name in ("model", "duration", "ratio", "resolution", "generate_audio")
    }
    payload["content"] = content
    return payload


@dataclass(frozen=True)
class VideoEndpoint:
    submit: str
    query: str
    key_name: str
    id_field: str
    url_field: str
    task_container: str | None = None


H3_ENDPOINT = VideoEndpoint(
    f"{MINIMAX_URL}/v2/video_generation",
    f"{MINIMAX_URL}/v2/query/video_generation",
    "MINIMAX_API_KEY", "task_id", "url", "task",
)
ARK_ENDPOINT = VideoEndpoint(ARK_TASKS, ARK_TASKS, "ARK_API_KEY", "id", "video_url")
REGEN_ENDPOINT = VideoEndpoint(
    f"{MINIMAX_URL}/v2/video_regeneration", H3_ENDPOINT.query,
    H3_ENDPOINT.key_name, H3_ENDPOINT.id_field, H3_ENDPOINT.url_field, H3_ENDPOINT.task_container,
)


async def provider_video(endpoint, payload, run_number=0, resume_id=""):
    token = api_key(endpoint.key_name)
    async with client(120) as session:
        async def submit(_key):
            _, body = await request_json(
                session, "POST", endpoint.submit, token=token, json=payload, statuses=(200, 201, 202)
            )
            return body.get(endpoint.id_field)

        async def query(remote_id):
            _, body = await request_json(session, "GET", f"{endpoint.query}/{remote_id}", token=token)
            task = body.get(endpoint.task_container, {}) if endpoint.task_container else body
            if not isinstance(task, dict):
                return None, None
            content = task.get("content")
            url = content.get(endpoint.url_field) if isinstance(content, dict) else None
            return task.get("status"), url

        async def download(url):
            return await download_public(url, MAX_VIDEO_BYTES)

        return await run_task(
            scope=fingerprint(endpoint.submit, token), payload=payload, run_number=run_number,
            resume_id=resume_id, submit=submit, query=query, download=download,
        )


async def regenerate_h3(source_task, run_number):
    payload = {"model": H3, "source_task_id": task_id(source_task.strip()), "resolution": "2K"}
    return await provider_video(REGEN_ENDPOINT, payload, run_number)
