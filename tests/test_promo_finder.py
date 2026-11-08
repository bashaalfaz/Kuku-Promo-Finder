import tempfile, unittest, sys, types as pytypes, unittest.mock
from pathlib import Path
from promo_finder import seconds, stamp, parse_script, candidates_for_episode, composite_candidates, _gemini_generate_with_failover

class PromoFinderTests(unittest.TestCase):
    def test_timestamp_roundtrip(self):
        self.assertAlmostEqual(seconds("01:02.50"),62.5)
        self.assertEqual(stamp(62.5),"01:02.50")
    def test_parse_real_input(self):
        p=Path("data/episode-001-Episode 1671703.txt")
        ep,log,dur,events=parse_script(p)
        self.assertTrue(ep)
        self.assertGreater(len(events),20)
        self.assertGreater(dur,60)
    def test_candidate_duration_bounds(self):
        p=Path("data/episode-001-Episode 1671703.txt")
        ep,log,dur,events=parse_script(p)
        cs=candidates_for_episode(ep,log,dur,events)
        self.assertTrue(cs)
        for c in cs: self.assertGreaterEqual(c["duration_seconds"],20); self.assertLessEqual(c["duration_seconds"],60)
    def test_composite_total_duration(self):
        a={"episode":"A","segments":[{"episode":"A","start":"00:00.00","end":"00:20.00","start_seconds":0,"end_seconds":20,"duration_seconds":20}],"duration_seconds":20,"hook":"betrayal truth","hook_timestamp":"00:00.00","cliffhanger":"Who are you?","cliffhanger_timestamp":"00:18.00","score":8}
        b={"episode":"B","segments":[{"episode":"B","start":"00:10.00","end":"00:35.00","start_seconds":10,"end_seconds":35,"duration_seconds":25}],"duration_seconds":25,"hook":"betrayal truth","hook_timestamp":"00:10.00","cliffhanger":"What happens now?","cliffhanger_timestamp":"00:34.00","score":7}
        cs=composite_candidates([a,b])
        self.assertTrue(cs)
        self.assertLessEqual(cs[0]["duration_seconds"],60)
        self.assertEqual(len(cs[0]["segments"]),2)

    def test_gemini_retry_then_fallback(self):
        calls=[]
        class RetryError(Exception):
            code=503
        class FakeModels:
            def generate_content(self, model, contents, config):
                calls.append(model)
                # Fail all 3 primary attempts; succeed on first fallback attempt.
                if model=="gemini-3.8-flash":
                    raise RetryError("capacity unavailable")
                return pytypes.SimpleNamespace(text='{"evaluations":[]}')
        class FakeClient:
            models=FakeModels()
        fake_types=pytypes.SimpleNamespace(GenerateContentConfig=lambda **kw: kw)
        fake_google=pytypes.ModuleType("google")
        fake_genai=pytypes.ModuleType("google.genai")
        fake_genai.types=fake_types
        fake_google.genai=fake_genai
        sleeps=[]
        with unittest.mock.patch.dict(sys.modules, {"google":fake_google,"google.genai":fake_genai}):
            result,model,errors=_gemini_generate_with_failover("prompt",FakeClient(),sleep_fn=sleeps.append)
        self.assertEqual(model,"gemini-3.5-flash")
        self.assertEqual(calls,["gemini-3.8-flash"]*3+["gemini-3.5-flash"])
        self.assertEqual(sleeps,[2,2])
        self.assertEqual(len(errors),3)

    def test_gemini_primary_success_no_wait(self):
        calls=[]
        class FakeModels:
            def generate_content(self, model, contents, config):
                calls.append(model)
                return pytypes.SimpleNamespace(text='{"evaluations":[]}')
        class FakeClient:
            models=FakeModels()
        fake_types=pytypes.SimpleNamespace(GenerateContentConfig=lambda **kw: kw)
        fake_google=pytypes.ModuleType("google")
        fake_genai=pytypes.ModuleType("google.genai")
        fake_genai.types=fake_types
        fake_google.genai=fake_genai
        sleeps=[]
        with unittest.mock.patch.dict(sys.modules, {"google":fake_google,"google.genai":fake_genai}):
            result,model,errors=_gemini_generate_with_failover("prompt",FakeClient(),sleep_fn=sleeps.append)
        self.assertEqual(model,"gemini-3.8-flash")
        self.assertEqual(calls,["gemini-3.8-flash"])
        self.assertEqual(sleeps,[])

    def test_segment_time_order(self):
        p=Path("data/episode-001-Episode 1671703.txt")
        ep,log,dur,events=parse_script(p)
        cs=candidates_for_episode(ep,log,dur,events)
        for c in cs:
            s=c["segments"][0]
            self.assertLess(s["start_seconds"],s["end_seconds"])
if __name__=="__main__": unittest.main()
