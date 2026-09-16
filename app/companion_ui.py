from __future__ import annotations

import atexit
import base64
import difflib
import html
import importlib.util
import json
from pathlib import Path

import streamlit as st

from astral_agents.capture_service import CaptureService
from astral_agents.companion import StoryStore, configured_model, generate, model_ready, split_cast
from astral_agents.companion_models import CaptureProfile, CharacterCard, StoryArchive

ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE = 8 * 1024 * 1024
KINDS = {"manual": "自定义开局", "capture": "剧情实况", "fork": "改写分支", "continuation": "自然续演"}
KIND_ICONS = {"manual": "✦", "capture": "◉", "fork": "⑂", "continuation": "➝"}
STATES = {"stopped": "未运行", "starting": "初始化中", "running": "正在捕捉",
          "stopping": "正在停止", "error": "需要处理"}
STATE_TONES = {"stopped": "idle", "starting": "busy", "running": "live", "stopping": "busy", "error": "error"}
PORTRAITS = {"三月七": "march-7th", "丹恒": "dan-heng", "姬子": "himeko", "瓦尔特": "welt"}
STARTERS = [
    ("列车启程前", "三月七，丹恒", "【原创开局】星穹列车即将启程。三月七想留下核实一条求助消息，丹恒提醒大家时间有限。玩家站在车门前，还没有作出选择。"),
    ("一封没有寄出的信", "姬子，瓦尔特", "【原创开局】观景车厢里出现了一封没有署名的信。姬子认为应该寻找写信的人，瓦尔特担心冒然调查会伤害对方。信的内容尚未公开。"),
    ("信号另一端的你", "三月七", "【原创开局】三月七的相机突然收到一段来自屏幕外的文字。她发现玩家能听见她，但不知道玩家是谁，也不知道这条联系会持续多久。"),
]
PROMPTS = [("此刻的担忧", "你现在最担心什么？"),
           ("如果我请你留下", "如果我请求你留下，你会怎么选择？"),
           ("屏幕外的我", "你知道我是从屏幕外和你说话的吗？")]
PRESETS = {"主屏底部字幕": .70, "主屏中央对话": .42}


# ---------------------------------------------------------------- resources

@st.cache_data(show_spinner=False)
def asset(path: str):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


@st.cache_data(show_spinner=False)
def stylesheet(mtime: float):
    return (ROOT / "app/companion.css").read_text(encoding="utf-8")


@st.cache_resource(show_spinner=False)
def story_store(database: str):
    store = StoryStore(Path(database))
    seed_cards(store)
    return store


@st.cache_resource(show_spinner=False)
def capture_service(database: str):
    service = CaptureService(Path(database))
    atexit.register(service.close)
    return service


def portrait_path(name):
    slug = PORTRAITS.get(name)
    path = ROOT / "app/assets/characters" / f"{slug}.png" if slug else None
    return path if path and path.exists() else None


def seed_cards(store):
    if store.setting("cards_seeded", False):
        return
    import yaml
    data = yaml.safe_load((ROOT / "scenarios/sealed_transport/characters.yaml").read_text(encoding="utf-8"))
    existing = {c["name"] for c in store.cards()}
    for c in data["characters"]:
        if c["display_name"] not in existing:
            store.save_card(CharacterCard(name=c["display_name"], identity=c["public_summary"],
                                          voice=c["speech_style"]["notes"],
                                          boundaries="；".join(c["hard_constraints"]) + "；只依据当前剧情，不预知未来。"))
    store.save_setting("cards_seeded", True)


# ------------------------------------------------------------------ helpers

def esc(value):
    return html.escape(str(value))


def jump(node_id):
    st.session_state.pending_story = node_id
    st.rerun()


def friendly_error(exc, fallback):
    """Show actionable validation messages; hide internals of unexpected failures."""
    if isinstance(exc, ValueError) and str(exc) and "validation error" not in str(exc):
        return str(exc)
    return f"{fallback}（{type(exc).__name__}）"


