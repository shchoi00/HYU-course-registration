# Interactive Registration Modes Design

## Goal

Turn the script into a file-free interactive CLI for ordinary use. A user enters portal credentials only during first-time setup, chooses wishlist courses and priorities in the terminal, and starts either scheduled registration or cancellation-ticketing mode.

## Accepted User Flow

1. Load locally encrypted credentials.
2. If credentials do not exist or cannot be decrypted, prompt for portal ID and password with the password hidden.
3. Attempt a real SSO login before persisting anything. Save credentials only after login succeeds.
4. Log in, fetch the complete portal wishlist, select target courses, and assign priorities.
5. Choose one of two modes:
   - **Scheduled registration:** enter and validate a future local date/time, show a countdown, refresh the authenticated session at the target time, and attempt every selected course exactly once in priority order. Courses that do not succeed immediately enter cancellation-ticketing mode.
   - **Cancellation ticketing:** skip the timer and repeatedly attempt unfinished courses in priority order.
6. Cancellation ticketing removes successful or already-registered courses. It continues without an attempt limit until every course succeeds or the user presses `Ctrl+C`.

## Architecture

The current single-file script will be separated into focused modules while retaining `main.py` as the executable entry point:

- `credentials.py`: cross-platform storage paths, Fernet encryption/decryption, atomic writes, permission hardening, and first-time credential setup.
- `workflow.py`: mode selection, schedule validation/countdown, scheduled-to-ticketing state transition, and unlimited round-robin orchestration.
- `main.py`: portal HTTP operations and composition of credential, selection, and workflow components.

Pure workflow functions receive clocks, sleep functions, and attempt callbacks as parameters. This keeps scheduling and unlimited retry behavior deterministic in tests without contacting the portal.

## Credential Storage

Use `platformdirs` to select per-user locations on Windows, macOS, and Linux:

- Encryption key: user configuration directory, `credential.key`.
- Encrypted credential token: user data directory, `credentials.enc`.

Use `cryptography.fernet.Fernet` authenticated symmetric encryption. The encrypted payload is a versioned JSON object containing `user_id` and `password`. Writes use a temporary sibling file followed by `os.replace` so an interruption cannot leave a partially written credential file. On POSIX, directories are restricted to mode `0700` and files to `0600`; Windows receives the normal per-user application directories because POSIX mode bits are not an access-control mechanism there.

The generated key is stored locally because the user explicitly requires no OS keychain and no repeated master-password prompt. This protects credentials from casual plaintext disclosure but does not protect them if an attacker obtains both the key and encrypted token under the same user account. The UI and documentation state this limitation.

No credential is saved before a real SSO login succeeds. If setup login fails, temporary data is discarded and the current process returns to the credential prompt; `Ctrl+C` cancels setup. If decryption or payload validation fails later, the program reports the problem and runs setup again; it does not silently overwrite the old files before new credentials are validated.

The repository-local legacy `secrets.json` remains readable for one migration run. After its credentials successfully log in, the program stores them in the new encrypted location and tells the user to delete the legacy file. New setup never writes `secrets.json`.

## Modes and State Transitions

### Scheduled Registration

The CLI accepts `YYYY-MM-DD HH:MM:SS` in local system time and rejects invalid or non-future values. The countdown displays remaining `HH:MM:SS` without flooding scrollback.

Wishlist selection occurs before waiting. At the target time the program creates a fresh login session, extracts new tokens, fetches the wishlist again, and rematches selected courses by `suupNo`. A course missing from the refreshed wishlist is reported as unresolved and enters neither an invalid registration request nor a false success state.

Each resolved course receives exactly one registration attempt in priority order. Success and already-registered responses are complete. Every other result, including NetFunnel failure, `M77`, HTTP failure, and unsuccessful portal responses, transfers that course to cancellation ticketing.

### Cancellation Ticketing

Cancellation ticketing cycles over unfinished courses in stable priority order. Each course gets one attempt per round. Successful or already-registered courses are removed. All other results remain pending. A configurable interval defaults to 0.3 seconds between rounds, not between courses, preserving the agreed round-robin behavior.

The loop is intentionally unlimited. `Ctrl+C` exits cleanly with a summary of completed and unfinished courses. Each acquired NetFunnel key is released in a `finally` block, including on request errors or interruption.

## CLI Interaction

The startup CLI has no course or credential file-editing requirement:

1. First-time credential prompt when needed.
2. Wishlist checkbox.
3. Priority selection.
4. Mode menu with `예약 수강신청` as the safe default and `바로 취케팅` as the second option.
5. Scheduled mode time prompt and explicit summary before countdown.

Empty selections and cancelled prompts terminate without sending registration requests. Selecting immediate ticketing is an explicit action; missing or invalid configuration can never fall through to immediate registration.

## Error Handling

- Authentication failure during first setup: show failure, save nothing, and return to the credential prompt in the current process.
- Stored credential corruption: report and return to setup; preserve corrupt files until replacement credentials pass login validation.
- Session refresh failure at scheduled time: retry login up to three times at 0.5-second intervals while preserving the selected course list. If all three fail, report that no registration request was sent and exit nonzero; `Ctrl+C` remains available.
- Wishlist refresh mismatch: report the exact course name, code, and class number; skip malformed registration data.
- Transient portal/NetFunnel error: keep the course pending in ticketing mode.
- Unknown response: treat as unsuccessful, log its code/message, and keep pending.

## Tests

Tests will cover:

- encrypted round trip never stores plaintext ID/password;
- credential files use injected platform paths and atomic replacement;
- failed validation login writes no credentials;
- successful validation login saves and subsequent runs decrypt automatically;
- corrupt credentials re-enter setup without premature overwrite;
- schedule parsing rejects malformed and past times;
- scheduled mode performs exactly one prioritized attempt per course;
- only failed scheduled courses transition to cancellation ticketing;
- direct ticketing skips scheduled attempts;
- cancellation ticketing preserves round-robin order, removes successes, and has no attempt cap;
- `Ctrl+C` yields a clean completed/unfinished summary;
- target-time refresh rematches by `suupNo` and never uses stale course payloads;
- existing selection and response-classification behavior remains covered.

Network calls are replaced at the application boundary in unit tests. Existing portal parsing and matching functions continue to use complete representative response dictionaries.

## Documentation and Migration

Update `README.md`, `architecture.md`, examples, and dependency declarations. Documentation will explain the two modes, first-time credential validation, encrypted storage paths, the local-key security limitation, legacy `secrets.json` migration, schedule format, countdown behavior, unlimited cancellation ticketing, and `Ctrl+C` shutdown.

## Completion Criteria

- No manual credential, course, or schedule file editing is required for normal operation.
- First-time credentials are stored only after verified SSO success and are not stored as plaintext.
- Scheduled mode never sends requests before its validated target time.
- Scheduled failures immediately and automatically enter unlimited cancellation ticketing.
- Direct cancellation ticketing is selectable at startup.
- All automated tests, static checks, dependency checks, and a non-registering CLI smoke test pass.
