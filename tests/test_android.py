import asyncio
import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from xml.etree import ElementTree

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ImageContent
from PIL import Image
from typer.testing import CliRunner

from tapherd import cli, tease
from tapherd.devices.adb import DiscoveredDevice
from tapherd.devices.registry import DeviceRegistry
from tapherd.devices.state import StateStore
from tapherd.errors import TapHerdError
from tapherd.mcp_server import HTTP_HOST, HTTP_PATH, HTTP_PORT, create_server

SETTINGS_NODE = b"""
    <node text="Network &amp; internet" resource-id="android:id/title" content-desc="Network settings"
        class="android.widget.TextView" bounds="[10,100][210,160]" clickable="true"/>
"""


@dataclass
class FakeDevice:
    serial: str
    commands: list[tuple[str, ...]] = field(default_factory=list)
    pushes: list[tuple[Path, str]] = field(default_factory=list)
    tree: bytes = b"<hierarchy>" + SETTINGS_NODE + b"</hierarchy>"
    ime: str = "com.example.keyboard/.Ime"
    response: dict[tuple[str, ...], str] = field(default_factory=dict)
    push_fails: bool = False

    def shell(self, *arguments: str, timeout: float = 15) -> str:
        self.commands.append(arguments)
        for prefix, output in self.response.items():
            if arguments[: len(prefix)] == prefix:
                return output
        match arguments[:2]:
            case ("getprop", "ro.build.version.release"):
                return "14"
            case ("uiautomator", "dump"):
                return f"UI hierarchy dumped to: {arguments[-1]}"
            case ("settings", "--user"):
                return self.ime
            case ("am", "start"):
                return "Status: ok"
            case ("am", "broadcast"):
                return "Broadcast completed: result=0"
            case ("pm", "install"):
                return "Success"
            case _:
                return ""

    def screenshot(self) -> Image.Image:
        return Image.new("RGB", (1080, 1920), "blue")

    def screen_size(self) -> tuple[int, int]:
        return (1080, 1920)

    def foreground_app(self) -> str:
        return "com.android.settings"

    def read_file(self, path: str) -> bytes:
        return self.tree

    def push_file(self, source: Path, destination: str) -> None:
        self.pushes.append((source, destination))
        if self.push_fails:
            raise TapHerdError("Transfer interrupted. Check that the device is online.")


class FakeAdb:
    def __init__(self) -> None:
        self.discovered = [DiscoveredDevice("emulator-5554", "device", "Pixel")]
        self.connections: dict[str, FakeDevice] = {}
        self.connect_calls: list[str] = []
        self.disconnect_calls: list[str] = []
        self.reconnect_calls: list[tuple[str, str | None]] = []
        self.recoverable: set[str] = set()

    def version(self) -> str:
        return "Android Debug Bridge version 1.0.41"

    def list_devices(self) -> list[DiscoveredDevice]:
        return list(self.discovered)

    def connect(self, address: str) -> str:
        self.connect_calls.append(address)
        self.discovered.append(DiscoveredDevice(address, "device"))
        return f"connected to {address}"

    def disconnect(self, address: str) -> str:
        self.disconnect_calls.append(address)
        self.discovered = [info for info in self.discovered if info.serial != address]
        return f"disconnected {address}"

    def reconnect(self, serial: str, address: str | None = None) -> None:
        self.reconnect_calls.append((serial, address))
        if serial in self.recoverable:
            self.discovered = [
                info for info in self.discovered if info.serial != serial
            ]
            self.discovered.append(DiscoveredDevice(serial, "device"))

    def device(self, serial: str) -> FakeDevice:
        if serial not in self.connections:
            self.connections[serial] = FakeDevice(serial)
        return self.connections[serial]


