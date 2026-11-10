import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import briefing_schedule


class BriefingScheduleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.workspace = Path(self.directory.name) / "Fictional household"
        self.daily = f'0 7 * * 1-5 /usr/bin/python3 "{self.workspace}/scripts/briefing.py" daily >> "{self.workspace}/logs/briefing.log" 2>&1\n'
        self.weekly = f'0 8 * * 0 /usr/bin/python3 "{self.workspace}/scripts/briefing.py" weekly\n'
        self.other = 'MAILTO=private@example.invalid\n0 1 * * * /usr/bin/true\n'
        self.content = self.other + self.daily + self.weekly
        self.digest = hashlib.sha256(self.content.encode()).hexdigest()

    def test_exact_owned_entries_only_and_repeat_is_noop(self):
        updated, kinds, ambiguous = briefing_schedule.retirement_plan(self.content, self.workspace)
        self.assertEqual(kinds, ["daily", "weekly"])
        self.assertEqual(ambiguous, 0)
        self.assertTrue(updated.startswith(self.other))
        self.assertEqual(briefing_schedule.retirement_plan(updated, self.workspace), (updated, [], 0))

    def test_other_workspaces_and_complex_commands_are_not_removed(self):
        other = self.daily.replace(str(self.workspace), "/other/household")
        complex_line = self.weekly.rstrip() + ' ; echo secret\n'
        for content, ambiguous in ((other, 0), (complex_line, 1)):
            self.assertEqual(briefing_schedule.retirement_plan(content, self.workspace),
                             (content, [], ambiguous))

    def test_read_only_audit_does_not_create_files_or_print_commands(self):
        with mock.patch.object(briefing_schedule, "read_crontab", return_value=self.content):
            result = briefing_schedule.schedule_health(self.workspace)
        self.assertEqual(result["status"], "warn")
        self.assertNotIn("private@example", str(result))
        self.assertNotIn(str(self.workspace), str(result))
        self.assertFalse(self.workspace.exists())

    def test_apply_backs_up_and_preserves_unrelated_jobs(self):
        updated = briefing_schedule.retirement_plan(self.content, self.workspace)[0]
        with mock.patch.object(briefing_schedule, "read_crontab", side_effect=[self.content, self.content, updated]), \
                mock.patch.object(briefing_schedule, "verify_managed_jobs") as verify, \
                mock.patch.object(briefing_schedule.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            backup = briefing_schedule.apply_retirement(self.workspace, self.digest)
        self.assertEqual(backup.read_text(), self.content)
        self.assertEqual(backup.stat().st_mode & 0o077, 0)
        self.assertEqual(backup.parent.stat().st_mode & 0o077, 0)
        verify.assert_called_once_with(self.workspace, ["daily", "weekly"])
        self.assertEqual(run.call_args.args[0], ["crontab", "-"])
        self.assertEqual(run.call_args.kwargs["input"], updated)

    def test_changed_crontab_or_missing_managed_jobs_never_installs(self):
        for cause in ("audit_changed", "prewrite_changed", "unloaded", "backup_failed"):
            readings = [self.content + "# changed\n"] if cause == "audit_changed" else [self.content, self.content + "# changed\n"]
            with self.subTest(cause=cause), \
                    mock.patch.object(briefing_schedule, "read_crontab", side_effect=readings), \
                    mock.patch.object(briefing_schedule, "verify_managed_jobs", side_effect=RuntimeError("unloaded") if cause == "unloaded" else None), \
                    mock.patch.object(briefing_schedule, "atomic_write_text", side_effect=OSError if cause == "backup_failed" else None), \
                    mock.patch.object(briefing_schedule.subprocess, "run") as install:
                with self.assertRaises((RuntimeError, OSError)):
                    briefing_schedule.apply_retirement(self.workspace, self.digest)
                install.assert_not_called()

    def test_ambiguous_entry_requires_review(self):
        content = self.weekly.rstrip() + " && echo unrelated\n"
        with mock.patch.object(briefing_schedule, "read_crontab", return_value=content), \
                mock.patch.object(briefing_schedule, "verify_managed_jobs") as verify:
            with self.assertRaises(RuntimeError):
                briefing_schedule.apply_retirement(self.workspace, hashlib.sha256(content.encode()).hexdigest())
            verify.assert_not_called()

    def test_managed_jobs_must_point_at_same_workspace_and_task(self):
        good = f"arguments = {{\n/bin/bash\n{self.workspace}/scripts/cron_runner.sh\nbriefing-weekly\n}}"
        for stdout, code, expected in ((good, 0, True), (good, 1, False), ("other workspace", 0, False)):
            with mock.patch.object(briefing_schedule.subprocess, "run", return_value=mock.Mock(returncode=code, stdout=stdout)):
                if expected:
                    briefing_schedule.verify_managed_jobs(self.workspace, ["weekly"])
                else:
                    with self.assertRaises(RuntimeError):
                        briefing_schedule.verify_managed_jobs(self.workspace, ["weekly"])

    def test_crontab_unavailable_is_warning_not_fake_recovery(self):
        with mock.patch.object(briefing_schedule, "read_crontab", side_effect=subprocess.TimeoutExpired("crontab", 15)):
            self.assertEqual(briefing_schedule.schedule_health(self.workspace)["status"], "warn")

    def test_install_failure_keeps_backup_and_does_not_blindly_restore(self):
        with mock.patch.object(briefing_schedule, "read_crontab", side_effect=[self.content, self.content]), \
                mock.patch.object(briefing_schedule, "verify_managed_jobs"), \
                mock.patch.object(briefing_schedule.subprocess, "run", return_value=mock.Mock(returncode=1)) as install:
            with self.assertRaises(RuntimeError):
                briefing_schedule.apply_retirement(self.workspace, self.digest)
        self.assertEqual(install.call_count, 1)
        backups = list((self.workspace / "backups").glob("*/crontab.txt"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), self.content)

    def test_failed_read_and_missing_crontab_are_distinguished(self):
        for code, error, expected in ((1, "no crontab for user", ""), (1, "permission denied", None)):
            with mock.patch.object(briefing_schedule.subprocess, "run", return_value=mock.Mock(returncode=code, stderr=error)):
                if expected is None:
                    with self.assertRaises(RuntimeError):
                        briefing_schedule.read_crontab()
                else:
                    self.assertEqual(briefing_schedule.read_crontab(), expected)


if __name__ == "__main__":
    unittest.main()
