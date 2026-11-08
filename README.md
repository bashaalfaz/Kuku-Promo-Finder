# Kuku Promo Finder — Enhanced

A reusable prototype for **Problem 1: Find the Promos (Ads)** in the Kuku AI Generalist assignment.

## What it does
- Reads all timestamped `.txt` screenplays from a folder or ZIP.
- Parses event start/end timestamps, speaker/action/camera descriptions, scene and episode metadata.
- Generates single-segment 20–60 second candidate clips.
- Generates optional 2-segment montage suggestions (same or different episodes), enforcing a total runtime of 20–60 seconds.
- Ranks candidates using interpretable hook, cliffhanger, dialogue/action density and cut-alignment features.
- Uses Google Gemini semantic reranking when `GEMINI_API_KEY` is configured. It tries `gemini-3.8-flash` up to 3 times, waiting 2 seconds between transient failures, then falls back to `gemini-3.5-flash` for up to 3 attempts with the same retry interval.
- Exports ranked JSON, CSV, per-episode audit and run summary.
- Includes a Streamlit UI for uploading a new ZIP and downloading outputs.

## Requirements
- Python 3.10+
- Core CLI: Python standard library only.
- UI: Streamlit (`pip install -r requirements.txt`).
- Gemini API: create an API key in Google AI Studio and set `GEMINI_API_KEY`. Without a key, deterministic ranking still runs. Gemini reviews the top 60 heuristic candidates in batches of 10. The primary model is `gemini-3.8-flash`; the fallback is `gemini-3.5-flash` (the supported stable Gemini 3.5 Flash model ID).

## VS Code / Windows setup
Open this folder in VS Code, then Terminal → New Terminal.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m unittest discover -s tests -v
python promo_finder.py --input data --output outputs
streamlit run app.py
```

If PowerShell blocks activation, use:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```
Or use Command Prompt:
```bat
py -3 -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
python -m unittest discover -s tests -v
python promo_finder.py --input data --output outputs
streamlit run app.py
```

## CLI on a fresh ZIP
```powershell
python promo_finder.py --input "C:\path\to\new_show.zip" --output outputs_new_show
```
The ZIP may contain nested folders; only `.txt` files are extracted, using safe flattened filenames.

## Gemini API key and automatic failover
Create a Gemini API key in Google AI Studio. PowerShell:
```powershell
$env:GEMINI_API_KEY="your_gemini_api_key"
python promo_finder.py --input data --output outputs_gemini
```
The Streamlit app also accepts the key in its password field. On Streamlit Community Cloud, add this under App Settings → Secrets:
```toml
GEMINI_API_KEY = "your_gemini_api_key"
```

For each batch, the retry policy is:
1. `gemini-3.8-flash`: attempt immediately; on a transient error wait 2 seconds and retry; wait 2 seconds and make the third attempt.
2. If all three primary attempts fail, switch to `gemini-3.5-flash` and use the same three-attempt policy.
3. If both models fail, preserve heuristic rankings and record failure details in `gemini_status` in the JSON output.

Only transient rate-limit, capacity, server and network errors are retried. Invalid API keys and malformed requests are not retried. Never commit API keys, `.env` files or Streamlit secrets. Gemini sees screenplay candidate text only; it does not see video.

## Output files
- `promo_candidates.json`: full structured candidate list, rationale, score breakdown and known limitations.
- `promo_candidates.csv`: spreadsheet-friendly ranked list.
- `episode_audit.json`: parsing and candidate counts for each episode.
- `run_summary.json`: compact execution summary.

Each promo includes a list of segments. A segment contains episode, start, end and duration. A composite may join two separate moments; total runtime is still constrained to 20–60 seconds. For a composite, the editor must confirm chronology, character identity and narrative coherence.

## Quality control
The included tests validate timestamp conversion, parsing, duration bounds, multi-segment total duration, timestamp order, and Gemini retry/failover behavior. The audit reports episodes with no parsed events. The scoring values are **relative editorial triage scores, not calibrated probabilities or proof of promo quality**.

For a real pilot, ask editors to label top candidates as usable/not usable and record rejection reasons. Measure precision@3/10, timestamp correction rate, editor time saved, and recall against manually selected promos.

## Honest limitations (do not hide these)
1. **Video limitation:** supplied inputs are screenplay text, not video. The prototype cannot validate visual action, performance, audio, framing, shot transitions or whether a cut is visually understandable. Human video review is mandatory. To genuinely solve this, ingest licensed episode video and align screenplay timecodes to video/audio; add a multimodal video review stage.
2. **Composite limitation:** multi-segment suggestions use lexical overlap and ranking heuristics. They can join unrelated scenes or spoil story context. Review continuity and chronology.
3. **LLM limitation:** optional LLM review may hallucinate or overrate a beat. It only reranks supplied text and cannot establish truth. Keep its reasoning visible and editor approval mandatory.
4. **Timecode assumption:** screenplay timestamps are assumed to match the final episode timeline. If editing changes runtime, timestamps must be realigned.
5. **No guarantee of perfection:** hook and cliffhanger quality are subjective and depend on the actual cut, acting, sound and audience. The tool finds candidates; editors decide what to publish.

## Tools and AI disclosure
This project was built with Python and Streamlit. ChatGPT assisted with code design, implementation and test drafting. The base pipeline is deterministic and works without paid APIs. The optional LLM adapter uses an OpenAI-compatible endpoint when configured. A human editor remains responsible for final promo selection.