def node_label(node):
    return f"{KIND_ICONS[node['kind']]} {node['title']}"


def tags(*items):
    return "".join(f'<span class="tag">{esc(i)}</span>' for i in items if i)


def scene(node, *, depth=None):
    meta = tags(KINDS[node["kind"]], "在场 · " + node["cast"],
                f"第 {depth} 幕" if depth else "", node["created"][:16].replace("T", " "))
    st.markdown(f'<div class="scene-paper kind-{node["kind"]}"><div class="scene-kicker">'
                f'{KIND_ICONS[node["kind"]]} CURRENT MOMENT</div><h3>{esc(node["title"])}</h3>'
                f'<div class="prose">{esc(node["content"])}</div><div class="tags">{meta}</div></div>',
                unsafe_allow_html=True)


def section(kicker, title, note=""):
    st.markdown(f'<div class="section-head"><div class="section-kicker">{esc(kicker)}</div>'
                f'<h2>{esc(title)}</h2>{f"<p>{esc(note)}</p>" if note else ""}</div>',
                unsafe_allow_html=True)


# ------------------------------------------------------------------- layout

def render(database: Path):
    database = database.resolve()
    store = story_store(str(database))
    service = capture_service(str(database))
    css = ROOT / "app/companion.css"
    st.markdown("<style>" + stylesheet(css.stat().st_mtime) + "</style>", unsafe_allow_html=True)
    nodes = store.nodes()
    by_id = {n["id"]: n for n in nodes}
    live, node = sidebar(store, nodes, by_id)
    hero(store)
    ready = model_ready(store)
    workbench_metrics(store, service, live, ready)
    capture_tab, story_tab, chat_tab, cards_tab, settings_tab = st.tabs(
        ["◉ 伴游控制台", "⑂ 故事档案", "✧ 跨屏对话", "◇ 角色档案", "⚙ 连接与设置"])
    with capture_tab:
        capture_console(store, service, node)
    with story_tab:
        story_library(store, nodes, node, live)
    with chat_tab:
        character_chat(store, node, live)
    with cards_tab:
        character_editor(store)
    with settings_tab:
        connections(store, ready)


def sidebar(store, nodes, by_id):
    with st.sidebar:
        st.markdown('<div class="link-brand"><span>✦</span> WhatIfStarRail</div>'
                    '<div class="link-sub">星铁如果说 · 叙事工作台<br>每一个如果，都值得一条新的轨道。</div>',
                    unsafe_allow_html=True)
        live = st.toggle("使用模型生成", value=False, key="use_live",
                         help="开启后发送当前分支文本到已配置的模型；API 密钥只从本地环境读取。")
        if live and not model_ready(store):
            st.warning("尚未配置模型，生成会失败。请在「连接与设置」中查看。", icon="⚠️")
        st.markdown('<div class="side-label">当前故事</div>', unsafe_allow_html=True)
        node = None
        if nodes:
            ids = list(reversed(by_id))  # newest first
            if st.session_state.get("story_selected") not in by_id:
                st.session_state.story_selected = ids[0]
            selected = st.selectbox("选择时间节点", ids, key="story_selected",
                                    format_func=lambda i: node_label(by_id[i]))
            node = by_id[selected]
            depth = 0
            cursor = node
            while cursor:
                depth += 1
                cursor = by_id.get(cursor["parent"])
            st.markdown(f'<div class="side-node">{esc(KINDS[node["kind"]])} · 第 {depth} 幕<br>'
                        f'在场：{esc(node["cast"])}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="side-node">尚未建立故事。<br>先选一个开局，或接入游戏字幕。</div>',
                        unsafe_allow_html=True)
        if st.button("↻ 刷新故事库", width="stretch"):
            st.rerun()
        st.markdown('<div class="side-links"><a href="https://github.com/JaspinXu/WhatIfStarRail/blob/main/docs/companion.zh-CN.md" target="_blank">使用指南</a>'
                    '<a href="https://github.com/JaspinXu/WhatIfStarRail" target="_blank">项目主页</a></div>'
                    '<div class="side-foot">本地工作台 · v0.2<br>角色心境与改写内容为同人推演。</div>',
                    unsafe_allow_html=True)
    return live, node


