# ABOUTME: Tests for table queue, status polling, and CSV download.
# ABOUTME: Unit tests for naming/timing; integration tests for real download flow.

from datetime import datetime

import pytest

from tablebuilder.downloader import generate_table_name, DownloadError


class TestGenerateTableName:
    def test_generates_timestamped_name(self):
        """Table names contain a timestamp."""
        name = generate_table_name()
        # Should start with "tb_" prefix
        assert name.startswith("tb_")
        # Should contain today's date
        today = datetime.now().strftime("%Y%m%d")
        assert today in name

    def test_names_are_unique(self):
        """Two calls produce different names."""
        name1 = generate_table_name()
        name2 = generate_table_name()
        assert name1 != name2


class TestDownloadError:
    def test_error_is_exception(self):
        """DownloadError is a proper exception."""
        err = DownloadError("timeout")
        assert str(err) == "timeout"


@pytest.mark.integration
class TestDownloaderIntegration:
    def test_queue_and_download(self, abs_page_with_table, tmp_path):
        """Can queue a table, wait for completion, and download CSV."""
        from tablebuilder.downloader import queue_and_download

        output = tmp_path / "test_output.csv"
        queue_and_download(abs_page_with_table, str(output), timeout=300)
        assert output.exists()
        content = output.read_text()
        assert len(content) > 0
