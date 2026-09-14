from __future__ import annotations

import atexit
import base64
import difflib
import html
import importlib.util
import json
import os
from pathlib import Path

import streamlit as st

from astral_agents.capture_service import CaptureService
from astral_agents.companion import StoryStore, generate
from astral_agents.companion_models import CaptureProfile, CharacterCard, StoryArchive

ROOT = Path(__file__).resolve().parents[1]
KINDS = {"manual": "自定义开局", "capture": "剧情实况", "fork": "改写分支", "continuation": "自然续演"}
STATES = {"stopped": "未运行", "starting": "初始化中", "running": "正在捕捉",
          "stopping": "正在停止", "error": "需要处理"}
PORTRAITS = {"三月七": "march-7th", "丹恒": "dan-heng", "姬子": "himeko", "瓦尔特": "welt"}
STARTERS = [
    ("列车启程前", "三月七，丹恒", "【原创开局】星穹列车即将启程。三月七想留下核实一条求助消息，丹恒提醒大家时间有限。玩家站在车门前，还没有作出选择。"),
    ("一封没有寄出的信", "姬子，瓦尔特", "【原创开局】观景车厢里出现了一封没有署名的信。姬子认为应该寻找写信的人，瓦尔特担心冒然调查会伤害对方。信的内容尚未公开。"),
    ("信号另一端的你", "三月七", "【原创开局】三月七的相机突然收到一段来自屏幕外的文字。她发现玩家能听见她，但不知道玩家是谁，也不知道这条联系会持续多久。"),
]


@st.cache_data
def asset(path: str):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


@st.cache_resource
def capture_service(database: str):
    service = CaptureService(Path(database))
    atexit.register(service.close)
    return service


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


def jump(node_id):
    st.session_state.pending_story = node_id
    st.rerun()


def scene(node):
    st.markdown('<div class="scene-paper"><h3>' + html.escape(node["title"]) + '</h3><div class="prose">' +
                html.escape(node["content"]) + '</div><span class="tag">' +
                html.escape(KINDS[node["kind"]]) + '</span><span class="tag">' +
                html.escape(node["cast"]) + '</span></div>', unsafe_allow_html=True)


def render(database: Path):
    store = StoryStore(database)
    seed_cards(store)
    service = capture_service(str(database.resolve()))
    st.markdown("<style>" + (ROOT / "app/companion.css").read_text(encoding="utf-8") + "</style>", unsafe_allow_html=True)
    with st.sidebar:
        st.markdown('<div class="link-brand">WhatIfStarRail</div><div class="link-sub">星铁如果说 / 叙事工作台<br>每一个如果，都值得一条新的轨道。</div>', unsafe_allow_html=True)
        live = st.toggle("使用模型生成", value=False, key="use_live")
        st.caption("在线生成发送当前分支文本；API 密钥仅从本地环境读取。")
        st.divider()
        st.caption("当前故事")
        nodes = store.nodes()
        if nodes:
            by_id = {n["id"]: n for n in nodes}
            ids = list(by_id)
            if st.session_state.get("story_selected") not in ids:
                st.session_state.story_selected = ids[-1]
            selected = st.selectbox("选择时间节点", ids, key="story_selected",
                                    format_func=lambda i: by_id[i]["title"] + " · " + i[:6])
            node = by_id[selected]
            st.caption("在场：" + node["cast"])
        else:
            node = None
            st.caption("尚未建立故事，先选一个开局或接入游戏。")
        if st.button("刷新故事库", use_container_width=True):
            st.rerun()
        st.divider()
        st.markdown("[使用指南](https://github.com/JaspinXu/WhatIfStarRail/blob/main/docs/companion.zh-CN.md) · "
                    "[项目主页](https://github.com/JaspinXu/WhatIfStarRail)")
        st.caption("本地工作台 · v0.2\n\n角色心境与改写内容为同人推演。")
    art = asset(str(ROOT / "app/assets/ui/march-comm-hero-v1.png"))
    st.markdown("<style>.workbench-hero:before{background-image:"
                "linear-gradient(90deg,#121a30 0%,#141c30ee 40%,#141c3030 80%),url('" + art + "')}</style>",
                unsafe_allow_html=True)
    st.markdown('<div class="workbench-hero">'
                '<div class="kicker">WHAT IF / A DIFFERENT TRACK</div><h1>星铁如果说</h1>'
                '<p>如果你能在那一刻开口，故事会不会不一样？<br>'
                '接住一段剧情，听见一个人，再写下一种可能。</p>'
                '<span class="hero-chip">Honkai: Star Rail / 崩坏：星穹铁道</span></div>', unsafe_allow_html=True)
    model_ready = bool(os.getenv("OPENAI_API_KEY") and (store.setting("model") or os.getenv("ASTRAL_OPENAI_MODEL")))
    workbench_metrics(store, service, live, model_ready)
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
        connections(store, model_ready)


