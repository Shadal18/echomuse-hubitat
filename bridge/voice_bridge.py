import io
import json
import socket
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
from esphome.vendor import api_pb2 as pb
from esphome.message_registry import encode, decode
from esphome.frame_protocol import encode_frame

with open("/bridge/hubitat.json") as f:
    config = json.load(f)

def hubitat(endpoint, body=None):
    url = config["base_url"] + "/" + endpoint + "?" + urlencode(
        {"access_token": config["access_token"]}
    )
    data = None if body is None else json.dumps(body).encode()
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Hubitat HTTP {error.code}") from None
    except Exception:
        raise RuntimeError("Hubitat request failed") from None

def exact(f, count):
    result = bytearray()
    while len(result) < count:
        chunk = f.read(count - len(result))
        if not chunk:
            raise RuntimeError("Connection closed")
        result.extend(chunk)
    return bytes(result)

def varint(f):
    value = 0
    for shift in range(0, 28, 7):
        byte = exact(f, 1)[0]
        value |= (byte & 127) << shift
        if byte < 128:
            return value
    raise RuntimeError("Invalid frame")

def receive(f):
    if exact(f, 1) != b"\x00":
        raise RuntimeError("Unexpected frame")
    size, kind = varint(f), varint(f)
    if size > 65535:
        raise RuntimeError("Oversized frame")
    return decode(kind, exact(f, size))

def send(s, message):
    s.sendall(encode_frame(*encode(message)))

def event(s, name, data=None):
    send(s, pb.VoiceAssistantEventResponse(
        event_type=getattr(pb, "VOICE_ASSISTANT_" + name),
        data=[{"name": k, "value": str(v)} for k, v in (data or {}).items()],
    ))

def wy_send(s, kind, data=None, payload=b""):
    header = {"type": kind}
    if data:
        header["data"] = data
    if payload:
        header["payload_length"] = len(payload)
    s.sendall(json.dumps(header).encode() + b"\n" + payload)

def wy_receive(f):
    line = f.readline(65536)
    if not line:
        raise RuntimeError("Speech service disconnected")
    header = json.loads(line)
    extra = header.get("data_length", 0)
    size = header.get("payload_length", 0)
    if not 0 <= extra <= 1048576 or not 0 <= size <= 1048576:
        raise RuntimeError("Oversized Wyoming event")
    data = dict(header.get("data") or {})
    if extra:
        data.update(json.loads(exact(f, extra)))
    payload = exact(f, size)
    if header["type"] == "error":
        raise RuntimeError("Speech service reported an error")
    return header["type"], data, payload

def transcribe(audio):
    with socket.create_connection(("127.0.0.1", 10300), timeout=20) as s:
        fmt = {"rate": 16000, "width": 2, "channels": 1}
        wy_send(s, "transcribe", {"language": "en"})
        wy_send(s, "audio-start", fmt)
        for offset in range(0, len(audio), 3200):
            wy_send(s, "audio-chunk", fmt, audio[offset:offset + 3200])
        wy_send(s, "audio-stop")
        with s.makefile("rb") as f:
            while True:
                kind, data, payload = wy_receive(f)
                if kind == "transcript":
                    return data.get("text", "").strip()

def synthesize(text):
    pcm = bytearray()
    fmt = None
    with socket.create_connection(("127.0.0.1", 10200), timeout=20) as s:
        wy_send(s, "synthesize", {"text": text})
        with s.makefile("rb") as f:
            while True:
                kind, data, payload = wy_receive(f)
                if kind == "audio-start":
                    fmt = data
                elif kind == "audio-chunk":
                    pcm.extend(payload)
                    if len(pcm) > 10000000:
                        raise RuntimeError("Reply audio exceeded test limit")
                elif kind == "audio-stop":
                    break
    if not fmt or not pcm:
        raise RuntimeError("Piper returned no audio")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(fmt["channels"])
        wav.setsampwidth(fmt["width"])
        wav.setframerate(fmt["rate"])
        wav.writeframes(pcm)
    duration = len(pcm) / (fmt["rate"] * fmt["width"] * fmt["channels"])
    return buffer.getvalue(), duration

