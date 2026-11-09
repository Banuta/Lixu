import json
import socket
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path

from aicolors import config as configmod
from aicolors import effects
from aicolors.devices import create_device, govee, openrgb, wled
from aicolors.devices.zenkabeat import DryRunKeyboard
from aicolors.discovery import mdns
from aicolors.discovery.scan import suggested_devices
from aicolors.devices.base import Found
from aicolors.engine import Engine
from aicolors.gsi import StateStore, parse_state

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


def fake_controller(ctype=0, name="ASUS ROG STRIX B550-F", leds=3, zones=None):
    zones = zones or [("Aura Mainboard", leds)]
    leds = sum(n for _, n in zones)
    body = struct.pack("<i", ctype) + _ostr(name) + _ostr("ASUS Aura") + _ostr("1") + _ostr("") + _ostr("HID")
    body += struct.pack("<Hi", 1, 0)  # 1 mod, activ 0
    body += _ostr("Direct") + struct.pack("<9I", *([0] * 9)) + struct.pack("<H", 1) + struct.pack("<I", 0xFF)
    body += struct.pack("<H", len(zones))
    for zname, zcount in zones:
        body += _ostr(zname) + struct.pack("<iIII", 1, zcount, 120, zcount) + struct.pack("<H", 0)  # fără matrice
    body += struct.pack("<H", leds) + b"".join(_ostr(f"LED {i}") + struct.pack("<I", i) for i in range(leds))
    body += struct.pack("<H", leds) + b"\x00" * 4 * leds
    return struct.pack("<I", 4 + len(body)) + body


class FakeOpenRGB(threading.Thread):
    def __init__(self, controllers=None):
        super().__init__(daemon=True)
        self.controllers = controllers or [fake_controller()]
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
                    reply = struct.pack("<I", len(self.controllers))
                elif pkt == openrgb.REQUEST_CONTROLLER_DATA:
                    # notificare asincronă înainte de răspuns: clientul trebuie s-o ignore
                    conn.sendall(b"ORGB" + struct.pack("<III", 0, openrgb.DEVICE_LIST_UPDATED, 0))
                    reply = self.controllers[dev]
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


class OpenRGBRamTest(unittest.TestCase):
    STICKS = [fake_controller(1, "Kingston Fury DDR4 RGB", 5), fake_controller(1, "Kingston Fury DDR4 RGB", 5),
              fake_controller(0, "ASRock B450M Pro4 R2.0", 3)]

    def test_all_sticks_as_one_device(self):
        srv = FakeOpenRGB(self.STICKS)
        srv.start()
        dev = openrgb.from_config({"type": "openrgb", "device_type": "dram", "port": srv.port})
        self.assertEqual((dev.led_count, len(dev.controllers)), (10, 2))
        self.assertIn("x2", dev.name)
        dev.send([(i, 0, 0) for i in range(10)])
        dev.close()
        srv.join(2)
        updates = [(d, data) for d, p, data in srv.received if p == openrgb.UPDATE_LEDS]
        self.assertEqual([d for d, _ in updates], [0, 1])
        self.assertEqual(updates[1][1], openrgb.update_leds_payload([(i, 0, 0) for i in range(5, 10)]))
        modes = [d for d, p, _ in srv.received if p == openrgb.SET_CUSTOM_MODE]
        self.assertEqual(modes, [0, 1])

    def test_discover_groups_ram(self):
        srv = FakeOpenRGB(self.STICKS)
        srv.start()
        found = openrgb.discover(port=srv.port)
        srv.join(2)
        self.assertEqual(found[0].kind, "openrgb:dram")
        self.assertIn("x2", found[0].name)
        self.assertEqual(found[0].config["device_type"], "dram")
        self.assertTrue(found[0].config["all"])
        self.assertEqual(found[1].config["device_type"], "motherboard")


