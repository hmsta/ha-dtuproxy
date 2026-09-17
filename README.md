# DTU Proxy for Home Assistant

Local, read-only Home Assistant monitoring for the Hoymiles DTU Proxy firmware.
One config entry represents the proxy, its physical meter, and every gateway
client reported by the proxy.

## Features

- UI-based setup; YAML configuration is not required.
- Automatic client devices from the proxy's `/status.json` response.
- Automatic direct client monitoring from each proxy-reported `remote_ip`,
  validated by gateway ID.
- Configurable meter updates independent of DTU/cloud reporting.
- Per-field availability when power or energy cache blocks are stale.
- Proxy and client health, master state, cache, Wi-Fi, temperature, last-boot, reset, and
  memory diagnostics.
- Privacy-conscious diagnostics that redact endpoint addresses, network
  addresses, SSIDs, and credentials and omit raw Modbus frames.

The integration only performs HTTP `GET` requests. It does not call the
firmware configuration or OTA endpoints.

## Requirements

- Home Assistant 2026.7.4 or newer.
- A reachable DTU Proxy HTTP endpoint exposing `/status.json` and `/meter.json`.
- Reachable client HTTP endpoints exposing `/status.json` for client-local
  diagnostics.

The expected meter schema and units are documented in
[`tests/fixtures/meter.json`](tests/fixtures/meter.json):

- power: W
- voltage: centivolts, converted to V
- current: mA, converted to A
- power factor: thousandths, displayed as percent
- energy: Wh

Negative power and power-factor values are valid and are preserved.

## Installation with HACS

Until the repository is included in the default HACS catalog:

