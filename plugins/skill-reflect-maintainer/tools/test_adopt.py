import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import adopt


class AdoptEngineTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[3]
        self.scratch = Path(__file__).resolve().parents[1] / ".test-work"
        self.scratch.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix="case-", dir=str(self.scratch))
        self.to = Path(self.tmp.name) / "author-plugin"

    def tearDown(self):
        self.tmp.cleanup()
        if self.scratch.exists() and not any(self.scratch.iterdir()):
            self.scratch.rmdir()

    def run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = adopt.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_adopt_idempotent_copies_pin_hooks_config_and_stable_hash(self):
        self.to.mkdir(parents=True)
        hooks_dir = self.to / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "hooks.json").write_text(
            json.dumps({"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "echo keep"}]}]}}),
            encoding="utf-8",
        )

        code, _, err = self.run_cli(
            "adopt",
            "--to", str(self.to),
            "--from", str(self.repo),
            "--scope", "demo-skill",
            "--destination", "acme/widgets",
        )
        self.assertEqual(code, 0, err)
        self.assertTrue((self.to / "skills" / "skill-reflect" / "SKILL.md").is_file())
        self.assertTrue((self.to / "hooks" / "stage_pending.py").is_file())
        self.assertTrue((self.to / "hooks" / "nudge_start.py").is_file())
        self.assertTrue((self.to / "skill-reflect.config.schema.json").is_file())
        pin = json.loads((self.to / ".skill-reflect-vendor.json").read_text(encoding="utf-8"))
        first_hash = pin["contentHash"]
        self.assertEqual(pin["schema"], 1)
        self.assertEqual(pin["upstreamVersion"], "1.0.0")
        self.assertEqual(pin["scope"], ["demo-skill"])
        self.assertEqual(pin["destinationRepo"], "acme/widgets")
        self.assertRegex(first_hash, r"^sha256:[0-9a-f]{64}$")

        hooks = json.loads((self.to / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertIn("PreToolUse", hooks["hooks"])
        self.assertIn("SessionStart", hooks["hooks"])
        self.assertIn("SessionEnd", hooks["hooks"])
        self.assertEqual(json.dumps(hooks).count("nudge_start.py"), 1)
        self.assertEqual(json.dumps(hooks).count("stage_pending.py"), 1)

        config_path = self.to / "skill-reflect.config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["mode"], "vendored")
        self.assertEqual(config["destination"]["mode"], "ask")
        config_path.write_text('{"version": 1, "mode": "vendored", "custom_preserved": true}\n', encoding="utf-8")

        code, _, err = self.run_cli(
            "adopt",
            "--to", str(self.to),
            "--from", str(self.repo),
            "--scope", "demo-skill",
            "--destination", "acme/widgets",
        )
        self.assertEqual(code, 0, err)
        self.assertIn("custom_preserved", config_path.read_text(encoding="utf-8"))
        pin2 = json.loads((self.to / ".skill-reflect-vendor.json").read_text(encoding="utf-8"))
        self.assertEqual(pin2["contentHash"], first_hash)
        hooks2 = json.loads((self.to / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.assertEqual(json.dumps(hooks2).count("nudge_start.py"), 1)
        self.assertEqual(json.dumps(hooks2).count("stage_pending.py"), 1)

    def test_doctor_exit_codes_current_update_available_and_drift(self):
        code, _, err = self.run_cli("adopt", "--to", str(self.to), "--from", str(self.repo))
        self.assertEqual(code, 0, err)

        code, out, err = self.run_cli("doctor", "--to", str(self.to), "--reference-version", "1.0.0")
        self.assertEqual(code, 0, err + out)

        code, out, _ = self.run_cli("doctor", "--to", str(self.to), "--reference-version", "9.9.9")
        self.assertEqual(code, 10, out)
        self.assertIn("update available: yes", out)

        skill_md = self.to / "skills" / "skill-reflect" / "SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nlocal edit\n", encoding="utf-8")
        code, out, _ = self.run_cli("doctor", "--to", str(self.to), "--reference-version", "1.0.0")
        self.assertEqual(code, 11, out)
        self.assertIn("local drift: yes", out)

    def test_update_refuses_drift_without_force(self):
        code, _, err = self.run_cli("adopt", "--to", str(self.to), "--from", str(self.repo))
        self.assertEqual(code, 0, err)
        skill_md = self.to / "skills" / "skill-reflect" / "SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\nlocal drift\n", encoding="utf-8")

        code, out, _ = self.run_cli("update", "--to", str(self.to), "--from", str(self.repo))
        self.assertEqual(code, 3, out)
        self.assertIn("Local drift detected", out)


if __name__ == "__main__":
    unittest.main()
