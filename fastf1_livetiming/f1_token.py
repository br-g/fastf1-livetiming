"""Simple F1 TV login to retrieve subscription token.

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

from loguru import logger
from playwright.async_api import Page, async_playwright

LOGIN_URL = "https://account.formula1.com/#/en/login?redirect=https%3A%2F%2Fwww.formula1.com%2Fen&lead_source=web_f1core"
API_URL = "https://api.formula1.com/v2/account/subscriber/authenticate/by-password"

COOKIE_IFRAME = "iframe[src*='consent.formula1.com']"
COOKIE_BUTTON = '//*[@id="notice"]/div[3]/button[1]'

EMAIL_INPUT = "#loginform > div:nth-child(2) > input"
PASSWORD_INPUT = "#loginform > div.field.password > input"
SUBMIT_BTN = "#loginform > div.actions > button"


async def _handle_consent(page: Page) -> None:
    """Handle GDPR consent banner if present."""
    try:
        logger.info("  Checking for GDPR consent banner...")
        iframe_selector = await page.query_selector(COOKIE_IFRAME)
        if not iframe_selector:
            try:
                await page.wait_for_selector(
                    COOKIE_IFRAME, timeout=30000, state="visible"
                )
            except Exception:
                logger.error("  No consent banner found")
                return

        logger.info("  Consent banner found, clicking accept...")
        iframe_locator = page.frame_locator(COOKIE_IFRAME)
        button = iframe_locator.locator(COOKIE_BUTTON)
        await button.click(timeout=30000)

        # Wait for iframe to disappear or timeout (shorter timeout)
        try:
            await page.wait_for_selector(COOKIE_IFRAME, state="hidden", timeout=30000)
            logger.info("  Consent accepted")
        except Exception:
            logger.error("  Consent clicked (banner still visible)")
            pass  # Continue even if it doesn't disappear

        await asyncio.sleep(2)

    except Exception:
        # Consent handling is optional, continue if it fails
        logger.error("  Consent handling failed, continuing...")
        pass


async def _login(email: str, password: str, headless: bool = True) -> str:
    """Internal async function to perform F1 TV login."""
    logger.info("Starting F1 TV login...")
    logger.info(f"Mode: {'headless' if headless else 'visible browser'}")

    async with async_playwright() as p:
        logger.info("Launching browser...")
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
            """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.chrome = { runtime: {} };
        """
        )

        try:
            logger.info("Navigating to F1 login page...")
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)

            await _handle_consent(page)

            logger.info("Waiting for login form...")
            await page.wait_for_selector(EMAIL_INPUT, state="visible", timeout=30000)
            await page.wait_for_selector(PASSWORD_INPUT, state="visible", timeout=30000)
            await page.wait_for_selector(SUBMIT_BTN, state="visible", timeout=30000)

            logger.info("Filling credentials...")
            await page.fill(EMAIL_INPUT, email)
            await asyncio.sleep(0.3)
            await page.fill(PASSWORD_INPUT, password)
            await asyncio.sleep(0.5)

            token_future = asyncio.Future()
            api_called = asyncio.Event()

            async def handle_route(route):
                try:
                    api_called.set()
                    response = await route.fetch()
                    status = response.status

                    if status == 200:
                        body = await response.body()
                        data = json.loads(body.decode("utf-8"))
                        # Try both camelCase and snake_case
                        token = data.get("data", {}).get(
                            "subscriptionToken"
                        ) or data.get("data", {}).get("subscription_token")
                        if token and not token_future.done():
                            token_future.set_result(token)
                        elif not token_future.done():
                            token_future.set_exception(
                                RuntimeError(
                                    f"200 OK but no token in response. Data: {data}"
                                )
                            )
                    elif status == 401:
                        if not token_future.done():
                            token_future.set_exception(
                                ValueError("Invalid email or password (401)")
                            )
                    elif status == 403:
                        if not token_future.done():
                            token_future.set_exception(
                                ValueError("Account forbidden or bot detected (403)")
                            )
                    else:
                        try:
                            body = await response.body()
                            body_text = body.decode("utf-8")
                        except Exception:
                            body_text = "Could not read response body"

                        if not token_future.done():
                            token_future.set_exception(
                                RuntimeError(
                                    f"Login failed with status {status}. Body: {body_text[:200]}"
                                )
                            )

                    await route.fulfill(response=response)

                except Exception as e:
                    if not token_future.done():
                        token_future.set_exception(
                            RuntimeError(f"Route handler error: {e}")
                        )
                    try:
                        await route.continue_()
                    except Exception:
                        pass

            # Intercept login API call
            await page.route(f"**{API_URL}**", handle_route)

            logger.info("Submitting login form...")
            try:
                await page.click(SUBMIT_BTN, timeout=30000)
            except Exception:
                logger.info("  Retrying click with force...")
                await page.click(SUBMIT_BTN, force=True, timeout=30000)

            logger.info("Waiting for login API response...")
            try:
                await asyncio.wait_for(api_called.wait(), timeout=30.0)
                logger.info("  Login API called")
            except asyncio.TimeoutError:
                raise RuntimeError(
                    "Login form submitted but no API call detected - "
                    "possible bot detection or form submission failure"
                )

            try:
                token = await asyncio.wait_for(token_future, timeout=30.0)
                logger.info("✓ Token received successfully!")
                return token
            except asyncio.TimeoutError:
                raise RuntimeError(
                    "API called but no token received - check credentials"
                )

        except asyncio.TimeoutError as e:
            raise RuntimeError(f"Login timed out: {e}")
        finally:
            logger.info("Closing browser...")
            await context.close()
            await browser.close()


def get_token(headless: bool = True) -> str:
    """
    Log in to F1 TV and retrieve subscription token.

    Credentials are read from environment variables:
    - F1_EMAIL: F1 TV account email
    - F1_PASSWORD: F1 TV account password

    Args:
        headless: Run browser in headless mode (default: True)

    Returns:
        JWT subscription token string
    """
    email = os.getenv("F1_EMAIL")
    password = os.getenv("F1_PASSWORD")

    if not email:
        raise ValueError("F1_EMAIL environment variable not set")
    if not password:
        raise ValueError("F1_PASSWORD environment variable not set")

    return asyncio.run(_login(email, password, headless))


if __name__ == "__main__":
    # CLI usage, for debugging
    import sys

    try:
        token = get_token(headless=False)
        print("\nToken:")
        print(token)
        sys.exit(0)
    except Exception as e:
        logger.info(f"\n✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
