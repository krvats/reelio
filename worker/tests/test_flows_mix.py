"""Mixing pages, sorting + filters, and overlay layers."""
import os, sys, shutil, subprocess, tempfile, unittest, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from reelio import engine, layers, media
from reelio.sources import multi, page, links
from reelio.errors import SourceProblem
from reelio.util import now, iso

E = engine.Engine


class Fake:
    _passes = E._passes
    candidates = E.candidates


def item(key, **kw):
    d = {"key": key, "status": "pending", "fails": 0, "created": kw.pop("created", "2026-01-01T00:00:00Z")}
    d.update(kw)
    return d


def keys(route, items):
    return [i["key"] for i in Fake().candidates(dict(route, id="r"), {"items": items})]


class Sorting(unittest.TestCase):
    def setUp(self):
        d = lambda n: iso(now() - datetime.timedelta(days=n))
        self.items = [item("a", views=100, likes=5, posted_at=d(2)), item("b", views=9000, likes=50, posted_at=d(40)),
                      item("c", views=500, likes=500, posted_at=d(10)), item("n")]

    def test_views_high_low_unknown_last(self):
        self.assertEqual(keys({"order": "views_high"}, self.items), ["b", "c", "a", "n"])
        self.assertEqual(keys({"order": "views_low"}, self.items), ["a", "c", "b", "n"])
        self.assertEqual(keys({"order": "likes_high"}, self.items)[:2], ["c", "b"])

    def test_posted_new_old(self):
        self.assertEqual(keys({"order": "posted_new"}, self.items), ["a", "c", "b", "n"])
        self.assertEqual(keys({"order": "posted_old"}, self.items), ["b", "c", "a", "n"])

    def test_filters(self):
        self.assertEqual(sorted(keys({"filters": {"min_views": 400}}, self.items)), ["b", "c", "n"])
        self.assertEqual(sorted(keys({"filters": {"min_views": 400, "unknown": "skip"}}, self.items)), ["b", "c"])
        self.assertEqual(sorted(keys({"filters": {"within_days": 15}}, self.items)), ["a", "c", "n"])
        self.assertEqual(sorted(keys({"filters": {"older_than_days": 15, "unknown": "skip"}}, self.items)), ["b"])
        self.assertEqual(sorted(keys({"filters": {"max_views": 1000, "min_views": 200}}, self.items)), ["c", "n"])

    def test_words_and_post_first_bypass(self):
        its = [item("x", name="Funny cat"), item("y", name="Sad dog"), item("z", name="Sad cat", post_now=True)]
        self.assertEqual(sorted(keys({"filters": {"include": "cat"}}, its)), ["x", "z"])
        self.assertEqual(sorted(keys({"filters": {"exclude": "cat", "min_views": 5, "unknown": "skip"}}, its)), ["z"])

    def test_mix_takes_turns(self):
        its = [item("a1", src_i=0, created="2026-01-01T00:00:01Z"), item("a2", src_i=0, created="2026-01-01T00:00:02Z"),
               item("a3", src_i=0, created="2026-01-01T00:00:03Z"), item("b1", src_i=1, created="2026-01-02T00:00:00Z"),
               item("c1", src_i=2, created="2026-01-03T00:00:00Z")]
        self.assertEqual(keys({"order": "mix"}, its), ["a1", "b1", "c1", "a2", "a3"])


class Multi(unittest.TestCase):
    def test_one_bad_page_never_stops_others(self):
        calls = []

        def fake(src, store, route):
            calls.append(route["id"])
            if "bad" in src["url"]:
                raise SourceProblem("nope", "fix", kind="blocked")
            return [{"key": "link:ig_" + src["url"][-3:], "name": "v", "created": iso(), "meta": {"url": src["url"]}}]
        old, oldl = page.list_items, links.list_items
        page.list_items = fake
        links.list_items = lambda s, st, r: [{"key": "link:own1", "name": "mine", "created": iso(), "meta": {"url": "https://x/y"}}]
        try:
            out = multi.list_items({"sources": [{"type": "page", "url": "https://i.com/aaa"}, {"type": "page", "url": "https://i.com/bad"},
                                                {"type": "page", "url": "https://i.com/ccc"}, {"type": "links"}]}, None, {"id": "r1"})
        finally:
            page.list_items, links.list_items = old, oldl
        self.assertEqual([i["key"] for i in out], ["link:ig_aaa", "link:ig_ccc", "link:own1"])
        self.assertEqual([i["src_i"] for i in out], [0, 2, 3])
        self.assertEqual(calls, ["r1~0", "r1~1", "r1~2"])         # each page has its own memory id
        self.assertEqual(out[2]["meta"]["from"], "my links")

    def test_all_bad_raises(self):
        old = page.list_items
        page.list_items = lambda *a: (_ for _ in ()).throw(SourceProblem("nope", "fix", kind="blocked"))
        try:
            with self.assertRaises(SourceProblem):
                multi.list_items({"sources": [{"type": "page", "url": "https://i.com/a"}]}, None, {"id": "r"})
        finally:
            page.list_items = old


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class Render(unittest.TestCase):
    def test_text_only_shows_inside_the_window(self):
        d = tempfile.mkdtemp()
        src, out, png = (os.path.join(d, n) for n in ("in.mp4", "out.mp4", "f.png"))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=540x960:d=4:r=30", "-f", "lavfi", "-i", "anullsrc",
                        "-t", "4", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", src], check=True)
        edit = {"canvas": {"bg": "#ffffff"}, "reel_box": {"x": 50, "y": 50, "w": 90, "h": 40, "fit": "cover"},
                "layers": [{"id": "fr", "type": "frame", "color": "#ffffff", "window": {"x": 50, "y": 50, "w": 90, "h": 40}},
                           {"type": "text", "text": "HELLO", "size": 400, "color": "#ff0000", "x": 50, "y": 50, "clip_to": "fr", "font": "sans-bold"},
                           {"type": "text", "text": "OUT", "size": 200, "color": "#ff0000", "x": 50, "y": 8, "clip_to": "fr"}]}
        media.prepare(src, out, edit, None, None, assets={}, variables={})
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out, "-frames:v", "1", png], check=True)
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", png, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        W, H = 1080, 1920
        px = lambda x, y: tuple(raw[(y * W + x) * 3:(y * W + x) * 3 + 3])
        self.assertEqual(px(5, 5), (255, 255, 255))                                   # white above the window, text clipped away
        self.assertEqual(px(540, int(H * .08)), (255, 255, 255))                      # "OUT" sits on the white part: hidden
        reds = sum(1 for x in range(100, 980, 4) for y in range(700, 1220, 4) if px(x, y)[0] > 200 and px(x, y)[1] < 80)
        blues = sum(1 for x in range(100, 980, 8) for y in range(700, 1220, 8) if px(x, y)[2] > 200 and px(x, y)[0] < 80)
        self.assertGreater(reds, 50)                                                  # text visible in the window
        self.assertGreater(blues, 200)                                                # reel visible in the window
        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