def hero(store):
    art = asset(str(ROOT / "app/assets/ui/march-comm-hero-v1.png"))
    st.markdown("<style>.workbench-hero:before{background-image:linear-gradient(90deg,#10172b 0%,#121a2fee 38%,"
                "#121a2f55 70%,#121a2f10 100%),url('" + art + "')}</style>", unsafe_allow_html=True)
    st.markdown('<div class="workbench-hero">'
                '<div class="kicker">WHAT IF / A DIFFERENT TRACK</div><h1>星铁如果说</h1>'
                '<p>如果你能在那一刻开口，故事会不会不一样？<br>'
                '接住一段剧情，听见一个人，再写下一种可能。</p>'
                '<span class="hero-chip">Honkai: Star Rail / 崩坏：星穹铁道</span>'
                '<span class="hero-chip ghost">非官方 · 本地运行</span></div>', unsafe_allow_html=True)


@st.fragment(run_every=2)
def workbench_metrics(store, service, live, ready):
    stats = store.stats()
    status = service.status()
    tone = STATE_TONES[status["state"]]
    metrics = [
        ("采集连接", STATES[status["state"]], f"已保存 {status['saved']} 条 · 后台运行", tone),
        ("故事档案", str(stats["nodes"]), f"{stats['forks']} 条改写分支 · {stats['chats']} 轮对话", "idle"),
        ("角色档案", str(stats["cards"]), "身份、语气与知识边界", "idle"),
        ("叙事引擎", "在线模型" if live else "离线预演",
         "模型已配置" if ready else "未配置 · 见连接与设置", "live" if live and ready else
         ("error" if live else "idle")),
    ]
    html_cards = "".join(
        f'<div class="status-card tone-{t}"><div class="label"><i></i>{esc(label)}</div>'
        f'<div class="value">{esc(value)}</div><div class="hint">{esc(hint)}</div></div>'
        for label, value, hint, t in metrics)
    st.markdown(f'<div class="status-grid">{html_cards}</div>', unsafe_allow_html=True)


# ------------------------------------------------------------ capture tab

def capture_console(store, service, node):
    left, right = st.columns([1.65, 1], gap="large")
    with left:
        section("LIVE / 现场记录", "剧情正在发生")
        capture_status(service, store)
        if node:
            scene(node)
        else:
            st.markdown('<div class="empty-panel"><b>还没有接入剧情</b>'
                        '<ol><li>从右侧选一段原创开局，立即开始对话与改写；</li>'
                        '<li>或展开下方「字幕区域与后台采集」，边玩边记录；</li>'
                        '<li>也可以在「从零创建」里手动写下任意剧情节点。</li></ol></div>',
                        unsafe_allow_html=True)
        capture_settings(store, service)
    with right:
        section("QUICK START / 改变从这里开始", "选一段未写完的故事")
        for title, cast, content in STARTERS:
            body = content.replace("【原创开局】", "")
            st.markdown(f'<div class="starter"><div class="starter-top"><b>{esc(title)}</b>'
                        f'<span>{esc(cast)}</span></div><p>{esc(body)}</p></div>', unsafe_allow_html=True)
            if st.button("进入这段故事 →", key="starter_" + title, width="stretch"):
                jump(store.add(title, content, cast))
        with st.expander("✎ 从零创建 / 手动补录"), st.form("new_node"):
            title = st.text_input("节点标题", placeholder="给这个瞬间取个名字", key="new_title")
            cast = st.text_input("在场人物（用逗号分隔）", value="三月七，丹恒", key="new_cast")
            content = st.text_area("当前剧情 / 自定义开局", height=150, key="new_content",
                                   placeholder="写下正在发生的事情、地点、已知事实与矛盾……")
            if st.form_submit_button("建立剧情节点", type="primary", width="stretch"):
                try:
                    node_id = store.add(title, content, cast)
                except ValueError:
                    st.error("请填写剧情和在场人物，剧情最多 24000 字。")
                else:
                    jump(node_id)


