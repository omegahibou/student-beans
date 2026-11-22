import asyncio
import os
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from .base import BaseProvider


class StudentBeansProvider(BaseProvider):
    def __init__(self, headless: bool = True):
        super().__init__("studentbeans", "https://www.studentbeans.com/en-us/us/accounts/authorisation/log-in")
        self.headless = headless

    def _proxy_config(self):
        """Build Playwright proxy config from Railway env vars."""
        host = os.getenv("PROXY_HOST")
        port = os.getenv("PROXY_PORT")
        user = os.getenv("PROXY_USER")
        pwd = os.getenv("PROXY_PASS")
        if not host or not port:
            return None
        proxy = {"server": f"http://{host}:{port}"}
        if user and pwd:
            proxy["username"] = user
            proxy["password"] = pwd
        return proxy

    async def fetch_codes(self, email: str, password: str) -> str:
        # NOTE: Student Beans frequently changes its DOM and runs bot detection
        # (CAPTCHA, rate limiting, device fingerprinting). Code-extraction
        # selectors below are placeholders and must be reverse-engineered
        # against the live site before codes will actually be returned.
        async with async_playwright() as p:
            proxy = self._proxy_config()
            launch_kwargs = {"headless": self.headless}
            if proxy:
                launch_kwargs["proxy"] = proxy

            browser = await p.chromium.launch(**launch_kwargs)
            # Use Playwright's real user agent: a spoofed one that doesn't match
            # the actual browser version is an easy bot-detection signal.
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="en-US",
            )
            page = await context.new_page()
            try:
                # Retry a few times if the server returns a 5xx error page
                status = None
                for attempt in range(3):
                    response = await page.goto(
                        self.login_url, wait_until="domcontentloaded", timeout=30000
                    )
                    status = response.status if response else None
                    if status is None or status < 500:
                        break
                    await asyncio.sleep(5 * (attempt + 1))

                if status is not None and status >= 400:
                    return (
                        f"❌ Student Beans returned HTTP {status} on the login page. "
                        "Their site is either down or blocking automated logins from "
                        "this server. If the link works in a normal browser, try "
                        "running the bot from your own computer or set PROXY_HOST/PROXY_PORT."
                    )

                # Confirmed selectors for accounts.studentbeans.com
                await page.wait_for_selector('#email', timeout=10000)
                await page.fill('#email', email, timeout=10000)
                await page.fill('#password', password, timeout=10000)
                await page.click('form button[type="submit"]', timeout=10000)
                await page.wait_for_timeout(4000)

                # TODO: replace these with real Student Beans code selectors
                # from your dashboard/offers page (e.g. .discount-code, [data-code])
                codes = await page.evaluate(
                    """() => {
                    const els = document.querySelectorAll('.discount-code, [data-code]');
                    return Array.from(els).map(e => e.innerText || e.getAttribute('data-code')).filter(Boolean);
                    }"""
                )

                if not codes:
                    return "No codes found. Code selectors need to be updated for the current Student Beans site."
                return "\n".join(f"- {c}" for c in codes)
            except PlaywrightTimeout:
                return "❌ Timeout — Student Beans page took too long to load (possibly rate-limited or blocked)."
            except Exception as e:
                return f"Error fetching Student Beans codes: {e}"
            finally:
                await browser.close()
