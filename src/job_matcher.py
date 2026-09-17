#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
job_matcher.py —— 校招岗位 JD 抓取 + 三维规则打分 + 4色块归类（零 LLM token）

抓取：直调飞书/北森/Moka 公开接口（复用 Hiring-Radar 的接口方案）
打分：纯规则词典匹配（技术 + 经验 + 薪资），不调 LLM
输出：JSON 中间结果 + Markdown 4色块报告

用法: python job_matcher.py
"""
import os, sys, json, re, ssl, base64, html as _html, urllib.request
from datetime import datetime

# ============ 通用 HTTP ============
CTX = ssl.create_default_context()
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# =========================================================
# 1. 简历词典（从 求职者-校招简历.md 提取）
# =========================================================

# 经验维度：业务类别 → 关键词（含同义词，解决"同业务不同用词"）
BUSINESS = [
    {"name": "直播运营", "kw": ["直播", "直播间", "主播", "带货", "直播运营"],
     "evidence": "去哪儿直播运营（视频号/抖音直播间 GMV 400W+/900W+）"},
    {"name": "用户增长/获客", "kw": ["用户增长", "获客", "拉新", "增长", "冷启动", "引流", "涨粉", "流量承接"],
     "evidence": "美团用户增长（KOS 矩阵涨粉 4K+、引流成交 GMV 150W+）"},
    {"name": "商家/商户运营", "kw": ["商家", "商户", "招商", "选品", "店铺", "商家服务"],
     "evidence": "美团商家运营（搭建商家服务体系、孵化 10+ 月 GMV 80W 商家）"},
    {"name": "内容运营/创作", "kw": ["内容运营", "内容创作", "图文", "短视频", "视频", "选题", "素材", "爆款", "小红书", "笔记", "编导", "剪辑", "文案"],
     "evidence": "美团小红书内容 + 去哪儿矩阵视频（播放 100W+）"},
    {"name": "用户运营", "kw": ["用户运营", "用户分层", "用户标签", "用户画像", "社群", "会员", "留存", "促活", "私域", "企微"],
     "evidence": "高途用户运营（企微标签体系、用户分层）"},
    {"name": "活动策划", "kw": ["活动策划", "活动运营", "节点营销", "大促", "campaign"],
     "evidence": "高途活动策划（5 城 5 场 200 人活动、曝光 400W）"},
    {"name": "策略运营", "kw": ["策略运营", "运营策略", "规则迭代", "精细化运营"],
     "evidence": "滴滴策略运营（规则迭代、补贴管控）"},
    {"name": "电商运营", "kw": ["电商", "gmv", "roi", "转化率", "上架", "类目"],
     "evidence": "内容电商 GMV/ROI 提升（ROI 0.56→0.94 等）"},
]

# 技术维度：JD 点名的硬技能
SKILLS = [
    {"name": "SQL", "kw": ["sql"]},
    {"name": "Python", "kw": ["python"]},
    {"name": "Excel", "kw": ["excel"]},
    {"name": "数据分析", "kw": ["数据分析", "数据复盘", "数据看板", "数据监控", "数据报表"]},
    {"name": "直播", "kw": ["直播", "主播"]},
    {"name": "内容创作工具", "kw": ["剪映", "ps", "可画", "剪辑", "短视频"]},
    {"name": "流量投放", "kw": ["投流", "投放", "千川", "千帆", "信息流", "加热"]},
    {"name": "AI工具", "kw": ["ai", "aigc", "大模型", "agent", "自动化"]},
]

# 目标岗位方向词（用户定的 6 词 + 常见扩展）
MKT_KW = ["市场", "营销", "商务", "销售", "品牌", "渠道", "增长", "商业", "外贸", "客户", "媒介", "公关", "广告", "主播", "策划", "文案", "编辑"]

# 技术岗强信号词：岗位名含这些且非经理/运营/管培生，多为技术岗（产品工程师/销售工程师/IC市场等）
TECH_STRONG = ["工程师", "算法", "开发", "硬件", "芯片", "半导体", "嵌入式", "验证", "封装", "工艺", "机械", "电气", "电子", "测试", "运维", "架构", "layout", "ic", "设计"]

def classify_type(title):
    """岗位类型：技术岗排除 → 运营 > 市场销售 > 产品 > 其他"""
    t = title or ""
    tl = t.lower()
    # 技术岗排除：产品工程师/销售工程师/IC市场 是技术岗，不是目标岗
    # 保留真目标岗：产品经理/产品运营/运营/管培生/培训生/主播
    keep = ("经理" in t) or ("运营" in t) or ("管培生" in t) or ("培训生" in t) or ("主播" in t)
    if (not keep) and any(k in tl for k in TECH_STRONG):
        return "其他"
    if "科研" in t:
        return "其他"
    if "运营" in t:
        return "运营"
    if any(w in t for w in MKT_KW):
        return "市场销售"
    if "产品" in t:
        return "产品"
    return "其他"


def is_intern(j):
    """实习岗判断（求职者明确排除实习，只投校招正式全职）。
    只认 title 的"实习"二字 + 英文 intern（词边界，避免误杀 internal）。
    不用 type 字段 —— 多招聘系统的 type 字段含义混乱，不可作依据。
    不认 trainee —— Management Trainee（管培生）是校招正式岗，必须保留。"""
    title = j.get("title") or ""
    if "实习" in title:
        return True
    if re.search(r"\bintern\b", title, re.IGNORECASE):
        return True
    return False

# =========================================================
# 2. 抓取函数（直调公开接口）
# =========================================================

def fetch_feishu(host_path, company, pages=8):
    """飞书招聘：host 可为 'host/path'，自动解析 website-path"""
    host = host_path
    forced = ""
    if "/" in host_path:
        host, forced = host_path.split("/", 1)
        forced = forced.strip("/")
    def _call(path, limit, offset):
        body = {"keyword": "", "limit": limit, "offset": offset, "portal_type": 2,
                "job_category_id_list": [], "location_code_list": [], "subject_id_list": [],
                "recruitment_id_list": [], "job_function_id_list": []}
        headers = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
                   "Origin": f"https://{host}", "Referer": f"https://{host}/",
                   "Portal-Channel": "office", "Portal-Platform": "pc", "website-path": path}
        req = urllib.request.Request(f"https://{host}/api/v1/search/job/posts",
                                     data=json.dumps(body).encode(), headers=headers)
        return json.load(urllib.request.urlopen(req, timeout=25, context=CTX))
    # 探测 path
    def _probe_path():
        if forced:
            try:
                if _call(forced, 1, 0).get("code") == 0:
                    return forced
            except Exception:
                pass
        for cand in ("index", "experienced", "fte", "social", "recruitment", "campus"):
            try:
                if _call(cand, 1, 0).get("code") == 0:
                    return cand
            except Exception:
                continue
        return forced or "index"
    path = _probe_path()
    out = []
    for pg in range(pages):
        try:
            d = _call(path, 50, pg * 50)
        except Exception:
            break
        data = d.get("data") or {}
        posts = data.get("job_post_list") or []
        if not posts:
            break
        for j in posts:
            jid = str(j.get("id", ""))
            jd = "\n".join(x for x in [j.get("description", ""), j.get("requirement", "")] if x)
            cities = ", ".join(c.get("name", "") for c in (j.get("city_list") or []) if isinstance(c, dict))
            jf = j.get("job_function") or {}
            rt = j.get("recruit_type") or {}
            out.append({
                "title": j.get("title", ""), "company": company, "location": cities,
                "dept": jf.get("name", "") if isinstance(jf, dict) else "",
                "type": rt.get("name", "") if isinstance(rt, dict) else "",
                "jd": jd, "comp": "", "id": jid,
            })
        if len(posts) < 50:
            break
    return out

def fetch_beisen(slug, company, pages=8):
    """北森：Category=['2'] 校招，失败回退 ['1'] 社招"""
    def _call(cat, page, size):
        body = {"PageIndex": page, "PageSize": size, "LocId": [], "Category": cat,
                "KeyWords": "", "SpecialType": 0, "PortalId": "",
                "DisplayFields": ["Category", "Kind", "LocId", "PostDate", "Salary"]}
        headers = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "application/json",
                   "Origin": f"https://{slug}.zhiye.com", "Referer": f"https://{slug}.zhiye.com/campus/jobs"}
        req = urllib.request.Request(f"https://{slug}.zhiye.com/api/Jobad/GetJobAdPageList",
                                     data=json.dumps(body).encode(), headers=headers)
        return json.load(urllib.request.urlopen(req, timeout=25, context=CTX))
    out = []
    used_cat = "2"
    for cat in (["2"], ["1"]):
        out = []
        for pg in range(pages):
            try:
                d = _call(cat, pg, 50)
            except Exception:
                break
            posts = d.get("Data") or []
            if not posts:
                break
            for j in posts:
                jid = str(j.get("JobAdId", "") or j.get("Id", ""))
                title = j.get("JobAdName", "")
                out.append({
                    "title": title, "company": company,
                    "location": ", ".join(j.get("LocNames") or []),
                    "type": j.get("Category", ""),
                    "comp": j.get("Salary", "") or "",
                    "jd": j.get("Duty", "") or "",
                    "id": jid,
                })
            if len(posts) < 50:
                break
        if out:
            used_cat = cat[0]
            break
    for o in out:
        o["_cat"] = used_cat
    return out

def fetch_moka(org, site, company, pages=10):
    """Moka：AES 解密接口"""
    if not HAS_CRYPTO:
        return []
    IV = b"de7c21ed8d6f50fe"
    H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "Content-Type": "application/json",
         "Accept": "application/json", "Origin": "https://app.mokahr.com"}
    API = "https://app.mokahr.com/api/outer/ats-apply/website/jobs/v2"
    def _strip(s):
        if not s: return ""
        t = re.sub(r"(?i)<br\s*/?>", "\n", str(s))
        t = re.sub(r"(?i)</(p|li|div|h[1-6])>", "\n", t)
        t = re.sub(r"<[^>]+>", " ", t)
        t = _html.unescape(t)
        t = re.sub(r"[ \t]+", " ", t)
        return re.sub(r"\n\s*\n\s*\n+", "\n\n", t).strip()
    def _decrypt(d):
        if isinstance(d, dict) and "data" in d and "necromancer" in d:
            key = d["necromancer"].encode()
            if len(key) not in (16, 24, 32):
                raise RuntimeError("key len")
            pt = unpad(AES.new(key, AES.MODE_CBC, IV).decrypt(base64.b64decode(d["data"])), 16)
            return json.loads(pt.decode("utf-8"))
        return d
    def _call(limit, offset):
        body = {"orgId": org, "siteId": int(site), "locale": "zh-CN", "limit": limit, "offset": offset}
        req = urllib.request.Request(API, data=json.dumps(body).encode(), headers=H)
        return _decrypt(json.load(urllib.request.urlopen(req, timeout=25, context=CTX)))
    out = []
    for pg in range(pages):
        try:
            resp = _call(50, pg * 50)
        except Exception:
            break
        data = resp.get("data") if isinstance(resp, dict) else resp
        jobs = (data.get("jobs") or data.get("list") or []) if isinstance(data, dict) else (data or [])
        if not jobs:
            break
        for j in jobs:
            jid = str(j.get("id", ""))
            locs = ", ".join(x.get("cityName", "") for x in (j.get("locations") or []) if isinstance(x, dict) and x.get("cityName"))
            dep = j.get("department") or {}
            mn, mx = j.get("minSalary"), j.get("maxSalary")
            comp = f"{mn}-{mx}" if (mn or mx) else ""
            out.append({
                "title": j.get("title", ""), "company": company, "location": locs,
                "dept": dep.get("name", "") if isinstance(dep, dict) else "",
                "type": j.get("commitment", ""),
                "comp": comp, "jd": _strip(j.get("jobDescription", "")), "id": jid,
            })
        if len(jobs) < 50:
            break
    return out

# =========================================================
# 3. 打分函数
# =========================================================

def parse_salary(comp):
    """解析薪资字符串 → 年总包（元）。无法解析返回 None。
    支持：8K-10K 元/月（×15）、12W-16W 元/年、9-13（K/月）、9000-13000（元/月）、面议/日薪→None"""
    if not comp:
        return None
    comp = comp.strip()
    if "面议" in comp or "元/天" in comp or "元/日" in comp or "兼职" in comp:
        return None
    # 年包 "12W-16W 元/年" / "12-16万"
    if "年" in comp or "W" in comp or "w" in comp or "万" in comp:
        m = re.findall(r"(\d+(?:\.\d+)?)", comp)
        if m:
            vals = [float(x) for x in m[:2]]
            return sum(vals) / len(vals) * 10000
    # 月薪 "8K-10K 元/月"
    if "K" in comp or "k" in comp:
        m = re.findall(r"(\d+(?:\.\d+)?)\s*[kK]", comp)
        if m:
            vals = [float(x) * 1000 for x in m]
            return sum(vals) / len(vals) * 15
    # 纯数字区间 "9-13"（K/月）或 "9000-13000"（元/月）
    if "-" in comp or "月" in comp:
        m = re.findall(r"(\d+(?:\.\d+)?)", comp)
        if len(m) >= 2:
            vals = [float(x) for x in m[:2]]
            if vals[0] < 100:
                return sum(vals) / len(vals) * 1000 * 15  # K/月
            return sum(vals) / len(vals) * 15  # 元/月
    return None

def score_experience(jd):
    jdl = (jd or "").lower()
    hits = [b for b in BUSINESS if any(k in jdl for k in b["kw"])]
    if len(hits) >= 2:
        return "直接", hits
    if len(hits) == 1:
        return "可迁移", hits
    return "无", []

# 四类"做不了"的硬背景/技能信号（粗标红用，召回优先，LLM 精判兜底）
UNDOABLE = {
    "硬件技术": ["芯片", "半导体", "集成电路", "fpga", "pcb", "嵌入式", "单片机", "固件", "机械设计", "电气工程", "slam", "激光雷达", "毫米波", "射频", "模拟电路", "数字电路", "封装", "光刻", "晶圆"],
    "供应链": ["供应链", "物流", "仓储", "物料", "进销存", "货代", "报关", "库存管理", "供应商管理", "配送", "海运", "空运", "陆运", "订舱", "单证", "舱位", "多式联运", "集运", "船公司", "集装箱", "通关", "海关", "货运"],
    "医学": ["医学", "临床", "药学", "药理", "护理", "医疗器械", "医美", "生物医药", "疾病", "诊疗", "病理", "制剂"],
}

def is_undoable(title, jd):
    """粗标红：判断岗位是否"做不了"的四类（硬件技术/供应链/医学/产品工程师）。
    召回优先——宁可多标，LLM 精判会纠正。返回 (bool, 类别串)。"""
    t = (title or "")
    jdl = (jd or "").lower()
    reasons = []
    # 岗位名级：工程师（非经理/运营/管培/培训）→ 产品工程师类
    if ("工程师" in t) and not any(k in t for k in ("经理", "运营", "管培", "培训")):
        reasons.append("产品工程师")
    # 供应链词（岗位名级）
    for w in ["供应链", "采购", "物流", "仓储", "货代", "报关", "物料", "海运", "空运", "陆运", "集运", "货运", "集装箱", "多式联运", "订舱", "单证", "外运"]:
        if w in t:
            reasons.append("供应链")
            break
    # 医学词（岗位名级）
    for w in ["医药", "医学", "临床", "药学", "护理", "医疗器械", "医美"]:
        if w in t:
            reasons.append("医学")
            break
    # 硬件技术产品（岗位名级）：具身智能/机器视觉/处理器核/IP研发 等，说产品实为硬件/技术
    for w in ["具身智能", "机器视觉", "处理器", "ip研发"]:
        if w in t.lower():
            reasons.append("硬件技术产品")
            break
    # 产品应用岗（岗位名级）：实为售前/售后技术支持工程师
    if "产品应用" in t:
        reasons.append("产品工程师")
    # 产品研究 + 工科专业（JD级）：实为产品研发技术岗
    if "产品研究" in t and any(k in jdl for k in ("机电", "电气", "机械", "能源", "技术协议")):
        reasons.append("硬件技术产品")
    # JD 级：命中某组 ≥2 词 → 疑似该类
    for cat, kws in UNDOABLE.items():
        if sum(1 for k in kws if k in jdl) >= 2:
            reasons.append(cat)
    reasons = list(dict.fromkeys(reasons))
    return bool(reasons), "、".join(reasons)

def score_skill(jd):
    jdl = (jd or "").lower()
    return [s["name"] for s in SKILLS if any(k in jdl for k in s["kw"])]

def classify_priority(exp, annual):
    matched = exp in ("直接", "可迁移")
    if annual is None:
        return ("②/④待定" if matched else "④/②待定"), matched
    ge18 = annual >= 180000
    if matched and ge18: return "①", matched
    if matched and not ge18: return "②", matched
    if not matched and ge18: return "③", matched
    return "④", matched

# =========================================================
# 4. 公司清单（9月14日投递表，99 行里可抓官网 JD 的 23 家）
# =========================================================

COMPANIES = [
    # 飞书系（host）
    {"name": "伊芙丽集团", "sys": "feishu", "host": "wx5a691zs0.jobs.feishu.cn"},
    {"name": "乐享元游", "sys": "feishu", "host": "ocn860ugrb9t.jobs.feishu.cn"},
    # 北森系（slug）
    {"name": "瑞沃德", "sys": "beisen", "slug": "rwdls"},
    {"name": "国芯微电子", "sys": "beisen", "slug": "nationalchip"},
    {"name": "AIVA汽车", "sys": "beisen", "slug": "aiva"},
    {"name": "泰康之家", "sys": "beisen", "slug": "jobtaikang"},
    {"name": "陕西德信", "sys": "beisen", "slug": "sxqc"},
    {"name": "泛联新安", "sys": "beisen", "slug": "flyaitalent"},
    {"name": "凯金新能源", "sys": "beisen", "slug": "kaijin2"},
    {"name": "赛夫集团", "sys": "beisen", "slug": "seif1"},
    {"name": "鼎桥技术", "sys": "beisen", "slug": "td-tech"},
    {"name": "九江金鹭", "sys": "beisen", "slug": "cxtc-jt2"},
    {"name": "先临三维", "sys": "beisen", "slug": "shining3d"},
    {"name": "亚特电器", "sys": "beisen", "slug": "yat-pro"},
    # Moka 系（orgId/siteId）
    {"name": "古茗茶饮", "sys": "moka", "org": "guming", "site": "39377"},
    {"name": "云和恩墨", "sys": "moka", "org": "enmotech", "site": "47098"},
    {"name": "三福", "sys": "moka", "org": "sanfu", "site": "46833"},
    {"name": "Shopee", "sys": "moka", "org": "shopee", "site": "2962"},
    {"name": "鸿芯微纳", "sys": "moka", "org": "giga-da", "site": "26752"},
    {"name": "天虹数科", "sys": "moka", "org": "tianhongshuke", "site": "24998"},
    {"name": "新安股份", "sys": "moka", "org": "wynca", "site": "102535"},
    {"name": "BIGO", "sys": "moka", "org": "bigo", "site": "1018"},
    {"name": "曹操出行", "sys": "moka", "org": "geely", "site": "78436"},
]

# 集团门户范围过滤：投递表里的子公司，其链接指向母公司集团门户（Moka org/北森 slug 是集团级），
# 抓出来的是整个集团的岗位。必须按子公司关键词收窄到 title+dept，命中才保留；命中 0 → 该公司 JD 不可得。
# 泰康之家 (jobtaikang) 实为泰康保险集团门户（人寿/泰康之家/泰康口腔/科技运营混在一起），
#   按"之家"收窄到泰康之家养老社区专属岗（title 前缀「之家-」）。
# 曹操出行 (geely/78436) 实为吉利控股集团门户（钱江摩托同源），"曹操"标签命中 0 → 自然判 JD 不可得。
SCOPE_FILTER = {
    "泰康之家": ["之家"],
    "曹操出行": ["曹操"],
}

def main():
    all_jobs = []
    for c in COMPANIES:
        try:
            if c["sys"] == "feishu":
                jobs = fetch_feishu(c["host"], c["name"])
            elif c["sys"] == "beisen":
                jobs = fetch_beisen(c["slug"], c["name"])
            else:
                jobs = fetch_moka(c["org"], c["site"], c["name"])
            # 集团门户范围过滤（子公司链接指向集团门户时收窄）
            scope_kws = SCOPE_FILTER.get(c["name"])
            if scope_kws:
                before = len(jobs)
                jobs = [j for j in jobs if any(k in (j["title"] + (j.get("dept") or "")) for k in scope_kws)]
                if len(jobs) != before:
                    print(f"  [SCOPE] {c['name']} 收窄 {before} -> {len(jobs)} 岗", file=sys.stderr)
            # 实习岗过滤（求职者明确排除实习，只投校招正式全职）
            n_before = len(jobs)
            jobs = [j for j in jobs if not is_intern(j)]
            if len(jobs) != n_before:
                print(f"  [实习过滤] {c['name']} 剔除 {n_before - len(jobs)} 个实习岗", file=sys.stderr)
            for j in jobs:
                j["_src_sys"] = c["sys"]
                j["_company"] = c["name"]
                # 打分
                j["_type"] = classify_type(j["title"])
                exp, hits = score_experience(j["jd"])
                j["_exp"] = exp
                j["_hits"] = [h["name"] for h in hits]
                j["_evidence"] = "；".join(h["evidence"] for h in hits)
                j["_skills"] = score_skill(j["jd"])
                annual = parse_salary(j.get("comp", ""))
                j["_annual"] = annual
                prio, matched = classify_priority(exp, annual)
                j["_prio"] = prio
                j["_matched"] = matched
                j["_undoable"], j["_undoable_reason"] = is_undoable(j["title"], j["jd"])
            all_jobs.extend(jobs)
            print(f"[OK] {c['name']} ({c['sys']}) → {len(jobs)} 岗", file=sys.stderr)
        except Exception as e:
            print(f"[FAIL] {c['name']} ({c['sys']}) → {type(e).__name__}: {e}", file=sys.stderr)

    # 保存中间 JSON
    with open("job_match_raw.json", "w", encoding="utf-8") as f:
        json.dump(all_jobs, f, ensure_ascii=False, indent=1)
    print(f"\n总岗位数: {len(all_jobs)}", file=sys.stderr)
    return all_jobs

if __name__ == "__main__":
    main()
