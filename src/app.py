#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
经营分析智能体 — 周报生成器
上传 Excel → AI 分析 → 下载 HTML 报告
"""

import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from datetime import datetime
import anthropic

# ─── 配置文件读写 ─────────────────────────────────────────────────
CONFIG_PATH = Path.home() / ".weekly-report" / "config.json"

def load_local_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}

def save_local_config(data: dict):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = load_local_config()
    current.update(data)
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")

# ─── 页面配置 ────────────────────────────────────────────────────
st.set_page_config(
    page_title="经营分析智能体",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', 'Inter', sans-serif;
}
.main { background: #F5F5F7; }
.block-container { padding: 2rem 2.5rem; max-width: 960px; margin: 0 auto; }
.title-area { text-align: center; padding: 2.5rem 0 1.5rem; }
.title-area h1 { font-size: 2rem; font-weight: 700; color: #1D1D1F; margin: 0; }
.title-area p { color: #6E6E73; font-size: 0.95rem; margin-top: 0.5rem; }
.upload-card {
    background: white; border-radius: 16px; padding: 2rem;
    border: 0.5px solid #D2D2D7; box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    margin-bottom: 1.5rem;
}
.status-bar {
    background: #EBF5FF; border-left: 4px solid #007AFF;
    border-radius: 8px; padding: 0.8rem 1.2rem;
    font-size: 0.9rem; color: #007AFF; margin: 1rem 0;
}
.stButton > button {
    background: #007AFF !important; color: white !important;
    border: none !important; border-radius: 10px !important;
    padding: 0.65rem 2rem !important; font-size: 1rem !important;
    font-weight: 600 !important; width: 100% !important;
    transition: all 0.2s !important;
}
.stButton > button:hover { background: #0066DD !important; }
.download-btn > button {
    background: #34C759 !important;
}
.step-badge {
    display: inline-block; background: #007AFF; color: white;
    border-radius: 50%; width: 24px; height: 24px; text-align: center;
    line-height: 24px; font-size: 12px; font-weight: 700; margin-right: 8px;
}
</style>
""", unsafe_allow_html=True)


# ─── Excel 读取 ───────────────────────────────────────────────────
def read_excel_data(uploaded_file) -> dict:
    """读取上传的 Excel，返回结构化数据字典"""
    excel_bytes = uploaded_file.getvalue()
    data = {}

    with pd.ExcelFile(BytesIO(excel_bytes)) as xl:
        sheets = xl.sheet_names

        for sheet in sheets:
            df = pd.read_excel(xl, sheet_name=sheet, header=None)
            # row 0: 标题行, row 2: 列名, row 3+: 数据
            if len(df) < 4:
                continue

            channels = ["淘系官旗", "唯品", "分销", "京东", "拼多多", "天猫超市", "淘系奥莱", "小平台"]
            rows = []
            for i in range(3, len(df)):
                row = df.iloc[i]
                season = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
                new_old = str(row.iloc[1]).strip() if pd.notna(row.iloc[1]) else ""
                if not season and not new_old:
                    continue

                channel_data = {}
                for j, ch in enumerate(channels):
                    val = row.iloc[2 + j]
                    channel_data[ch] = float(val) if pd.notna(val) and str(val) not in ['nan', ''] else None

                retail_amt = row.iloc[10] if len(row) > 10 else None
                yoy = row.iloc[11] if len(row) > 11 else None
                share = row.iloc[12] if len(row) > 12 else None

                rows.append({
                    "季节": season,
                    "新老品": new_old,
                    "渠道同比": channel_data,
                    "零售额": float(retail_amt) if pd.notna(retail_amt) else None,
                    "同比": float(yoy) if pd.notna(yoy) else None,
                    "占比": float(share) if pd.notna(share) else None,
                })

            data[sheet] = rows

    return data, sheets


def build_data_summary(data: dict, sheets: list, target_week: str) -> str:
    """将数据转为 AI 可读的文本摘要"""
    lines = []
    lines.append(f"# 经营数据摘要 — 目标周：{target_week}")
    lines.append(f"共包含 {len(sheets)} 周数据，Sheet名称：{', '.join(sheets)}\n")

    for sheet in sheets:
        rows = data.get(sheet, [])
        lines.append(f"## {sheet}")
        for r in rows:
            row_str = f"  [{r['季节']}|{r['新老品']}] 零售额={r['零售额']} 同比={r['同比']} 占比={r['占比']}"
            ch_str = " | ".join(
                f"{k}:{v:.1%}" if isinstance(v, float) else f"{k}:N/A"
                for k, v in r["渠道同比"].items()
            )
            lines.append(row_str)
            lines.append(f"    渠道: {ch_str}")
        lines.append("")

    return "\n".join(lines)


