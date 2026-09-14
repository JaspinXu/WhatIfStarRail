from pathlib import Path

import streamlit as st

from astral_agents.companion import (
    StoryStore,
    SubtitleBuffer,
    capture_subtitles,
    generate,
)


def render(database: Path):
    store = StoryStore(database)
    st.markdown("<style>.block-container{padding-top:3.5rem}"
                "button[role=tab][aria-selected=true] p{color:#071725!important}"
                "</style>", unsafe_allow_html=True)
    st.markdown('<div class="hero"><div class="eyebrow">ASTRAL LINK / 星铁伴游</div>'
                '<div class="hero-title">在故事发生时，走进故事。</div>'
                '<div class="hero-sub">捕捉这一刻 · 与角色跨越第四面墙 · '
                '让一个不同的选择，生长成新的世界</div></div>', unsafe_allow_html=True)
    st.caption("非官方本地伴游插件 · 改写保存在独立故事分支 · 角色内心为同人推演")
    live = st.sidebar.toggle("使用模型生成", value=False)
    st.sidebar.caption("离线模式可体验全部流程。模型模式会发送所选分支的文本与对话，截图留在本机。")
    nodes = store.nodes()
    c1, c2, c3 = st.columns(3)
    c1.metric("剧情节点", len(nodes))
    c2.metric("改写分支", sum(n["kind"] == "fork" for n in nodes))
    c3.metric("引擎", "模型生成" if live else "离线示意")
    capture_tab, story_tab, chat_tab = st.tabs(["◉ 剧情接入", "⑂ 分支工作室", "✧ 跨屏对话"])
    with capture_tab:
        st.subheader("把游戏中的这一刻带进来")
        st.caption("手动输入可从任何任务、任何角色、任何自定义世界开始。OCR 需要在运行服务的电脑上显示游戏。")
        with st.form("new_node"):
            title = st.text_input("节点标题", placeholder="例如：列车启程前的另一个选择")
            cast = st.text_input("在场人物（用逗号分隔）", value="三月七，丹恒")
            content = st.text_area("当前剧情 / 自定义开局", height=160,
                                   placeholder="写下已发生的事、地点、人物知道什么，以及尚未解决的矛盾。")
            if st.form_submit_button("建立剧情节点", type="primary"):
                try:
                    st.session_state.story_selected = store.add(title, content, cast)
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
        with st.expander("实时字幕捕捉 · 本地 OCR", expanded=False):
            st.caption("窗口化游戏，填写字幕区域的屏幕像素坐标（含说话人）。先预览，再开始；"
                       "建议伴游放在另一块屏幕。页面需保持连接。连续两帧稳定后自动记录，低置信度文字忽略。")
            coords = st.columns(4)
            left = coords[0].number_input("左 X", value=200, step=10)
            top = coords[1].number_input("上 Y", value=750, step=10)
            width = coords[2].number_input("宽", min_value=100, max_value=7680, value=1500, step=10)
            height = coords[3].number_input("高", min_value=50, max_value=2160, value=250, step=10)
            region = {"left": left, "top": top, "width": width, "height": height}
            capture_cast = st.text_input("捕捉场景人物", value="三月七，丹恒")
            interval = st.slider("采样间隔（秒）", 2, 10, 3)
            if st.button("开始新的捕捉时间线"):
                st.session_state.pop("capture_head", None)
                st.session_state.pop("subtitle_buffer", None)
                st.success("下一条稳定字幕将作为新的起点。")
            if st.button("预览字幕区域"):
                try:
                    import mss
                    from PIL import Image
                    with mss.mss() as screen:
                        shot = screen.grab(region)
                        st.image(Image.frombytes("RGB", shot.size, shot.rgb))
                except Exception:
                    st.error('无法截取区域。请安装 pip install -e ".[capture]" 并检查屏幕坐标。')
            enabled = st.toggle("开始自动捕捉", key="capture_enabled")
            if not enabled:
                st.session_state.pop("subtitle_buffer", None)
            if enabled and not capture_cast.replace("，", "").replace(",", "").strip():
                st.warning("请先填写捕捉场景人物。")
            elif enabled:
                poll_capture(store, region, capture_cast, interval)

    with story_tab:
        st.subheader("每个选择，都有自己的后续")
        if not nodes:
            st.info("先在「剧情接入」建立一个节点，再改写或自然续演。")
        else:
            ids = [n["id"] for n in nodes]
            by_id = {n["id"]: n for n in nodes}
            selected = st.selectbox("选择时间节点", ids, key="story_selected",
                                    format_func=lambda i: f"{by_id[i]['title']} · {i[:6]}")
            node = by_id[selected]
            branch = store.lineage(selected)
            st.caption(" → ".join(n["title"] for n in branch))
            st.markdown(node["content"])
            st.caption(f"在场：{node['cast']} · 来源：{node['kind']} · {node['created'][:19]}")
            with st.expander("查看此分支的前文"):
                for ancestor in branch[:-1]:
                    st.markdown(f"**{ancestor['title']}**")
                    st.write(ancestor["content"])
            with st.form("fork"):
                fork_title = st.text_input("新分支标题", value=f"{node['title']} · 如果")
                fork_cast = st.text_input("分支在场人物", value=node["cast"])
                change = st.text_area("改写 / 校正后的剧情前提", value=node["content"], height=150)
                if st.form_submit_button("从这里创建分支"):
                    try:
                        new_id = store.add(fork_title, change, fork_cast, "fork", selected)
                        st.session_state.pending_story = new_id
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            direction = st.text_input("续演方向（可选）", placeholder="例如：让人物自行选择，展示分歧与代价")
            if st.button("自然演进一轮", type="primary"):
                try:
                    with st.spinner("人物正在作出选择…"):
                        text = generate(store, selected, direction or "自然演进下一轮。", live=live)
                        new_id = store.add(f"续演 · {len(branch)}", text, node["cast"],
                                           "continuation", selected)
                    st.session_state.pending_story = new_id
                    st.rerun()
                except Exception:
                    st.error("生成失败，未写入后续。请检查模型名称、凭据、网络或切换离线模式。")
            st.download_button("导出当前分支与对话", store.export(selected),
                               file_name=f"astral-branch-{selected[:8]}.json", mime="application/json")
    with chat_tab:
        st.subheader("此时此地，听见 TA 的回答")
        if not nodes:
            st.info("建立剧情节点后，即可与其中的人物对话。")
        else:
            selected = st.session_state.story_selected
            node = next(n for n in nodes if n["id"] == selected)
            actors = list(dict.fromkeys(n.strip() for n in node["cast"].replace("，", ",").split(",") if n.strip()))
            actor = st.selectbox("对话人物", actors)
            st.caption(f"时间锚点：{node['title']}。只使用这个分支的前文；人物不会预知后续。")
            for item in store.chats(selected, actor):
                with st.chat_message("user"):
                    st.write(item["question"])
                with st.chat_message("assistant"):
                    st.write(item["answer"])
            question = st.chat_input("跨越屏幕，问问 TA 此刻的心境、处境，或提出你的选择…")
            if question:
                try:
                    with st.spinner(f"{actor}正在回应…"):
                        answer = generate(store, selected, question[:4000], actor=actor, live=live)
                    store.chat(selected, actor, question[:4000], answer)
                    st.rerun()
                except Exception:
                    st.error("角色回应失败。请检查模型配置或切换离线模式后重试。")


def poll_capture(store, region, cast, interval):
    @st.fragment(run_every=interval)
    def tick():
        try:
            if "ocr_reader" not in st.session_state:
                from rapidocr_onnxruntime import RapidOCR
                st.session_state.ocr_reader = RapidOCR()
            buffer = st.session_state.setdefault("subtitle_buffer", SubtitleBuffer())
            raw = capture_subtitles(region, st.session_state.ocr_reader)
            st.caption("捕捉中 · " + (raw[:160] or "等待字幕"))
            text = buffer.push(raw)
            if text:
                parent = st.session_state.get("capture_head")
                node_id = store.add(f"实况 · {text[:24]}", text, cast, "capture", parent)
                st.session_state.capture_head = node_id
                st.session_state.pending_story = node_id
                st.rerun()
        except Exception:
            st.error('OCR 不可用，请安装 pip install -e ".[capture]"，检查坐标后重新开启。')
    tick()