audio_reply = b""
reply_path = "/reply.wav"
fetched = threading.Event()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != reply_path:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(audio_reply)))
        self.end_headers()
        self.wfile.write(audio_reply)
        fetched.set()

    def log_message(self, *args):
        pass


import queue
import sys
import webrtcvad

class TurnCancelled(Exception):
    pass

class ListeningTimeout(Exception):
    pass

class Controller:
    def __init__(self):
        self.socket = socket.create_connection(("127.0.0.1", 16001), timeout=10)
        self.file = self.socket.makefile("rb")
        self.lock = threading.Lock()
        self.messages = queue.Queue(maxsize=512)
        self.failed = threading.Event()
        self.closing = threading.Event()

        try:
            self.send(pb.HelloRequest(
                client_info="EchoMuse Hubitat voice bridge",
                api_version_major=1,
                api_version_minor=10,
            ))
            if not isinstance(receive(self.file), pb.HelloResponse):
                raise RuntimeError("Controller handshake failed")
            self.socket.settimeout(None)
            self.reader = threading.Thread(target=self.read_loop, daemon=True)
            self.reader.start()
            self.send(pb.MediaPlayerCommandRequest(
                has_volume=True, volume=0.85
            ))
            self.send(pb.SubscribeVoiceAssistantRequest(subscribe=True))
        except BaseException:
            self.close()
            raise

    def send(self, message):
        with self.lock:
            send(self.socket, message)

    def event(self, name, data=None):
        self.send(pb.VoiceAssistantEventResponse(
            event_type=getattr(pb, "VOICE_ASSISTANT_" + name),
            data=[
                {"name": k, "value": str(v)}
                for k, v in (data or {}).items()
            ],
        ))

    def read_loop(self):
        try:
            while not self.closing.is_set():
                message = receive(self.file)
                if isinstance(message, pb.PingRequest):
                    self.send(pb.PingResponse())
                elif isinstance(message, (
                    pb.VoiceAssistantRequest,
                    pb.VoiceAssistantAudio,
                )):
                    self.messages.put(message, timeout=1)
                elif isinstance(message, pb.DisconnectRequest):
                    raise RuntimeError("Controller requested disconnect")
        except Exception:
            if not self.closing.is_set():
                self.failed.set()

    def next(self, timeout=1):
        if self.failed.is_set():
            raise ConnectionError("Controller connection lost")
        return self.messages.get(timeout=timeout)

    def close(self):
        self.closing.set()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        if hasattr(self, "reader"):
            self.reader.join(timeout=2)
        try:
            self.file.close()
        except Exception:
            pass
        self.socket.close()

def record_command(controller):
    vad = webrtcvad.Vad(2)
    frame_bytes = 640  # 20 ms, 16 kHz, signed 16-bit mono
    pending = bytearray()
    audio = bytearray()
    speech_frames = 0
    silence_frames = 0
    voiced = False
    started = time.monotonic()

    print("Listening...", flush=True)

    try:
        while True:
            elapsed = time.monotonic() - started

            if elapsed >= 10:
                raise ListeningTimeout("No clean end of speech")

            if not voiced and elapsed >= 3:
                return b""

            try:
                message = controller.next(timeout=0.1)
            except queue.Empty:
                continue

            if isinstance(message, pb.VoiceAssistantRequest):
                if not message.start:
                    raise TurnCancelled()
                continue

            if not isinstance(message, pb.VoiceAssistantAudio):
                continue

            pending.extend(message.data)

            while len(pending) >= frame_bytes:
                frame = bytes(pending[:frame_bytes])
                del pending[:frame_bytes]
                audio.extend(frame)

                if len(audio) > 16000 * 2 * 8:
                    raise ListeningTimeout("Speech continued for over eight seconds")

                if vad.is_speech(frame, 16000):
                    speech_frames += 1
                    silence_frames = 0
                    if not voiced and speech_frames >= 3:
                        voiced = True
                        controller.event("STT_VAD_START")
                else:
                    if not voiced:
                        speech_frames = 0
                    else:
                        silence_frames += 1

                if voiced and silence_frames >= 25:
                    print("End of speech detected.", flush=True)
                    return bytes(audio)

            if message.end:
                return bytes(audio) if voiced else b""
    finally:
        controller.event("STT_VAD_END")

