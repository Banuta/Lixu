import io
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from aicolors import cs2cfg, layout, protocol
from aicolors.devices.zenkabeat import DryRunKeyboard
from aicolors.effects import Renderer, health_color
from aicolors.gsi import GsiServer, StateStore, parse_state


class ProtocolTest(unittest.TestCase):
    def test_packet_layout(self):
        frame = protocol.solid_frame((0, 0, 0))
        frame[1] = (10, 20, 30)  # Esc
        pkt = protocol.build_stream_packet(frame)
        self.assertEqual(len(pkt), protocol.FEATURE_LEN_STREAM)
        self.assertEqual(pkt[:4], bytes([0x08, 0x0A, 0x7A, 0x01]))
        self.assertEqual(pkt[4 + 3 : 4 + 6], bytes([10, 20, 30]))
        self.assertEqual(sum(pkt[4:]), 60)

    def test_rgb_order(self):
        frame = protocol.solid_frame((0, 0, 0))
        frame[0] = (1, 2, 3)
        data = protocol.encode_frame(frame, (2, 1, 0))
        self.assertEqual(data[:3], bytes([3, 2, 1]))

    def test_clamp_and_validation(self):
        data = protocol.encode_frame(protocol.solid_frame((300, -5, 127.6)))
        self.assertEqual(data[:3], bytes([255, 0, 128]))
        with self.assertRaises(ValueError):
            protocol.encode_frame([(0, 0, 0)] * 10)
        with self.assertRaises(ValueError):
            protocol.parse_rgb_order("0,0,1")

    def test_led_grid(self):
        self.assertEqual(protocol.led_index(*protocol.led_position(83)), 83)
        self.assertEqual(protocol.led_position(layout.key("Esc").led), (1, 0))


class LayoutTest(unittest.TestCase):
    def test_unique_leds(self):
        leds = [k.led for k in layout.KEYS]
        self.assertEqual(len(leds), 68)
        self.assertEqual(len(set(leds)), 68)
        self.assertTrue(all(0 <= led < protocol.LED_COUNT for led in leds))

    def test_rows_are_physical_rows(self):
        for names, row in ((layout.NUMBER_ROW, 1), (layout.QWERTY_ROW, 2),
                           (layout.HOME_ROW, 3), (layout.BOTTOM_ROW, 4)):
            rows = {protocol.led_position(layout.key(n).led)[0] for n in names}
            self.assertEqual(rows, {row}, names)
            cols = [protocol.led_position(layout.key(n).led)[1] for n in names]
            self.assertEqual(cols, sorted(cols), names)


SAMPLE = {
    "provider": {"steamid": "765"},
    "map": {"phase": "live"},
    "round": {"phase": "live"},
    "player": {
        "steamid": "765", "team": "T", "activity": "playing",
        "state": {"health": 50, "armor": 100, "helmet": False, "flashed": 0, "burning": 0,
                  "round_kills": 2, "round_killhs": 1},
        "weapons": {
            "weapon_0": {"name": "weapon_knife", "state": "holstered"},
            "weapon_1": {"name": "weapon_ak47", "state": "active", "ammo_clip": 15, "ammo_clip_max": 30},
        },
    },
    "auth": {"token": "secret"},
}


class GsiTest(unittest.TestCase):
    def test_parse(self):
        st = parse_state(SAMPLE, now=100.0)
        self.assertEqual(st.team, "T")
        self.assertEqual(st.health, 50)
        self.assertEqual(st.active_weapon.ammo_clip, 15)
        self.assertTrue(st.in_game)
        self.assertTrue(st.is_local_player)

    def test_bomb_timestamps(self):
        st = parse_state(SAMPLE, now=1.0)
        planted = dict(SAMPLE, round={"phase": "live", "bomb": "planted"})
        st = parse_state(planted, st, now=5.0)
        self.assertEqual(st.bomb_planted_at, 5.0)
        st = parse_state(planted, st, now=9.0)
        self.assertEqual(st.bomb_planted_at, 5.0)
        st = parse_state(dict(SAMPLE, round={"phase": "over", "bomb": "defused", "win_team": "CT"}), st, now=20.0)
        self.assertIsNone(st.bomb_planted_at)
        self.assertEqual(st.bomb_ended_at, 20.0)
        self.assertEqual(st.round_over_at, 20.0)

    def test_http_server_and_token(self):
        store = StateStore()
        server = GsiServer(store, port=0, token="secret")
        server.start()
        try:
            url = f"http://127.0.0.1:{server.port}/"
            req = urllib.request.Request(url, data=json.dumps(SAMPLE).encode(), method="POST")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
            self.assertEqual(store.get().health, 50)

            bad = dict(SAMPLE, auth={"token": "nope"})
            req = urllib.request.Request(url, data=json.dumps(bad).encode(), method="POST")
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req)
            self.assertEqual(ctx.exception.code, 403)
            self.assertEqual(store.updates, 1)
        finally:
            server.stop()


