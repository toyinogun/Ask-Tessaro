# Verify: fictional company dataset · spec 0002 · updated 2026-10-08
_Steps derived from spec 0002 acceptance criteria. `/check verify` runs these; `/test` locks the durable ones._

## Commands
- [ ] `uv run tessaro-dataset validate --anchor 2026-10-07T10:00+02:00` → exit 0, "33 employees valid" → AC-1, AC-13
- [ ] `uv run tessaro-dataset validate --anchor 2026-10-10T10:00+02:00` (a Saturday) → exit 0 plus a weekend warning on stderr → AC-3
- [ ] `uv run tessaro-dataset validate --anchor 2026-10-07T18:00+02:00` → exit 0 plus the "after 17:30" warning → AC-3
- [ ] `TESSARO_DATASET_ANCHOR=2026-10-07T08:00:00+00:00 uv run tessaro-dataset validate` → the anchor prints as `2026-10-07T10:00:00+02:00` (UTC input converted to Amsterdam) → AC-3
- [ ] `uv run tessaro-dataset validate --anchor 2026-10-07T10:00` (no offset) → exit 2 → AC-13
- [ ] Copy `dataset/` and `bundles/` to a temp dir, set a team_id to `sales` and add a second `dutch_name` tag, run `validate --root <tmp>` → exit 1, both problems printed → AC-5, AC-6, AC-13
- [ ] `just dataset --anchor 2026-10-07T10:00+02:00` twice, `diff -r` the two `dataset/build/` outputs → identical; 11 files; `git status` shows nothing under `dataset/build/` → AC-7, AC-12, AC-13
- [ ] In `dataset/build/frappe_hr.json`: no `TES-01042`; Ruben (`TES-01007`) has `relieving_date: null`; Nina (`TES-01023`) is in `finance`, reports to `TES-01022` → AC-7, AC-16
- [ ] Rerun the export with `--include-demo-inputs` → `TES-01042` appears in `frappe_hr.json` and `openfga.tuples.yaml` → AC-7
- [ ] `directory.json` holds `TES-01042` even without the flag; Daan's forms include `de Wit` and `daan.dewit@tessaro.example` → AC-7
- [ ] `demo_actions.json` lists, in order: create TES-01042 (joining 2026-10-12, the next Monday), create TES-01043, set TES-01007 relieving date 2026-10-07, move TES-01023 to payments reporting to TES-01001 on 2026-10-14; `demo_only_ids` is the two joiners → AC-16
- [ ] `openfga.tuples.yaml`: Pieter's `stand_in` tuple on `team:payments` has `within_window` from `2026-10-05T09:00:00+02:00` to `2026-10-07T10:15:00+02:00`; rerun with `--stand-in-minutes 20` → ends at 10:20; no `lifecycle_case` objects → AC-2, AC-8
- [ ] `uv run tessaro-dataset standin --minutes 5` → one tuple whose window runs from now (to the minute) to now plus 5 minutes → AC-16
- [ ] `grep` every leave `reason` value from `dataset/leave.yaml` across `dataset/build/` → found only in `frappe_hr.json` → AC-10
- [ ] `erpnext.json`: every `payable_iban` starts `NL`, has `XTSR` at positions 5 to 8 and passes mod 97 → AC-11
- [ ] `authentik.json`: Maria has `managers` and `team-payments`; Pieter has `eng` but not `managers` or `prod-readonly`; the CEO has only `staff`; Sanne has `people-advisors` → AC-9
- [ ] `just check` → green, including the anchor sweep (20 anchors) and the 80% coverage gate → AC-13

## Value sourcing (vary the input, check the output)
- [ ] Anchor: no flag gives now in Amsterdam; `--anchor` wins over `TESSARO_DATASET_ANCHOR`
- [ ] Stand in end: `--stand-in-minutes` and `TESSARO_DATASET_STAND_IN_MINUTES` both move `valid_until`; `0` exits 2
- [ ] Allocation year: an anchor of 2026-12-31 gives allocations for 2026 and 2027; an anchor of 2027-01-01 gives 2027 and 2028
- [ ] Working days: anchor Friday 2026-10-09 and Saturday 2026-10-10 both put `@anchor+1wd` bookings on Monday 2026-10-12
- [ ] `@next_monday`: an anchor on Monday 2026-10-12 gives Lisa a joining date of 2026-10-19, not the same day
- [ ] Day expressions in timestamp fields: ticket articles with a `T` suffix keep it; Pieter's `valid_from` (no suffix) is 09:00
- [ ] Exact hours across daylight saving: anchor 2026-10-25T01:30+02:00, `@anchor+2h` is 02:30+01:00
- [ ] Email: tussenvoegsel joins without a space (`daan.dewit`, `bram.vandijk`)
- [ ] Reports to: a member reports to the team manager, a manager to the CEO, the CEO to no one
- [ ] Channels: the CEO is subscribed to `general` and `announcements` only (extra members); the leaver also gets `workplace`
- [ ] Balance: Noor's 2026 remaining equals 25 minus approved vacation working days in 2026, with the open request shown as 5 pending
- [ ] Zammad `latest_update` on T-1001 is the injected (visible) article's time, not the internal note's
- [ ] Snipe-IT stock: 7 laptops `ready_to_deploy` with no assignee (4 engineering, 3 office)
- [ ] BookStack: one book "Tessaro handbook", chapters from front matter, 20 pages
- [ ] Record order: every list in every export is sorted by its key

## Acceptance-criteria coverage
- AC-1 commands 1 · AC-2 tuples step, value sourcing · AC-3 commands 2 to 4 · AC-4 validate (minimums run on load), demo walk test · AC-5 broken copy · AC-6 broken copy · AC-7 frappe_hr, flag and directory steps · AC-8 tuples step · AC-9 authentik step · AC-10 reason grep · AC-11 IBAN step · AC-12 determinism diff · AC-13 just check, exit codes · AC-14 balance value step · AC-15 demo walk test in `just check` · AC-16 demo_actions and standin steps
