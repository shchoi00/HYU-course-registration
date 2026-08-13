# Interactive Registration Modes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-platform interactive CLI that validates and encrypts credentials once, offers scheduled registration and direct cancellation-ticketing modes, and automatically transitions scheduled failures into unlimited ticketing.

**Architecture:** Keep portal HTTP details in `main.py`, move credential persistence into `credentials.py`, and move time/mode state transitions into `workflow.py`. Both new modules expose pure or dependency-injected interfaces so credential, timer, and retry behavior can be verified without contacting the portal.

**Tech Stack:** Python 3.9+, `requests`, `questionary==2.1.1`, `cryptography==50.0.0`, `platformdirs==4.4.0`, standard-library `unittest`.

**Spec:** `docs/superpowers/specs/2026-08-13-interactive-registration-modes-design.md`

## Global Constraints

- Preserve the existing SSO/RSA, wishlist, NetFunnel, and registration request formats.
- Normal operation must not require editing credential, course, schedule, or mode files.
- Save credentials only after a real SSO validation succeeds.
- Support Windows, macOS, and Linux without an OS keychain or repeated master-password prompt.
- Scheduled mode sends no registration request before its validated future local time.
- Scheduled mode attempts each resolved selected course exactly once in priority order, then sends only unfinished courses to ticketing.
- Ticketing is unlimited, stable-priority round robin until all courses succeed or `Ctrl+C` interrupts it.
- Preserve unrelated working-tree changes and stage only files owned by each task.

---

## File Structure

- Create `credentials.py`: encrypted credential storage, cross-platform paths, atomic/private writes, legacy loading, and validation-before-save onboarding.
- Create `workflow.py`: schedule parsing/countdown, scheduled single pass, unlimited ticketing, and result summaries.
- Modify `main.py`: replace file-required startup with credential onboarding; add mode/time prompts, fresh scheduled login, wishlist rematching, and orchestration.
- Create `tests/test_credentials.py`: real Fernet storage and onboarding behavior.
- Create `tests/test_workflow.py`: deterministic schedule and mode state transitions.
- Modify `tests/test_cli_workflow.py`: retain course selection tests and cover mode/time prompts at the UI boundary.
- Modify `requirements.txt`: add pinned cross-platform storage/encryption dependencies.
- Modify `README.md`, `architecture.md`, `config.json.example`, `secrets.json.example`, `walkthrough.md`: document interactive operation and legacy migration.

---

### Task 1: Encrypted Cross-Platform Credential Store