def capture_settings(store, service):
    with st.expander("⚙ 字幕区域与后台采集", expanded=False):
        saved = CaptureProfile.model_validate(store.setting("capture_profile", {}))
        st.caption("先选屏幕预设再校准区域。后台采集持续到手动停止或服务退出；关闭网页不会停止采集。")
        preset = st.selectbox("字幕区域预设", ["已保存 / 自定义", *PRESETS])
        region = saved.region()
        if preset in PRESETS:
            try:
                import mss
                with mss.mss() as screen:
                    monitor = screen.monitors[1]
                region = {"left": monitor["left"] + int(monitor["width"] * .12),
                          "top": monitor["top"] + int(monitor["height"] * PRESETS[preset]),
                          "width": int(monitor["width"] * .76), "height": int(monitor["height"] * .24)}
            except Exception:
                st.warning("未找到屏幕或未安装采集依赖，请使用自定义坐标。")
        with st.form("capture_settings"):
            cols = st.columns(4)
            coords = {key: col.number_input(label, value=value, step=10)
                      for col, (key, value), label in zip(cols, region.items(), ["左 X", "上 Y", "宽", "高"], strict=True)}
            cast = st.text_input("捕捉场景人物", value=saved.cast)
            a, b = st.columns(2)
            interval = a.slider("采样间隔（秒）", .5, 10.0, float(min(saved.interval, 10)), .5)
            confidence = b.slider("最低识别置信度", .1, 1.0, saved.confidence, .05)
            if st.form_submit_button("保存采集配置", width="stretch"):
                try:
                    profile = CaptureProfile(**coords, interval=interval, confidence=confidence, cast=cast)
                except ValueError:
                    st.error("请检查区域尺寸、坐标和在场人物。")
                else:
                    store.save_setting("capture_profile", profile.model_dump())
                    st.success("配置已保存，下一次启动采集时生效。")
        running = service.running
        new_timeline = st.checkbox("本次开始新的捕捉时间线", disabled=running,
                                   help="切换任务或章节时勾选，新的字幕不会接在旧剧情后面。")
        a, b, c = st.columns(3)
        if a.button("▶ 启动捕捉", type="primary", width="stretch", disabled=running):
            try:
                service.start(CaptureProfile.model_validate(store.setting("capture_profile", {})),
                              new_timeline=new_timeline)
            except ValueError as exc:
                st.error(friendly_error(exc, "启动失败"))
            else:
                st.rerun()
        if b.button("■ 停止捕捉", width="stretch", disabled=not running):
            service.stop()
            st.rerun()
        if c.button("◎ 预览区域", width="stretch"):
            try:
                import mss
                from PIL import Image
                profile = CaptureProfile.model_validate(store.setting("capture_profile", {}))
                with mss.mss() as screen:
                    shot = screen.grab(profile.region())
                st.image(Image.frombytes("RGB", shot.size, shot.rgb), caption="已保存的字幕区域")
            except Exception:
                st.error('无法截取区域，请安装 pip install -e ".[capture]" 并检查屏幕坐标。')


