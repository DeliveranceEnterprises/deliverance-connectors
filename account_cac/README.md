<!--
SPDX-FileCopyrightText: 2026 Deliverance Enterprises

SPDX-License-Identifier: MIT
-->

# Account-level InOrbit resources

The files in this folder are account-level InOrbit Configuration-as-Code
resources shared by all connectors in this repository, such as the global
Robot and Navigation dashboards. Each of them holds the common sections plus
one section per vendor, conditioned on that vendor's hardware tag.

- Apply them from this folder only. No connector keeps its own copy.
- Each vendor edits only its own section. Never remove or rewrite another
  vendor's section; the file is applied as a whole and overwrites the
  dashboard in InOrbit.
- `<ACCOUNT_ID>` is a placeholder for the InOrbit account id. Replace it when
  applying, for example:

  ```bash
  sed -e "s/<ACCOUNT_ID>/your-account-id/g" \
      account_cac/dashboard_robot.yaml > /tmp/robot.yaml
  yes | inorbit apply -f /tmp/robot.yaml
  ```

Vendor-specific resources (actions, data sources, status and incident
definitions, preferences) stay in each connector's own `cac/` folder.
