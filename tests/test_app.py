import json
import sys
import tempfile
import types
import unittest
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from lixu import config as configmod
from lixu import effects
from lixu.peripherals import hidpp


class FakeMouse:
    """Simulează un mouse HID++ 2.0 (ca G502 LIGHTSPEED) la nivel de rapoarte."""

    FEATURES = {hidpp.ROOT: 0, hidpp.DEVICE_NAME: 2, hidpp.BATTERY_VOLTAGE: 4,
                hidpp.ADJUSTABLE_DPI: 6, hidpp.REPORT_RATE: 7, hidpp.ONBOARD_PROFILES: 9}

    def __init__(self, index=1, offline=False):
        self.index = index
        self.offline = offline
        self.queue = deque()
        self.dpi = 1600
        self.rate_ms = 1
        self.mode = 1
        self.name = b"G502 LIGHTSPEED"
        self.written = []

    def write(self, data):
        self.written.append(bytes(data))
        if self.offline:
            return
        rid, idx, feat, fn = data[:4]
        func = fn >> 4
        p = data[4:]
        # zgomot: un raport al altei aplicații (alt sw_id) trebuie ignorat
        self.queue.append(bytes((0x11, idx, feat, (func << 4) | 0x1)) + b"\x99" * 16)
        if idx != self.index:
            self.queue.append(bytes((0x10, idx, 0x8F, feat, fn, 0x08, 0)))
            return
        by_index = {v: k for k, v in self.FEATURES.items()}
        fid = by_index.get(feat)
        r = None
        if fid == hidpp.ROOT and func == 0:
            r = bytes((self.FEATURES.get(int.from_bytes(p[:2], "big"), 0), 0, 0))
        elif fid == hidpp.ROOT and func == 1:
            r = bytes((4, 2, p[2]))
        elif fid == hidpp.DEVICE_NAME:
            r = bytes((len(self.name),)) if func == 0 else self.name[p[0]:p[0] + 16]
        elif fid == hidpp.BATTERY_VOLTAGE:
            r = bytes((0x0F, 0x47, 0x00))  # 3911 mV, nu se încarcă
        elif fid == hidpp.ADJUSTABLE_DPI:
            if func == 1:
                r = bytes((0, 0x00, 0x64, 0xE0, 0x32, 0x64, 0x00, 0, 0))  # 100..25600 pas 50
            elif func == 2:
                r = bytes((0, self.dpi >> 8, self.dpi & 0xFF, 0x03, 0x20))
            elif func == 3:
                self.dpi = (p[1] << 8) | p[2]
                r = p[:3]
        elif fid == hidpp.REPORT_RATE:
            r = {0: bytes((0b10001011,)), 1: bytes((self.rate_ms,))}.get(func)
            if func == 2:
                self.rate_ms = p[0]
                r = b""
        elif fid == hidpp.ONBOARD_PROFILES:
            if func == 2:
                r = bytes((self.mode,))
            elif func == 1:
                self.mode = p[0]
                r = b""
        if r is None:
            self.queue.append(bytes((0x11, idx, 0xFF, feat, fn, 0x07)) + b"\x00" * 14)
        else:
            self.queue.append(bytes((0x11, idx, feat, fn)) + r.ljust(16, b"\x00"))

    def read(self, timeout):
        return self.queue.popleft() if self.queue else None


class HidppTest(unittest.TestCase):
    def test_voltage_curve(self):
        self.assertEqual(hidpp.voltage_to_percent(4200), 100)
        self.assertEqual(hidpp.voltage_to_percent(3811), 50)
        self.assertEqual(hidpp.voltage_to_percent(3400), 0)
        self.assertTrue(50 < hidpp.voltage_to_percent(3840) < 60)

    def test_dpi_list_with_range(self):
        data = bytes((0, 0x00, 0x64, 0xE0, 0x32, 0x64, 0x00, 0, 0))
        dpis = hidpp.parse_dpi_list(data)
        self.assertEqual((dpis[0], dpis[1], dpis[-1], len(dpis)), (100, 150, 25600, 511))
        self.assertEqual(hidpp.parse_dpi_list(bytes((0, 0x01, 0x90, 0x03, 0x20, 0, 0))), [400, 800])

    def test_mouse(self):
        dev = hidpp.HidppDevice(FakeMouse(), index=1)
        self.assertEqual(dev.ping(), (4, 2))
        self.assertEqual(dev.name(), "G502 LIGHTSPEED")
        bat = dev.battery()
        self.assertEqual((bat.voltage, bat.charging, bat.source), (3911, False, "voltage"))
        self.assertTrue(60 < bat.percent < 70)
        self.assertEqual(dev.dpi(), 1600)
        dev.set_dpi(812)  # rotunjit la cel mai apropiat pas de 50
        self.assertEqual(dev.dpi(), 800)
        self.assertEqual(dev.report_rate_choices(), [125, 250, 500, 1000])
        dev.set_report_rate(500)
        self.assertEqual(dev.report_rate(), 500)
        self.assertEqual(dev.onboard_mode(), "onboard")
        dev.set_host_mode(True)
        self.assertEqual(dev.onboard_mode(), "host")

    def test_missing_feature_and_wrong_index(self):
        dev = hidpp.HidppDevice(FakeMouse(), index=1)
        self.assertFalse(dev.has(hidpp.UNIFIED_BATTERY))
        self.assertIsNone(hidpp.HidppDevice(FakeMouse(), index=2).ping())

    def test_offline(self):
        dev = hidpp.HidppDevice(FakeMouse(offline=True), index=1, timeout=0.05)
        with self.assertRaises(hidpp.DeviceOffline):
            dev.battery()

    def test_request_format(self):
        mouse = FakeMouse()
        hidpp.HidppDevice(mouse, index=1).ping()
        msg = mouse.written[0]
        self.assertEqual(len(msg), 20)
        self.assertEqual(msg[:7], bytes((0x11, 1, 0, 0x1B, 0, 0, 0x5A)))


