"""Safety checks use temporary queues; they never launch a browser or spend credits."""

import fcntl
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from queue_agent import Queue, QueueError, read_queue, safe_csv, validate_evidence


def workbook(path, data, *, shared=False, formulas=None, headers=None, extra=None,
             cell_errors=None):
    formulas = formulas or {}
    cell_errors = cell_errors or {}
    rows = [headers or ["enabled", "job_id", "image", "prompt"]] + data
    all_strings = []
    xml_rows = []
    for row_number, row in enumerate(rows, 1):
        cells = []
        for column_number, value in enumerate(row):
            column = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[column_number]
            address = f"{column}{row_number}"
            formula = f"<f>{escape(formulas[address])}</f>" if address in formulas else ""
            if address in cell_errors:
                cell = f'<c r="{address}" t="e">{formula}<v>{escape(cell_errors[address])}</v></c>'
            elif shared:
                all_strings.append(str(value))
                cell = f'<c r="{address}" t="s">{formula}<v>{len(all_strings)-1}</v></c>'
            else:
                cell = f'<c r="{address}" t="inlineStr">{formula}<is><t>{escape(str(value))}</t></is></c>'
            cells.append(cell)
        if extra and row_number in extra:
            cells.append(extra[row_number])
        xml_rows.append(f'<row r="{row_number}">' + "".join(cells) + "</row>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Queue" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(xml_rows) + "</sheetData></worksheet>")
        if shared:
            z.writestr("xl/sharedStrings.xml", '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in all_strings) + "</sst>")


def evidence(**overrides):
    value = {"model": "Kling 2.5 Turbo", "duration_seconds": 5, "resolution": "720p",
             "unlimited_mode": True, "generate_label": "Generate Unlimited",
             "observed_at": datetime.now(timezone.utc).isoformat()}
    value.update(overrides)
    return value


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.queue = Queue(self.root)
        (self.root / "images" / "scene.png").write_bytes(b"test image content")
        self.rows = [["YES", "scene_01", "scene.png", "Slow camera push-in."]]
        self.write_book()

    def write_book(self, **kwargs):
        workbook(self.root / "prompts.xlsx", self.rows, **kwargs)

    def write_evidence(self, **overrides):
        path = self.root / "state" / "evidence.json"
        path.write_text(json.dumps(evidence(**overrides)))
        return path

    def authorize(self):
        self.queue.claim("scene_01")
        return self.queue.authorize("scene_01", self.write_evidence())

    def test_inline_and_shared_strings_are_equivalent(self):
        self.rows[0][3] = "Hindi: नमस्ते\nA & B < C"
        self.write_book()
        inline = self.queue.scan()["pending"]
        self.write_book(shared=True)
        shared = self.queue.scan()["pending"]
        self.assertEqual(inline, shared)
        self.assertEqual(shared[0]["prompt"], self.rows[0][3])

    def test_schema_and_extra_columns(self):
        self.write_book(headers=["enabled", "prompt", "image", "job_id"])
        with self.assertRaisesRegex(QueueError, "row 1"):
            self.queue.scan()
        self.write_book(extra={2: '<c r="AB2" t="inlineStr"><is><t>extra</t></is></c>'})
        self.assertIn("outside", self.queue.scan()["errors"][0]["error"])

    def test_formulas_and_flags_are_not_instructions(self):
        self.write_book(formulas={"D2": 'HYPERLINK("https://example.invalid")'})
        self.assertIn("Formulas", self.queue.scan()["errors"][0]["error"])
        self.rows = [["NO", "ignored", "missing.png", ""], ["", "ignored2", "", ""],
                     ["true", "invalid", "scene.png", "hi"]]
        self.write_book()
        result = self.queue.scan()
        self.assertEqual(result["pending"], [])
        self.assertEqual(len(result["errors"]), 1)
        self.rows = [["NO", "ignored", "scene.png", "hi"]]
        self.write_book(formulas={"A2": '"NO"'})
        self.assertEqual(len(self.queue.scan()["errors"]), 1)

    def test_path_traversal_absolute_and_symlink_are_blocked(self):
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside")
        (self.root / "images" / "escape.png").symlink_to(outside)
        for value in ["../outside.png", str(outside), "escape.png"]:
            with self.subTest(value=value):
                self.rows[0][2] = value
                self.write_book()
                self.assertFalse(self.queue.scan()["pending"])
                with self.assertRaises(QueueError):
                    self.queue.claim("scene_01")

    def test_excel_error_cells_rejected_in_enabled_rows(self):
        for address, error in [("A2", "#N/A"), ("B2", "#REF!"),
                               ("C2", "#VALUE!"), ("D2", "#DIV/0!")]:
            with self.subTest(address=address):
                self.write_book(cell_errors={address: error})
                scan = self.queue.scan()
                self.assertFalse(scan["pending"])
                self.assertEqual(len(scan["errors"]), 1)
                self.assertIn("Excel error cells", scan["errors"][0]["error"])
                with self.assertRaises(QueueError):
                    self.queue.claim("scene_01")
                self.assertFalse(self.queue.load()["jobs"])

    def test_disabled_rows_skip_errors_except_in_enabled_field(self):
        for flag in ["NO", ""]:
            with self.subTest(flag=flag):
                self.rows[0][0] = flag
                self.write_book(cell_errors={"B2": "#REF!", "C2": "#N/A", "D2": "#VALUE!"})
                scan = self.queue.scan()
                self.assertFalse(scan["pending"])
                self.assertFalse(scan["errors"])
                self.write_book(cell_errors={"A2": "#N/A"})
                scan = self.queue.scan()
                self.assertFalse(scan["pending"])
                self.assertIn("Excel error cells", scan["errors"][0]["error"])

    def test_literal_error_text_remains_a_valid_prompt(self):
        for shared in [False, True]:
            for prompt in ["#N/A", "#VALUE!", "#CELL_ERROR:#N/A"]:
                with self.subTest(shared=shared, prompt=prompt):
                    self.rows[0][3] = prompt
                    self.write_book(shared=shared)
                    scan = self.queue.scan()
                    self.assertFalse(scan["errors"])
                    self.assertEqual(scan["pending"][0]["prompt"], prompt)

    def test_authorization_rejects_prompt_changed_to_excel_error(self):
        self.queue.claim("scene_01")
        self.write_book(cell_errors={"D2": "#N/A"})
        with self.assertRaisesRegex(QueueError, "Excel error cells"):
            self.queue.authorize("scene_01", self.write_evidence())
        job = self.queue.load()["jobs"]["scene_01"]
        self.assertEqual(job["status"], "claimed")
        self.assertNotIn("evidence", job)

    def test_duplicate_content_and_duplicate_ids(self):
        self.rows.append(["YES", "scene_02", "scene.png", "Slow camera push-in."])
        self.write_book()
        scan = self.queue.scan()
        self.assertEqual([j["job_id"] for j in scan["pending"]], ["scene_01"])
        self.assertIn("Duplicate image", scan["errors"][0]["error"])
        self.queue.claim("scene_01")
        self.assertFalse(self.queue.scan()["pending"])
        self.rows[1][1] = "scene_01"
        self.write_book()
        self.assertEqual(len(self.queue.scan()["errors"]), 2)

    def test_changed_prompt_and_image_require_new_id(self):
        self.queue.claim("scene_01")
        self.rows[0][3] = "Different camera motion"
        self.write_book()
        self.assertIn("Inputs changed", self.queue.scan()["errors"][0]["error"])
        with self.assertRaisesRegex(QueueError, "changed"):
            self.queue.authorize("scene_01", self.write_evidence())
        self.rows[0][3] = "Slow camera push-in."
        self.write_book()
        (self.root / "images" / "scene.png").write_bytes(b"changed content")
        self.assertIn("Inputs changed", self.queue.scan()["errors"][0]["error"])
        with self.assertRaisesRegex(QueueError, "changed"):
            self.queue.authorize("scene_01", self.write_evidence())

    def test_casefold_job_id_collisions_in_workbook_and_ledger(self):
        self.rows.append(["YES", "SCENE_01", "scene.png", "Different scene"])
        self.write_book()
        result = self.queue.scan()
        self.assertFalse(result["pending"])
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(all("case-insensitive" in e["error"] for e in result["errors"]))
        with self.assertRaisesRegex(QueueError, "case-insensitive"):
            self.queue.claim("SCENE_01")
        # Even an enabled alias with an invalid image reserves its filename.
        self.rows[1][2] = "missing.png"
        self.write_book()
        self.assertFalse(self.queue.scan()["pending"])
        self.rows.pop()
        self.write_book()
        self.queue.claim("scene_01")
        self.queue.set_status("scene_01", "failed", note="Stopped before submission")
        self.rows = [["YES", "SCENE_01", "scene.png", "Different scene"]]
        self.write_book()
        self.assertIn("recorded job_id", self.queue.scan()["errors"][0]["error"])
        with self.assertRaisesRegex(QueueError, "case-insensitively"):
            self.queue.claim("SCENE_01")

    def test_authorization_rejects_casefold_alias_added_after_claim(self):
        self.queue.claim("scene_01")
        self.rows.append(["YES", "SCENE_01", "scene.png", "Different scene"])
        self.write_book()
        with self.assertRaisesRegex(QueueError, "changed"):
            self.queue.authorize("scene_01", self.write_evidence())
        self.assertEqual(self.queue.load()["jobs"]["scene_01"]["status"], "claimed")
        self.assertFalse(self.queue.scan()["pending"])
        self.assertTrue(all("case-insensitive" in e["error"] for e in self.queue.scan()["errors"]))

    def test_uncertain_job_never_reclaims_or_opens_second_job(self):
        self.authorize()
        self.queue.set_status("scene_01", "unknown", note="Browser disconnected after click")
        self.rows.append(["YES", "scene_02", "scene.png", "Unique next motion"])
        self.write_book()
        restarted = Queue(self.root)
        with self.assertRaisesRegex(QueueError, "already recorded"):
            restarted.claim("scene_01")
        with self.assertRaisesRegex(QueueError, "unfinished"):
            restarted.claim("scene_02")
        with self.assertRaisesRegex(QueueError, "newly claimed"):
            restarted.authorize("scene_01", self.write_evidence())
        self.assertEqual(restarted.scan()["active"], ["scene_01"])

    def test_blocked_job_keeps_shared_draft_reserved(self):
        self.authorize()
        self.queue.set_status("scene_01", "blocked", note="Waiting for the user to confirm submission")
        self.rows.append(["YES", "scene_02", "scene.png", "Unique next motion"])
        self.write_book()
        restarted = Queue(self.root)
        self.assertEqual(restarted.scan()["active"], ["scene_01"])
        with self.assertRaisesRegex(QueueError, "unfinished"):
            restarted.claim("scene_02")
        with self.assertRaisesRegex(QueueError, "already recorded"):
            restarted.claim("scene_01")
        with self.assertRaisesRegex(QueueError, "newly claimed"):
            restarted.authorize("scene_01", self.write_evidence())
        restarted.set_status("scene_01", "failed", note="Confirmed no remote submission; abandoned")
        self.assertEqual(restarted.claim("scene_02")["status"], "claimed")

    def test_blocked_job_recovers_verified_manual_result_while_paused(self):
        for via_submitted in [False, True]:
            with self.subTest(via_submitted=via_submitted):
                root = self.root / str(via_submitted)
                queue = Queue(root)
                (root / "images" / "scene.png").write_bytes(b"test image content")
                workbook(root / "prompts.xlsx", self.rows)
                queue.claim("scene_01")
                queue.authorize("scene_01", self.write_evidence())
                queue.set_status("scene_01", "blocked", note="Waiting for the user to confirm submission")
                (root / "PAUSE").touch()
                with self.assertRaisesRegex(QueueError, "generation-url"):
                    queue.set_status("scene_01", "completed", video="scene_01.mp4")
                receipt = "https://higgsfield.ai/generation/manually-confirmed"
                if via_submitted:
                    queue.set_status("scene_01", "submitted", generation_url=receipt,
                                     note="Matched the user's manual submission in website history")
                with self.assertRaisesRegex(QueueError, "existing nonempty"):
                    queue.set_status("scene_01", "completed", generation_url=receipt,
                                     video="scene_01.mp4")
                (root / "videos" / "scene_01.mp4").write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
                job = queue.set_status("scene_01", "completed", generation_url=receipt,
                                       video="scene_01.mp4", note="Downloaded the matched manual result")
                self.assertEqual(job["status"], "completed")
                self.assertEqual(job["generation_url"], receipt)
                self.assertFalse(queue.scan()["active"])
                (root / "PAUSE").unlink()
                with self.assertRaisesRegex(QueueError, "already recorded"):
                    queue.claim("scene_01")

    def test_single_use_authorization_and_pause(self):
        (self.root / "PAUSE").touch()
        with self.assertRaisesRegex(QueueError, "PAUSE"):
            self.queue.claim("scene_01")
        (self.root / "PAUSE").unlink()
        self.queue.claim("scene_01")
        (self.root / "PAUSE").touch()
        with self.assertRaisesRegex(QueueError, "PAUSE"):
            self.queue.authorize("scene_01", self.write_evidence())
        (self.root / "PAUSE").unlink()
        self.queue.authorize("scene_01", self.write_evidence())
        with self.assertRaisesRegex(QueueError, "single-use"):
            self.queue.authorize("scene_01", self.write_evidence())

    def test_lock_prevents_concurrent_state_mutation(self):
        with (self.root / "state" / "queue.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(QueueError, "lock"):
                self.queue.claim("scene_01")
        self.assertFalse(self.queue.load()["jobs"])
        self.queue.claim("scene_01")

    def test_corrupt_state_fails_closed(self):
        (self.root / "state" / "queue.json").write_text("{broken")
        with self.assertRaisesRegex(QueueError, "unreadable"):
            self.queue.claim("scene_01")

    def test_unlimited_evidence_rejects_cost_and_stale_or_wrong_settings(self):
        validate_evidence(evidence())
        invalid = [dict(model="Kling 3.0"), dict(duration_seconds=10), dict(duration_seconds=True),
                   dict(resolution="1080p"), dict(unlimited_mode=False), dict(unlimited_mode=1),
                   dict(generate_label="Generate 10 credits"), dict(generate_label="Generate Unlimited 0"),
                   dict(credits=0), dict(observed_at="2020-01-01T00:00:00+00:00"),
                   dict(observed_at="2026-09-20T10:00:00"),
                   dict(observed_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())]
        for changes in invalid:
            with self.subTest(changes=changes):
                with self.assertRaises(QueueError):
                    validate_evidence(evidence(**changes))

    def test_status_transitions_and_verified_video(self):
        self.queue.claim("scene_01")
        with self.assertRaisesRegex(QueueError, "forbidden"):
            self.queue.set_status("scene_01", "submitted", generation_url="https://higgsfield.ai/generation/abc")
        self.queue.authorize("scene_01", self.write_evidence())
        with self.assertRaisesRegex(QueueError, "generation-url"):
            self.queue.set_status("scene_01", "submitted")
        self.queue.set_status("scene_01", "submitted", generation_url="https://higgsfield.ai/generation/abc")
        output = self.root / "videos" / "scene_01.mp4"
        output.write_bytes(b"<html>Error</html>" + b" " * 100)
        with self.assertRaisesRegex(QueueError, "signature"):
            self.queue.set_status("scene_01", "completed", video="scene_01.mp4")
        output.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
        job = self.queue.set_status("scene_01", "completed", video="scene_01.mp4")
        self.assertEqual(job["status"], "completed")
        self.assertFalse(self.queue.scan()["pending"])
        with self.assertRaisesRegex(QueueError, "already recorded"):
            self.queue.claim("scene_01")

    def test_completed_video_cannot_escape_output_directory(self):
        self.authorize()
        self.queue.set_status("scene_01", "submitted", generation_url="https://higgsfield.ai/generation/abc")
        outside = self.root / "outside.mp4"
        outside.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
        (self.root / "videos" / "escape.mp4").symlink_to(outside)
        for video in ["../outside.mp4", "escape.mp4", str(outside)]:
            with self.subTest(video=video):
                with self.assertRaises(QueueError):
                    self.queue.set_status("scene_01", "completed", video=video)
        self.assertEqual(self.queue.load()["jobs"]["scene_01"]["status"], "submitted")

    def test_completed_video_cannot_reuse_resolved_or_casefold_output_path(self):
        self.authorize()
        self.queue.set_status("scene_01", "submitted", generation_url="https://higgsfield.ai/generation/abc")
        output = self.root / "videos" / "scene_01.mp4"
        output.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 100)
        self.queue.set_status("scene_01", "completed", video=output.name)
        self.rows.append(["YES", "scene_02", "scene.png", "Different scene"])
        self.write_book()
        self.queue.claim("scene_02")
        self.queue.authorize("scene_02", self.write_evidence())
        self.queue.set_status("scene_02", "submitted", generation_url="https://higgsfield.ai/generation/def")
        (self.root / "videos" / "alias.mp4").symlink_to(output)
        for filename in ["scene_01.mp4", "SCENE_01.MP4", "alias.mp4"]:
            with self.subTest(filename=filename):
                with self.assertRaisesRegex(QueueError, "already associated"):
                    self.queue.set_status("scene_02", "completed", video=filename)
        self.assertEqual(self.queue.load()["jobs"]["scene_02"]["status"], "submitted")
        (self.root / "videos" / "scene_02.mp4").write_bytes(output.read_bytes())
        self.queue.set_status("scene_02", "completed", video="scene_02.mp4")

    def test_csv_formula_injection_protected(self):
        for value in ["=1+1", " +SUM(A1)", "-1+1", "@HYPERLINK()", "\t=1", "\nhello"]:
            self.assertTrue(safe_csv(value).startswith("'"))
        self.queue.claim("scene_01")
        self.queue.set_status("scene_01", "blocked", note='=HYPERLINK("https://example.invalid")')
        self.assertIn("'=HYPERLINK", (self.root / "status.csv").read_text())


if __name__ == "__main__":
    unittest.main()