class OpenRGBZoneTest(unittest.TestCase):
    BOARD = [fake_controller(0, "B550M AORUS ELITE", zones=[("Motherboard", 0), ("D_LED1 Bottom", 30),
                                                             ("D_LED2 Top", 20)])]

    def test_zone_device_sends_only_its_zone(self):
        srv = FakeOpenRGB(self.BOARD)
        srv.start()
        dev = openrgb.from_config({"type": "openrgb", "match": "B550M AORUS ELITE", "zone": "D_LED2",
                                   "port": srv.port})
        self.assertEqual((dev.led_count, dev.zone, dev.name), (20, 2, "B550M AORUS ELITE - D_LED2 Top"))
        dev.send([(1, 2, 3)] * 20)
        dev.close()
        srv.join(2)
        last = srv.received[-1]
        self.assertEqual(last[1], openrgb.UPDATE_ZONE_LEDS)
        self.assertEqual(last[2], openrgb.update_zone_payload(2, [(1, 2, 3)] * 20))
        self.assertEqual(struct.unpack("<IiH", last[2][:10]), (10 + 80, 2, 20))

    def test_empty_or_unknown_zone(self):
        from aicolors.devices.base import DeviceError

        for zone in ("Motherboard", "D_LED9"):
            srv = FakeOpenRGB(self.BOARD)
            srv.start()
            with self.assertRaises(DeviceError) as ctx:
                openrgb.from_config({"type": "openrgb", "match": "AORUS", "zone": zone, "port": srv.port})
            srv.join(2)
            self.assertTrue("Resize" in str(ctx.exception) or "D_LED1" in str(ctx.exception))

    def test_scan_lists_zones(self):
        srv = FakeOpenRGB(self.BOARD)
        srv.start()
        found = openrgb.discover(port=srv.port)
        srv.join(2)
        names = [f.name for f in found]
        self.assertIn("B550M AORUS ELITE - D_LED1 Bottom", names)
        z2 = next(f for f in found if f.name.endswith("D_LED2 Top"))
        self.assertEqual(z2.config["zone"], "D_LED2 Top")
        z0 = next(f for f in found if f.name.endswith("Motherboard"))
        self.assertFalse(z0.controllable)


class MemoryDiscoveryTest(unittest.TestCase):
    def test_kingston_fury(self):
        from aicolors.discovery import memory

        mods = memory.parse_modules(json.dumps([
            {"DeviceLocator": "DIMM 0", "Manufacturer": "Kingston", "PartNumber": "KF436C17BBA/8 ",
             "Capacity": 8589934592, "ConfiguredClockSpeed": 3600},
            {"DeviceLocator": "DIMM 1", "Manufacturer": "Kingston", "PartNumber": "KF436C17BBA/8 ",
             "Capacity": 8589934592, "ConfiguredClockSpeed": 3600}]))
        f = memory.describe(mods)[0]
        self.assertIn("Kingston FURY KF436C17BBA/8", f.name)
        self.assertIn("16 GB, 3600 MT/s, RGB", f.details)
        self.assertTrue(any("OpenRGB" in n for n in f.notes))
        self.assertEqual(memory.parse_modules('{"PartNumber": "X"}'), [{"PartNumber": "X"}])
        self.assertEqual(memory.describe([]), [])


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
            path = Path(tmp) / "aicolors.json"
            path.write_text(json.dumps({"gsi": {"port": 3456}, "fps": 20, "devices": [
                {"type": "wled", "host": "10.0.0.5"}, {"type": "govee", "host": "x", "enabled": False}]}))
            cfg = configmod.load(str(path))
            self.assertEqual((cfg.port, cfg.fps), (3456, 20.0))
            self.assertEqual([d["type"] for d in cfg.active_devices], ["wled"])
            self.assertEqual(len(cfg.devices), 2)
            configmod.save(cfg, path)
            self.assertEqual(configmod.load(str(path)).port, 3456)

    def test_example_config_is_valid(self):
        example = Path(__file__).resolve().parent.parent / "aicolors.example.json"
        cfg = configmod.load(str(example))
        for entry in cfg.devices:
            self.assertIsNotNone(create_device(entry, dry_run=True))

    def test_suggested_devices(self):
        results = [("x", [Found("wled", "a", config={"type": "wled", "host": "1.2.3.4", "leds": None}),
                          Found("motherboard", "b", controllable=False, config={"type": "openrgb"})], None)]
        self.assertEqual(suggested_devices(results), [{"type": "wled", "host": "1.2.3.4"}])


if __name__ == "__main__":
    unittest.main()


class FakeModeWriter:
    def __init__(self, mode=2):
        self.mode = mode
        self.calls = []
        self.closed = False

    def current(self):
        return self.mode

    def set_mode(self, value):
        self.calls.append(value)
        self.mode = value
        return True

    def close(self):
        self.closed = True