@st.fragment(run_every=2)
def workbench_metrics(store, service, live, model_ready):
    nodes = store.nodes()
    status = service.status()
    metrics = [
        ("采集连接", STATES[status["state"]], "后台采集 · 可离开当前页面"),
        ("故事档案", str(len(nodes)), str(sum(n["kind"] == "fork" for n in nodes)) + " 条改写分支"),
        ("角色档案", str(len(store.cards())), "身份、语气与知识边界"),
        ("叙事引擎", "在线模型" if live else "离线预演", "模型已配置" if model_ready else "连接设置中查看配置"),
    ]
    for col, (label, value, hint) in zip(st.columns(4), metrics, strict=True):
        col.markdown(f'<div class="status-card"><div class="label">{label}</div><div class="value">{value}</div><div class="hint">{hint}</div></div>', unsafe_allow_html=True)


def capture_console(store, service, node):
    left, right = st.columns([1.65, 1], gap="large")
    with left:
        st.markdown('<div class="section-kicker">LIVE / 现场记录</div>', unsafe_allow_html=True)
        st.subheader("剧情正在发生")
        capture_status(service)
        if node:
            scene(node)
        else:
            st.markdown('<div class="empty-panel">还没有接入剧情。<br>从右侧开启一个原创场景，或在下方配置游戏字幕区域。</div>', unsafe_allow_html=True)
        with st.expander("字幕区域与后台采集", expanded=False):
            saved = CaptureProfile.model_validate(store.setting("capture_profile", {}))
            st.caption("首次使用先选屏幕预设，再校准区域。后台采集持续到手动停止或服务退出；关闭网页不会停止采集。")
            preset = st.selectbox("字幕区域预设", ["已保存 / 自定义", "主屏底部字幕", "主屏中央对话"])
            region = saved.region()
            if preset != "已保存 / 自定义":
                try:
                    import mss
                    with mss.mss() as screen:
                        monitor = screen.monitors[1]
                    region = {"left": monitor["left"] + int(monitor["width"] * .12),
                              "top": monitor["top"] + int(monitor["height"] * (.70 if preset == "主屏底部字幕" else .42)),
                              "width": int(monitor["width"] * .76), "height": int(monitor["height"] * .24)}
                except Exception:
                    st.warning("未找到屏幕或未安装采集依赖，请使用自定义坐标。")
            with st.form("capture_settings"):
                cols = st.columns(4)
                coords = {key: col.number_input(label, value=value, step=10)
                          for col, (key, value), label in zip(cols, region.items(), ["左 X", "上 Y", "宽", "高"], strict=True)}
                cast = st.text_input("捕捉场景人物", value=saved.cast)
                interval = st.slider("采样间隔（秒）", .5, 10.0, float(min(saved.interval, 10)), .5)
                confidence = st.slider("最低识别置信度", .1, 1.0, saved.confidence, .05)
                if st.form_submit_button("保存采集配置"):
                    try:
                        profile = CaptureProfile(**coords, interval=interval, confidence=confidence, cast=cast)
                        store.save_setting("capture_profile", profile.model_dump())
                        st.success("配置已保存，下一次启动采集时生效。")
                    except ValueError:
                        st.error("请检查区域尺寸、坐标和在场人物。")
            if st.button("预览已保存的字幕区域"):
                try:
                    import mss
                    from PIL import Image
                    profile = CaptureProfile.model_validate(store.setting("capture_profile", {}))
                    with mss.mss() as screen:
                        shot = screen.grab(profile.region())
                        st.image(Image.frombytes("RGB", shot.size, shot.rgb))
                except Exception:
                    st.error('无法截取区域，请安装 pip install -e ".[capture]" 并检查屏幕坐标。')
            new_timeline = st.checkbox("本次开始新的捕捉时间线")
            a, b = st.columns(2)
            if a.button("启动后台捕捉", type="primary", use_container_width=True):
                try:
                    service.start(CaptureProfile.model_validate(store.setting("capture_profile", {})),
                                  new_timeline=new_timeline)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
            if b.button("停止捕捉", use_container_width=True):
                service.stop()
                st.rerun()
    with right:
        st.markdown('<div class="section-kicker">QUICK START / 改变从这里开始</div>', unsafe_allow_html=True)
        st.subheader("选一段未写完的故事")
        for title, cast, content in STARTERS:
            with st.container(border=True):
                st.markdown("**" + title + "**")
                st.caption(cast + " · 原创开局")
                st.write(content.replace("【原创开局】", ""))
                if st.button("进入这段故事", key="starter_" + title, use_container_width=True):
                    jump(store.add(title, content, cast))
        with st.expander("从零创建 / 手动补录"), st.form("new_node"):
            title = st.text_input("节点标题", placeholder="给这个瞬间取个名字", key="new_title")
            cast = st.text_input("在场人物（用逗号分隔）", value="三月七，丹恒", key="new_cast")
            content = st.text_area("当前剧情 / 自定义开局", height=150, key="new_content")
            if st.form_submit_button("建立剧情节点", type="primary"):
                try:
                    jump(store.add(title, content, cast))
                except ValueError:
                    st.error("请填写剧情和在场人物，剧情最多 24000 字。")


