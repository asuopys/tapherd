"""Expose TapHerd's active-device operations over the Model Context Protocol."""

import asyncio
import base64
import io
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, TypeVar

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolResult,
    ContentBlock,
    ImageContent,
    TextContent,
    ToolAnnotations,
)
from PIL import Image
from pydantic import Field, ValidationError

from tapherd.actions.android import AndroidActions, Direction, Key, TapSelector
from tapherd.config import DEVICE_LIMIT
from tapherd.devices.adb import AdbBackend, DeviceConnection
from tapherd.devices.registry import DeviceRegistry
from tapherd.devices.state import StateStore
from tapherd.errors import TapHerdError
from tapherd.recipes.runner import RecipeService
from tapherd.ui import screen

HTTP_HOST = "127.0.0.1"
HTTP_PORT = 8765
HTTP_PATH = "/mcp"
_READ_ONLY = ToolAnnotations(readOnlyHint=True)
_Result = TypeVar("_Result")


def _reply(
    fields: dict[str, Any], *, error: bool = False, image: ImageContent | None = None
) -> CallToolResult:
    payload = {"ok": not error, **fields}
    content: list[ContentBlock] = [
        TextContent(
            type="text",
            text=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
    ]
    if image is not None:
        content.append(image)
    return CallToolResult(content=content, structuredContent=payload, isError=error)


class TapHerdMCP(FastMCP):
    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> CallToolResult | Sequence[ContentBlock] | dict[str, Any]:
        try:
            return await super().call_tool(name, arguments)
        except ToolError as error:
            cause = error.__cause__
            if isinstance(cause, TapHerdError):
                message = str(cause)
            elif isinstance(cause, ValidationError):
                details = cause.errors(
                    include_url=False, include_context=False, include_input=False
                )
                fields = sorted(
                    {".".join(map(str, detail["loc"])) for detail in details}
                )
                message = f"Check the tool schema and correct the arguments ({', '.join(fields)})."
            elif cause is None:
                message = (
                    "List the available MCP tools and choose a registered TapHerd tool."
                )
            else:
                message = "TapHerd could not complete the action. Run `tapherd doctor` and try again."
            return _reply({"error": message}, error=True)


INSTRUCTIONS = (
    "Control your own Android devices. List devices first and use an active serial.\n"
    "When the user asks you to post, publish the post: finish with the app's final "
    "Post, Share, or Upload button. Never save it as a draft unless the user asks for "
    "a draft. Use the visibility the user asked for (for example Public, Everyone, "
    "Friends, Unlisted, Private, or Only me). If they didn't say, post publicly. "
    "Before the final tap, check the screen shows that visibility. Afterwards, confirm "
    "the post appears on the profile."
)


def create_server(registry: DeviceRegistry) -> TapHerdMCP:
    recipes = RecipeService(registry)
    server = TapHerdMCP(
        "TapHerd",
        instructions=INSTRUCTIONS,
        log_level="WARNING",
        host=HTTP_HOST,
        port=HTTP_PORT,
        streamable_http_path=HTTP_PATH,
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[
                HTTP_HOST,
                f"{HTTP_HOST}:{HTTP_PORT}",
                "localhost",
                f"localhost:{HTTP_PORT}",
            ],
        ),
    )

    async def on_device(
        serial: str, action: str, operation: Callable[[DeviceConnection], _Result]
    ) -> _Result:
        def run_action() -> _Result:
            with registry.target(serial, action=action) as device:
                return operation(device)

        return await asyncio.to_thread(run_action)

    @server.tool(annotations=_READ_ONLY)
    async def list_devices() -> CallToolResult:
        """List detected Android devices, their active status, and the free-tier limit."""
        listing = await asyncio.to_thread(registry.list_devices)
        return _reply(asdict(listing))

    @server.tool(annotations=_READ_ONLY)
    async def device_info(serial: str) -> CallToolResult:
        """Read an active device's details, native screen size, and foreground app package."""
        details = await asyncio.to_thread(registry.device_info, serial)
        width, height = details.screen_size
        return _reply(
            {
                **asdict(details.device),
                "screen_size": {"width": width, "height": height},
                "foreground_app": details.foreground_app,
            }
        )

    @server.tool(annotations=_READ_ONLY)
    async def screenshot(
        serial: str,
        max_width: Annotated[int, Field(ge=1)] = screen.DEFAULT_SCREENSHOT_WIDTH,
    ) -> CallToolResult:
        """Capture a PNG screenshot and return it as an image, scaled down to max_width if needed."""
        png = await on_device(
            serial, "screenshot", lambda device: screen.screenshot(device, max_width)
        )
        with Image.open(io.BytesIO(png)) as image:
            width, height = image.size
        return _reply(
            {
                "serial": serial,
                "width": width,
                "height": height,
                "mime_type": "image/png",
            },
            image=ImageContent(
                type="image",
                mimeType="image/png",
                data=base64.b64encode(png).decode("ascii"),
            ),
        )

    @server.tool(annotations=_READ_ONLY)
    async def read_screen(serial: str) -> CallToolResult:
        """Read up to 150 accessibility elements with labels and native pixel coordinates."""
        elements = await on_device(serial, "read_screen", screen.read_screen)
        return _reply(
            {"serial": serial, "elements": [element.to_dict() for element in elements]}
        )

    @server.tool()
    async def tap(
        serial: str,
        x: int | None = None,
        y: int | None = None,
        selector: TapSelector | None = None,
    ) -> CallToolResult:
        """Tap native pixel coordinates, or match one exact text, resource_id, or content_desc selector."""
        tapped_x, tapped_y = await on_device(
            serial,
            "tap",
            lambda device: AndroidActions(device).tap(x, y, selector=selector),
        )
        return _reply({"serial": serial, "x": tapped_x, "y": tapped_y})

    @server.tool()
    async def swipe(
        serial: str,
        direction: Direction | None = None,
        x1: int | None = None,
        y1: int | None = None,
        x2: int | None = None,
        y2: int | None = None,
        duration_ms: Annotated[int, Field(ge=1, le=2_147_483_647)] = 300,
    ) -> CallToolResult:
        """Swipe in one direction, or between two native pixel coordinate pairs."""
        await on_device(
            serial,
            "swipe",
            lambda device: AndroidActions(device).swipe(
                (x1, y1, x2, y2), direction=direction, duration_ms=duration_ms
            ),
        )
        return _reply({"serial": serial})

    @server.tool()
    async def type_text(serial: str, text: str) -> CallToolResult:
        """Enter text into the focused field. Unicode and multiline input use ADBKeyboard."""
        await on_device(
            serial, "type_text", lambda device: AndroidActions(device).type_text(text)
        )
        return _reply({"serial": serial})

    @server.tool()
    async def press_key(serial: str, key: Key) -> CallToolResult:
        """Press back, home, enter, recents, or delete on an active device."""
        await on_device(
            serial, "press_key", lambda device: AndroidActions(device).press_key(key)
        )
        return _reply({"serial": serial})

    @server.tool()
    async def open_app(serial: str, package: str) -> CallToolResult:
        """Open an installed Android app by package name."""
        await on_device(
            serial, "open_app", lambda device: AndroidActions(device).open_app(package)
        )
        return _reply({"serial": serial, "package": package})

    @server.tool()
    async def open_app_many(
        package: str,
        serials: Annotated[list[str], Field(min_length=1, max_length=DEVICE_LIMIT)]
        | None = None,
        group: str | None = None,
    ) -> CallToolResult:
        """Open an Android app concurrently on distinct active serials or one active device group."""
        if (serials is None) == (group is None):
            raise TapHerdError(
                "Provide a list of active device serials or a group name."
            )
        if group is not None:
            serials = await asyncio.to_thread(registry.active_group, group)
            if not serials:
                raise TapHerdError(
                    "No active devices in that group. Use list_devices to check groups."
                )
        assert serials is not None
        if len(set(serials)) != len(serials):
            raise TapHerdError("List each device serial once.")

        async def open_one(serial: str) -> dict[str, Any]:
            try:
                await on_device(
                    serial,
                    "open_app",
                    lambda device: AndroidActions(device).open_app(package),
                )
            except TapHerdError as error:
                return {"serial": serial, "ok": False, "error": str(error)}
            return {"serial": serial, "ok": True}

        results = await asyncio.gather(*(open_one(serial) for serial in serials))
        return _reply(
            {"package": package, "results": results},
            error=any(not result["ok"] for result in results),
        )

    @server.tool()
    async def push_media(serial: str, local_path: str) -> CallToolResult:
        """Copy a user-provided local image or video to a unique path in Android's gallery."""
        remote_path = await on_device(
            serial,
            "push_media",
            lambda device: AndroidActions(device).push_media(Path(local_path)),
        )
        return _reply({"serial": serial, "device_path": remote_path})

    @server.tool()
    async def prepare_app(serial: str, package: str) -> CallToolResult:
        """Give a posting app access to all photos and videos and turn off its camera
        and microphone, so upload screens aren't interrupted by permission prompts.
        Android closes the app if it is running."""
        result = await on_device(
            serial,
            "prepare_app",
            lambda device: AndroidActions(device).prepare_app(package),
        )
        return _reply({"serial": serial, "package": package, **result})

    @server.tool()
    async def remove_media(serial: str, device_path: str) -> CallToolResult:
        """Delete media that push_media copied to the device, for example after posting."""
        await on_device(
            serial,
            "remove_media",
            lambda device: AndroidActions(device).remove_media(device_path),
        )
        return _reply({"serial": serial, "removed": device_path})

    @server.tool(annotations=_READ_ONLY)
    async def list_recipes() -> CallToolResult:
        """List available posting recipes, their verification status, and parameters."""
        return _reply({"recipes": await asyncio.to_thread(recipes.list_recipes)})

    @server.tool()
    async def run_recipe(
        name: str, serials: list[str], params: dict[str, str]
    ) -> CallToolResult:
        """Run a posting recipe and return a result per device. Stop for review on needs_ai.

        Pass the visibility the user asked for. Recipes publish publicly by default.
        """
        result = await recipes.run(name, serials, params)
        return _reply(asdict(result), error=not result.completed)

    return server


def run_server(*, http: bool = False) -> None:
    registry = DeviceRegistry(AdbBackend(), StateStore.from_environment())
    create_server(registry).run(transport="streamable-http" if http else "stdio")


if __name__ == "__main__":
    run_server()
