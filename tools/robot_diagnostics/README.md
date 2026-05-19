# Robot Diagnostics

Read-only diagnostics and inventory tool for the Deliverance InOrbit connector repo.

The tool is intentionally conservative:

- It reads local connector YAML/env files.
- It can query manufacturer APIs using read-only endpoints.
- It can query InOrbit using `inorbit describe robots`.
- It does not run robot actions, navigation commands, tasks, `inorbit apply`, or `inorbit delete`.
- It masks fleet IDs and never prints full secrets.
- Generated inventory outputs should go under repo-root `outputs/`, which is ignored by Git.

## Usage

From the repo root:

```bash
cd ~/INORBIT/deliverance-connectors
cd tools/robot_diagnostics
uv sync
uv run robot-diagnostics --provider allybot --all --ws-seconds 10
```

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
uv run python -m unittest discover -s tests
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

Provider config defaults:

- Allybot: `../../allybot_connector/config/my_fleet.local.yaml`, `../../allybot_connector/config/.env.local`
- Keenon: `../../keenon_connector/config/my_fleet.local.yaml`, `../../keenon_connector/config/.env.local`
- AutoXing: `../../autoxing_connector/config/my_fleet.local.yaml`, `../../autoxing_connector/config/.env.local`

Keenon and AutoXing provider modules currently parse local configuration and mark missing credentials/placeholders clearly. Their API-specific read-only checks are intentionally incremental and can be expanded after real credentials are available.

## Safe Examples And Reports

- `examples/sample_inventory.md`
- `examples/sample_inventory.json`
- `reports/allybot_validation_summary.md`

The files under `examples/` must stay fictitious. The report under `reports/` is sanitized for team review and must not include secrets, IP addresses, full fleet IDs, raw API responses, or WebSocket URLs.
