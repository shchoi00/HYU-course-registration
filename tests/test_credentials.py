import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import credentials
from credentials import (
    CredentialPaths,
    CredentialSetupCancelled,
    CredentialStorageError,
    CredentialStore,
    obtain_validated_credentials,
)


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

            with patch("credentials._atomic_write", side_effect=fail_token_write), self.assertRaises(OSError):
                store.save({"user_id": "u", "password": "p"})

            self.assertFalse(store.paths.key_path.exists())
            self.assertFalse(store.paths.token_path.exists())

    def test_replacing_corrupt_key_token_write_failure_preserves_old_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(
                    root / "config" / "credential.key",
                    root / "data" / "credentials.enc",
                )
            )
            store.paths.key_path.parent.mkdir(parents=True)
            store.paths.token_path.parent.mkdir(parents=True)
            store.paths.key_path.write_text("not-a-fernet-key", encoding="utf-8")
            store.paths.token_path.write_text("not-a-token", encoding="utf-8")
            original_key = store.paths.key_path.read_bytes()
            original_token = store.paths.token_path.read_bytes()
            original_atomic_write = credentials._atomic_write

            def fail_token_write(path, data):
                if path == store.paths.token_path:
                    raise OSError("token write failed")
                original_atomic_write(path, data)

            with patch("credentials._atomic_write", side_effect=fail_token_write), self.assertRaises(OSError):
                store.save({"user_id": "u", "password": "p"})

            self.assertEqual(store.paths.key_path.read_bytes(), original_key)
            self.assertEqual(store.paths.token_path.read_bytes(), original_token)


class TestCredentialOnboarding(unittest.TestCase):
    def make_store(self, root):
        return CredentialStore(
            CredentialPaths(
                root / "config" / "credential.key",
                root / "data" / "credentials.enc",
            )
        )

    def test_failed_prompted_login_saves_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            prompts = iter([
                {"user_id": "wrong", "password": "wrong"},
                None,
            ])

            with self.assertRaises(CredentialSetupCancelled):
                obtain_validated_credentials(
                    store,
                    prompt_credentials=lambda: next(prompts),
                    validate_credentials=lambda value: None,
                )

            self.assertFalse(store.paths.key_path.exists())
            self.assertFalse(store.paths.token_path.exists())

    def test_successful_prompted_login_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            session = object()

            result = obtain_validated_credentials(
                store,
                prompt_credentials=lambda: {"user_id": "valid", "password": "valid-pass"},
                validate_credentials=lambda value: session,
            )

            self.assertEqual(result.credentials, {"user_id": "valid", "password": "valid-pass"})
            self.assertIs(result.validation, session)
            self.assertFalse(result.migrated_legacy)
            self.assertEqual(store.load()["user_id"], "valid")

    def test_stored_credentials_validate_without_prompting(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self.make_store(Path(directory))
            store.save({"user_id": "stored", "password": "stored-pass"})
            session = object()

            result = obtain_validated_credentials(
                store,
                prompt_credentials=lambda: self.fail("stored credentials should avoid prompt"),
                validate_credentials=lambda value: session if value["user_id"] == "stored" else None,
            )

            self.assertEqual(result.credentials["user_id"], "stored")
            self.assertIs(result.validation, session)
            self.assertFalse(result.migrated_legacy)

    def test_corrupt_store_falls_back_without_overwriting_until_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self.make_store(root)
            store.paths.key_path.parent.mkdir(parents=True)
            store.paths.token_path.parent.mkdir(parents=True)
            store.paths.key_path.write_text("not-a-fernet-key", encoding="utf-8")
            store.paths.token_path.write_text("not-a-token", encoding="utf-8")
            original_key = store.paths.key_path.read_bytes()
            original_token = store.paths.token_path.read_bytes()
            prompts = iter([
                {"user_id": "bad", "password": "bad-pass"},
                None,
            ])

            with self.assertRaises(CredentialSetupCancelled):
                obtain_validated_credentials(
                    store,
                    prompt_credentials=lambda: next(prompts),
                    validate_credentials=lambda value: None,
                )

            self.assertEqual(store.paths.key_path.read_bytes(), original_key)
            self.assertEqual(store.paths.token_path.read_bytes(), original_token)

    def test_corrupt_store_is_replaced_after_prompted_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self.make_store(root)
            store.paths.key_path.parent.mkdir(parents=True)
            store.paths.token_path.parent.mkdir(parents=True)
            store.paths.key_path.write_text("not-a-fernet-key", encoding="utf-8")
            store.paths.token_path.write_text("not-a-token", encoding="utf-8")
            session = object()

            result = obtain_validated_credentials(
                store,
                prompt_credentials=lambda: {"user_id": "valid", "password": "valid-pass"},
                validate_credentials=lambda value: session,
            )

            self.assertIs(result.validation, session)
            self.assertEqual(store.load(), {"user_id": "valid", "password": "valid-pass"})

    def test_legacy_secrets_migrate_only_after_successful_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self.make_store(root)
            legacy_path = root / "secrets.json"
            legacy_path.write_text(
                json.dumps({"user_id": "legacy", "password": "legacy-pass"}),
                encoding="utf-8",
            )
            attempts = []
            session = object()

            result = obtain_validated_credentials(
                store,
                prompt_credentials=lambda: self.fail("valid legacy credentials should avoid prompt"),
                validate_credentials=lambda value: session if attempts.append(value) is None else None,
                legacy_path=legacy_path,
            )

            self.assertEqual(result.credentials["user_id"], "legacy")
            self.assertIs(result.validation, session)
            self.assertTrue(result.migrated_legacy)
            self.assertEqual(store.load()["password"], "legacy-pass")
            self.assertEqual(attempts, [{"user_id": "legacy", "password": "legacy-pass"}])

    def test_failed_legacy_validation_prompts_and_does_not_mark_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self.make_store(root)
            legacy_path = root / "secrets.json"
            legacy_path.write_text(
                json.dumps({"user_id": "legacy", "password": "wrong"}),
                encoding="utf-8",
            )
            session = object()

            result = obtain_validated_credentials(
                store,
                prompt_credentials=lambda: {"user_id": "prompted", "password": "valid-pass"},
                validate_credentials=lambda value: session if value["user_id"] == "prompted" else None,
                legacy_path=legacy_path,
            )

            self.assertEqual(result.credentials["user_id"], "prompted")
            self.assertIs(result.validation, session)
            self.assertFalse(result.migrated_legacy)
            self.assertEqual(store.load()["user_id"], "prompted")
