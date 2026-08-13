import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import credentials
from credentials import CredentialPaths, CredentialStorageError, CredentialStore


class TestCredentialStore(unittest.TestCase):
    def test_round_trip_encrypts_without_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(
                    root / "config" / "credential.key",
                    root / "data" / "credentials.enc",
                )
            )
            expected = {"user_id": "portal-user", "password": "secret-password"}

            store.save(expected)

            self.assertEqual(store.load(), expected)
            self.assertNotIn(b"portal-user", store.paths.token_path.read_bytes())
            self.assertNotIn(b"secret-password", store.paths.token_path.read_bytes())

    def test_missing_key_for_existing_token_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(
                    root / "config" / "credential.key",
                    root / "data" / "credentials.enc",
                )
            )

            store.save({"user_id": "u", "password": "p"})
            store.paths.key_path.unlink()

            with self.assertRaises(CredentialStorageError):
                store.load()

    def test_first_save_token_write_failure_removes_new_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(
                    root / "config" / "credential.key",
                    root / "data" / "credentials.enc",
                )
            )
            original_atomic_write = credentials._atomic_write

            def fail_token_write(path, data):
                if path == store.paths.token_path:
                    raise OSError("token write failed")
                original_atomic_write(path, data)

            with patch("credentials._atomic_write", side_effect=fail_token_write):
                with self.assertRaises(OSError):
                    store.save({"user_id": "u", "password": "p"})

            self.assertFalse(store.paths.key_path.exists())
            self.assertFalse(store.paths.token_path.exists())
