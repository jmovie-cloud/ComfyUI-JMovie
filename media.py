"""Bridge provider files and ComfyUI media types."""

from io import BytesIO

import av
import numpy as np
from PIL import Image
import torch
from comfy_api.latest import InputImpl


def png_image(image):
    if image.ndim != 4 or image.shape[0] != 1 or image.shape[-1] not in (3, 4):
        raise ValueError("Connect a single RGB or RGBA image.")
    pixels = (image[0].detach().cpu().clamp(0, 1).numpy() * 255).round()
    buffer = BytesIO()
    Image.fromarray(pixels.astype(np.uint8)).save(buffer, format="PNG")
    return buffer.getvalue()


def decode_image(data):
    try:
        with Image.open(BytesIO(data), formats=("PNG", "JPEG", "WEBP")) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError()
            pixels = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    except (OSError, TypeError, ValueError, Image.DecompressionBombError):
        raise RuntimeError("The cloud result is not a usable image.") from None
    return torch.from_numpy(pixels).unsqueeze(0)


def decode_video(data):
    stream = BytesIO(data)
    try:
        with av.open(stream, mode="r", format="mov") as container:
            if not container.streams.video:
                raise ValueError()
    except (ValueError, av.FFmpegError):
        raise RuntimeError("The cloud result is not a usable MP4 video.") from None
    stream.seek(0)
    return InputImpl.VideoFromFile(stream)


def decode_music(data):
    try:
        with av.open(BytesIO(data), mode="r", format="mp3") as container:
            source = container.streams.audio[0]
            resampler = av.AudioResampler(format="fltp", layout=source.layout, rate=source.rate)
            frames = [frame.to_ndarray() for packet in container.decode(source) for frame in resampler.resample(packet)]
            if not frames:
                raise ValueError()
            frames.extend(frame.to_ndarray() for frame in resampler.resample(None))
            return {
                "waveform": torch.from_numpy(np.concatenate(frames, axis=1)).unsqueeze(0),
                "sample_rate": source.rate,
            }
    except (ValueError, IndexError, av.FFmpegError):
        raise RuntimeError("MiniMax did not return usable audio.") from None
