import tempfile
import unittest
from pathlib import Path

from analyzer import LaravelQueryScanner
from context_builder import build_context
from tests.test_analyzer import LaravelFixture


class ContextBuilderTests(unittest.TestCase):
    def test_context_is_scoped_to_one_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            findings = scanner.scan(selected_file=fixture.controller).findings
            context = build_context(
                fixture.root,
                "app/Http/Controllers/UserController.php",
                "index",
                findings,
            )
            self.assertIn("Laravel 7", context)
            self.assertIn("public function index()", context)
            self.assertNotIn("public function repeated()", context)
            self.assertIn("posts(): hasMany", context)
            self.assertIn("create_users.php", context)
            self.assertIn("LQS001", context)


if __name__ == "__main__":
    unittest.main()

