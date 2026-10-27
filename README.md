# EchoMuse Hubitat Bridge

Experimental bidirectional integration between EchoMuse and Hubitat:

- Speak to EchoMuse to control selected Hubitat lights and switches.
- Let Hubitat send announcements to EchoMuse, without a wake word.

No Home Assistant required.

> Early alpha. This project is completely vibe coded. Expect bugs and test carefully. Announcement playback has worked in a manual Python API test on the developer's setup. The new Hubitat app/child-driver workflow still needs end-to-end verification.

## How it works

Voice commands:

```text
EchoMuse microphone -> Python bridge -> Whisper -> Hubitat app
-> configured LLM -> validated device command -> Piper -> EchoMuse speaker
```

Announcements:

```text
Hubitat automation -> EchoMuse Speaker child device -> parent app
-> authenticated Python API -> Piper -> EchoMuse speaker
```

Fixed announcements do not use the LLM.

## Features

### Voice control

- On/off commands for selected lights and switches.
- Explicit whole-number brightness percentages from 0 to 100.
- Multiple devices using the same action and brightness level.
- One configured default speaker room.
- Dry-run mode for testing device commands.
- Editable OpenAI-compatible API URL, model ID, and optional API key.

### Announcements

- Automatically created Hubitat speaker child device.
- Standard speech and notification commands for Hubitat automations.
- Bearer-token-authenticated announcement API.
- Up to 16 pending announcements, processed between voice conversations.
- Pending messages expire after 60 seconds.
- Messages limited to 240 characters and generated audio limited to 12 seconds.
- No automatic retry after dispatch.

> Dry-run mode only prevents device-control commands. Announcements still play aloud.

## Requirements

- Hubitat with access to Apps Code and Drivers Code.
- A working EchoMuse controller and compatible voice hardware.
- Linux with Docker Engine and Docker Compose.
- An OpenAI-compatible LLM reachable from the Hubitat hub.
- LAN connectivity from Hubitat to the Python bridge.
- Internet access for downloading images and speech models during setup.

The Compose stack runs Whisper, Piper, and the bridge. It does not install or configure the EchoMuse controller.

The bridge currently assumes these services share its Linux host/network namespace:

| Service | Address used by bridge |
| --- | --- |
| EchoMuse controller API | `127.0.0.1:16001` |
| Whisper | `127.0.0.1:10300` |
| Piper | `127.0.0.1:10200` |

The bridge uses Linux host networking. A separate ephemeral loopback HTTP server serves generated playback audio to the controller.

## Files

This guide assumes the Groovy files are at the repository root:

```text
README.md
compose.yaml
hubitat.example.json
.gitignore
EchoMuseBridge.groovy
EchoMuseSpeaker.groovy
bridge/
  voice_bridge.py
voice-runtime/
  Dockerfile
```

If the Groovy files are stored in a subfolder, use those files in the Hubitat installation steps below.

## 1. Install the child speaker driver

In Hubitat:

1. Open **Drivers Code**.
2. Select **New Driver**.
3. Paste `EchoMuseSpeaker.groovy`.
4. Save.

Do not manually create a virtual speaker. The parent app creates it after announcement settings are saved.

## 2. Install or update the Hubitat app

### New installation

1. Open **Apps Code** and select **New App**.
2. Paste `EchoMuseBridge.groovy` and save.
3. Enable OAuth in the app code's OAuth settings.
4. Open **Apps -> Add User App -> EchoMuse Bridge**.

### Existing installation

Back up your existing app code, then replace the contents of its existing Apps Code entry with the updated file and save.

Do not uninstall the app or create another instance just to update it. Keep the existing OAuth configuration.

### Voice settings

- Select only ordinary lights and switches appropriate for experimental control.
- Do not select locks, garage doors, alarm systems, security-related virtual switches, or hazardous equipment.
- Leave **Allow actual switching** off during initial testing.
- Set the default speaker room.
- Enter an LLM API base URL reachable from Hubitat, including `/v1`.
- Enter the exact model ID accepted by your server.
- Enter an API key if required.

Example URL and model ID, not universal defaults:

```text
http://192.168.1.50:8083/v1
qwen3-8b
```

The Hubitat hub calls the LLM directly. A Docker-only service hostname is not necessarily reachable from Hubitat.

The app displays a local base URL and access token for the Python bridge. Keep that token private.

