import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from lixu import config as configmod
from lixu import effects
from lixu.devices import create_device, govee, openrgb, wled
from lixu.devices.zenkabeat import DryRunKeyboard
from lixu.discovery import mdns
from lixu.discovery.scan import suggested_devices
from lixu.devices.base import Found
from lixu.engine import Engine
from lixu.gsi import StateStore, parse_state

LIVE = {"map": {"phase": "live"}, "round": {"phase": "live"},
        "player": {"team": "CT", "activity": "playing", "state": {"health": 50, "armor": 100}}}


class WledTest(unittest.TestCase):
    def test_drgb(self):
        pkts = wled.build_packets([(1, 2, 3), (4, 5, 6)], timeout_s=2)
        self.assertEqual(pkts, [bytes([2, 2, 1, 2, 3, 4, 5, 6])])

    def test_dnrgb_for_long_strips(self):
        colors = [(i % 256, 0, 0) for i in range(600)]
        pkts = wled.build_packets(colors)
        self.assertEqual(len(pkts), 2)
        self.assertEqual(pkts[0][:4], bytes([4, 2, 0, 0]))
        self.assertEqual(pkts[1][:4], bytes([4, 2, 489 >> 8, 489 & 0xFF]))
        self.assertEqual(len(pkts[0]) - 4 + len(pkts[1]) - 4, 1800)

    def test_udp_send(self):
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        rx.bind(("127.0.0.1", 0))
        rx.settimeout(2)
        dev = wled.WledDevice("127.0.0.1", led_count=3, port=rx.getsockname()[1])
        dev.send([(255, 0, 0)] * 3)
        self.assertEqual(rx.recv(100), bytes([2, 2, 255, 0, 0, 255, 0, 0, 255, 0, 0]))
        dev.close()
        rx.close()


class GoveeTest(unittest.TestCase):
    def test_color_message(self):
        msg = json.loads(govee.color_message((10, 20, 30)))
        self.assertEqual(msg["msg"]["cmd"], "colorwc")
        self.assertEqual(msg["msg"]["data"]["color"], {"r": 10, "g": 20, "b": 30})


def _ostr(s):
    raw = s.encode() + b"\x00"
    return struct.pack("<H", len(raw)) + raw


def fake_controller(ctype=0, name="ASUS ROG STRIX B550-F", leds=3):
    body = struct.pack("<i", ctype) + _ostr(name) + _ostr("ASUS Aura") + _ostr("1") + _ostr("") + _ostr("HID")
    body += struct.pack("<Hi", 1, 0)  # 1 mod, activ 0
    body += _ostr("Direct") + struct.pack("<9I", *([0] * 9)) + struct.pack("<H", 1) + struct.pack("<I", 0xFF)
    body += struct.pack("<H", 1) + _ostr("Aura Mainboard") + struct.pack("<iIII", 1, leds, leds, leds)
    body += struct.pack("<H", 0)  # fără matrice
    body += struct.pack("<H", leds) + b"".join(_ostr(f"LED {i}") + struct.pack("<I", i) for i in range(leds))
    body += struct.pack("<H", leds) + b"\x00" * 4 * leds
    return struct.pack("<I", 4 + len(body)) + body


