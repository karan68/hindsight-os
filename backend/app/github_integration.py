from __future__ import annotations

import json
import subprocess
from typing import Any

from pydantic import BaseModel, Field

from app.workstream import WorkstreamEvent, WorkstreamIngestResponse, ingest_workstream_event


DEFAULT_MARKER = "<!-- hindsight-github-pr-check -->"


class GitHubPrCheckRequest(BaseModel):
    repo: str = Field(description="GitHub repository in owner/name form")
    pr_number: int = Field(ge=1)
    post_comment: bool = True
    force_check: bool = False
    marker: str = DEFAULT_MARKER
    diff_char_limit: int = Field(default=7000, ge=1000, le=20000)


class GitHubPrCheckResponse(BaseModel):
    repo: str
    pr_number: int
    pr_url: str
    changed_files: list[str]
    posted: bool = False
    comment_url: str | None = None
    comment_body: str
    ingest: WorkstreamIngestResponse


def _run_gh(args: list[str]) -> str:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "gh command failed").strip()
        raise RuntimeError(detail)
    return result.stdout


def _gh_json(args: list[str]) -> Any:
    output = _run_gh(args).strip()
    return json.loads(output) if output else None


def _repo_parts(repo: str) -> tuple[str, str]:
    parts = repo.strip().split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("repo must be in owner/name form")
    return parts[0], parts[1]


def _read_pr(repo: str, pr_number: int) -> dict[str, Any]:
    return _gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,url,title,body,author,files,headRefName,baseRefName,isDraft",
        ]
    )


def _read_pr_files(repo: str, pr_number: int) -> list[dict[str, Any]]:
    owner, name = _repo_parts(repo)
    return _gh_json(["api", f"repos/{owner}/{name}/pulls/{pr_number}/files"]) or []


def _diff_summary(files: list[dict[str, Any]], *, limit: int) -> str:
    blocks: list[str] = []
    used = 0
    for item in files:
        filename = item.get("filename") or item.get("path") or "unknown"
        status = item.get("status") or "modified"
        additions = item.get("additions", 0)
        deletions = item.get("deletions", 0)
        patch = item.get("patch") or "(patch unavailable from GitHub API)"
        block = f"File: {filename} ({status}, +{additions}/-{deletions})\n{patch}"
        remaining = limit - used
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = f"{block[: max(0, remaining - 80)]}\n... diff truncated by Hindsight ..."
            blocks.append(block)
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def _format_comment(
    request: GitHubPrCheckRequest,
    pr: dict[str, Any],
    response: WorkstreamIngestResponse,
) -> str:
    record = response.record
    warning = response.warning
    marker = request.marker.strip() or DEFAULT_MARKER

    if warning is None:
        return f"""{marker}
### Hindsight OS PR Check

No deep memory check was run for this PR.

- Screening decision: **{record.screening.decision}**
- Outcome: **{record.outcome}**
- Risk score: {record.screening.risk_score}
- Reason: {record.screening.reason}

Hindsight stayed quiet because the PR did not match a memory-changing policy signal.
"""

    primary = record.primary_evidence_labels or record.evidence_labels[:3]
    evidence_lines = "\n".join(f"- {label}" for label in primary) or "- none"
    extra = max(0, len(record.evidence_labels) - len(primary))
    extra_line = f"\nAdditional retrieved context hidden from the PR comment: {extra} memor{'y' if extra == 1 else 'ies'}." if extra else ""
    ops = " -> ".join(op.op for op in record.ops) or "none"
    threat = ""
    if warning.is_poisoning:
        threat = (
            f"\nThreat: **{warning.manipulation_tactic}** "
            f"({warning.threat_id or 'memory poisoning risk'})"
        )

    return f"""{marker}
### Hindsight OS PR Check

Hindsight checked this PR against trusted Cognee memory.

- Classification: **{record.classification or 'none'}**
- Outcome: **{record.outcome}**
- Recommended control: **{record.recommended_control or 'none'}**
- Analysis mode: **{warning.mode}**
- Risk score: {record.screening.risk_score}{threat}

Summary:
> {warning.summary}

Primary evidence:
{evidence_lines}{extra_line}

Ops: `{ops}`

PR: {pr.get('url', '')}
"""


def _post_or_update_comment(repo: str, pr_number: int, marker: str, body: str) -> str:
    owner, name = _repo_parts(repo)
    comments = _gh_json(["api", f"repos/{owner}/{name}/issues/{pr_number}/comments"]) or []
    existing = next((item for item in comments if marker in (item.get("body") or "")), None)
    if existing:
        _gh_json(
            [
                "api",
                f"repos/{owner}/{name}/issues/comments/{existing['id']}",
                "-X",
                "PATCH",
                "-f",
                f"body={body}",
            ]
        )
        return existing.get("html_url", "")

    _run_gh(["pr", "comment", str(pr_number), "--repo", repo, "--body", body])
    comments_after = _gh_json(["api", f"repos/{owner}/{name}/issues/{pr_number}/comments"]) or []
    return next((item.get("html_url", "") for item in comments_after if marker in (item.get("body") or "")), "")


async def check_github_pr(request: GitHubPrCheckRequest) -> GitHubPrCheckResponse:
    pr = _read_pr(request.repo, request.pr_number)
    files = _read_pr_files(request.repo, request.pr_number)
    changed_files = [item.get("filename") or item.get("path") or "unknown" for item in files]
    diff = _diff_summary(files, limit=request.diff_char_limit)
    author = ((pr.get("author") or {}).get("login") or "unknown") if isinstance(pr, dict) else "unknown"
    command = "/hindsight check\n" if request.force_check else ""

    event = WorkstreamEvent(
        source="github",
        event_type="pr_opened",
        actor=author,
        content=f"{command}{pr.get('title', '')}".strip(),
        metadata={
            "pr_number": pr.get("number"),
            "url": pr.get("url"),
            "title": pr.get("title") or "",
            "body": pr.get("body") or "",
            "head": pr.get("headRefName"),
            "base": pr.get("baseRefName"),
            "is_draft": pr.get("isDraft"),
            "changed_files": changed_files,
            "diff": diff,
        },
        event_id=f"github-pr-{request.pr_number}-check",
    )
    ingest = await ingest_workstream_event(event)
    comment = _format_comment(request, pr, ingest)
    comment_url = None
    if request.post_comment:
        comment_url = _post_or_update_comment(
            request.repo, request.pr_number, request.marker.strip() or DEFAULT_MARKER, comment
        )

    return GitHubPrCheckResponse(
        repo=request.repo,
        pr_number=request.pr_number,
        pr_url=pr.get("url", ""),
        changed_files=changed_files,
        posted=request.post_comment,
        comment_url=comment_url,
        comment_body=comment,
        ingest=ingest,
    )