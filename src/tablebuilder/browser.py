# ABOUTME: Playwright browser session management for ABS TableBuilder.
# ABOUTME: Handles browser launch, login, conditions-of-use, and cleanup.

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

from tablebuilder.config import Config

TABLEBUILDER_LOGIN_URL = "https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml"


class LoginError(Exception):
    """Raised when login to TableBuilder fails."""


class MaintenanceError(Exception):
    """Raised when TableBuilder is in maintenance mode."""


class TableBuilderSession:
    """Context manager for a Playwright session logged into TableBuilder."""

    def __init__(self, config: Config, headless: bool = True):
        self.config = config
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._page = None

    def __enter__(self) -> Page:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._page = self._browser.new_page()
        self._login()
        return self._page

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        return False

    def _login(self):
        """Navigate to login page, fill credentials, verify success."""
        page = self._page
        page.goto(TABLEBUILDER_LOGIN_URL, wait_until="networkidle")

        # Check for maintenance
        maintenance = page.query_selector("text=maintenance")
        if maintenance and "scheduled" in (maintenance.text_content() or "").lower():
            # Maintenance banner exists but site may still be accessible
            pass

        # Fill login form
        page.fill('input[type="text"]', self.config.user_id)
        page.fill('input[type="password"]', self.config.password)
        page.click('input[type="submit"], button[type="submit"]')

        # Wait for navigation
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            raise LoginError("Login timed out — TableBuilder may be down.")

        # Check for login error
        error_element = page.query_selector(".error-message, .ui-messages-error")
        if error_element:
            error_text = error_element.text_content() or "Unknown login error"
            raise LoginError(f"Login failed: {error_text.strip()}")

        # If we're still on the login page, credentials were wrong
        if "login.xhtml" in page.url:
            raise LoginError(
                "Login failed — still on login page. Check your User ID and password."
            )

        # Handle conditions-of-use dialog if it appears
        try:
            agree_button = page.wait_for_selector(
                "text=I agree, button:has-text('Agree'), input[value='Agree']",
                timeout=3000,
            )
            if agree_button:
                agree_button.click()
                page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeout:
            pass  # No conditions dialog — that's fine