@st.fragment(run_every=2)
def capture_status(service):
    status = service.status()
    st.caption(f"{STATES[status['state']]} · 已采样 {status['frames']} 帧 · 保存 {status['saved']} 条 · OCR {status['latency_ms']} ms")
    if status["error"]:
        st.error(status["error"])
    elif status["last_text"]:
        st.markdown('<div class="timeline-item"><div class="time">最近识别 · ' +
                    html.escape((status["last_seen"] or "")[:19]) + '</div><div class="line">' +
                    html.escape(status["last_text"][:700]) + '</div></div>', unsafe_allow_html=True)
    if status["last_node"] and st.button("打开最新捕捉剧情"):
        jump(status["last_node"])


def story_library(store, nodes, node, live):
    st.subheader("故事档案")
    search, category = st.columns([3, 1])
    query = search.text_input("搜索剧情、人物或标题", placeholder="找回那个想要改变的瞬间", key="library_query")
    kind = category.selectbox("来源", ["全部", *KINDS.values()])
    found = [n for n in reversed(nodes) if query.casefold() in (n["title"] + n["content"] + n["cast"]).casefold()
             and (kind == "全部" or KINDS[n["kind"]] == kind)]
    st.caption(f"找到 {len(found)} 个节点 · 选择节点可查看祖先、比较改写或继续故事")
    with st.expander("检索结果", expanded=bool(query) or not node):
        for n in found[:40]:
            col, action = st.columns([5, 1])
            col.write(f"{n['title']} · {KINDS[n['kind']]} · {n['cast']}")
            if action.button("打开", key="open_" + n["id"]):
                jump(n["id"])
        if len(found) > 40:
            st.caption("显示前 40 条，请输入更精确的关键词。")
    if node:
        branch = store.lineage(node["id"])
        left, right = st.columns([1.7, 1], gap="large")
        with left:
            scene(node)
            with st.expander("这条故事线的时间轴", expanded=False):
                for ancestor in branch:
                    st.markdown('<div class="timeline-item"><div class="time">' +
                                html.escape(KINDS[ancestor["kind"]] + " · " + ancestor["created"][:16]) +
                                '</div><div class="line">' + html.escape(ancestor["title"]) + '</div></div>', unsafe_allow_html=True)
            if node["parent"]:
                with st.expander("与父节点比较改写"):
                    parent = branch[-2]
                    a, b = st.columns(2)
                    a.caption("之前 · " + parent["title"])
                    a.write(parent["content"])
                    b.caption("现在 · " + node["title"])
                    b.write(node["content"])
                    st.code("\n".join(difflib.unified_diff(parent["content"].splitlines(), node["content"].splitlines(),
                                                          fromfile="原节点", tofile="当前节点", lineterm="")), language="diff")
            direction = st.text_input("续演方向（可选）", placeholder="让人物自行选择，展示分歧与代价", key="direction")
            if st.button("自然演进一轮", type="primary"):
                try:
                    with st.spinner("人物正在作出选择…"):
                        text = generate(store, node["id"], direction or "自然演进下一轮。", live=live)
                        new_id = store.add(f"续演 · {len(branch)}", text, node["cast"], "continuation", node["id"])
                    jump(new_id)
                except Exception:
                    st.error("生成失败，未写入后续。请检查连接设置或切换离线预演。")
        with right:
            with st.form("fork_" + node["id"]):
                st.markdown("**如果，这一次不一样**")
                title = st.text_input("新分支标题", value=node["title"][:100] + " · 如果")
                cast = st.text_input("分支在场人物", value=node["cast"])
                change = st.text_area("改写 / 校正后的剧情前提", value=node["content"], height=220)
                if st.form_submit_button("从这里创建分支", type="primary"):
                    try:
                        jump(store.add(title, change, cast, "fork", node["id"]))
                    except ValueError:
                        st.error("请检查标题、剧情长度和在场人物。")
            st.download_button("导出当前分支与对话", store.export(node["id"]),
                               file_name=f"WhatIfStarRail-{node['id'][:8]}.json", mime="application/json", use_container_width=True)
    else:
        st.info("从伴游控制台选择开局，或者导入已有故事归档。")
    with st.expander("导入故事归档"):
        st.caption("支持本项目导出的 v1 JSON；校验通过后以全新节点 ID 导入，不覆盖已有故事。上限 8 MB。")
        uploaded = st.file_uploader("选择故事 JSON", type=["json"])
        if uploaded:
            try:
                raw = uploaded.getvalue()
                if len(raw) > 8 * 1024 * 1024:
                    raise ValueError("文件过大")
                archive = StoryArchive.model_validate_json(raw)
                st.info(f"待导入：{len(archive.nodes)} 个节点 / {len(archive.chats)} 轮对话")
                if st.button("确认导入归档"):
                    jump(store.import_archive(raw.decode("utf-8")))
            except ValueError:
                st.error("归档无效：请检查版本、节点引用及文件大小。")


