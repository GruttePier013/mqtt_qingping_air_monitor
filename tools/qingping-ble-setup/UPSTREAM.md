# Upstream

| | |
|---|---|
| Project | qingping: python tools for qingping air monitor |
| Source | https://github.com/bitrate16/qingping |
| Commit | `63f1f9eca24dfdd7046ad0832259b7fd96b6c147` (2025-08-07, "Update bluetooth.md") |
| PyPI | `qingping` 0.3 |
| Author | © 2025 bitrate16 |
| License | GNU Affero General Public License v3.0 or later ([LICENSE](LICENSE)) |

## Files

Everything in this folder is an **unmodified** copy of that commit, except:

| File | Origin |
|---|---|
| `README.md` | Written for this repository (the upstream README is kept as `README.upstream.md`, renamed only) |
| `UPSTREAM.md` | This file |
| `qingping_mac_helper.py` | Written for this repository (MIT), does not use upstream code |

The cross-platform tool in `tools/qingping-provision` and the integration's `ble_provision.py` are
independent MIT implementations of the protocol facts. They do not contain upstream code.

The AGPL applies to the upstream files. If you modify and distribute them, or offer them over a
network, you must make your modified source available under the AGPL.

To update:

```bash
git clone https://github.com/bitrate16/qingping /tmp/qp
cp -r /tmp/qp/qingping /tmp/qp/bluetooth.md /tmp/qp/pipeline.md /tmp/qp/setup.py \
      /tmp/qp/requirements.txt /tmp/qp/LICENSE tools/qingping-ble-setup/
cp /tmp/qp/README.md tools/qingping-ble-setup/README.upstream.md
# update the commit hash above
```
