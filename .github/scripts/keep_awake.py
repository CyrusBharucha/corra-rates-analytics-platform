"""Keeps the Streamlit Community Cloud deployment from hibernating.

Community Cloud sleeps an app after ~12 hours with no traffic, but a plain
HTTP request does not count as traffic: the GET only returns the static HTML
shell. The Python process is started by the browser, which runs the page's
JavaScript and opens a WebSocket to /_stcore/stream. That is why HTTP-only
monitors (UptimeRobot and friends) report a healthy 200 while the app sleeps
anyway.

So this drives a real headless Chromium: load the page, click the wake button
if the hibernation screen is showing, then hold the socket open long enough
for Streamlit to register a genuine session.

Note on frames: streamlit.app serves an empty outer shell and mounts the real
app in a nested iframe (/~/+/). Both the app root and the hibernation wake
button live in that frame, not the top-level document, so every lookup here
scans page.frames rather than the main document.
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

# Text on the hibernation screen's wake button.
WAKE_BUTTON = re.compile(r"get this app back up", re.IGNORECASE)
APP_ROOT = '[data-testid="stApp"]'

PAGE_LOAD_TIMEOUT_MS = 90_000
# If the app is already running its root shows up almost immediately, so a
# short first look tells us whether we need the wake path at all.
INITIAL_APP_SECONDS = 20
# A cold start has to boot Python, hit the BoC API and bootstrap the curves,
# so give it room; the job itself is capped in the workflow.
APP_RENDER_SECONDS = 240
# Streamlit occasionally leaves the shell on the hibernation screen after the
# backend is already up, so one reload is worth a try before giving up.
RELOAD_APP_SECONDS = 120
# Streamlit only counts a session once the WebSocket has been open a moment,
# so linger rather than exiting the instant the DOM appears.
SESSION_HOLD_MS = 30_000


def _find_in_frames(page, selector: str):
    """First frame containing selector, or None. Includes the main frame."""
    for frame in page.frames:
        try:
            if frame.locator(selector).count() > 0:
                return frame
        except PlaywrightError:
            continue  # frame detached or still navigating
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
    """Click the hibernation screen's wake button.

    Matching on the button's wording alone is brittle, since Streamlit is free
    to reword it. The hibernation screen only ever renders a single button, so
    fall back to clicking whatever lone button is on the page.
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
            # Not up yet: either hibernating (needs a click) or mid-boot.
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