class FakeOpenRGB(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.received = []

    def run(self):
        conn, _ = self.srv.accept()
        self.srv.close()
        with conn:
            while True:
                hdr = b""
                while len(hdr) < 16:
                    chunk = conn.recv(16 - len(hdr))
                    if not chunk:
                        return
                    hdr += chunk
                dev, pkt, size = struct.unpack("<III", hdr[4:])
                data = b""
                while len(data) < size:
                    data += conn.recv(size - len(data))
                self.received.append((dev, pkt, data))
                if pkt == openrgb.REQUEST_CONTROLLER_COUNT:
                    reply = struct.pack("<I", 1)
                elif pkt == openrgb.REQUEST_CONTROLLER_DATA:
                    # notificare asincronă înainte de răspuns: clientul trebuie s-o ignore
                    conn.sendall(b"ORGB" + struct.pack("<III", 0, openrgb.DEVICE_LIST_UPDATED, 0))
                    reply = fake_controller()
                else:
                    continue
                conn.sendall(b"ORGB" + struct.pack("<III", dev, pkt, len(reply)) + reply)


class OpenRGBTest(unittest.TestCase):
    def test_parse_controller(self):
        c = openrgb.parse_controller(0, fake_controller())
        self.assertEqual((c.type, c.name, c.leds), ("motherboard", "ASUS ROG STRIX B550-F", 3))
        self.assertEqual(c.zones, [("Aura Mainboard", 3)])

    def test_update_payload(self):
        p = openrgb.update_leds_payload([(1, 2, 3)])
        self.assertEqual(p, struct.pack("<IH", 10, 1) + bytes([1, 2, 3, 0]))

    def test_device_against_fake_server(self):
        srv = FakeOpenRGB()
        srv.start()
        dev = openrgb.OpenRGBDevice(port=srv.port, device_type="motherboard")
        self.assertEqual(dev.led_count, 3)
        dev.send([(9, 8, 7)] * 3)
        dev.close()
        srv.join(2)
        pkts = [p for _, p, _ in srv.received]
        self.assertEqual(pkts, [openrgb.SET_CLIENT_NAME, openrgb.REQUEST_CONTROLLER_COUNT,
                                openrgb.REQUEST_CONTROLLER_DATA, openrgb.SET_CUSTOM_MODE, openrgb.UPDATE_LEDS])
        self.assertEqual(srv.received[-1][2], openrgb.update_leds_payload([(9, 8, 7)] * 3))


class MdnsTest(unittest.TestCase):
    def test_parse_response(self):
        svc = "_wled._tcp.local."
        inst = "wled-birou." + svc
        hdr = struct.pack(">HHHHHH", 0, 0x8400, 0, 1, 0, 2)

        def rr(name, rtype, rdata):
            return mdns.encode_name(name) + struct.pack(">HHIH", rtype, 1, 120, len(rdata)) + rdata

        data = hdr + rr(svc, 12, mdns.encode_name(inst))
        data += rr(inst, 33, struct.pack(">HHH", 0, 0, 80) + mdns.encode_name("wled-birou.local."))
        data += rr("wled-birou.local.", 1, socket.inet_aton("192.168.1.42"))
        recs = mdns.parse_records(data)
        self.assertEqual(recs[0]["target"], inst)
        self.assertEqual(recs[1]["port"], 80)
        self.assertEqual(recs[2]["ip"], "192.168.1.42")

    def test_compressed_name(self):
        data = b"\x00" * 12 + mdns.encode_name("a.local.") + b"\x03foo\xc0\x0c"
        name, off = mdns.read_name(data, 12 + len(mdns.encode_name("a.local.")))
        self.assertEqual(name, "foo.a.local.")


class StripEffectsTest(unittest.TestCase):
    def test_all_effects_lengths(self):
        st = parse_state(LIVE, now=0)
        for name in effects.STRIP_EFFECTS:
            for n in (1, 5, 60):
                out = effects.strip(st, 0.0, n, name)
                self.assertEqual(len(out), n)
                self.assertTrue(all(isinstance(v, int) and 0 <= v <= 255 for c in out for v in c))

    def test_health_strip(self):
        out = effects.strip(parse_state(LIVE, now=0), 0.0, 10, "health")
        self.assertEqual(out[4], effects.to_rgb(effects.health_color(50)))
        self.assertEqual(out[5], (15, 0, 0))

    def test_unknown_effect(self):
        with self.assertRaises(ValueError):
            effects.strip(parse_state(LIVE, now=0), 0.0, 3, "disco")

    def test_animating(self):
        st = parse_state(LIVE, now=0)
        self.assertFalse(effects.is_animating(st, 0))
        self.assertTrue(effects.is_animating(None, 0))
        planted = parse_state(dict(LIVE, round={"phase": "live", "bomb": "planted"}), st, now=1)
        self.assertTrue(effects.is_animating(planted, 2))

    def test_keyboard_strip_mapping(self):
        kb = DryRunKeyboard()
        colors = kb.map_strip([(i, 0, 0) for i in range(21)])
        self.assertEqual(len(colors), 126)
        self.assertEqual(colors[1], (0, 0, 0))     # Esc, coloana 0
        self.assertEqual(colors[85], (14, 0, 0))   # Home, coloana 14


class EngineTest(unittest.TestCase):
    def test_tick_sends_only_on_change(self):
        store = StateStore()
        entries = [{"type": "zenkabeat"}, {"type": "wled", "leds": 12, "effect": "health"},
                   {"type": "govee"}, {"type": "logitech", "target": "mouse"},
                   {"type": "openrgb", "leds": 4, "brightness": 0.5}]
        eng = Engine(entries, store, dry_run=True)
        store.update(LIVE, now=0)
        eng.tick(100.0)
        devs = [o.device for o in eng.outputs]
        self.assertEqual([d.frames_sent for d in devs], [1, 1, 1, 1, 1])
        eng.tick(100.01)  # nimic schimbat, înainte de keepalive
        self.assertEqual([d.frames_sent for d in devs], [1, 1, 1, 1, 1])
        eng.tick(115.0)   # keepalive
        self.assertTrue(all(d.frames_sent == 2 for d in devs))
        self.assertEqual(devs[1].last_frame[4], effects.to_rgb(effects.health_color(50)))
        self.assertEqual(devs[4].last_frame[0], (0, 55, 128))  # CT (0,110,255) * 0.5

    def test_broken_device_does_not_stop_others(self):
        store = StateStore()
        eng = Engine([{"type": "nu-exista"}, {"type": "govee"}], store, dry_run=True)
        eng.tick(1.0)
        self.assertIsNone(eng.outputs[0].device)
        self.assertEqual(eng.outputs[1].device.frames_sent, 1)

    def test_static_state_sleeps_longer(self):
        store = StateStore()
        eng = Engine([{"type": "govee"}], store, dry_run=True)
        store.update(LIVE, now=0)
        eng.tick(10.0)
        self.assertGreaterEqual(eng.next_delay(10.0), 1.0)  # fără animație: doarme până la keepalive
        store.update(dict(LIVE, round={"phase": "live", "bomb": "planted"}), now=10)
        self.assertAlmostEqual(eng.next_delay(11.0), 1 / 30)

    def test_run_and_stop(self):
        store = StateStore()
        eng = Engine([{"type": "wled", "leds": 5}], store, dry_run=True)
        t = threading.Thread(target=eng.run)
        t.start()
        store.update(LIVE)
        time.sleep(0.3)
        eng.stop()
        t.join(2)
        self.assertFalse(t.is_alive())


class ConfigTest(unittest.TestCase):
    def test_roundtrip_and_disabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lixu.json"
            path.write_text(json.dumps({"gsi": {"port": 3456}, "fps": 20, "devices": [
                {"type": "wled", "host": "10.0.0.5"}, {"type": "govee", "host": "x", "enabled": False}]}))
            cfg = configmod.load(str(path))
            self.assertEqual((cfg.port, cfg.fps), (3456, 20.0))
            self.assertEqual([d["type"] for d in cfg.active_devices], ["wled"])
            self.assertEqual(len(cfg.devices), 2)
            configmod.save(cfg, path)
            self.assertEqual(configmod.load(str(path)).port, 3456)

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "lixu.example.json"
        cfg = configmod.load(str(example))
        for entry in cfg.devices:
            self.assertIsNotNone(create_device(entry, dry_run=True))

    def test_suggested_devices(self):
        results = [("x", [Found("wled", "a", config={"type": "wled", "host": "1.2.3.4", "leds": None}),
                          Found("motherboard", "b", controllable=False, config={"type": "openrgb"})], None)]
        self.assertEqual(suggested_devices(results), [{"type": "wled", "host": "1.2.3.4"}])


if __name__ == "__main__":
    unittest.main()