class EffectsTest(unittest.TestCase):
    def led(self, frame, name):
        return frame[layout.key(name).led]

    def test_health_bar(self):
        st = parse_state(SAMPLE, now=0)
        frame = Renderer().render(st, now=0.0)
        self.assertEqual(len(frame), protocol.LED_COUNT)
        self.assertEqual(self.led(frame, "5"), health_color(50))  # 50 HP -> tastele 1-5 aprinse
        self.assertEqual(self.led(frame, "6"), (15, 0, 0))

    def test_kills_and_ammo(self):
        frame = Renderer().render(parse_state(SAMPLE, now=0), now=0.0)
        self.assertEqual(self.led(frame, "Home"), (255, 0, 80))    # headshot
        self.assertEqual(self.led(frame, "Delete"), (255, 200, 0))  # kill
        self.assertEqual(self.led(frame, "PgUp"), (0, 0, 0))
        self.assertEqual(self.led(frame, "Z"), (255, 255, 255))     # 15/30 gloanțe
        self.assertEqual(self.led(frame, "/"), (0, 0, 0))

    def test_menu_and_dead(self):
        r = Renderer()
        idle = r.render(None, now=0.0)
        self.assertTrue(any(c != (0, 0, 0) for c in idle))
        dead = dict(SAMPLE, player=dict(SAMPLE["player"], state={"health": 0}))
        frame = r.render(parse_state(dead, now=0), now=0.0)
        self.assertEqual(self.led(frame, "W"), (25, 25, 25))

    def test_flash_goes_white(self):
        flashed = dict(SAMPLE, player=dict(SAMPLE["player"], state=dict(SAMPLE["player"]["state"], flashed=255)))
        frame = Renderer().render(parse_state(flashed, now=0), now=0.0)
        self.assertTrue(all(frame[led] == (255, 255, 255) for led in layout.ALL_LEDS))

    def test_bomb_tints_red(self):
        planted = dict(SAMPLE, round={"phase": "live", "bomb": "planted"})
        st = parse_state(planted, parse_state(SAMPLE, now=0), now=0)
        frame = Renderer().render(st, now=0.0)
        r, g, b = self.led(frame, "W")
        self.assertGreater(r, g)

    def test_dry_run_keyboard(self):
        out = io.StringIO()
        kb = DryRunKeyboard(preview=True, stream=out)
        kb.send_frame(Renderer().render(parse_state(SAMPLE, now=0), now=0.0))
        self.assertEqual(kb.frames_sent, 1)
        self.assertIn("Esc", out.getvalue())


class Cs2CfgTest(unittest.TestCase):
    def test_render_and_install(self):
        text = cs2cfg.render_cfg(port=3123, token="abc")
        self.assertIn('"uri"       "http://127.0.0.1:3123/"', text)
        self.assertIn('"token" "abc"', text)
        self.assertNotIn("auth", cs2cfg.render_cfg())
        with tempfile.TemporaryDirectory() as tmp:
            path = cs2cfg.install_cfg(Path(tmp), port=3000)
            self.assertEqual(path.name, "gamestate_integration_aicolors.cfg")

    def test_find_in_library_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Steam"
            lib = Path(tmp) / "Games"
            (root / "steamapps").mkdir(parents=True)
            (lib / cs2cfg.CS2_SUBDIR).mkdir(parents=True)
            (root / "steamapps" / "libraryfolders.vdf").write_text(
                '"libraryfolders"\n{\n "0" { "path" "%s" }\n "1" { "path" "%s" }\n}\n' % (root, lib))
            self.assertEqual(cs2cfg.find_cs2_cfg_dirs([root]), [lib / cs2cfg.CS2_SUBDIR])


if __name__ == "__main__":
    unittest.main()


class KbTestTableTest(unittest.TestCase):
    def test_groups_and_red(self):
        from aicolors import kbtest

        pal = bytes.fromhex("ff0000ffff0000ff0000ffff0000ffff00ffffffff")
        table = (pal * 20).ljust(1024, b"\x00")
        self.assertEqual(kbtest.palette_groups(table), 20)
        self.assertEqual(kbtest.colors_of(table, 1)[0][:3], ["#ff0000", "#ffff00", "#00ff00"])
        red = kbtest.all_red(table, 20)
        self.assertTrue(kbtest.is_all_red(red, 20))
        self.assertEqual(red[20 * 21:], table[20 * 21:])  # restul tabelei nu se atinge
        self.assertFalse(kbtest.is_all_red(table, 20))


class KbLearnDiffTest(unittest.TestCase):
    def test_changed_runs_and_describe(self):
        from aicolors import kblearn

        a = bytes(0xC000)
        b = bytearray(a)
        b[0xB802] = 7
        b[0xB805] = 9
        b[0xC000 - 1] = 1
        self.assertEqual(kblearn.changed_runs(a, bytes(b)), [(0xB802, 0xB806), (0xBFFF, 0xC000)])
        text = "\n".join(kblearn.describe(a, bytes(b)))
        self.assertIn("0xb802-0xb805 (date)", text)
        self.assertIn("nimic", kblearn.describe(a, a)[0])
        b[0x10] = 1
        self.assertIn("COD!", "\n".join(kblearn.describe(a, bytes(b))))


class WriteGuardTest(unittest.TestCase):
    def test_code_area_refused(self):
        for page in (0x00, 0x03, 0x80, 0xAF, 0xFD):
            with self.assertRaises(ValueError):
                protocol.write_packet(page, bytes(1024))
        pkt = protocol.write_packet(0xB8, bytes(1024))
        self.assertEqual(pkt[:8], bytes((6, 8, 0xB8, 0, 0x40, 0, 0, 0)))
        self.assertEqual(len(pkt), 1032)


class ProfileWriteTest(unittest.TestCase):
    def test_profile_packet(self):
        pkt = protocol.profile_write_packet(0xB6, bytes(range(254)))
        self.assertEqual(len(pkt), 1032)
        self.assertEqual(pkt[:8], bytes((6, 3, 0xB6, 0, 0, 0, 0, 0)))
        self.assertEqual(pkt[8 + 0x0D], 0x0D)
        with self.assertRaises(ValueError):
            protocol.profile_write_packet(0x02, bytes(254))