1. Open HACS in Home Assistant.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/hmsta/ha-dtuproxy` as an **Integration** repository.
4. Download **DTU Proxy**.
5. Restart Home Assistant.
6. Open **Settings → Devices & services → Add integration** and select
   **DTU Proxy**.

## Configuration

Enter the proxy host and HTTP port. Use a host or IP address only, without a URL
scheme or path.

After the proxy is validated, the integration reads the proxy's client list.
Every gateway ID becomes a Home Assistant device automatically. When a client
entry contains `remote_ip`, the integration contacts that address, verifies that
the returned gateway ID matches, and adds client-local diagnostics such as
temperature, firmware, last boot, reset reason, and free heap to the same device.
No client addresses need to be entered manually.

Use **Configure** on the integration entry to choose a meter update interval of
5, 10, 15, 30, or 60 seconds.

## Devices and entities

### Proxy

The proxy device includes fleet health, connected/healthy client counts, active
master, active-master DTU confirmation, network state, temperature, last boot,
cache state, heap, and reset reason. Only actionable health entities are enabled
by default; detailed network, cache, and memory diagnostics remain available but
disabled.

| Entity | Default | Sample value | Explanation |
| --- | --- | --- | --- |
| Fleet healthy | Enabled | `On` | Exactly one master exists and every client is connected, healthy, and cache-synchronized. |
| Active master DTU confirmed | Enabled | `On` | The currently selected master has confirmed local DTU traffic. |
| Connected clients | Enabled | `3` | Number of gateway clients currently connected to the proxy. |
| Active master | Enabled | `gw01` | Gateway ID of the authoritative master; history shows master changes and flip-flopping. |
| Internal temperature | Enabled | `47.2 °C` | Proxy internal-die temperature for thermal alerts. |
| Wi-Fi signal strength | Enabled | `-63 dBm` | Proxy Wi-Fi RSSI for weak-signal alerting; unavailable while the Wi-Fi station is disconnected. |
| Last boot | Enabled | `2026-09-16 08:42:17 UTC` | Stable timestamp derived from uptime; changes only after a device reboot. |
| Reset reason | Enabled | `Power on` | Firmware-reported reason for the most recent boot. |
| Healthy clients | Disabled | `3` | Healthy-client count; normally redundant with Fleet healthy. |
| Ethernet link | Disabled | `On` | Physical Ethernet link state for network troubleshooting. |
| Wi-Fi connected | Disabled | `Off` | Wi-Fi station connection state, primarily useful when diagnosing fallback networking. |
| Network transition | Disabled | `Off` | Indicates a short-lived firmware network transition window. |
| Cache entries | Disabled | `42` | Number of raw Modbus cache entries maintained by the proxy. |
| Cache generation | Disabled | `12893` | Current distributed-cache generation for protocol troubleshooting. |
| Free heap | Disabled | `153600 B` | Currently available firmware heap memory. |

### Clients

Each gateway ID becomes its own device. Proxy-observed entities include
connection, health, local DTU presence, cache synchronization, RSSI, and
transaction diagnostics. The authoritative active-master identity is exposed
once on the proxy instead of duplicating role entities on every client. Direct
HTTP endpoints discovered through `remote_ip` add client-local runtime
diagnostics.

Entities marked **Direct client** use the address reported by the proxy. They
become unavailable when `remote_ip` is absent, invalid, unreachable, or returns a
different gateway ID. The remaining entities come directly from the proxy's
client overview.

| Entity | Source | Default | Sample value | Explanation |
| --- | --- | --- | --- | --- |
| Connected | Proxy | Enabled | `On` | The client currently has a connection to the proxy. |
| Healthy | Proxy | Enabled | `On` | The client passes the proxy's liveness checks. |
| Cache synchronized | Proxy | Enabled | `On` | The client has committed the current meter cache and is eligible to serve it. |
| Local DTU presence | Proxy | Enabled | `present` | Whether this gateway has observed local DTU traffic. |
| Wi-Fi signal strength | Proxy | Enabled | `-61 dBm` | Client Wi-Fi RSSI for weak-signal alerting. |
| Internal temperature | Direct client | Enabled | `44.8 °C` | Client internal-die temperature for thermal alerts. |
| Last boot | Direct client | Enabled | `2026-09-16 09:13:04 UTC` | Stable timestamp that changes only after the client reboots. |
| Reset reason | Direct client | Enabled | `Watchdog` | Firmware-reported reason for the client's most recent boot. |
| Resynchronizing | Proxy | Disabled | `Off` | The client is rebuilding its cache after connecting or falling behind. |
| Cache acknowledgment age | Proxy | Disabled | `2.4 s` | Time since the proxy received the client's latest cache acknowledgment. |
| Prepare timeouts | Proxy | Disabled | `0` | Count of cache-transaction prepare timeouts. |
| Commit timeouts | Proxy | Disabled | `0` | Count of cache-transaction commit timeouts. |
| Master attempts | Proxy | Disabled | `3` | Number of master-election attempts recorded for the client. |
| Proxy receive age | Direct client | Disabled | `0.7 s` | Time since the client last received traffic from the proxy. |
| Free heap | Direct client | Disabled | `147456 B` | Currently available client firmware heap memory. |

Per-client role and master-confirmation entities are intentionally omitted. The
proxy's **Active master** and **Active master DTU confirmed** entities provide the
same information once, without duplicating it across every client device.

### Meter

The meter is represented as a separate device linked through the proxy. It
provides total and per-phase active power, voltage, current, power factor, and
import/export energy. All meter entities are enabled by default.

The values below are representative fixture values, not live installation data.
Negative power and power-factor values are valid.

| Entity | Default | Sample value | Explanation |
| --- | --- | --- | --- |
| Meter data available | Enabled | `On` | At least one decoded meter record is currently available. |
| Power data available | Enabled | `On` | The power, voltage, current, and power-factor cache block is available. |
| Energy data available | Enabled | `On` | The cumulative energy cache block is available. |
| Fault code | Enabled | `0` | Meter-reported fault code; zero indicates no reported fault. |
| Total active power | Enabled | `-20010 W` | Signed total three-phase active power. |
| Phase A active power | Enabled | `-5400 W` | Signed active power on phase A. |
| Phase B active power | Enabled | `-9120 W` | Signed active power on phase B. |
| Phase C active power | Enabled | `-5490 W` | Signed active power on phase C. |
| Phase A voltage | Enabled | `231.60 V` | RMS voltage on phase A. |
| Phase B voltage | Enabled | `230.00 V` | RMS voltage on phase B. |
| Phase C voltage | Enabled | `231.60 V` | RMS voltage on phase C. |
| Phase A current | Enabled | `25.200 A` | Current on phase A. |
| Phase B current | Enabled | `40.200 A` | Current on phase B. |
| Phase C current | Enabled | `25.800 A` | Current on phase C. |
| Total power factor | Enabled | `-95.1%` | Signed total power factor. |
| Phase A power factor | Enabled | `-92.2%` | Signed power factor on phase A. |
| Phase B power factor | Enabled | `-98.8%` | Signed power factor on phase B. |
| Phase C power factor | Enabled | `-92.0%` | Signed power factor on phase C. |
| Exported energy | Enabled | `9399000 Wh` | Total cumulative exported energy. |
| Imported energy | Enabled | `26427234 Wh` | Total cumulative consumed/imported energy. |
| Phase A exported energy | Enabled | `2772422 Wh` | Cumulative exported energy on phase A. |
| Phase B exported energy | Enabled | `3422016 Wh` | Cumulative exported energy on phase B. |
| Phase C exported energy | Enabled | `3204563 Wh` | Cumulative exported energy on phase C. |
| Phase A imported energy | Enabled | `9432234 Wh` | Cumulative consumed/imported energy on phase A. |
| Phase B imported energy | Enabled | `8869875 Wh` | Cumulative consumed/imported energy on phase B. |
| Phase C imported energy | Enabled | `8125125 Wh` | Cumulative consumed/imported energy on phase C. |

If one decoded cache block is stale, only entities from that block become
unavailable. An empty `meterData` array makes all meter measurement entities
unavailable without deleting them.

## Update intervals

- Meter data: 30 seconds by default; configurable to 5, 10, 15, 30, or 60 seconds
- Proxy and proxy-observed client status: 30 seconds
- Direct client diagnostics: 60 seconds

HTTP requests time out after 5 seconds. Proxy status and meter requests are
serialized so a new request is not sent to the proxy while another is still in
progress. Failed proxy requests use exponential backoff starting at the greater
of 30 seconds or the configured interval, capped at 5 minutes; a successful
request immediately restores the normal polling interval. Offline clients are
retried on their normal 60-second diagnostics cycle.

Home Assistant is used for monitoring rather than the proxy's real-time control
loop.

## Security and privacy

The current firmware serves HTTP on the local network. Keep the devices on a
trusted network and do not expose their web interfaces to the Internet.

No endpoint addresses or credentials are present in this repository. The proxy
address remains in Home Assistant's config entry storage; client addresses are
discovered at runtime. Both are redacted from integration diagnostics.

## Development

The repository follows the HACS integration layout:

```text
custom_components/dtu_proxy/
```

The validation workflow runs HACS validation and Home Assistant `hassfest` for
every push and pull request.

## License

[MIT](LICENSE)