@pytest.fixture
def adb(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeAdb:
    fake = FakeAdb()
    monkeypatch.setattr(cli, "AdbBackend", lambda: fake)
    monkeypatch.setenv("TAPHERD_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("TAPHERD_NO_TEASE", "1")
    monkeypatch.delenv("TAPHERD_WAITLIST_URL", raising=False)
    monkeypatch.delenv("TAPHERD_ACTION_LOG", raising=False)
    monkeypatch.delenv("TAPHERD_MAX_CONCURRENCY", raising=False)
    return fake


def run_cli(*arguments: str, exit_code: int = 0) -> str:
    result = CliRunner().invoke(cli.app, list(arguments))
    if result.exception and not isinstance(result.exception, SystemExit):
        raise result.exception
    assert result.exit_code == exit_code, result.output
    return result.output


def listing() -> dict[str, Any]:
    return json.loads(run_cli("devices", "--json"))


def test_auto_selection_lists_all_adb_devices_and_only_reads_active_devices(
    adb: FakeAdb,
) -> None:
    adb.discovered = [
        DiscoveredDevice("d", "device"),
        DiscoveredDevice("aa", "unauthorized"),
        DiscoveredDevice("b", "device"),
        DiscoveredDevice("c", "device"),
        DiscoveredDevice("a", "device"),
    ]
    view = listing()
    assert view["tier"] == "free"
    assert view["device_limit"] == 3
    assert view["selection_mode"] == "auto"
    assert [device["serial"] for device in view["devices"]] == [
        "a",
        "aa",
        "b",
        "c",
        "d",
    ]
    assert [device["serial"] for device in view["devices"] if device["active"]] == [
        "a",
        "b",
        "c",
    ]
    assert view["devices"][-1]["android_version"] is None
    assert set(adb.connections) == {"a", "b", "c"}
    assert "Automatic selection" in run_cli("devices")
    assert "inactive" in run_cli("open-app", "d", "com.android.settings", exit_code=1)
    assert "USB debugging prompt" in run_cli("inspect", "aa", exit_code=1)
    assert adb.disconnect_calls == []
    assert set(adb.connections) == {"a", "b", "c"}


def test_explicit_selection_and_labels_persist_across_commands(adb: FakeAdb) -> None:
    adb.discovered.extend(
        DiscoveredDevice(serial, "device") for serial in ("b", "c", "d", "e")
    )
    run_cli("use", "d")
    run_cli("label", "d", "Phone four", "--group", "Demo phones")
    run_cli("label", "d", "Main phone")
    view = listing()
    assert view["selection_mode"] == "explicit"
    (device,) = [device for device in view["devices"] if device["active"]]
    assert (device["serial"], device["label"], device["group"]) == (
        "d",
        "Main phone",
        "Demo phones",
    )
    run_cli("label", "d", "Main phone", "--group", "")
    assert (
        next(device for device in listing()["devices"] if device["serial"] == "d")[
            "group"
        ]
        is None
    )
    run_cli("use", "b")
    run_cli("use", "c")
    run_cli("use", "d")
    assert "up to 3 active devices" in run_cli("use", "e", exit_code=1)
    run_cli("unuse", "d")
    run_cli("unuse", "c")
    assert "Automatic selection is now on" in run_cli("unuse", "b")
    assert listing()["selection_mode"] == "auto"
    assert adb.disconnect_calls == []


def test_simultaneous_selection_does_not_exceed_limit(tmp_path: Path) -> None:
    adb = FakeAdb()
    serials = ["a", "b", "c", "d"]
    adb.discovered = [DiscoveredDevice(serial, "device") for serial in serials]
    registry = DeviceRegistry(adb, StateStore(tmp_path))

    def select(serial: str) -> str | None:
        try:
            registry.use(serial)
        except TapHerdError as error:
            return str(error)
        return None

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(select, serials))
    assert results.count(None) == 3
    (error,) = [result for result in results if result is not None]
    assert "up to 3 active devices" in error
    assert len(registry.store.read().selected) == 3


def test_connect_and_disconnect_only_change_the_requested_adb_address(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    adb.discovered.extend(
        DiscoveredDevice(serial, "device") for serial in ("a", "b", "c")
    )
    for serial in ("a", "b", "c"):
        run_cli("use", serial)
    monkeypatch.setenv("TAPHERD_WAITLIST_URL", "https://example.com/pro")
    result = run_cli("connect", "remote.test:5555")
    assert "connected to remote.test:5555" in result
    assert "up to 3 active devices" in result
    assert "https://example.com/pro" in result
    assert adb.connect_calls == ["remote.test:5555"]
    assert adb.disconnect_calls == []
    remote = next(
        device
        for device in listing()["devices"]
        if device["serial"] == "remote.test:5555"
    )
    assert remote["status"] == "device" and not remote["active"]
    assert "host:port" in run_cli("connect", "remote.test:65536", exit_code=1)
    assert adb.connect_calls == ["remote.test:5555"]
    run_cli("disconnect", "remote.test:5555")
    assert adb.disconnect_calls == ["remote.test:5555"]
    assert len(adb.discovered) == 4


def test_doctor_reports_how_to_find_an_online_device(adb: FakeAdb) -> None:
    output = run_cli("doctor")
    assert "Active and online: emulator-5554" in output
    assert "Ready. Next, connect your AI" in output
    adb.discovered.clear()
    assert "Start an emulator, or connect a phone" in run_cli("doctor", exit_code=1)


@pytest.mark.parametrize(
    ("package", "component"),
    [
        ("com.instagram.android", "com.instagram.android/.activity.MainTabActivity"),
        (
            "com.google.android.youtube",
            "com.google.android.youtube/.app.honeycomb.Shell$HomeActivity",
        ),
    ],
)
def test_open_app_starts_the_resolved_launcher_activity(
    adb: FakeAdb, package: str, component: str
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    device.response[("cmd", "package", "resolve-activity")] = (
        "priority=0 preferredOrder=0 match=0x108000 specificIndex=-1 isDefault=false\n"
        + component
    )
    run_cli("open-app", serial, package)
    assert device.commands[-1][:3] == ("am", "start", "-W")
    assert device.commands[-1][-2:] == ("-n", component)


def test_open_app_ignores_an_unrelated_or_missing_launcher(adb: FakeAdb) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    device.response[("cmd", "package", "resolve-activity")] = "com.example.other/.Main"
    run_cli("open-app", serial, "com.android.settings")
    assert device.commands[-1][-2:] == ("-p", "com.android.settings")
    device.response[("cmd", "package", "resolve-activity")] = "No activity found"
    run_cli("open-app", serial, "com.android.settings")
    assert device.commands[-1][-2:] == ("-p", "com.android.settings")


def test_open_inspect_and_capture_android_settings(
    adb: FakeAdb, tmp_path: Path
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    run_cli("open-app", serial, "com.android.settings")
    assert device.commands[0][:3] == ("cmd", "package", "resolve-activity")
    assert device.commands[1][:3] == ("am", "start", "-W")
    assert device.commands[1][-2:] == ("-p", "com.android.settings")
    (element,) = json.loads(run_cli("inspect", serial))
    assert element == {
        "text": "Network & internet",
        "resource_id": "android:id/title",
        "content_desc": "Network settings",
        "class": "android.widget.TextView",
        "bounds": [10, 100, 210, 160],
        "center": [110, 130],
        "clickable": True,
        "scrollable": False,
    }
    assert device.commands[-1] == ("rm", "-f", device.commands[-2][-1])

    out = tmp_path / "settings.png"
    run_cli("screenshot", serial, "--out", str(out), "--max-width", "360")
    with Image.open(out) as image:
        assert (image.format, image.size) == ("PNG", (360, 640))
    original = out.read_bytes()
    assert "already exists" in run_cli(
        "screenshot", serial, "--out", str(out), exit_code=1
    )
    assert out.read_bytes() == original


def test_inspect_filters_empty_nodes_caps_output_and_cleans_up_bad_dumps(
    adb: FakeAdb,
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    device.tree = (
        b'<hierarchy><node text="" bounds="[0,0][100,100]"/>'
        b'<node scrollable="true" bounds="[0,0][100,100]"/>'
        + SETTINGS_NODE * 160
        + b"</hierarchy>"
    )
    elements = json.loads(run_cli("inspect", serial))
    assert len(elements) == 150
    assert elements[0]["scrollable"]
    device.tree = b"<broken"
    assert "wait for its screen to settle" in run_cli("inspect", serial, exit_code=1)
    assert device.commands[-1] == ("rm", "-f", device.commands[-2][-1])


def test_tap_swipe_and_key_handle_both_action_forms(adb: FakeAdb) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    assert "Tapped (5, 8) on" in run_cli("tap", serial, "5", "8")
    assert 'Tapped "Network & internet" at (' in run_cli(
        "tap", serial, "--text", "Network & internet"
    )
    assert "Swiped up on" in run_cli("swipe", serial, "--direction", "up")
    run_cli("swipe", serial, "1", "2", "3", "4", "--duration-ms", "200")
    assert "Pressed recents on" in run_cli("press-key", serial, "recents")
    assert device.commands[0] == ("input", "tap", "5", "8")
    assert device.commands[-4:] == [
        ("input", "tap", "110", "130"),
        ("input", "swipe", "540", "1536", "540", "384", "300"),
        ("input", "swipe", "1", "2", "3", "4", "200"),
        ("input", "keyevent", "KEYCODE_APP_SWITCH"),
    ]
    assert "both x and y" in run_cli(
        "tap", serial, "5", "--text", "Network & internet", exit_code=1
    )
    assert "all four" in run_cli("swipe", serial, "1", "2", exit_code=1)


def test_selector_rejects_distinct_matching_locations(adb: FakeAdb) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    device.tree = (
        b"<hierarchy>"
        + SETTINGS_NODE
        + SETTINGS_NODE.replace(b"[10,100]", b"[10,120]")
        + b"</hierarchy>"
    )
    assert "several locations" in run_cli(
        "tap", serial, "--resource-id", "android:id/title", exit_code=1
    )
    assert all(command[:2] != ("input", "tap") for command in device.commands)


def test_type_text_ascii_and_unicode(adb: FakeAdb) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    run_cli("type-text", serial, "one %s & two")
    assert device.commands[1:] == [
        ("input", "text", "one%s%"),
        ("input", "text", "s%s&%stwo"),
    ]
    assert "install and select ADBKeyboard" in run_cli(
        "type-text", serial, "mañana 🐈", exit_code=1
    )
    device.ime = "com.android.adbkeyboard/com.android.adbkeyboard.AdbIME"
    run_cli("type-text", serial, "mañana 🐈\n你好")
    broadcast = device.commands[-1]
    assert "ADB_INPUT_B64" in broadcast
    assert base64.b64decode(broadcast[-1]).decode() == "mañana 🐈\n你好"


def test_apk_and_media_use_unique_paths_and_cleanup(
    adb: FakeAdb, tmp_path: Path
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"test")
    run_cli("install-apk", serial, str(apk))
    ((source, remote),) = device.pushes
    assert source == apk
    assert remote.startswith("/data/local/tmp/tapherd-")
    assert device.commands[-2:] == [
        ("pm", "install", "-r", remote),
        ("rm", "-f", remote),
    ]

    image = tmp_path / "A photo.png"
    image.write_bytes(b"test")
    first = run_cli("push-media", serial, str(image)).strip()
    second = run_cli("push-media", serial, str(image)).strip()
    assert first != second
    assert first.startswith("/sdcard/DCIM/TapHerd/A-photo-") and first.endswith(".png")
    assert device.commands[-1][-1] == f"file://{second}"
    assert "android.intent.action.MEDIA_SCANNER_SCAN_FILE" in device.commands[-1]
    assert device.commands[-3] == ("mv", device.pushes[-1][1], second)

    device.push_fails = True
    assert "Transfer interrupted" in run_cli(
        "push-media", serial, str(image), exit_code=1
    )
    assert device.commands[-1] == ("rm", "-f", device.pushes[-1][1])


def test_prepare_app_allows_all_media_and_turns_off_camera_and_mic(
    adb: FakeAdb,
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    package = "com.google.android.youtube"
    assert "all photos and videos allowed" in run_cli("prepare-app", serial, package)
    commands = device.commands
    assert ("pm", "grant", package, "android.permission.READ_MEDIA_VIDEO") in commands
    assert ("pm", "grant", package, "android.permission.READ_MEDIA_IMAGES") in commands
    assert (
        "pm",
        "revoke",
        package,
        "android.permission.READ_MEDIA_VISUAL_USER_SELECTED",
    ) in commands
    for permission in ("android.permission.CAMERA", "android.permission.RECORD_AUDIO"):
        assert ("pm", "revoke", package, permission) in commands
        assert (
            "pm",
            "set-permission-flags",
            package,
            permission,
            "user-set",
            "user-fixed",
        ) in commands
    assert "Enter an Android package name" in run_cli(
        "prepare-app", serial, "not a package", exit_code=1
    )


def test_prepare_app_reports_an_app_that_takes_no_media_access(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)

    def shell(*arguments: str, timeout: float = 15) -> str:
        if arguments[:2] == ("pm", "grant"):
            raise TapHerdError("Android's `pm` command failed.")
        return ""

    monkeypatch.setattr(device, "shell", shell)
    assert "did not accept photo and video access" in run_cli(
        "prepare-app", serial, "com.example.app", exit_code=1
    )


def test_remove_media_deletes_only_files_push_media_created(
    adb: FakeAdb, tmp_path: Path
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"test")
    pushed = run_cli("push-media", serial, str(video)).strip()

    assert "Removed" in run_cli("remove-media", serial, pushed)
    assert ("rm", "-f", pushed) in device.commands
    assert device.commands[-2][:3] == ("content", "call", "--uri")
    assert device.commands[-2][-1] == pushed

    for other in (
        "/sdcard/DCIM/Camera/holiday.mp4",
        "/sdcard/DCIM/TapHerd/../Camera/holiday.mp4",
        "/sdcard/DCIM/TapHerd/.tapherd-0123.part",
        "/sdcard/DCIM/TapHerd/*",
    ):
        before = len(device.commands)
        assert "Only files that push_media copied" in run_cli(
            "remove-media", serial, other, exit_code=1
        )
        assert device.commands[before:] == []

    name = pushed.rsplit("/", 1)[-1]
    device.response[("ls", "/sdcard/DCIM/TapHerd")] = name
    assert "still lists" in run_cli("remove-media", serial, pushed, exit_code=1)


def test_media_scan_can_confirm_indexing_without_a_broadcast(
    adb: FakeAdb, tmp_path: Path
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    device.response[("content", "call")] = (
        "Result: Bundle[{android.intent.extra.STREAM=content://media/external/images/media/1}]"
    )
    image = tmp_path / "sample.png"
    image.write_bytes(b"test")
    destination = run_cli("push-media", serial, str(image)).strip()
    assert device.commands[-1][-4:] == ("--method", "scan_file", "--arg", destination)
    assert ("am", "broadcast") not in [command[:2] for command in device.commands]


def test_mcp_tools_share_actions_and_return_a_structured_screenshot(
    adb: FakeAdb, tmp_path: Path
) -> None:
    registry = DeviceRegistry(adb, StateStore.from_environment())
    serial = "emulator-5554"
    registry.label(serial, "Pixel test", "Demo")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"test")

    async def verify() -> None:
        async with create_connected_server_and_client_session(
            create_server(registry)
        ) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "list_devices",
                "device_info",
                "screenshot",
                "read_screen",
                "tap",
                "swipe",
                "type_text",
                "press_key",
                "open_app",
                "open_app_many",
                "push_media",
                "prepare_app",
                "remove_media",
                "list_recipes",
                "run_recipe",
            }
            listing = await client.call_tool("list_devices")
            assert listing.structuredContent is not None
            assert listing.structuredContent["tier"] == "free"
            assert listing.structuredContent["device_limit"] == 3
            details = await client.call_tool("device_info", {"serial": serial})
            assert details.structuredContent is not None
            assert details.structuredContent["foreground_app"] == "com.android.settings"
            assert details.structuredContent["label"] == "Pixel test"
            assert details.structuredContent["screen_size"] == {
                "width": 1080,
                "height": 1920,
            }
            tree = await client.call_tool("read_screen", {"serial": serial})
            assert tree.structuredContent is not None
            assert tree.structuredContent["elements"][0]["center"] == [110, 130]
            capture = await client.call_tool(
                "screenshot", {"serial": serial, "max_width": 360}
            )
            assert capture.structuredContent == {
                "ok": True,
                "serial": serial,
                "width": 360,
                "height": 640,
                "mime_type": "image/png",
            }
            (png,) = [
                block for block in capture.content if isinstance(block, ImageContent)
            ]
            assert png.mimeType == "image/png"
            with Image.open(io.BytesIO(base64.b64decode(png.data))) as image:
                assert image.format == "PNG" and image.size == (360, 640)
            for name, args in (
                ("open_app", {"package": "com.android.settings"}),
                ("tap", {"selector": {"text": "Network & internet"}}),
                ("swipe", {"direction": "up"}),
                ("swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4}),
                ("type_text", {"text": "one two"}),
                ("press_key", {"key": "back"}),
                ("push_media", {"local_path": str(source)}),
            ):
                result = await client.call_tool(name, {"serial": serial, **args})
                assert not result.isError, result.content
                assert (
                    result.structuredContent is not None
                    and result.structuredContent["ok"]
                )
                if name == "tap":
                    assert (
                        result.structuredContent["x"],
                        result.structuredContent["y"],
                    ) == (110, 130)
            assert result.structuredContent["device_path"].startswith(
                "/sdcard/DCIM/TapHerd/clip-"
            )

    asyncio.run(verify())
    commands = adb.device(serial).commands
    assert ("input", "tap", "110", "130") in commands
    assert ("input", "swipe", "540", "1536", "540", "384", "300") in commands
    assert ("input", "swipe", "1", "2", "3", "4", "300") in commands
    assert ("input", "text", "one%stwo") in commands
    assert ("input", "keyevent", "KEYCODE_BACK") in commands


def test_mcp_group_launches_two_devices_concurrently(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = DeviceRegistry(adb, StateStore.from_environment())
    serials = ["emulator-5554", "emulator-5556"]
    adb.discovered.extend(
        [DiscoveredDevice(serials[1], "device"), DiscoveredDevice("outside", "device")]
    )
    barrier = Barrier(2, timeout=3)
    for serial in serials:
        registry.label(serial, serial, "Demo")

        def shell(*arguments: str, timeout: float = 15) -> str:
            if arguments[:2] == ("cmd", "package"):
                return ""
            assert arguments[:2] == ("am", "start")
            barrier.wait()
            return "Status: ok"

        monkeypatch.setattr(adb.device(serial), "shell", shell)

    async def verify() -> None:
        async with create_connected_server_and_client_session(
            create_server(registry)
        ) as client:
            result = await client.call_tool(
                "open_app_many", {"group": "Demo", "package": "com.android.settings"}
            )
            assert not result.isError, result.content
            assert result.structuredContent is not None
            assert result.structuredContent["results"] == [
                {"serial": serial, "ok": True} for serial in serials
            ]

    asyncio.run(verify())
    assert "outside" not in adb.connections


def test_mcp_multi_device_failure_keeps_other_results(adb: FakeAdb) -> None:
    registry = DeviceRegistry(adb, StateStore.from_environment())

    async def verify() -> None:
        async with create_connected_server_and_client_session(
            create_server(registry)
        ) as client:
            result = await client.call_tool(
                "open_app_many",
                {
                    "serials": ["gone", "emulator-5554"],
                    "package": "com.android.settings",
                },
            )
            assert result.isError and result.structuredContent is not None
            missing, online = result.structuredContent["results"]
            assert not missing["ok"] and "ADB cannot see gone" in missing["error"]
            assert online == {"serial": "emulator-5554", "ok": True}

    asyncio.run(verify())


@pytest.mark.parametrize(("other", "limit"), [("first", "3"), ("second", "1")])
def test_actions_queue_for_the_same_device_or_when_concurrency_is_one(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch, other: str, limit: str
) -> None:
    monkeypatch.setenv("TAPHERD_MAX_CONCURRENCY", limit)
    adb.discovered = [
        DiscoveredDevice(serial, "device") for serial in ("first", "second")
    ]
    first = DeviceRegistry(adb, StateStore.from_environment())
    queued = DeviceRegistry(adb, StateStore.from_environment())
    waiting = Event()
    entered = Event()

    def enter() -> None:
        waiting.set()
        with queued.target(other):
            entered.set()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with first.target("first"):
            future = executor.submit(enter)
            assert waiting.wait(1)
            assert not entered.wait(0.1)
        future.result(timeout=2)
    assert entered.is_set()


def test_reconnect_recovers_only_the_requested_device_before_an_action(
    adb: FakeAdb,
) -> None:
    serial = "emulator-5554"
    adb.discovered = [
        DiscoveredDevice(serial, "offline"),
        DiscoveredDevice("other", "offline"),
    ]
    adb.recoverable.add(serial)
    run_cli("press-key", serial, "home")
    assert adb.reconnect_calls == [(serial, None)]
    assert adb.device(serial).commands == [("input", "keyevent", "KEYCODE_HOME")]


def test_inactive_remote_is_not_reconnected_when_the_active_set_is_full(
    adb: FakeAdb,
) -> None:
    address = "remote.test:5555"
    adb.discovered.extend(DiscoveredDevice(serial, "device") for serial in ("a", "b"))
    run_cli("connect", address)
    adb.discovered = [device for device in adb.discovered if device.serial != address]
    adb.recoverable.add(address)
    assert "ADB cannot see" in run_cli("press-key", address, "home", exit_code=1)
    assert adb.reconnect_calls == []


def test_transport_failure_after_an_action_does_not_replay_it(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)

    def shell(*arguments: str, timeout: float = 15) -> str:
        device.commands.append(arguments)
        adb.discovered = [DiscoveredDevice(serial, "offline")]
        raise TapHerdError("Lost the connection. Check the device before retrying.")

    monkeypatch.setattr(device, "shell", shell)
    assert "Lost the connection" in run_cli("press-key", serial, "home", exit_code=1)
    assert device.commands == [("input", "keyevent", "KEYCODE_HOME")]
    assert adb.reconnect_calls == []


def test_do_not_reconnect_after_an_explicit_disconnect_while_the_remote_is_absent(
    adb: FakeAdb,
) -> None:
    address = "remote.test:5555"
    adb.recoverable.add(address)
    run_cli("connect", address)
    run_cli("use", address)
    adb.discovered = [device for device in adb.discovered if device.serial != address]
    run_cli("press-key", address, "home")
    assert adb.reconnect_calls == [(address, address)]
    adb.discovered = [device for device in adb.discovered if device.serial != address]
    assert "already disconnected" in run_cli("disconnect", address)
    assert "ADB cannot see" in run_cli("press-key", address, "home", exit_code=1)
    assert adb.reconnect_calls == [(address, address)]


def test_opt_in_action_logs_save_outcomes_without_arguments(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    serial = "emulator-5554"
    run_cli("press-key", serial, "home")
    assert "No local action log" in run_cli("logs", serial, exit_code=1)
    monkeypatch.setenv("TAPHERD_ACTION_LOG", "1")
    run_cli("type-text", serial, "private test input")
    run_cli("open-app", serial, "invalid package", exit_code=1)
    lines = run_cli("logs", serial).splitlines()
    success, failure = map(json.loads, lines)
    assert success["serial"] == failure["serial"] == serial
    assert (success["action"], success["ok"]) == ("type_text", True)
    assert (failure["action"], failure["ok"]) == ("open_app", False)
    assert set(success) == {
        "serial",
        "action",
        "started_at",
        "finished_at",
        "duration_ms",
        "ok",
    }
    assert "private test input" not in "\n".join(lines)
    assert json.loads(run_cli("logs", serial, "--limit", "1")) == failure


def test_mcp_returns_actionable_errors_for_inactive_devices_and_bad_inputs(
    adb: FakeAdb,
) -> None:
    registry = DeviceRegistry(adb, StateStore.from_environment())
    adb.discovered.extend(
        DiscoveredDevice(serial, "device") for serial in ("a", "b", "c")
    )

    async def verify() -> None:
        async with create_connected_server_and_client_session(
            create_server(registry)
        ) as client:
            for name in ("screenshot", "device_info", "read_screen"):
                inactive = await client.call_tool(name, {"serial": "emulator-5554"})
                assert inactive.isError and inactive.structuredContent is not None
                assert inactive.structuredContent["ok"] is False
                assert "3 active devices" in inactive.structuredContent["error"]
            missing = await client.call_tool("read_screen", {"serial": "gone"})
            assert missing.isError and missing.structuredContent is not None
            assert "tapherd devices" in missing.structuredContent["error"]
            invalid = await client.call_tool(
                "screenshot", {"serial": "a", "max_width": 0}
            )
            assert invalid.isError and invalid.structuredContent is not None
            assert "max_width" in invalid.structuredContent["error"]
            bad_swipe = await client.call_tool("swipe", {"serial": "a", "x1": 2})
            assert bad_swipe.isError and bad_swipe.structuredContent is not None
            assert "all four" in bad_swipe.structuredContent["error"]

    asyncio.run(verify())
    assert "emulator-5554" not in adb.connections


def test_mcp_http_is_loopback_and_rejects_external_hosts_and_origins(
    adb: FakeAdb,
) -> None:
    server = create_server(DeviceRegistry(adb, StateStore.from_environment()))
    assert server.settings.host == HTTP_HOST == "127.0.0.1"
    app = server.streamable_http_app()

    async def verify() -> None:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url=f"http://{HTTP_HOST}:{HTTP_PORT}",
                headers={"accept": "application/json, text/event-stream"},
            ) as client,
        ):
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "tapherd-test", "version": "1"},
                },
            }
            good = await client.post(HTTP_PATH, json=request)
            assert good.status_code == 200
            assert good.json()["result"]["serverInfo"]["name"] == "TapHerd"
            bad_host = await client.post(
                HTTP_PATH, json=request, headers={"host": "example.test"}
            )
            assert bad_host.status_code == 421
            bad_origin = await client.post(
                HTTP_PATH, json=request, headers={"origin": "https://example.test"}
            )
            assert bad_origin.status_code == 403

    asyncio.run(verify())


def _recipe(steps: list[dict[str, Any]], params: dict[str, Any] | None = None) -> None:
    directory = StateStore.from_environment().directory / "recipes"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sample.yaml").write_text(
        yaml.safe_dump(
            {
                "app_package": "com.android.settings",
                "status": "unverified",
                "params": params or {},
                "steps": steps,
            }
        )
    )


def test_pro_notice_is_shared_by_devices_and_run_without_changing_json(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch
) -> None:
    waitlist = "https://example.test/waitlist"
    monkeypatch.setenv("TAPHERD_WAITLIST_URL", waitlist)
    now = 1_800_000_000
    monkeypatch.setattr(tease.time, "time", lambda: now)
    runner = CliRunner()

    muted = runner.invoke(cli.app, ["devices", "--json"])
    assert muted.exit_code == 0 and not muted.stderr
    assert StateStore.from_environment().read().last_pro_notice_at is None

    monkeypatch.delenv("TAPHERD_NO_TEASE")
    visible = runner.invoke(cli.app, ["devices", "--json"])
    assert visible.exit_code == 0
    result = json.loads(visible.stdout)
    assert result["tier"] == "free" and result["device_limit"] == 3
    notice = f"TapHerd Pro is coming: scheduling, 50+ devices, maintained recipes → {waitlist}"
    assert visible.stderr == notice + "\n"

    _recipe([{"id": "open", "type": "open_app"}])
    run_args = ["run", "sample", "--devices", "emulator-5554"]
    now += 86_399
    hidden = runner.invoke(cli.app, run_args)
    assert hidden.exit_code == 0 and not hidden.stderr
    assert json.loads(hidden.stdout)["results"][0]["status"] == "completed"

    now += 1
    again = runner.invoke(cli.app, run_args)
    assert again.exit_code == 0 and again.stderr == notice + "\n"
    assert json.loads(again.stdout)["results"][0]["status"] == "completed"
    assert not runner.invoke(cli.app, ["devices"]).stderr


def _tree(*texts: str) -> bytes:
    root = ElementTree.Element("hierarchy")
    for index, text in enumerate(texts):
        left = 10 + 40 * index
        ElementTree.SubElement(
            root,
            "node",
            {
                "text": text,
                "bounds": f"[{left},100][{left + 30},160]",
                "clickable": "true",
            },
        )
    return ElementTree.tostring(root, encoding="utf-8")


def _input_taps(device: FakeDevice) -> list[tuple[str, ...]]:
    return [command for command in device.commands if command[:2] == ("input", "tap")]


@pytest.mark.parametrize("exact_visible", [True, False])
def test_recipe_selects_the_exact_pushed_filename_or_stops(
    adb: FakeAdb, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exact_visible: bool
) -> None:
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"test")
    device = adb.device("emulator-5554")

    def read_file(path: str) -> bytes:
        destinations = [cmd[-1] for cmd in device.commands if cmd[0] == "mv"]
        if not destinations:
            return _tree("Topic=axb", "Topic=a.b")
        filename = Path(destinations[-1]).name
        return _tree(
            "Newest",
            f"{filename} thumbnail",
            filename if exact_visible else "other.mp4",
        )

    monkeypatch.setattr(device, "read_file", read_file)
    _recipe(
        [
            {"id": "open", "type": "open_app"},
            {
                "id": "ready",
                "type": "wait_for",
                "selector": {"text_contains": "Topic="},
                "timeout": 1,
                "fallbacks": [{"text": "Ready"}],
            },
        ],
    )
    ambiguous = json.loads(
        run_cli("run", "sample", "--devices", device.serial, exit_code=1)
    )
    assert "Multiple locations" in ambiguous["results"][0]["reason"]
    assert not _input_taps(device)

    _recipe(
        [
            {
                "id": "choose_topic",
                "type": "tap",
                "selector": {"text": "Unavailable"},
                "fallbacks": [{"regex": "^{{ topic }}$"}],
            },
            {"id": "type_topic", "type": "type", "text": "{{ topic }}"},
            {"id": "move", "type": "swipe", "direction": "up"},
            {"id": "copy", "type": "push_media", "path": "{{ video }}"},
            {"id": "media", "type": "choose_media", "timeout": 0.05},
            {"id": "proof", "type": "screenshot"},
        ],
        {"video": {"type": "video"}, "topic": {"type": "text"}},
    )
    report = json.loads(
        run_cli(
            "run",
            "sample",
            "--devices",
            device.serial,
            "--param",
            f"video={source}",
            "--param",
            "topic=Topic=a.b",
            exit_code=0 if exact_visible else 1,
        )
    )
    (result,) = report["results"]
    assert result["media_path"].startswith("/sdcard/DCIM/TapHerd/clip-")
    assert ("input", "text", "Topic=a.b") in device.commands
    assert _input_taps(device)[0] == ("input", "tap", "65", "130")
    with Image.open(result["screenshot_path"]) as image:
        assert image.format == "PNG"
    if exact_visible:
        assert result["status"] == "completed"
        assert _input_taps(device)[1:] == [("input", "tap", "105", "130")]
    else:
        assert result["status"] == "needs_ai"
        assert (
            result["failed_step"] == "media" and result["ui_tree_source"] == "current"
        )
        assert "exact filename" in result["reason"]
        assert len(_input_taps(device)) == 1


@pytest.mark.parametrize(
    "private_visible,confirmation",
    [(True, "Uploading"), (False, None), (True, "Completed")],
)
def test_recipe_checks_visibility_and_surfaces_an_uncertain_publish(
    adb: FakeAdb,
    monkeypatch: pytest.MonkeyPatch,
    private_visible: bool,
    confirmation: str | None,
) -> None:
    device = adb.device("emulator-5554")

    def read_file(path: str) -> bytes:
        if _input_taps(device):
            assert confirmation is not None
            return _tree(confirmation)
        return _tree(
            "Visibility: Private" if private_visible else "Visibility: Public", "Upload"
        )

    monkeypatch.setattr(device, "read_file", read_file)
    _recipe(
        [
            {
                "id": "publish",
                "type": "tap",
                "publish": True,
                "selector": {"text": "Upload"},
                "require": [{"text": "Visibility: Private"}],
            },
            {
                "id": "confirmation",
                "type": "wait_for",
                "selector": {"text": "Completed"},
                "timeout": 0.05,
            },
        ]
    )
    completed = confirmation == "Completed"
    (result,) = json.loads(
        run_cli(
            "run", "sample", "--devices", device.serial, exit_code=0 if completed else 1
        )
    )["results"]
    if completed:
        assert (
            result["status"] == "completed" and result["publish_state"] == "confirmed"
        )
        assert Path(result["screenshot_path"]).is_file()
        assert len(_input_taps(device)) == 1
        return
    assert result["status"] == "needs_ai"
    assert result["screenshot_path"] and result["ui_tree_source"] == "current"
    if private_visible:
        assert (
            result["publish_state"] == "unknown"
            and result["failed_step"] == "confirmation"
        )
        assert "Check your uploads" in result["reason"]
        assert result["ui_tree"][0]["text"] == "Uploading"
        assert len(_input_taps(device)) == 1
    else:
        assert (
            result["publish_state"] == "not_attempted"
            and result["failed_step"] == "publish"
        )
        assert not _input_taps(device)


def test_mcp_lists_the_unverified_sample_and_runs_recipes_per_device(
    adb: FakeAdb,
) -> None:
    _recipe([{"id": "open", "type": "open_app"}])
    registry = DeviceRegistry(adb, StateStore.from_environment())

    async def verify() -> None:
        async with create_connected_server_and_client_session(
            create_server(registry)
        ) as client:
            listing = await client.call_tool("list_recipes")
            assert listing.structuredContent is not None
            sample = next(
                item
                for item in listing.structuredContent["recipes"]
                if item["name"] == "youtube_shorts_post"
            )
            assert sample["status"] == "unverified"
            assert sample["params"]["visibility"]["default"] == "public"
            result = await client.call_tool(
                "run_recipe",
                {
                    "name": "sample",
                    "serials": ["emulator-5554", "missing"],
                    "params": {},
                },
            )
            assert result.isError and result.structuredContent is not None
            ready, missing = result.structuredContent["results"]
            assert (
                ready["status"] == "completed"
                and Path(ready["screenshot_path"]).is_file()
            )
            assert (
                missing["status"] == "needs_ai" and missing["failed_step"] == "device"
            )
            assert missing["ui_tree"] == [] and missing["screenshot_path"] is None

    asyncio.run(verify())


def test_recipe_refuses_publish_without_guards_before_any_device_action(
    adb: FakeAdb,
) -> None:
    _recipe(
        [
            {
                "id": "publish",
                "type": "tap",
                "publish": True,
                "selector": {"text": "Upload"},
            },
            {"id": "confirm", "type": "assert", "selector": {"text": "Uploaded"}},
        ]
    )
    assert "on-screen guards" in run_cli(
        "run", "sample", "--devices", "emulator-5554", exit_code=1
    )
    assert not adb.connections


def test_push_falls_back_to_the_adb_tool_when_sync_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from adbutils import AdbError

    from tapherd.devices import adb as adb_module

    class FailingSync:
        def push(self, *args: object, **kwargs: object) -> None:
            raise AdbError("FAIL")

    class Device:
        serial = "emulator-5556"
        sync = FailingSync()

    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> None:
        calls.append(command)

    monkeypatch.setattr(adb_module.shutil, "which", lambda _: "/sdk/adb")
    monkeypatch.setattr(adb_module.subprocess, "run", run)
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"video")
    connection = adb_module._AdbConnection(Device())  # type: ignore[arg-type]
    connection.push_file(source, "/sdcard/DCIM/TapHerd/.tapherd-1.part")
    assert calls == [
        [
            "/sdk/adb",
            "-s",
            "emulator-5556",
            "push",
            str(source),
            "/sdcard/DCIM/TapHerd/.tapherd-1.part",
        ]
    ]


