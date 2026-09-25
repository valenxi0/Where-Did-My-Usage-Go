import json
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/where-did-my-usage-go/scripts"
sys.path.insert(0, str(SCRIPTS))

try:
    import render_png
except SystemExit:
    render_png = None


@unittest.skipUnless(render_png, "Pillow is optional; run tests with `uv run --with pillow python -m unittest discover -s tests`")
class PngExportTests(unittest.TestCase):
    def test_sample_is_social_size(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/demo.json").read_text())
        image = render_png.render(data, "named")
        self.assertEqual(image.size, (1080, 1350))

    def test_story_and_link_preview_sizes(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/demo.json").read_text())
        for fmt, size in (("story", (1080, 1920)), ("og", (1200, 630))):
            for theme in render_png.THEMES:
                self.assertEqual(render_png.render(data, "anonymous", theme, fmt).size, size)

    def test_every_style_renders_every_format(self):
        data = json.loads((Path(__file__).resolve().parents[1] / "tests/fixtures/demo.json").read_text())
        for style in render_png.STYLES:
            for fmt, size in render_png.FORMATS.items():
                self.assertEqual(render_png.render(data, "anonymous", "paper", fmt, style).size, size)

    def test_styles_survive_missing_price_limit_and_hours(self):
        data = {"window": "Last 24 hours", "agents": [{"name": "Codex", "sessions": 2, "tokens": None}], "projects": []}
        for style in render_png.STYLES:
            self.assertEqual(render_png.render(data, "anonymous", style=style).size, (1080, 1350))

    def test_anonymous_image_ignores_named_only_content(self):
        data = {
            "window": "Past 7 days", "display_name": "Secret Name", "x_handle": "secret_handle",
            "anonymous_display_name": "Player One", "roast": "Secret roast",
            "anonymous_roast": "The tokens would like a word.",
            "highlight": "Secret win", "anonymous_highlight": "Built a feature.",
            "agents": [{"name": "Codex", "sessions": 1, "tokens": 100}],
            "projects": [{"name": "Secret Project", "anonymous_name": "Project 1",
                          "summary": "Secret summary", "anonymous_summary": "Worked on a feature.",
                          "sessions": 1, "tokens": 100}],
            "notes": ["Secret note"], "anonymous_notes": ["Local transcript data."],
        }
        first = [render_png.render(data, "anonymous", style=style).tobytes() for style in render_png.STYLES]
        data.update(display_name="Another Secret", x_handle="different_handle", roast="Another secret roast", highlight="Another secret win")
        data["projects"][0].update(name="Another private project", summary="Another private summary")
        data["notes"] = ["Another secret note"]
        second = [render_png.render(data, "anonymous", style=style).tobytes() for style in render_png.STYLES]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
