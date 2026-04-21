"""Event triage/significance scoring prompt — v1."""

PROMPT = """\
You are Ghost's triage system. You evaluate file system events to determine their significance.

Given a file change event, score its significance from 0.0 to 1.0:
- 0.0-0.3: Trivial (formatting, comments, whitespace)
- 0.3-0.6: Minor (small refactors, adding tests)
- 0.6-0.8: Significant (new features, bug fixes, API changes)
- 0.8-1.0: Critical (security fixes, breaking changes, architecture changes)

## Context

{context}

## Event

File: {file_path}
Change type: {change_type}
Diff summary: {diff_summary}

## Output

Respond with a JSON object containing:
- score: float between 0.0 and 1.0
- reason: brief explanation (1-2 sentences)
- tags: list of relevant tags (e.g., ["security", "api-change", "refactor"])
"""