@st.fragment(run_every=2)
def capture_status(service, store):
    status = service.status()
    tone = STATE_TONES[status["state"]]
    st.markdown(f'<div class="capture-line tone-{tone}"><i></i><b>{STATES[status["state"]]}</b>'
                f'<span>已采样 {status["frames"]} 帧</span><span>保存 {status["saved"]} 条</span>'
                f'<span>OCR {status["latency_ms"]} ms</span></div>', unsafe_allow_html=True)
    if status["error"]:
        st.error(status["error"])
    elif status["last_text"]:
        st.markdown('<div class="timeline-item"><div class="time">最近识别 · ' +
                    esc((status["last_seen"] or "")[:19].replace("T", " ")) + ' UTC</div><div class="line">' +
                    esc(status["last_text"][:700]) + '</div></div>', unsafe_allow_html=True)
    last = status["last_node"]
    if last and last != st.session_state.get("story_selected") and st.button("打开最新捕捉剧情 →"):
        try:
            store.node(last)
        except KeyError:
            st.warning("该捕捉节点已被删除。")
        else:
            jump(last)


# -------------------------------------------------------------- story tab

def story_library(store, nodes, node, live):
    section("ARCHIVE / 故事档案", "找回那个想要改变的瞬间")
    search, category = st.columns([3, 1])
    query = search.text_input("搜索剧情、人物或标题", placeholder="输入关键词，例如：三月七、车门、信", key="library_query")
    kind = category.selectbox("来源", ["全部", *KINDS.values()])
    needle = query.strip().casefold()
    found = [n for n in reversed(nodes) if needle in (n["title"] + n["content"] + n["cast"]).casefold()
             and (kind == "全部" or KINDS[n["kind"]] == kind)]
    st.caption(f"找到 {len(found)} 个节点 · 选择节点可查看祖先、比较改写或继续故事")
    with st.expander("检索结果", expanded=bool(needle) or kind != "全部" or not node):
        if not found:
            st.caption("没有匹配的节点。")
        for n in found[:40]:
            col, action = st.columns([6, 1], vertical_alignment="center")
            current = " · 当前" if node and n["id"] == node["id"] else ""
            col.markdown(f'<div class="result-row"><b>{esc(node_label(n))}</b>{esc(current)}'
                         f'<span>{esc(KINDS[n["kind"]])} · {esc(n["cast"])} · {esc(n["content"][:60])}</span></div>',
                         unsafe_allow_html=True)
            if action.button("打开", key="open_" + n["id"], width="stretch"):
                jump(n["id"])
        if len(found) > 40:
            st.caption("显示前 40 条，请输入更精确的关键词。")
    if not node:
        st.info("从伴游控制台选择开局，或者在下方导入已有故事归档。")
        import_panel(store)
        return
    branch = store.lineage(node["id"])
    children = store.children(node["id"])
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        st.markdown('<div class="breadcrumb">' + '<b>›</b>'.join(
            f'<span class="{"on" if a["id"] == node["id"] else ""}">{esc(a["title"][:18])}</span>'
            for a in branch[-6:]) + '</div>', unsafe_allow_html=True)
        scene(node, depth=len(branch))
        continue_panel(store, node, branch, live)
        with st.expander(f"这条故事线的时间轴（{len(branch)} 幕）"):
            for index, ancestor in enumerate(branch, 1):
                st.markdown('<div class="timeline-item"><div class="time">' +
                            esc(f"第 {index} 幕 · {KINDS[ancestor['kind']]} · {ancestor['created'][:16].replace('T', ' ')}") +
                            '</div><div class="line">' + esc(ancestor["title"]) + '</div></div>', unsafe_allow_html=True)
        if node["parent"]:
            with st.expander("与上一幕比较改写"):
                parent = branch[-2]
                a, b = st.columns(2)
                a.caption("之前 · " + parent["title"])
                a.write(parent["content"])
                b.caption("现在 · " + node["title"])
                b.write(node["content"])
                diff = "\n".join(difflib.unified_diff(parent["content"].splitlines(), node["content"].splitlines(),
                                                      fromfile="上一幕", tofile="当前节点", lineterm=""))
                st.code(diff or "（文本相同）", language="diff")
    with right:
        navigation_panel(branch, children)
        fork_form(store, node)
        st.download_button("⭳ 导出当前分支与对话", store.export(node["id"]),
                           file_name=f"WhatIfStarRail-{node['id'][:8]}.json", mime="application/json",
                           width="stretch")
        delete_panel(store, node, branch, children)
        import_panel(store)


