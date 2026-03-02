# ABOUTME: Tests for the resilience layer (retry decorator and find_element).
# ABOUTME: Uses simple callables and counters to test retry behavior.

import pytest

from tablebuilder.resilience import retry


class TestRetryRetriesCorrectNumberOfTimes:
    """Verify the retry decorator calls a flaky function the right number of times."""

    def test_retry_retries_correct_number_of_times(self):
        """A function that fails N-1 times then succeeds should be called N times."""
        call_count = 0

        @retry(max_attempts=3, backoff_base=0.01)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "success"

        result = flaky()
        assert result == "success"
        assert call_count == 3


class TestRetryRaisesAfterExhaustion:
    """Verify the retry decorator raises after all attempts are exhausted."""

    def test_retry_raises_after_exhaustion(self):
        """A function that always fails should raise after max_attempts."""
        call_count = 0

        @retry(max_attempts=3, backoff_base=0.01)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent failure")

        with pytest.raises(ValueError, match="permanent failure"):
            always_fails()
        assert call_count == 3


class TestRetryNoRetryOnSuccess:
    """Verify the retry decorator does not retry when the function succeeds."""

    def test_retry_no_retry_on_success(self):
        """A function that succeeds on first try should be called only once."""
        call_count = 0

        @retry(max_attempts=3, backoff_base=0.01)
        def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeeds()
        assert result == "ok"
        assert call_count == 1


class TestRetryRespectsMaxAttemptsOne:
    """Verify the retry decorator with max_attempts=1 does not retry."""

    def test_retry_respects_max_attempts_one(self):
        """With max_attempts=1, a failing function should be called once and raise immediately."""
        call_count = 0

        @retry(max_attempts=1, backoff_base=0.01)
        def fails_once():
            nonlocal call_count
            call_count += 1
            raise ValueError("instant failure")

        with pytest.raises(ValueError, match="instant failure"):
            fails_once()
        assert call_count == 1


class TestRetryOnlyCatchesSpecifiedExceptions:
    """Verify the retry decorator only catches the specified exception types."""

    def test_retry_only_catches_specified_exceptions(self):
        """With retryable_exceptions=(ValueError,), a TypeError should not be retried."""
        call_count = 0

        @retry(max_attempts=3, backoff_base=0.01, retryable_exceptions=(ValueError,))
        def raises_type_error():
            nonlocal call_count
            call_count += 1
            raise TypeError("wrong type")

        with pytest.raises(TypeError, match="wrong type"):
            raises_type_error()
        assert call_count == 1
