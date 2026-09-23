#!/usr/bin/env python3
"""Local, fail-closed queue bookkeeping. Never submits to Higgsfield itself."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import xml.etree.ElementTree as ET


COLUMNS = ["enabled", "job_id", "image", "prompt"]
STATES = {"claimed", "authorized", "submitted", "completed", "blocked", "unknown", "failed"}
# A blocked job can still be awaiting the user's submission confirmation.
# Keep its shared browser draft reserved until the job is reconciled or failed.
ACTIVE_STATES = {"claimed", "authorized", "submitted", "unknown", "blocked"}
JOB_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
CELL_REF = re.compile(r"([A-Z]+)([1-9][0-9]*)\Z")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
MAX_WORKBOOK_BYTES = 20 * 1024 * 1024
MAX_IMAGE_BYTES = 50 * 1024 * 1024


class QueueError(Exception):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_inside(base: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise QueueError(f"{label} must be a nonempty path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise QueueError(f"{label} must be relative and cannot contain '..'")
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(base.resolve()) or resolved == base.resolve():
        raise QueueError(f"{label} escapes its allowed folder")
    return resolved


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        raw = archive.read(name)
        if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
            raise QueueError("Workbook XML declarations are unsupported")
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError) as exc:
        raise QueueError(f"Cannot read workbook XML: {name}: {exc}") from exc


def read_queue(path: Path) -> list[dict]:
    """Read XLSX cells directly; never evaluate formulas or external links."""
    if not path.is_file():
        raise QueueError(f"Workbook does not exist: {path}")
    if path.stat().st_size > MAX_WORKBOOK_BYTES:
        raise QueueError("Workbook exceeds 20 MiB")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(i.file_size for i in entries) > 50 * 1024 * 1024:
                raise QueueError("Workbook archive is too large")
            if len({i.filename for i in entries}) != len(entries):
                raise QueueError("Workbook contains duplicate archive paths")
            book = _xml(archive, "xl/workbook.xml")
            sheets = [s for s in book.findall("m:sheets/m:sheet", NS) if s.get("name") == "Queue"]
            if len(sheets) != 1:
                raise QueueError("Workbook must have exactly one sheet named Queue")
            rid = sheets[0].get("{" + NS["r"] + "}id")
            rels = _xml(archive, "xl/_rels/workbook.xml.rels")
            matches = [r for r in rels if r.get("Id") == rid]
            if len(matches) != 1 or matches[0].get("TargetMode") == "External":
                raise QueueError("Queue sheet relationship is invalid")
            target = matches[0].get("Target", "")
            if not target or ".." in Path(target).parts or "\\" in target:
                raise QueueError("Queue sheet relationship has an unsafe path")
            sheet_path = target.lstrip("/") if target.startswith("/") else "xl/" + target
            if not sheet_path.startswith("xl/"):
                raise QueueError("Queue sheet is outside workbook")
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = ["".join(t.text or "" for t in si.findall(".//m:t", NS))
                           for si in _xml(archive, "xl/sharedStrings.xml").findall("m:si", NS)]
            sheet = _xml(archive, sheet_path)
            rows: dict[int, dict] = {}
            for row in sheet.findall("m:sheetData/m:row", NS):
                try:
                    row_number = int(row.get("r", "0"))
                except ValueError as exc:
                    raise QueueError("Invalid workbook row number") from exc
                if not 1 <= row_number <= 10001 or row_number in rows:
                    raise QueueError("Queue supports up to 10,000 data rows, with unique row numbers")
                values, formulas, cell_errors, seen = {}, set(), set(), set()
                for cell in row.findall("m:c", NS):
                    ref = CELL_REF.fullmatch(cell.get("r", ""))
                    if not ref or int(ref[2]) != row_number or ref[1] in seen:
                        raise QueueError(f"Invalid or duplicate cell in row {row_number}")
                    column = ref[1]
                    seen.add(column)
                    if cell.find("m:f", NS) is not None:
                        formulas.add(column)
                    kind = cell.get("t", "n")
                    value = cell.findtext("m:v", "", NS)
                    if kind == "s":
                        try:
                            index = int(value)
                            if index < 0:
                                raise ValueError()
                            value = strings[index]
                        except (ValueError, IndexError) as exc:
                            raise QueueError(f"Invalid shared string in {column}{row_number}") from exc
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall("m:is//m:t", NS))
                    elif kind == "e":
                        cell_errors.add(column)
                    values[column] = value
                rows[row_number] = {"row": row_number, "values": values,
                                    "formulas": formulas, "cell_errors": cell_errors}
            header = rows.pop(1, None)
            if not header or header["formulas"] or header["cell_errors"]:
                raise QueueError("Queue row 1 must contain plain column headers")
            if [header["values"].get(c, "") for c in "ABCD"] != COLUMNS:
                raise QueueError("Queue row 1 must be exactly: enabled, job_id, image, prompt")
            if any(v.strip() for k, v in header["values"].items() if k not in set("ABCD")):
                raise QueueError("Queue must have exactly four columns")
            return [rows[n] for n in sorted(rows)]
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise QueueError(f"Cannot read workbook: {exc}") from exc


def parse_job(root: Path, row: dict) -> dict | None:
    values = row["values"]
    flag = values.get("A", "").strip()
    if "A" in row["formulas"]:
        raise QueueError("enabled must be literal YES, NO, or blank; formulas are forbidden")
    if "A" in row["cell_errors"]:
        raise QueueError("enabled must be literal YES, NO, or blank; Excel error cells are forbidden")
    if flag in {"", "NO"}:
        return None
    if flag != "YES":
        raise QueueError("enabled must be exactly YES, NO, or blank")
    if row["formulas"]:
        raise QueueError("Formulas are forbidden in enabled rows")
    if row["cell_errors"]:
        raise QueueError("Excel error cells are forbidden in enabled rows")
    if any(v.strip() for k, v in values.items() if k not in set("ABCD")):
        raise QueueError("Enabled row has data outside the four queue columns")
    job_id = values.get("B", "")
    if not JOB_ID.fullmatch(job_id):
        raise QueueError("job_id must be 1–80 letters, digits, underscores, or hyphens")
    image_name = values.get("C", "")
    image = resolve_inside(root / "images", image_name, "image")
    if image.suffix.lower() not in IMAGE_EXTENSIONS or not image.is_file():
        raise QueueError("image must be an existing JPG, JPEG, PNG, or WebP inside images/")
    if not 0 < image.stat().st_size <= MAX_IMAGE_BYTES:
        raise QueueError("image must be nonempty and at most 50 MiB")
    prompt = values.get("D", "")
    if not prompt.strip() or len(prompt) > 12000:
        raise QueueError("prompt must be nonblank and at most 12,000 characters")
    if any(ord(c) < 32 and c not in "\t\n\r" for c in prompt):
        raise QueueError("prompt contains unsupported control characters")
    image_hash = hashlib.sha256(image.read_bytes()).hexdigest()
    content_hash = hashlib.sha256(json.dumps([image_hash, prompt], ensure_ascii=False).encode()).hexdigest()
    fingerprint = hashlib.sha256(json.dumps([job_id, content_hash]).encode()).hexdigest()
    return {"job_id": job_id, "row": row["row"], "image": image_name,
            "image_path": str(image), "prompt": prompt, "image_sha256": image_hash,
            "content_hash": content_hash, "fingerprint": fingerprint}


def safe_csv(value) -> str:
    text = str(value or "")
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


def atomic_write(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Queue:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("images", "videos", "state"):
            folder = self.root / name
            if folder.is_symlink():
                raise QueueError(f"{name}/ must not be a symlink")
            folder.mkdir(exist_ok=True)
        self.state_path = self.root / "state" / "queue.json"

    @contextmanager
    def locked(self):
        lock_path = self.root / "state" / "queue.lock"
        if lock_path.is_symlink():
            raise QueueError("Queue lock cannot be a symlink")
        with open(lock_path, "a+", encoding="utf-8") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QueueError("Another queue command holds the lock; try again later") from exc
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self) -> dict:
        if not self.state_path.exists():
            return {"version": 1, "jobs": {}}
        if self.state_path.is_symlink():
            raise QueueError("Queue state cannot be a symlink")
        try:
            data = json.loads(self.state_path.read_text())
            if data["version"] != 1 or not isinstance(data["jobs"], dict):
                raise ValueError("unsupported state format")
            recorded_ids = set()
            for key, job in data["jobs"].items():
                if (not JOB_ID.fullmatch(key) or not isinstance(job, dict)
                        or job.get("job_id") != key or job.get("status") not in STATES
                        or not isinstance(job.get("content_hash"), str)
                        or not isinstance(job.get("fingerprint"), str)
                        or key.casefold() in recorded_ids):
                    raise ValueError("invalid job state")
                recorded_ids.add(key.casefold())
            return data
        except (ValueError, KeyError, TypeError, OSError) as exc:
            raise QueueError(f"State is unreadable; refusing to submit jobs: {exc}") from exc

    def save(self, state: dict):
        atomic_write(self.state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
        self.export(state)

    def export(self, state: dict):
        fields = ["job_id", "status", "image", "generation_url", "video", "updated_at", "note"]
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(fields)
        for job in state["jobs"].values():
            writer.writerow([safe_csv(job.get(f, "")) for f in fields])
        atomic_write(self.root / "status.csv", output.getvalue())

    def check_pause(self):
        if (self.root / "PAUSE").exists() or (self.root / "PAUSE").is_symlink():
            raise QueueError("PAUSE file exists. No job may be claimed or authorized")

    def scan_unlocked(self, state: dict) -> dict:
        errors, candidates, counts = [], [], {}
        for row in read_queue(self.root / "prompts.xlsx"):
            row_id = row["values"].get("B", "")
            if row["values"].get("A", "").strip() == "YES" and JOB_ID.fullmatch(row_id):
                canonical_id = row_id.casefold()
                counts[canonical_id] = counts.get(canonical_id, 0) + 1
            try:
                job = parse_job(self.root, row)
                if job:
                    candidates.append(job)
            except (QueueError, OSError) as exc:
                errors.append({"row": row["row"], "job_id": row["values"].get("B", ""), "error": str(exc)})
        pending, seen, recorded_ids = [], {}, {}
        for recorded in state["jobs"].values():
            seen[recorded["content_hash"]] = recorded["job_id"]
            recorded_ids[recorded["job_id"].casefold()] = recorded["job_id"]
        for job in candidates:
            job_id = job["job_id"]
            message = None
            if counts[job_id.casefold()] > 1:
                message = "Duplicate job_id (case-insensitive) in enabled rows; all rows with this ID are blocked"
            elif job_id.casefold() in recorded_ids and recorded_ids[job_id.casefold()] != job_id:
                message = "job_id collides case-insensitively with recorded job_id " + recorded_ids[job_id.casefold()]
            elif job_id in state["jobs"]:
                if state["jobs"][job_id]["fingerprint"] != job["fingerprint"]:
                    message = "Inputs changed for a recorded job_id; use a new job_id"
                else:
                    continue
            elif job["content_hash"] in seen:
                message = "Duplicate image and prompt already represented by job_id " + seen[job["content_hash"]]
            if message:
                errors.append({"row": job["row"], "job_id": job_id, "error": message})
                continue
            seen[job["content_hash"]] = job_id
            pending.append(job)
        return {"paused": (self.root / "PAUSE").exists(), "pending": pending, "errors": errors,
                "nonterminal": [j for j in state["jobs"].values() if j["status"] not in {"completed", "failed"}],
                "active": [j["job_id"] for j in state["jobs"].values() if j["status"] in ACTIVE_STATES]}

    def scan(self):
        with self.locked():
            state = self.load()
            result = self.scan_unlocked(state)
            self.export(state)
            return result

    def claim(self, job_id: str):
        with self.locked():
            self.check_pause()
            state = self.load()
            if job_id in state["jobs"]:
                raise QueueError("Job is already recorded; no automatic retry or duplicate submission is allowed")
            scan = self.scan_unlocked(state)
            if scan["active"]:
                raise QueueError("An uncertain or unfinished job already exists: " + ", ".join(scan["active"]))
            matches = [j for j in scan["pending"] if j["job_id"] == job_id]
            if len(matches) != 1:
                details = [e["error"] for e in scan["errors"] if e["job_id"] == job_id]
                raise QueueError("Job is not eligible: " + ("; ".join(details) or "not an enabled valid row"))
            job = matches[0]
            job.update(status="claimed", created_at=now(), updated_at=now(),
                       history=[{"status": "claimed", "at": now()}])
            state["jobs"][job_id] = job
            self.save(state)
            return job

    def authorize(self, job_id: str, evidence_path: Path):
        with self.locked():
            self.check_pause()
            state = self.load()
            job = self.recorded(state, job_id)
            if job["status"] != "claimed":
                raise QueueError("Only a newly claimed job can be authorized; authorizations are single-use")
            if evidence_path.stat().st_size > 65536:
                raise QueueError("Evidence file is too large")
            try:
                evidence = json.loads(evidence_path.read_text())
            except (ValueError, OSError) as exc:
                raise QueueError(f"Invalid evidence JSON: {exc}") from exc
            validate_evidence(evidence)
            # Re-read the saved workbook and bytes immediately before authorization.
            current = [parse_job(self.root, r) for r in read_queue(self.root / "prompts.xlsx")
                       if r["values"].get("B", "").casefold() == job_id.casefold()]
            matches = [j for j in current if j]
            if len(matches) != 1 or matches[0]["fingerprint"] != job["fingerprint"]:
                raise QueueError("Job inputs were removed or changed after claim; refusing authorization")
            other_active = [j["job_id"] for j in state["jobs"].values()
                            if j["job_id"] != job_id and j["status"] in ACTIVE_STATES]
            if other_active:
                raise QueueError("Another unfinished job exists")
            job["evidence"] = evidence
            self.transition(job, "authorized", "Fresh unlimited UI evidence accepted")
            self.save(state)
            return {**job, "instruction": "Recheck the live UI, then click Generate Unlimited exactly once immediately. If interrupted, never click again; reconcile history."}

    @staticmethod
    def recorded(state: dict, job_id: str):
        if job_id not in state["jobs"]:
            raise QueueError("Unknown job_id; claim a valid workbook row first")
        return state["jobs"][job_id]

    @staticmethod
    def transition(job: dict, status: str, note: str):
        job.update(status=status, updated_at=now(), note=note)
        job.setdefault("history", []).append({"status": status, "at": now(), "note": note})

    def set_status(self, job_id: str, status: str, note: str = "", generation_url: str | None = None,
                   video: str | None = None):
        if len(note) > 4000:
            raise QueueError("note exceeds 4,000 characters")
        with self.locked():
            state = self.load()
            job = self.recorded(state, job_id)
            old = job["status"]
            allowed = {
                "claimed": {"blocked", "unknown", "failed"},
                "authorized": {"submitted", "blocked", "unknown", "failed"},
                "submitted": {"completed", "blocked", "unknown", "failed"},
                "unknown": {"submitted", "completed", "blocked", "failed"},
                "blocked": {"submitted", "completed", "unknown", "failed"},
                "completed": set(), "failed": set(),
            }
            if status not in allowed[old]:
                raise QueueError(f"Transition {old} -> {status} is forbidden")
            if status in {"blocked", "unknown", "failed"} and not note.strip():
                raise QueueError(f"{status} requires an explanatory --note")
            if generation_url:
                validate_generation_url(generation_url)
            resulting_url = generation_url or job.get("generation_url")
            if status in {"submitted", "completed"} and not resulting_url:
                raise QueueError(f"{status} requires --generation-url from the actual generation")
            if status == "submitted":
                others = [j["job_id"] for j in state["jobs"].values()
                          if j["job_id"] != job_id and j["status"] in ACTIVE_STATES]
                if others:
                    raise QueueError("Another unfinished job exists: " + ", ".join(others))
            if status == "completed":
                if not video:
                    raise QueueError("completed requires --video relative to videos/")
                output = resolve_inside(self.root / "videos", video, "video")
                for recorded in state["jobs"].values():
                    if recorded["job_id"] == job_id or recorded["status"] != "completed":
                        continue
                    previous_output = resolve_inside(self.root / "videos", recorded.get("video", ""), "recorded video")
                    if str(previous_output).casefold() == str(output).casefold():
                        raise QueueError("Video output is already associated with completed job_id " + recorded["job_id"])
                validate_video(output)
                job["video"] = str(output.relative_to(self.root / "videos"))
                job["video_bytes"] = output.stat().st_size
            elif video:
                raise QueueError("--video is only accepted for completed jobs")
            if generation_url:
                job["generation_url"] = generation_url
            self.transition(job, status, note)
            self.save(state)
            return job


def validate_evidence(evidence: dict):
    required = {"model", "duration_seconds", "resolution", "unlimited_mode", "generate_label", "observed_at"}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise QueueError("Evidence must have exactly model, duration_seconds, resolution, unlimited_mode, generate_label, observed_at")
    if (evidence["model"] != "Kling 2.5 Turbo" or type(evidence["duration_seconds"]) is not int
            or evidence["duration_seconds"] != 5 or evidence["resolution"] != "720p"
            or evidence["unlimited_mode"] is not True or evidence["generate_label"] != "Generate Unlimited"):
        raise QueueError("Credit protection failed: require Kling 2.5 Turbo, 5s, 720p, Unlimited on, and exact Generate Unlimited label")
    try:
        observed = datetime.fromisoformat(evidence["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("missing timezone")
        age = (datetime.now(timezone.utc) - observed).total_seconds()
        if age < 0 or age > 60:
            raise ValueError("evidence must be from the preceding 60 seconds")
    except (ValueError, TypeError, AttributeError) as exc:
        raise QueueError(f"Invalid observed_at: {exc}") from exc


def validate_generation_url(value: str):
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname not in {"higgsfield.ai", "www.higgsfield.ai"}
            or parsed.username or parsed.password or parsed.port not in {None, 443}
            or len(value) > 4000 or not (parsed.path.strip("/") or parsed.query)):
        raise QueueError("generation-url must be an HTTPS Higgsfield generation page URL")


def validate_video(path: Path):
    if not path.is_file() or path.stat().st_size < 32:
        raise QueueError("Video output must be an existing nonempty media file inside videos/")
    with path.open("rb") as stream:
        head = stream.read(4096)
    if path.suffix.lower() == ".mp4":
        if head[4:8] != b"ftyp":
            raise QueueError("MP4 container signature is missing (download may be an HTML error page)")
    elif path.suffix.lower() == ".webm":
        if not head.startswith(b"\x1a\x45\xdf\xa3") or b"webm" not in head:
            raise QueueError("WebM container signature is missing")
    else:
        raise QueueError("Completed video must be .mp4 or .webm")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan", help="Validate the workbook and list pending and unfinished jobs; never submit")
    claim = commands.add_parser("claim", help="Persist a job before doing any browser submission")
    claim.add_argument("job_id")
    authorize = commands.add_parser("authorize", help="Validate fresh evidence and record a single-use authorization")
    authorize.add_argument("job_id")
    authorize.add_argument("--evidence", type=Path, required=True)
    status = commands.add_parser("set-status", help="Record observed remote progress or a verified local video")
    status.add_argument("job_id")
    status.add_argument("status", choices=["submitted", "completed", "blocked", "unknown", "failed"])
    status.add_argument("--note", default="")
    status.add_argument("--generation-url")
    status.add_argument("--video", help="Path relative to videos/")
    args = parser.parse_args(argv)
    try:
        queue = Queue(args.root)
        if args.command == "scan":
            result = queue.scan()
        elif args.command == "claim":
            result = queue.claim(args.job_id)
        elif args.command == "authorize":
            result = queue.authorize(args.job_id, args.evidence)
        else:
            result = queue.set_status(args.job_id, args.status, args.note, args.generation_url, args.video)
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False, indent=2))
        return 0
    except (QueueError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
