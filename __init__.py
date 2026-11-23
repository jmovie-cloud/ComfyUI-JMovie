from comfy_api.latest import ComfyExtension

from .nodes import CloudImage


class JMovieCloudExtension(ComfyExtension):
    async def get_node_list(self):
        return [CloudImage]


async def comfy_entrypoint():
    return JMovieCloudExtension()
