# Robot Diagnostics

Read-only diagnostics and inventory tool for the Deliverance InOrbit connector repo.

The tool is intentionally conservative:

- It reads local connector YAML/env files.
- It can query manufacturer APIs using read-only endpoints.
- It can query InOrbit using `inorbit describe robots`.
- It does not run robot actions, navigation commands, tasks, `inorbit apply`, or `inorbit delete`.
- It masks fleet IDs and never prints full secrets. Files and the json/markdown output also leave out account identifiers (AutoXing `business_id`, Keenon `store_id`, Allybot `openid`) and vendor map and robot names.
- It only logs in to Allybot when you pass `--allow-login` (see below).
- Generated inventory outputs should go under `outputs/` in this directory, which is ignored by Git.

> **Allybot: use a dedicated account.** Allybot keeps one session per account,
> so logging in from this tool ends the session of every other consumer of the
> account: the running Allybot connector and the Deliverance Platform
> integration (`deliverance-integrations-allybot`). The live Allybot query is
> therefore skipped unless you pass `--allow-login` or set
> `ALLYBOT_DIAGNOSTICS_ALLOW_LOGIN=1`. Only do so with an account that no
> production service uses.

## Usage

From the repo root:

```bash
cd tools/robot_diagnostics
uv sync
uv run robot-diagnostics --provider all --all
# Live Allybot query, with a dedicated account only:
uv run robot-diagnostics --provider allybot --all --ws-seconds 10 --allow-login
```

InOrbit is queried with the `inorbit` CLI on `PATH` and the current
environment. Pass `--inorbit-workspace <dir>` to use `<dir>/.venv-inorbit/bin/inorbit`
with the variables of `<dir>/.env-inorbit` instead, or `--no-inorbit` to skip it.

Generate a real inventory under an ignored `outputs/` directory:

```bash
uv run robot-diagnostics \
  --provider allybot \
  --all \
  --markdown outputs/robot_inventory.md \
  --csv outputs/robot_inventory.csv \
  --json outputs/robot_inventory.json
```

The `outputs/` path is ignored because it may contain real robot names, robot IDs, map names, timestamps, and operational state. Do not commit real generated inventories. Use `examples/` for fictitious sample output that is safe to version.

Run the local test suite:

```bash
uv run pytest
```

Validation states:

- `yaml_only`: robot is configured locally, but no live source/InOrbit signal was checked or found.
- `pending_credentials`: required local credentials or IDs are missing/placeholders.
- `source_partial`: at least one read-only manufacturer signal was found, but not enough for a complete source check.
- `source_ok`: manufacturer read-only status and map checks succeeded.
- `inorbit_ok`: InOrbit sees the robot online, but source-side validation is not complete in this run.
- `full_flow_ok`: source-side read-only checks succeeded and InOrbit sees the robot online.
- `failed`: a required read-only step failed, such as authentication.

In short:

- `full_flow_ok` means the manufacturer source and InOrbit are aligned in this run.
- `source_partial` means the manufacturer source responded partially, but map, pose, or InOrbit visibility is missing.
- `inorbit_ok` means InOrbit sees the robot, even if the manufacturer source was not validated in this run.

Provider config: each provider reads `<connector>/config/my_fleet.local.yaml`,
or `<connector>/config/my_fleet.yaml` when there is no local copy, and the
matching `.env.local` or `.env` (for example `allybot_connector/config/my_fleet.yaml`
and `allybot_connector/config/.env`, relative to the repo root). A provider
without a fleet config is reported as not configured and skipped.

Keenon and AutoXing provider modules currently parse local configuration and mark missing credentials/placeholders clearly. Their API-specific read-only checks are intentionally incremental and can be expanded after real credentials are available.

## Safe Examples

- `examples/sample_inventory.md`
- `examples/sample_inventory.json`

The files under `examples/` must stay fictitious.