def test_recipes_can_prepare_the_app_before_opening_it(adb: FakeAdb) -> None:
    _recipe(
        [
            {"id": "allow_media", "type": "prepare_app"},
            {"id": "open", "type": "open_app"},
        ]
    )
    device = adb.device("emulator-5554")
    result = json.loads(run_cli("run", "sample", "--devices", "emulator-5554"))
    assert result["results"][0]["status"] == "completed"
    grant = next(i for i, c in enumerate(device.commands) if c[:2] == ("pm", "grant"))
    start = next(i for i, c in enumerate(device.commands) if c[:2] == ("am", "start"))
    assert grant < start


def test_doctor_explains_unauthorized_and_offline_devices(adb: FakeAdb) -> None:
    adb.discovered = [DiscoveredDevice("R58M123", "unauthorized")]
    assert "Allow USB debugging" in run_cli("doctor", exit_code=1)
    adb.discovered = [DiscoveredDevice("emulator-5554", "offline")]
    assert "adb reconnect offline" in run_cli("doctor", exit_code=1)


@pytest.mark.parametrize(
    ("system", "hint"),
    [
        ("Darwin", "brew install"),
        ("Windows", "winget install"),
        ("Linux", "apt install"),
    ],
)
def test_adb_install_hint_matches_the_operating_system(
    monkeypatch: pytest.MonkeyPatch, system: str, hint: str
) -> None:
    from tapherd.devices import adb as adb_module

    monkeypatch.setattr(adb_module.platform, "system", lambda: system)
    assert hint in adb_module.install_adb_hint()


