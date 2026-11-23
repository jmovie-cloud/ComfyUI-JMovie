from comfy_api.latest import ComfyExtension

from .managed import add_routes
from .nodes import CloudImage, CloudImageUpscale, CloudMusic, CloudVideo, H3Upscale, JMovieImage, ResumeVideo


WEB_DIRECTORY = "./web"


class JMovieCloudExtension(ComfyExtension):
    async def on_load(self):
        from server import PromptServer

        if PromptServer.instance is not None:
            add_routes(PromptServer.instance)

    async def get_node_list(self):
        return [CloudImage, JMovieImage, CloudVideo, ResumeVideo, CloudMusic, CloudImageUpscale, H3Upscale]


async def comfy_entrypoint():
    return JMovieCloudExtension()
