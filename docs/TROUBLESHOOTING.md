# Troubleshooting

Start with `tapherd doctor`. It checks Python, ADB, and your devices, and tells you the next command to run.

## No device found

- **Emulator:** start it from Android Studio's Device Manager and wait for the home screen. Then run `adb devices -l`. You should see `emulator-5554  device`.
- **Phone:** turn on Developer options (tap **Build number** seven times in **Settings → About phone**), then turn on **USB debugging** and connect with a data cable. Some cables only charge.
- Run `tapherd devices`. Free uses up to three active devices. If a fourth is connected, choose with `tapherd use <serial>`.

## `unauthorized`

The phone hasn't trusted this computer yet. Unlock it, accept **Allow USB debugging**, and tick **Always allow from this computer**. If no prompt appears, run `adb kill-server`, then `adb devices`, and check the phone again.

## `offline`

Run `adb reconnect offline`. For an emulator, restart it from Device Manager. If it stays offline, run `adb kill-server` and then `tapherd doctor`.

## The emulator won't boot

- Make sure the system image is **arm64-v8a** on Apple Silicon, or **x86_64** on Intel and AMD computers.
- Give it more memory, or run fewer emulators at once. Two emulators need about 8 GB of free memory.
- In Device Manager, choose **Wipe Data** or **Cold Boot Now**.

## Windows: virtualization

The emulator needs hardware virtualization. Turn on **Virtualization (VT-x or AMD-V)** in your BIOS or UEFI, then in Windows **Turn Windows features on or off**, turn on **Windows Hypervisor Platform**, and restart. [Windows setup](SETUP_WINDOWS.md)

## Windows: USB drivers

Many phones need their manufacturer's USB driver for ADB. Google Pixel phones use the Google USB Driver from Android Studio's SDK Manager. Other brands list theirs on their support sites. [Android OEM USB drivers](https://developer.android.com/studio/run/oem-usb)

## Linux: permission denied or no USB device

Add a udev rule so your user can talk to the phone, then reconnect it. [Linux setup](SETUP_LINUX.md#let-adb-reach-a-usb-phone)

## Linux: the emulator is very slow

Check that KVM works with `ls -l /dev/kvm` and that your user is in the `kvm` group. [Linux setup](SETUP_LINUX.md#check-kvm)

## Type emoji and other Unicode text

Android's built-in `input text` command only types plain single-line ASCII. For emoji, accented letters, other scripts, or line breaks, install the open-source ADBKeyboard on the device and select it as the keyboard. [Steps](SETUP_MAC.md#tap-swipe-and-type) TapHerd then sends the text through ADBKeyboard automatically. Long plain-ASCII text is typed in pieces, so captions aren't cut off.

## `uv tool install tapherd` says TapHerd wasn't found

Recent uv versions skip packages uploaded in the last few days, as a safety delay. If TapHerd was released very recently, exempt it, and only it:

```sh
uv tool install --exclude-newer-package tapherd=false tapherd
```

The installers already do this.

## An app asks for camera, microphone, or photo permissions

Run `tapherd prepare-app <serial> <package>` before opening the app. It allows access to all photos and videos and turns off the camera and microphone, so upload screens aren't interrupted. It closes the app if it's open.

## `push-media` failed on an emulator

Some emulator versions reject the first transfer method. TapHerd automatically retries with the `adb push` tool. If it still fails, check that the file exists and is a video or image, and run `adb devices` to confirm the device is online.

## TikTok says "Couldn't post" and saves a draft

This comes from TikTok, not TapHerd. TikTok often refuses to post from an emulator on a Windows or Linux PC with an Intel or AMD processor. The emulator is `x86_64`, and TikTok only ships Arm code, so it runs through a translation layer. When the upload fails, TikTok moves the video to **Drafts** by itself.

To post to TikTok, use a real Android phone with USB debugging on, or an `arm64-v8a` emulator on an Arm computer such as a Mac with Apple silicon. Then open the draft and tap **Post**, or post the video again. TapHerd won't try to hide that a device is an emulator. [Acceptable use](ACCEPTABLE_USE.md)

## A recipe returned `needs_ai`

That's on purpose. The recipe couldn't confirm a step, so it stopped instead of guessing. The result includes the failed step, a fresh screen tree, and a screenshot path. Your AI client can finish the job with the generic tools. If a recipe keeps stopping at the same step after an app update, open a recipe report. [Recipes](RECIPES.md)

## My AI client doesn't see TapHerd's tools

1. Run `tapherd config mcp --client <client>` again and check where it says to put the snippet. [Connect your AI](CONNECT_YOUR_AI.md)
2. Make sure the JSON or TOML is still valid after you edit it, with no trailing commas.
3. Restart the client completely. Claude Desktop needs to be quit, not just closed.
4. In Claude Code, approve the project's `tapherd` server when prompted. Run `/mcp` to see its status.
5. Run the command from the snippet yourself, for example `/path/to/python -m tapherd.mcp_server`. If it prints an error, fix that first. If it waits silently, it's working. Press Ctrl+C.

## `read_screen` doesn't show text on a web page

Chrome's page content isn't part of Android's UI dump. Use `screenshot` for web pages.

Still stuck? Open a bug report with the output of `tapherd doctor` and `tapherd --version`, and remove any account names first.
