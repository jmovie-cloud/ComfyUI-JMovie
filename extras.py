"""Direct MiniMax music and Stability AI fast image upscaling."""

import aiohttp

from .providers import MAX_IMAGE_BYTES
from .transport import RequestError, api_key, client, request, request_json


async def generate_music(prompt, lyrics, instrumental):
    prompt, lyrics = prompt.strip(), lyrics.strip()
    if len(prompt) > 2000 or len(lyrics) > 3500:
        raise ValueError("Use up to 2,000 prompt and 3,500 lyric characters.")
    if instrumental and not prompt:
        raise ValueError("Enter a music prompt for an instrumental track.")
    if not instrumental and not lyrics:
        raise ValueError("Enter lyrics or enable instrumental.")
    payload = {
        "model": "music-3.0",
        "prompt": prompt,
        "is_instrumental": instrumental,
        "output_format": "hex",
        "stream": False,
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    }
    if not instrumental:
        payload["lyrics"] = lyrics
    token = api_key("MINIMAX_API_KEY")
    try:
        async with client(300) as session:
            _, body = await request_json(
                session, "POST", "https://api.minimax.io/v1/music_generation",
                token=token, json=payload, limit=32 * 1024 * 1024,
            )
    except RequestError as error:
        if error.status is None or error.status >= 500:
            raise RuntimeError("Music submission unconfirmed. Check MiniMax usage before rerunning.") from None
        raise
    status = body.get("base_resp")
    if isinstance(status, dict) and status.get("status_code") != 0:
        code = status.get("status_code")
        raise RuntimeError(f"MiniMax Music rejected the request (code {code if type(code) is int else 'unknown'}).")
    try:
        data = body["data"]
        if data["status"] != 2:
            raise ValueError()
        audio = bytes.fromhex(data["audio"])
        if not audio:
            raise ValueError()
        return audio
    except (ValueError, KeyError, TypeError):
        raise RuntimeError("MiniMax Music returned no complete track. Check usage before rerunning.") from None


async def upscale_image(png):
    token = api_key("STABILITY_API_KEY")
    form = aiohttp.FormData()
    form.add_field("image", png, filename="image.png", content_type="image/png")
    form.add_field("output_format", "png")
    async with client(120) as session:
        _, image = await request(
            session, "POST", "https://api.stability.ai/v2beta/stable-image/upscale/fast",
            token=token, data=form, headers={"Accept": "image/*"}, limit=MAX_IMAGE_BYTES,
        )
    return image