class ZenkabeatModesTest(unittest.TestCase):
    def test_scene(self):
        self.assertEqual(effects.scene(None, 0), "menu")
        st = parse_state(LIVE, now=0)
        self.assertEqual(effects.scene(st, 0), "ct")
        bomb = parse_state(dict(LIVE, round={"phase": "live", "bomb": "planted"}), st, now=1)
        self.assertEqual(effects.scene(bomb, 2), "bomb")
        low = dict(LIVE, player=dict(LIVE["player"], state={"health": 10}))
        self.assertEqual(effects.scene(parse_state(low, now=0), 0), "low_hp")
        dead = dict(LIVE, player=dict(LIVE["player"], state={"health": 0}))
        self.assertEqual(effects.scene(parse_state(dead, now=0), 0), "dead")

    def test_device_writes_only_on_scene_change_and_restores(self):
        from aicolors.devices.zenkabeat import ZenkabeatModeKeyboard

        w = FakeModeWriter(mode=2)
        dev = ZenkabeatModeKeyboard({"ct": 1, "bomb": 4, "dead": ""}, writer=w)
        dev.send(["menu"])            # efectul tău -> nicio scriere
        dev.send(["ct"])
        dev.send(["ct"])
        dev.send(["dead"])            # gol = efectul tău
        dev.send(["bomb"])
        dev.preview(7)
        dev.preview(None)
        dev.send(["bomb"])
        dev.close()
        self.assertEqual(w.calls, [1, 2, 4, 7, 2, 4, 2])
        self.assertTrue(w.closed)

    def test_engine_scene_and_rate_limit(self):
        from aicolors.devices.zenkabeat import ZenkabeatModeKeyboard

        w = FakeModeWriter(mode=2)
        store = StateStore()
        eng = Engine([], store)
        out = __import__("aicolors.engine", fromlist=["Output"]).Output({"type": "zenkabeat"})
        out.device = ZenkabeatModeKeyboard({"ct": 1, "bomb": 4}, writer=w)
        eng.outputs = [out]
        store.update(LIVE, now=0)
        eng.tick(100.0)
        self.assertEqual(w.calls, [1])
        store.update(dict(LIVE, round={"phase": "live", "bomb": "planted"}), now=100)
        eng.tick(101.0)                       # sub 3 s de la ultima scriere -> așteaptă
        self.assertEqual(w.calls, [1])
        eng.tick(103.5)
        self.assertEqual(w.calls, [1, 4])
        snap = eng.snapshot()[0]
        self.assertEqual((snap["scene"], snap["mode"], snap["original_mode"], snap["colors"]), ("bomb", 4, 2, []))
        self.assertEqual(eng.keyboard_preview(9)["mode"], 9)
        eng.reconfigure([{"type": "zenkabeat", "modes": {"ct": 3}}])
        self.assertEqual(out.device.modes, {"ct": 3})


class GoveeSegmentsTest(unittest.TestCase):
    def test_razer_packets(self):
        import base64

        on = json.loads(govee.razer_enable(True))["msg"]
        self.assertEqual(on, {"cmd": "razer", "data": {"pt": "uwABsQEK"}})
        self.assertEqual(json.loads(govee.razer_enable(False))["msg"]["data"]["pt"], "uwABsQAL")
        raw = base64.b64decode(json.loads(govee.razer_frame([(255, 0, 0), (0, 0, 255)]))["msg"]["data"]["pt"])
        self.assertEqual(raw[:6], bytes((0xBB, 0x00, 8, 0xB0, 0x01, 2)))  # 0x01 = segmente separate
        grad = base64.b64decode(json.loads(govee.razer_frame([(1, 1, 1)], gradient=True))["msg"]["data"]["pt"])
        self.assertEqual(grad[4], 0x00)
        self.assertEqual(raw[6:12], bytes((255, 0, 0, 0, 0, 255)))
        x = 0
        for b in raw[:-1]:
            x ^= b
        self.assertEqual(raw[-1], x)

    def test_groups(self):
        out = govee.expand_groups([(1, 1, 1), (2, 2, 2)], [[0, 2], [3]], 5)
        self.assertEqual(out, [(1, 1, 1), (0, 0, 0), (1, 1, 1), (2, 2, 2), (0, 0, 0)])

    def _rx(self, n):
        socks = []
        for _ in range(n):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", 0))
            s.settimeout(2)
            socks.append(s)
        return socks

    def test_device_segments_and_hosts(self):
        rx = self._rx(2)
        orig = govee.CONTROL_PORT
        try:
            # două „dispozitive” pe porturi diferite: trimitem direct la adresele lor
            dev = govee.GoveeDevice(hosts=["127.0.0.1", "127.0.0.1"], segments=4, groups=[[0, 1], [2, 3]])
            dev.addresses = [s.getsockname() for s in rx]
            self.assertEqual(dev.led_count, 2)
            dev.send([(9, 0, 0), (0, 9, 0)])
            dev.close()
            for s in rx:
                msgs = []
                while True:
                    try:
                        msgs.append(json.loads(s.recv(4096))["msg"])
                    except socket.timeout:
                        break
                    if len(msgs) == 3:
                        break
                self.assertEqual([m["cmd"] for m in msgs], ["razer", "razer", "razer"])
        finally:
            govee.CONTROL_PORT = orig
            for s in rx:
                s.close()

    def test_validation_and_config(self):
        from aicolors.devices.base import DeviceError

        with self.assertRaises(DeviceError):
            govee.GoveeDevice("1.2.3.4", groups=[[0]])          # groups fără segments
        with self.assertRaises(DeviceError):
            govee.GoveeDevice("1.2.3.4", segments=3, groups=[[5]])
        with self.assertRaises(DeviceError):
            govee.GoveeDevice()
        d = create_device({"type": "govee", "host": "x", "segments": 15, "groups": [[0], [1], [2]]}, dry_run=True)
        self.assertEqual(d.led_count, 3)


