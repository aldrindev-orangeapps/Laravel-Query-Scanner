import tempfile
import unittest
from pathlib import Path

from analyzer import CacheStore, LaravelQueryScanner, extract_methods, mask_php


CONTROLLER = """<?php
namespace App\\Http\\Controllers;
use App\\User;
use Illuminate\\Support\\Facades\\DB;

class UserController {
    public function index() {
        $users = User::all();
        foreach ($users as $user) {
            echo $user->posts;
            DB::table('logs')->where('user_id', $user->id)->first();
        }
        DB::table('users')->select('*')->get();
    }

    public function repeated() {
        User::where('active', 1)->first();
        User::where('active', 2)->first();
    }

    public function fullyQualified() {
        \\App\\User::all();
    }
}
"""

MODEL = """<?php
namespace App;
class User extends Model {
    protected $table = 'users';
    public function posts() { return $this->hasMany(Post::class); }
}
"""

MIGRATION = """<?php
Schema::create('users', function ($table) {
    $table->bigIncrements('id');
    $table->string('email')->index();
});
"""


class LaravelFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "app" / "Http" / "Controllers").mkdir(parents=True)
        (root / "database" / "migrations").mkdir(parents=True)
        (root / "artisan").write_text("", encoding="utf-8")
        (root / "composer.json").write_text("{}", encoding="utf-8")
        self.controller = root / "app" / "Http" / "Controllers" / "UserController.php"
        self.controller.write_text(CONTROLLER, encoding="utf-8")
        (root / "app" / "User.php").write_text(MODEL, encoding="utf-8")
        (root / "database" / "migrations" / "create_users.php").write_text(MIGRATION, encoding="utf-8")


class AnalyzerTests(unittest.TestCase):
    def test_mask_preserves_offsets_and_newlines(self) -> None:
        source = "<?php\n// function fake() {}\n$x = 'query ->get()';\n"
        masked = mask_php(source)
        self.assertEqual(len(source), len(masked))
        self.assertEqual(source.count("\n"), masked.count("\n"))
        self.assertNotIn("fake", masked)
        self.assertNotIn("query", masked)

    def test_extracts_named_methods_not_comment_text(self) -> None:
        methods = extract_methods(CONTROLLER + "\n// function ignored() {}")
        self.assertEqual(["index", "repeated", "fullyQualified"], [method.name for method in methods])

    def test_scanner_finds_core_rules(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller)
            rules = {finding.rule_id for finding in summary.findings}
            self.assertTrue({"LQS001", "LQS002", "LQS003", "LQS004", "LQS005"}.issubset(rules))
            n_plus_one = next(item for item in summary.findings if item.rule_id == "LQS002")
            self.assertEqual("index", n_plus_one.method)
            self.assertEqual("posts", next(name for name in scanner.relationships if name == "posts"))

    def test_selected_method_limits_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller, selected_method="repeated")
            self.assertTrue(summary.findings)
            self.assertEqual({"repeated"}, {item.method for item in summary.findings})

    def test_fully_qualified_model_query_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller, selected_method="fullyQualified")
            self.assertEqual(["LQS004"], [item.rule_id for item in summary.findings])

    def test_cache_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=True)
            scanner.cache = CacheStore(Path(directory) / "cache")
            first = scanner.scan(selected_file=fixture.controller)
            second = scanner.scan(selected_file=fixture.controller)
            self.assertEqual(0, first.files_cached)
            self.assertEqual(1, second.files_cached)
            self.assertEqual(len(first.findings), len(second.findings))


if __name__ == "__main__":
    unittest.main()

