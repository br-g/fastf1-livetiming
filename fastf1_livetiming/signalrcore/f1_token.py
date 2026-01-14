"""Simple F1 login to retrieve subscription token.

This module provides a single function to log in to F1 TV and retrieve
the subscription token needed for API access.

Acknowledgments:
    A massive shoutout to @eepzii for his great work on the Paddock project
    (https://github.com/eepzii/paddock). It was a primary source of inspiration for this
    implementation.

Environment Variables:
    F1_EMAIL: F1 TV account email
    F1_PASSWORD: F1 TV account password

Example:
    >>> import f1_token
    >>> token = f1_token.get_token()
    >>> print(token)
    'eyJ...'
"""

import asyncio
import json
import os
import re

from loguru import logger
from playwright.async_api import Page, Route
from playwright.async_api import TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

LOGIN_URL = "https://account.formula1.com/#/en/login?redirect=https%3A%2F%2Fwww.formula1.com%2Fen&lead_source=web_f1core"
API_PATTERN = re.compile(r".*/account/subscriber/authenticate/by-password")

# Retry Settings
MAX_RETRIES = 5
BASE_DELAY = 5


class AuthError(Exception):
    """Raised when authentication fails definitively (401/403)."""

    pass


class LoginRetryError(Exception):
    """Raised when login fails after multiple retries."""

    pass


async def _handle_consent(page: Page) -> None:
    try:
        iframe_selector = (
            "iframe[src*='consent.formula1.com'], iframe[title*='Consent']"
        )

        try:
            await page.wait_for_selector(
                iframe_selector, timeout=30000, state="visible"
            )
        except PlaywrightTimeout:
            return

        logger.info("  Consent banner found. Attempting to accept...")

        try:
            frame = page.frame_locator(iframe_selector).first
            accept_btn = frame.get_by_role(
                "button", name=re.compile(r"(ACCEPT|AGREE|YES)", re.IGNORECASE)
            ).first
            if await accept_btn.is_visible():
                await accept_btn.click()
                await asyncio.sleep(1)
        except Exception:
            pass

        try:
            await page.evaluate(
                f"""
                const iframes = document.querySelectorAll("{iframe_selector}");
                iframes.forEach(iframe => {{
                    const container = iframe.closest('div[id^="sp_message_container"]');
                    if (container) container.remove();
                    else iframe.remove();
                }});
            """
            )
            logger.info("  Consent banner cleanup done.")
        except Exception as e:
            # Ignore "context destroyed" errors caused by successful navigation
            if "Execution context was destroyed" not in str(e):
                logger.warning(f"  Consent cleanup error: {e}")

    except Exception as e:
        logger.warning(f"  Consent handling warning: {e}")


async def _intercept_token(route: Route, token_future: asyncio.Future) -> None:
    try:
        response = await route.fetch()
        status = response.status

        if status == 200:
            try:
                body = await response.json()
                data = body.get("data", {})
                token = data.get("subscriptionToken") or data.get("subscription_token")

                if token and not token_future.done():
                    token_future.set_result(token)
            except json.JSONDecodeError:
                pass
        elif status == 403:
            if not token_future.done():
                token_future.set_exception(AuthError("403 Forbidden - Bot detected"))
        elif status == 401:
            if not token_future.done():
                token_future.set_exception(
                    AuthError("401 Unauthorized - Check Password")
                )

        await route.fulfill(response=response)
    except Exception:
        try:
            await route.continue_()
        except:
            pass


