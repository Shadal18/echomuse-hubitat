# EchoMuse Hubitat Bridge

Experimental local voice control for Hubitat using an EchoMuse controller, Whisper speech recognition, an OpenAI-compatible LLM server, and Piper speech synthesis.

No Home Assistant installation is required.

> Development alpha: expect installation changes and bugs. Start in dry-run mode and review the selected devices before enabling control.

## What it does

The voice pipeline is:

1. The EchoMuse controller supplies voice audio to the bridge.
2. The bridge detects the end of speech and sends audio to Whisper.
3. The bridge sends the transcribed request to the Hubitat app.
4. The Hubitat app asks your configured LLM to interpret the request.
5. The app validates the returned command against your selected devices.
6. In live mode, the app sends the command to Hubitat devices.
7. Piper generates the spoken response.

Supported commands:

- Turn selected switches and lights on or off.
- Set brightness to an explicit whole-number percentage.
- Control multiple selected devices with the same action.
- Use a configured default room for requests such as “turn off the lights.”

Examples:

- “Turn on the living room lights.”
- “Set the living room lights to 25 percent.”
- “Turn off the kitchen lights and hallway lights.”

Relative brightness changes, scheduled commands, and different actions for different devices in one request are not supported.

## Requirements

- A Hubitat hub with access to **Apps Code**.
- A working EchoMuse controller and compatible voice hardware.
- A Linux host with Docker Engine and Docker Compose.
- An OpenAI-compatible LLM server reachable from the Hubitat hub.
- Network access to download container images and speech models.

The current bridge assumes:

| Component               | Address used by the bridge |
| ----------------------- | -------------------------- |
| EchoMuse controller API | `127.0.0.1:16001`          |
| Whisper                 | `127.0.0.1:10300`          |
| Piper                   | `127.0.0.1:10200`          |

Run the bridge on the same Linux host/network namespace as the EchoMuse controller API.

> The included Compose file starts Whisper, Piper, and the voice bridge. It does not install or configure the EchoMuse controller itself.

## Repository layout

```text
.
├── .gitignore
├── README.md
├── compose.yaml
├── hubitat.example.json
├── EchoMuseBridge.groovy
├── bridge/
│   └── voice_bridge.py
└── voice-runtime/
    └── Dockerfile
```

`hubitat.json` is created during installation and must remain private.

## 1. Install the Hubitat app

`EchoMuseBridge.groovy` is a custom Hubitat app, not a device driver.

1. Open your Hubitat administration interface.
2. Navigate to **Apps Code**.
3. Select **New App**.
4. Paste the contents of `EchoMuseBridge.groovy`.
5. Save the app.
6. Open the app code's **OAuth** settings and enable OAuth.
7. Navigate to **Apps** → **Add User App**.
8. Select **EchoMuse Bridge**.

Configure the following settings:

### Allowed devices

Select only the ordinary lights and switches you want voice commands to control.

Do not select:

- Locks.
- Garage doors.
- Alarm systems.
- Security-related virtual switches.
- Switches controlling hazardous equipment.

Leave **Allow actual switching** turned off for initial testing.

### Speaker location

Enter the default room for the speaker.

Requests without an explicit room use this setting. The current app has one default room for all requests sent to that app instance.

Use clear device names that include room information where practical.

### LLM server URL

Enter the OpenAI-compatible API base URL, including `/v1`.

Example:

```text
http://192.168.1.50:8083/v1
```

Use your server's actual address and port.

The Hubitat hub makes this request directly. The URL must be reachable from Hubitat, not merely from inside a Docker network.

### Model ID

Enter the exact model ID accepted by your LLM server.

Example:

```text
qwen3-8b
```

This is an example, not a required model.

Enter an API key if your server requires one.

> OpenAI-compatible API support does not guarantee that every model will reliably follow the command format. Test your chosen model in dry-run mode.

### Bridge connection

The app displays:

- A local base URL.
- An access token.

Keep the access token private.

## 2. Configure the bridge

Download or clone this repository onto the Linux host running the EchoMuse controller.

From the repository directory, create your private configuration:

```bash
cp hubitat.example.json hubitat.json
nano hubitat.json
```

Replace the placeholders:

```json
{
  "base_url": "http://HUBITAT-IP/apps/api/APP-ID",
  "access_token": "YOUR_PRIVATE_ACCESS_TOKEN"
}
```

Use the local base URL and access token displayed by the Hubitat app.

The base URL should end with the app ID. Do not append `/intent`, `/health`, or an access-token query string.

Do not commit or share `hubitat.json`.

## 3. Build and start in dry-run mode

These instructions assume the Compose bridge service includes:

```yaml
build:
  context: .
  dockerfile: voice-runtime/Dockerfile
```