def continue_panel(store, node, branch, live):
    with st.container(border=True):
        st.markdown("**让故事继续**" + ("" if live else " <span class='muted'>· 离线预演</span>"),
                    unsafe_allow_html=True)
        direction = st.text_input("续演方向（可选）", placeholder="让人物自行选择，展示分歧与代价", key="direction")
        if st.button("自然演进一轮", type="primary", width="stretch"):
            try:
                with st.spinner("人物正在作出选择…"):
                    text = generate(store, node["id"], direction.strip() or "自然演进下一轮。", live=live)
                    new_id = store.add(f"续演 · 第 {len(branch) + 1} 幕", text, node["cast"],
                                       "continuation", node["id"])
            except Exception as exc:
                st.error(friendly_error(exc, "生成失败，未写入后续。请检查连接设置或切换离线预演"))
            else:
                jump(new_id)


def navigation_panel(branch, children):
    with st.container(border=True):
        st.markdown("**分支导航**")
        if len(branch) > 1 and st.button("↑ 回到上一幕 · " + branch[-2]["title"][:20], width="stretch",
                                         key="nav_parent"):
            jump(branch[-2]["id"])
        if children:
            st.caption(f"从这里延伸出 {len(children)} 条后续")
            for child in children[:8]:
                if st.button(node_label(child)[:28], key="child_" + child["id"], width="stretch"):
                    jump(child["id"])
        else:
            st.caption("这是故事线的最新一幕。续演或改写会在这里延伸。")


def fork_form(store, node):
    with st.form("fork_" + node["id"]):
        st.markdown("**如果，这一次不一样**")
        title = st.text_input("新分支标题", value=node["title"][:100] + " · 如果")
        cast = st.text_input("分支在场人物", value=node["cast"])
        change = st.text_area("改写 / 校正后的剧情前提", value=node["content"], height=200)
        if st.form_submit_button("从这里创建分支", type="primary", width="stretch"):
            try:
                node_id = store.add(title, change, cast, "fork", node["id"])
            except ValueError:
                st.error("请检查标题、剧情长度和在场人物。")
            else:
                jump(node_id)


def delete_panel(store, node, branch, children):
    if children:
        return
    with st.expander("删除此节点"):
        st.caption("仅可删除没有后续的节点，会同时删除该节点的对话记录，适合清理识别错误的字幕。")
        confirm = st.checkbox("我确认删除「" + node["title"][:24] + "」", key="confirm_delete_" + node["id"])
        if st.button("删除节点", disabled=not confirm, width="stretch", key="delete_" + node["id"]):
            try:
                store.delete_leaf(node["id"])
            except (KeyError, ValueError) as exc:
                st.error(friendly_error(exc, "删除失败"))
            else:
                parent = branch[-2]["id"] if len(branch) > 1 else None
                if parent:
                    jump(parent)
                st.session_state.pop("story_selected", None)
                st.rerun()


def import_panel(store):
    with st.expander("导入故事归档"):
        st.caption("支持本项目导出的 v1 JSON；校验通过后以全新节点 ID 导入，不覆盖已有故事。上限 8 MB。")
        uploaded = st.file_uploader("选择故事 JSON", type=["json"])
        if not uploaded:
            return
        raw = uploaded.getvalue()
        try:
            if len(raw) > MAX_ARCHIVE:
                raise ValueError("归档不能超过 8 MB")
            archive = StoryArchive.model_validate_json(raw)
        except ValueError as exc:
            st.error("归档无效：" + friendly_error(exc, "请检查版本、节点引用及文件大小"))
            return
        st.info(f"待导入：{len(archive.nodes)} 个节点 / {len(archive.chats)} 轮对话")
        if st.button("确认导入归档", type="primary", width="stretch"):
            jump(store.import_archive(raw.decode("utf-8")))


