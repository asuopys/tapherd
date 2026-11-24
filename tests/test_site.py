import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
REPO = "https://github.com/asuopys/tapherd"


def _page() -> str:
    return (SITE / "index.html").read_text(encoding="utf-8")


def test_every_local_asset_the_pages_reference_exists() -> None:
    referenced: set[str] = set()
    for name in ("index.html", "docs.html", "privacy.html"):
        page = (SITE / name).read_text(encoding="utf-8")
        referenced |= set(
            re.findall(r'(?:src|poster|href|content|data-loop)="(assets/[^"]+)"', page)
        )
        referenced |= set(re.findall(r'href="([a-z]+\.html)"', page))

    assert referenced, "The pages should reference their local assets."
    for asset in referenced:
        assert (SITE / asset).is_file(), f"{asset} is referenced but missing"
        assert not asset.endswith((".mp4", ".mov")), (
            "Use looping images, not video files"
        )


def test_page_keeps_signup_video_and_analytics_off_until_configured() -> None:
    page = _page()

    assert "Real screen recording, sped up" in page
    # Demo videos are looping images served from the site, not third-party embeds.
    assert "<video" not in page and "<iframe" not in page and "loom.com" not in page
    loops = re.findall(r'data-loop="(assets/[^"]+)"', page)
    assert loops, "The hero should play the recorded run as a loop"
    for loop in loops:
        path = SITE / loop
        assert path.suffix in (".webp", ".gif") and path.is_file(), loop
        assert path.stat().st_size < 4_000_000, f"{loop} is too large for the page"
    token = re.search(r'name="tapherd-analytics-token" content="([^"]*)"', page).group(
        1
    )
    assert token == "" or re.fullmatch(r"[0-9a-f]{32}", token)
    assert '<fieldset id="signup-fields" disabled>' in page
    # The page may only carry Supabase's public, insert-only publishable key.
    url, key = re.search(
        r'data-supabase-url="([^"]*)" data-supabase-key="([^"]*)"', page
    ).groups()
    assert url == "" or re.fullmatch(r"https://[a-z0-9]{20}\.supabase\.co", url)
    assert key == "" or key.startswith("sb_publishable_")
    assert "sb_secret_" not in page and "service_role" not in page
    assert "We'll email you about TapHerd Pro. Unsubscribe anytime." in page


def test_disclaimer_and_link_preview_tags_are_present() -> None:
    disclaimer = (
        "TapHerd is not affiliated with or endorsed by TikTok, Meta, Google, or X. "
        "All trademarks belong to their owners."
    )
    for path in (
        SITE / "index.html",
        SITE / "docs.html",
        SITE / "privacy.html",
        ROOT / "README.md",
    ):
        assert disclaimer in path.read_text(encoding="utf-8"), path
    page = _page()
    for tag in ("og:title", "og:description", "og:image", "twitter:card"):
        assert tag in page
    # Link previews need absolute URLs on the live domain.
    domain = (SITE / "CNAME").read_text(encoding="utf-8").strip()
    assert f'content="https://{domain}/assets/og-image.jpg"' in page
    assert (SITE / "assets" / "og-image.jpg").is_file()


def test_public_copy_avoids_overclaiming() -> None:
    banned = (
        "prevents misuse",
        "undetectable",
        "undetected",
        "safe for your accounts",
        "guaranteed",
        "account farm",
        "mass accounts",
        "bypass",
        "revolutionary",
        "game-changing",
    )
    for path in (
        SITE / "index.html",
        SITE / "docs.html",
        SITE / "privacy.html",
        ROOT / "README.md",
    ):
        text = path.read_text(encoding="utf-8").lower()
        for phrase in banned:
            assert phrase not in text, f"{phrase!r} in {path.name}"


def test_page_loads_only_local_assets_and_links_only_to_the_repository() -> None:
    page = _page()

    loaded = re.findall(r'(?:src|poster)="([^"]+)"', page)
    assert loaded and all(url.startswith("assets/") for url in loaded)
    external = re.findall(r'href="(https?://[^"]+)"', page)
    assert external, "The install section should link to the repository"
    assert all(url.startswith(REPO) for url in external), external


EMAIL_CASES = {
    "name@example.com": True,
    "first.last+tag@mail.example.co.uk": True,
    "a_b-c%d@sub-domain.example.io": True,
    "name@example": False,
    "name@example.c": False,
    "name@@example.com": False,
    "name@exa mple.com": False,
    "name..dots@example.com": False,
    ".name@example.com": False,
    "name.@example.com": False,
    "name@example..com": False,
    "name@example.123": False,
    "a@b.co": True,
    "x@y.z": False,
}


def _sql_valid(email: str, migration: str) -> bool:
    pattern = re.search(r"email ~ '([^']+)'", migration)
    length = re.search(r"between (\d+) and (\d+)", migration)
    assert pattern and length
    low, high = int(length.group(1)), int(length.group(2))
    return (
        email == email.strip().lower()
        and low <= len(email) <= high
        and re.fullmatch(pattern.group(1), email) is not None
        and ".." not in email
        and not email.startswith(".")
        and ".@" not in email
    )


def _page_valid(email: str, page: str) -> bool:
    pattern = re.search(r"const EMAIL = /(.+)/;", page)
    assert pattern
    return (
        6 <= len(email) <= 254
        and re.fullmatch(pattern.group(1), email) is not None
        and ".." not in email
        and not email.startswith(".")
        and ".@" not in email
    )


def test_page_and_database_accept_the_same_emails() -> None:
    # The migrations live only in the maintainer's local checkout, not in Git.
    found = sorted((ROOT / "supabase" / "migrations").glob("*_waitlist.sql"))
    if not found:
        pytest.skip("Supabase migrations are kept out of the repository")
    migration = found[0].read_text(encoding="utf-8")
    page = _page()
    for email, expected in EMAIL_CASES.items():
        assert _sql_valid(email, migration) is expected, email
        assert _page_valid(email, page) is expected, email


# Symbols that iOS draws as color emoji unless told otherwise. Use CSS shapes or
# plain text instead (✓ U+2713 and arrows like → are safe).
EMOJI_PRONE = {0x2733, 0x2734, 0x25B6, 0x25C0, 0x2714, 0x2716, 0x2728, 0x2B50, 0x2764}


def test_site_avoids_symbols_ios_turns_into_emoji() -> None:
    for path in [
        *SITE.glob("*.html"),
        *(SITE / "assets").glob("*.js"),
        *(SITE / "assets").glob("*.css"),
    ]:
        text = path.read_text(encoding="utf-8")
        found = sorted(
            {
                f"U+{ord(ch):04X}"
                for ch in text
                if ord(ch) in EMOJI_PRONE or ord(ch) >= 0x1F000
            }
        )
        assert not found, f"{path.name} has emoji-prone symbols: {found}"
