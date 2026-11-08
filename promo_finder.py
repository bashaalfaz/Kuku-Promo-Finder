from __future__ import annotations
import argparse, csv, json, os, re, zipfile, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

TS = r"(\d{2}:\d{2}(?:\.\d+)?)"
START_RE = re.compile(r"^\s*Start:\s*\(?"+TS+r"\)?", re.I)
END_RE = re.compile(r"^\s*End:\s*\(?"+TS+r"\)?", re.I)
EP_RE = re.compile(r"^EPISODE NUMBER:\s*(.+)$", re.M)
LOG_RE = re.compile(r"^EPISODE LOGLINE:\s*(.+)$", re.M)
SCENE_RE = re.compile(r"^SCENE\s+(\d+)", re.I)
SPEAKER_RE = re.compile(r"^\*\*(.+?)\*\*:\s*$")

HOOK_PATTERNS = {
 "betrayal": (r"\b(betray|cheat|abandon|not anymore|changed my mind|marrying me|choose her|lied to me|you knew)\b", 2.8),
 "threat": (r"\b(kill|die|destroy|arrest|guards|punish|ruin|pay for this|never forgive|you will regret)\b", 2.7),
 "reveal": (r"\b(secret|truth|actually|revealed|heir|inheritance|is your|is mine|father|daughter|duke|pregnant)\b", 2.3),
 "emotion": (r"\b(please|shocked|betrayed|humiliated|disgrace|worthless|love you|hate you|why me)\b", 1.8),
 "power": (r"\b(kneel|bow|your grace|duke|queen|lord|my wife|my husband|marry)\b", 1.2)
}
CLIFF_PATTERNS = [
 r"\?", r"\b(wait|stop|who are you|what have you done|you have no idea|one condition|unless|until|the truth|secret|tonight|tomorrow)\b",
 r"\b(kill|die|fire|gun|blood|scream|gasp|shock|reveal|never|impossible)\b",
 r"\b(if you|before you|now you|you are|i know|what if|how dare)\b"
]
FILLER = {"the","a","an","and","or","but","to","of","in","on","is","it","you","i","he","she","we","they","my","your","me","him","her","this","that"}

@dataclass
class Event:
    start: float
    end: float
    kind: str
    text: str
    scene: str = ""

def seconds(s:str)->float:
    m=re.fullmatch(r"\s*(\d+):(\d{2})(?:\.(\d+))?\s*",s)
    if not m: raise ValueError(f"Invalid timestamp: {s}")
    return int(m.group(1))*60+int(m.group(2))+float("0."+(m.group(3) or "0"))

