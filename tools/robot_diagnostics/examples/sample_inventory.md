# Sample Robot Inventory

This is fictitious demo data. It is safe to commit and does not describe real robots, customers, maps, IP addresses, tokens, or fleet IDs.

| robot_id | provider | fleet_robot_id_masked | configured_in_yaml | exists_in_inorbit | online | last_seen | location_tags | map_name | pose | battery | work_status | water | ws | validated | observations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| demo-allybot-1 | Allybot | demo-a...bot-1 | true | true | true | 2099-01-01T00:00:00Z | demo-location | Demo Map A | x=1.0; y=2.0; yaw=0.5 | 0.82 | Cleaning | fresh=70; sewage=10 | seen | full_flow_ok | Demo row only. |
| demo-keenon-1 | Keenon | demo-k...non-1 | true | false | false |  | demo-location | Demo Map B |  |  |  |  | skipped | pending_credentials | Demo credentials missing. |
| demo-autoxing-1 | AutoXing | demo-a...ing-1 | true | true | true | 2099-01-01T00:05:00Z | demo-location | Demo Area C | x=3.0; y=4.0; yaw=1.2 | 0.64 | Idle |  | skipped | inorbit_ok | Demo InOrbit-only row. |