def test_version_flag_prints_the_package_version() -> None:
    result = CliRunner().invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.startswith("tapherd ")


def test_welcome_message_appears_once_in_a_terminal(
    adb: FakeAdb, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True, raising=False)
    cli._welcome_once("devices")
    cli._welcome_once("devices")
    assert capsys.readouterr().err.count("Welcome to TapHerd") == 1
    cli._welcome_once("mcp")
    assert "Welcome" not in capsys.readouterr().err


def test_fourth_device_gets_the_cap_message_with_waitlist_in_cli_and_mcp(
    adb: FakeAdb,
) -> None:
    adb.discovered = [
        DiscoveredDevice(f"emulator-55{54 + 2 * i}", "device") for i in range(4)
    ]
    fourth = "emulator-5560"
    message = run_cli("open-app", fourth, "com.android.settings", exit_code=1)
    assert "up to 3 active devices" in message and "waitlist" in message.lower()

    registry = DeviceRegistry(adb, StateStore.from_environment())

    async def verify() -> None:
        async with create_connected_server_and_client_session(
            create_server(registry)
        ) as client:
            result = await client.call_tool(
                "open_app", {"serial": fourth, "package": "com.android.settings"}
            )
            text = " ".join(getattr(block, "text", "") for block in result.content)
            assert result.isError
            assert "up to 3 active devices" in text and "waitlist" in text.lower()

    asyncio.run(verify())


def test_long_ascii_text_is_typed_in_short_pieces(adb: FakeAdb) -> None:
    serial = "emulator-5554"
    device = adb.device(serial)
    text = "TapHerd lets your own AI agent control Android devices. " * 3
    run_cli("type-text", serial, text)
    typed = [c[2] for c in device.commands if c[:2] == ("input", "text")]
    assert len(typed) == 4
    assert all(len(piece.replace("%s", " ")) <= 50 for piece in typed)
    assert "".join(typed).replace("%s", " ") == text


def test_verified_recipes_must_record_version_date_and_device() -> None:
    from pydantic import ValidationError

    from tapherd.recipes.schema import Recipe

    base = {
        "app_package": "com.google.android.youtube",
        "status": "verified",
        "steps": [{"id": "open", "type": "open_app"}],
    }
    with pytest.raises(ValidationError, match="tested_on"):
        Recipe.model_validate({**base, "tested_app_version": "21.45.88"})
    recipe = Recipe.model_validate(
        {
            **base,
            "tested_app_version": "21.45.88",
            "tested_on": "2026-11-19",
            "tested_device": "emulator",
        }
    )
    assert str(recipe.tested_on) == "2026-11-19"
