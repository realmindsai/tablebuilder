# ABOUTME: MCP tool definitions for TableBuilder service.
# ABOUTME: Wraps REST API endpoints for use from Claude Code / Claude Desktop.

# MCP tools call the same REST API as any other client.
# They use a configured API key from environment variables.
#
# Tools:
#   - search_dictionary(query) -> search results
#   - submit_job(dataset, rows, cols, wafers) -> job_id
#   - job_status(job_id) -> status + progress
#   - download_result(job_id) -> CSV content
#   - list_jobs() -> user's recent jobs
#
# Implementation deferred until REST API is deployed and tested.
# See spec: docs/superpowers/specs/2026-03-18-tablebuilder-service-design.md