def stamp(x:float)->str:
    x=max(0.0,x); m=int(x//60); s=x-m*60
    return f"{m:02d}:{s:05.2f}"

def words(s:str)->set[str]:
    return {w for w in re.findall(r"[a-z']+",s.lower()) if len(w)>2 and w not in FILLER}

def parse_script(path:Path):
    raw=path.read_text(encoding="utf-8",errors="replace")
    epm=EP_RE.search(raw); lm=LOG_RE.search(raw)
    episode=epm.group(1).strip() if epm else path.stem
    logline=lm.group(1).strip() if lm else ""
    lines=raw.splitlines(); events=[]; scene=""; kind="ACTION"; active=None
    # Parse each timestamped block. Content runs until the next Start or section header.
    i=0
    while i<len(lines):
        line=lines[i].strip()
        sm=SCENE_RE.match(line)
        if sm: scene=f"Scene {sm.group(1)}"
        sp=SPEAKER_RE.match(line)
        if sp: kind=sp.group(1).strip()
        mt=START_RE.match(line)
        if not mt:
            i+=1; continue
        start=seconds(mt.group(1)); end=start
        chunks=[]; j=i+1
        while j<len(lines):
            cur=lines[j].strip()
            if START_RE.match(cur): break
            em=END_RE.match(cur)
            if em:
                end=max(start,seconds(em.group(1))); j+=1; continue
            if cur.startswith("**") or SCENE_RE.match(cur) or cur.startswith("---"): break
            if cur and not cur.lower().startswith(("scene heading:","actions and dialogue:","scene end:")):
                chunks.append(cur.strip().strip("*"))
            j+=1
        txt=" ".join(chunks).strip()
        if txt:
            k=kind
            if k.upper()=="CAMERA": k="CAMERA"
            elif k.upper()=="ACTION": k="ACTION"
            else: k="DIALOGUE"
            events.append(Event(start,end,k,txt,scene))
        i=max(i+1,j)
    events.sort(key=lambda e:(e.start,e.end))
    duration=max((e.end for e in events),default=0)
    return episode,logline,duration,events

def hook_score(e:Event):
    text=e.text.lower(); score=0.0; tags=[]
    for tag,(pat,weight) in HOOK_PATTERNS.items():
        n=len(re.findall(pat,text))
        if n: score+=weight*min(n,2); tags.append(tag)
    if "!" in e.text: score+=0.7
    if "?" in e.text: score+=0.5
    if e.kind=="DIALOGUE": score+=0.8
    elif e.kind=="ACTION": score+=0.35
    # visually described actions can be a hook, but camera-only descriptions score less
    if len(e.text)>30: score+=0.2
    return score,tags

def cliff_score(e:Event):
    t=e.text.lower()
    score=sum(2.0*bool(re.search(p,t)) for p in CLIFF_PATTERNS)
    if e.kind=="DIALOGUE" and ("?" in e.text or "!" in e.text): score+=1.0
    if e.kind=="ACTION" and any(x in t for x in ("raises","draws","slams","collapses","screams","gasps","freezes")): score+=1.1
    return score+min(len(t)/500,0.5)

def rank_window(events, start, end, episode, logline):
    inside=[e for e in events if e.start<end and e.end>=start]
    if not inside: return None
    first=[e for e in inside if start-0.01<=e.start<=start+3.0]
    if not first: first=inside[:2]
    hook=max(first,key=lambda e:hook_score(e)[0])
    ending=[e for e in inside if e.start>=end-9 or e.end>=end-6]
    if not ending: ending=inside[-3:]
    cliff=max(ending,key=cliff_score)
    hs,tags=hook_score(hook); cs=cliff_score(cliff)
    dialogue=sum(e.kind=="DIALOGUE" for e in inside)
    actions=sum(e.kind=="ACTION" for e in inside)
    density=min(len(inside)/10,1.0)
    # Penalize windows with little context and starts that do not have an event at/near the cut.
    start_alignment=1.0 if any(abs(e.start-start)<0.25 for e in events) else 0.45
    score=hs*0.34+cs*0.34+min(dialogue,7)*0.34+min(actions,4)*0.12+density*1.1+start_alignment
    return {
      "episode":episode,"segments":[{"episode":episode,"start":stamp(start),"end":stamp(end),"start_seconds":round(start,2),"end_seconds":round(end,2),"duration_seconds":round(end-start,2)}],
      "duration_seconds":round(end-start,2),"hook":hook.text[:350],"hook_timestamp":stamp(hook.start),
      "cliffhanger":cliff.text[:350],"cliffhanger_timestamp":stamp(cliff.start),
      "why_it_works":f"Potential {', '.join(tags) if tags else 'dramatic'} opening; {dialogue} dialogue beats and {actions} action beats build context before a high-tension final beat.",
      "score":round(score,3),"score_breakdown":{"hook":round(hs,2),"cliffhanger":round(cs,2),"dialogue_beats":dialogue,"action_beats":actions,"event_density":round(density,2),"start_alignment":start_alignment},
      "editorial_review_required":True
    }

def candidates_for_episode(episode,logline,duration,events,max_candidates=10):
    if duration<20 or not events: return []
    # Candidate cuts begin at meaningful timestamped event boundaries, with 20-60s durations.
    proposals=[]
    for e in events:
        start=e.start
        if start>duration-20: continue
        for length in (30,40,50,60):
            end=min(start+length,duration)
            if 20<=end-start<=60:
                c=rank_window(events,start,end,episode,logline)
                if c: proposals.append(c)
    proposals.sort(key=lambda c:c["score"],reverse=True)
    kept=[]
    for c in proposals:
        s=c["segments"][0]["start_seconds"]
        if any(abs(s-k["segments"][0]["start_seconds"])<12 for k in kept): continue
        kept.append(c)
        if len(kept)>=max_candidates: break
    return kept

def composite_candidates(all_single, max_composites=30):
    # Combine 2 or 3 distinct story moments into one <=60s promo. Cross-episode joins are explicit.
    pool=sorted(all_single,key=lambda c:c["score"],reverse=True)[:100]
    combos=[]
    for i,a in enumerate(pool):
        for b in pool[i+1:]:
            if a["episode"]==b["episode"]:
                sa,ea=a["segments"][0]["start_seconds"],a["segments"][0]["end_seconds"]
                sb,eb=b["segments"][0]["start_seconds"],b["segments"][0]["end_seconds"]
                # Same-episode montage beats must not overlap; keep a small separation.
                if not (ea+2 <= sb or eb+2 <= sa):
                    continue
            dur=a["duration_seconds"]+b["duration_seconds"]
            if 20<=dur<=60:
                wa,wb=words(a["hook"]+" "+a["cliffhanger"]),words(b["hook"]+" "+b["cliffhanger"])
                overlap=len(wa&wb)/max(1,len(wa|wb))
                # Small coherence bonus for shared names/concepts; weakly related clips remain possible but rank lower.
                coherence=min(overlap*4,1.0)
                score=(a["score"]+b["score"])/2+coherence*0.8-0.15
                segs=a["segments"]+b["segments"]
                combos.append({"episode":"Multi-segment: "+a["episode"]+" + "+b["episode"],"segments":segs,
                  "duration_seconds":round(dur,2),"hook":a["hook"],"hook_timestamp":a["hook_timestamp"],
                  "cliffhanger":b["cliffhanger"],"cliffhanger_timestamp":b["cliffhanger_timestamp"],
                  "why_it_works":"A short-form montage: the first segment establishes an immediate dramatic hook; the later segment escalates or reframes the stakes and ends on an unresolved beat. Review story continuity before use.",
                  "score":round(score,3),"score_breakdown":{"segment_a":a["score"],"segment_b":b["score"],"lexical_coherence":round(coherence,2)},
                  "editorial_review_required":True,"composite":True})
    combos.sort(key=lambda c:c["score"],reverse=True)
    out=[]
    for c in combos:
        sig=tuple((s["episode"],s["start_seconds"]) for s in c["segments"])
        if any(tuple((s["episode"],s["start_seconds"]) for s in x["segments"])==sig for x in out): continue
        out.append(c)
        if len(out)>=max_composites: break
    return out

def _is_retryable_gemini_error(exc: Exception) -> bool:
    """Retry only transient quota, capacity, server and transport failures."""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    response = getattr(exc, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None
    if status in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True
    message = str(exc).lower()
    transient_terms = (
        "timeout", "timed out", "temporarily unavailable", "overloaded",
        "resource exhausted", "rate limit", "too many requests",
        "internal error", "service unavailable", "connection reset",
        "connection error", "deadline exceeded", "503", "429", "500"
    )
    permanent_terms = ("api key not valid", "permission denied", "unauthorized",
                       "invalid argument", "model not found", "404", "400")
    if any(term in message for term in permanent_terms):
        return False
    return any(term in message for term in transient_terms)


def _gemini_generate_with_failover(prompt, client, sleep_fn=time.sleep):
    """
    Try Gemini 3.8 Flash first, then Gemini 3.5 Flash as fallback.
    Each model gets up to 3 attempts. The first attempt is immediate;
    retries wait 2 seconds. The HTTP timeout is configured on the client.
    """
    from google.genai import types

    model_chain = ["gemini-3.8-flash", "gemini-3.5-flash"]
    errors = []
    for model in model_chain:
        for attempt in range(1, 4):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        response_mime_type="application/json"
                    )
                )
                text = getattr(response, "text", None)
                if not text or not text.strip():
                    raise ValueError("Gemini returned an empty response")
                parsed = json.loads(text)
                if not isinstance(parsed, dict) or not isinstance(parsed.get("evaluations"), list):
                    raise ValueError("Gemini response did not match the expected JSON schema")
                return parsed, model, errors
            except Exception as exc:
                errors.append({"model": model, "attempt": attempt, "error": str(exc)[:300]})
                # Invalid credentials, invalid model IDs and malformed requests are not
                # capacity failures; retrying them only wastes time and quota.
                if not _is_retryable_gemini_error(exc) and not isinstance(exc, ValueError):
                    return None, None, errors
                if attempt < 3:
                    sleep_fn(2)
                    continue
                break
    return None, None, errors


