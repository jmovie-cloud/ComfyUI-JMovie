# JMovie Cloud

Cloud media nodes for ComfyUI. This development snapshot includes the Cloud Image node with direct OpenAI, BytePlus and MiniMax connections.

Clone this repository into ComfyUI's `custom_nodes` directory. Set `OPENAI_API_KEY`, `ARK_API_KEY` or `MINIMAX_API_KEY` in the environment of the ComfyUI server, then restart it. Add **JMovie Cloud → Cloud Image**, select a model, enter a prompt, and connect the output to **Preview Image** or **Save Image**. For editing, connect one reference image. Requests go to the selected provider and are billed by that provider.

## JMovie account connection

The planned managed connection opens a JMovie page to sign in and authorize ComfyUI. JMovie handles generation, usage and billing for authorized tasks. The developer API product is separate. The managed connection, video, music and upscaling are pending integration.

## Build status

Registry publication and live provider verification are pending.
