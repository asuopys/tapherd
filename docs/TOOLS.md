# MCP tools

TapHerd's MCP server gives your AI client 15 tools. Every tool returns a JSON text block with `"ok": true` or `"ok": false`. When something fails, the message says what to do next, for example `Run tapherd devices and check that the device is online.` [Connect your AI](CONNECT_YOUR_AI.md)

Coordinates are native screen pixels, as reported by `device_info` and `read_screen`. A `serial` is the ID shown by `list_devices`, such as `emulator-5554`. Only active devices count, and Free allows up to three.

## Devices

### `list_devices`

Lists detected Android devices, which are active, and the free-tier limit. Takes no parameters.

```json
{"ok": true, "devices": [{"serial": "emulator-5554", "status": "device", "active": true, "label": "Pixel 1", "group": "Demo", "model": "sdk_gphone64_arm64", "android_version": "14"}], "selection_mode": "auto", "tier": "free", "device_limit": 3, "max_concurrency": 3}
```

### `device_info`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |

```json
{"ok": true, "serial": "emulator-5554", "status": "device", "active": true, "label": "Pixel 1", "group": "Demo", "model": "sdk_gphone64_arm64", "android_version": "14", "screen_size": {"width": 1080, "height": 2400}, "foreground_app": "com.android.settings"}
```

## See the screen

### `screenshot`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `max_width` | integer, default 720 | The image is scaled down to this width if it's wider. |

Returns the PNG as an image block, plus:

```json
{"ok": true, "serial": "emulator-5554", "width": 720, "height": 1600, "mime_type": "image/png"}
```

### `read_screen`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |

Returns up to 150 on-screen elements. Empty, non-clickable elements are dropped.

```json
{"ok": true, "serial": "emulator-5554", "elements": [{"text": "Network & internet", "resource_id": "android:id/title", "content_desc": "", "class": "android.widget.TextView", "bounds": [126, 560, 954, 630], "center": [540, 595], "clickable": false, "scrollable": false}]}
```

`read_screen` uses Android's UI dump, which doesn't include web page text inside Chrome. Use `screenshot` for web pages.

## Act in any app

### `tap`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `x`, `y` | integers, optional | Native pixel coordinates |
| `selector` | object, optional | One of `{"text": …}`, `{"resource_id": …}`, or `{"content_desc": …}`, matching exactly |

Give either coordinates or a selector. A selector that matches more than one element is refused, so be more specific. The reply includes the coordinates that were tapped. On the command line, use `tapherd tap <serial> --text "…"` or `tapherd tap <serial> <x> <y>`.

```json
{"ok": true, "serial": "emulator-5554", "x": 540, "y": 893}
```

### `swipe`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `direction` | `up`, `down`, `left`, or `right`, optional | |
| `x1`, `y1`, `x2`, `y2` | integers, optional | Swipe between two points instead of a direction |
| `duration_ms` | integer, default 300 | |

```json
{"ok": true, "serial": "emulator-5554"}
```

### `type_text`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device with a focused text field |
| `text` | string | Plain single-line ASCII works with Android's keyboard. Emoji, other Unicode, and line breaks need ADBKeyboard. [Troubleshooting](TROUBLESHOOTING.md#type-emoji-and-other-unicode-text) |

Long text is sent in short pieces so Android doesn't drop the end.

```json
{"ok": true, "serial": "emulator-5554"}
```

### `press_key`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `key` | `back`, `home`, `enter`, `recents`, or `delete` | |

```json
{"ok": true, "serial": "emulator-5554"}
```

### `open_app`

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `package` | string | For example `com.android.settings` |

```json
{"ok": true, "serial": "emulator-5554", "package": "com.android.settings"}
```

## Work across devices

### `open_app_many`

Opens one app on several active devices at the same time.

| Parameter | Type | Notes |
| --- | --- | --- |
| `package` | string | |
| `serials` | list of 1–3 strings, optional | Give either `serials` or `group`. |
| `group` | string, optional | A group set with `tapherd label <serial> <name> --group <group>` |

```json
{"ok": true, "package": "com.android.settings", "results": [{"serial": "emulator-5554", "ok": true}, {"serial": "emulator-5556", "ok": true}]}
```

## Post content

### `push_media`

Copies a video or image from your computer into the device's gallery under a unique name.

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `local_path` | string | Absolute path on the computer running TapHerd |

```json
{"ok": true, "serial": "emulator-5556", "device_path": "/sdcard/DCIM/TapHerd/demo-6e32a2448e87447ea27d4dfd652c45fb.mp4"}
```

### `prepare_app`

Gets a posting app ready to upload. It allows access to all photos and videos, replacing "selected photos only", and turns off the camera and microphone so Android stops asking. Android closes the app if it is running, so call this before `open_app`.

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `package` | string | For example `com.google.android.youtube` |

```json
{"ok": true, "serial": "emulator-5556", "package": "com.google.android.youtube", "allowed": ["android.permission.READ_MEDIA_IMAGES", "android.permission.READ_MEDIA_VIDEO"], "denied": ["android.permission.CAMERA", "android.permission.RECORD_AUDIO"], "skipped": ["android.permission.READ_EXTERNAL_STORAGE"]}
```

### `remove_media`

Deletes a file that `push_media` copied, for example after posting. It refuses any path that `push_media` didn't create.

| Parameter | Type | Notes |
| --- | --- | --- |
| `serial` | string | Active device |
| `device_path` | string | The `device_path` that `push_media` returned |

```json
{"ok": true, "serial": "emulator-5556", "removed": "/sdcard/DCIM/TapHerd/demo-6e32a2448e87447ea27d4dfd652c45fb.mp4"}
```

Some apps save their own copy of a posted video, for example to `DCIM/Camera`. `remove_media` doesn't touch those.

### `list_recipes`

Lists posting recipes, with their test status and parameters. Takes no parameters.

```json
{"ok": true, "recipes": [{"name": "youtube_shorts_post", "app_package": "com.google.android.youtube", "tested_app_version": null, "tested_on": null, "tested_device": null, "status": "unverified", "params": {"video_path": {"type": "video", "description": "Path to a local vertical or square test video."}}}]}
```

### `run_recipe`

Runs a posting recipe on one or more active devices. If any step can't be confirmed, that device returns `needs_ai` with the failed step, a fresh UI tree, and a screenshot path, so your agent can finish with the generic tools. Recipes publish the post rather than saving a draft. Pass the visibility the user wants; the YouTube Shorts recipe defaults to `public`. A recipe never retries after its publish tap without checking whether the post already exists.

| Parameter | Type | Notes |
| --- | --- | --- |
| `name` | string | From `list_recipes` |
| `serials` | list of strings | Up to three active devices |
| `params` | object of strings | The recipe's parameters, for example `{"video_path": "/Users/me/clip.mp4", "title": "…", "visibility": "public"}` |

```json
{"ok": false, "recipe": "youtube_shorts_post", "recipe_status": "unverified", "run_id": "…", "results": [{"serial": "emulator-5556", "status": "needs_ai", "failed_step": "wait_for_upload_menu", "reason": "…", "screenshot_path": "…/runs/…/emulator-5556.png", "ui_tree": [], "ui_tree_source": "current", "media_path": "/sdcard/DCIM/TapHerd/…mp4", "publish_state": "not_attempted"}]}
```

Recipes and scheduling only support posting to accounts you own. [Acceptable use](ACCEPTABLE_USE.md) · [Recipes](RECIPES.md)