def llm_review(candidates, api_key=None):
    """
    Gemini semantic reranker. It reviews up to the top 20 heuristic candidates
    in small batches. Every batch follows 3.8 x3 -> 3.5 Flash x3.
    If Gemini is unavailable, the deterministic ranking is preserved.
    """
    api_key = api_key or os.getenv("GEMINI_API_KEY")
    if not api_key:
        return candidates, {"mode": "heuristic_no_api_key", "models_used": [],
                            "batches_reviewed": 0, "retry_log": []}
    try:
        from google import genai
        from google.genai import types

        # Google GenAI HttpOptions timeout is expressed in milliseconds.
        # This prevents a single stalled request from hanging the app forever.
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000)
        )
    except Exception as exc:
        return candidates, {"mode": "heuristic_sdk_error", "models_used": [],
                            "batches_reviewed": 0, "retry_log": [str(exc)[:300]]}

    review_count = min(20, len(candidates))
    reviewed = candidates[:review_count]
    batch_size = 10
    models_used, retry_log, successful_batches = [], [], 0
    for offset in range(0, len(reviewed), batch_size):
        batch = reviewed[offset:offset + batch_size]
        request_data = {
            "task": (
                "Act as a strict senior vertical-microdrama promo editor. Score each candidate "
                "from 1 to 5 for: hook (first 3 seconds), cliffhanger (unresolved final beat), "
                "standalone (understandable to a new viewer), and escalation (emotional/dramatic "
                "build). Judge only the supplied screenplay evidence. Never invent events or "
                "visuals. A text screenplay cannot prove actual video quality. Return JSON only."
            ),
            "required_output": {
                "evaluations": [
                    {"id": 0, "hook": 1, "cliffhanger": 1, "standalone": 1,
                     "escalation": 1, "reason": "short evidence-based explanation"}
                ]
            },
            "candidates": [
                {"id": i, "episode": c["episode"], "duration_seconds": c["duration_seconds"],
                 "segments": c["segments"], "hook": c["hook"],
                 "cliffhanger": c["cliffhanger"], "why_it_works": c["why_it_works"]}
                for i, c in enumerate(batch)
            ]
        }
        result, model, errors = _gemini_generate_with_failover(
            json.dumps(request_data, ensure_ascii=False), client
        )
        retry_log.extend([{"batch_start": offset, **e} for e in errors])
        if result is None:
            continue
        successful_batches += 1
        if model not in models_used:
            models_used.append(model)
        by_id = {int(x["id"]): x for x in result["evaluations"]
                 if isinstance(x, dict) and str(x.get("id", "")).isdigit()}
        for local_id, candidate in enumerate(batch):
            evaluation = by_id.get(local_id)
            if not evaluation:
                continue
            try:
                scores = {
                    key: max(1.0, min(5.0, float(evaluation[key])))
                    for key in ("hook", "cliffhanger", "standalone", "escalation")
                }
            except (KeyError, TypeError, ValueError):
                continue
            candidate["gemini_review"] = {
                **scores, "model": model,
                "reason": str(evaluation.get("reason", ""))[:500]
            }
            semantic_average = sum(scores.values()) / 4
            candidate["score"] = round(candidate["score"] * 0.55 + semantic_average * 0.9, 3)

    candidates.sort(key=lambda c: c["score"], reverse=True)
    mode = "gemini_semantic_reranking" if successful_batches else "heuristic_gemini_unavailable"
    return candidates, {
        "mode": mode, "models_used": models_used,
        "batches_reviewed": successful_batches,
        "candidate_limit": review_count, "batch_size": batch_size,
        "retry_policy": "gemini-3.8-flash: up to 3 attempts; then gemini-3.5-flash: up to 3 attempts; 2 seconds between retries",
        "request_timeout_seconds": 30,
        "retry_log": retry_log
    }

