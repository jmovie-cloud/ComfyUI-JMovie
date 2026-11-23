from io import BytesIO

import numpy as np
import torch
from comfy_api.latest import io
from PIL import Image

from .providers import MINIMAX_MODELS, OPENAI_MODELS, SEEDREAM_MODELS, generate_image


class CloudImage(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="JMovieCloudImage",
            display_name="Cloud Image",
            category="JMovie Cloud",
            description="Generate or edit an image through a direct provider connection.",
            inputs=[
                io.Combo.Input("model", options=[*OPENAI_MODELS, *SEEDREAM_MODELS, *MINIMAX_MODELS]),
                io.String.Input("prompt", multiline=True),
                io.Image.Input("reference_image", optional=True),
            ],
            outputs=[io.Image.Output()],
        )

    @classmethod
    async def execute(cls, model, prompt, reference_image=None):
        if not prompt.strip():
            raise ValueError("Enter an image prompt.")
        reference = None
        if reference_image is not None:
            if reference_image.shape[0] != 1:
                raise ValueError("Connect a single reference image.")
            pixels = (reference_image[0].detach().cpu().clamp(0, 1).numpy() * 255).round()
            buffer = BytesIO()
            Image.fromarray(pixels.astype(np.uint8)).save(buffer, format="PNG")
            reference = buffer.getvalue()

        result = await generate_image(model, prompt, reference)
        with Image.open(BytesIO(result)) as image:
            pixels = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
        return io.NodeOutput(torch.from_numpy(pixels).unsqueeze(0))
