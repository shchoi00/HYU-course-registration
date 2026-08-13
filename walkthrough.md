# Hanyang University Course Registration Automation - Walkthrough

## Implementation Summary

The automation now uses an interactive workflow with two execution modes and a validated credential migration path:

- **Credential onboarding with verification**: first-run `user_id` and hidden-password prompt is validated by real SSO login before any credential file is written.
- **Legacy `secrets.json` migration**: if a legacy file exists in the repository root, it is used only after successful validation and then stored into the encrypted local store.
- **Mode selection at launch**:
  - `예약 수강신청` (scheduled mode) with an arrow-key date/time picker, single-line countdown, and one-attempt-per-course behavior.
  - `바로 취케팅` (ticketing mode) for unlimited priority round-robin until all attempts succeed.
- **Failure handling**:
  - Scheduled failures move directly to ticketing.
  - Ticketing retries only failed courses in each round; successful courses are removed from later rounds.
  - `Ctrl+C` returns a completion/pending summary state.

## Architecture

- **Login**: Uses RSA-encrypted SSO login flow (`publicTk.do` + `lgnps.do`) and verifies via portal access.
- **Course discovery**: Loads wishlist entries from `/findHeemangSuupSearchs.do`.
- **Queueing**: NetFunnel handshake `5001 -> 5002` for each registration attempt.
- **Registration**: Sends `hyuHaksaengSgsc.do` with activated NetFunnel key.

## Current CLI Verification Flow

### Local verification commands

```bash
venv/bin/python -m unittest tests.test_credentials tests.test_workflow -v
venv/bin/python -m unittest tests.test_application tests.test_cli_workflow tests.test_course_selection -v
```

### Operational behavior assertions covered by tests

- First-run failed prompt path writes no credential artifacts.
- First-run success path writes encrypted credentials.
- Scheduled mode starts its picker at today's `09:00:00`, rejects past selections, and runs refresh/rematch before registration at the selected target.
- The countdown overwrites one terminal line and formats long waits with days instead of unbounded hours.
- Ticketing and scheduled summaries are reported on interruption (`Ctrl+C`).
- Scheduled mode transitions to ticketing immediately when pending items remain.

## Usage

1. Install dependencies in virtualenv:

   ```bash
   venv/bin/pip install -r requirements.txt
   ```

2. Run the CLI:

   ```bash
   venv/bin/python main.py
   ```

3. Follow the interactive sequence:
   - Login setup or reuse (first-run validated save)
   - Course selection and priorities
   - Mode choice (`예약 수강신청` / `바로 취케팅`)
   - If scheduled, choose the target with left/right and up/down arrows, press Enter, and wait

## Files

- `main.py`: Application orchestration and registration workflow.
- `credentials.py`: Encrypted credential store/migration helpers using `platformdirs`.
- `workflow.py`: Scheduled countdown and round-robin orchestration.
- `config.json`: Optional compatibility file (normal run path does not require manual editing).
- `secrets.json`: Legacy migration input only.
- `.gitignore`: Excludes legacy local files such as `secrets.json`.
