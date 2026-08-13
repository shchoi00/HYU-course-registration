Status: complete

Changes:
- Rewrote `README.md` to document exact execution commands, first-run hidden-password credential setup flow, real validation-before-save behavior, auto-reuse of verified credentials, mode menu semantics (`예약 수강신청`, `바로 취케팅`), countdown format/behavior, scheduled failure-to-ticketing handoff, unlimited round-robin ticketing, and `Ctrl+C` summary output.
- Added security limitations and platformdirs-based local credential storage paths in `README.md` (including key/token storage location strategy and decryption risk when both files are leaked).
- Documented credential migration/removal guidance and removed obsolete manual course/schedule instructions from setup docs.
- Updated `architecture.md` to match current production flow: interactive onboarding, mode selection, scheduled refresh/rematch, ticketing round robin, cancellation summary, and credential migration boundaries.
- Updated `walkthrough.md` to describe the implemented interactive UX, migration flow, and local verification strategy.
- Updated `config.json.example` and `secrets.json.example` to remove legacy operational fields from normal usage; kept `config.json.example` as minimal compatibility template and marked legacy migration role for `secrets.json.example`.

Commit:
- `c1eafb2` (`docs: explain registration modes and credential setup`)

Verification Summary:
- `venv/bin/python -m pip install -r requirements.txt` -> PASS
- `venv/bin/python -m pip check` -> PASS
- `venv/bin/python -m unittest discover -s tests -v` -> PASS (49 tests)
- `venv/bin/ruff check --ignore EXE001,DTZ005,DTZ007,BLE001,S110 main.py credentials.py workflow.py tests`
  - FAILED with existing lint findings (20 errors) in `credentials.py`, `main.py`, `workflow.py`, and test modules.
- `venv/bin/python -m py_compile main.py credentials.py workflow.py tests/*.py` -> PASS
- `git diff --check` -> PASS

Safe CLI smoke-path verification (fake callbacks / temporary credential dirs, no real portal calls):
- `venv/bin/python -m unittest tests.test_credentials.TestCredentialOnboarding.test_failed_prompted_login_saves_nothing tests.test_credentials.TestCredentialOnboarding.test_successful_prompted_login_is_saved tests.test_application.TestModeSelection.test_mode_menu_defaults_to_scheduled tests.test_application.TestScheduledApplication.test_scheduled_mode_refreshes_and_uses_new_course_payload tests.test_cli_workflow.TestInteractiveCourseSelection -v`
- Result: PASS (first-run failure writes no files, first-run success writes encrypted credentials, mode UI default behavior, scheduled refresh-before-registration path, selection/priority prompt path)

Concerns:
- `ruff` is installed as requested and command-level verification now runs, but the exact `ruff` command in Task 6 is not zero-clean due pre-existing findings not introduced in this task.
- Remaining recommended action: resolve or intentionally ignore the surfaced lint rules globally for this branch before claiming a fully green Task-6 lint gate.

---

Task 6 fix round 1 (this pass):
- Updated `README.md` wording: later runs now explicitly state that validated credentials are used to log in automatically.
- Added `ruff.toml` with:
  - `target-version = "py39"`
  - per-file ignores for deliberate naive datetime fixtures:
    - `tests/test_application.py`: `DTZ001`
    - `tests/test_workflow.py`: `DTZ001`
- Removed legacy/incorrect docs steps from this task scope by only updating required code/docs/examples.
- Fixed Ruff findings:
  - `main.py`: renamed unused unpacked variable `_tokens` to satisfy `RUF059`.
  - `workflow.py`: import order adjusted to satisfy `I001`.
  - `credentials.py`: retained `Optional[...]` typing on Python 3.9 by adding `from __future__ import annotations` and local `# noqa: UP045` on three `Optional` return annotations.
  - `tests/test_credentials.py`: combined nested context managers to satisfy `SIM117`.
  - `tests/test_application.py`, `tests/test_workflow.py`, `tests/test_cli_workflow.py`: normalized import/type import ordering.

Verification Commands (exact Task 6 requirements):
- `cd /Users/shchoi/workspace/HYU-course-registration/.worktrees/interactive-registration-modes && venv/bin/ruff check --ignore EXE001,DTZ005,DTZ007,BLE001,S110 main.py credentials.py workflow.py tests`
  - Result: `All checks passed!`
- `cd /Users/shchoi/workspace/HYU-course-registration/.worktrees/interactive-registration-modes && venv/bin/python -m pip check`
  - Result: `No broken requirements found.`
- `cd /Users/shchoi/workspace/HYU-course-registration/.worktrees/interactive-registration-modes && venv/bin/python -m unittest discover -s tests -v`
  - Result: `Ran 49 tests in 0.033s` and `OK`.
- `cd /Users/shchoi/workspace/HYU-course-registration/.worktrees/interactive-registration-modes && venv/bin/python -m py_compile main.py credentials.py workflow.py tests/*.py`
  - Result: exit 0 (no output).
- `cd /Users/shchoi/workspace/HYU-course-registration/.worktrees/interactive-registration-modes && git diff --check`
  - Result: no whitespace issues.

Commit:
- `e9dc9db` (`chore(task6): fix round 1 lint, ruff config, docs wording`)