def character_chat(store, node, live):
    if not node:
        st.info("先选择一段剧情，再邀请其中的人物与你对话。")
        return
    left, right = st.columns([2, 1], gap="large")
    with right:
        st.caption("当前时刻")
        st.markdown("**" + node["title"] + "**")
        st.write(node["content"][:700])
        st.caption("只使用当前分支前文。角色卡可以在「角色档案」编辑。")
        st.markdown("**可以这样问**")
        st.caption("你现在最担心什么？\n\n如果我请求你留下，你会怎么选择？\n\n你知道我是从屏幕外和你说话的吗？")
    with left:
        actors = [a.strip() for a in node["cast"].replace("，", ",").split(",") if a.strip()]
        actor = st.selectbox("对话人物", actors, key="chat_actor")
        card = next((c for c in store.cards() if c["name"] == actor), None)
        if card:
            st.caption(card["voice"])
        st.subheader("与 " + actor + " 的跨屏通讯")
        for item in store.chats(node["id"], actor):
            with st.chat_message("user"):
                st.write(item["question"])
            with st.chat_message("assistant"):
                st.write(item["answer"])
        question = st.chat_input("说出那个原本无法告诉 TA 的想法…")
        if question:
            try:
                with st.spinner(actor + "正在回应…"):
                    answer = generate(store, node["id"], question[:4000], actor=actor, live=live)
                store.chat(node["id"], actor, question[:4000], answer)
                st.rerun()
            except Exception:
                st.error("角色回应失败，记录未写入。请检查连接设置后重试。")


