# -*- coding: utf-8 -*-
"""
build_excel.py —— 读 job_match_raw.json，输出在线 Excel（腾讯文档 sheet）。

列：优先级 | 公司 | 岗位 | 类型 | 薪资 | 匹配理由 | 投递链接
- 可投岗位：按 ①②③④ 色块排序，整行浅色填充
- 标红岗位（4类做不了）：整行浅红，优先级列填「不投」，匹配理由列填标红理由
- 全灰公司（所有目标岗都标红）：整公司标灰，置底
- 公司列、投递链接列：同一公司合并单元格
"""
import json
import sys
from urllib.parse import urlparse

BASE = r"C:/Users/Lenovo/WorkBuddy/2026-09-09-20-49-24"
sys.path.insert(0, BASE)
sys.path.insert(0, r"C:/Users/Lenovo/.workbuddy/plugins/cache/workbuddy-builtin/tencent-docs-plugin/5.5.4-wb.38151288.g1ca4889a.h1a8f7c37fe76/skills/tencent-docs")

import gen_report as gr
import tencentdocs as td

TDOC_RAW = f"{BASE}/tdoc_today_raw.json"

BLOCK_COLOR = {
    "①": "FFDDEBF7",   # 蓝
    "②": "FFE2EFDA",   # 绿
    "③": "FFFFF2CC",   # 黄
    "④": "FFFCE4EC",   # 粉
    "未知": "FFEDEDED",  # 灰
}
BLOCK_ORDER = {"①": 0, "②": 1, "③": 2, "④": 3, "未知": 4}
TYPE_ORDER = {"运营": 0, "市场销售": 1, "产品": 2}
RED_COLOR = "FFFFC7CE"   # 浅红（标红：做不了）
GRAY_COLOR = "FFD9D9D9"  # 浅灰（标灰：全灰公司置底）


# ---------- 公司 -> 投递链接 ----------
def parse_comp_links(tdoc_path):
    """从投递表原始 JSON 解析 公司名 -> 投递链接（第9列，去重）。"""
    raw = json.load(open(tdoc_path, encoding="utf-8"))
    text = raw["result"]["content"][0]["text"]
    inner = json.loads(text)
    content = inner["content"]
    comp_map = {}
    for line in content.split("\n"):
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 9 and cells[8]:
                name = cells[2]
                apply = cells[8]
                if name and name not in comp_map:
                    comp_map[name] = apply
    return comp_map


def _is_portal(u):
    return any(k in u for k in ("mokahr", "zhiye.com", "feishu", "hotjob", "51job", "zhaopin"))


def match_link(comp, comp_map):
    """job 里的公司短名 -> 投递表里的完整链接（双向包含模糊匹配，优先门户链接）。"""
    if comp in comp_map and _is_portal(comp_map[comp]):
        return comp_map[comp]
    fallback = None
    for k, v in comp_map.items():
        if comp and (comp in k or k in comp):
            if _is_portal(v):
                return v
            if fallback is None:
                fallback = v
    if comp in comp_map:
        return comp_map[comp]
    return fallback


def host_of(url):
    try:
        return urlparse(url).netloc
    except Exception:
        return url


# ---------- 构建行 ----------
def build_rows(comp_map):
    jobs = json.load(open(f"{BASE}/job_match_raw.json", encoding="utf-8"))
    target = [j for j in jobs if j["_type"] in ("运营", "市场销售", "产品") and not gr.is_intern(j)]

    rows = []
    for j in target:
        label, ge18, precise = gr.salary_of(j)
        b = gr.block_of(j["_exp"], ge18)
        hits = "、".join(j["_hits"]) if j["_hits"] else "—"
        link = match_link(j["_company"], comp_map) or ""
        undoable = bool(j.get("_undoable"))
        reason = j.get("_undoable_reason", "") or ""
        # (block, company, title, type, salary, hits, link, undoable, reason)
        rows.append((b, j["_company"], j["title"], j["_type"], label, hits, link, undoable, reason))
    return rows


