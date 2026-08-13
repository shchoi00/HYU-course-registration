import subprocess
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


def is_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", path],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode == 0


class TestCredentialIgnoreRules(unittest.TestCase):
    def test_sensitive_credential_files_are_ignored_at_any_depth(self):
        sensitive_paths = [
            "credential.key",
            "credentials.enc",
            "secrets.json",
            "config.json",
            ".env",
            ".env.local",
            "nested/credential.key",
            "nested/credentials.enc",
            "nested/secrets.json",
            "nested/config.json",
            "nested/.env",
            "nested/.env.production",
        ]

        for path in sensitive_paths:
            with self.subTest(path=path):
                self.assertTrue(is_ignored(path), f"sensitive file is not ignored: {path}")

    def test_credential_examples_remain_available_for_version_control(self):
        example_paths = [
            "secrets.json.example",
            "config.json.example",
            ".env.example",
            "nested/.env.example",
        ]

        for path in example_paths:
            with self.subTest(path=path):
                self.assertFalse(is_ignored(path), f"example file is unexpectedly ignored: {path}")


if __name__ == "__main__":
    unittest.main()