class FakeBulb:
    instances = []

    def __init__(self, dev_id, address, local_key, **kw):
        self.args = (dev_id, address, local_key, kw)
        self.calls = []
        FakeBulb.instances.append(self)

    def set_socketTimeout(self, s):
        pass

    def status(self):
        return {"dps": {"20": True}}

    def turn_on(self, nowait=False):
        self.calls.append(("on",))

    def set_colour(self, r, g, b, nowait=False):
        self.calls.append(("colour", r, g, b, nowait))

    def close(self):
        self.calls.append(("close",))


class TuyaTest(unittest.TestCase):
    def setUp(self):
        sys.modules["tinytuya"] = types.SimpleNamespace(BulbDevice=FakeBulb, deviceScan=lambda *a, **k: {
            "192.168.1.80": {"gwId": "bf1234567890abcdef", "version": "3.3"}})
        FakeBulb.instances.clear()

    def tearDown(self):
        sys.modules.pop("tinytuya", None)

    def test_bulb_uses_wizard_key(self):
        from lixu.devices import tuya

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "devices.json"
            path.write_text(json.dumps([{"id": "bf1234567890abcdef", "key": "secret", "name": "Bec birou"}]))
            dev = tuya.TuyaBulb("bf1234567890abcdef", devices_json=str(path))
        self.assertEqual(dev.name, "Bec birou")
        bulb = FakeBulb.instances[0]
        self.assertEqual(bulb.args[2], "secret")
        dev.send([(0, 0, 0)])
        dev.send([(255, 0, 0)])
        self.assertEqual(bulb.calls[-2:], [("colour", 1, 1, 1, True), ("colour", 255, 0, 0, True)])

    def test_missing_key(self):
        from lixu.devices import tuya
        from lixu.devices.base import DeviceError

        with self.assertRaises(DeviceError):
            tuya.TuyaBulb("necunoscut", devices_json="/nu/exista.json")

    def test_discover(self):
        from lixu.devices import tuya

        found = tuya.discover(1)
        self.assertEqual(found[0].address, "192.168.1.80")
        self.assertFalse(found[0].controllable)  # fără local key
        self.assertTrue(found[0].notes)


class PaletteTest(unittest.TestCase):
    def test_apply_and_restore(self):
        orig = effects.palette()
        try:
            effects.apply_palette({"ct": "#123456", "nope": "#000000"})
            self.assertEqual(effects.team_color("CT"), (0x12, 0x34, 0x56))
            with self.assertRaises(ValueError):
                effects.hex_to_rgb("rosu")
        finally:
            effects.apply_palette(orig)
        self.assertEqual(effects.palette(), orig)


class AppApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from lixu.app import App

        cls.tmp = tempfile.TemporaryDirectory()
        path = Path(cls.tmp.name) / "lixu.json"
        cfg = configmod.Config(devices=[{"type": "zenkabeat"}, {"type": "wled", "leds": 10, "effect": "health"}],
                               port=0, ui_port=0, path=path)
        cls.app = App(cfg, dry_run=True)
        cls.app.start()
        cls.base = cls.app.ui_url.rstrip("/")

    @classmethod
    def tearDownClass(cls):
        cls.app.stop()
        effects.apply_palette(__import__("lixu.app", fromlist=["x"]).DEFAULT_PALETTE)
        cls.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return json.loads(r.read())

    def post(self, path, body, header=True):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"X-Lixu": "1"} if header else {})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_index_and_meta(self):
        with urllib.request.urlopen(self.base + "/") as r:
            self.assertIn(b"<title>Lixu</title>", r.read())
        meta = self.get("/api/meta")
        self.assertIn("tuya", meta["types"])
        self.assertEqual(len(meta["keys"]), 68)

    def test_simulate_and_state(self):
        self.post("/api/simulate", {"preset": "t_low"})
        st = self.get("/api/state")
        self.assertEqual((st["game"]["team"], st["game"]["health"]), ("T", 17))

    def test_csrf_header_required(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post("/api/simulate", {"preset": "menu"}, header=False)
        self.assertEqual(ctx.exception.code, 403)

    def test_save_config_reconfigures(self):
        cfg = self.get("/api/config")
        cfg["devices"][1]["effect"] = "ammo"
        cfg["devices"].append({"type": "govee", "host": "1.2.3.4", "enabled": False})
        cfg["colors"]["t"] = "#00ff00"
        r = self.post("/api/config", cfg)
        self.assertTrue(r["ok"])
        self.assertEqual([o.effect for o in self.app.engine.outputs], ["keyboard", "ammo"])
        self.assertEqual(effects.team_color("T"), (0, 255, 0))
        saved = json.loads(Path(r["path"]).read_text())
        self.assertEqual(saved["devices"][2]["enabled"], False)

    def test_identify(self):
        self.assertTrue(self.post("/api/identify", {"index": 0})["ok"])
        self.assertGreater(self.app.engine.outputs[0].identify_until, 0)


if __name__ == "__main__":
    unittest.main()
