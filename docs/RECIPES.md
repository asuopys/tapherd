# Write and run posting recipes

TapHerd includes `youtube_shorts_post` as an unverified sample. The source is in [src/tapherd/recipes/bundled/youtube_shorts_post.yaml](../src/tapherd/recipes/bundled/youtube_shorts_post.yaml). It publishes the Short with the visibility you choose: `public` (the default), `unlisted`, or `private`. Use a video you own and an account you own. YouTube's Android workflow needs an audience setting as well as a title and visibility. [YouTube Shorts upload guide](https://support.google.com/youtube/answer/12779649?hl=en&co=GENIE.Platform%3DAndroid)

## Run the Shorts sample

```sh
tapherd recipes
tapherd run youtube_shorts_post --devices emulator-5554 \
  --param 'video_path=/absolute/path/to/your-test-video.mp4' \
  --param 'title=My first TapHerd Short' \
  --param 'visibility=public'
```

Repeat `--param` to pass a description. Set `visibility=private` or `visibility=unlisted` for a test run. If you supply a description, the recipe requires the editor to show it before proceeding. The sample checks the chosen visibility, title, and audience on the upload screen before tapping the upload button. Use `list_recipes` and `run_recipe` for the same workflow in an MCP client. [MCP setup](MCP.md)

Pass a comma-separated list to `--devices` to run on multiple active devices with TapHerd's configured concurrency limit. Each device gets its own result. The CLI prints the result as JSON and returns exit code 1 if any device needs review.

## Review a stopped run

A `needs_ai` result includes the step ID, what failed, a local screenshot path when available, and the observed UI tree. `ui_tree_source` indicates whether TapHerd captured a fresh tree, reused its last observation, or could not read one. Screenshots are saved under the local registry's `runs` directory. Use `tapherd inspect <serial>` or the MCP screen tools to check the device before continuing.

The picker step matches the exact filename TapHerd assigned during that run. If the picker shows thumbnails without filenames, open the picker view that shows filenames and locate the returned `media_path` before choosing the video.

After a publish tap, `publish_state` is `unknown` until the recipe sees its confirmation. A timeout returns `needs_ai` with the observed screen. Check **Your videos** for the Short and its visibility before retrying. The engine dispatches each step once.

## Write and test your own YAML

Put a trusted `.yaml` file in the local registry's `recipes` directory, normally `~/.config/tapherd/recipes/`. If you set `TAPHERD_STATE_DIR`, put it under that directory. The filename stem is the name you pass to `tapherd run`. Choose your own name when adapting the bundled sample.

Start by opening the app and capturing its screen. For example, save this as `inspect_youtube.yaml`.

```yaml
app_package: com.google.android.youtube
tested_app_version: null
tested_on: null
tested_device: null
status: unverified
params: {}
steps:
  - id: open_youtube
    type: open_app
  - id: capture_home
    type: screenshot
```

Use `tapherd recipes` to check that TapHerd can load the file. Run it on one test emulator, then use `tapherd inspect` to collect the exact labels and resource IDs your app version exposes. Give each step a unique `id`, and keep the recipe unverified until you test the complete workflow on the real app. Record the app version when marking your recipe verified.

| Step type | Fields |
| --- | --- |
| `prepare_app` | Gives the recipe's app access to all photos and videos and turns off its camera and microphone, so upload screens aren't interrupted. Put it before `open_app`, because Android closes the app when a permission is turned off. |
| `open_app` | Opens the recipe's `app_package`. |
| `wait_for` | `selector`, optional `fallbacks`, and `timeout` in seconds. |
| `assert` | `selector` and optional `fallbacks`. Checks the current UI. |
| `tap` | `selector`, optional `fallbacks`, and optional `require` guards checked from the same UI tree. |
| `type` | `text` to enter into the focused field. |
| `push_media` | Local `path` to a media file. Saves the unique device path for the picker. |
| `choose_media` | Optional `timeout`. Selects the exact file from the preceding push. |
| `swipe` | `direction` or `coordinates: [x1, y1, x2, y2]`. Optional `duration_ms`. |
| `screenshot` | Saves a local PNG using the step ID. The run also returns a final PNG. |

A selector has one field from `text`, `text_contains`, `resource_id`, `content_desc`, or `regex`. Exact fields compare the full value. Regex searches visible text and accessibility descriptions. TapHerd tries fallbacks in order when a selector has no match. Multiple distinct matches stop the run for review.

Declare `params` with a `type` of `text`, `file`, `video`, or `choice`. A parameter without a `default` is required. Choice parameters declare `choices`. Insert values in step strings with `{{ parameter_name }}`. Values inserted into a regex are escaped. A step with `when_param: name` runs only when that parameter is nonempty.

Mark the final upload tap with `publish: true`, set its `require` guards, and follow it immediately with a `wait_for` or `assert` that confirms the upload. Later steps may only check the screen or take screenshots.