# --------------------------------------------------------------- chat tab

def character_chat(store, node, live):
    if not node:
        st.info("先选择一段剧情，再邀请其中的人物与你对话。")
        return
    actors = split_cast(node["cast"])
    left, right = st.columns([2, 1], gap="large")
    with left:
        actor = st.selectbox("对话人物", actors, key="chat_actor")
        card = store.card(actor)
        section("CROSS-SCREEN / 跨屏通讯", "与 " + actor + " 的对话",
                card["voice"][:120] if card and card["voice"] else "")
        avatar = portrait_path(actor)
        history = store.chats(node["id"], actor)
        if not history:
            st.markdown('<div class="empty-panel slim">还没有对话。说出那个原本无法告诉 TA 的想法，'
                        '或者从下面的问题开始。</div>', unsafe_allow_html=True)
        for item in history:
            with st.chat_message("user", avatar="🧑‍🚀"):
                st.write(item["question"])
            with st.chat_message("assistant", avatar=str(avatar) if avatar else "✦"):
                st.write(item["answer"])
        suggestion = None
        cols = st.columns(len(PROMPTS))
        for col, (label, prompt) in zip(cols, PROMPTS, strict=True):
            if col.button("✧ " + label, key=f"prompt_{prompt}", help=prompt, width="stretch"):
                suggestion = prompt
        question = st.chat_input("说出那个原本无法告诉 TA 的想法…") or suggestion
        if question:
            try:
                with st.spinner(actor + " 正在回应…"):
                    answer = generate(store, node["id"], question[:4000], actor=actor, live=live)
            except Exception as exc:
                st.error(friendly_error(exc, "角色回应失败，记录未写入。请检查连接设置后重试"))
            else:
                store.chat(node["id"], actor, question[:4000], answer)
                st.rerun()
    with right:
        portrait = portrait_path(actor)
        img = f'<img src="{asset(str(portrait))}" alt="{esc(actor)}">' if portrait else ""
        identity = card["identity"][:160] if card else "尚未建立角色卡，可在「角色档案」补充。"
        st.markdown(f'<div class="persona tall">{img}<h3>{esc(actor)}</h3><p>{esc(identity)}</p>'
                    f'<span class="tag">{"在线模型" if live else "离线预演"}</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="moment"><div class="time">当前时刻 · {esc(node["title"])}</div>'
                    f'<div class="line">{esc(node["content"][:500])}</div></div>', unsafe_allow_html=True)
        st.caption("只使用当前分支前文；对话按节点与人物隔离。角色心境为同人推演。")


# -------------------------------------------------------------- cards tab

def character_editor(store):
    section("PERSONAS / 角色档案", "让每个人，有自己的声音",
            "角色卡决定生成时的身份、表达习惯和知识边界。内置卡只使用公开概述，不加载模拟场景的私密线索。")
    cards = store.cards()
    cols = st.columns(4 if len(cards) >= 4 else max(len(cards), 1))
    for index, card in enumerate(cards):
        portrait = portrait_path(card["name"])
        img = f'<img src="{asset(str(portrait))}" alt="{esc(card["name"])}">' if portrait else \
            f'<div class="initial">{esc(card["name"][:1])}</div>'
        with cols[index % len(cols)]:
            st.markdown(f'<div class="persona">{img}<h3>{esc(card["name"])}</h3>'
                        f'<p>{esc(card["identity"][:110])}</p><span class="tag">可编辑角色卡</span></div>',
                        unsafe_allow_html=True)
    st.write("")
    selection = st.selectbox("编辑角色", ["新建角色", *[c["name"] for c in cards]], key="card_selection")
    blank = {"name": "", "identity": "", "voice": "", "boundaries": CharacterCard.model_fields["boundaries"].default}
    card = next((c for c in cards if c["name"] == selection), blank)
    with st.form("card_" + selection):
        name = st.text_input("人物名称", value=card["name"], disabled=selection != "新建角色",
                             placeholder="例如：黑塔")
        a, b = st.columns(2)
        identity = a.text_area("身份与性格", value=card["identity"], height=140)
        voice = b.text_area("说话方式", value=card["voice"], height=140)
        boundaries = st.text_area("知识边界与行为约束", value=card["boundaries"])
        if st.form_submit_button("保存角色卡", type="primary"):
            name = name.strip()
            if selection == "新建角色" and any(c["name"] == name for c in cards):
                st.error("已存在同名角色，请在上方选择它进行编辑。")
                return
            try:
                store.save_card(CharacterCard(name=name, identity=identity, voice=voice, boundaries=boundaries))
            except ValueError:
                st.error("请填写人物名称并检查字段长度。")
            else:
                st.toast("角色卡已保存：" + name)
                st.rerun()