def call(tool, args):
    result, err = td.call_tool("tencent-docs", tool, args)
    if err:
        raise RuntimeError(f"{tool} 调用失败: {err}")
    r = (result or {}).get("result") or {}
    sc = r.get("structuredContent") or {}
    return sc


def main():
    comp_map = parse_comp_links(TDOC_RAW)
    rows = build_rows(comp_map)
    print(f"目标岗共 {len(rows)} 个，标红 {sum(1 for r in rows if r[7])} 个")

    from collections import Counter, defaultdict
    ok_rows = [r for r in rows if not r[7]]
    print("可投分块分布:", dict(Counter(r[0] for r in ok_rows)))

    # 公司分组
    co_rows = defaultdict(list)
    for r in rows:
        co_rows[r[1]].append(r)

    def is_all_gray(rlist):
        return all(r[7] for r in rlist)

    def co_sort_key(co):
        rlist = co_rows[co]
        if is_all_gray(rlist):
            return (1, co)  # 全灰公司置底
        best = min(BLOCK_ORDER[r[0]] for r in rlist if not r[7])
        return (0, best, co)  # 可投公司按最靠前色块排序

    sorted_cos = sorted(co_rows.keys(), key=co_sort_key)

    # 最终行顺序：可投公司(可投岗按色块排前 + 标红岗排后) -> 全灰公司(置底)
    final_rows = []
    for co in sorted_cos:
        rlist = co_rows[co]
        ok = sorted([r for r in rlist if not r[7]],
                    key=lambda r: (BLOCK_ORDER[r[0]], TYPE_ORDER.get(r[3], 9), r[2]))
        bad = sorted([r for r in rlist if r[7]], key=lambda r: r[2])
        final_rows.extend(ok)
        final_rows.extend(bad)

    def row_color(r):
        co = r[1]
        if is_all_gray(co_rows[co]):
            return GRAY_COLOR
        if r[7]:
            return RED_COLOR
        return BLOCK_COLOR[r[0]]

    # 分组：连续相同公司（在 final_rows 上）
    groups = []
    i = 0
    while i < len(final_rows):
        co = final_rows[i][1]
        j = i
        while j < len(final_rows) and final_rows[j][1] == co:
            j += 1
        groups.append((co, i, j - 1))
        i = j
    print(f"公司数 {len(co_rows)}，全灰 {sum(1 for c in sorted_cos if is_all_gray(co_rows[c]))} 家")

    # 1) 创建在线表格
    sc = call("manage.create_file", {"title": "校招岗位JD匹配（4色块·标红标灰）", "file_type": "sheet"})
    file_id = sc.get("file_id", "")
    file_url = sc.get("url", "")
    print("FILE_ID:", file_id)

    # 2) 拿 sheet_id
    sc = call("sheet.get_sheet_info", {"file_id": file_id})
    sheet_id = sc["sheets"][0]["sheet_id"]

    # 3) 改子表名
    call("sheet.rename_sheet", {"file_id": file_id, "sheet_id": sheet_id, "name": "岗位匹配"})

    # 4) 写数据（第0行图例 + 第1行表头 + 第2行起数据）
    legend = ("【颜色图例】\n"
              "蓝=①匹配+薪资≥18万(优先投)｜绿=②匹配+薪资<18万｜黄=③不匹配+薪资≥18万｜粉=④不匹配+薪资<18万(靠后)｜灰=薪资未知\n"
              "红=做不了(4类：硬件技术产品/供应链/医学销售/产品工程师)｜深灰=全灰公司(无合适岗置底)\n"
              "【判断标准】匹配=经验直接或可迁移；薪资门槛=年包18万")
    values = [{"row": 0, "col": 0, "value_type": "STRING", "string_value": legend}]
    header = ["优先级", "公司", "岗位", "类型", "薪资", "匹配理由", "投递链接"]
    values += [{"row": 1, "col": c, "value_type": "STRING", "string_value": h} for c, h in enumerate(header)]

    first_row_of_group = {s: True for (_, s, _) in groups}
    for i, r in enumerate(final_rows):
        block, comp, title, typ, sal, hits, link, undoable, reason = r
        row_idx = i + 2
        prio = "不投" if undoable else block
        reason_col = reason if undoable else hits
        for c, v in [(0, prio), (2, title), (3, typ), (4, sal), (5, reason_col)]:
            values.append({"row": row_idx, "col": c, "value_type": "STRING", "string_value": v})
        if i in first_row_of_group:
            values.append({"row": row_idx, "col": 1, "value_type": "STRING", "string_value": comp})
            values.append({"row": row_idx, "col": 6, "value_type": "STRING", "string_value": host_of(link) if link else "—"})

    BATCH = 800
    for s in range(0, len(values), BATCH):
        chunk = values[s:s + BATCH]
        call("sheet.set_range_value", {"file_id": file_id, "sheet_id": sheet_id, "values": chunk})
        print(f"  已写 {min(s + BATCH, len(values))}/{len(values)} 单元格")
    print("数据写入完成")

    # 5) 图例行合并 + 样式（第0行，横跨7列）
    call("sheet.merge_cell", {
        "file_id": file_id, "sheet_id": sheet_id,
        "start_row": 0, "end_row": 0, "start_col": 0, "end_col": 6,
    })
    call("sheet.set_cell_style", {
        "file_id": file_id, "sheet_id": sheet_id,
        "start_row": 0, "end_row": 0, "start_col": 0, "end_col": 6,
        "bg_color": "FFD9E1F2", "bold": False, "font_color": "FF1F1F1F",
        "horizontal_align": "left", "vertical_align": "center",
    })

    # 6) 表头样式（第1行）
    call("sheet.set_cell_style", {
        "file_id": file_id, "sheet_id": sheet_id,
        "start_row": 1, "end_row": 1, "start_col": 0, "end_col": 6,
        "bg_color": "FF4472C4", "bold": True, "font_color": "FFFFFFFF",
        "horizontal_align": "center", "vertical_align": "center",
    })

    # 7) 数据行按颜色连续段上色（色块 / 标红 / 标灰）
    cur_color = None
    start_row = None
    for i, r in enumerate(final_rows):
        row_idx = i + 2
        color = row_color(r)
        if color != cur_color:
            if cur_color is not None:
                call("sheet.set_cell_style", {
                    "file_id": file_id, "sheet_id": sheet_id,
                    "start_row": start_row, "end_row": row_idx - 1,
                    "start_col": 0, "end_col": 6,
                    "bg_color": cur_color,
                })
            cur_color = color
            start_row = row_idx
    if cur_color is not None:
        call("sheet.set_cell_style", {
            "file_id": file_id, "sheet_id": sheet_id,
            "start_row": start_row, "end_row": len(final_rows) + 1,
            "start_col": 0, "end_col": 6,
            "bg_color": cur_color,
        })
    print("上色完成")

    # 7) 合并单元格：公司列 + 链接列
    for comp, s, e in groups:
        if e > s:
            call("sheet.merge_cell", {
                "file_id": file_id, "sheet_id": sheet_id,
                "start_row": s + 2, "end_row": e + 2, "start_col": 1, "end_col": 1,
            })
            call("sheet.merge_cell", {
                "file_id": file_id, "sheet_id": sheet_id,
                "start_row": s + 2, "end_row": e + 2, "start_col": 6, "end_col": 6,
            })
    print("合并单元格完成")

    # 8) 超链接
    for comp, s, e in groups:
        link = final_rows[s][6]
        if link:
            call("sheet.set_link", {
                "file_id": file_id, "sheet_id": sheet_id,
                "row": s + 2, "col": 6,
                "url": link, "display_text": host_of(link),
            })
    print("超链接设置完成")

    # 9) 输出链接
    full = f"{file_url}?_fid={file_id}"
    print("LINK:", full)
    with open(f"{BASE}/outputs/job-match/excel_link.txt", "w", encoding="utf-8") as f:
        f.write(full)


if __name__ == "__main__":
    main()
