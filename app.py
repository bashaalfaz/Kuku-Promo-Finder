import json, tempfile, zipfile
from pathlib import Path
import streamlit as st
from promo_finder import run

st.set_page_config(page_title="Kuku Promo Finder",page_icon="🎬",layout="wide")
st.title("🎬 Kuku Promo Finder")
st.caption("Screenplay-to-promo candidate discovery | human editorial approval required")
st.info("Text-only analysis: this app does not inspect finished video, visuals, acting or audio. Use the timestamps to review the actual episode.")
try:
    default_key = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    default_key = ""
api_key = st.text_input("Gemini API key (or configure GEMINI_API_KEY in environment / Streamlit Secrets)", value=default_key, type="password")
st.caption("Failover: Gemini 3.8 Flash × 3 attempts, then Gemini 3.5 Flash × 3 attempts. Two seconds between retries.")
upload=st.file_uploader("Upload a ZIP containing timestamped .txt screenplay episodes",type=["zip"])
if upload and st.button("Analyse screenplay pack",type="primary"):
    with tempfile.TemporaryDirectory() as td:
        zpath=Path(td)/"input.zip"; zpath.write_bytes(upload.getvalue())
        out=Path(td)/"outputs"
        with st.spinner("Parsing episodes and ranking promo candidates..."):
            result=run(zpath,out,api_key=api_key.strip() or None)
            payload=json.loads((out/"promo_candidates.json").read_text())
            st.session_state["payload"]=payload
            st.session_state["files"]={p.name:p.read_bytes() for p in out.iterdir() if p.is_file() and not p.name.startswith("_")}
if "payload" in st.session_state:
    p=st.session_state["payload"]
    c1,c2,c3,c4=st.columns(4)
    c1.metric("Episodes",p["episodes_processed"]); c2.metric("Single-segment",p["single_segment_candidates"])
    c3.metric("Multi-segment",p["multi_segment_candidates"]); c4.metric("Total candidates",p["candidate_count"])
    mode=p["scoring_mode"]; st.write("Scoring mode:",mode)
    gs=p.get("gemini_status", {})
    if mode == "gemini_semantic_reranking":
        st.success(f"Gemini review completed using: {', '.join(gs.get('models_used', []))}")
    else:
        st.warning("Gemini semantic review was unavailable or no API key was configured. Showing deterministic ranking.")
    if gs.get("retry_log"):
        with st.expander("Gemini retry and failover log"):
            st.json(gs["retry_log"])
    promos=p["promos"]
    types=["All","Single segment","Multi-segment"]
    choice=st.selectbox("Candidate type",types)
    filtered=[x for x in promos if choice=="All" or bool(x.get("composite"))==(choice=="Multi-segment")]
    for x in filtered[:100]:
        with st.expander(f"#{x['rank']} · {x['episode']} · {x['duration_seconds']} sec · score {x['score']}"):
            st.write("**Segments**")
            for seg in x["segments"]: st.write(f"{seg['episode']}: {seg['start']} → {seg['end']} ({seg['duration_seconds']} sec)")
            st.write("**Hook:**",x["hook"]); st.write("**Cliffhanger:**",x["cliffhanger"])
            st.write("**Why it may work:**",x["why_it_works"])
            st.json(x["score_breakdown"])
            st.warning("Verify the actual video, continuity, first-3-second hook and unresolved ending before publishing.")
    st.subheader("Download outputs")
    for name,data in st.session_state["files"].items():
        st.download_button(f"Download {name}",data=data,file_name=name)