def load_input(input_path:Path,temp_dir:Path):
    if input_path.is_dir(): return sorted(input_path.glob("*.txt"))
    if input_path.suffix.lower()==".zip":
        temp_dir.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(input_path) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(".txt") and not info.is_dir():
                    # flatten names safely; skip path traversal
                    name=Path(info.filename).name
                    (temp_dir/name).write_bytes(z.read(info))
        return sorted(temp_dir.glob("*.txt"))
    raise ValueError("Input must be a folder of .txt scripts or a .zip screenplay pack")

def run(input_path:Path,output:Path,api_key=None):
    output.mkdir(parents=True,exist_ok=True)
    files=load_input(input_path,output/"_extracted")
    singles=[]; audit=[]
    for file_index, p in enumerate(files, 1):
        print(f"Parsing episode {file_index}/{len(files)}: {p.name}", flush=True)
        ep,log,dur,events=parse_script(p)
        cs=candidates_for_episode(ep,log,dur,events)
        singles.extend(cs)
        audit.append({"file":p.name,"episode":ep,"duration_seconds":round(dur,2),"events_parsed":len(events),"single_segment_candidates":len(cs),"status":"ok" if events else "no_events"})
    singles.sort(key=lambda c:c["score"],reverse=True)
    composites=composite_candidates(singles)
    allc=singles+composites
    allc.sort(key=lambda c:c["score"],reverse=True)
    for i,c in enumerate(allc,1): c["rank"]=i
    print(
        f"Generated {len(allc)} candidates. Starting Gemini review "
        f"for up to {min(20, len(allc))} candidates...",
        flush=True
    )
    allc,gemini_status=llm_review(allc, api_key=api_key)
    for i,c in enumerate(allc,1): c["rank"]=i
    payload={"project":"Kuku Promo Finder Enhanced","show":"I Married a Broken Soldier. He was a Duke",
      "episodes_processed":len(files),"episodes_with_events":sum(x["events_parsed"]>0 for x in audit),
      "single_segment_candidates":len(singles),"multi_segment_candidates":len(composites),"candidate_count":len(allc),
      "scoring_mode":gemini_status["mode"],"gemini_status":gemini_status,
      "ranking_note":"Scores are editorial triage scores, not probabilities. Review every cut against the finished video.",
      "promos":allc,"episode_audit":audit,
      "known_limitations":["Text-only screenplay analysis cannot verify actual video visuals, acting, audio, framing, continuity or whether a cut is visually intelligible.",
      "Multi-segment montage suggestions are heuristic and may join unrelated story beats; editorial review is mandatory.",
      "Gemini semantic reranking requires GEMINI_API_KEY; deterministic scoring works without one."]}
    (output/"promo_candidates.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8")
    with (output/"promo_candidates.csv").open("w",newline="",encoding="utf-8") as f:
        fields=["rank","episode","duration_seconds","score","segments","hook","hook_timestamp","cliffhanger","cliffhanger_timestamp","why_it_works","composite","editorial_review_required"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for c in allc:
            row=c.copy(); row["segments"]=json.dumps(c["segments"],ensure_ascii=False)
            w.writerow({k:row.get(k,"") for k in fields})
    (output/"episode_audit.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    (output/"run_summary.json").write_text(json.dumps({k:payload[k] for k in ("episodes_processed","episodes_with_events","single_segment_candidates","multi_segment_candidates","candidate_count","scoring_mode","known_limitations")},indent=2),encoding="utf-8")
    return payload

def main():
    ap=argparse.ArgumentParser(description="Rank 20-60 second microdrama promo candidates from timestamped scripts.")
    ap.add_argument("--input",default="data",help="Folder of .txt scripts or screenplay .zip")
    ap.add_argument("--output",default="outputs")
    ap.add_argument("--api-key",default=None,help="Gemini API key; alternatively set GEMINI_API_KEY")
    args=ap.parse_args()
    p=run(Path(args.input),Path(args.output),api_key=args.api_key)
    print(f"Processed {p['episodes_processed']} episodes ({p['episodes_with_events']} with parsed events).")
    print(f"Candidates: {p['candidate_count']} total; {p['single_segment_candidates']} single-segment; {p['multi_segment_candidates']} multi-segment.")
    print(f"Scoring: {p['scoring_mode']}. Outputs: {args.output}/")
    if p.get("gemini_status"):
        print(f"Gemini models used: {p['gemini_status'].get('models_used', [])}")
        print(f"Gemini batches reviewed: {p['gemini_status'].get('batches_reviewed', 0)}")
if __name__=="__main__": main()