**Files:**
- Create: `credentials.py`
- Create: `tests/test_credentials.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces: `CredentialPaths(key_path: Path, token_path: Path)`.
- Produces: `default_credential_paths() -> CredentialPaths`.
- Produces: `CredentialStore(paths: CredentialPaths)` with `load() -> dict[str, str] | None` and `save(credentials: dict[str, str]) -> None`.
- Produces: `CredentialStorageError` for incomplete, corrupt, or invalid stored payloads.

- [ ] **Step 1: Add dependency declarations**

Append exact Python 3.9-compatible versions:

```text
cryptography==50.0.0
platformdirs==4.4.0
```

- [ ] **Step 2: Write failing encrypted round-trip tests**

```python
class TestCredentialStore(unittest.TestCase):
    def test_round_trip_encrypts_without_plaintext(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = CredentialStore(
                CredentialPaths(root / "config" / "credential.key", root / "data" / "credentials.enc")
            )
            expected = {"user_id": "portal-user", "password": "secret-password"}

            store.save(expected)

            self.assertEqual(store.load(), expected)
            self.assertNotIn(b"portal-user", store.paths.token_path.read_bytes())
            self.assertNotIn(b"secret-password", store.paths.token_path.read_bytes())

    def test_missing_key_for_existing_token_is_rejected(self):
        store.save({"user_id": "u", "password": "p"})
        store.paths.key_path.unlink()
        with self.assertRaises(CredentialStorageError):
            store.load()
```

- [ ] **Step 3: Run the focused tests and verify RED**

Run: `venv/bin/python -m unittest tests.test_credentials.TestCredentialStore -v`

Expected: import failure because `credentials.py` does not exist.

- [ ] **Step 4: Implement storage paths, encryption, and atomic writes**

Implement these concrete elements:

```python
@dataclass(frozen=True)
class CredentialPaths:
    key_path: Path
    token_path: Path

def default_credential_paths() -> CredentialPaths:
    directories = PlatformDirs("hyu-course-registration", appauthor=False)
    return CredentialPaths(
        Path(directories.user_config_path) / "credential.key",
        Path(directories.user_data_path) / "credentials.enc",
    )

class CredentialStore:
    PAYLOAD_VERSION = 1

    def load(self):
        # Return None only when both files are absent. Reject one-file and InvalidToken states.

    def save(self, credentials):
        # Validate non-empty user_id/password, create/reuse Fernet key,
        # encrypt canonical UTF-8 JSON, then atomically replace the token.
```

Use a private `_atomic_write(path: Path, data: bytes)` that creates the parent, writes and flushes a temporary sibling, calls `os.fsync`, applies POSIX `0600`, and calls `os.replace`. Apply POSIX `0700` to created directories. Never log key, token, ID, or password.

- [ ] **Step 5: Run credential tests and dependency checks**

Run:

```bash
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m unittest tests.test_credentials.TestCredentialStore -v
venv/bin/python -m pip check
```

Expected: all pass, with no broken dependencies.

- [ ] **Step 6: Commit Task 1**

```bash
git add credentials.py tests/test_credentials.py requirements.txt
git commit -m "feat: add encrypted credential storage"
```

---

### Task 2: Validate Credentials Before Saving and Migrate Legacy Secrets

**Files:**
- Modify: `credentials.py`
- Modify: `tests/test_credentials.py`
- Modify: `main.py`

**Interfaces:**
- Consumes: `CredentialStore.load()` and `CredentialStore.save()` from Task 1.
- Produces: `CredentialSetupCancelled`.
- Produces: `ValidatedCredentials(credentials: dict[str, str], validation: object, migrated_legacy: bool)`.
- Produces: `obtain_validated_credentials(store, prompt_credentials, validate_credentials, legacy_path=None) -> ValidatedCredentials`.
- Changes: SSO login failures raise `AuthenticationError` rather than terminating the process with `sys.exit`.

- [ ] **Step 1: Write failing validation-before-save tests**

```python
def test_failed_prompted_login_saves_nothing(self):
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
    session = object()
    result = obtain_validated_credentials(
        store,
        prompt_credentials=lambda: {"user_id": "valid", "password": "valid-pass"},
        validate_credentials=lambda value: session,
    )
    self.assertIs(result.validation, session)
    self.assertEqual(store.load()["user_id"], "valid")
```

Add cases for stored credential automatic validation, corrupt store fallback without overwrite, and `secrets.json` migration only after successful validation.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `venv/bin/python -m unittest tests.test_credentials -v`

Expected: missing onboarding symbols.

- [ ] **Step 3: Implement deterministic onboarding**

Implement this order exactly:

```python
def obtain_validated_credentials(store, prompt_credentials, validate_credentials, legacy_path=None):
    # 1. Try encrypted stored credentials.
    # 2. If absent/broken, try a complete legacy JSON payload once.
    # 3. Prompt until validation succeeds or prompt returns None.
    # 4. Call store.save only after validate_credentials returns a truthy session/context.
```

Preserve corrupt encrypted files until replacement validation succeeds. Once validated, `save()` atomically replaces them. Return `migrated_legacy=True` only when legacy credentials were validated and encrypted.

- [ ] **Step 4: Make authentication composable**

Add:

```python
class AuthenticationError(RuntimeError):
    pass
```

Change credential-related `sys.exit(1)` branches in `login_with_sso` and `login_with_cookie` into `AuthenticationError` raises. Keep top-level user-facing error handling in `main()`.

- [ ] **Step 5: Run onboarding and existing authentication-adjacent tests**

Run:

```bash
venv/bin/python -m unittest tests.test_credentials tests.test_course_selection -v
venv/bin/python -m py_compile main.py credentials.py
```

Expected: all pass.

- [ ] **Step 6: Commit Task 2**

```bash
git add credentials.py tests/test_credentials.py main.py
git commit -m "feat: validate credentials before persistence"
```

---

### Task 3: Schedule Parsing and Countdown

**Files:**
- Create: `workflow.py`
- Create: `tests/test_workflow.py`

**Interfaces:**
- Produces: `ScheduleValidationError`.
- Produces: `parse_target_time(value: str, now: datetime) -> datetime`.
- Produces: `format_remaining(seconds: float) -> str` returning zero-padded `HH:MM:SS`.
- Produces: `countdown_until(target, now_fn, sleep_fn, render_fn) -> None`.

- [ ] **Step 1: Write failing schedule tests**

```python
def test_parse_target_time_rejects_past_value(self):
    now = datetime(2026, 8, 13, 9, 0, 0)
    with self.assertRaisesRegex(ScheduleValidationError, "미래"):
        parse_target_time("2026-08-13 08:59:59", now)

def test_countdown_renders_and_waits_until_target(self):
    clock = FakeClock(datetime(2026, 8, 13, 9, 59, 58))
    rendered = []
    countdown_until(
        datetime(2026, 8, 13, 10, 0, 0),
        now_fn=clock.now,
        sleep_fn=clock.sleep,
        render_fn=rendered.append,
    )
    self.assertEqual(rendered, ["00:00:02", "00:00:01", "00:00:00"])
```

Also test malformed format and `format_remaining(3661) == "01:01:01"`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `venv/bin/python -m unittest tests.test_workflow.TestScheduling -v`

Expected: import failure because `workflow.py` does not exist.

- [ ] **Step 3: Implement parsing and countdown**

Use local naive `datetime` consistently because the CLI explicitly accepts local system time. Parse only `%Y-%m-%d %H:%M:%S`. Countdown sleeps at most one second per iteration and calls `render_fn` only when the displayed whole-second value changes.

- [ ] **Step 4: Run scheduling tests**

Run: `venv/bin/python -m unittest tests.test_workflow.TestScheduling -v`

Expected: pass without real sleeping.

- [ ] **Step 5: Commit Task 3**

```bash
git add workflow.py tests/test_workflow.py
git commit -m "feat: add validated registration countdown"
```

---

### Task 4: Scheduled Single Pass and Unlimited Cancellation Ticketing

**Files:**
- Modify: `workflow.py`
- Modify: `tests/test_workflow.py`
- Modify: `tests/test_cli_workflow.py`

**Interfaces:**
- Produces: `RegistrationSummary(completed: list[dict], pending: list[dict], interrupted: bool)`.
- Produces: `run_scheduled_pass(courses, attempt_course) -> RegistrationSummary`.
- Produces: `run_ticketing(courses, attempt_course, wait_for_next_round=lambda: None) -> RegistrationSummary`.
- `attempt_course(course, attempt_number) -> Literal["success", "retry"]`.

- [ ] **Step 1: Write failing scheduled-transition test**

```python
def test_scheduled_pass_attempts_once_and_returns_only_failures(self):
    outcomes = {"1": "retry", "2": "success", "3": "retry"}
    calls = []
    summary = run_scheduled_pass(
        courses,
        lambda course, attempt: calls.append((course["suupNo"], attempt)) or outcomes[course["suupNo"]],
    )
    self.assertEqual(calls, [("1", 1), ("2", 1), ("3", 1)])
    self.assertEqual([c["suupNo"] for c in summary.pending], ["1", "3"])
```

- [ ] **Step 2: Write failing unlimited ticketing tests**

```python
def test_ticketing_round_robins_until_all_succeed_without_attempt_cap(self):
    # Course 1 succeeds on attempt 12; course 2 succeeds on attempt 2.
    # Assert stable order and that attempt 12 occurs.

def test_ticketing_returns_pending_summary_on_keyboard_interrupt(self):
    # Raise KeyboardInterrupt on the third callback and assert interrupted=True,
    # completed courses preserved, and unfinished courses reported pending.
```

- [ ] **Step 3: Run workflow tests and verify RED**

Run: `venv/bin/python -m unittest tests.test_workflow -v`

Expected: missing workflow runner symbols.

- [ ] **Step 4: Implement mode runners**

Use one state record per course:

```python
{"course": course, "attempts": 0, "status": "pending"}
```

`run_scheduled_pass` iterates once. `run_ticketing` loops while pending, increments each course independently, removes only `success`, waits once between rounds, and catches `KeyboardInterrupt` outside the per-course iteration so it can return a complete summary.

- [ ] **Step 5: Replace bounded runner tests**

Remove tests and production expectations tied to `max_attempts`. Retain response classification, selection, and transient-error continuation coverage, rewriting them against `run_ticketing` where necessary.

- [ ] **Step 6: Run all workflow/CLI unit tests**

Run:

```bash
venv/bin/python -m unittest tests.test_workflow tests.test_cli_workflow -v
```

Expected: pass, including an attempt number greater than 10.

- [ ] **Step 7: Commit Task 4**

```bash
git add workflow.py tests/test_workflow.py tests/test_cli_workflow.py
git commit -m "feat: add scheduled and ticketing workflows"
```

---

### Task 5: Interactive Application Orchestration

**Files:**
- Modify: `main.py`
- Modify: `tests/test_cli_workflow.py`
- Create: `tests/test_application.py`

**Interfaces:**
- Consumes: credential and workflow interfaces from Tasks 1-4.
- Produces: `select_run_mode(questionary_module=None) -> str | None` returning `"scheduled"`, `"ticketing"`, or `None`.
- Produces: `prompt_target_time(now, questionary_module=None) -> datetime | None`.
- Produces: `rematch_selected_courses(selected, refreshed) -> tuple[list[dict], list[dict]]` keyed strictly by stringified `suupNo`.
- Produces: `refresh_registration_context(credentials, attempts=3, interval=0.5) -> tuple[Session, dict, list[dict]]`.
- Produces: `run_application(load_authentication, fetch_context, select_courses, select_mode, select_target_time, run_countdown, refresh_context, attempt_course, wait_for_round) -> int` for dependency-injected orchestration tests. `load_authentication() -> tuple[dict[str, str], object]`; `fetch_context(session) -> tuple[dict, list[dict]]`; `refresh_context(credentials) -> tuple[object, dict, list[dict]]`.

- [ ] **Step 1: Write failing mode and safe-default tests**

```python
def test_mode_menu_defaults_to_scheduled(self):
    prompts = FakeQuestionary(select_answers=["scheduled"])
    self.assertEqual(select_run_mode(prompts), "scheduled")
    self.assertEqual(prompts.select_calls[0]["default"], "scheduled")

def test_cancelled_mode_prompt_sends_no_registration_requests(self):
    courses = [{"suupNo": "30012", "haksuNo": "COE8042", "gwamokNm": "확률과통계"}]
    exit_code = run_application(
        load_authentication=lambda: ({"user_id": "u", "password": "p"}, object()),
        fetch_context=lambda session: ({"tk": "token"}, courses),
        select_courses=lambda wishlist: courses,
        select_mode=lambda: None,
        select_target_time=lambda: self.fail("time prompt must not run"),
        run_countdown=lambda target: self.fail("countdown must not run"),
        refresh_context=lambda credentials: self.fail("refresh must not run"),
        attempt_course=lambda course, attempt: attempts.append((course, attempt)),
        wait_for_round=lambda: None,
    )
    self.assertEqual(exit_code, 1)
    self.assertEqual(attempts, [])
```

- [ ] **Step 2: Write failing scheduled refresh/rematch test**

```python
def test_scheduled_mode_refreshes_and_uses_new_course_payload(self):
    stale = {"suupNo": "30012", "marker": "stale"}
    fresh = {"suupNo": "30012", "marker": "fresh"}
    # Inject initial and refreshed sessions/lists; assert attempt receives fresh.

def test_scheduled_failures_enter_ticketing_immediately(self):
    # Scheduled outcomes: retry, success, retry.
    # Assert ticketing receives only the first and third course in priority order.
```

- [ ] **Step 3: Run application tests and verify RED**

Run: `venv/bin/python -m unittest tests.test_application tests.test_cli_workflow -v`

Expected: missing orchestration symbols.

- [ ] **Step 4: Implement credential prompt and startup**

Use `questionary.text("포털 ID")` and `questionary.password("포털 비밀번호")`. Build `{ "login_mode": "sso", "user_id": user_id.strip(), "password": password }` in memory. Connect `obtain_validated_credentials` to a validator that calls `create_session` and returns the authenticated session on success.

If `secrets.json` migrates, log only the path and deletion recommendation, never credential values. Remove the hard requirement for `config.json` from `load_config`/startup.

- [ ] **Step 5: Implement mode and time prompts**

The select choices are:

```python
[
    Choice("예약 수강신청 — 지정 시각 1회 시도 후 실패 과목 취케팅", value="scheduled"),
    Choice("바로 취케팅 — 성공할 때까지 무제한 순회", value="ticketing"),
]
```

Set `default="scheduled"`. The time prompt loops on `ScheduleValidationError` and never falls back to ticketing or immediate registration.

- [ ] **Step 6: Implement fresh scheduled context and orchestration**

Scheduled order:

```text
countdown -> fresh login (3 x 0.5s) -> fresh tokens -> fresh wishlist
-> rematch selected suupNo -> one scheduled pass -> ticketing(pending)
```

Direct ticketing order:

```text
initial authenticated session/tokens/wishlist -> ticketing(all selected)
```

Wrap every NetFunnel acquire/register operation so release stays in `finally`. Convert expected `requests.RequestException` and portal failures to `"retry"`. Print completed/pending summaries on normal completion and interruption.

- [ ] **Step 7: Run application and regression tests**

Run:

```bash
venv/bin/python -m unittest discover -s tests -v
venv/bin/python -m py_compile main.py credentials.py workflow.py
```

Expected: all pass and no real portal registration request occurs in tests.

- [ ] **Step 8: Commit Task 5**

```bash
git add main.py tests/test_application.py tests/test_cli_workflow.py
git commit -m "feat: add interactive registration modes"
```

---

### Task 6: Documentation, Migration UX, and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `architecture.md`
- Modify: `walkthrough.md`
- Modify: `config.json.example`
- Modify: `secrets.json.example`
- Modify: `.gitignore` only if a new repository-local legacy artifact needs exclusion.

**Interfaces:**
- Consumes the final CLI copy, paths, modes, and limits from Tasks 1-5.
- Produces user documentation with no obsolete manual setup path presented as normal operation.

- [ ] **Step 1: Rewrite setup and usage documentation**

Document:

```text
venv/bin/pip install -r requirements.txt
venv/bin/python main.py
```

Then explain first-run verified credential setup, hidden password input, automatic later login, `예약 수강신청`, `바로 취케팅`, countdown, one scheduled attempt per course, automatic failed-course transition, unlimited round robin, and `Ctrl+C` summary.

- [ ] **Step 2: Document security limitations and paths**

State that Fernet prevents plaintext disclosure and detects tampering, but an attacker who obtains both the local key and token can decrypt credentials. Give OS-appropriate locations through `platformdirs` rather than hard-coded project paths. Explain automatic `secrets.json` migration and manual deletion after the success notice.

- [ ] **Step 3: Remove obsolete examples**

Remove `courses`, `schedule`, and credential editing from normal `config.json.example`/README instructions. Mark `secrets.json.example` as legacy migration input or remove it if the migration test and docs no longer require distribution.

- [ ] **Step 4: Run fresh full verification**

Run:

```bash
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m pip check
venv/bin/python -m unittest discover -s tests -v
venv/bin/ruff check --ignore EXE001,DTZ005,DTZ007,BLE001,S110 main.py credentials.py workflow.py tests
venv/bin/python -m py_compile main.py credentials.py workflow.py tests/*.py
git diff --check
```

Expected: zero failures, lint errors, dependency errors, syntax errors, and whitespace errors.

- [ ] **Step 5: Run safe CLI smoke tests**

Using a temporary injected credential directory and fake portal callbacks, exercise:

1. First setup failure writes no files.
2. First setup success writes encrypted credentials.
3. Scheduled prompt/countdown reaches refresh without registration before target.
4. Direct ticketing renders selection and mode UI.

Do not send a real registration request. A real SSO login may be used only for the already-approved credential validation/migration flow, stopping at the mode menu.

- [ ] **Step 6: Commit Task 6**

```bash
git add README.md architecture.md walkthrough.md config.json.example secrets.json.example
git commit -m "docs: explain registration modes and credential setup"
```