async def _login_attempt(email: str, password: str, headless: bool) -> str:
    logger.info(f"Launching browser (Headless: {headless})...")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-background-networking",
                "--disable-blink-features=AutomationControlled",
            ],
            ignore_default_args=["--enable-automation"],
        )

        context = await browser.new_context()
        page = await context.new_page()

        await page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        try:
            token_future = asyncio.Future()
            await page.route(
                API_PATTERN, lambda route: _intercept_token(route, token_future)
            )

            logger.info("  Navigating to F1 login...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

            await _handle_consent(page)

            logger.info("  Waiting for login form...")
            email_input = page.locator("input[name='Login'], input[type='email']").first
            pass_input = page.locator(
                "input[name='Password'], input[type='password']"
            ).first
            submit_btn = page.locator(
                "button[type='submit'], button:has-text('Sign In')"
            ).first

            await email_input.wait_for(state="visible", timeout=60000)

            logger.info("  Filling credentials...")
            await email_input.fill(email)
            await asyncio.sleep(0.3)

            await pass_input.fill(password)
            await asyncio.sleep(0.5)

            logger.info("  Clicking submit...")
            try:
                await submit_btn.click(timeout=30000)
            except Exception:
                logger.info(
                    "  Standard click blocked/failed, retrying with Force Click..."
                )
                await submit_btn.click(force=True, timeout=30000)

            logger.info("  Waiting for API response...")
            token = await asyncio.wait_for(token_future, timeout=30.0)

            logger.success("  ✓ Token received!")
            return token

        except AuthError as e:
            raise e
        except Exception as e:
            raise RuntimeError(f"Login process failed: {e}")
        finally:
            await context.close()
            await browser.close()


async def _login_with_retry(email: str, password: str, headless: bool) -> str:
    """Retries the login process on failure."""
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if attempt > 1:
                logger.info(f"--- Retry Attempt {attempt}/{MAX_RETRIES} ---")
            return await _login_attempt(email, password, headless)

        except AuthError as e:
            logger.error(f"Stopper Error: {e}")
            raise e  # Don't retry wrong passwords or 403s
        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt} failed: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BASE_DELAY * attempt)

    raise LoginRetryError(
        f"Failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )


def get_token(headless: bool = True) -> str:
    return "eyJraWQiOiIxIiwidHlwIjoiSldUIiwiYWxnIjoiUlMyNTYifQ.eyJFeHRlcm5hbEF1dGhvcml6YXRpb25zQ29udGV4dERhdGEiOiJGUkEiLCJTdWJzY3JpcHRpb25TdGF0dXMiOiJhY3RpdmUiLCJTdWJzY3JpYmVySWQiOiIyMzAwNzgwMDYiLCJGaXJzdE5hbWUiOiJCcnVubyIsImVudHMiOlt7ImNvdW50cnkiOiJGUkEiLCJlbnQiOiJSRUcifSx7ImNvdW50cnkiOiJGUkEiLCJlbnQiOiJBQ0NFU1MifV0sIkxhc3ROYW1lIjoiR29kZWZyb3kiLCJleHAiOjE3Njg3NTk0NDMsIlNlc3Npb25JZCI6ImV5SmhiR2NpT2lKb2RIUndPaTh2ZDNkM0xuY3pMbTl5Wnk4eU1EQXhMekEwTDNodGJHUnphV2N0Ylc5eVpTTm9iV0ZqTFhOb1lUSTFOaUlzSW5SNWNDSTZJa3BYVkNKOS5leUppZFNJNklqRXdNREV4SWl3aWMya2lPaUkyTUdFNVlXUTROQzFsT1ROa0xUUTRNR1l0T0RCa05pMWhaak0zTkRrMFpqSmxNaklpTENKb2RIUndPaTh2YzJOb1pXMWhjeTU0Yld4emIyRndMbTl5Wnk5M2N5OHlNREExTHpBMUwybGtaVzUwYVhSNUwyTnNZV2x0Y3k5dVlXMWxhV1JsYm5ScFptbGxjaUk2SWpJek1EQTNPREF3TmlJc0ltbGtJam9pTnpBNU9XWTFPVGN0T1dSaFppMDBaRFk1TFRsaVpEUXRZbUZoWldaa04yUXdPVFpsSWl3aWRDSTZJakVpTENKc0lqb2labkl0UmxJaUxDSmtZeUk2SWpNMk5EUWlMQ0poWldRaU9pSXlNREkyTFRBeExUSTRWREU0T2pBME9qQXpMall4T0ZvaUxDSmtkQ0k2SWpFaUxDSmxaQ0k2SWpJd01qWXRNREl0TVROVU1UZzZNRFE2TURNdU5qRTRXaUlzSW1ObFpDSTZJakl3TWpZdE1ERXRNVFZVTVRnNk1EUTZNRE11TmpFNFdpSXNJbWx3SWpvaU1qUXdNVG8wT1RBd09qRmpZems2TWpZek5qcGlabU0xT2pVM09UUTZPVFF4T2pZek9XSWlMQ0pqSWpvaVJFaEJVazFCVUZWU1NTSXNJbk4wSWpvaVZFNGlMQ0p3WXlJNklqWXpOamN3TVNJc0ltTnZJam9pU1U1RUlpd2libUptSWpveE56WTROREV6T0RRekxDSmxlSEFpT2pFM056RXdNRFU0TkRNc0ltbHpjeUk2SW1GelkyVnVaRzl1TG5SMklpd2lZWFZrSWpvaVlYTmpaVzVrYjI0dWRIWWlmUS5zZERjNEVfZnIwd3RxODhBbXZyUFN2TlNTZ050N3hPVHNzUXVqblo2YkRzIiwiaWF0IjoxNzY4NDEzODQzLCJTdWJzY3JpYmVkUHJvZHVjdCI6IkYxIFRWIEFjY2VzcyBBbm51YWwiLCJqdGkiOiJjMTg0ZmQyYS05YTVkLTRiZGUtYmZmMi03MjcwMjVkZWY5ZWEiLCJoYXNoZWRTdWJzY3JpYmVySWQiOiJVc3ZLbVFNR2lUTUg2a1V6Q08wSHFXTnQ2UHV3b2ppOEpEXC80c000ZDlrRT0ifQ.dAFf2VYs7OnruWvjdSIioAD6wDK_fj5EBORaHdUQXJtDbostZKTrL_D86QpjBAV7TpEaodDDSLV3ZNTyMlbr7ZkjWfvAh-EU6StX5fqLHmegFsyJMoB2VSDqmJ79OOI1Ksm3PbvTjn8V3WTBf94rL5sHFauTyHcBbF0O8Gh92DM8Az-EMSYciJ39de5J3RbvZxvdyA76GUcQrQ6Q-CcoGeTQz1JSBb1UVxqX2YPiauR15kWCIrlT0gjJh3Ht95I19XueqwTUnZTZQ01hgvOX90DmZLUM7JHxk-88tampL8H7B_pNb88VoRSWg2vPzZ7LQBW_z5mcZ7hCLOM9-2hbTQ"
    email = os.getenv("F1_EMAIL")
    password = os.getenv("F1_PASSWORD")

    if not email or not password:
        raise ValueError("F1_EMAIL and F1_PASSWORD environment variables required")

    return asyncio.run(_login_with_retry(email, password, headless))


if __name__ == "__main__":
    import sys

    try:
        # Run visible for debugging
        print(get_token(headless=True))
    except Exception as e:
        logger.error(e)
        sys.exit(1)
