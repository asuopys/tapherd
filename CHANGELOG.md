# Changelog

All notable changes are listed here. TapHerd follows [Semantic Versioning](https://semver.org/). Recipe status changes are always recorded, with the app version and date they were tested.

## [Unreleased]

### Changed

- Posting publishes instead of stopping at drafts. The MCP server tells your AI to finish with the app's final Post, Share, or Upload button, never to save a draft unless you ask, and to use the visibility you ask for (public if you don't say).
- `youtube_shorts_post` now defaults to `public` visibility. Pass `visibility=private` or `unlisted` for a test run.
- Troubleshooting and Windows setup explain why TikTok says "Couldn't post" and saves a draft on `x86_64` emulators, and what to use instead.
- The Supabase waitlist migrations are no longer in the repository.
- `tap`, `swipe`, `type-text`, and `press-key` print a one-line confirmation. The `tap` MCP tool returns the coordinates it tapped.

## [0.1.1] - 2026-11-19

### Changed

- `tapherd doctor` ends with a **Ready** line and the next command to run when everything works.
- `tapherd pro` and the device-limit message now link to the live waitlist at https://tapherd.info/#waitlist.
- The package no longer bundles a copy of the website.
- Clearer README and setup guides, including installing the latest code from GitHub.

## [0.1.0] - 2026-11-19

First public release of the free, MIT-licensed connector.

### Added

- Local MCP server (stdio, or Streamable HTTP on 127.0.0.1) with 15 tools: `list_devices`, `device_info`, `screenshot`, `read_screen`, `tap`, `swipe`, `type_text`, `press_key`, `open_app`, `open_app_many`, `push_media`, `prepare_app`, `remove_media`, `list_recipes`, and `run_recipe`.
- `tapherd` CLI with the same actions, `doctor`, `devices`, `label`, `use` and `unuse`, `inspect`, `run`, `config mcp`, `pro`, and `--version`.
- Up to three active devices on the free tier, with concurrent actions across devices.
- YAML recipe engine that stops with `needs_ai` instead of guessing, and never retries after a publish tap without checking for an existing upload.
- Installers for macOS and Linux (`install.sh`) and Windows (`install.ps1`).
- Setup guides for macOS, Windows (beta), and Linux (beta).

### Recipes

- `youtube_shorts_post`: unverified. It hasn't completed a real post yet.

### Known limitations

- `type_text` needs ADBKeyboard for emoji and other Unicode.
- `read_screen` can't read web page text inside Chrome. Use `screenshot`.
- Windows and Linux pass automated tests but haven't been tried with real devices.
