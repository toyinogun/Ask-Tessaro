# 0002. Fictional company dataset: rationale

## Context

Ask Tessaro is a public portfolio build on made up data. Every part of it needs the same fictional company: the in memory fakes behind the client protocols (spec 0001), the OpenFGA tuples and their CLI tests (feature 5), the tool policy tests (feature 6), the privacy proxy's directory recognizer and leak scan (feature 7), the six team systems seeded on the cluster (feature 11), the evaluation suites (feature 22) and the demo reset (feature 32). If each of these invents its own people and records, they disagree. A fake says Maria manages Payments while a tuple says she does not, and the tests prove nothing about the real chain.

The demo script (PRD 14.6) is time sensitive. A joiner starts "next Monday", the leaver's last day is "today", and a stand in must approve one joiner and then be refused once the window ends, in the same session. OpenFGA checks the stand in window against real time (tool servers pass `current_time`), so the window cannot be faked inside OpenFGA. Data with fixed dates is only correct on one day.

The data also carries the safety story. It holds a ticket with instructions aimed at the AI, a colleague on sick leave whose reason must never surface, and an employee with a Dutch name that generic name detectors miss. It also needs real looking personal data (emails, phones, addresses, IBANs) for the privacy proxy to mask. Because the repo is public, none of it may point at a real person, a real inbox or a real bank account.

Finally, the cluster is out of reach for now (scope cluster note). This feature must be fully buildable and testable on a laptop, and it must produce something the cluster seed jobs can use later without knowing yet exactly what each system's API expects.

## Options considered

### Option 1: Hand written YAML behind a typed library (chosen)

The company is written by hand as YAML files, one per entity kind, with dates as expressions relative to an anchor. A new `libs/tessaro-dataset` package validates the files into frozen pydantic models, derives what can be derived (groups, emails, balances), and exports typed records per system plus a CLI that writes them to a gitignored folder.

**Pros**:
- Every record is deliberate and reviewable in a pull request, which matters for traps and demo characters.
- One parser and one date resolver, shared by every consumer.
- Validation catches drift (dangling references, duplicate emails, a missing trap) in CI.
- Live dates without a fake clock.

**Cons**:
- Writing about 33 people and their records by hand takes real effort.
- A small date grammar to build, test and learn.
- One more workspace package to maintain.

### Option 2: Seeded generator (Faker)

Python code generates the company from a fixed random seed, with the demo characters and traps placed by hand in code.

**Pros**:
- Little typing; easy to grow to hundreds of people.
- Realistic variety in names and addresses for free.

**Cons**:
- The content is less deliberate; a library upgrade can change every generated value and quietly break tests that assert specific names or dates.
- Traps and demo characters still need hand placement, so the hard part is not saved.
- Harder to review: the data lives in code paths, not in readable records.

### Option 3: Plain YAML files, no library

The same YAML, but each consumer (fakes, tests, seed jobs) parses only what it needs.

**Pros**:
- No new package.
- Each consumer stays independent.

**Cons**:
- Parsing, date resolution and derivation are written several times and drift apart.
- No single place validates the whole company, so contradictions surface late, as confusing test failures.

### Option 4: Committed generated JSON per system

A script renders per system JSON once and the output is committed; consumers read the JSON.

**Pros**:
- Diffs of exactly what each system receives are visible in pull requests.
- Consumers need no YAML or date logic.

**Cons**:
- Committed output freezes the dates, which breaks the time sensitive demo.
- Two copies of the truth (source and output) that must be kept in sync.

## Rationale

The traps and the demo cast are the point of this dataset, and both need exact, deliberate content: a specific injected sentence, a specific medical note, a specific Dutch name, a joiner with a specific ID. A generator saves typing only for the background records, which are the cheap part, and makes the important part harder to review. At about 33 people, writing by hand is a few hours of work, and the result reads like a company in a pull request. Hand written YAML is the boring, reviewable choice.

Putting a library in front of the files follows from the number of consumers. At least seven features read this data. Without one loader they would each reimplement date resolution and derivation, and the first disagreement would show up as a puzzling failure in, say, the OpenFGA tests. A frozen, validated `Dataset` with exporters makes agreement structural, and the collecting validator in CI keeps the hand written files honest as they grow.

Relative dates are the only way the demo stays true without a fake clock. That matters most for the stand in, whose window OpenFGA checks against real time. Making the window end a set time after load (default 15 minutes) lets you show the approval and then the refusal in one session. Exports are typed records in each system's terms rather than guessed API payloads because the real APIs can only be proven on the cluster. Guessing Frappe or Snipe-IT field names now would bake in errors that the fakes would then hide.

Decisions made inside this spec, each with the runner up:
- Working days are Monday to Friday, with no holiday calendar: no dependency and fully predictable tests. Runner up: the `holidays` package for Dutch public holidays.
- Times on a day expression default to 09:00 local: office start, readable in the demo. Runner up: midnight, which reads oddly in workflow timers.
- `@next_monday` is strictly after the anchor date, so on a Monday it means the following Monday ("starting next Monday" never means today). Runner up: the same day when the anchor is a Monday.
- OpenFGA users are `user:<employee id>`: stable, unique and present in every system. Runner up: a username slug like the PRD example (`user:maria`), which can collide and changes when a name changes.
- Remaining leave deducts only approved applications, as Frappe HR does; open ones show as pending. Runner up: deducting open ones too, which would differ from what Frappe shows.
- The made up IBAN bank code is `XTSR`: valid checksums so Presidio's IBAN recognizer (which checks them) is really exercised, on a bank code no Dutch bank uses. Runner up: invalid checksums, which the recognizer would skip.
- Bundles stay in the existing root `bundles/` folder (PRD 9.5 treats them as IT and Security owned files) but load and validate with the dataset. Runner up: moving them under `dataset/`.
- Two offices (Amsterdam head office, Rotterdam) give bookings and bundles a real choice. Runner up: Amsterdam only.
- The stand in window is armed by its own command just before demo step 5, not at seed time, because demo steps 1 to 4 take longer than any sensible window. Runner up: a long default window, which never shows the refusal live.
- The leaver and mover are seeded in their "before" state and changed on camera through `demo_actions`, because Frappe HR fires the leaver and mover webhooks on an update, not on an insert. Runner up: seeding them already changed, which would either start their workflows during seeding or never start them.
- IBANs are derived from authored account numbers, because hand computing about 33 mod 97 checksums invites mistakes. Runner up: authored IBANs checked by a test.
- PyYAML stays, with strict pydantic types so YAML 1.1 surprises (`10:30` read as a number, `no` read as false) fail validation instead of slipping through. Runner up: `ruamel.yaml` in YAML 1.2 mode, a heavier dependency for the same protection.
- A sweep of about 20 anchors runs in CI, because a dataset written with relative dates can be valid on the pinned test anchor and broken on the day you demo. Runner up: only the pinned anchor, which is faster but hides that failure.