def speak(controller, server, text):
    global audio_reply, reply_path
    audio_reply, duration = synthesize(text)
    reply_path = f"/reply-{time.monotonic_ns()}.wav"
    fetched.clear()

    controller.event("TTS_START", {"text": text})
    controller.event("TTS_END", {
        "url": f"http://127.0.0.1:{server.server_port}{reply_path}"
    })
    controller.event("RUN_END")
    print("Reply:", text, flush=True)

    if not fetched.wait(10):
        raise RuntimeError("Controller did not fetch reply audio")

    # Wait for estimated playback, with no extra padding.
    time.sleep(duration)

def check_mode(live):
    dry_run = hubitat("health").get("dryRun")
    if live and dry_run is not False:
        raise RuntimeError("Enable actual switching in Hubitat for --live")
    if not live and dry_run is not True:
        raise RuntimeError("Disable actual switching in Hubitat for dry-run mode")

def serve_controller(controller, server, live):
    print("Connected. Mode:", "LIVE" if live else "DRY RUN", flush=True)

    while True:
        print("READY: say your wake word.", flush=True)

        while True:
            try:
                message = controller.next()
            except queue.Empty:
                continue

            if isinstance(message, pb.VoiceAssistantRequest) and message.start:
                break

        try:
            controller.event("RUN_START")
            controller.event("STT_START")

            audio = record_command(controller)

            if audio:
                text = transcribe(audio)
            else:
                text = ""

            print("Heard:", text or "(no speech)", flush=True)
            controller.event("STT_END", {"text": text})

            if text:
                # Re-check mode before each possible dispatch.
                check_mode(live)
                result = hubitat("intent", {"text": text})
                print("Hubitat:", json.dumps(result), flush=True)

                if result.get("executed") is True and not live:
                    raise RuntimeError("Unexpected execution in dry-run mode")

                reply = result.get("message") or "No response from Hubitat."
            else:
                reply = "I did not hear a command."

            controller.event("INTENT_END", {"continue_conversation": "0"})
            speak(controller, server, reply)

        except TurnCancelled:
            controller.event("ERROR", {
                "code": "cancelled",
                "message": "Voice turn cancelled",
            })
            controller.event("RUN_END")
            print("Voice turn cancelled.", flush=True)

        except ListeningTimeout as error:
            controller.event("ERROR", {
                "code": "listening_timeout",
                "message": "Could not detect a clean end to the command",
            })
            controller.event("RUN_END")
            print(f"Listening stopped: {error}. No command sent.", flush=True)

        except Exception:
            # Never automatically retry an intent: dispatch may have occurred.
            try:
                controller.event("ERROR", {
                    "code": "bridge_error",
                    "message": "Voice request failed",
                })
                controller.event("RUN_END")
            except Exception:
                pass
            raise

def main():
    live = "--live" in sys.argv[1:]
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(
        target=server.serve_forever, daemon=True
    ).start()

    try:
        while True:
            controller = None
            try:
                check_mode(live)
                controller = Controller()
                serve_controller(controller, server, live)
            except KeyboardInterrupt:
                break
            except Exception as error:
                print(
                    f"Bridge error: {error}. No intent will be retried automatically.",
                    flush=True,
                )
            finally:
                if controller is not None:
                    controller.close()

            print("Reconnecting in two seconds after an error...", flush=True)
            time.sleep(2)
    finally:
        server.shutdown()
        server.server_close()

if __name__ == "__main__":
    main()
