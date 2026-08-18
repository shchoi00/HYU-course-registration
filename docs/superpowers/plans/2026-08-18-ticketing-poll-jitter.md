# Ticketing Poll Jitter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed 0.5-second ticketing poll delay with an independently sampled uniform 0.7–1.3-second delay while preserving all other behavior.

**Architecture:** Add one small injectable wait helper in `main.py` and wire it into the existing `run_application()` call. Keep `workflow.py`, authentication, capacity classification, NetFunnel, and registration untouched. Update only the affected README timing text.

**Tech Stack:** Python 3, standard-library `random` and `time`, `unittest`

---

### Task 1: Add and wire the randomized wait helper

**Files:**
- Modify: `tests/test_application.py`
- Modify: `main.py`

- [ ] **Step 1: Write the failing helper and wiring tests**

Add a test that injects a uniform function returning `0.94`, records the requested bounds, and records the sleep value. Assert bounds `(0.7, 1.3)` and sleep `[0.94]`. Extend the existing `TestMainWiring` assertion so `wait_for_round` is the new helper.

- [ ] **Step 2: Run the targeted tests to verify RED**

Run:

```bash
./venv/bin/python -m unittest tests.test_application.TestTicketingPollWait tests.test_application.TestMainWiring -v
```

Expected: FAIL because `wait_for_ticketing_poll` does not exist and main still passes the fixed lambda.

- [ ] **Step 3: Implement the minimal helper**

In `main.py`, import `random` and add:

```python
def wait_for_ticketing_poll(
    sleep_fn=time.sleep,
    uniform_fn=random.uniform,
):
    sleep_fn(uniform_fn(0.7, 1.3))
```

Pass `wait_for_ticketing_poll` as `wait_for_round` in `main()`.

- [ ] **Step 4: Run the targeted tests to verify GREEN**

Run the same targeted test command and expect both test classes to pass.

### Task 2: Align documentation and verify regressions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the three fixed 0.5-second descriptions**

Describe the interval as a fresh random `0.7~1.3초` wait per wishlist polling round, with an average of 1 second.

- [ ] **Step 2: Run full verification**

Run:

```bash
./venv/bin/python -m unittest discover -s tests -q
./venv/bin/python -m py_compile main.py workflow.py credentials.py
./venv/bin/ruff check main.py tests/test_application.py --ignore EXE001,DTZ005,DTZ007,BLE001,S110
git diff --check
```

Expected: all tests and checks pass with no behavior changes outside the wait helper and documentation.

- [ ] **Step 3: Review the final diff**

Confirm `workflow.py` and request logic are unchanged and that implementation edits are limited to `main.py`, `tests/test_application.py`, and `README.md`. Do not commit or push without an explicit request.
