"""Build redacted evidence bundles for external review.

The command is designed for two situations: a live local demo, where it captures
real API snapshots and optional screenshots, and CI, where it still emits a
complete zip with command output and explicit warnings when no server/browser is
available.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SECRET_KEY_RE = re.compile(r"(password|secret|token|dsn|wallet|private[_-]?key|authorization)", re.IGNORECASE)
RAW_SQL_RE = re.compile(r"(\bselect\b.+\bfrom\b.+)", re.IGNORECASE | re.DOTALL)
INTERNAL_REGISTRY_RE = re.compile(r"https://artifacthub-[^\\s'\"}]+", re.IGNORECASE)

API_SNAPSHOT_PATHS = {
    "dashboard": "/api/dashboard?limit=50",
    "runs": "/api/runs?limit=50",
    "expectations": "/api/expectations",
    "alerts": "/api/alerts?limit=50",
    "diagnostics": "/api/diagnostics",
    "sources": "/api/sources/health",
    "query_templates": "/api/query-templates",
    "imports": "/api/imports/plans",
    "playbook": "/api/playbook",
    "topology": "/api/topology/current",
    "heatmap": "/api/topology/heatmap?bucket_minutes=10",
}
PAGE_PATHS = {
    "dashboard": "/dashboard",
    "runs": "/runs",
    "expectations": "/expectations",
    "alerts": "/alerts",
    "diagnostics": "/diagnostics",
    "sources": "/sources",
    "query_templates": "/query-templates",
    "imports": "/imports",
    "playbook": "/playbook",
    "topology": "/topology",
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
        "redaction": "password/token/secret/dsn/wallet keys redacted; raw SQL-like text summarized",
        "artifacts": [],
        "warnings": [],
    }

    _write_json(bundle_dir / "app_metadata.json", _app_metadata(repo_root, options), manifest, "metadata")
    _write_page_inventory(bundle_dir / "page_inventory.json", options, manifest)
    discovery = _capture_api_snapshots(options.api_base_url, bundle_dir / "api_snapshots", manifest)
    _write_json(bundle_dir / "diagnostics_review.json", _diagnostics_review(discovery), manifest, "diagnostics_review")
    _write_design_notes(bundle_dir / "design_review_notes.md", discovery, manifest)
    _write_bundle_readme(bundle_dir / "README.md", manifest)
    if not options.skip_commands:
        _capture_command_outputs(repo_root, bundle_dir / "test_results", manifest)
    else:
        skipped = bundle_dir / "test_results" / "_skipped.txt"
        skipped.parent.mkdir(parents=True, exist_ok=True)
        skipped.write_text("Command capture skipped by review-bundle option.\n")
        manifest["artifacts"].append({"type": "test_result", "name": "skipped", "path": str(skipped)})
    if not options.skip_screenshots:
        _capture_screenshots(repo_root, options.frontend_base_url, discovery, bundle_dir / "screenshots", manifest)
    else:
        skipped = bundle_dir / "screenshots" / "_skipped.txt"
        skipped.parent.mkdir(parents=True, exist_ok=True)
        skipped.write_text("Screenshot capture skipped by review-bundle option.\n")
        manifest["artifacts"].append({"type": "screenshot", "name": "skipped", "path": str(skipped)})

    _write_json(bundle_dir / "manifest.json", manifest, manifest, "manifest")
    zip_path = shutil.make_archive(str(bundle_dir), "zip", bundle_dir)
    return {
        "bundle_dir": str(bundle_dir),
        "zip_path": zip_path,
        "artifact_count": len(manifest["artifacts"]),
        "warnings": manifest["warnings"],
    }


def _capture_api_snapshots(api_base_url: str, output_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    discovery: dict[str, Any] = {"snapshots": {}, "apj_run_id": None, "diagnostic_id": None}
    for name, path in API_SNAPSHOT_PATHS.items():
        payload = _fetch_json(api_base_url, path)
        discovery["snapshots"][name] = payload
        _write_json(output_dir / f"{name}.json", payload, manifest, "api_snapshot", name=name)

    runs_payload = discovery["snapshots"].get("runs")
    if isinstance(runs_payload, list):
        apj = next(
            (
                item
                for item in runs_payload
                if "APJ" in str(item.get("region", "")).upper()
                and "CALC" in str(item.get("job_name", "")).upper()
            ),
            runs_payload[0] if runs_payload else None,
        )
        if apj and apj.get("id"):
            discovery["apj_run_id"] = apj["id"]
            _write_json(output_dir / "apj_critical_run_detail.json", _fetch_json(api_base_url, f"/api/runs/{apj['id']}"), manifest, "api_snapshot")

    diagnostics_payload = discovery["snapshots"].get("diagnostics")
    if isinstance(diagnostics_payload, list):
        diagnostic = next(
            (
                item
                for item in diagnostics_payload
                if item.get("ess_request_id") == "13729027" or "Calculate_pvt" in str(item.get("report_title", ""))
            ),
            diagnostics_payload[0] if diagnostics_payload else None,
        )
        if diagnostic and diagnostic.get("id"):
            discovery["diagnostic_id"] = diagnostic["id"]
            _write_json(
                output_dir / "calculate_pvt_diagnostic_detail.json",
                _fetch_json(api_base_url, f"/api/diagnostics/{diagnostic['id']}"),
                manifest,
                "api_snapshot",
            )
    return discovery


def _capture_command_outputs(repo_root: Path, output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    commands = {
        "backend_pytest": [sys.executable, "-m", "pytest"],
        "frontend_build": ["npm", "run", "build"],
        "frontend_test": ["npm", "test"],
        "docker_compose_build": ["docker", "compose", "build"],
    }
    working_dirs = {
        "backend_pytest": repo_root / "backend",
        "frontend_build": repo_root / "frontend",
        "frontend_test": repo_root / "frontend",
        "docker_compose_build": repo_root,
    }
    for name, command in commands.items():
        artifact = output_dir / f"{name}.txt"
        try:
            result = subprocess.run(command, cwd=working_dirs[name], text=True, capture_output=True, timeout=600)
            artifact.write_text(
                redact_text(
                    f"$ {' '.join(command)}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nEXIT_CODE={result.returncode}\n"
                )
            )
            if result.returncode != 0:
                manifest["warnings"].append(f"Command {name} exited {result.returncode}")
        except Exception as exc:
            artifact.write_text(redact_text(f"Command {name} failed before completion: {exc}"))
            manifest["warnings"].append(f"Command {name} failed: {exc}")
        manifest["artifacts"].append({"type": "test_result", "name": name, "path": str(artifact)})


def _capture_screenshots(
    repo_root: Path,
    frontend_base_url: str,
    discovery: dict[str, Any],
    output_dir: Path,
    manifest: dict[str, Any],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    npx = shutil.which("npx")
    if not npx:
        manifest["warnings"].append("Playwright screenshots skipped: npx not found.")
        return
    pages = dict(PAGE_PATHS)
    if discovery.get("apj_run_id"):
        pages["apj_critical_run_detail"] = f"/runs/{discovery['apj_run_id']}"
    if discovery.get("diagnostic_id"):
        pages["calculate_pvt_diagnostic_detail"] = f"/diagnostics/{discovery['diagnostic_id']}"
    for name, path in pages.items():
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


def _fetch_json(api_base_url: str, path: str) -> Any:
    target = f"{api_base_url.rstrip('/')}{path}"
    try:
        with urllib.request.urlopen(target, timeout=20) as response:
            body = response.read().decode("utf-8")
        return redact(json.loads(body))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": redact_text(str(exc)), "url": target}


def _write_page_inventory(path: Path, options: ReviewBundleOptions, manifest: dict[str, Any]) -> None:
    pages = [{"name": name, "frontend_path": page, "url": f"{options.frontend_base_url.rstrip('/')}{page}"} for name, page in PAGE_PATHS.items()]
    pages.extend(
        [
            {"name": "apj_critical_run_detail", "frontend_path": "/runs/:id", "discoverable": True},
            {"name": "calculate_pvt_diagnostic_detail", "frontend_path": "/diagnostics/:id", "discoverable": True},
        ]
    )
    _write_json(path, {"pages": pages, "api_snapshots": API_SNAPSHOT_PATHS}, manifest, "page_inventory")


def _diagnostics_review(discovery: dict[str, Any]) -> dict[str, Any]:
    diagnostics = discovery.get("snapshots", {}).get("diagnostics")
    return {
        "diagnostic_count": len(diagnostics) if isinstance(diagnostics, list) else 0,
        "seeded_calculate_pvt_diagnostic_id": discovery.get("diagnostic_id"),
        "apj_run_id": discovery.get("apj_run_id"),
        "notes": [
            "Review the APJ run detail and Calculate_pvt diagnostic detail when IDs are discoverable.",
            "All customer SQL text and secrets should appear only as hashes, metadata, or redacted text.",
        ],
    }


def _write_design_notes(path: Path, discovery: dict[str, Any], manifest: dict[str, Any]) -> None:
    path.write_text(
        "\n".join(
            [
                "# Design Review Notes",
                "",
                "- Dashboard should lead with runtime status, server-time heat, and topology drill-downs.",
                "- Critical jobs should explain elapsed vs expected runtime before deeper SQL/UDQ evidence.",
                "- Topology evidence should distinguish confirmed DB instance bindings from inferred app server bindings.",
                "- Review redaction: no passwords, tokens, wallet paths, DSNs, or raw UDQ SQL should be present.",
                f"- APJ run detail discovered: {bool(discovery.get('apj_run_id'))}.",
                f"- Calculate_pvt diagnostic discovered: {bool(discovery.get('diagnostic_id'))}.",
                "",
            ]
        )
    )
    manifest["artifacts"].append({"type": "design_review_notes", "path": str(path)})


def _write_bundle_readme(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(
        "\n".join(
            [
                "# JobRun Sentinel Review Bundle",
                "",
                "This zip contains a redacted external-review package for the current app state.",
                "",
                "Expected directories and files:",
                "",
                "- `app_metadata.json`: repository, runtime, and command metadata.",
                "- `test_results/`: backend, frontend, and Docker build command output when captured.",
                "- `api_snapshots/`: redacted API payloads or explicit capture errors.",
                "- `screenshots/`: Playwright screenshots when a frontend server is available.",
                "- `page_inventory.json`: frontend/API coverage map.",
                "- `diagnostics_review.json`: diagnostic review pointers for APJ/Calculate_pvt.",
                "- `design_review_notes.md`: human review checklist.",
                "",
                "The bundle command redacts secret-like keys and long raw SQL-like text.",
                "",
            ]
        )
    )
    manifest["artifacts"].append({"type": "readme", "path": str(path)})


def _app_metadata(repo_root: Path, options: ReviewBundleOptions) -> dict[str, Any]:
    return {
        "app": "JobRun Sentinel",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "git_head": _command_text(["git", "rev-parse", "HEAD"], repo_root),
        "git_branch": _command_text(["git", "branch", "--show-current"], repo_root),
        "api_base_url": options.api_base_url,
        "frontend_base_url": options.frontend_base_url,
        "screenshots_requested": not options.skip_screenshots,
        "commands_requested": not options.skip_commands,
    }


def _command_text(command: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=15)
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _write_json(path: Path, payload: Any, manifest: dict[str, Any], artifact_type: str, *, name: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(payload), indent=2, default=str))
    manifest["artifacts"].append({"type": artifact_type, "name": name or path.stem, "path": str(path)})


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if SECRET_KEY_RE.search(str(key)) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str) -> str:
    value = INTERNAL_REGISTRY_RE.sub("[internal registry redacted]", value)
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