## 3. Configure the Python bridge

On the Linux host, from the repository directory:

```bash
cp hubitat.example.json hubitat.json
nano hubitat.json
```

For an existing installation, edit the existing private file instead of overwriting it.

Generate a separate announcement secret:

```bash
openssl rand -hex 32
```

Configure:

```json
{
  "base_url": "http://HUBITAT-IP/apps/api/APP-ID",
  "access_token": "YOUR_HUBITAT_APP_TOKEN",
  "announcement_token": "YOUR_NEW_RANDOM_ANNOUNCEMENT_TOKEN",
  "announcement_bind": "0.0.0.0",
  "announcement_port": 18083
}
```

Use the app's displayed base URL. Do not append `/intent`, `/health`, or an access-token query string.

The two tokens have different purposes:

| Token | Used for |
| --- | --- |
| `access_token` | Python bridge requests to the Hubitat app |
| `announcement_token` | Hubitat requests to the Python announcement API |

Never commit `hubitat.json`.

Without an announcement token, the announcement API stays disabled. The default API bind address is loopback; use the explicit LAN-listening configuration above when Hubitat needs to connect.

`ECHOMUSE_ANNOUNCE_TOKEN`, when present in the bridge process environment, overrides the configured announcement token. `HUBITAT_CONFIG` can override the configuration-file path; the default is `/bridge/hubitat.json`.

## 4. Start the stack

The bridge service should build the included Dockerfile and mount the project directory:

```yaml
  bridge:
    build:
      context: .
      dockerfile: voice-runtime/Dockerfile
    image: echomuse-voice-bridge:local
    restart: unless-stopped
    network_mode: host
    init: true
    volumes:
      - ./:/bridge:ro
    entrypoint: ["python", "-u"]
    command: ["/bridge/bridge/voice_bridge.py"]
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

Keep the Whisper and Piper service definitions in `compose.yaml`.

With actual switching disabled in Hubitat:

```bash
docker compose up -d --build
docker compose logs --tail=100 -f bridge
```

The initial startup may take longer while images and speech models download.

## 5. Test voice commands in dry-run mode

Try:

- "Turn on the living room lights."
- "Set the living room lights to 25 percent."
- "Turn off the kitchen lights."

Confirm transcripts, target devices, actions, and brightness levels before enabling live control.

Dry-run still sends transcripts and the selected-device catalog to your configured LLM.

### Enable live control

1. Stop the bridge: `docker compose stop bridge`.
2. Enable **Allow actual switching** in Hubitat and save.
3. Change the bridge command to:

   ```yaml
   command: ["/bridge/bridge/voice_bridge.py", "--live"]
   ```

4. Run `docker compose up -d --force-recreate bridge`.

The bridge checks that its mode matches the Hubitat setting. To return to dry-run, reverse both settings while the bridge is stopped.

## 6. Configure the Hubitat speaker

Open the installed EchoMuse Bridge app and enable **Speaker announcements**.

| Setting | Value |
| --- | --- |
| Python bridge URL | `http://BRIDGE-LAN-IP:18083` |
| Announcement token | Same secret as `announcement_token` |
| Speaker device name | Your preferred label, such as `EchoMuse Speaker` |

Use the Linux host/container LAN address reachable from Hubitat. For a Proxmox LXC deployment, this is normally the container's address, not the Proxmox host's address.

Do not use `127.0.0.1`, `0.0.0.0`, or append `/announce`.

Click **Done** to save. The app creates the speaker child device.

Under **Devices**, open the speaker:

1. Click **Refresh** and check `bridgeStatus`.
2. Click **Test Announcement**.
3. Listen for the spoken test.

The app also has test/check buttons that use saved settings.

## 7. Create an announcement automation

In Hubitat's Notifications app or a compatible rule:

- Trigger: front-door contact opens.
- Output device: EchoMuse Speaker.
- Message: "The front door has opened."

The child driver supports `speak(text)` and `deviceNotification(text)`.

Per-message volume and voice arguments are currently ignored with a warning. Playback uses the existing controller volume and configured Piper voice.

## Announcement API

Both endpoints require:

```text
Authorization: Bearer YOUR_ANNOUNCEMENT_TOKEN
```

### POST /announce

```json
{"text":"The front door has opened."}
```

Only the `text` field is accepted.

Successful submission returns HTTP 202:

```json
{"ok":true,"queued":true,"id":"REQUEST_ID"}
```

This confirms queue acceptance, not audible playback. Check Python logs for completion or failure. There is currently no per-request playback-status endpoint or callback into Hubitat.

| HTTP status | Meaning |
| --- | --- |
| 400 | Invalid message/body |
| 401 | Invalid or missing token |
| 415 | Content type must be `application/json` |
| 429 | Queue full |
| 503 | Controller unavailable |

### GET /health

Reports API health, controller connection state, and pending queue length.

### Local test

On the Linux host/container running the bridge:

```bash
read -rsp "Announcement token: " ANNOUNCE_TOKEN
echo
curl -i http://127.0.0.1:18083/announce \
  -H "Authorization: Bearer $ANNOUNCE_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"text":"The front door has opened."}'
unset ANNOUNCE_TOKEN
```

## Speaker diagnostics

| Attribute | Meaning |
| --- | --- |
| `bridgeStatus` | Last connection-check result; use Refresh to update |
| `announcementStatus` | Latest submission result, not playback state |
| `lastAnnouncementError` | Last submission error |
| `lastRequestId` | Latest accepted request ID |

Disabling announcements in the app retains the child device but blocks new submissions from it. Already queued messages are not cancelled by this setting.

## Security and privacy

- Keep both tokens and `hubitat.json` private.
- Use a separate random announcement token.
- Restrict port 18083 to trusted LAN clients, ideally the Hubitat hub.
- Do not expose the API directly to the internet.
- The included HTTP server does not provide TLS. Bearer tokens are not encrypted over plain HTTP.
- Treat voice recognition and LLM interpretation as fallible.
- Logs can contain transcripts, device names, and command results. Redact before sharing.
- Whether LLM processing stays local depends on your configured server.

## Known limitations

- One controller connection and one default room per app instance.
- No per-announcement volume control, chime, or multi-speaker routing yet.
- Background speech or TV audio may interfere with voice recognition.
- Wake-word interruption during announcements still needs testing.
- Announcements wait while the voice loop is busy.
- Pending jobs are held in memory and lost on process restart.
- No automatic replay of failed announcements or device intents.
- Relative brightness changes and mixed-action requests are unsupported.
- Multi-device dispatch is not atomic and physical device state is not confirmed.
- The Groovy prompt appends `/no_think`; test compatibility with your model.
- Current image references use `latest` tags and are not reproducible pinned builds.
- Piper, protocol modules, and controller versions must be compatible.

## Troubleshooting

### No speaker child device

Install the EchoMuse Speaker driver first. Check the announcement settings, save the parent app with Done, and inspect Hubitat logs for creation errors.

### Unauthorized

Compare the app's announcement token with the Python configuration. Check for an environment-variable override.

### Bridge unreachable

Check the bridge LAN address, port, bind address, and firewall. Hubitat cannot reach the bridge through its own `127.0.0.1`.

### Queued but no sound

Check Python logs. A queued response is not playback confirmation. Messages can expire, exceed the generated-audio limit, or fail in synthesis/playback.

```bash
docker compose logs --since=5m --tail=100 bridge
docker compose logs --tail=100 piper
```

### Bridge reconnects repeatedly

Check the controller at `127.0.0.1:16001`, the Hubitat token, mode settings, and protocol compatibility. The bridge checks for announcement message types at startup when announcements are enabled.

### Invalid LLM response

Check the URL, model ID, API key, JSON-format behavior, and the app's request timeout. Invalid responses are rejected without dispatching their proposed commands.

## Updating

Back up the private configuration and working code first.

For a Python-file-only change with the project bind-mounted:

```bash
docker compose restart bridge
```

For Dockerfile/dependency changes:

```bash
docker compose up -d --build
```

For Compose configuration changes:

```bash
docker compose up -d --force-recreate bridge
```

Update the existing Hubitat driver and app code entries, then reopen the installed app and save with Done.

## Reporting issues

Include Hubitat, controller, Docker, and model versions; dry-run/live mode; expected and actual behavior; and redacted logs. For announcements, include the HTTP result, request ID, and relevant bridge log lines.

Never include tokens, API keys, or the private configuration.

## Contributions

Feedback, fixes, testing, and contributions are welcome. This is a learning project with very few brain cells involved. Please review changes before using them to control real devices.