# ─── AI 调用 ─────────────────────────────────────────────────────
def generate_report_with_ai(data_summary: str, target_week: str, api_key: str, base_url: str = "", model: str = "claude-sonnet-4-6") -> str:
    """调用 Claude API 生成 HTML 报告"""

    client = anthropic.Anthropic(
        api_key=api_key,
        base_url=base_url if base_url else None,
    )

    system_prompt = """你是一位专业的电商经营分析师，擅长生成苹果设计风格的 HTML 经营分析报告。

严格按照以下规范生成单文件 HTML：

## 设计规范
- 背景色：#F5F5F7，卡片：#FFFFFF，分割线：#D2D2D7
- 主蓝：#007AFF，正向绿：#34C759，负向红：#FF3B30，警告橙：#FF9500
- 字体：-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'PingFang SC', sans-serif
- 卡片：border-radius 12px，border 0.5px solid #D2D2D7，box-shadow 0 1px 3px rgba(0,0,0,0.05)
- 所有图表用 SVG 手写，不用任何第三方图表库

## 报告结构（必须按顺序，共5个模块）

**MODULE 01 — 整体大盘**
- KPI三卡：当周全渠道零售额 / 当周同比增速 / 预算目标差距
- 三周汇总表：日期范围/零售额/同比/环比/状态
- SVG趋势折线图（三周零售额，蓝色渐变填充）
- SVG缺口柱状图（三周同比 vs 预算目标）
- 蓝色左边框结论框

**MODULE 02 — 渠道诊断**
- 8大渠道状态表（淘系官旗/唯品/分销/京东/拼多多/天猫超市/淘系奥莱/小平台）
- 每行含：同比/预算差距/三周趋势/状态徽章（绿=超预期/黄=预警/红=问题/蓝=关注）
- SVG多组柱状图（8渠道×三周，蓝/绿/橙三色）
- 强势渠道洞察（绿边框）+ 问题渠道洞察（红边框）两栏

**MODULE 03 — 季节结构**
- 五季节（Q1/Q2/Q3/Q4/Q9）三周明细表：零售额/同比/占比/趋势
- 季节占比甜甜圈 SVG + 季节三周同比折线 SVG（两列布局）
- 各季节独立卡片（含品类诊断文字）
- 结论框

**MODULE 04 — 新老品分析**
- 新老品三周对比汇总表（电商新品/线下新品/电商一年期/线下一年期）
- 亮点（绿边框）+ 风险（红边框）两栏
- 结论框

**MODULE 05 — 重点问题与行动计划**
- P1~P4优先级卡片（红/橙/黄/蓝左边框）
- 每卡：优先级标签+问题描述+三格KPI+诊断+行动清单（→）

## 输出要求
- 只输出完整的 HTML，从 <!DOCTYPE html> 开始，到 </html> 结束
- 不要任何 markdown 标记，不要代码块包裹
- CSS 全部内联在 <style> 标签，不引用外部资源
- 中文全程，数据来自用户提供的 Excel 摘要"""

    user_prompt = f"""请根据以下数据生成 {target_week} 的完整经营分析周报 HTML：

{data_summary}

要求：
1. 数据全部来自上面的摘要，不要编造数据
2. 对数据缺失的地方用"暂无数据"或"-"填充
3. 分析洞察要专业、具体，指出真实问题
4. 行动计划要可执行，结合数据给出具体建议
5. 直接输出 HTML，不要任何其他文字"""

    with st.status("🤖 AI 正在分析数据并生成报告...", expanded=True) as status:
        st.write("📊 解析数据结构...")
        time.sleep(0.5)
        st.write("🧠 AI 开始分析，这需要约 30-60 秒...")

        html_content = ""
        with client.messages.stream(
            model=model,
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        ) as stream:
            for text in stream.text_stream:
                html_content += text

        st.write("✅ 报告生成完成！")
        status.update(label="✅ 报告已生成！", state="complete")

    # 清理掉可能的 markdown 代码块包裹
    if "```html" in html_content:
        html_content = html_content.split("```html")[1].split("```")[0].strip()
    elif "```" in html_content:
        html_content = html_content.split("```")[1].split("```")[0].strip()

    return html_content


