import os, sys, time, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import acoustic_protocol as p

def reason(text):
    try: p.parse_command(text)
    except p.ProtocolError as e: return e.reason
    return None

class T(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(p.parse_command("12 F 50"), p.Command(12, "F", 50))
        self.assertEqual(p.parse_command("  7  tl   30 "), p.Command(7, "TL", 30))   # case + spaces tolerated
        self.assertEqual(p.parse_command("13 GO A"), p.Command(13, "GO", "A"))
        self.assertEqual(p.parse_command("14 stop"), p.Command(14, "STOP", None))
        self.assertEqual(p.parse_command("15 STAT"), p.Command(15, "STAT", None))
        self.assertEqual(p.parse_command("1 R 100").arg, 100)           # exactly at the limit
        self.assertEqual(p.parse_command("1 TR 90").arg, 90)
    def test_far(self):
        for t in ("12 F 101", "12 L 5000", "12 TL 91", "12 F 0", "12 TR 0"):
            self.assertEqual(reason(t), "FAR", t)
    def test_bad(self):
        for t in ("", "F 50", "0 F 5", "100 F 5", "12 F", "12 STOP 5", "12 STAT now", "12 JUMP 5",
                  "12 F -5", "12 F 5.5", "12 GO", "12 F 5; rm -rf", "12 F \u00b2", "ab F 5",
                  "12 F 123456789", "12 GO TOOLONGNAME", "12 F 5 5"):
            self.assertEqual(reason(t), "BAD", repr(t))
    def test_format(self):
        self.assertEqual(p.format_command(12, "F", 50), "12 F 50")
        self.assertEqual(p.format_command(14, "STOP"), "14 STOP")
        with self.assertRaises(p.ProtocolError): p.format_command(12, "F", 500)
        with self.assertRaises(p.ProtocolError): p.format_command(100, "STOP")
    def test_replies(self):
        self.assertEqual(p.format_reply(12, "OK"), "12 OK")
        self.assertEqual(p.format_reply(15, "POS", 120, 85, 90), "15 POS 120 85 90")
        self.assertEqual(p.parse_reply("15 POS 120 85 90"), (15, ["POS", "120", "85", "90"]))
        for t in ("", "OK", "12", "x OK"):
            with self.assertRaises(p.ProtocolError): p.parse_reply(t)
    def test_framing(self):
        self.assertEqual(p.frame_unicast(234, "12 F 50"), b"$M2340712 F 50")
        self.assertEqual(p.frame_unicast(234, "12 OK", ack=False), b"$U23405" b"12 OK")
        self.assertEqual(p.frame_unicast(5, "14 STOP")[:7], b"$M00507")
        for bad in ((256, "12 F 50"), (234, "x"), (234, "x" * 65), (-1, "12 F 50")):
            with self.assertRaises(ValueError): p.frame_unicast(*bad)
    def test_incoming(self):
        self.assertEqual(p.message_from_line("#U0712 F 50"), "12 F 50")
        self.assertIsNone(p.message_from_line("#U0912 F 50"))        # length does not match
        self.assertIsNone(p.message_from_line("#B23405Hello"))       # broadcast is ignored
        self.assertIsNone(p.message_from_line("#R234T00046"))
        self.assertIsNone(p.message_from_line(""))
    def test_roundtrip_through_modem_text(self):
        text = p.format_command(33, "TL", 45)
        frame = p.frame_unicast(234, text).decode()
        yy, data = frame[5:7], frame[7:]
        self.assertEqual(p.message_from_line("#U" + yy + data), text)
    def test_cache(self):
        c = p.ReplyCache(ttl=0.2)
        self.assertIsNone(c.lookup(12))
        c.store(12, "12 OK")
        self.assertEqual(c.lookup(12), "12 OK")      # resent command -> same reply, no second move
        self.assertIsNone(c.lookup(13))              # a different number is a new command
        time.sleep(0.3)
        self.assertIsNone(c.lookup(12))              # expired: a new session may reuse the number
    def test_sizes(self):
        worst = "99 TR 90"; self.assertLessEqual(len(worst), 10)
        n = len("12 F 50"); print("on-air time for '12 F 50': %.3f s" % (0.105 + (n + 16) * 0.0125))


if __name__ == "__main__":
    unittest.main(verbosity=1)
