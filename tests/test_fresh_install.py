import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/where-did-my-usage-go"


class FreshInstallTests(unittest.TestCase):
    def test_copied_skill_uses_private_data_dir_and_exports_both_visibilities(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Run with `uv run --with pillow python -m unittest discover -s tests`")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root / "installed-skill"
            shutil.copytree(SKILL, install, ignore=shutil.ignore_patterns("private", "__pycache__"))
            data_dir = root / "app-data"
            codex_session = root / ".codex/sessions/example.jsonl"
            codex_session.parent.mkdir(parents=True)
            at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            codex_session.write_text("\n".join(json.dumps(item) for item in [
                {"type": "session_meta", "payload": {"id": "one", "cwd": "/private-project"}},
                {"type": "turn_context", "payload": {"model": "test-model"}},
                {"timestamp": at, "type": "event_msg", "payload": {"type": "user_message", "message": "Build a feature"}},
                {"timestamp": at, "type": "event_msg", "payload": {"type": "token_count",
                 "info": {"total_token_usage": {"input_tokens": 100, "output_tokens": 20, "cached_input_tokens": 30}}}},
            ]))
            env = dict(os.environ, HOME=str(root), USERPROFILE=str(root), WDMUG_DATA_DIR=str(data_dir))

            missing_window = subprocess.run([sys.executable, str(install / "scripts/collect.py")],
                                            cwd=install, env=env, capture_output=True, text=True)
            self.assertNotEqual(missing_window.returncode, 0)
            self.assertFalse(data_dir.exists())

            def run(script, *arguments):
                subprocess.run([sys.executable, str(install / "scripts" / script), *arguments],
                               cwd=install, env=env, check=True, capture_output=True, text=True)

            run("collect.py", "--hours", "48", "--through-now")
            pricing_path = data_dir / "pricing.json"
            pricing_path.write_text(json.dumps({"as_of": "2026-01-01", "models": [{
                "model": "test-model", "input_per_million": 2,
                "cached_input_per_million": 0.2, "output_per_million": 10,
                "source_url": "https://example.com/pricing"}]}))
            run("draft.py", "--name", "Sample Person", "--x-handle", "@sample_user", "--pricing", str(pricing_path))
            share_path = data_dir / "share.json"
            share = json.loads(share_path.read_text())
            share["projects"][0]["summary"] = "Built a private feature."
            share["projects"][0]["anonymous_summary"] = "Built a feature."
            tampered = dict(share)
            tampered["estimated_api_cost"] = {**share["estimated_api_cost"], "usd": 9999}
            share_path.write_text(json.dumps(tampered))
            invalid = subprocess.run([sys.executable, str(install / "scripts/export_card.py"),
                                      "--visibility", "named", "--output", str(data_dir / "invalid")],
                                     cwd=install, env=env, capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertFalse((data_dir / "invalid.png").exists())
            share_path.write_text(json.dumps(share))
            run("export_card.py", "--visibility", "named", "--output", str(data_dir / "named"))
            run("export_card.py", "--visibility", "anonymous", "--output", str(data_dir / "anonymous"))
            run("export_card.py", "--visibility", "anonymous", "--theme", "all", "--output", str(data_dir / "preview"))
            self.assertEqual(len(list(data_dir.glob("preview-*.png"))), 4)

            named_html = (data_dir / "named.html").read_text()
            anonymous_html = (data_dir / "anonymous.html").read_text()
            self.assertIn("Sample Person", named_html)
            self.assertIn("@sample_user", named_html)
            self.assertIn("Est. API equivalent", named_html)
            self.assertNotIn("Agent operator", named_html)
            self.assertNotIn("Player card / 001", named_html)
            self.assertNotIn('class="avatar"', named_html)
            for secret in ("Sample Person", "sample_user", "private-project", "Built a private feature"):
                self.assertNotIn(secret, anonymous_html)
            for name in ("named.png", "anonymous.png"):
                with Image.open(data_dir / name) as image:
                    self.assertEqual(image.size, (1080, 1350))
            self.assertFalse((install / "private").exists())
            if os.name != "nt":
                self.assertEqual((data_dir / "activity.json").stat().st_mode & 0o777, 0o600)
                self.assertEqual((data_dir / "named.png").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
