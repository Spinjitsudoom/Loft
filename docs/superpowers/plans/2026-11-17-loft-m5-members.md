# M5 Members Implementation Plan

> Executed inline (superpowers:executing-plans). Ledger: `.superpowers/sdd/2026-11-17-loft-m5-members/progress.md`.
> Branch `m5-downloads-members`. Spec: `docs/superpowers/specs/2026-11-16-loft-design.md` (People, M5).

**Goal:** members can ask to join, submit books for approval, request books with upvotes, discuss
each book without spoilers, and get notifications.

## Global constraints (from the spec)
- Members can't add books directly: submissions wait in the admin's approval queue; nothing shows
  for others until approved. A submission must have its details filled in (title and author).
- Spoilers: a message from further ahead than the viewer is blurred until they reach it; tap to
  reveal. Each message is stamped with where its writer was.
- Book files are never changed; submitted files wait in the data dir, never the books folder.
- Non-book files and passwords never show; members never see another member's drafts.
- Copy: plain words, sentence case, buttons name what happens.

## Calls (mine; recorded in the spec)
- Asking to join is off until the admin turns it on (Library settings → People). Pending requests
  carry a password hash; approve makes the account; decline deletes it. At most 20 waiting.
- Submitted drafts are marked in draft.json and never pruned while waiting; unsent drafts of
  members are pruned like the admin's. Drafts carry their owner; only the owner (or an admin, for
  submitted ones) can see or change them.
- Requests: requester votes automatically; one vote each; ranked by votes then age. Admin marks
  added (linking a book) or declines with a reason; requester and voters are told.
- Discussion: messages carry `position` (0..1, the writer's progress then) and a label ("Page 34",
  "12%"); written with no progress → position 0 (never blurred). Viewer finished → nothing blurred.
  One level of replies. Edit/delete own; admin deletes any; a deleted message with replies stays as
  "Message removed". Live: the open thread asks for new messages every 10 s.
- Notifications polled every 60 s and on each screen; opening the list marks them read.

## Tasks
1. **notifications.py** + table; `notify(con, user_ids, kind, text, link)`; list/unread count/
   mark read; routes GET /api/notifications, POST /api/notifications/read.
2. **joining.py**: setting `join_requests` in libsettings; table join_requests; `ask_to_join`,
   `pending`, `approve` (creates member), `decline`; routes; admins notified. Login page form;
   Library settings → People section with the switch and the waiting list.
3. **Submissions**: uploads open to members (owner in draft.json; owner checks); `submissions.py`
   (table; submit with required details → notify admins; list mine / pending; approve with the
   admin's details → uploads.save → notify; reject with reason → discard → notify). Prune skips
   submitted drafts. UI: Add page for members ("Send for approval"), "Your submissions" list;
   Approvals tab for admins (review card reusing detailFields/lookups).
4. **requests.py**: tables requests, request_votes; ask, vote/unvote, list ranked, delete own open,
   fulfil (book id) / decline (reason) with notifications. UI: Requests tab.
5. **discussion.py**: table messages; post (position from the writer's progress), list (with
   `ahead` flag for the viewer), edit, delete; reply notifications. UI: book page section and a
   reader panel; blur + tap to reveal; poll every 10 s while open.
6. **Bell**: top bar bell with unread count; notifications list page.

Each server task: tests first in tests/test_<module>.py (RED → GREEN), full suite after. UI tasks
verified in headless Chromium on the scratch server (:4548) with an admin and a member session.
