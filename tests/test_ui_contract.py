import re
import unittest
from pathlib import Path


class UiContractTests(unittest.TestCase):
    def test_ids_referenced_by_js_exist_in_html(self) -> None:
        root = Path(__file__).resolve().parents[1]
        app_js = (root / "static" / "app.js").read_text(encoding="utf-8")
        index_html = (root / "static" / "index.html").read_text(encoding="utf-8")

        js_ids = set(re.findall(r'document\.getElementById\("([A-Za-z0-9_-]+)"\)', app_js))
        html_ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"', index_html))

        missing = sorted(js_ids - html_ids)
        self.assertEqual(missing, [], f"IDs referenced in app.js missing from index.html: {missing}")

    def test_layout_sections_present(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index_html = (root / "static" / "index.html").read_text(encoding="utf-8")

        self.assertIn('class="metrics"', index_html)
        self.assertIn('class="controls card"', index_html)
        self.assertIn('class="card chart-wrap"', index_html)


if __name__ == "__main__":
    unittest.main()
