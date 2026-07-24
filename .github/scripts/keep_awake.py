"""Drive a real headless Chromium to keep the Streamlit app from hibernating.

Plain HTTP pings don't count as traffic: Streamlit only registers a session
once a browser opens the WebSocket at /_stcore/stream. The real app lives in
a nested iframe (/~/+/), so every DOM lookup scans page.frames rather than
the top-level document.
"""
from __future__ import annotations

import os
import re
import sys
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

APP_URL = os.environ.get(
    "APP_URL",
    "https://corra-rates-analytics-platform-3ncvfa6f4pv2ytsc3pauy7.streamlit.app/",
)

WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)
APP_ROOT = '[data-testid="stApp"]'

PAGE_LOAD_TIMEOUT_MS = 90_000
INITIAL_APP_SECONDS = 20   # short first look: already-running apps appear fast
APP_RENDER_SECONDS = 240   # cold start: boot Python, hit BoC API, bootstrap curves
RELOAD_APP_SECONDS = 120   # one reload before giving up
SESSION_HOLD_MS = 30_000   # hold the WebSocket open so Streamlit counts the session


def _find_in_frames(page, selector: str):
    for frame in page.frames:
        try:
            if frame.locator(selector).count() > 0:
                return frame
        except PlaywrightError:
            continue
    return None


def _poll_frames(page, selector: str, seconds: int):
    deadline = time.time() + seconds
    while time.time() < deadline:
        frame = _find_in_frames(page, selector)
        if frame is not None:
            return frame
        page.wait_for_timeout(2_000)
    return None


def _try_wake(page) -> None:
    """Click the hibernation wake button.

    Match by button text first; fall back to the lone button on the page
    (the hibernation screen only ever renders one).
    """
    for frame in page.frames:
        try:
            button = frame.get_by_role("button", name=WAKE_BUTTON)
            if button.count() > 0:
                button.first.click(timeout=5_000)
                print("Clicked the wake button (matched by name).")
                return
        except PlaywrightError:
            continue

    for frame in page.frames:
        try:
            buttons = frame.locator("button")
            if buttons.count() == 1:
                label = (buttons.first.inner_text(timeout=2_000) or "").strip()
                buttons.first.click(timeout=5_000)
                print(f"Clicked the only button on the page: {label!r}.")
                return
        except PlaywrightError:
            continue

    print("No wake button found; app is presumably still booting.")


def _diagnose(page) -> str:
    lines = [f"url={page.url}", f"title={page.title()!r}", "frames:"]
    for frame in page.frames:
        try:
            body = frame.locator("body").inner_text(timeout=2_000)[:120]
        except PlaywrightError:
            body = "<unreadable>"
        lines.append(f"  {frame.url} :: {body!r}")
    return "\n".join(lines)


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()

        try:
            page.goto(APP_URL, wait_until="domcontentloaded",
                      timeout=PAGE_LOAD_TIMEOUT_MS)
        except PlaywrightTimeout:
            print(f"FAIL: {APP_URL} did not respond within "
                  f"{PAGE_LOAD_TIMEOUT_MS // 1000}s", file=sys.stderr)
            browser.close()
            return 1

        app_frame = _poll_frames(page, APP_ROOT, INITIAL_APP_SECONDS)

        if app_frame is None:
            _try_wake(page)
            app_frame = _poll_frames(page, APP_ROOT, APP_RENDER_SECONDS)

        if app_frame is None:
            print("App root still missing; reloading once.", file=sys.stderr)
            try:
                page.reload(wait_until="domcontentloaded",
                            timeout=PAGE_LOAD_TIMEOUT_MS)
                app_frame = _poll_frames(page, APP_ROOT, RELOAD_APP_SECONDS)
            except PlaywrightTimeout:
                pass

        if app_frame is None:
            print(f"FAIL: {APP_ROOT} never appeared.\n{_diagnose(page)}",
                  file=sys.stderr)
            browser.close()
            return 1

        print("App is up.")
        page.wait_for_timeout(SESSION_HOLD_MS)
        print(f"OK: app live in frame {app_frame.url} "
              f"(title={page.title()!r}); session held "
              f"{SESSION_HOLD_MS // 1000}s.")

        browser.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