def character_editor(store):
    st.subheader("让每个人，有自己的声音")
    st.caption("角色卡决定生成时的身份、表达习惯和知识边界。内置卡只使用公开概述，不加载模拟场景的私密线索。")
    cards = store.cards()
    cols = st.columns(2)
    for index, card in enumerate(cards):
        portrait = ""
        if card["name"] in PORTRAITS:
            url = asset(str(ROOT / "app/assets/characters" / (PORTRAITS[card["name"]] + ".png")))
            portrait = '<img src="' + url + '" alt="' + html.escape(card["name"]) + '">'
        with cols[index % 2]:
            st.markdown('<div class="persona">' + portrait + '<h3>' + html.escape(card["name"]) +
                        '</h3><p>' + html.escape(card["identity"][:180]) + '</p><span class="tag">可编辑角色卡</span></div>', unsafe_allow_html=True)
            st.write("")
    selection = st.selectbox("编辑角色", ["新建角色", *[c["name"] for c in cards]], key="card_selection")
    card = next((c for c in cards if c["name"] == selection), CharacterCard(name="新角色").model_dump())
    with st.form("card_" + selection):
        name = st.text_input("人物名称", value=card["name"], disabled=selection != "新建角色")
        identity = st.text_area("身份与性格", value=card["identity"])
        voice = st.text_area("说话方式", value=card["voice"])
        boundaries = st.text_area("知识边界与行为约束", value=card["boundaries"])
        if st.form_submit_button("保存角色卡"):
            try:
                store.save_card(CharacterCard(name=name, identity=identity, voice=voice, boundaries=boundaries))
                st.rerun()
            except ValueError:
                st.error("请填写人物名称并检查字段长度。")


def connections(store, model_ready):
    st.subheader("连接与设置")
    st.caption("将采集、故事数据和模型连接分开管理，让你的工作区可以长期使用。")
    a, b = st.columns(2, gap="large")
    with a:
        with st.container(border=True):
            st.markdown("**叙事模型**")
            st.caption("状态：" + ("已配置" if model_ready else "待配置") + " · 密钥不写入数据库或导出文件")
            with st.form("model_settings"):
                model = st.text_input("模型名称", value=store.setting("model", "") or os.getenv("ASTRAL_OPENAI_MODEL", ""))
                protocol = st.selectbox("接口协议", ["responses", "chat"],
                                        index=1 if store.setting("protocol") == "chat" else 0,
                                        format_func=lambda p: "Responses API" if p == "responses" else "Chat Completions（兼容接口）")
                if st.form_submit_button("保存模型设置"):
                    store.save_setting("model", model.strip())
                    store.save_setting("protocol", protocol)
                    st.success("已保存，下一次生成生效。")
            st.caption("服务启动前设置 OPENAI_API_KEY；兼容服务可设置 OPENAI_BASE_URL。切换端点时请同时使用该服务的密钥。")
        with st.container(border=True):
            st.markdown("**采集环境检查**")
            for package, label in [("mss", "屏幕采集"), ("rapidocr_onnxruntime", "本地 OCR"), ("openai", "模型 SDK")]:
                ready = importlib.util.find_spec(package) is not None
                st.write(("✓ " if ready else "○ ") + label + (" · 已安装" if ready else " · 未安装"))
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
