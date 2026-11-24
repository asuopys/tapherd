# Set up TapHerd on Windows (beta)

TapHerd's automated tests pass on Windows 10 and 11 with Python 3.11–3.13. Real devices haven't been tried on Windows yet, so treat it as beta and [report anything that breaks](https://github.com/asuopys/tapherd/issues/new/choose).

## Fastest path: the installer

Open **PowerShell** (not as administrator) and run:

```powershell
irm https://raw.githubusercontent.com/asuopys/tapherd/main/scripts/install.ps1 | iex
```

The script installs uv and Android Platform-Tools for your user, then TapHerd, and runs `tapherd doctor`. Before it installs anything, it says what it will do. It never needs administrator rights. To read it first, open [scripts/install.ps1](../scripts/install.ps1).

## Manual install

1. Install uv: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
2. Install Android Platform-Tools: `winget install --id Google.PlatformTools`. Open a **new** terminal afterwards so `adb` is on PATH.
3. Install TapHerd: `uv tool install tapherd`.
4. Check: `tapherd doctor`.

## Download the Android emulator

1. Turn on virtualization. In your BIOS or UEFI, enable **Intel VT-x** or **AMD-V** (often called SVM). In Windows, open **Turn Windows features on or off**, tick **Windows Hypervisor Platform**, and restart.
2. Download [Android Studio](https://developer.android.com/studio) and run the installer. Choose the **Standard** setup, which downloads the SDK, the emulator, and Platform-Tools.
3. Open **More Actions → Virtual Device Manager**. Create a **Pixel** device with the Play Store icon and a **Google Play** system image at **API 34 or later** with architecture **x86_64**. On an Arm Windows laptop, choose **arm64-v8a**. TikTok usually can't post from an `x86_64` emulator; use a real phone for TikTok. [Why](TROUBLESHOOTING.md#tiktok-says-couldnt-post-and-saves-a-draft)
4. Start it and wait for the home screen. `adb devices -l` should list `emulator-5554  device`.

Android Studio's SDK lives in `%LOCALAPPDATA%\Android\Sdk`. If `adb` isn't found, add `%LOCALAPPDATA%\Android\Sdk\platform-tools` to your user PATH.

## Use a real phone

Turn on **Developer options** and **USB debugging** on the phone. Install your phone maker's USB driver ([list](https://developer.android.com/studio/run/oem-usb)); Pixel phones use the Google USB Driver from Android Studio's SDK Manager. Connect, accept **Allow USB debugging**, and run `tapherd devices`.

## Connect your AI

```powershell
tapherd config mcp --client claude-desktop
```

Paste the output where it says. For Claude Desktop that's `%APPDATA%\Claude\claude_desktop_config.json`. [All clients](CONNECT_YOUR_AI.md)

## Known differences on Windows

- Run commands in PowerShell or Windows Terminal. Output is UTF-8, so labels with emoji print correctly.
- Paths in `push-media` can use either `C:\Users\you\clip.mp4` or `C:/Users/you/clip.mp4`.

Problems? See [Troubleshooting](TROUBLESHOOTING.md).
