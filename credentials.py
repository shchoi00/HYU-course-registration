from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from platformdirs import PlatformDirs


class CredentialStorageError(Exception):
    """Raised when stored credential files are incomplete or invalid."""


class CredentialSetupCancelled(Exception):
    """Raised when credential onboarding is cancelled before validation succeeds."""


@dataclass(frozen=True)
class CredentialPaths:
    key_path: Path
    token_path: Path


@dataclass(frozen=True)
class ValidatedCredentials:
    credentials: dict[str, str]
    validation: object
    migrated_legacy: bool


def default_credential_paths() -> CredentialPaths:
    directories = PlatformDirs("hyu-course-registration", appauthor=False)
    return CredentialPaths(
        Path(directories.user_config_path) / "credential.key",
        Path(directories.user_data_path) / "credentials.enc",
    )


class CredentialStore:
    PAYLOAD_VERSION = 1

    def __init__(self, paths: CredentialPaths):
        self.paths = paths

    def load(self) -> Optional[dict[str, str]]:  # noqa: UP045
        key_exists = self.paths.key_path.exists()
        token_exists = self.paths.token_path.exists()

        if not key_exists and not token_exists:
            return None
        if key_exists != token_exists:
            raise CredentialStorageError("credential storage is incomplete")

        try:
            fernet = Fernet(self.paths.key_path.read_bytes())
            decrypted = fernet.decrypt(self.paths.token_path.read_bytes())
            payload = json.loads(decrypted.decode("utf-8"))
        except (OSError, ValueError, InvalidToken) as exc:
            raise CredentialStorageError("stored credentials are invalid") from exc

        return self._credentials_from_payload(payload)

    def save(self, credentials: dict[str, str]) -> None:
        normalized = self._validate_credentials(credentials)
        key, created_key, previous_key = self._load_or_create_key()
        payload = {
            "version": self.PAYLOAD_VERSION,
            "credentials": normalized,
        }
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        token = Fernet(key).encrypt(data)
        try:
            _atomic_write(self.paths.token_path, token)
        except OSError:
            if created_key:
                if previous_key is None:
                    try:
                        self.paths.key_path.unlink()
                    except FileNotFoundError:
                        pass
                else:
                    _atomic_write(self.paths.key_path, previous_key)
            raise

    def _load_or_create_key(self) -> tuple[bytes, bool, Optional[bytes]]:  # noqa: UP045
        if self.paths.key_path.exists():
            key = self.paths.key_path.read_bytes()
            try:
                Fernet(key)
            except ValueError:
                previous_key = key
                key = Fernet.generate_key()
                _atomic_write(self.paths.key_path, key)
                return key, True, previous_key
            return key, False, None

        key = Fernet.generate_key()
        _atomic_write(self.paths.key_path, key)
        return key, True, None

    def _credentials_from_payload(self, payload):
        if not isinstance(payload, dict):
            raise CredentialStorageError("stored credentials are invalid")
        if payload.get("version") != self.PAYLOAD_VERSION:
            raise CredentialStorageError("stored credentials version is unsupported")

        try:
            return self._validate_credentials(payload["credentials"])
        except KeyError as exc:
            raise CredentialStorageError("stored credentials are invalid") from exc

    @staticmethod
    def _validate_credentials(credentials):
        if not isinstance(credentials, dict):
            raise CredentialStorageError("credentials must be a mapping")

        user_id = credentials.get("user_id")
        password = credentials.get("password")
        if not isinstance(user_id, str) or not user_id:
            raise CredentialStorageError("user_id is required")
        if not isinstance(password, str) or not password:
            raise CredentialStorageError("password is required")

        return {"user_id": user_id, "password": password}


def obtain_validated_credentials(
    store,
    prompt_credentials,
    validate_credentials,
    legacy_path=None,
) -> ValidatedCredentials:
    try:
        stored_credentials = store.load()
    except CredentialStorageError:
        stored_credentials = None

    result = _validate_candidate(
        stored_credentials,
        validate_credentials,
        migrated_legacy=False,
    )
    if result is not None:
        return result

    legacy_credentials = _load_legacy_credentials(legacy_path)
    result = _validate_candidate(
        legacy_credentials,
        validate_credentials,
        migrated_legacy=True,
    )
    if result is not None:
        store.save(result.credentials)
        return result

    while True:
        prompted_credentials = prompt_credentials()
        if prompted_credentials is None:
            raise CredentialSetupCancelled("credential setup was cancelled")

        result = _validate_candidate(
            prompted_credentials,
            validate_credentials,
            migrated_legacy=False,
        )
        if result is not None:
            store.save(result.credentials)
            return result


def _validate_candidate(
    credentials,
    validate_credentials,
    migrated_legacy: bool,
) -> Optional[ValidatedCredentials]:  # noqa: UP045
    if credentials is None:
        return None

    try:
        normalized = CredentialStore._validate_credentials(credentials)
    except CredentialStorageError:
        return None

    validation = validate_credentials(normalized)
    if not validation:
        return None

    return ValidatedCredentials(
        credentials=normalized,
        validation=validation,
        migrated_legacy=migrated_legacy,
    )


def _load_legacy_credentials(legacy_path):
    if legacy_path is None:
        return None

    path = Path(legacy_path)
    if not path.exists():
        return None

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    try:
        return CredentialStore._validate_credentials(payload)
    except CredentialStorageError:
        return None


def _atomic_write(path: Path, data: bytes) -> None:
    _ensure_private_directory(path.parent)
    temp_name = None

    try:
        with tempfile.NamedTemporaryFile(
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temp_file:
            temp_name = temp_file.name
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())

        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
    except OSError:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise


def _ensure_private_directory(path: Path) -> None:
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent

    path.mkdir(parents=True, exist_ok=True)
    for directory in missing:
        os.chmod(directory, 0o700)