Its startup command should initially omit `--live`:

```yaml
command: ["/bridge/bridge/voice_bridge.py"]
```

Confirm **Allow actual switching** is off in the Hubitat app, then run:

```bash
docker compose up -d --build
```

Follow the bridge logs:

```bash
docker compose logs -f bridge
```

The initial startup may take longer while images and speech models download.

Once the bridge reports that it is ready, say your configured wake word and a supported command.

In dry-run mode, the app returns what it would do without sending the switching command.

Check that:

- The transcript matches what you said.
- The correct devices are selected.
- The action is correct.
- Any brightness percentage is preserved.
- Unclear or unsupported requests are rejected.

Dry-run mode still sends transcripts and selected-device information to your configured LLM server.

## 4. Enable live control

Only enable live mode after testing.

1. Stop the bridge:

   ```bash
   docker compose stop bridge
   ```

2. In the Hubitat app, turn on **Allow actual switching** and save the settings.

3. Change the bridge command in `compose.yaml` to:

   ```yaml
   command: ["/bridge/bridge/voice_bridge.py", "--live"]
   ```

4. Recreate the bridge service:

   ```bash
   docker compose up -d --force-recreate bridge
   ```

The bridge checks that its startup mode matches the Hubitat app's control setting. A mismatch prevents normal operation.

To return to dry-run mode, stop the bridge, disable actual switching in Hubitat, remove `--live`, and recreate the bridge service.

## Useful commands

Show service status:

```bash
docker compose ps
```

Follow all logs:

```bash
docker compose logs -f
```

Follow bridge logs:

```bash
docker compose logs -f bridge
```

Stop the stack:

```bash
docker compose down
```

Rebuild after changing the Dockerfile:

```bash
docker compose up -d --build
```

## Security and privacy

- Keep `hubitat.json` and access tokens private.
- Do not expose the controller, speech services, or Hubitat app endpoints directly to the internet.
- Select only devices appropriate for experimental voice control.
- Keep control disabled during initial testing.
- Review logs before sharing them; logs can contain transcripts, device names, and command results.
- Speech processing uses the configured Whisper and Piper services.
- Transcripts and the allowed-device catalog are sent to the configured LLM server. Whether that stays local depends on the server you configure.

The app validates returned device IDs, supported commands, and brightness values before dispatching commands. These checks do not guarantee that an LLM correctly understood your intent.

## Known limitations

- This is an experimental integration, not a production-ready voice assistant.
- The current bridge uses fixed local addresses for the controller, Whisper, and Piper.
- The bridge uses Linux host networking.
- One default speaker room is configured per app instance.
- Background speech or television audio may interfere with recognition.
- Device names and LLM behavior affect target matching.
- Relative brightness commands are not supported.
- Different actions or brightness levels for different devices in one request are not supported.
- Multi-device commands are not atomic: some commands may be sent before another fails.
- A sent command is not confirmation that a physical device reached the requested state.
- Failed intents are not automatically retried, because a command may already have been dispatched.
- The current Dockerfile and speech services use `latest` image tags; builds are not pinned to immutable versions.
- The Groovy prompt currently appends `/no_think` to the user message. Test behavior with your selected model.

## Troubleshooting

### Bridge repeatedly reconnects

Check:

- The EchoMuse controller is running.
- Its API is reachable at `127.0.0.1:16001` from the bridge.
- `hubitat.json` contains the correct base URL and token.
- The Hubitat app's control setting matches the presence or absence of `--live`.

View the logs:

```bash
docker compose logs --tail=100 bridge
```

### No valid LLM response

Check:

- The URL is reachable from the Hubitat hub.
- The API base URL includes `/v1`.
- The model ID matches your server configuration.
- Any required API key is set.
- The model returns the requested JSON without extra commentary.
- The server responds within the app's configured timeout.

The app rejects invalid LLM responses rather than dispatching their commands.

### Wrong devices are selected

Return to dry-run mode.

Review the allowed-device list, default room, and device names. Test the same request again before enabling live control.

### Reply audio fails

Check the Piper logs:

```bash
docker compose logs --tail=100 piper
```

Also check the bridge logs for synthesis or reply-fetch errors.

### Python reports missing ESPHome modules

The bridge imports protocol modules from the EchoMuse controller environment. Confirm that the base controller image provides:

```text
esphome.vendor.api_pb2
esphome.message_registry
esphome.frame_protocol
```

A dependency error here must be resolved before the bridge can run.

## Reporting issues

Include:

- Hubitat platform version.
- Linux and Docker versions.
- LLM server software and model ID.
- Whether dry-run or live mode was enabled.
- The request you spoke.
- Expected and actual behavior.
- Relevant redacted logs.

Never include access tokens, API keys, or your private `hubitat.json`.
