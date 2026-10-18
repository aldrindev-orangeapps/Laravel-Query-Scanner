import tempfile
import unittest
from pathlib import Path

from analyzer import CacheStore, LaravelQueryScanner, QUERY_PATTERN, extract_methods, mask_php


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

    public function multipleLoopQueries() {
        $users = User::get();
        foreach ($users as $user) {
            User::where('id', $user->id)->first();
            DB::table('logs')->where('user_id', $user->id)->first();
        }
    }

    public function assignedRelationshipName() {
        $users = User::get();
        foreach ($users as $user) {
            $user->posts = User::where('id', $user->id)->first();
        }
    }

    public function collectionOperations() {
        $users = User::where('active', 1)->get();
        $users->where('type', 'a')->pluck('id');
        $users->where('type', 'b')->pluck('id');
    }

    public function repeatedBuilder() {
        $builder = User::query();
        $builder->where('active', 1)->first();
        $builder->where('active', 2)->first();
    }

    public function differentBuilders() {
        $users = User::query();
        $posts = Post::query();
        $users->where('active', 1)->first();
        $posts->where('active', 1)->first();
    }

    public function sessionInsideLoop() {
        foreach ([1, 2] as $id) {
            Session::get('branch_code');
        }
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

POST_MODEL = """<?php
namespace App;
class Post extends Model {}
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
        (root / "app" / "Post.php").write_text(POST_MODEL, encoding="utf-8")
        (root / "database" / "migrations" / "create_users.php").write_text(MIGRATION, encoding="utf-8")


class AnalyzerTests(unittest.TestCase):
    def test_mask_preserves_offsets_and_newlines(self) -> None:
        source = "<?php\n// function fake() {}\n$x = 'query ->get()';\n"
        masked = mask_php(source)
        self.assertEqual(len(source), len(masked))
        self.assertEqual(source.count("\n"), masked.count("\n"))
        self.assertNotIn("fake", masked)
        self.assertNotIn("query", masked)

    def test_property_access_does_not_swallow_following_query(self) -> None:
        source = "if ($user->id) {\n    User::where('id', 1)->first();\n}"
        match = QUERY_PATTERN.search(mask_php(source))
        self.assertIsNotNone(match)
        self.assertTrue(source[match.start():].startswith("User::where"))

    def test_extracts_named_methods_not_comment_text(self) -> None:
        methods = extract_methods(CONTROLLER + "\n// function ignored() {}")
        self.assertIn("index", [method.name for method in methods])
        self.assertIn("sessionInsideLoop", [method.name for method in methods])

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

    def test_reports_every_query_in_one_loop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller, selected_method="multipleLoopQueries")
            self.assertEqual(2, sum(item.rule_id == "LQS001" for item in summary.findings))

    def test_relationship_assignment_is_not_lazy_loading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller, selected_method="assignedRelationshipName")
            self.assertNotIn("LQS002", {item.rule_id for item in summary.findings})
            self.assertEqual(1, sum(item.rule_id == "LQS001" for item in summary.findings))

    def test_collection_operations_are_not_repeated_queries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller, selected_method="collectionOperations")
            self.assertNotIn("LQS005", {item.rule_id for item in summary.findings})

    def test_same_builder_repeats_but_different_models_do_not_collide(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            repeated = scanner.scan(selected_file=fixture.controller, selected_method="repeatedBuilder")
            different = scanner.scan(selected_file=fixture.controller, selected_method="differentBuilders")
            self.assertIn("LQS005", {item.rule_id for item in repeated.findings})
            self.assertNotIn("LQS005", {item.rule_id for item in different.findings})

    def test_session_get_inside_loop_is_not_a_database_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = LaravelFixture(Path(directory))
            scanner = LaravelQueryScanner(fixture.root, use_cache=False)
            summary = scanner.scan(selected_file=fixture.controller, selected_method="sessionInsideLoop")
            self.assertFalse(summary.findings)

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

