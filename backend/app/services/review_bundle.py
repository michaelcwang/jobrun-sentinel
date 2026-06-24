"""Build redacted evidence bundles for external review.

The bundle command intentionally degrades instead of failing when the local API,
frontend, Playwright, or Docker are unavailable. That lets support teams share a
single zip with whatever evidence is available while keeping CI responsible for
hard failures.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SECRET_KEY_RE = re.compile(r"(password|secret|token|dsn|wallet|private[_-]?key|authorization)", re.IGNORECASE)
RAW_SQL_RE = re.compile(r"(\bselect\b.+\bfrom\b.+)", re.IGNORECASE | re.DOTALL)
API_PATHS = {
    "dashboard": "/api/dashboard?limit=50",
    "runs": "/api/runs?limit=50",
    "alerts": "/api/alerts?limit=50",
    "diagnostics": "/api/diagnostics",
    "topology": "/api/topology/current",
    "heatmap": "/api/topology/heatmap?bucket_minutes=10",
    "sources": "/api/sources/health",
    "query_templates": "/api/query-templates",
}
SCREENSHOT_PATHS = {
    "dashboard": "/dashboard",
    "runs": "/runs",
    "diagnostics": "/diagnostics",
    "topology": "/topology",
    "sources": "/sources",
    "query_templates": "/query-templates",
}


@dataclass
class ReviewBundleOptions:
    api_base_url: str = "http://127.0.0.1:8000"
    frontend_base_url: str = "http://127.0.0.1:5173"
    output_dir: Path = Path("backend/review_bundles")
    skip_screenshots: bool = False
    skip_commands: bool = False


def create_review_bundle(options: ReviewBundleOptions) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[3]
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    bundle_dir = (repo_root / options.output_dir / f"jobrun-sentinel-review-{timestamp}").resolve()
    bundle_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "created_at": timestamp,
        "api_base_url": options.api_base_url,
        "frontend_base_url": options.frontend_base_url,
        "redaction": "password/token/secret/dsn/wallet keys redacted; raw SQL-like strings summarized",
        "artifacts": [],
        "warnings": [],
    }

    _capture_api_snapshots(options.api_base_url, bundle_dir / "api", manifest)
    if not options.skip_commands:
        _capture_command_outputs(repo_root, bundle_dir / "commands", manifest)
    if not options.skip_screenshots:
        _capture_screenshots(repo_root, options.frontend_base_url, bundle_dir / "screenshots", manifest)

    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(redact(manifest), indent=2, default=str))
    zip_path = shutil.make_archive(str(bundle_dir), "zip", bundle_dir)
    return {
        "bundle_dir": str(bundle_dir),
        "zip_path": zip_path,
        "artifact_count": len(manifest["artifacts"]),
        "warnings": manifest["warnings"],
    }


def _capture_api_snapshots(api_base_url: str, output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, path in API_PATHS.items():
        target = f"{api_base_url.rstrip('/')}{path}"
        artifact = output_dir / f"{name}.json"
        try:
            with urllib.request.urlopen(target, timeout=20) as response:
                body = response.read().decode("utf-8")
                payload = json.loads(body)
            artifact.write_text(json.dumps(redact(payload), indent=2, default=str))
            manifest["artifacts"].append({"type": "api_snapshot", "name": name, "path": str(artifact)})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            artifact.write_text(json.dumps({"error": str(exc), "url": target}, indent=2))
            manifest["warnings"].append(f"API snapshot failed for {name}: {exc}")
            manifest["artifacts"].append({"type": "api_snapshot_error", "name": name, "path": str(artifact)})


def _capture_command_outputs(repo_root: Path, output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    # These mirror the CI gates so an external review bundle carries the same
    # build/test evidence a pull request would produce.
    commands = {
        "backend_pytest": ["bash", "-lc", "cd backend && .venv/bin/python -m pytest"],
        "frontend_build": ["bash", "-lc", "cd frontend && npm run build"],
        "frontend_test": ["bash", "-lc", "cd frontend && npm test"],
        "docker_compose_build": ["bash", "-lc", "docker compose build"],
    }
    for name, command in commands.items():
        artifact = output_dir / f"{name}.txt"
        try:
            result = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, timeout=600)
            artifact.write_text(redact_text(f"$ {' '.join(command)}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT_CODE={result.returncode}\n"))
            if result.returncode != 0:
                manifest["warnings"].append(f"Command {name} exited {result.returncode}")
        except Exception as exc:
            artifact.write_text(redact_text(f"Command {name} failed before completion: {exc}"))
            manifest["warnings"].append(f"Command {name} failed: {exc}")
        manifest["artifacts"].append({"type": "command_output", "name": name, "path": str(artifact)})


def _capture_screenshots(repo_root: Path, frontend_base_url: str, output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    npx = shutil.which("npx")
    if not npx:
        manifest["warnings"].append("Playwright screenshots skipped: npx not found.")
        return
    for name, path in SCREENSHOT_PATHS.items():
        artifact = output_dir / f"{name}.png"
        url = f"{frontend_base_url.rstrip('/')}{path}"
        command = [npx, "playwright", "screenshot", "--viewport-size=1440,1100", url, str(artifact)]
        try:
            result = subprocess.run(command, cwd=repo_root / "frontend", text=True, capture_output=True, timeout=90)
            if result.returncode != 0:
                manifest["warnings"].append(f"Screenshot {name} failed: {redact_text(result.stderr)[:300]}")
                continue
            manifest["artifacts"].append({"type": "screenshot", "name": name, "path": str(artifact)})
        except Exception as exc:
            manifest["warnings"].append(f"Screenshot {name} failed: {exc}")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[key] = "[redacted]"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)(password|token|secret|dsn|wallet)(['\"]?\s*[:=]\s*)['\"]?[^,'\"\s}]+", r"\1\2[redacted]", value)
    if len(value) > 120 and RAW_SQL_RE.search(value):
        return "[raw SQL-like text redacted; see template hash/provenance in API]"
    return value


def options_from_args(args: argparse.Namespace) -> ReviewBundleOptions:
    return ReviewBundleOptions(
        api_base_url=args.api_base_url,
        frontend_base_url=args.frontend_base_url,
        output_dir=Path(args.output_dir),
        skip_screenshots=args.skip_screenshots,
        skip_commands=args.skip_commands,
    )
