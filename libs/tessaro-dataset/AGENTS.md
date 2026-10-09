# tessaro-dataset

## Overview

The single source for the fictional Tessaro company. It loads the YAML in `dataset/` (people, leave, claims, tickets, devices, bookings, stand ins, channels, handbook pages) and the access bundles in `bundles/`, validates them, derives what is never stored, and exports one file per team system. Governing spec: [docs/specs/0002-fictional-company-dataset/index.md](../../docs/specs/0002-fictional-company-dataset/index.md).

## Stack

- Python 3.13, import name `tessaro_dataset` (src layout: `src/tessaro_dataset/`, `tests/`)
- Dependencies: pydantic, pydantic-settings, pyyaml
- Console script `tessaro-dataset` (`cli.py`), with settings from `TESSARO_DATASET_*` env vars (`ANCHOR`, `STAND_IN_MINUTES`)

## Commands

```bash
uv run tessaro-dataset validate --anchor 2026-10-07T10:00+02:00   # exit 0 ok, 1 dataset problems, 2 bad usage
uv run tessaro-dataset export --out <dir> [--include-demo-inputs] [--stand-in-minutes N]
uv run tessaro-dataset standin --minutes 5                        # a fresh stand in tuple from now
just dataset --anchor 2026-10-07T10:00+02:00                      # export to dataset/build/ (gitignored)
uv run pytest libs/tessaro-dataset/tests --cov=tessaro_dataset -q
```

## Layout

- `dates.py`: the `@anchor` date grammar (`+Nd`, `+Nwd`, `+Nh`, `@next_monday`, `@standin_end`, `@anchor_year`); all timestamps are `Europe/Amsterdam` aware
- `loader.py` reads the files, `assemble.py` resolves dates and builds models, `validate.py` and `minimums.py` collect problems, `derive.py` and `balances.py` compute derived values
- `models/`: frozen pydantic models by domain; `registry.py`: fixed names (groups, profiles, demo roles, `ALLOWED_RELATIONS`)
- `fgaload.py`: the Python half of `just authz-load`; checks the `fga store create` and `fga tuple write` JSON, then sets the store and model IDs in `.env` (`python -m tessaro_dataset.fgaload ids|env`)
- `exports/`: one module per target, each returning frozen `ExportRecord`s; `EXPORTERS` in `exports/__init__.py` lists them

## Conventions

- Dates in YAML are `@anchor` expressions, never fixed calendar dates, so the demo works on any day. Tests always pin the anchor.
- Validation collects every problem and raises one `DatasetError`; never stop at the first problem.
- Derived values (reports to, Authentik groups, Zulip channels, leave balances, IBANs) are computed, never written by hand in YAML.
- Mark a sensitive field with `Sensitive(...)` in its model; it may appear only in the `frappe_hr` export, and a test checks every other exporter.
- Demo input joiners stay out of every export except `directory` and `demo_actions` unless `include_demo_inputs=True`.
- Export output is deterministic: sorted keys, every list sorted by its key.
- `tests/test_real_dataset.py` and `tests/test_anchor_sweep.py` load the real `dataset/`, so a broken YAML edit fails CI.
- `ALLOWED_RELATIONS` and `CONDITIONED_RELATIONS` in `registry.py` must equal the directly assignable relations in `authz/model.fga`; `tests/test_fga_model.py` parses the model and fails on drift, so change both together. IT approvers export as `user:<id> it_approver org:tessaro` (`FGA_ORG`).
- Root `AGENTS.md` rules apply.

_Drafted by /sync from the introducing change, worth a quick human pass._
