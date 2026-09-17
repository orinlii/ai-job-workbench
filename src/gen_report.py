#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_report.py —— 读 job_match_raw.json，应用公司级薪资方向表，生成 4 色块 Markdown 报告
"""
import json, re
from collections import Counter, defaultdict

# 公司级薪资方向表（用于接口无薪资的岗位）
COMPANY_SALARY = {
    # ---- 9月15日投递表 ----
    "陕西德信":   {"dir": "<18万", "note": "陕汽控股旗下汽车零部件国企，校招销售/市场岗4-8K·15薪，总包6-15万", "lv": "C(估计)"},
    "云和恩墨":   {"dir": "<18万", "note": "数据库技术服务公司，销售管培方向年薪10-16万", "lv": "C(估计)"},
    "伊芙丽集团": {"dir": "<18万", "note": "杭州女装电商，电商商品/店铺运营6-8.5K/月≈8-11万", "lv": "A(就业网)"},
    "乐享元游":   {"dir": "<18万", "note": "广州游戏公司，运营/策划/广告投放6-12.5K/月≈8-16万", "lv": "B(就业网)"},
    "古茗茶饮":   {"dir": "临界", "note": "茶饮连锁，常规管培8-17K/月(<18万)；未来领袖专项起薪40-80万为顶尖口径，本科S级15万+", "lv": "A(官网/就业网)"},
    "Shopee":     {"dir": "≥18万", "note": "跨境电商，产品类校招年包约35万(郑大/沈航就业网)，产品经理20-35K/月", "lv": "A(就业网)"},
    "BIGO":       {"dir": "≥18万", "note": "欢聚旗下海外社交大厂，产品经理校招方向20-35万(互联网产品岗常规)", "lv": "C(估计)"},
    "鼎桥技术":   {"dir": "≥18万", "note": "华为+诺基亚合资，客户经理/产品行销13-16K/月·15薪≈20-24万", "lv": "B(就业网)"},
    "AIVA汽车":   {"dir": "临界", "note": "阿维塔(长安/华为/宁德合资)运营销售岗1.2-2.2万·15薪≈18-33万，但赛豆(二手车)口径未明，保守按临界", "lv": "B(就业网)"},
    "天虹数科":   {"dir": "<18万", "note": "零售国企，营销策划/运营管培5.5-10K/月·13薪≈7-13万", "lv": "A(就业网)"},
    "泰康之家":   {"dir": "<18万", "note": "养老社区，营销支持/市场4-10K/月·13薪≈5-13万", "lv": "A(就业网)"},
    "凯金新能源": {"dir": "<18万", "note": "电池负极材料，本科职能/产品/品牌类8-17万/年", "lv": "A(宣讲会)"},
    "先临三维":   {"dir": "<18万", "note": "3D扫描，本科5-10K/月≈6-12万(硕士10-25K)", "lv": "B(就业网)"},
    "新安股份":   {"dir": "<18万", "note": "化工，华洋化工营销/销售专员7-14K/月≈10-18万(本科<18万)", "lv": "B(就业网)"},
    "瑞沃德":     {"dir": "临界", "note": "生命科学仪器，商务专员9-15K/月·14-15薪≈12-22万", "lv": "B(就业网)"},
    "九江金鹭":   {"dir": "<18万", "note": "厦门钨业旗下硬质合金，本科运营/职能6-10K/月", "lv": "B(就业网)"},
}

def salary_of(j):
    """返回 (salary_label, ge18, precise)"""
    annual = j.get("_annual")
    if annual is not None:
        w = annual / 10000
        return (f"{w:.1f}万", annual >= 180000, True)
    info = COMPANY_SALARY.get(j["_company"], {})
    d = info.get("dir", "未知")
    note = info.get("note", "")
    if d == "<18万":
        return ("<18万", False, False)
    if d in ("≥18万", "部分≥18万"):
        return ("≥18万(方向级)", True, False)
    if d == "临界":
        return ("临界(待核)", False, False)  # 保守归②/④，标注待核
    return ("未知", None, False)  # 薪资未知，不落块或特殊处理

def block_of(exp, ge18):
    matched = exp in ("直接", "可迁移")
    if ge18 is None:
        return "未知"  # 薪资未知
    if matched and ge18: return "①"
    if matched and not ge18: return "②"
    if not matched and ge18: return "③"
    return "④"

def is_intern(j):
    """实习岗判断（求职者明确排除实习，只投校招正式全职）。
    只认 title 的"实习"二字 + 英文 intern（词边界，避免误杀 internal）。
    不用 type 字段 —— 多招聘系统的 type 字段含义混乱（蔚来/知乎/月之暗面把正式校招岗也标成"实习"），不可作依据。
    不认 trainee —— Management Trainee（管培生）是校招正式岗，必须保留。"""
    title = j.get("title") or ""
    if "实习" in title:
        return True
    if re.search(r"\bintern\b", title, re.IGNORECASE):
        return True
    return False

def main():
    jobs = json.load(open("job_match_raw.json", encoding="utf-8"))
    target = [j for j in jobs if j["_type"] in ("运营", "市场销售", "产品")]

    # 分块
    blocks = {"①": [], "②": [], "③": [], "④": [], "未知": []}
    for j in target:
        label, ge18, precise = salary_of(j)
        b = block_of(j["_exp"], ge18)
        j["_sal_label"] = label
        j["_sal_precise"] = precise
        blocks[b].append(j)

    # 块内排序：类型（运营>市场销售>产品）> 公司
    type_order = {"运营": 0, "市场销售": 1, "产品": 2}
    for b in blocks:
        blocks[b].sort(key=lambda x: (type_order.get(x["_type"], 9), x["_company"], x["title"]))

    # 统计
    tech_count = sum(1 for j in jobs if j["_type"] == "其他")
    n_comp = len(set(j["_company"] for j in jobs))

    lines = []
    lines.append("# 校招岗位 JD 匹配报告（4 色块归类）\n")
    lines.append(f"- **数据源**：9月14日投递表（100 行 / 99 家，可抓官网 JD 的 23 家：北森12/飞书2/Moka9，实际抓到 {n_comp} 家，共 {len(jobs)} 岗）")
    lines.append(f"- **目标岗**：运营/市场销售/产品 共 {len(target)} 岗；技术/职能岗 {tech_count} 岗已排除")
    lines.append(f"- **规则**：三维（技术佐证 + 经验为主 + 薪资门槛 18万）→ 四优先级分块；岗位类型 运营>市场销售>产品\n")
    lines.append(f"## 一句话总结\n")
    lines.append(f"23 家可抓官网 JD 的公司里，实际抓到 {n_comp} 家；目标岗 **{len(blocks['①'])} 个落蓝块（匹配+≥18万）**，{len(blocks['②'])} 个落绿块（匹配+<18万），{len(blocks['③'])} 个落黄块（不匹配+≥18万），{len(blocks['④'])} 个落粉块（不匹配+<18万），{len(blocks['未知'])} 个薪资未知。\n")

    # 色块标题
    block_meta = {
        "①": ("🔵 蓝色 = 第一优先级（匹配 + 薪资≥18万）", "优先投"),
        "②": ("🟢 绿色 = 第二优先级（匹配 + 薪资<18万）", "薪资不达标，慎投"),
        "③": ("🟡 黄色 = 第三优先级（不匹配 + 薪资≥18万）", "跨赛道高薪"),
        "④": ("🟣 粉色 = 第四优先级（不匹配 + 薪资<18万）", "基本放弃"),
        "未知": ("⚪ 薪资未知", "待核"),
    }
    for b in ["①", "②", "③", "④", "未知"]:
        lst = blocks[b]
        title, hint = block_meta[b]
        lines.append(f"## {title}（{len(lst)} 岗）\n")
        lines.append(f"*{hint}*\n")
        if not lst:
            lines.append("（空）\n")
            continue
        # 表头
        if b == "①":
            lines.append("| 公司 | 岗位 | 类型 | 薪资 | 匹配理由（命中的业务） |")
            lines.append("|---|---|---|---|---|")
            for j in lst:
                hits = "、".join(j["_hits"]) if j["_hits"] else "—"
                lines.append(f"| {j['_company']} | {j['title']} | {j['_type']} | {j['_sal_label']} | {hits} |")
        elif b == "②":
            lines.append("| 公司 | 岗位 | 类型 | 薪资 | 匹配理由 |")
            lines.append("|---|---|---|---|---|")
            for j in lst:
                hits = "、".join(j["_hits"]) if j["_hits"] else "—"
                lines.append(f"| {j['_company']} | {j['title']} | {j['_type']} | {j['_sal_label']} | {hits} |")
        else:
            # ③④未知：精简，只列公司岗位
            lines.append("| 公司 | 岗位 | 类型 | 薪资 |")
            lines.append("|---|---|---|---|")
            for j in lst:
                lines.append(f"| {j['_company']} | {j['title']} | {j['_type']} | {j['_sal_label']} |")
        lines.append("")

    # 抓取失败清单
    lines.append("## 抓取失败 / JD 不可得清单\n")
    lines.append("**以下公司无法用脚本抓官网 JD**（投递链接是公众号/前程无忧/智联/国聘/问卷星/自建系统，非飞书/北森/Moka 三大系统），或集团门户未按子公司拆分：\n")
    lines.append("① 集团门户未拆分子公司：曹操出行（geely/78436 实为吉利控股集团门户，\"曹操\"标签命中 0 岗，判 JD 不可得）。\n")
    lines.append("② 其余约 76 家投递链接为公众号文章或反爬平台（前程无忧/智联/国聘/问卷星/自建/海康/长虹等），JD 不可得，需人工贴 JD 才能匹配。\n")

    # 薪资未知清单
    unknown_sal = [j for j in target if j["_sal_label"] in ("未知", "临界(待核)")]
    if unknown_sal:
        lines.append("## 薪资未知 / 临界清单（需 OfferShow/牛客 单查）\n")
        lines.append("| 公司 | 岗位 | 说明 |")
        lines.append("|---|---|---|")
        for j in unknown_sal:
            info = COMPANY_SALARY.get(j["_company"], {})
            lines.append(f"| {j['_company']} | {j['title']} | {info.get('note','未知')} |")
        lines.append("")

    out = "\n".join(lines)
    with open("outputs/job-match/2026-09-15.md", "w", encoding="utf-8") as f:
        f.write(out)
    print(f"报告已生成，目标岗 {len(target)} 个：①{len(blocks['①'])} ②{len(blocks['②'])} ③{len(blocks['③'])} ④{len(blocks['④'])} 未知{len(blocks['未知'])}")

if __name__ == "__main__":
    main()
