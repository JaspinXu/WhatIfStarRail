from __future__ import annotations

import base64
import html
import os
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from astral_agents.config import load_scenario  # noqa: E402
from astral_agents.domain.models import RunConfig, RunStatus  # noqa: E402
from astral_agents.evaluation.metrics import evaluate_run  # noqa: E402
from astral_agents.exporter import DISCLAIMER, build_demo_archive  # noqa: E402
from astral_agents.simulation.engine import SimulationEngine  # noqa: E402
from astral_agents.simulation.observation import build_observation  # noqa: E402
from astral_agents.storage.repository import SQLiteRepository  # noqa: E402

st.set_page_config(
    page_title="Astral Narrative Agents",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
:root {
  --void: #050612;
  --surface: rgba(16, 19, 43, .88);
  --surface-2: rgba(25, 28, 60, .82);
  --line: rgba(184, 198, 255, .18);
  --text: #f4f6ff;
  --muted: #a3acd0;
  --cyan: #68e8ef;
  --amber: #f9d786;
  --purple: #b59aff;
  --pink: #ff82bb;
  --danger: #ff6f91;
}
.stApp {
  background:
    radial-gradient(circle at 84% 8%, rgba(104,232,239,.14), transparent 25rem),
    radial-gradient(circle at 14% 34%, rgba(181,154,255,.15), transparent 30rem),
    radial-gradient(circle at 70% 72%, rgba(255,130,187,.08), transparent 26rem),
    linear-gradient(150deg, #050612 0%, #0b1027 48%, #080a1b 100%);
  color: var(--text);
}
.stApp:before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  opacity: .32;
  background-image:
    radial-gradient(circle, rgba(244,246,255,.72) 0 1px, transparent 1.5px),
    radial-gradient(circle, rgba(104,232,239,.58) 0 1px, transparent 1.5px),
    linear-gradient(118deg, transparent 49.9%, rgba(181,154,255,.06) 50%, transparent 50.2%);
  background-size: 79px 79px, 131px 131px, 28rem 28rem;
  background-position: 12px 18px, 39px 62px;
}
[data-testid="stSidebar"] {
  background:
    linear-gradient(180deg, rgba(12,14,34,.98), rgba(7,9,24,.98)),
    radial-gradient(circle at 50% 0%, rgba(104,232,239,.08), transparent 20rem);
  border-right: 1px solid rgba(104,232,239,.18);
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
  color: #b5c3d7;
}
.block-container {
  max-width: 1500px;
  padding-top: 1.35rem;
  padding-bottom: 3rem;
}
h1, h2, h3 { letter-spacing: -.025em; color: var(--text) !important; }
p, label, [data-testid="stCaptionContainer"] { color: #b9c7d9; }
.hero {
  position: relative;
  overflow: hidden;
  padding: 1.5rem 1.7rem;
  margin-bottom: 1.1rem;
  border: 1px solid rgba(104,232,239,.25);
  border-radius: 18px 5px 18px 5px;
  background:
    linear-gradient(105deg, rgba(17,21,48,.97), rgba(11,16,38,.78)),
    radial-gradient(circle at 90% 0%, rgba(104,232,239,.2), transparent 25rem);
  box-shadow: 0 22px 70px rgba(0,0,0,.28), inset 0 1px rgba(255,255,255,.05);
}
.hero:after {
  content: "✦";
  position: absolute;
  right: 1.4rem;
  top: -.8rem;
  font-size: 7rem;
  line-height: 1;
  color: rgba(104,232,239,.09);
}
.eyebrow {
  color: var(--cyan);
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .18em;
  text-transform: uppercase;
}
.hero-title {
  margin-top: .35rem;
  color: var(--text);
  font-size: clamp(2rem, 4vw, 3.65rem);
  font-weight: 760;
  line-height: 1.02;
  letter-spacing: -.055em;
}
.hero-sub {
  max-width: 58rem;
  margin-top: .7rem;
  color: #a8b9ce;
  font-size: .98rem;
  line-height: 1.65;
}
.mission-stage {
  position: relative;
  min-height: 29rem;
  margin-bottom: 1.15rem;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1.12fr) minmax(24rem, .88fr);
  align-items: stretch;
  border: 1px solid rgba(142,169,255,.28);
  border-radius: 26px 7px 26px 7px;
  background:
    linear-gradient(100deg, rgba(9,12,31,.98) 0%, rgba(16,20,49,.92) 54%, rgba(25,22,55,.66) 100%),
    radial-gradient(circle at 82% 32%, rgba(255,130,187,.22), transparent 24rem);
  box-shadow: 0 30px 90px rgba(0,0,0,.42), inset 0 1px rgba(255,255,255,.06);
}
.mission-stage:before {
  content:""; position:absolute; inset:0; pointer-events:none;
  background:
    linear-gradient(90deg, transparent 0 68%, rgba(104,232,239,.09) 68.15%, transparent 68.3%),
    linear-gradient(0deg, transparent 0 82%, rgba(249,215,134,.12) 82.15%, transparent 82.3%);
}
.mission-stage.ai-stage {
  display:block;
  background-size:cover;
  background-position:center;
}
.mission-stage.ai-stage:after {
  content:""; position:absolute; inset:0; pointer-events:none;
  background:linear-gradient(90deg, rgba(5,8,23,.34), transparent 58%);
}
.mission-stage.ai-stage .mission-copy { width:min(64%, 52rem); min-height:29rem; }
.mission-copy {
  position: relative; z-index: 2;
  padding: clamp(2rem, 4vw, 4.25rem);
  display:flex; flex-direction:column; justify-content:center;
}
.mission-code {
  color: var(--amber); font-size:.7rem; font-weight:850; letter-spacing:.22em;
  text-transform:uppercase; margin-bottom:1rem;
}
.mission-title {
  max-width: 44rem; color:var(--text); font-size:clamp(2.5rem,4.8vw,5rem);
  line-height:.98; letter-spacing:-.065em; font-weight:850;
  text-shadow: 0 0 42px rgba(181,154,255,.18);
}
.mission-title em { color:var(--cyan); font-style:normal; }
.mission-sub {
  max-width: 40rem; margin-top:1.25rem; color:#b8c2df; font-size:.98rem; line-height:1.75;
}
.mission-art {
  position:relative; min-height:29rem; display:flex; align-items:flex-end; justify-content:center;
  background:
    radial-gradient(circle at 55% 45%, rgba(104,232,239,.18), transparent 38%),
    linear-gradient(145deg, transparent, rgba(181,154,255,.08));
}
.mission-art img {
  position:absolute; z-index:1; width:min(43rem,118%); height:112%;
  bottom:-10%; right:-5%; object-fit:contain;
  filter:drop-shadow(0 30px 42px rgba(0,0,0,.55));
  animation:astral-float 7s ease-in-out infinite;
}
.mission-seal {
  position:absolute; z-index:2; right:1.1rem; bottom:1rem;
  padding:.5rem .7rem; border:1px solid rgba(249,215,134,.35);
  background:rgba(8,10,27,.72); color:#f7dfaa; font-size:.62rem; letter-spacing:.12em;
}
@keyframes astral-float { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-9px)} }
.status-row { display:flex; gap:.45rem; flex-wrap:wrap; margin-top:1rem; }
.pill {
  display:inline-flex;
  align-items:center;
  gap:.35rem;
  padding:.33rem .65rem;
  border:1px solid var(--line);
  border-radius:999px;
  background:rgba(7,9,27,.58);
  color:#c6d3e4;
  font-size:.76rem;
  font-weight:650;
}
.pill.ok { border-color:rgba(88,214,199,.35); color:#83e2d7; }
.pill.warn { border-color:rgba(244,199,107,.35); color:#f4c76b; }
.pill.error { border-color:rgba(255,107,122,.42); color:#ff8794; }
.metric-card {
  min-height: 7.2rem;
  padding: 1rem 1.05rem;
  border: 1px solid var(--line);
  border-radius: 15px 4px 15px 4px;
  background:
    linear-gradient(160deg, rgba(26,30,65,.92), rgba(11,15,37,.86)),
    radial-gradient(circle at 100% 0%, rgba(104,232,239,.08), transparent 10rem);
  box-shadow: inset 0 1px rgba(255,255,255,.035);
}
.metric-label { color:var(--muted); font-size:.74rem; font-weight:700; letter-spacing:.08em; }
.metric-value { color:var(--text); font-size:1.75rem; font-weight:760; margin-top:.45rem; }
.metric-note { color:#7890aa; font-size:.72rem; margin-top:.18rem; }
.section-kicker { color:var(--cyan); font-size:.72rem; font-weight:800; letter-spacing:.14em; margin-bottom:.2rem; }
.action-card {
  height: 100%;
  min-height: 13rem;
  padding: 1rem;
  border: 1px solid var(--line);
  border-top: 3px solid var(--actor-color, var(--cyan));
  border-radius: 15px 4px 15px 4px;
  background: linear-gradient(150deg, rgba(25,29,64,.9), rgba(10,14,35,.82));
  box-shadow: 0 14px 32px rgba(0,0,0,.16);
}
.action-head { display:flex; align-items:center; gap:.55rem; margin-bottom:.75rem; }
.sigil {
  width:2rem;height:2rem;border-radius:10px;display:inline-grid;place-items:center;
  background:color-mix(in srgb, var(--actor-color) 15%, transparent);
  color:var(--actor-color);font-weight:800;
}
.actor-name { color:var(--text);font-weight:750; }
.action-type { color:var(--cyan);font-size:.72rem;text-transform:uppercase;letter-spacing:.08em; }
.action-body { color:#b4c3d5;font-size:.84rem;line-height:1.52; }
.action-result {
  margin-top:.7rem;padding-top:.65rem;border-top:1px solid var(--line);
  color:#dae5f4;font-size:.78rem;line-height:1.48;
}
.diff {
  display:flex;justify-content:space-between;gap:1rem;padding:.65rem .1rem;
  border-bottom:1px solid var(--line);font-size:.84rem;
}
.diff-label { color:#b8c7d9; }
.diff-value { color:var(--cyan);font-family:ui-monospace,SFMono-Regular,Consolas,monospace; }
.timeline-item {
  position:relative;margin-left:.65rem;padding:0 0 1rem 1.25rem;
  border-left:1px solid rgba(88,214,199,.25);
}
.timeline-item:before {
  content:"";position:absolute;left:-.28rem;top:.25rem;width:.52rem;height:.52rem;
  border-radius:50%;background:var(--cyan);box-shadow:0 0 0 4px rgba(88,214,199,.09);
}
.timeline-id { color:#7187a1;font-size:.69rem;font-family:ui-monospace,Consolas,monospace; }
.timeline-copy { color:#c4d1e1;font-size:.82rem;line-height:1.5;margin-top:.2rem; }
.chapter-card {
  margin-bottom:1rem;padding:1.3rem 1.35rem;border:1px solid var(--line);
  border-radius:18px 5px 18px 5px;background:linear-gradient(145deg,rgba(25,29,64,.92),rgba(18,20,48,.78));
}
.chapter-no {color:var(--purple);font-size:.7rem;font-weight:800;letter-spacing:.12em;}
.chapter-title {color:var(--text);font-size:1.28rem;font-weight:750;margin:.3rem 0 .55rem;}
.chapter-body {color:#b8c7d9;font-size:.87rem;line-height:1.75;white-space:pre-wrap;}
.audit-banner {
  padding:.85rem 1rem;border:1px solid rgba(184,156,244,.38);border-radius:13px;
  background:rgba(184,156,244,.08);color:#d9c9ff;font-size:.84rem;
}
.readonly-banner {
  padding:.75rem 1rem;border:1px solid rgba(88,214,199,.3);border-radius:12px;
  background:rgba(88,214,199,.06);color:#9de9e0;font-size:.82rem;
}
.layer {
  padding:1.1rem;border:1px solid var(--line);border-radius:15px 4px 15px 4px;min-height:9rem;
  background:linear-gradient(145deg,rgba(24,28,62,.84),rgba(10,14,34,.78));
}
.layer-title {font-weight:760;color:var(--text);margin-bottom:.45rem;}
.layer-copy {font-size:.82rem;color:#9eb0c6;line-height:1.55;}
.sidebar-brand { padding:.25rem 0 1rem; }
.sidebar-mark {color:var(--amber);font-size:1.45rem;text-shadow:0 0 20px rgba(249,215,134,.45);}
.sidebar-title {color:var(--text);font-weight:760;font-size:1.05rem;}
.sidebar-caption {color:#7289a2;font-size:.72rem;line-height:1.45;margin-top:.3rem;}
.legal {
  margin-top:1rem;padding-top:1rem;border-top:1px solid var(--line);
  color:#647b94;font-size:.66rem;line-height:1.45;
}
[data-testid="stMetric"] {
  border:1px solid var(--line);border-radius:14px;padding:.8rem;background:rgba(15,28,46,.7);
}
[data-testid="stProgressBar"] > div > div { background-color:var(--cyan); }
div[data-testid="stTabs"] button { color:#9fb0c5; }
div[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap:.4rem; padding:.35rem; border:1px solid var(--line); border-radius:15px 4px 15px 4px;
  background:rgba(9,12,31,.72);
}
div[data-testid="stTabs"] button {
  border-radius:10px 3px 10px 3px; padding:.7rem 1rem;
}
div[data-testid="stTabs"] button[aria-selected="true"] {
  color:#07131d; background:linear-gradient(135deg,var(--cyan),#a9f4ef);
}
.stButton > button, .stDownloadButton > button {
  border-radius:12px 4px 12px 4px;border:1px solid rgba(104,232,239,.3);
  background:rgba(17,21,48,.82); transition:all .18s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color:rgba(104,232,239,.72); transform:translateY(-1px);
  box-shadow:0 9px 24px rgba(33,205,212,.12);
}
.stButton > button[kind="primary"] {
  background:linear-gradient(135deg,#4ddce3,#6078e8);border:none;color:#07131d;font-weight:800;
}
.character-dossier {
  position:relative; min-height:35rem; overflow:hidden;
  border:1px solid color-mix(in srgb, var(--actor-color) 42%, var(--line));
  border-radius:22px 5px 22px 5px;
  background:
    radial-gradient(circle at 50% 35%, color-mix(in srgb, var(--actor-color) 18%, transparent), transparent 42%),
    linear-gradient(155deg,rgba(23,27,60,.95),rgba(8,11,29,.92));
}
.character-dossier:after {
  content:"ARCHIVE / VERIFIED"; position:absolute; top:1rem; right:1rem;
  color:color-mix(in srgb, var(--actor-color) 70%, white); font-size:.6rem; letter-spacing:.18em;
}
.character-dossier img {
  width:100%; height:27rem; object-fit:contain; object-position:center bottom;
  filter:drop-shadow(0 24px 35px rgba(0,0,0,.5));
}
.dossier-copy { padding:0 1.25rem 1.25rem; position:relative; z-index:2; }
.dossier-name { color:var(--text); font-size:1.75rem; font-weight:850; letter-spacing:-.035em; }
.dossier-role { color:var(--actor-color); font-size:.7rem; font-weight:850; letter-spacing:.14em; text-transform:uppercase; }
.dossier-summary { color:#aeb9d6; font-size:.82rem; line-height:1.6; margin-top:.55rem; }
.official-note {
  margin-top:.55rem; padding:.55rem .7rem; border-left:2px solid var(--amber);
  background:rgba(249,215,134,.06); color:#b8b6c6; font-size:.67rem; line-height:1.5;
}
.comms-shell {
  position:relative; padding:.9rem; border:1px solid rgba(104,232,239,.2);
  border-radius:18px 5px 18px 5px;
  background:linear-gradient(150deg,rgba(12,16,39,.94),rgba(8,11,27,.9));
  box-shadow:inset 0 1px rgba(255,255,255,.035);
}
.comms-head {
  display:flex; justify-content:space-between; gap:1rem; align-items:center;
  padding:.35rem .45rem .8rem; border-bottom:1px solid var(--line);
}
.comms-title {color:var(--cyan);font-size:.7rem;font-weight:850;letter-spacing:.16em;}
.comms-live {color:#8ff6cf;font-size:.64rem;letter-spacing:.1em;}
.comms-live:before {
  content:""; display:inline-block; width:.48rem; height:.48rem; margin-right:.35rem;
  border-radius:50%; background:#65efb9; box-shadow:0 0 12px #65efb9;
}
.comms-round {color:#7380a9;font-size:.64rem;letter-spacing:.12em;margin:.95rem .45rem .5rem;}
.comms-entry {
  display:grid; grid-template-columns:2.45rem minmax(0,1fr); gap:.72rem;
  align-items:start; margin:.58rem .25rem;
}
.comms-sigil {
  width:2.45rem;height:2.45rem;display:grid;place-items:center;
  border:1px solid color-mix(in srgb,var(--actor-color) 65%,transparent);
  border-radius:12px 3px 12px 3px;
  background:color-mix(in srgb,var(--actor-color) 14%,rgba(9,12,31,.9));
  color:var(--actor-color);font-weight:900;
  box-shadow:0 0 18px color-mix(in srgb,var(--actor-color) 13%,transparent);
}
.comms-meta {display:flex;gap:.55rem;align-items:baseline;margin:0 0 .28rem .15rem;}
.comms-name {color:var(--text);font-size:.74rem;font-weight:800;}
.comms-action {color:#7683aa;font-size:.6rem;letter-spacing:.09em;text-transform:uppercase;}
.comms-bubble {
  padding:.68rem .82rem; border:1px solid color-mix(in srgb,var(--actor-color) 23%,var(--line));
  border-radius:4px 13px 13px 13px;
  background:linear-gradient(135deg,color-mix(in srgb,var(--actor-color) 8%,rgba(25,29,62,.9)),rgba(12,15,36,.88));
  color:#e1e6f7;font-size:.82rem;line-height:1.56;
}
.comms-narration {
  margin:.3rem 0 .2rem 3.45rem; padding-left:.75rem;
  border-left:1px solid rgba(249,215,134,.32); color:#8e97b8;font-size:.68rem;line-height:1.45;
}
@media (max-width: 900px) {
  .mission-stage { grid-template-columns:1fr; min-height:auto; }
  .mission-art { min-height:22rem; order:-1; }
  .mission-art img { height:110%; width:100%; right:0; }
  .mission-copy { padding:2rem 1.35rem 2.4rem; }
  .mission-title { font-size:clamp(2.3rem,12vw,4rem); }
  .mission-stage.ai-stage .mission-copy { width:100%; min-height:32rem; padding-top:17rem; }
  .mission-stage.ai-stage { background-position:66% center; }
}
#MainMenu, footer {visibility:hidden;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

DB_PATH = Path(os.getenv("ASTRAL_DATABASE", ROOT / "runs" / "astral.sqlite"))
ASSET_DIR = ROOT / "app" / "assets"
AI_HERO_ART = ASSET_DIR / "ui" / "march-comm-hero-v1.png"
OFFICIAL_CHARACTER_URL = "https://hsr.hoyoverse.com/zh-cn/character"
CHARACTER_MEDIA = {
    "march_7th": {
        "art": ASSET_DIR / "characters" / "march-7th.png",
        "voice": ASSET_DIR / "voices" / "march-7th.mp3",
        "cv": "诺亚",
    },
    "dan_heng": {
        "art": ASSET_DIR / "characters" / "dan-heng.png",
        "voice": ASSET_DIR / "voices" / "dan-heng.mp3",
        "cv": "李春胤",
    },
    "himeko": {
        "art": ASSET_DIR / "characters" / "himeko.png",
        "voice": ASSET_DIR / "voices" / "himeko.mp3",
        "cv": "林簌",
    },
    "welt": {
        "art": ASSET_DIR / "characters" / "welt.png",
        "voice": ASSET_DIR / "voices" / "welt.mp3",
        "cv": "彭博",
    },
}


@st.cache_data(show_spinner=False)
def image_data_uri(path: str) -> str:
    encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@st.cache_resource
def context(database_path: str):
    bundle = load_scenario(ROOT / "scenarios" / "sealed_transport")
    repository = SQLiteRepository(database_path)
    return bundle, repository, SimulationEngine(bundle, repository)


bundle, repository, engine = context(str(DB_PATH.resolve()))


def status_label(status: RunStatus) -> tuple[str, str]:
    labels = {
        RunStatus.READY: ("等待首轮", "warn"),
        RunStatus.RUNNING: ("调查进行中", "ok"),
        RunStatus.PAUSED: ("已暂停", "warn"),
        RunStatus.SUCCEEDED: ("任务完成", "ok"),
        RunStatus.FAILED: ("撤离 / 失败", "error"),
        RunStatus.BLOCKED: ("审计阻断", "error"),
    }
    return labels[status]


def fmt_value(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def select_run(run_id: str) -> None:
    st.session_state.selected_run = run_id


def create_run(*, complete: bool) -> None:
    policy = st.session_state.get("policy", "heuristic")
    if policy == "llm" and not os.getenv("OPENAI_API_KEY"):
        policy = "heuristic"
    run_id = engine.create_run(
        RunConfig(
            scenario_id=bundle.scenario.id,
            seed=int(st.session_state.get("seed", 42)),
            policy=policy,
            memory_strategy=st.session_state.get(
                "memory_strategy", "event_retrieval"
            ),
            model=os.getenv("ASTRAL_OPENAI_MODEL", "gpt-5.6-sol"),
            story_background=st.session_state.get(
                "story_background",
                bundle.scenario.premise,
            ),
        )
    )
    if complete:
        advance_live(run_id)
    select_run(run_id)


def advance_live(run_id: str, rounds: int | None = None) -> None:
    live = st.status("通讯频道已建立 · 等待角色回应…", expanded=True)
    completed = 0
    while rounds is None or completed < rounds:
        current = repository.get_state(run_id)
        if current.status in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.BLOCKED,
        }:
            break
        record = engine.step(run_id)
        completed += 1
        live.markdown(f"**ROUND {record.round_no:02d}**")
        for action in record.actions:
            profile = bundle.character_map[action.actor_id]
            live.write(
                f"{profile.display_name}："
                f"{action.public_content or '我会继续观察。'}"
            )
    final_state = repository.get_state(run_id)
    live.update(
        label=f"通讯同步完成 · 第 {final_state.round_no} 轮",
        state="complete",
        expanded=False,
    )


def dialogue_feed_markup(records: list, *, limit_rounds: int = 6) -> str:
    action_labels = {
        "investigate": "现场核验",
        "reveal": "共享证据",
        "move": "位置转移",
        "use_resource": "系统操作",
        "ask": "询问",
        "speak": "发言",
        "negotiate": "协商",
        "assist": "协助",
        "oppose": "反对",
        "wait": "观察",
    }
    visible = records[-limit_rounds:]
    parts = [
        '<div class="comms-shell"><div class="comms-head">'
        '<span class="comms-title">ASTRAL EXPRESS / LIVE COMMS</span>'
        '<span class="comms-live">CHANNEL OPEN</span></div>'
    ]
    for record in visible:
        parts.append(
            f'<div class="comms-round">ROUND {record.round_no:02d} · '
            f'{len(record.actions)} ACTIVE AGENTS</div>'
        )
        for action in record.actions:
            profile = bundle.character_map[action.actor_id]
            caused = next(
                (
                    event
                    for event in record.events
                    if action.id in event.caused_by_action_ids
                ),
                None,
            )
            dialogue = action.public_content or "我会继续观察。"
            parts.append(
                f'<div class="comms-entry" style="--actor-color:{profile.color}">'
                f'<div class="comms-sigil">{profile.sigil}</div><div>'
                f'<div class="comms-meta"><span class="comms-name">'
                f'{html.escape(profile.display_name)}</span>'
                f'<span class="comms-action">'
                f'{html.escape(action_labels.get(action.action_type.value, action.action_type.value))}'
                f'</span></div><div class="comms-bubble">'
                f'{html.escape(dialogue)}</div></div></div>'
            )
            if caused and caused.public_summary and caused.public_summary != dialogue:
                parts.append(
                    '<div class="comms-narration">动作转述 · '
                    f'{html.escape(caused.public_summary)}</div>'
                )
    parts.append("</div>")
    return "".join(parts)


with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
          <div class="sidebar-mark">✦</div>
          <div class="sidebar-title">ASTRAL / 星轨观测站</div>
          <div class="sidebar-caption">叙事智能体任务终端<br>SEALED ROUTE · 01</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("场景")
    st.selectbox(
        "场景",
        [bundle.scenario.title],
        label_visibility="collapsed",
        disabled=True,
    )
    st.selectbox(
        "运行策略",
        ["heuristic", "scripted", "llm"],
        format_func={
            "heuristic": "离线启发式（推荐）",
            "scripted": "固定示例轨迹",
            "llm": "OpenAI 实时决策",
        }.get,
        key="policy",
    )
    if st.session_state.policy == "llm" and not os.getenv("OPENAI_API_KEY"):
        st.warning("未配置 OPENAI_API_KEY；新运行会安全回退到离线策略。")
    with st.expander("实验参数", expanded=False):
        st.number_input("随机种子", min_value=0, max_value=999999, value=42, key="seed")
        st.selectbox(
            "记忆策略",
            ["event_retrieval", "recent_only", "none"],
            format_func={
                "event_retrieval": "事件检索记忆",
                "recent_only": "仅最近记忆",
                "none": "无长期记忆",
            }.get,
            key="memory_strategy",
        )
        st.caption(f"数据库 · {DB_PATH.name}")
    with st.expander("故事工作室", expanded=False):
        st.text_area(
            "本次故事背景",
            value=bundle.scenario.premise,
            height=180,
            key="story_background",
            help=(
                "新建运行时会固化到该档案，并作为所有角色共同知道的背景；"
                "角色仍只能依据各自观察、记忆和已共享线索行动。"
            ),
        )
        st.caption("修改后请新建运行；已有档案会保留创建时的背景。")
    quick_col, blank_col = st.columns(2)
    with quick_col:
        if st.button("快速演示", type="primary", width="stretch"):
            with st.spinner("正在重建 10 轮事件链…"):
                create_run(complete=True)
            st.rerun()
    with blank_col:
        if st.button("单步新建", width="stretch"):
            create_run(complete=False)
            st.rerun()

    runs = repository.list_runs()
    if runs:
        run_options = [item["run_id"] for item in runs]
        current_id = st.session_state.get("selected_run")
        if current_id not in run_options:
            current_id = run_options[0]
            select_run(current_id)
        selected = st.selectbox(
            "运行档案",
            run_options,
            index=run_options.index(current_id),
            format_func=lambda item: (
                f"{item.split('-')[-1]} · "
                f"R{next(row['current_round'] for row in runs if row['run_id'] == item):02d}"
            ),
        )
        if selected != st.session_state.get("selected_run"):
            select_run(selected)
            st.rerun()
    st.markdown(f'<div class="legal">{html.escape(DISCLAIMER)}</div>', unsafe_allow_html=True)


selected_run = st.session_state.get("selected_run")
if not selected_run:
    ai_hero = image_data_uri(str(AI_HERO_ART))
    st.markdown(
        f"""
        <div class="mission-stage ai-stage" style="background-image:url('{ai_hero}')">
          <div class="mission-copy">
            <div class="mission-code">Astral narrative protocol / 01</div>
            <div class="mission-title">每个人只看见<br><em>自己的星轨</em></div>
            <div class="mission-sub">{html.escape(st.session_state.get("story_background", bundle.scenario.premise))}</div>
            <div class="status-row">
              <span class="pill ok">✓ 无需 API Key</span>
              <span class="pill">事件溯源</span>
              <span class="pill">私有记忆</span>
              <span class="pill">确定性回放</span>
            </div>
          </div>
          <div class="mission-seal">AI-EDITED UI ART · SOURCE: HoYoverse CHARACTER ART</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_a, col_b, col_c = st.columns([1.15, 1, 1])
    layers = [
        ("01 / 公开设定", "不可被模型修改的最小角色事实，均附公开来源。"),
        ("02 / 场景真相", "只由确定性事件与 reducer 更新的唯一世界状态。"),
        ("03 / 角色认知", "可能不完整或错误；每条记忆都保留事件来源。"),
    ]
    for column, (title, copy) in zip(
        [col_a, col_b, col_c], layers, strict=True
    ):
        with column:
            st.markdown(
                f'<div class="layer"><div class="layer-title">{title}</div>'
                f'<div class="layer-copy">{copy}</div></div>',
                unsafe_allow_html=True,
            )
    st.info("从左侧点击“快速演示”可直接加载完整轨迹；点击“单步新建”可亲自推进每一轮。")
    st.stop()

state = repository.get_state(selected_run)
manifest = repository.get_manifest(selected_run)
label, label_class = status_label(state.status)
metrics = evaluate_run(repository, selected_run)
run_code = selected_run.split("-")[-1].upper()
himeko_art = image_data_uri(str(CHARACTER_MEDIA["himeko"]["art"]))
story_excerpt = " ".join(
    (state.story_background or bundle.scenario.premise).split()
)
if len(story_excerpt) > 220:
    story_excerpt = f"{story_excerpt[:220].rstrip()}…"

st.markdown(
    f"""
    <div class="mission-stage" style="min-height:23rem">
      <div class="mission-copy" style="padding-block:2.25rem">
        <div class="mission-code">Mission / {run_code} · Live archive</div>
        <div class="mission-title" style="font-size:clamp(2.5rem,4.2vw,4.5rem)">{html.escape(bundle.scenario.title)}</div>
        <div class="mission-sub">{html.escape(story_excerpt)}</div>
        <div class="status-row">
          <span class="pill {label_class}">● {label}</span>
          <span class="pill">第 {state.round_no} / {bundle.scenario.max_rounds} 轮</span>
          <span class="pill ok">✓ 状态有效</span>
          <span class="pill {'error' if metrics['leakage_findings'] else 'ok'}">越界知情 {metrics['leakage_findings']}</span>
          <span class="pill">种子 {manifest.seed}</span>
        </div>
      </div>
      <div class="mission-art" style="min-height:23rem">
        <img src="{himeko_art}" alt="姬子官方角色立绘" style="height:122%;bottom:-25%">
        <div class="mission-seal">NAVIGATOR / HIMEKO</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

terminal = state.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.BLOCKED}
control_1, control_2, control_3, spacer = st.columns([1, 1, 1.15, 3])
with control_1:
    if st.button("推进一轮", type="primary", disabled=terminal, width="stretch"):
        advance_live(selected_run, rounds=1)
        st.rerun()
with control_2:
    if st.button("推进三轮", disabled=terminal, width="stretch"):
        advance_live(selected_run, rounds=3)
        st.rerun()
with control_3:
    if st.button("运行至结局", disabled=terminal, width="stretch"):
        advance_live(selected_run)
        st.rerun()

tabs = st.tabs(["运行台", "角色视角", "回放", "章节与导出", "研究说明"])

with tabs[0]:
    with st.expander("本档案的故事背景", expanded=False):
        st.write(state.story_background or bundle.scenario.premise)
        st.caption("该背景已在建档时固化，并进入每名角色的 ObservationPacket。")
    round_records = repository.get_rounds(selected_run)
    if round_records:
        st.markdown(
            dialogue_feed_markup(round_records),
            unsafe_allow_html=True,
        )
        st.write("")
    else:
        st.info("推进首轮后，四名角色的显式对白会在这里按轮次实时展开。")
    st.markdown('<div class="section-kicker">WORLD PULSE</div>', unsafe_allow_html=True)
    metric_cols = st.columns(5)
    metric_data = [
        ("阶段", state.phase, "状态机当前阶段"),
        ("证据完整度", f"{state.resources['evidence']:g}/10", "已确认且可追溯"),
        ("开放悬念", str(len(state.open_threads)), " / ".join(state.open_threads) or "全部关闭"),
        ("已确认事件", str(metrics["events"]), f"{metrics['actions']} 个行动"),
        ("状态摘要", state.state_digest()[:8], "确定性快照"),
    ]
    for column, (metric_label, value, note) in zip(
        metric_cols, metric_data, strict=True
    ):
        with column:
            st.markdown(
                f"""
                <div class="metric-card">
                  <div class="metric-label">{html.escape(metric_label)}</div>
                  <div class="metric-value">{html.escape(value)}</div>
                  <div class="metric-note">{html.escape(note)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.write("")
    left, right = st.columns([1.65, 1])
    with left:
        st.subheader("本轮行动链")
        if state.round_no == 0:
            st.info("尚未推进。首轮将从同一个世界快照为四名角色分别构建观察包。")
        else:
            record = repository.get_round(selected_run, state.round_no)
            action_cols = st.columns(4)
            action_labels = {
                "investigate": "调查",
                "reveal": "共享",
                "move": "移动",
                "use_resource": "修复",
                "ask": "询问",
                "wait": "观察",
            }
            for column, action in zip(
                action_cols, record.actions, strict=True
            ):
                profile = bundle.character_map[action.actor_id]
                caused = next(
                    (
                        event
                        for event in record.events
                        if action.id in event.caused_by_action_ids
                    ),
                    None,
                )
                with column:
                    st.markdown(
                        f"""
                        <div class="action-card" style="--actor-color:{profile.color}">
                          <div class="action-head">
                            <span class="sigil">{profile.sigil}</span>
                            <div>
                              <div class="actor-name">{html.escape(profile.display_name)}</div>
                              <div class="action-type">{action_labels.get(action.action_type.value, action.action_type.value)}</div>
                            </div>
                          </div>
                          <div class="action-body">{html.escape(action.rationale or '依据当前观察选择保守行动。')}</div>
                          <div class="action-result">→ {html.escape(caused.public_summary if caused and caused.public_summary else '已记录行动意图')}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        st.write("")
        st.subheader("人员位置")
        location_cols = st.columns(len(bundle.scenario.locations))
        for column, location in zip(
            location_cols, bundle.scenario.locations, strict=True
        ):
            occupants = [
                bundle.character_map[character_id]
                for character_id, location_id in state.locations.items()
                if location_id == location.id
            ]
            with column:
                st.caption(location.display_name)
                if occupants:
                    for person in occupants:
                        st.markdown(
                            f"<span class='pill' style='border-color:{person.color}55'>"
                            f"{person.sigil} {html.escape(person.display_name)}</span>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption("无人")
    with right:
        st.subheader("资源窗口")
        for resource in bundle.scenario.resources:
            value = state.resources[resource.id]
            ratio = max(0.0, min(1.0, value / resource.maximum))
            st.caption(f"{resource.display_name} · {value:g}{resource.unit}")
            st.progress(ratio)
        st.write("")
        st.subheader("最近状态变化")
        if state.round_no:
            record = repository.get_round(selected_run, state.round_no)
            visible_diffs = record.diffs[-8:]
            if visible_diffs:
                for diff in visible_diffs:
                    st.markdown(
                        f'<div class="diff"><span class="diff-label">{html.escape(diff.label)}</span>'
                        f'<span class="diff-value">{html.escape(fmt_value(diff.before))} → '
                        f'{html.escape(fmt_value(diff.after))}</span></div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("本轮没有世界状态变化。")
        else:
            st.caption("推进后将在这里显示 before / after。")

    st.write("")
    st.subheader("已确认事件时间线")
    timeline = repository.get_events(selected_run)[-14:]
    for event in reversed(timeline):
        visibility = "所有人可见" if "public" in event.tags else f"{len(event.observers)} 名现场角色可见"
        st.markdown(
            f"""
            <div class="timeline-item">
              <div class="timeline-id">{html.escape(event.id)} · {html.escape(visibility)}</div>
              <div class="timeline-copy">{html.escape(event.public_summary or '仅包含定向私密载荷')}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

with tabs[1]:
    audit_mode = st.toggle("研究者审计模式", value=False)
    if audit_mode:
        st.markdown(
            '<div class="audit-banner">◆ 审计模式已开启：可比较各角色的已知集合。'
            "普通角色决策接口永远不会收到这张全局矩阵。</div>",
            unsafe_allow_html=True,
        )
        st.write("")
    selected_character = st.selectbox(
        "选择角色视角",
        [character.id for character in bundle.characters],
        format_func=lambda character_id: bundle.character_map[character_id].display_name,
    )
    profile = bundle.character_map[selected_character]
    media = CHARACTER_MEDIA[selected_character]
    current_record = (
        repository.get_round(selected_run, state.round_no)
        if state.round_no
        else None
    )
    decision_state = current_record.state_before if current_record else state
    events_to_now = repository.get_events(
        selected_run, end_round=decision_state.round_no
    )
    observation = build_observation(
        selected_character, decision_state, events_to_now, bundle
    )
    own_memories = [
        memory
        for memory in repository.get_memories(selected_run, selected_character)
        if memory.created_round <= decision_state.round_no
    ]
    own_beliefs = [
        belief
        for belief in repository.get_beliefs(selected_run, selected_character)
        if belief.last_updated_round <= decision_state.round_no
    ]
    perspective_label = (
        f"第 {state.round_no} 轮行动前"
        if current_record
        else "轮 0 初始简报后"
    )

    role_left, role_right = st.columns([1.15, 1.35])
    with role_left:
        st.markdown(
            f"""
            <div class="character-dossier" style="--actor-color:{profile.color}">
              <img src="{image_data_uri(str(media['art']))}" alt="{html.escape(profile.display_name)}官方角色立绘">
              <div class="dossier-copy">
                <div class="dossier-role">{profile.sigil} · {html.escape(profile.strategy.role)}</div>
                <div class="dossier-name">{html.escape(profile.display_name)}</div>
                <div class="dossier-summary">{html.escape(profile.public_summary)}</div>
                <div class="official-note">立绘与下方中文语音片段来自《崩坏：星穹铁道》官方角色站，仅用于本非商业研究演示；角色与素材权利归 HoYoverse / 相关权利人所有。</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(f"角色语音 · 中文 CV：{media['cv']}")
        st.audio(str(media["voice"]), format="audio/mpeg")
        st.markdown(f"[查看官方角色资料 ↗]({OFFICIAL_CHARACTER_URL})")
        st.write("")
        st.subheader(f"{perspective_label}实际观察")
        st.markdown(f"**所在位置** · {bundle.scenario.location_map[observation.current_location].display_name}")
        st.markdown(
            f"**现场成员** · "
            f"{'、'.join(bundle.character_map[item].display_name for item in observation.visible_characters) or '无'}"
        )
        st.markdown(
            f"**可访问事件** · {len(observation.accessible_event_ids)} 条"
        )
        st.markdown(
            f"**已知线索** · "
            f"{'、'.join(bundle.scenario.clue_map[item].display_name for item in observation.known_clue_ids) or '尚无'}"
        )
        with st.expander("查看权限过滤后的 ObservationPacket"):
            st.json(observation.model_dump(mode="json"))
    with role_right:
        st.subheader("为什么做出这个行动")
        if current_record:
            action = next(
                item
                for item in current_record.actions
                if item.actor_id == selected_character
            )
            st.markdown(f"**行动** · `{action.action_type.value}`")
            st.markdown(f"**理由** · {action.rationale}")
            st.markdown(
                f"**证据事件** · {', '.join(action.evidence_event_ids) or '无直接引用'}"
            )
            hit_ids = [
                hit.memory_id
                for hit in current_record.retrievals.get(selected_character, [])
            ]
            st.markdown(f"**本轮检索记忆** · {len(hit_ids)} 条")
        else:
            st.caption("推进一轮后显示决策证据链。")
        st.write("")
        st.subheader("独立记忆")
        if own_memories:
            for memory in own_memories[:7]:
                source = " / ".join(memory.source_event_ids)
                with st.expander(
                    f"R{memory.created_round:02d} · {memory.kind.value} · {source}"
                ):
                    st.write(memory.content)
                    st.caption(
                        f"显著度 {memory.salience:.2f} · 可见性 {memory.visibility.value} · "
                        f"标签 {' / '.join(memory.tags)}"
                    )
        else:
            st.caption("尚无记忆。")
        if own_beliefs:
            st.write("")
            st.subheader("角色认知")
            for belief in own_beliefs:
                st.markdown(
                    f"- **{belief.stance} · {belief.confidence:.0%}** — "
                    f"{belief.proposition} `{'/'.join(belief.source_event_ids)}`"
                )

    if audit_mode:
        st.write("")
        st.subheader("信息边界矩阵")
        rows = []
        for clue in bundle.scenario.clues:
            row = {"事实": clue.display_name}
            for character in bundle.characters:
                discovery = decision_state.discovered_clues.get(clue.id)
                if clue.id in decision_state.shared_clue_ids:
                    row[character.display_name] = "共享 ✓"
                elif discovery and discovery.discovered_by == character.id:
                    row[character.display_name] = "私密 ◆"
                else:
                    row[character.display_name] = "未知 —"
            rows.append(row)
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            f"{perspective_label} · ◆ 私密：仅拥有者观察包可读取；"
            "✓ 共享：已经过事件显式传播。"
        )

with tabs[2]:
    st.markdown(
        '<div class="readonly-banner">◌ 回放是只读视图，不会修改当前运行或创建新事件。</div>',
        unsafe_allow_html=True,
    )
    st.write("")
    if state.round_no == 0:
        replay_round = 0
        st.caption("回放轮次 · 0（推进后即可拖动时间轴）")
    else:
        replay_round = st.slider(
            "回放轮次",
            min_value=0,
            max_value=state.round_no,
            value=state.round_no,
        )
    replay_state = repository.get_state_at_round(selected_run, replay_round)
    rcols = st.columns(4)
    rcols[0].metric("轮次", f"{replay_round} / {state.round_no}")
    rcols[1].metric("阶段", replay_state.phase)
    rcols[2].metric("证据", f"{replay_state.resources['evidence']:g} / 10")
    rcols[3].metric("快照摘要", replay_state.state_digest()[:8])
    if replay_round:
        replay_record = repository.get_round(selected_run, replay_round)
        event_col, diff_col = st.columns([1.2, 1])
        with event_col:
            st.subheader("这一轮确认了什么")
            for event in replay_record.events:
                st.markdown(
                    f"**`{event.id}`**  \n{event.public_summary or '定向私密事件'}"
                )
        with diff_col:
            st.subheader("与上一轮的差异")
            if replay_record.diffs:
                for diff in replay_record.diffs:
                    st.markdown(
                        f"- {diff.label}：`{fmt_value(diff.before)}` → "
                        f"`{fmt_value(diff.after)}`"
                    )
            else:
                st.caption("没有结构化状态变化。")
        with st.expander("可复现信息"):
            st.code(
                f"seed={manifest.seed}\n"
                f"config_digest={manifest.config_digest}\n"
                f"state_digest={replay_state.state_digest()}\n"
                f"timeline_hash={replay_state.timeline_hash}"
            )
    else:
        st.info("轮 0 包含登舰简报和四条定向私密 briefing，尚未产生角色行动。")
    replay_result = engine.replay(selected_run)
    st.success(
        f"全量重放 {'通过' if replay_result.matched else '失败'} · "
        f"{replay_result.rounds_replayed} 轮 · {replay_result.actual_digest}"
    )

with tabs[3]:
    episodes = repository.get_episodes(selected_run)
    st.subheader("事件生成的章节")
    if not episodes:
        st.info(f"每 {bundle.scenario.episode_interval} 轮生成一个章节；当前尚未到章节节点。")
    for index, episode in enumerate(episodes, start=1):
        st.markdown(
            f"""
            <div class="chapter-card">
              <div class="chapter-no">CHAPTER {index:02d} · ROUND {episode.start_round:02d}–{episode.end_round:02d}</div>
              <div class="chapter-title">{html.escape(episode.title)}</div>
              <div class="chapter-body">{html.escape(episode.body)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.expander(f"来源事件 · {len(episode.event_ids)} 条"):
            st.code("\n".join(episode.event_ids))
            st.caption(
                f"生成方式 {episode.generated_by} · 新增推断 {len(episode.inferred_facts)} · "
                f"连续性校验 {'通过' if episode.validation_passed else '失败'}"
            )
    st.write("")
    export_left, export_right = st.columns([1.25, 1])
    with export_left:
        st.subheader("导出演示包")
        include_private = st.toggle(
            "包含完整研究 trace",
            value=False,
            help="开启后会包含角色私密记忆、私密事件载荷与决策理由。",
        )
        if include_private:
            st.warning("完整 trace 含私密角色状态，仅适合本地研究审计；仍不会包含 API Key。")
        archive = build_demo_archive(
            repository,
            selected_run,
            include_private=include_private,
        )
        st.download_button(
            "下载 ZIP 演示包",
            data=archive,
            file_name=f"{selected_run}{'-private' if include_private else ''}.zip",
            mime="application/zip",
            type="primary",
        )
        st.caption("默认导出已脱敏：事件、快照、章节、指标与可复现清单。")
    with export_right:
        st.subheader("自动评测")
        metric_rows = [
            {"指标": "越界知情", "结果": str(metrics["leakage_findings"])},
            {"指标": "严重连续性错误", "结果": str(metrics["critical_findings"])},
            {"指标": "证据引用有效率", "结果": f"{metrics['evidence_validity_rate']:.0%}"},
            {"指标": "章节事件覆盖率", "结果": f"{metrics['narrative_event_coverage']:.0%}"},
            {"指标": "确定性摘要", "结果": metrics["final_state_digest"]},
        ]
        st.dataframe(metric_rows, width="stretch", hide_index=True)

with tabs[4]:
    st.subheader("三层信息，不让模型混在一起")
    layer_cols = st.columns(3)
    layer_content = [
        (
            "01 / 公开设定",
            "蓝色矩形 · 不可修改",
            "只保存本次实验需要的最小公开角色事实，并记录来源与访问版本。",
        ),
        (
            "02 / 场景真相",
            "青色圆形 · 事件确认",
            "地点、资源、线索与任务状态只能由白名单事件经 reducer 更新。",
        ),
        (
            "03 / 角色认知",
            "琥珀菱形 · 可能错误",
            "角色只接收权限过滤后的观察和本人记忆；信念始终保留证据来源。",
        ),
    ]
    for column, (title, meta, copy) in zip(
        layer_cols, layer_content, strict=True
    ):
        with column:
            st.markdown(
                f"""
                <div class="layer">
                  <div class="layer-title">{title}</div>
                  <div class="action-type">{meta}</div>
                  <div class="layer-copy" style="margin-top:.7rem">{copy}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    st.write("")
    st.subheader("一次轮次如何被提交")
    flow_cols = st.columns(6)
    stages = [
        ("01", "隔离观察"),
        ("02", "检索本人记忆"),
        ("03", "提出行动意图"),
        ("04", "规则裁决"),
        ("05", "确定性更新"),
        ("06", "连续性审计"),
    ]
    for column, (number, name) in zip(flow_cols, stages, strict=True):
        with column:
            st.markdown(
                f'<div class="metric-card" style="min-height:6rem">'
                f'<div class="metric-label">{number}</div>'
                f'<div style="color:#eaf1ff;font-weight:700;margin-top:.65rem">{name}</div>'
                f"</div>",
                unsafe_allow_html=True,
            )
    st.write("")
    source_col, scope_col = st.columns(2)
    with source_col:
        st.subheader("公开资料来源")
        for fact in bundle.canon_facts:
            profile = bundle.character_map[fact.subject_id]
            st.markdown(
                f"- [{profile.display_name} · {fact.value}]({fact.source_url}) "
                f"`{fact.source_version}`"
            )
        st.caption("人物语言风格参数是本原型的建模推导，不是官方数值。")
    with scope_col:
        st.subheader("原型边界")
        st.markdown(
            """
            - 不复刻战斗系统或主线剧情
            - 仅在 UI 中限量使用官方公开立绘与短语音片段，并明确标注来源
            - 不再分发角色模型、CG、完整语音包或长段台词
            - 不读取泄露、测试服或未公开材料
            - 实时 LLM 只能提出意图，不能直接写世界状态
            - 所有原创章节都明确标注为非官方内容
            """
        )
    st.info(DISCLAIMER)
