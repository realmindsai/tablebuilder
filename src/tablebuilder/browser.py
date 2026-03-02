# ABOUTME: Playwright browser session management for ABS TableBuilder.
# ABOUTME: Handles browser launch, login, conditions-of-use, and cleanup.

import time

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

from tablebuilder.config import Config
from tablebuilder.logging_config import get_logger
from tablebuilder.resilience import find_element, retry
from tablebuilder.selectors import LOGIN_USERNAME, LOGIN_PASSWORD, LOGIN_BUTTON, TERMS_BUTTON

logger = get_logger("tablebuilder.browser")

TABLEBUILDER_LOGIN_URL = "https://tablebuilder.abs.gov.au/webapi/jsf/login.xhtml"


class LoginError(Exception):
    """Raised when login to TableBuilder fails."""


class MaintenanceError(Exception):
    """Raised when TableBuilder is in maintenance mode."""


class TableBuilderSession:
    """Context manager for a Playwright session logged into TableBuilder."""

    def __init__(self, config: Config, headless: bool = True, knowledge=None):
        self.config = config
        self.headless = headless
        self.knowledge = knowledge
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

    @retry(max_attempts=2, retryable_exceptions=(PlaywrightTimeout,))
    def _login(self):
        """Navigate to login page, fill credentials, verify success."""
        login_start = time.time()
        logger.info("Login started for user %s", self.config.user_id)
        page = self._page
        page.goto(TABLEBUILDER_LOGIN_URL, wait_until="networkidle")

        # Check for maintenance
        maintenance = page.query_selector("text=maintenance")
        if maintenance and "scheduled" in (maintenance.text_content() or "").lower():
            logger.info("Maintenance banner detected, proceeding anyway")

        # Fill login form using resilient element finding
        username_el = find_element(page, LOGIN_USERNAME, self.knowledge)
        if not username_el:
            raise LoginError("Cannot find username field.")
        username_el.fill(self.config.user_id)

        password_el = find_element(page, LOGIN_PASSWORD, self.knowledge)
        if not password_el:
            raise LoginError("Cannot find password field.")
        password_el.fill(self.config.password)

        login_btn = find_element(page, LOGIN_BUTTON, self.knowledge)
        if not login_btn:
            raise LoginError("Cannot find login button.")
        login_btn.click()

        # Wait for navigation
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PlaywrightTimeout:
            raise LoginError("Login timed out — TableBuilder may be down.")

        # If we're still on the login page, credentials were wrong
        if "login.xhtml" in page.url:
            raise LoginError(
                "Login failed — still on login page. Check your User ID and password."
            )

        # Handle conditions-of-use / terms page
        if "terms.xhtml" in page.url:
            try:
                terms_btn = find_element(page, TERMS_BUTTON, self.knowledge)
                if not terms_btn:
                    raise LoginError("Cannot find terms acceptance button.")
                terms_btn.click()
                page.wait_for_load_state("networkidle", timeout=10000)
                logger.info("Terms and conditions accepted")
            except PlaywrightTimeout:
                raise LoginError("Timed out accepting conditions of use.")

        # Verify we reached the data catalogue
        if "dataCatalogueExplorer.xhtml" not in page.url:
            raise LoginError(
                f"Login did not reach data catalogue. Current URL: {page.url}"
            )

        login_duration = time.time() - login_start
        logger.info("Login succeeded in %.1f seconds", login_duration)
        if self.knowledge is not None:
            self.knowledge.record_timing("login", login_duration)
