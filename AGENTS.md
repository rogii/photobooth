# Photobooth repository instructions

Write and maintain all repository content in English, including documentation, comments, and user-facing text.

## Session startup

At the start of every new session, before parsing the user's task or doing any analysis, check for open pull requests. Update from `origin/main` only when the local workset is clean (there are no uncommitted tracked or untracked changes); if it is not clean, skip the update and report that it was skipped. Skip either step only when the user or higher-priority instructions explicitly say not to do it. If a step cannot be completed, report that and proceed only as appropriate; do not claim it was completed.

If fetching is blocked because the session cannot write Git metadata such as `.git/FETCH_HEAD`, request the required elevated filesystem access for the fetch and retry it if approved. This instruction records the required workflow but cannot itself change the session's sandbox permissions.

## Local deployment

For deployment tasks, consult `LAB_SETUP.local.md` if present.