# ----------------------------------------------------------- settings tab

def connections(store, ready):
    section("SETTINGS / 连接与设置", "让工作区可以长期使用", "采集、故事数据和模型连接分开管理。")
    a, b = st.columns(2, gap="large")
    with a:
        with st.container(border=True):
            st.markdown("**叙事模型** " + ('<span class="pill ok">已配置</span>' if ready
                                          else '<span class="pill warn">待配置</span>'), unsafe_allow_html=True)
            st.caption("密钥不写入数据库或导出文件")
            with st.form("model_settings"):
                model = st.text_input("模型名称", value=configured_model(store), placeholder="你有权限使用的模型名称")
                protocol = st.selectbox("接口协议", ["responses", "chat"],
                                        index=1 if store.setting("protocol") == "chat" else 0,
                                        format_func=lambda p: "Responses API" if p == "responses" else "Chat Completions（兼容接口）")
                if st.form_submit_button("保存模型设置", type="primary"):
                    store.save_setting("model", model.strip())
                    store.save_setting("protocol", protocol)
                    st.success("已保存，下一次生成生效。")
            st.caption("服务启动前设置 OPENAI_API_KEY；兼容服务可设置 OPENAI_BASE_URL。切换端点时请同时使用该服务的密钥。")
        with st.container(border=True):
            st.markdown("**运行环境检查**")
            for package, label in [("mss", "屏幕采集"), ("rapidocr_onnxruntime", "本地 OCR"),
                                   ("openai", "模型 SDK"), ("fastapi", "桥接 API")]:
                ok = importlib.util.find_spec(package) is not None
                st.markdown(f'<div class="check {"ok" if ok else ""}">{"✓" if ok else "○"} {label}'
                            f'<span>{"已安装" if ok else "未安装"}</span></div>', unsafe_allow_html=True)
            st.caption("依赖已安装不代表游戏已连接。请预览区域后再开始采集。")
    with b, st.container(border=True):
        st.markdown("**本地剧情接入 API**")
        st.caption("把你自己的 OCR、字幕或其他工具接入故事时间线。不是游戏官方 API；不需要账号 Cookie 或 authKey。")
        st.code('python -m pip install -e ".[bridge]"\n# 设置至少 24 字符的 WHATIF_BRIDGE_TOKEN\nwhatifstarrail bridge', language="bash")
        st.write("接口文档：启动后访问 http://127.0.0.1:8502/docs")
        st.code('POST /v1/ingest\nAuthorization: Bearer <token>\n\n' + json.dumps({
            "source": "my-subtitle-plugin", "event_id": "line-001", "timeline": "session-001",
            "title": "列车启程前", "text": "三月七：你真的决定了吗？", "cast": "三月七，丹恒",
        }, ensure_ascii=False, indent=2), language="text")
        st.caption("事件 ID 去重，重复提交返回原节点；同 ID 不同内容返回 409。相同来源与时间线自动衔接。")
