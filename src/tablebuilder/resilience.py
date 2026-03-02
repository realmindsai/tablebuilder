# ABOUTME: Self-healing element finding and retry logic for Playwright operations.
# ABOUTME: Tries fallback selectors when primary selectors fail, and retries transient errors.

from __future__ import annotations

import functools
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import ElementHandle, Page

    from tablebuilder.selectors import SelectorEntry

logger = logging.getLogger(__name__)


def find_element(
    page: "Page",
    selector_entry: "SelectorEntry",
    knowledge: "KnowledgeBase | None" = None,
    timeout: int = 5000,
) -> "ElementHandle | None":
    """Locate a single element using the selector entry's primary and fallback selectors.

    If a knowledge base is provided and has a preferred selector for this entry,
    that selector is tried first. Falls back through the selector entry's primary
    and fallback selectors in order.

    Returns the ElementHandle if found, or None if all selectors fail.
    """
    name = selector_entry.name
    candidates = _build_candidate_list(selector_entry, knowledge)

    for selector in candidates:
        try:
            element = page.query_selector(selector)
        except Exception:
            logger.debug(
                "Selector '%s' for %s raised an exception, skipping",
                selector,
                name,
            )
            if knowledge is not None:
                knowledge.record_selector_failure(name, selector)
            continue

        if element is not None:
            logger.info("Found element %s using selector: %s", name, selector)
            if knowledge is not None:
                knowledge.record_selector_success(name, selector)
            return element

        logger.debug("Selector '%s' did not match any element for %s", selector, name)
        if knowledge is not None:
            knowledge.record_selector_failure(name, selector)

    logger.warning("All selectors failed for %s", name)
    return None


def find_all_elements(
    page: "Page",
    selector_entry: "SelectorEntry",
    knowledge: "KnowledgeBase | None" = None,
) -> "list[ElementHandle]":
    """Locate all elements matching the selector entry's selectors.

    Same fallback logic as find_element but uses query_selector_all and returns
    the first non-empty result list. Returns an empty list if nothing found.
    """
    name = selector_entry.name
    candidates = _build_candidate_list(selector_entry, knowledge)

    for selector in candidates:
        try:
            elements = page.query_selector_all(selector)
        except Exception:
            logger.debug(
                "Selector '%s' for %s raised an exception, skipping",
                selector,
                name,
            )
            if knowledge is not None:
                knowledge.record_selector_failure(name, selector)
            continue

        if elements:
            logger.info(
                "Found %d element(s) for %s using selector: %s",
                len(elements),
                name,
                selector,
            )
            if knowledge is not None:
                knowledge.record_selector_success(name, selector)
            return elements

        logger.debug("Selector '%s' returned no elements for %s", selector, name)
        if knowledge is not None:
            knowledge.record_selector_failure(name, selector)

    logger.warning("All selectors returned no elements for %s", name)
    return []


def _build_candidate_list(
    selector_entry: "SelectorEntry",
    knowledge: "KnowledgeBase | None",
) -> list[str]:
    """Build an ordered list of selectors to try.

    If knowledge has a preferred selector, it goes first. Then primary,
    then fallbacks -- with duplicates removed while preserving order.
    """
    candidates: list[str] = []
    seen: set[str] = set()

    # Preferred selector from the knowledge base goes first
    if knowledge is not None:
        preferred = knowledge.get_preferred_selector(selector_entry.name)
        if preferred is not None and preferred not in seen:
            candidates.append(preferred)
            seen.add(preferred)

    # Primary selector
    if selector_entry.primary not in seen:
        candidates.append(selector_entry.primary)
        seen.add(selector_entry.primary)

    # Fallback selectors
    for fallback in selector_entry.fallbacks:
        if fallback not in seen:
            candidates.append(fallback)
            seen.add(fallback)

    return candidates


def retry(
    max_attempts: int = 3,
    backoff_base: float = 2.0,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
):
    """Decorator that retries a function with exponential backoff."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_attempts:
                        sleep_time = backoff_base ** (attempt - 1)
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                            attempt,
                            max_attempts,
                            func.__name__,
                            e,
                            sleep_time,
                        )
                        time.sleep(sleep_time)
                    else:
                        logger.error(
                            "All %d attempts failed for %s: %s",
                            max_attempts,
                            func.__name__,
                            e,
                        )
            raise last_exception

        return wrapper

    return decorator
