# Getting started, step by step

From zero to your AI tapping on an Android phone. Most people finish in 10 to 20 minutes, mostly waiting for the emulator to download. You don't need to know Python or Android.

There's an illustrated version of this guide at [tapherd.info/docs.html](https://tapherd.info/docs.html).

## 1. Get an Android device

TapHerd controls any Android device your computer can reach with Android's `adb` tool.

**Option A: a free emulator (recommended)**

1. Download [Android Studio](https://developer.android.com/studio) and install it.
2. Open it and choose the **Standard** setup. It downloads the emulator and `adb`.
3. Open **More Actions → Virtual Device Manager**, then **+ → Create Virtual Device**.
4. Pick a **Pixel** with the Play Store icon, and a **Google Play** system image at API 34 or later. Choose `arm64-v8a` on Apple chips, and `x86_64` on Intel and AMD computers.
5. Press **Play** and wait for the home screen.

- **Windows:** turn on virtualization first. [Windows setup](SETUP_WINDOWS.md)
- **Linux:** check KVM first. [Linux setup](SETUP_LINUX.md#check-kvm)

**Option B: your own Android phone**

1. Open **Settings → About phone** and tap **Build number** seven times.
2. Open **Settings → System → Developer options** and turn on **USB debugging**.
3. Connect it with a data cable, unlock it, and accept **Allow USB debugging**.

To post to apps such as TikTok, Instagram, or YouTube, install them on the device and sign in to your own accounts yourself. TapHerd never asks for passwords.

## 2. Install TapHerd

macOS and Linux, in Terminal:

```sh
curl -LsSf https://raw.githubusercontent.com/asuopys/tapherd/main/scripts/install.sh | sh
```

Windows, in PowerShell (no administrator rights needed):

```powershell
irm https://raw.githubusercontent.com/asuopys/tapherd/main/scripts/install.ps1 | iex
```

The installer sets up uv and TapHerd for your user, checks for `adb` and asks before installing it, then runs `tapherd doctor`. Open a new terminal window afterwards.

Prefer to do it by hand? Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run `uv tool install tapherd`.

## 3. Check everything

With the emulator or phone on:

```sh
tapherd doctor
```

You should see your device listed, for example `Active and online: emulator-5554`, and a last line that starts with **Ready**. If it says no device, `unauthorized`, or `offline`, it prints the next command to run. [Troubleshooting](TROUBLESHOOTING.md)

## 4. Connect your AI

| Your AI app | Run | Then |
| --- | --- | --- |
| Claude Code | `tapherd config mcp --client claude-code > .mcp.json` | Start `claude` in that folder and approve **tapherd**. |
| Claude Desktop | `tapherd config mcp --client claude-desktop` | **Settings → Developer → Edit Config**, add the `tapherd` entry, then quit and reopen Claude. |
| Codex | `tapherd config mcp --client codex` | Add the block to `~/.codex/config.toml` and start a new session. |
| Cursor | `tapherd config mcp --client cursor` | Add the entry to `~/.cursor/mcp.json` and reload Cursor. |

If the file already lists other servers, add `tapherd` next to them. [Exact paths for every system](CONNECT_YOUR_AI.md)

## 5. Your first AI tap

Ask your AI:

> Use TapHerd to list my devices. On the first one, open Settings, read the screen, tap Network & internet, and tell me what opened.

Settings opens, then **Network & internet**. Your AI can now read the screen, tap, swipe, type, and open apps. [All 15 tools](TOOLS.md)

## 6. Post a video (optional)

Put the video where your AI can read it, then ask something like:

> Using TapHerd, copy launch.mp4 to my phone and post it to TikTok, Instagram Reels, and YouTube Shorts. Write a caption and tags for each, and post them publicly. Delete the copy from the phone when you're done.

Your AI uses `push_media` to copy the file, `prepare_app` to allow photo access and turn off camera and microphone prompts, taps through each app, and finishes with `remove_media`. It publishes each post with the visibility you ask for, such as Public, Unlisted, Friends, or Only me. If you don't say, it posts publicly. Only post to accounts you own. [Acceptable use](ACCEPTABLE_USE.md)

## 7. Add more phones (optional)

Free uses up to three devices at once.

```sh
tapherd devices
tapherd label emulator-5556 "Pixel 2" --group Creators
tapherd use emulator-5556
```

Then ask your AI to work across a group: *"Open Settings on every phone in the Creators group."*

Running more than three? [Pro](https://tapherd.info/#pro) is planned for 50+ devices, a dashboard, and scheduled posting. Run `tapherd pro` to join the waitlist.
