I need a python script, called `codex_account_switcher.py`

if not existing, create a `~\.codex-accounts` directory on the computer, this is where we save stuff. Make sure this works on Windows, like it uses `C:\Users\<username>\.codex-accounts` when running on windows

if `~\.codex-accounts` is empty but there exists a `~\.codex\auth.json` file, then read in `~\.codex\auth.json`, use the only token or first token, obtain the username through the OpenAI API. Save the JSON as `~\.codex-accounts\<sanitized_user_name>.json`. Inform the user this has happened, and finish, there's nothing to do as there's only one account.

if `~\.codex-accounts` is not empty, read `~\.codex\auth.json` if it exists. It has a `account_id` field somewhere inside that's a UUID that matches to an user account. Remember this.

Read all `*.json` files from `~\.codex-accounts`, see if there is an `account_id` match. If no match, then as before, create a copy of `~\.codex\auth.json` as `~\.codex-accounts\<sanitized_user_name>.json` (using the same method as before during the fresh start), mark the new file as the match. If there is a match by `account_id`, remember which one is matching. Continue on.

Print up to 9 entries from `~\.codex-accounts` (`*.json` files, without the directory path or extension) to the screen, sorted by last modified date, numbered 1 to 9. Indicate which one is the matching current one inside `~\.codex`. Allow the user to pick one with a keystroke.

Then simply overwrite the `~\.codex\auth.json` with the one selected.

if `~\.codex-accounts` is empty and there does not exists a `~\.codex\auth.json` file, print an error, as there's nothing to be done

with argparse, allow the user to also specify a specific file from `~\.codex-accounts`, it may or may not include `*.json`. If attempted to select, skip the keystroke selection process.
