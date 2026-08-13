# Hanyang University Course Registration Automation - Walkthrough

## Implementation Summary

We have completed the implementation of the course registration automation script. The key technical challenge was the NetFunnel integration, which required a specific opcode sequence (5001 -> 5002) to acquire and activate a valid ticket.

## Architecture

- **Login**: Supports SSO login using RSA encryption (PKCS#1 v1.5) to `lgnps.do`.
- **Search**: Fetches course information using `findHeemangSuupSearchs.do`.
- **Queue**: Uses NetFunnel API to get a ticket (`opcode=5001`) and activate it (`opcode=5002`).
- **Registration**: Submits `hyuHaksaengSgsc.do` with the activated NetFunnel key and browser-mimicking headers (`sec-ch-ua`, etc.).

## Verification Results

- **Login**: ✅ Successful (RSS public key retrieval -> Encrypted Login -> Session established)
- **Token Extraction**: ✅ Extracted `tk` token from `sulg.do`.
- **Course Search**: ✅ Successfully retrieved course list (e.g., COE8042).
- **NetFunnel**: ✅ Successfully acquired and Activated key `54C26E85...`.
- **Registration**: ✅ Server responded with `[M77] 수강신청 기간이 아닙니다.`, confirming the request format and headers are correct and reached the business logic.

## How to Use

1. **Activate Virtual Environment**:

   ```bash
   source venv/bin/activate
   ```

2. **Configure credentials and runtime options**:
   - Put `user_id` and `password` in `secrets.json`.
   - Set `schedule` and `retry` options in `config.json` if needed.
   - Select wishlist courses and their priority interactively after launch.

3. **Run the Script**:
   ```bash
   python main.py
   ```

## Files

- `main.py`: Main automation script.
- `config.json`: User configuration.
- `.gitignore`: Excludes sensitive files and venv.