class EngineNoHangTest(unittest.TestCase):
    def test_slow_device_does_not_block_ui_or_others(self):
        import aicolors.engine as engmod
        from aicolors.devices.base import Device

        class Fast(Device):
            keepalive = 0.2

            def __init__(self):
                super().__init__("rapid", 3)
                self.frames = 0

            def send(self, colors):
                self.frames += 1

        class SlowSend(Device):
            def __init__(self):
                super().__init__("lent", 1)

            def send(self, colors):
                time.sleep(3)

        fast = Fast()

        def fake_create(entry, dry_run=False, preview=False):
            if entry["type"] == "slowconnect":
                time.sleep(3)
                raise OSError("nu răspunde")
            return {"fast": lambda: fast, "slowsend": SlowSend}[entry["type"]]()

        orig = engmod.create_device
        engmod.create_device = fake_create
        try:
            store = StateStore()
            eng = Engine([{"type": "slowconnect"}, {"type": "slowsend"}, {"type": "fast"}], store,
                         workers=True)
            t = threading.Thread(target=eng.run)
            t.start()
            store.update(LIVE)
            time.sleep(1.0)
            t0 = time.time()
            snap = eng.snapshot()                       # interfața: răspuns imediat
            self.assertLess(time.time() - t0, 0.1)
            self.assertEqual([s["connected"] for s in snap], [False, True, True])
            self.assertGreaterEqual(fast.frames, 2)     # luminile rapide merg mai departe
            eng.stop()
            t.join(10)
            self.assertFalse(t.is_alive())
        finally:
            engmod.create_device = orig


class FakePaletteWriter(FakeModeWriter):
    def __init__(self, mode=2):
        super().__init__(mode)
        self.palette = bytes.fromhex("ff0000ffff0000ff0000ffff0000ffff00ffffffff") * 20 + bytes(1024 - 420)
        self.palette_writes = []
        self.forced = []

    def read_palette(self):
        return self.palette

    def write_palette(self, table):
        self.palette_writes.append(table[:3])
        self.palette = table
        return True

    def set_mode(self, value, force=False):
        if force:
            self.forced.append(value)
        return super().set_mode(value)


class ZenkabeatAutoColorsTest(unittest.TestCase):
    def test_scene_colors_and_restore(self):
        from aicolors.devices.zenkabeat import ZenkabeatModeKeyboard

        w = FakePaletteWriter(mode=2)
        orig = w.palette
        dev = ZenkabeatModeKeyboard(writer=w, auto_colors=True, static_mode=1)
        self.assertEqual(dev.groups, 20)
        dev.send(["ct"])                         # paleta albastră + efect fix
        self.assertEqual(w.palette[:21], bytes(effects.CT_COLOR) * 7)
        self.assertEqual(w.palette[420:], orig[420:])  # restul tabelei neatins
        self.assertEqual(w.calls, [1])
        dev.send(["bomb"])                       # același efect: paletă roșie + reaplicare forțată
        self.assertEqual(w.palette[:3], bytes(effects.BOMB_COLOR))
        self.assertEqual(w.forced, [1])
        dev.send(["bomb"])                       # nimic nou de scris
        self.assertEqual(len(w.palette_writes), 2)
        dev.send(["menu"])                       # paleta și efectul tău
        self.assertEqual(w.palette, orig)
        self.assertEqual(w.mode, 2)
        dev.send(["t"])
        dev.close()                              # la închidere: totul înapoi
        self.assertEqual(w.palette, orig)
        self.assertEqual(w.mode, 2)
