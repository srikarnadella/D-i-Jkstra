"""The app's look: true-black flat (taste-skill app style), face = booth amber on the data.

Elevation is lightness alone (#000 ground, #111 card, #2a2a2a nested), no borders or shadows on
cards, nav marked active by brightness, the primary control an inverted white pill. Colour
(amber) is only on data marks. Base colours, font and sizes live in .streamlit/config.toml;
this file holds what the theme can't express. Cards are `st.container(key="card_…")`.
"""
import streamlit as st

from ui.common import PAGE_LABELS, go_to

# Data hue: booth amber — the mixer's on-air colour, and gentle on dark-adapted eyes.
ACCENT = "#f2b33d"
POSITIVE, NEGATIVE = "#3fc07a", "#e5484d"
INK, MUTED, FAINT = "#ffffff", "#cfcfcf", "#adadad"   # both well above 4.5:1 on #111
SURFACE, RAISED, RULE, GRID = "#111111", "#2a2a2a", "#1a1a1a", "#2b2b2b"

_CSS = f"""
<style>
:root {{
  --ground:#000; --surface:{SURFACE}; --raised:{RAISED}; --rule:{RULE}; --control:#444;
  --text:{INK}; --muted:{MUTED}; --faint:{FAINT}; --accent:{ACCENT};
  --positive:{POSITIVE}; --negative:{NEGATIVE};
}}
/* No top bar: Streamlit's can't hold anything real, and an empty one is flagged. */
header[data-testid="stHeader"] {{ display:none; }}
[data-testid="stMainBlockContainer"] {{ padding:36px 29px 64px; max-width:1440px; }}

/* Numbers that update or line up keep their width. */
.stApp {{ font-variant-numeric: tabular-nums; }}  /* an app: every figure keeps its width */
[data-testid="stMetricLabel"] p {{ color:var(--muted); font-size:15px; }}
h1 {{ letter-spacing:0; padding-top:0 !important; }}

/* Sidebar: mark + name + scope, nav on a 34px pitch, active = brightness only. */
[data-testid="stSidebar"] {{ min-width:224px !important; max-width:224px !important; }}
[data-testid="stSidebarContent"] {{ padding-top:8px; }}
[data-testid="stSidebar"] [data-testid^="stBaseButton"] {{
  background:transparent; border:0; box-shadow:none; color:#bbbbbb; min-height:40px; height:40px;
  padding:0 12px; justify-content:flex-start; border-radius:8px; font-weight:500;
}}
[data-testid="stSidebar"] [data-testid^="stBaseButton"] > div {{ justify-content:flex-start; width:100%; }}
[data-testid="stSidebar"] [data-testid^="stBaseButton"] p {{ font-size:16px; }}
[data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{ color:#ffffff; font-weight:600; }}
[data-testid="stSidebar"] [data-testid^="stBaseButton"]:hover {{ color:#ffffff; background:#111111; }}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {{ gap:0; }}
.brand {{ display:flex; align-items:center; gap:10px; padding:4px 10px 2px; }}
.brand-name {{ font-weight:700; font-size:19px; color:#fff; }}
.brand-scope {{ color:var(--faint); font-size:14px; padding:0 10px 18px 42px; }}

/* Controls: secondary = outlined pill, primary = inverted white pill. Accent never on chrome. */
[data-testid="stMain"] [data-testid="stBaseButton-secondary"] {{
  background:transparent; border:1px solid var(--control); color:#fff; min-height:36px;
}}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"]:hover {{ border-color:#8a8a8a; color:#fff; }}
[data-testid="stMain"] [data-testid="stBaseButton-primary"] {{
  background:#fff; color:#000; border:0; min-height:36px;
}}
[data-testid="stMain"] [data-testid="stBaseButton-primary"]:hover {{ background:#e6e6e6; color:#000; }}
[data-testid="stMain"] [data-testid="stBaseButton-primary"] p {{ color:#000; font-weight:500; }}

/* Cards: one lightness step, no border, no shadow, radius 20. */
div[class*="st-key-card"] {{ background:var(--surface); border-radius:20px; padding:20px 22px; border:0; }}
div[class*="st-key-card"] div[class*="st-key-nest"] {{ background:var(--raised); border-radius:14px; padding:14px 16px; }}
/* Primary is white, so anything Streamlit fills with it needs dark ink or a neutral fill. */
[data-baseweb="tag"] {{ background:var(--raised) !important; }}
[data-baseweb="tag"] span, [data-baseweb="tag"] svg {{ color:#fff !important; fill:#fff !important; }}
[data-testid="stBaseButton-primaryFormSubmit"] {{ background:#fff !important; border:0 !important; }}
[data-testid="stBaseButton-primaryFormSubmit"] p {{ color:#000 !important; font-weight:500; }}
/* Field labels and help text: heavier and larger, they were the thinnest text on the page. */
[data-testid="stWidgetLabel"] p, [data-testid="stWidgetLabel"] label {{ font-size:15px; font-weight:600; color:#fff; }}
[data-testid="stCaptionContainer"] p {{ font-size:14px; color:var(--faint); font-weight:500; }}
[data-testid="stTabs"] button p {{ font-size:16px; font-weight:600; }}
/* Toggles: white track when on, so its knob turns black to stay visible. */
[data-testid="stCheckbox"] label:has(input:checked) > div:first-child > div {{ background:#000 !important; }}
/* Fields inside a card take the nested step, so they still read as controls. */
div[class*="st-key-card"] [data-baseweb="select"] > div,
div[class*="st-key-card"] [data-baseweb="input"],
div[class*="st-key-card"] [data-baseweb="input"] input {{ background:var(--raised); }}
[data-testid="stExpander"] details {{ background:var(--surface); border:0; border-radius:20px; }}
[data-testid="stExpander"] summary {{ font-weight:600; }}
.card-title {{ font-size:19px; font-weight:700; color:#fff; margin:0 0 2px; }}
.card-sub {{ font-size:14px; color:var(--faint); margin:0 0 12px; }}
.lede {{ color:var(--muted); font-size:16px; margin:-6px 0 18px; }}

/* KPI strip: one card split by 1px rules; label over value. */
.kpis {{ display:grid; grid-template-columns:repeat(var(--n,4), 1fr); background:var(--surface);
  border-radius:20px; margin-bottom:14px; }}
.kpi {{ padding:16px 22px; border-left:1px solid var(--rule); }}
.kpi:first-child {{ border-left:0; }}
.kpi-label {{ color:var(--muted); font-size:15px; }}
.kpi-value {{ font-size:30px; font-weight:600; color:#fff; line-height:1.3; }}
.kpi-value small, .deck-figs small, .row-figs small {{ color:var(--faint); font-size:15px; font-weight:500; }}
.kpi-note {{ color:var(--faint); font-size:14px; }}

/* Lists inside cards: rows on 1px rules, figures right-aligned. */
.rowlist {{ display:flex; flex-direction:column; }}
.row {{ display:flex; flex-wrap:wrap; align-items:baseline; column-gap:12px; padding:9px 0;
  border-top:1px solid var(--rule); }}
.row:first-child {{ border-top:0; }}
.tight .row {{ padding:5px 0; }}
.row-main {{ flex:1; min-width:0; }}
.row-title {{ color:#fff; font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.row-sub {{ color:var(--faint); font-size:14px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.row-figs {{ color:#fff; font-weight:600; text-align:right; white-space:nowrap; }}
.bar {{ flex:0 0 100%; height:2px; background:#2a2a2a; margin-top:8px; }}
.empty {{ color:var(--faint); font-size:15px; line-height:1.5; margin:0; }}
.bar > span {{ display:block; height:2px; background:var(--muted); }}
.bar.lead > span {{ background:#fff; }}

/* Deck strip (Live): deck A → transition → deck B. */
.decks {{ display:grid; grid-template-columns:1fr 220px 1fr; align-items:stretch; gap:14px; margin:4px 0 14px; }}
.deck {{ background:var(--surface); border-radius:20px; padding:18px 22px; min-width:0; }}
.deck-label {{ color:var(--muted); font-size:15px; margin-bottom:6px; }}
.deck-title {{ font-size:22px; font-weight:700; color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.deck-artist {{ color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; margin-bottom:10px; }}
.deck-figs {{ display:flex; flex-wrap:wrap; gap:4px 18px; font-size:24px; font-weight:600; color:#fff; }}
.link {{ display:flex; flex-direction:column; justify-content:center; text-align:center; gap:8px; }}
.link-words {{ color:#fff; font-size:15px; font-weight:500; line-height:1.5; }}
.link-line {{ height:2px; background:var(--accent); position:relative; }}
.link-line::after {{ content:""; position:absolute; right:-1px; top:-4px; border-left:8px solid var(--accent);
  border-top:5px solid transparent; border-bottom:5px solid transparent; }}
.link.clash .link-line {{ background:var(--negative); }}
.link.clash .link-line::after {{ border-left-color:var(--negative); }}
.ok {{ color:var(--positive); }} .bad {{ color:var(--negative); }}

@media (max-width: 1100px) {{
  .decks {{ grid-template-columns:1fr; }}
  .link {{ flex-direction:row; align-items:center; text-align:left; }}
  .link-line {{ flex:0 0 40px; order:-1; }}
}}
@media (max-width: 760px) {{
  [data-testid="stMainBlockContainer"] {{ padding:20px 16px 48px; }}
  .kpis {{ grid-template-columns:1fr 1fr; }}
  .kpi:nth-child(3) {{ border-left:0; }}
  .kpi:nth-child(n+3) {{ border-top:1px solid var(--rule); }}
}}
</style>
"""

# Three nodes, two edges: a shortest path, in the data hue.
_MARK = f"""<svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
<path d="M4 17 L11 5 L18 15" fill="none" stroke="{ACCENT}" stroke-width="2"/>
<circle cx="4" cy="17" r="3" fill="{ACCENT}"/><circle cx="11" cy="5" r="3" fill="{ACCENT}"/>
<circle cx="18" cy="15" r="3" fill="{ACCENT}"/></svg>"""


def apply() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def sidebar(songs: list, current_page: str) -> None:
    with st.sidebar:
        st.markdown('<div class="brand">' + _MARK + '<span class="brand-name">D-i-Jkstra</span></div>'
                    f'<div class="brand-scope">{len(songs):,} tracks</div>',
                    unsafe_allow_html=True)
        for page_id, label in PAGE_LABELS.items():
            if st.button(label, key=f"nav_{page_id}", width="stretch",
                         type="primary" if page_id == current_page else "secondary"):
                go_to(page_id)