# ─── 主界面 ───────────────────────────────────────────────────────
def main():
    # ─── 侧边栏配置面板 ─────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚙️ 模型配置")

        cfg = load_local_config()

        # 优先用环境变量，否则用配置文件
        default_key   = os.environ.get("ANTHROPIC_API_KEY", "") or cfg.get("apiKey", "")
        default_url   = os.environ.get("OPENROUTER_BASE_URL", "") or cfg.get("baseUrl", "https://semir.onerouter.com/api")
        default_model = os.environ.get("WEEKLY_REPORT_MODEL", "") or cfg.get("model", "claude-sonnet-4-6")

        input_key   = st.text_input("API Key", value=default_key, type="password", placeholder="sk-...")
        input_url   = st.text_input("Base URL", value=default_url, placeholder="https://...")
        model_options = ["claude-sonnet-4-6", "claude-opus-4-5", "claude-haiku-3-5", "gpt-4o", "gpt-4o-mini"]
        input_model = st.selectbox(
            "模型",
            options=model_options,
            index=model_options.index(default_model) if default_model in model_options else 0
        )

        if st.button("💾 保存配置", use_container_width=True):
            save_local_config({"apiKey": input_key, "baseUrl": input_url, "model": input_model})
            st.success("✅ 已保存")
            st.rerun()

        # 用当前输入值（不一定已保存）作为本次运行的 key
        api_key    = input_key
        base_url   = input_url
        model_name = input_model

        st.markdown("---")
        st.markdown("**使用说明**")
        st.markdown("""
1. 填入 API Key 并点击「保存配置」
2. 上传 Excel 数据文件
3. 设置目标周数
4. 点击生成报告
""")

    # 标题
    st.markdown("""
    <div class="title-area">
        <h1>📊 经营分析智能体</h1>
        <p>上传周同比数据 Excel，AI 自动生成苹果风格经营分析周报</p>
    </div>
    """, unsafe_allow_html=True)

    # 步骤卡
    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown("#### 📁 上传数据文件")
        uploaded = st.file_uploader(
            "拖拽或点击上传「产品周同比数据.xlsx」",
            type=["xlsx", "xls"],
            label_visibility="collapsed"
        )

        if uploaded:
            st.success(f"✅ 已上传：{uploaded.name}  ({uploaded.size // 1024} KB)")

    with col2:
        st.markdown("#### ⚙️ 报告设置")
        week_num = st.number_input("目标周数", min_value=1, max_value=53, value=13, step=1)
        target_week = f"W{week_num:02d}"
        st.caption(f"将生成 **{datetime.now().year}年第{week_num}周** 报告")

    st.markdown("---")

    # 生成按钮
    col_btn, _, _ = st.columns([1, 1, 1])
    with col_btn:
        generate = st.button("🚀 生成经营分析报告", use_container_width=True)

    # 执行生成
    if generate:
        if not uploaded:
            st.error("⚠️ 请先上传 Excel 数据文件")
            return
        if not api_key:
            st.warning("⚠️ 请先在左侧边栏填入 API Key，然后点击「保存配置」")
            return

        try:
            # 读取数据
            with st.spinner("读取 Excel 数据..."):
                data, sheets = read_excel_data(uploaded)
                data_summary = build_data_summary(data, sheets, target_week)

            st.info(f"📋 检测到 {len(sheets)} 周数据：{', '.join(sheets)}")

            # 生成报告
            html_report = generate_report_with_ai(data_summary, target_week, api_key, base_url, model_name)

            if not html_report.strip().startswith("<!DOCTYPE") and not html_report.strip().startswith("<html"):
                st.error("报告生成格式异常，请重试")
                with st.expander("查看原始输出"):
                    st.text(html_report[:2000])
                return

            # 保存到 session state
            st.session_state["report_html"] = html_report
            st.session_state["report_week"] = target_week

        except anthropic.AuthenticationError:
            st.error("❌ API Key 无效，请在左侧边栏重新填写正确的 API Key")
        except Exception as e:
            st.error(f"❌ 生成失败：{str(e)}")
            raise

    # 下载区域
    if "report_html" in st.session_state:
        st.markdown("---")
        st.markdown("### ✅ 报告已就绪，点击下载")

        week = st.session_state["report_week"]
        filename = f"经营分析报告_{week}_{datetime.now().strftime('%Y%m%d')}.html"

        col_dl, col_preview, _ = st.columns([1, 1, 1])

        with col_dl:
            st.download_button(
                label=f"⬇️ 下载 {week} 报告 (HTML)",
                data=st.session_state["report_html"].encode("utf-8"),
                file_name=filename,
                mime="text/html",
                use_container_width=True,
                key="dl_btn"
            )

        with col_preview:
            if st.button("🗑️ 清除，重新生成", use_container_width=True):
                del st.session_state["report_html"]
                del st.session_state["report_week"]
                st.rerun()

        st.caption("💡 下载后用浏览器打开即可查看；在浏览器按 Ctrl+P 可另存为 PDF")

    # 底部说明
    st.markdown("---")
    with st.expander("📖 使用说明"):
        st.markdown("""
**数据文件格式要求**
- 文件名：`产品周同比数据.xlsx`
- 每张 Sheet 对应一周数据（Sheet名如：W11、W12、W13）
- 建议上传目标周 + 前两周，共3个Sheet（用于趋势对比）

**报告包含内容**
1. MODULE 01 — 整体大盘（KPI + 趋势图 + 缺口分析）
2. MODULE 02 — 渠道诊断（8大渠道 + 强势/问题洞察）
3. MODULE 03 — 季节结构（Q1~Q4/Q9 + 甜甜圈图）
4. MODULE 04 — 新老品分析
5. MODULE 05 — 重点问题与行动计划

**生成时间**：约 30~60 秒
        """)


if __name__ == "__main__":
    main()
