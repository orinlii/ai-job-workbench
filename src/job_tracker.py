#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简历投递自动化跟踪系统
功能：
1. 自动从投递链接提取公司、岗位、地点信息并填写到飞书Base
2. 自动从163邮箱识别笔试/面试邮件并同步到飞书日历
"""

import json
import os
import re
import time
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as date_parser

# 注册IMAP ID命令（163邮箱要求，RFC 2971）
imaplib.Commands['ID'] = ('AUTH', 'SELECTED')

# 飞书Base字段映射
FIELD_MAPPING = {
    "company": "公司名称",
    "position": "岗位名称",
    "status": "最新状态",
    "location": "地点",
    "apply_date": "投递时间",
    "written_test": "笔试",
    "interview": "一面",
    "industry": "公司行业",
    "link": "投递链接",
    "resume_version": "投递的简历版本",
    "note": "备注"
}


@dataclass
class JobInfo:
    """招聘岗位信息"""
    company: str = ""
    position: str = ""
    location: str = ""
    url: str = ""


@dataclass
class RecruitmentEmail:
    """招聘邮件信息"""
    company: str = ""
    email_type: str = ""  # written_test, interview, assessment, offer, rejection
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    location: str = ""
    subject: str = ""
    sender: str = ""
    message_id: str = ""
    body: str = ""  # 邮件正文（含主题）


class Config:
    """配置管理"""
    def __init__(self, config_path: str = "config.json"):
        with open(config_path, "r", encoding="utf-8") as f:
            self.data = json.load(f)

    def get(self, *keys, default=None):
        value = self.data
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
        return value if value is not None else default


class JobScraper:
    """招聘链接抓取器"""

    def __init__(self, config: Config):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.get("scraper", "user_agent",
                                      default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        })

    def scrape(self, url: str) -> JobInfo:
        """从链接抓取岗位信息"""
        job = JobInfo(url=url)
        if not url:
            return job

        try:
            domain = urlparse(url).netloc.lower()

            # 根据域名选择不同的解析策略
            if "zhipin.com" in domain:
                job = self._scrape_zhipin(url)
            elif "liepin.com" in domain:
                job = self._scrape_liepin(url)
            elif "51job.com" in domain or "51job" in domain:
                job = self._scrape_51job(url)
            elif "zhaopin.com" in domain:
                job = self._scrape_zhaopin(url)
            elif "nowcoder.com" in domain:
                job = self._scrape_nowcoder(url)
            else:
                job = self._scrape_generic(url)

        except Exception as e:
            print(f"[抓取失败] {url}: {e}")

        return job

    def _fetch_page(self, url: str) -> Optional[str]:
        """获取页面内容"""
        try:
            delay = self.config.get("scraper", "request_delay", default=2)
            timeout = self.config.get("scraper", "timeout", default=30)
            time.sleep(delay)
            response = self.session.get(url, timeout=timeout, allow_redirects=True)
            response.encoding = response.apparent_encoding
            return response.text
        except Exception as e:
            print(f"[页面获取失败] {url}: {e}")
            return None

    def _scrape_zhipin(self, url: str) -> JobInfo:
        """BOSS直聘"""
        job = JobInfo(url=url)
        html = self._fetch_page(url)
        if not html:
            return job

        soup = BeautifulSoup(html, "html.parser")

        # 岗位名称
        position_elem = soup.find("h1", class_="name") or soup.find("span", class_="job-name")
        if position_elem:
            job.position = position_elem.get_text(strip=True)

        # 公司名称
        company_elem = soup.find("a", class_="company") or soup.find("h3", class_="name")
        if company_elem:
            job.company = company_elem.get_text(strip=True)

        # 地点
        location_elem = soup.find("span", class_="job-area") or soup.find("p", class_="location-address")
        if location_elem:
            job.location = location_elem.get_text(strip=True)

        return job

    def _scrape_liepin(self, url: str) -> JobInfo:
        """猎聘"""
        job = JobInfo(url=url)
        html = self._fetch_page(url)
        if not html:
            return job

        soup = BeautifulSoup(html, "html.parser")

        # 岗位名称
        position_elem = soup.find("h1", class_="name") or soup.find("div", class_="title-info")
        if position_elem:
            job.position = position_elem.get_text(strip=True)

        # 公司名称
        company_elem = soup.find("a", class_="company-name") or soup.find("div", class_="company")
        if company_elem:
            job.company = company_elem.get_text(strip=True)

        # 地点
        location_elem = soup.find("span", class_="work-city") or soup.find("p", class_="basic-infor")
        if location_elem:
            text = location_elem.get_text(strip=True)
            # 提取城市信息
            city_match = re.search(r"([\u4e00-\u9fa5]{2,}(?:市|区|县)?)", text)
            if city_match:
                job.location = city_match.group(1)

        return job

    def _scrape_51job(self, url: str) -> JobInfo:
        """前程无忧"""
        job = JobInfo(url=url)
        html = self._fetch_page(url)
        if not html:
            return job

        soup = BeautifulSoup(html, "html.parser")

        # 岗位名称
        position_elem = soup.find("h1") or soup.find("div", class_="cn")
        if position_elem:
            job.position = position_elem.get_text(strip=True)

        # 公司名称
        company_elem = soup.find("a", class_="com_name") or soup.find("p", class_="cname")
        if company_elem:
            job.company = company_elem.get_text(strip=True)

        # 地点
        location_elem = soup.find("span", class_="lname") or soup.find("p", class_="msg")
        if location_elem:
            text = location_elem.get_text(strip=True)
            city_match = re.search(r"([\u4e00-\u9fa5]{2,}(?:市|区|县)?)", text)
            if city_match:
                job.location = city_match.group(1)

        return job

    def _scrape_zhaopin(self, url: str) -> JobInfo:
        """智联招聘"""
        job = JobInfo(url=url)
        html = self._fetch_page(url)
        if not html:
            return job

        soup = BeautifulSoup(html, "html.parser")

        # 岗位名称
        position_elem = soup.find("h3", class_="summary-plane__title") or soup.find("div", class_="job-name")
        if position_elem:
            job.position = position_elem.get_text(strip=True)

        # 公司名称
        company_elem = soup.find("a", class_="company__title") or soup.find("span", class_="company-name")
        if company_elem:
            job.company = company_elem.get_text(strip=True)

        # 地点
        location_elem = soup.find("span", class_="summary-plane__info") or soup.find("ul", class_="summary-plane__info")
        if location_elem:
            text = location_elem.get_text(strip=True)
            city_match = re.search(r"([\u4e00-\u9fa5]{2,}(?:市|区|县)?)", text)
            if city_match:
                job.location = city_match.group(1)

        return job

    def _scrape_nowcoder(self, url: str) -> JobInfo:
        """牛客网"""
        job = JobInfo(url=url)
        html = self._fetch_page(url)
        if not html:
            return job

        soup = BeautifulSoup(html, "html.parser")

        # 岗位名称
        position_elem = soup.find("h1") or soup.find("div", class_="job-title")
        if position_elem:
            job.position = position_elem.get_text(strip=True)

        # 公司名称
        company_elem = soup.find("a", class_="company-name") or soup.find("div", class_="company")
        if company_elem:
            job.company = company_elem.get_text(strip=True)

        # 地点
        location_elem = soup.find("span", class_="job-location") or soup.find("div", class_="location")
        if location_elem:
            job.location = location_elem.get_text(strip=True)

        return job

    def _scrape_generic(self, url: str) -> JobInfo:
        """通用网站抓取（公司官网等）"""
        job = JobInfo(url=url)
        html = self._fetch_page(url)
        if not html:
            return job

        soup = BeautifulSoup(html, "html.parser")

        # 从title提取信息
        title = soup.title.string if soup.title else ""
        if title:
            # 尝试从标题中提取公司和岗位
            # 常见格式："岗位名称 - 公司名称 - 招聘"
            parts = re.split(r"[-_|·]", title)
            if len(parts) >= 2:
                job.position = parts[0].strip()
                job.company = parts[1].strip()

        # 尝试从meta标签提取
        company_meta = soup.find("meta", attrs={"name": "company"}) or \
                       soup.find("meta", property="og:site_name")
        if company_meta and not job.company:
            job.company = company_meta.get("content", "").strip()

        # 尝试查找页面中的地点信息
        location_patterns = [
            r"工作地点[：:]\s*([\u4e00-\u9fa5a-zA-Z]+)",
            r"工作城市[：:]\s*([\u4e00-\u9fa5a-zA-Z]+)",
            r"地点[：:]\s*([\u4e00-\u9fa5a-zA-Z]+)",
            r"base[：:]\s*([\u4e00-\u9fa5a-zA-Z]+)"
        ]
        text = soup.get_text()
        for pattern in location_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                job.location = match.group(1).strip()
                break

        return job


class EmailReader:
    """163邮箱读取器"""

    def __init__(self, config: Config):
        self.config = config
        self.imap = None

    def connect(self):
        """连接IMAP服务器"""
        if not self.config.get("email", "enabled", default=True):
            print("[邮箱] 未启用邮箱功能")
            return False

        server = self.config.get("email", "imap_server", default="imap.163.com")
        port = self.config.get("email", "imap_port", default=993)
        username = self.config.get("email", "username", default="")
        password = self.config.get("email", "password", default="")

        if not username or not password or username == "your_email@163.com":
            print("[邮箱] 请先在config.json中配置邮箱账号和IMAP授权码")
            return False

        try:
            self.imap = imaplib.IMAP4_SSL(server, port)
            self.imap.login(username, password)

            # 发送IMAP ID命令（163邮箱安全要求）
            try:
                self.imap._simple_command(
                    'ID',
                    '("name" "JobTracker" "version" "1.0" "vendor" "Python-IMAP")'
                )
            except Exception as e:
                print(f"[邮箱] ID命令发送警告: {e}")

            print(f"[邮箱] 成功连接到 {username}")
            return True
        except Exception as e:
            print(f"[邮箱] 连接失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        if self.imap:
            try:
                self.imap.logout()
            except:
                pass
            self.imap = None

    def _decode_str(self, s: str) -> str:
        """解码邮件标题/发件人"""
        if not s:
            return ""
        decoded_parts = decode_header(s)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="ignore"))
            else:
                result.append(part)
        return "".join(result)

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析邮件日期"""
        try:
            return email.utils.parsedate_to_datetime(date_str)
        except:
            try:
                return date_parser.parse(date_str)
            except:
                return None

    # 公司名称标准化映射表（提取到的名称 → 标准名称）
    COMPANY_NAME_MAPPING = {
        "online.tcl": "TCL",
        "tcl": "TCL",
        "italent": "联合利华",
        "babycare2027届": "Babycare",
        "babycare": "Babycare",
        "联合利华2027管理培训生的岗": "联合利华",
        "图拉斯2027届": "图拉斯",
        "快手校园": "快手",
        "携程集团": "携程",
        "特步集团": "特步",
        "美团": "美团",
        "多益": "多益网络",
        "网易游戏互娱": "网易互娱",
        "网易": "网易",
        "京东": "京东",
        "安踏集团2027年全球": "安踏",
        "安踏": "安踏",
        "基恩士": "基恩士",
        "好未来招聘": "好未来",
        "好未来": "好未来",
        "小米集团": "小米",
        "小米": "小米",
        "字节跳动": "字节跳动",
        "阿里巴巴校园": "阿里巴巴",
        "阿里巴巴": "阿里巴巴",
        "腾讯": "腾讯",
        "百度": "百度",
        "OPPO": "OPPO",
        "vivo": "vivo",
        "华为": "华为",
        "深圳全棉时代": "全棉时代",
        "全棉时代": "全棉时代",
        "智元创新": "智元创新",
        "深圳元戎启行": "元戎启行",
        "元戎启行": "元戎启行",
        "作业帮教育": "作业帮",
        "作业帮": "作业帮",
        "哔哩哔哩": "哔哩哔哩",
        "bilibili": "哔哩哔哩",
        "B站": "哔哩哔哩",
        "阿迪达斯": "阿迪达斯",
        "雅诗兰黛": "雅诗兰黛",
        "海信": "海信",
        "厦门中达集团有限公司": "中达集团",
        "中达集团": "中达集团",
        "途牛旅游网": "途牛",
        "途牛": "途牛",
        "上海莉莉丝科技股份有限公司": "莉莉丝游戏",
        "莉莉丝游戏": "莉莉丝游戏",
        "长飞": "长飞",
        "雪川农业集团": "雪川农业",
        "元气森林": "元气森林",
        "斐乐": "斐乐",
        "微派": "微派",
        "隔壁刘奶奶": "隔壁刘奶奶",
        "科大讯飞": "科大讯飞",
        "影石": "影石",
        "新东方": "新东方",
        "minmax": "MiniMax",
        "货拉拉": "货拉拉",
        "凡岛": "凡岛",
        "顺丰": "顺丰",
        "得物": "得物",
        "雷鸟科技": "雷鸟科技",
        "李森智能": "李森智能",
        "万木生源": "万木生源",
        "遨森电商": "遨森电商",
        "道旅科技": "道旅科技",
        "百饮事业": "百饮事业",
        "老乡鸡": "老乡鸡",
        "转转": "转转",
        "半亩花田": "半亩花田",
        "虎牙": "虎牙",
        "万葭灯火": "字节跳动",
    }

    def _normalize_company_name(self, company: str) -> str:
        """标准化公司名称"""
        if not company:
            return ""
        company_lower = company.lower().strip()
        # 先精确匹配
        if company_lower in self.COMPANY_NAME_MAPPING:
            return self.COMPANY_NAME_MAPPING[company_lower]
        # 再模糊匹配（包含关系）
        for key, value in self.COMPANY_NAME_MAPPING.items():
            if key in company_lower or company_lower in key:
                return value
        return company

    def _extract_company(self, text: str, sender: str = "", subject: str = "") -> str:
        """从邮件内容中提取公司名称（基于实际数据探查优化版）"""
        # 公司名黑名单：明显不是公司名的词
        company_blacklist = {
            "本公司", "本邮件", "总部", "全国性", "同学", "少年", "未来", "可期",
            "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "为什么",
            "如果", "因为", "所以", "但是", "而且", "或者", "以及", "还是",
            "可以", "需要", "应该", "能够", "可能", "大概", "也许", "请问",
            "面试通知邮箱", "招聘小秘书", "services", "campus", "Assessment",
            "recruiting", "noreply", "no-reply", "support", "hr", "HR",
            "邮箱验证", "验证码", "One-time", "verification",
        }

        # 城市前缀列表
        city_prefixes = [
            "广州", "北京", "上海", "深圳", "杭州", "成都", "武汉", "南京", "苏州",
            "西安", "重庆", "天津", "长沙", "郑州", "青岛", "大连", "宁波", "厦门",
            "福州", "济南", "合肥", "昆明", "南昌", "石家庄", "太原", "沈阳", "长春",
            "哈尔滨", "贵阳", "南宁", "兰州", "乌鲁木齐", "呼和浩特", "银川", "西宁",
            "海口", "拉萨", "厦门",
        ]

        def clean_company(company: str) -> str:
            """清理公司名：去掉城市前缀、招聘后缀、年份等"""
            if not company:
                return ""
            company = company.strip()
            # 去掉引号
            company = company.strip('"\'')
            # 去掉城市前缀
            for city in city_prefixes:
                if company.startswith(city) and len(company) > len(city) + 2:
                    company = company[len(city):]
                    break
            # 去掉招聘相关后缀
            suffixes = ["招聘", "校招", "校园招聘", "人才", "官方", "集团招聘", "（中国）", "(中国)", "有限公司", "股份有限公司", "科技有限公司", "网络科技有限公司"]
            for suffix in suffixes:
                if company.endswith(suffix) and len(company) > len(suffix) + 1:
                    company = company[:-len(suffix)]
                    break
            # 去掉年份前缀（如"2027届"、"2027"）
            company = re.sub(r'^202\d[届年]?', '', company).strip()
            # 检查黑名单
            if company in company_blacklist or len(company) < 2:
                return ""
            return company

        # ========== 1. 优先从主题提取 ==========
        if subject:
            # 模式0：主题开头就是"XX公司/集团 + AI面试/测评/笔试/面试邀请"（最明确）
            # 如：基恩士（中国）有限公司AI面试邀请、请尽快完成基恩士（中国）有限公司发起的AI面试
            match = re.search(r'([\u4e00-\u9fa5a-zA-Z0-9（）()]{2,20}(?:公司|集团|有限公司))(?:发起的)?(?:AI面试|AI测评|测评|笔试|面试)', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式1：【公司名...】格式（不排除包含招聘/校招的，而是提取公司名部分）
            # 【阿里巴巴校园招聘】、【阿迪达斯2027管培生招聘】、【快手校园招聘】、【携程集团】
            match = re.search(r"【([^】]{2,25})】", subject)
            if match:
                bracket_content = match.group(1).strip()
                # 从【】内容中提取公司名：去掉招聘/校招/校园/年份/管培生等词
                company = re.sub(r'(校园招聘|校招|招聘|校园|202\d届|202\d年|管培生|全球|邀请|通知|笔试|面试|测评)', '', bracket_content).strip()
                company = clean_company(company)
                if company:
                    return company

            # 模式2：感谢投递/感谢应聘XX公司（51job等平台常用）
            # 感谢投递联合利华2027管理培训生、感谢您应聘雅诗兰黛集团2027管培生项目
            match = re.search(r'感谢(?:您|你)?(?:投递|应聘)([\u4e00-\u9fa5a-zA-Z0-9]{2,15})', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式3：求职者，感谢你投递XX公司的XX职位（mokahr等平台常用）
            match = re.search(r'感谢你投递([\u4e00-\u9fa5a-zA-Z0-9]{2,15})公司', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式4：主题开头是公司名+年份+校招/招聘
            # 图拉斯2027届校园招聘、特步集团 2027届全球校园招聘
            match = re.match(r'^([\u4e00-\u9fa5a-zA-Z0-9]{2,15})(?:集团)?\s*(?:202\d届|202\d年)?(?:校园招聘|校招|全球校园招聘|招聘)', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式5：XX公司/有限公司/科技/网络/集团 + 简历投递/招聘/结果/通知
            # 广州凡岛网络科技有限公司简历投递结果通知
            match = re.search(r'([\u4e00-\u9fa5]{2,20}(?:公司|有限公司|科技|网络|集团|股份))(?:简历投递|招聘|结果|通知|校园)', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式6：来自XX的消息通知/招聘
            match = re.search(r'来自([\u4e00-\u9fa5a-zA-Z0-9.]{2,15})(?:的|招聘|校园)', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式7：XX邀请您/你参加...
            match = re.search(r'([\u4e00-\u9fa5a-zA-Z0-9]{2,15})(?:邀请你|邀请您)', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # 模式8：XX集团/公司 + 其他（兜底）
            match = re.search(r'([\u4e00-\u9fa5]{2,10}(?:集团|公司))', subject)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

        # ========== 2. 从发件人名称提取 ==========
        if sender:
            # 提取发件人名称（去掉邮箱部分）
            sender_name = re.sub(r'<[^>]+>', '', sender).strip()
            sender_name = sender_name.strip('"\'')

            if sender_name and len(sender_name) <= 30:
                # 检查是否明显不是公司名
                if not any(bad in sender_name for bad in ["通知邮箱", "小秘书", "services", "campus@", "noreply", "no-reply"]):
                    # 去掉招聘相关后缀
                    company = clean_company(sender_name)
                    if company and len(company) <= 15:
                        return company

            # 从邮箱域名提取（排除第三方招聘平台）
            email_match = re.search(r"<([^>]+)>", sender)
            if email_match:
                email_addr = email_match.group(1)
                domain = email_addr.split("@")[-1].lower()
                # 排除第三方招聘平台域名
                third_party = ["nowcoder", "ibeisen", "mokahr", "hrtps", "service",
                               "shmail", "usermail", "mail", "hr", "campus", "e-mail",
                               "51job", "joinus", "hire", "quickmail", "online", "italent"]
                is_third_party = any(tp in domain for tp in third_party)
                if not is_third_party:
                    for suffix in [".com", ".cn", ".net", ".org", ".com.cn"]:
                        domain = domain.replace(suffix, "")
                    if domain and len(domain) > 1 and domain not in company_blacklist:
                        # 域名转公司名（如 bytedance -> 字节跳动，alibaba -> 阿里巴巴）
                        domain_company_map = {
                            "bytedance": "字节跳动",
                            "alibaba": "阿里巴巴",
                            "tencent": "腾讯",
                            "baidu": "百度",
                            "jd": "京东",
                            "meituan": "美团",
                            "xiaomi": "小米",
                            "huawei": "华为",
                            "bilibili": "哔哩哔哩",
                            "kuaishou": "快手",
                            "trip": "携程",
                            "xtep": "特步",
                            "tcl": "TCL",
                            "hisense": "海信",
                            "unilever": "联合利华",
                            "p&g": "宝洁",
                            "pg": "宝洁",
                        }
                        if domain in domain_company_map:
                            return domain_company_map[domain]
                        return domain.capitalize()

        # ========== 3. 从正文提取（兜底） ==========
        if text:
            # 感谢您投递XX公司的XX职位
            match = re.search(r'感谢(?:您|你)?(?:投递|应聘)([\u4e00-\u9fa5a-zA-Z0-9]{2,15})', text)
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

            # XX公司（兜底）
            match = re.search(r'([\u4e00-\u9fa5]{2,10}(?:集团|有限公司|公司))', text[:500])
            if match:
                company = clean_company(match.group(1))
                if company:
                    return company

        return ""

    def _extract_datetime(self, text: str, email_date: Optional[datetime] = None) -> Tuple[Optional[datetime], Optional[datetime]]:
        """从邮件内容中提取开始和结束时间"""
        start_time = None
        end_time = None

        # 预处理：去除时区前缀，统一格式
        text = re.sub(r'\(北京时间[^)]*\)', '', text)
        text = re.sub(r'UTC[+-]\d{2}:?\d{2}', '', text)

        # 模式0：相对时间（优先级最高，如"7个工作日内"、"48小时内"、"3天内"）
        if email_date:
            relative_patterns = [
                # N天内/之内/以内/后 → 结束时间 = 发送时间 + N*24小时（天和内之间允许空格）
                (r'(\d+)\s*天\s*(?:内|之内|以内|后)', "day"),
                # N小时内/之内/以内/后 → 结束时间 = 发送时间 + N小时（小时和内之间允许空格）
                (r'(\d+)\s*小时\s*(?:内|之内|以内|后)', "hour"),
                # N个工作日内/之内/以内 → 计算N个工作日后的精确时间
                (r'(\d+)\s*个?\s*工作日\s*(?:内|之内|以内|后)', "workday"),
                # 英文相对时间：expire in 7 days / within 7 days / valid for 7 days
                (r'(?:expire|expires|valid for|within|in)\s+(\d+)\s*(?:days?|day)', "day_en"),
                # 英文相对时间：expire in 48 hours / within 48 hours
                (r'(?:expire|expires|valid for|within|in)\s+(\d+)\s*(?:hours?|hour)', "hour_en"),
                # 英文相对时间：in 2 weeks / within 2 weeks
                (r'(?:expire|expires|valid for|within|in)\s+(\d+)\s*(?:weeks?|week)', "week_en"),
            ]

            for pattern, rtype in relative_patterns:
                match = re.search(pattern, text)
                if match:
                    num = int(match.group(1))
                    if rtype in ["day", "day_en"]:
                        end_time = email_date + timedelta(hours=num * 24)
                    elif rtype in ["hour", "hour_en"]:
                        end_time = email_date + timedelta(hours=num)
                    elif rtype in ["week", "week_en"]:
                        end_time = email_date + timedelta(days=num * 7)
                    else:  # workday
                        end_date = email_date.date()
                        workdays_added = 0
                        while workdays_added < num:
                            end_date += timedelta(days=1)
                            if end_date.weekday() < 5:
                                workdays_added += 1
                        end_time = email_date.replace(year=end_date.year,
                                                       month=end_date.month,
                                                       day=end_date.day)
                    start_time = email_date
                    return start_time, end_time

        # 模式1：带时间范围的格式（优先级最高）
        # 支持跨日期和同一天两种格式
        range_patterns = [
            # 生效/失效格式：于 2026年09月08日 周二 16:22 生效，于 2026年09月11日 周五 16:22 失效
            (r'于\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]?\s*(?:周[一二三四五六日天])?\s*(\d{1,2})[:：](\d{2})\s*生效.*?于\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]?\s*(?:周[一二三四五六日天])?\s*(\d{1,2})[:：](\d{2})\s*失效', "cross_date_cn"),
            # 跨日期：从 2026年09月03日 09:21 到 2026年09月06日 09:21
            (r'从\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]?\s*(\d{1,2})[:：](\d{2})\s*(?:到|至|~|-)\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]?\s*(\d{1,2})[:：](\d{2})', "cross_date_cn"),
            # 跨日期：2026-09-03 09:21 到 2026-09-06 09:21
            (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})\s*(?:到|至|~|-)\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})', "cross_date_en"),
            # 同一天：2026-09-01 19:00:00 -- 21:00:00
            (r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?\s*(?:--|-|~|至|到)\s*(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?', "same_day_en"),
            # 同一天：2026年9月1日 19:00-21:00
            (r'(\d{4})年(\d{1,2})月(\d{1,2})[日号]\s*(\d{1,2})[:：](\d{2})\s*(?:--|-|~|至|到)\s*(\d{1,2})[:：](\d{2})', "same_day_cn"),
        ]

        for pattern, rtype in range_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                try:
                    if rtype in ["cross_date_cn", "cross_date_en"]:
                        # 跨日期：10个分组（开始年月日时分 + 结束年月日时分）
                        start_time = datetime(int(groups[0]), int(groups[1]), int(groups[2]),
                                              int(groups[3]), int(groups[4]))
                        end_time = datetime(int(groups[5]), int(groups[6]), int(groups[7]),
                                            int(groups[8]), int(groups[9]))
                    else:
                        # 同一天：7个分组（开始年月日时分 + 结束时分）
                        start_time = datetime(int(groups[0]), int(groups[1]), int(groups[2]),
                                              int(groups[3]), int(groups[4]))
                        end_time = datetime(int(groups[0]), int(groups[1]), int(groups[2]),
                                            int(groups[5]), int(groups[6]))
                    return start_time, end_time
                except:
                    pass

        # 模式2：单个时间点（带关键词前缀）
        single_patterns = [
            # 考试时间：2026-09-01 19:00:00（支持可选的秒）
            (r'(?:考试时间|笔试时间|面试时间|测评时间|开始时间|时间)[：:]\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?',
             "start"),
            # 考试时间：2026年9月1日 19:00（支持可选的秒）
            (r'(?:考试时间|笔试时间|面试时间|测评时间|开始时间|时间)[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]?\s*(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?',
             "start"),
            # 截止时间：2026-09-01 23:59（支持可选的秒）
            (r'(?:截止时间|结束时间|有效期至|最晚)[：:]\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?',
             "end"),
            # 截止时间：2026年9月1日 23:59（支持可选的秒）
            (r'(?:截止时间|结束时间|有效期至|最晚)[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]?\s*(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?',
             "end"),
            # 请在2026-09-01 23:59前完成（支持可选的秒）
            (r'(?:请在|于)\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?\s*(?:前|之前|以内)',
             "end"),
        ]

        for pattern, ptype in single_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                try:
                    dt = datetime(int(groups[0]), int(groups[1]), int(groups[2]),
                                  int(groups[3]), int(groups[4]))
                    if ptype == "start":
                        start_time = dt
                        end_time = dt + timedelta(hours=1)
                    else:
                        end_time = dt
                        # 对于截止时间，开始时间设为截止前1小时
                        start_time = dt - timedelta(hours=1)
                    return start_time, end_time
                except:
                    pass

        # 模式2.5：特殊格式——括号里的日期时间（如"(09-09 11:17)"）
        # 常见于"AI面试即将在2天小时(09-09 11:17)后截止"这种格式
        if email_date:
            special_patterns = [
                # (09-09 11:17) 或 (09/09 11:17)
                r'\((\d{1,2})[-/](\d{1,2})\s+(\d{1,2})[:：](\d{2})\)',
            ]
            for pattern in special_patterns:
                match = re.search(pattern, text)
                if match:
                    groups = match.groups()
                    try:
                        month = int(groups[0])
                        day = int(groups[1])
                        hour = int(groups[2])
                        minute = int(groups[3])
                        # 根据邮件日期推断年份：如果月份小于邮件月份，说明是下一年
                        year = email_date.year
                        if month < email_date.month:
                            year = email_date.year + 1
                        elif month == email_date.month and day < email_date.day:
                            year = email_date.year + 1
                        end_time = datetime(year, month, day, hour, minute)
                        # 开始时间设为邮件发送时间
                        start_time = email_date
                        return start_time, end_time
                    except:
                        pass

        # 模式3：只有日期没有时间
        date_only_patterns = [
            # 2026-09-01
            r'(?:考试日期|笔试日期|面试日期|测评日期|日期)[：:]\s*(\d{4})[-/](\d{1,2})[-/](\d{1,2})',
            # 2026年9月1日
            r'(?:考试日期|笔试日期|面试日期|测评日期|日期)[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})[日号]',
        ]

        for pattern in date_only_patterns:
            match = re.search(pattern, text)
            if match:
                groups = match.groups()
                try:
                    start_time = datetime(int(groups[0]), int(groups[1]), int(groups[2]), 9, 0)
                    end_time = start_time + timedelta(hours=2)
                    return start_time, end_time
                except:
                    pass

        # 兜底：如果所有模式都没匹配到，但有邮件发送时间，用发送时间作为开始时间
        if start_time is None and email_date:
            start_time = email_date
            end_time = email_date + timedelta(hours=2)  # 默认持续2小时

        return start_time, end_time

    def _classify_email(self, subject: str, body: str) -> str:
        """
        分类邮件类型（基于实际数据探查优化版）
        
        优先级（最明确的优先识别）：
        1. 强拒信（明确的拒信表述，排除条件句）
        2. offer（录用通知，精确匹配）
        3. 测评（中英文支持）
        4. 笔试
        5. 面试
        6. 投递确认
        7. 调研
        8. 其他
        """
        text = f"{subject} {body}"
        text_lower = text.lower()

        # ========== 0. 强拒信识别（最优先：明确的拒信表述，必须在主题明确信号之前） ==========
        # 注意：很多拒信邮件主题是"感谢投递XX公司的职位"，正文里才说"很遗憾，不匹配"
        # 所以强拒信检查必须在主题明确信号检查之前，否则会被漏检
        strong_rejection_patterns = [
            r"未通过",
            r"不合适",
            r"不适合",
            r"不匹配",
            r"未能进入",
            r"未能通过",
            r"没有通过",
            r"很遗憾地通知",
            r"很抱歉地通知",
            r"遗憾地通知",
            r"抱歉地通知",
            r"后续有合适的机会",
            r"经过综合评估.{0,30}(未|不|遗憾|抱歉)",
            r"经过慎重考虑.{0,30}(未|不|遗憾|抱歉)",
            r"经过慎重评估.{0,30}(未|不|遗憾|抱歉)",
            r"未进入下一轮",
            r"匹配度存在偏差",
            r"不予录用",
            r"暂时不适合",
            r"暂时不符合",
            r"很遗憾.{0,10}经过",
            r"很抱歉.{0,10}经过",
        ]
        for pattern in strong_rejection_patterns:
            if re.search(pattern, text):
                # 排除条件句：如果出现在"如果不...就..."这种条件句里，不是拒信
                if re.search(r"(如果|若|如未|未按时|避免导致|否则|一经发现|违规行为).{0,30}" + pattern, text):
                    continue
                return "rejection"

        # ========== 1. 主题明确信号优先检查（避免被正文里的关键词覆盖） ==========
        # 注意：强拒信优先级比主题明确信号高，已经在上面检查过了
        if subject:
            subject_lower = subject.lower()
            # 投递确认（主题明确）
            if re.search(r'(感谢投递|感谢您投递|感谢你投递|投递成功|简历投递成功|已收到你的简历|我们已收到|简历已收到|申请成功|投递提醒|投递通知)', subject):
                return "confirmation"
            # 测评（主题明确）
            if re.search(r'(测评邀请|测评通知|在线测评|人才测评|性格测评|能力测评|综合素质测评|assessment invitation|online assessment)', subject_lower):
                return "assessment"
            # 笔试（主题明确）
            if re.search(r'(笔试邀请|笔试通知|在线笔试|线上笔试|统一笔试|written test)', subject_lower):
                return "written_test"
            # 面试（主题明确）
            if re.search(r'(面试邀请|面试通知|AI面试|视频面试|线上面试|群面|一面|二面|三面|interview invitation)', subject_lower):
                return "interview"

        # ========== 2. offer识别（精确匹配，排除注意事项里的提及） ==========
        offer_patterns = [
            r"录用通知",
            r"offer\s*letter",
            r"入职通知",
            r"入职邀请",
            r"正式录用",
            r"恭喜你.{0,10}获得.{0,10}offer",
            r"恭喜.{0,10}录用",
            r"我们很高兴地通知你",
            r"你已通过所有面试",
            r"发放录用",
        ]
        for pattern in offer_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                # 排除注意事项里的提及（如"如已发放offer"、"撤销offer"、"取消offer"）
                if re.search(r"(如已|撤销|取消|违反|违规).{0,20}" + pattern, text, re.IGNORECASE):
                    continue
                return "offer"

        # ========== 3. 测评识别（中英文支持） ==========
        assessment_keywords = [
            "性格测评", "在线测评", "人才测评", "综合素质测评",
            "心理测评", "能力测评", "测评邀请", "测评通知",
            "完成测评", "测评链接", "在线人才测评", "能力测评",
            "online assessment", "assessment invitation", "complete assessment",
            "测评未完成", "测评提醒",
        ]
        for keyword in assessment_keywords:
            if keyword.lower() in text_lower:
                # 排除"AI面试"伪装成测评的情况
                if "ai面试" in text_lower or "ai 面试" in text_lower:
                    if re.search(r"(面试内容|面试形式|面试时长|面试题|视频面试)", text):
                        return "interview"
                return "assessment"

        # 通用"测评"关键词（需要排除AI面试）
        if "测评" in text:
            if "ai测评" in text_lower or "ai 测评" in text_lower:
                if re.search(r"(面试内容|面试形式|面试时长|面试题|视频面试)", text):
                    return "interview"
            # 排除"面试测评"这种组合（如果明确是面试内容）
            if "面试测评" in text and re.search(r"(面试内容|面试形式|面试时长)", text):
                return "interview"
            return "assessment"

        # ========== 4. 笔试识别 ==========
        written_test_keywords = [
            "在线笔试", "笔试邀请", "笔试通知", "线上笔试",
            "统一笔试", "编程测试", "笔试时间", "参加笔试",
            "written test", "online test",
        ]
        for keyword in written_test_keywords:
            if keyword.lower() in text_lower:
                return "written_test"

        if "笔试" in text:
            return "written_test"

        # ========== 5. 面试识别 ==========
        interview_keywords = [
            "ai面试", "ai 面试", "视频面试", "线上面试", "群面",
            "一面", "二面", "三面", "hr面", "面试邀请", "面试通知",
            "面试时间", "参加面试", "面试链接", "在线面试", "专业面试",
            "面试确认", "interview",
        ]
        for keyword in interview_keywords:
            if keyword.lower() in text_lower:
                # 排除"面试体验调研"等调研邮件
                if re.search(r"(面试体验.{0,10}(调研|反馈)|评价.{0,10}面试官|面试.{0,10}问卷调查)", text):
                    return "survey"
                return "interview"

        if "面试" in text:
            # 排除调研邮件
            if re.search(r"(面试体验.{0,10}(调研|反馈)|评价.{0,10}面试官|面试.{0,10}问卷调查)", text):
                return "survey"
            return "interview"

        # ========== 6. 投递成功/简历确认识别 ==========
        confirmation_patterns = [
            r"简历投递成功",
            r"投递成功",
            r"已收到您的简历",
            r"我们已收到",
            r"确认职位信息",
            r"感谢您投递",
            r"感谢你投递",
            r"感谢投递",
            r"感谢您应聘",
            r"期待与你.{0,10}合拍",
            r"简历已收到",
            r"简历已经被发送",
            r"申请.{0,10}成功",
            r"投递提醒",
            r"投递通知",
            r"简历已顺利抵达",
            r"已收到您对",
            r"我们会尽快查看",
            r"我们会尽快处理",
            r"我们会尽快阅读",
            r"实时同步至",
        ]
        for pattern in confirmation_patterns:
            if re.search(pattern, text):
                # 如果后面跟着明确的拒信信号，还是拒信
                if not re.search(r"(未通过|不合适|不适合|不匹配|遗憾地通知|抱歉地通知|不再继续|未进入下一轮|匹配度存在偏差|流程已结束|未能满足|无法继续)", text):
                    return "confirmation"

        # ========== 7. 调研/反馈识别 ==========
        survey_patterns = [
            r"面试体验.{0,10}调研",
            r"面试体验.{0,10}反馈",
            r"评价.{0,10}面试官",
            r"面试.{0,10}问卷调查",
            r"体验调研",
            r"满意度调查",
            r"邀请您参与.{0,10}调研",
        ]
        for pattern in survey_patterns:
            if re.search(pattern, text):
                return "survey"

        # ========== 8. 其他（验证码、邮箱验证、招聘广告等） ==========
        return "other"

    def read_recent_emails(self) -> List[RecruitmentEmail]:
        """读取最近的招聘相关邮件"""
        if not self.imap:
            return []

        results = []
        check_days = self.config.get("email", "check_days", default=7)
        folders = self.config.get("email", "folders", default=["INBOX"])

        since_date = (datetime.now() - timedelta(days=check_days)).strftime("%d-%b-%Y")

        for folder in folders:
            try:
                self.imap.select(folder)
                _, message_ids = self.imap.search(None, f'(SINCE "{since_date}")')

                for msg_id in message_ids[0].split():
                    try:
                        _, msg_data = self.imap.fetch(msg_id, "(RFC822)")
                        msg = email.message_from_bytes(msg_data[0][1])

                        subject = self._decode_str(msg["Subject"])
                        sender = self._decode_str(msg["From"])
                        date = self._parse_date(msg["Date"])
                        message_id = msg["Message-ID"] or msg_id.decode()

                        # 获取正文（优先text/plain，其次从HTML提取）
                        body = ""
                        html_body = ""
                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                if content_type == "text/plain" and not body:
                                    try:
                                        body = part.get_payload(decode=True).decode(
                                            part.get_content_charset() or "utf-8", errors="ignore")
                                    except:
                                        pass
                                elif content_type == "text/html":
                                    try:
                                        html_body = part.get_payload(decode=True).decode(
                                            part.get_content_charset() or "utf-8", errors="ignore")
                                    except:
                                        pass
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode(
                                    msg.get_content_charset() or "utf-8", errors="ignore")
                            except:
                                pass

                        # 如果纯文本为空或太短，从HTML提取文本
                        if len(body.strip()) < 50 and html_body:
                            # 去除HTML标签，保留文本
                            body = re.sub(r'<style[^>]*>.*?</style>', '', html_body, flags=re.DOTALL)
                            body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL)
                            body = re.sub(r'<[^>]+>', ' ', body)
                            body = re.sub(r'&nbsp;', ' ', body)
                            body = re.sub(r'&amp;', '&', body)
                            body = re.sub(r'\s+', ' ', body).strip()

                        # 分类邮件
                        email_type = self._classify_email(subject, body)

                        if email_type == "other":
                            continue

                        # 提取信息
                        full_text = f"{subject} {body}"
                        company = self._extract_company(full_text, sender, subject)
                        company = self._normalize_company_name(company)  # 标准化公司名称
                        start_time, end_time = self._extract_datetime(full_text, date)

                        # 提取地点
                        location = ""
                        location_match = re.search(r"(?:地点|地址|位置)[：:]\s*([^\n\r]+)", full_text)
                        if location_match:
                            location = location_match.group(1).strip()[:50]

                        recruitment_email = RecruitmentEmail(
                            company=company,
                            email_type=email_type,
                            start_time=start_time,
                            end_time=end_time,
                            location=location,
                            subject=subject,
                            sender=sender,
                            message_id=message_id,
                            body=full_text
                        )
                        results.append(recruitment_email)
                        print(f"[邮箱] 识别到{email_type}邮件: {company} - {subject[:50]}")

                    except Exception as e:
                        print(f"[邮箱] 解析邮件失败: {e}")
                        continue

            except Exception as e:
                print(f"[邮箱] 读取文件夹{folder}失败: {e}")

        return results


class CalendarManager:
    """飞书日历管理器"""

    def __init__(self, config: Config):
        self.config = config
        # 使用新版本lark-cli（支持用户登录）
        self.lark_cli_path = r"C:\Users\Lenovo\AppData\Roaming\npm\lark-cli.cmd"
        # 本地文件记录已创建过日程的邮件ID（用于去重，不匹配旧格式日程）
        self.processed_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_emails.txt")
        self.processed_ids = self._load_processed_ids()

    def _load_processed_ids(self) -> set:
        """加载已处理的邮件ID"""
        ids = set()
        try:
            if os.path.exists(self.processed_file):
                with open(self.processed_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            ids.add(line)
        except Exception as e:
            print(f"[日历] 加载已处理邮件ID失败: {e}")
        return ids

    def _save_processed_id(self, message_id: str):
        """保存已处理的邮件ID"""
        if not message_id:
            return
        try:
            with open(self.processed_file, "a", encoding="utf-8") as f:
                f.write(message_id + "\n")
            self.processed_ids.add(message_id)
        except Exception as e:
            print(f"[日历] 保存已处理邮件ID失败: {e}")

    def create_event(self, recruitment_email: RecruitmentEmail) -> bool:
        """在飞书日历创建日程"""
        if not self.config.get("calendar", "enabled", default=True):
            return False

        if not recruitment_email.start_time:
            print(f"[日历] 无法创建日程：缺少开始时间 - {recruitment_email.subject}")
            return False

        # 只处理笔试和面试（测评归类为笔试）
        valid_types = ["written_test", "interview", "assessment"]
        if recruitment_email.email_type not in valid_types:
            print(f"[日历] 跳过非笔试/面试类型: {recruitment_email.email_type} - {recruitment_email.subject}")
            return False

        import subprocess

        # 邮件类型映射（测评归类为笔试）
        type_names = {
            "written_test": "笔试",
            "interview": "面试",
            "assessment": "笔试",
        }
        type_name = type_names.get(recruitment_email.email_type, "招聘")
        company = recruitment_email.company or "未知公司"

        # 去重检查：用邮件ID判断是否已经创建过日程（不匹配旧格式日程）
        msg_id = recruitment_email.message_id
        if msg_id and msg_id in self.processed_ids:
            print(f"[日历] 该邮件已创建过日程，跳过: [{type_name}] {company}")
            return False

        # 构建标题：[笔试] 美团 - 09-01 19:00~21:00（跨天时显示结束日期）
        start_str = recruitment_email.start_time.strftime("%m-%d %H:%M")
        if recruitment_email.end_time:
            # 判断是否跨天
            if recruitment_email.start_time.date() == recruitment_email.end_time.date():
                end_str = recruitment_email.end_time.strftime("%H:%M")
            else:
                end_str = recruitment_email.end_time.strftime("%m-%d %H:%M")
        else:
            end_time = recruitment_email.start_time + timedelta(
                minutes=self.config.get("calendar", "default_duration_minutes", default=60))
            end_str = end_time.strftime("%H:%M")

        title = f"[{type_name}] {company} - {start_str}~{end_str}"

        # 构建描述
        description = f"**邮件主题**: {recruitment_email.subject}\n"
        description += f"**发件人**: {recruitment_email.sender}\n"
        description += f"**类型**: {type_name}\n"
        if recruitment_email.location:
            description += f"**地点/链接**: {recruitment_email.location}\n"
        description += f"\n（由简历投递跟踪系统自动创建）"

        # 时间格式
        start_iso = recruitment_email.start_time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        if recruitment_email.end_time:
            end_iso = recruitment_email.end_time.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        else:
            end_time = recruitment_email.start_time + timedelta(
                minutes=self.config.get("calendar", "default_duration_minutes", default=60))
            end_iso = end_time.strftime("%Y-%m-%dT%H:%M:%S+08:00")

        try:
            # 把description写到临时文件，避免命令行特殊字符问题
            import tempfile
            import os
            tmp_fd, tmp_path = tempfile.mkstemp(suffix='.md', text=True)
            with os.fdopen(tmp_fd, 'w', encoding='utf-8', newline='\n') as f:
                f.write(description)

            # 使用lark-cli创建日程
            cmd = [
                self.lark_cli_path, "calendar", "+create",
                "--summary", title,
                "--description", f"@{tmp_path}",
                "--start", start_iso,
                "--end", end_iso,
                "--as", "user"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")

            # 删除临时文件
            try:
                os.unlink(tmp_path)
            except:
                pass

            if result.returncode == 0:
                print(f"[日历] 成功创建日程: {title}")
                # 保存邮件ID到本地文件，避免重复创建
                self._save_processed_id(recruitment_email.message_id)
                return True
            else:
                print(f"[日历] 创建日程失败: {result.stderr[:200]}")
                return False

        except Exception as e:
            print(f"[日历] 创建日程异常: {e}")
            return False


class BaseStatusUpdater:
    """飞书Base状态更新器（通过lark-cli操作）"""

    # 域名/路径到公司名称的映射表
    DOMAIN_COMPANY_MAPPING = {
        # 直接域名映射
        "careers.ctrip.com": "携程",
        "campus.kuaishou.cn": "快手",
        "talent.baidu.com": "百度",
        "careers.oppo.com": "OPPO",
        "join.qq.com": "腾讯",
        "campus.jd.com": "京东",
        "job.tal.com": "好未来",
        "job.fandow.com": "凡岛",
        "campus.dewu.com": "得物",
        "campus.sf-express.com": "顺丰",
        "hr-campus.vivo.com": "vivo",
        "jobs.bytedance.com": "字节跳动",
        "jobs.hisense.com": "海信",
        "zhaopin.xdf.cn": "新东方",
        "campus.game.163.com": "网易互娱",
        "campus.163.com": "网易",
        # zhiye.com子域名映射
        "snowvalleyfood.zhiye.com": "雪川农业",
        "keyence.zhiye.com": "基恩士",
        "purcotton1.zhiye.com": "全棉时代",
        "tuniu.zhiye.com": "途牛",
        "lisen.zhiye.com": "李森智能",
        "aosom1.zhiye.com": "遨森电商",
        "lxjchina1.zhiye.com": "老乡鸡",
        "dida.zhiye.com": "道旅科技",
        "zhuanzhuan.zhiye.com": "转转",
        "huawutang1.zhiye.com": "半亩花田",
        "yofc2.zhiye.com": "长飞",
        # mokahr.com路径映射（第三方平台）
        "huolalahr": "货拉拉",
        "antahr": "安踏",
        "xtep": "特步",
        "huya": "虎牙",
        "yeswood": "万木生源",
        # hotjob.cn路径映射（第三方平台）
        "SU64893571bef57c16d356b99e": "TCL",
        "SU66c83b1b1eb80543256c6529": "百饮事业",
        # 51job路径映射
        "elccampus": "雅诗兰黛",
    }

    def __init__(self, config: Config):
        self.config = config
        self.lark_cli_path = r"C:\Users\Lenovo\AppData\Roaming\npm\lark-cli.cmd"
        self.base_token = config.get("feishu", "base_token")
        self.table_id = config.get("feishu", "table_id")
        self._records = None

    def _extract_company_from_url(self, url: str) -> str:
        """从投递链接中提取公司名称"""
        if not url:
            return ""

        url_lower = url.lower()

        # 1. 直接域名匹配
        for domain, company in self.DOMAIN_COMPANY_MAPPING.items():
            if domain in url_lower:
                return company

        # 2. zhiye.com子域名提取（子域名通常是公司拼音/英文名）
        import re
        match = re.search(r"https?://([a-zA-Z0-9]+)\.zhiye\.com", url_lower)
        if match:
            subdomain = match.group(1)
            # 常见子域名到公司名的映射
            subdomain_mapping = {
                "snowvalleyfood": "雪川农业",
                "keyence": "基恩士",
                "purcotton1": "全棉时代",
                "tuniu": "途牛",
                "lisen": "李森智能",
                "aosom1": "遨森电商",
                "lxjchina1": "老乡鸡",
                "dida": "道旅科技",
                "zhuanzhuan": "转转",
                "huawutang1": "半亩花田",
                "yofc2": "长飞",
            }
            if subdomain in subdomain_mapping:
                return subdomain_mapping[subdomain]

        # 3. mokahr.com路径提取
        match = re.search(r"mokahr\.com/(?:campus-recruitment|campus_apply)/([a-zA-Z0-9]+)", url_lower)
        if match:
            company_key = match.group(1)
            mokahr_mapping = {
                "huolalahr": "货拉拉",
                "antahr": "安踏",
                "xtep": "特步",
                "huya": "虎牙",
                "yeswood": "万木生源",
            }
            if company_key in mokahr_mapping:
                return mokahr_mapping[company_key]

        return ""

    def _enrich_records_with_url_company(self):
        """对于公司名称为空的记录，从投递链接中提取公司名"""
        if not self._records:
            return

        enriched_count = 0
        for record in self._records:
            company = self._get_company_name(record)
            if not company:
                fields = record.get("fields", {})
                url = fields.get("投递链接", "")
                if isinstance(url, list):
                    url = url[0] if url else ""
                # 从markdown链接中提取URL
                import re
                url_match = re.search(r"\((https?://[^)]+)\)", str(url))
                if url_match:
                    url = url_match.group(1)
                elif not str(url).startswith("http"):
                    url = ""

                if url:
                    extracted_company = self._extract_company_from_url(url)
                    if extracted_company:
                        record["fields"]["公司名称"] = extracted_company
                        enriched_count += 1
                        print(f"[Base] 从链接提取公司名: {extracted_company} - {url[:60]}")

        if enriched_count > 0:
            print(f"[Base] 共从链接补充了 {enriched_count} 条记录的公司名")

    # 状态优先级（数值越大越靠后，优先级越高）
    # 正常流程：已投递 → 待笔试(含测评) → 待一面(含AI面) → 待二面 → 三面 → OC!
    # 终态：各种挂掉状态 + 投递后被拒 + 已放弃，不参与正常优先级比较
    STATUS_PRIORITY = {
        "已投递": 1,
        "待笔试": 2,   # 包含测评
        "待一面": 3,   # 包含AI面
        "待二面": 4,
        "三面": 5,     # 之前的待HR面
        "OC!": 6,
        # 终态用特殊值（负数），不参与正常优先级比较
        "投递后被拒": -1,  # 简历筛选不通过，直接被拒
        "AI面挂": -2,
        "笔试挂": -3,
        "一面挂": -4,
        "二面挂": -5,
        "三面挂": -6,
        "已放弃": -7,
    }

    # 终态定义：这些状态不被更低优先级覆盖
    TERMINAL_STATUSES = {"投递后被拒", "AI面挂", "笔试挂", "一面挂", "二面挂", "三面挂", "已放弃"}

    # 终态可被哪些状态覆盖
    TERMINAL_OVERRIDE = {
        "投递后被拒": {"OC!"},  # 被拒了只有offer能覆盖
        "AI面挂": {"OC!"},     # 挂掉了只有offer能覆盖
        "笔试挂": {"OC!"},
        "一面挂": {"OC!"},
        "二面挂": {"OC!"},
        "三面挂": {"OC!"},
        "已放弃": set(),        # 已放弃不被任何状态覆盖
    }

    def _get_all_records(self):
        """获取Base里的所有记录（支持分页）"""
        if self._records is not None:
            return self._records

        import subprocess
        import json

        all_records = []
        offset = 0
        page_size = 100

        while True:
            cmd = [
                self.lark_cli_path, "base", "+record-list",
                "--base-token", self.base_token,
                "--table-id", self.table_id,
                "--as", "user",
                "--offset", str(offset),
                "--limit", str(page_size),
                "--format", "json",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
            if result.returncode != 0:
                print(f"[Base] 获取记录失败 (offset={offset}): {result.stderr[:200]}")
                break

            try:
                data = json.loads(result.stdout)
                inner_data = data.get("data", {})

                # 记录是二维数组，字段名是一维数组，记录ID是一维数组
                records_array = inner_data.get("data", [])
                fields = inner_data.get("fields", [])
                record_ids = inner_data.get("record_id_list", [])
                has_more = inner_data.get("has_more", False)

                # 把数组格式转换成对象格式
                for i, record_array in enumerate(records_array):
                    record_obj = {
                        "record_id": record_ids[i] if i < len(record_ids) else "",
                        "fields": {}
                    }
                    for j, field_name in enumerate(fields):
                        if j < len(record_array):
                            record_obj["fields"][field_name] = record_array[j]
                    all_records.append(record_obj)

                print(f"[Base] 已获取 {len(all_records)} 条记录 (offset={offset}, has_more={has_more})")

                if not has_more or len(records_array) == 0:
                    break
                offset += page_size

            except Exception as e:
                print(f"[Base] 解析记录失败 (offset={offset}): {e}")
                break

        self._records = all_records
        print(f"[Base] 共获取 {len(all_records)} 条记录")

        # 对于公司名称为空的记录，从投递链接中提取公司名
        self._enrich_records_with_url_company()

        return all_records

    def _get_company_name(self, record):
        """从记录中提取公司名称"""
        fields = record.get("fields", {})
        company = fields.get("公司名称", "")
        if isinstance(company, list):
            company = company[0] if company else ""
        return company or ""

    def _get_current_status(self, record):
        """从记录中提取当前状态"""
        fields = record.get("fields", {})
        status = fields.get("最新状态", "")
        if isinstance(status, list):
            status = status[0] if status else ""
        return status or ""

    def _find_record_by_company(self, company: str):
        """通过公司名称模糊匹配Base里的记录"""
        if not company:
            return None

        records = self._get_all_records()
        company_lower = company.lower().strip()

        # 精确匹配优先
        for record in records:
            record_company = self._get_company_name(record)
            if record_company and record_company.lower().strip() == company_lower:
                return record

        # 模糊匹配（公司名包含在记录名中，或记录名包含在公司名中）
        for record in records:
            record_company = self._get_company_name(record)
            if record_company:
                record_company_lower = record_company.lower().strip()
                if company_lower in record_company_lower or record_company_lower in company_lower:
                    return record

        return None

    def _determine_status(self, email: RecruitmentEmail) -> str:
        """根据邮件类型和内容确定Base状态"""
        email_type = email.email_type
        subject = email.subject or ""

        # 投递确认（感谢投递）→ 已投递
        if email_type == "confirmation":
            return "已投递"

        # 拒信 → 根据邮件内容判断是哪个环节挂的
        if email_type == "rejection":
            text = f"{subject} {email.body or ''}"
            # 投递后被拒：简历筛选不通过，没有进入任何笔试/面试环节
            # 特征：提到简历、筛选、不符合、不匹配，且没有提到具体环节
            has_resume_signal = any(kw in text for kw in ["简历", "筛选", "不符合", "不匹配", "经历", "背景"])
            has_stage_signal = any(kw in text for kw in ["笔试", "测评", "面试", "AI面", "一面", "二面", "三面", "HR面"])
            if has_resume_signal and not has_stage_signal:
                return "投递后被拒"
            # 其他环节挂掉
            if "AI面" in text or "AI面试" in text or "ai面" in text.lower():
                return "AI面挂"
            if "笔试" in text:
                return "笔试挂"
            if "二面" in text or "2面" in text or "第二轮" in text:
                return "二面挂"
            if "三面" in text or "3面" in text or "第三轮" in text or "HR面" in text or "hr面" in text.lower():
                return "三面挂"
            if "一面" in text or "1面" in text or "第一轮" in text or "面试" in text:
                return "一面挂"
            # 默认投递后被拒（没有提到具体环节，大概率是简历筛选不通过）
            return "投递后被拒"

        # offer
        if email_type == "offer":
            return "OC!"

        # 测评 → 待笔试（Base里没有单独的待测评状态）
        if email_type == "assessment":
            return "待笔试"

        # 笔试
        if email_type == "written_test":
            return "待笔试"

        # 面试（区分一面、二面、三面/HR面）
        if email_type == "interview":
            if "二面" in subject or "2面" in subject or "第二轮" in subject:
                return "待二面"
            if "三面" in subject or "3面" in subject or "第三轮" in subject:
                return "三面"
            if "HR面" in subject or "hr面" in subject:
                return "三面"
            # 默认一面（含AI面）
            return "待一面"

        return ""

    def update_status(self, email: RecruitmentEmail):
        """
        根据邮件更新Base里的状态
        返回: (success: bool, reason: str)
        """
        company = email.company
        if not company:
            return False, "缺少公司名称"

        # 确定状态
        status = self._determine_status(email)
        if not status:
            return False, f"无法确定状态（邮件类型:{email.email_type}）"

        # 查找记录
        record = self._find_record_by_company(company)
        if not record:
            return False, "Base里匹配不到公司"

        record_id = record.get("record_id") or record.get("_record_id")
        current_status = self._get_current_status(record)

        # 终态处理：各种挂掉状态、已放弃不被更低优先级覆盖
        if current_status in self.TERMINAL_STATUSES:
            allowed_overrides = self.TERMINAL_OVERRIDE.get(current_status, set())
            if status not in allowed_overrides:
                return False, f"当前已是终态'{current_status}'，不被'{status}'覆盖"

        # 如果新状态优先级更低，不覆盖
        current_priority = self.STATUS_PRIORITY.get(current_status, -100) if current_status else -100
        new_priority = self.STATUS_PRIORITY.get(status, 0)
        if new_priority < current_priority:
            return False, f"当前状态'{current_status}'优先级高于新状态'{status}'"

        # 如果状态相同，不更新
        if current_status == status:
            return False, f"状态已是'{status}'"

        # 更新状态 + 写入备注
        import subprocess
        import json
        from datetime import datetime

        # 构建备注内容
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        old_status = current_status if current_status else "（空）"
        note_content = f"[{current_time}] 状态从「{old_status}」→「{status}」\n触发邮件：{email.subject}\n"

        # 获取当前备注，追加新内容
        current_note = record.get("fields", {}).get("备注", "")
        if isinstance(current_note, list):
            current_note = current_note[0] if current_note else ""
        new_note = note_content + (current_note if current_note else "")

        update_json = {
            "update_records": {
                record_id: {
                    "最新状态": [status],
                    "备注": new_note
                }
            }
        }

        # 直接传递JSON字符串（subprocess参数列表方式，不经过shell解析）
        cmd = [
            self.lark_cli_path, "base", "+record-batch-update",
            "--base-token", self.base_token,
            "--table-id", self.table_id,
            "--json", json.dumps(update_json, ensure_ascii=False),
            "--as", "user",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode == 0:
            print(f"[Base] 成功更新状态：{company} - {old_status} → {status}")
            # 更新本地缓存
            if self._records:
                for r in self._records:
                    if (r.get("record_id") or r.get("_record_id")) == record_id:
                        r["fields"]["最新状态"] = [status]
                        r["fields"]["备注"] = new_note
                        break
            return True, f"{old_status} → {status}"
        else:
            error_msg = result.stderr[:300] if result.stderr else result.stdout[:300]
            return False, f"lark-cli执行失败: {error_msg}"

    def batch_update(self, emails: List[RecruitmentEmail]) -> Dict:
        """
        批量更新状态
        按公司分组，每组按邮件时间排序，用最新的邮件状态更新
        返回: {"updated": int, "skipped": int, "failed": int,
               "updated_list": [(company, reason)],
               "skipped_list": [(company, reason)],
               "failed_list": [(company, reason)]}
        """
        # 按公司分组
        company_emails = {}
        for email in emails:
            company = email.company
            if not company:
                continue
            if company not in company_emails:
                company_emails[company] = []
            company_emails[company].append(email)

        results = {
            "updated": 0, "skipped": 0, "failed": 0,
            "updated_list": [], "skipped_list": [], "failed_list": []
        }

        for company, company_email_list in company_emails.items():
            try:
                # 按邮件时间排序（最新的在后面），统一时区处理避免排序异常
                def sort_key(e):
                    if isinstance(e.start_time, datetime):
                        if e.start_time.tzinfo is not None:
                            return e.start_time.replace(tzinfo=None)
                        return e.start_time
                    return datetime.min
                company_email_list.sort(key=sort_key)

                # 用最新的邮件更新状态
                latest_email = company_email_list[-1]
                success, reason = self.update_status(latest_email)
                if success:
                    results["updated"] += 1
                    results["updated_list"].append((company, reason))
                else:
                    results["skipped"] += 1
                    results["skipped_list"].append((company, reason))
            except Exception as e:
                print(f"[Base] 更新{company}状态异常: {e}")
                import traceback
                traceback.print_exc()
                results["failed"] += 1
                results["failed_list"].append((company, str(e)[:200]))

        return results


class FeishuBaseOperator:
    """飞书Base操作器（通过Playwright浏览器自动化）"""

    def __init__(self, config: Config):
        self.config = config
        self.browser = None
        self.page = None
        self.context = None

    def _get_playwright(self):
        """延迟导入playwright"""
        from playwright.sync_api import sync_playwright
        return sync_playwright()

    def connect(self):
        """连接浏览器（使用持久化用户数据目录保存登录态）"""
        try:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()

            # 使用持久化上下文，保存登录态
            user_data_dir = "./browser_data"
            self.context = self._pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,  # 首次使用需要可视化登录
                viewport={"width": 1440, "height": 900}
            )

            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            print("[Base] 浏览器已启动，请在弹出的浏览器中登录飞书（首次使用）")
            return True

        except Exception as e:
            print(f"[Base] 浏览器启动失败: {e}")
            return False

    def navigate_to_base(self):
        """导航到Base页面"""
        if not self.page:
            return False

        url = self.config.get("feishu", "base_url")
        self.page.goto(url, wait_until="networkidle")
        time.sleep(3)

        # 检查是否需要登录
        if "登录" in self.page.title() or "login" in self.page.url.lower():
            print("[Base] 请在浏览器中完成飞书登录...")
            self.page.wait_for_url("**/base/**", timeout=120000)
            time.sleep(3)

        print("[Base] 已进入飞书Base页面")
        return True

    def read_records(self) -> List[Dict]:
        """读取所有记录（通过页面DOM解析）"""
        if not self.page:
            return []

        records = []
        try:
            # 等待表格加载
            self.page.wait_for_selector("[class*='row']", timeout=10000)

            # 获取所有行
            rows = self.page.query_selector_all("[class*='row']")
            print(f"[Base] 找到 {len(rows)} 行数据")

            for i, row in enumerate(rows):
                try:
                    cells = row.query_selector_all("[class*='cell']")
                    record = {"row_index": i}

                    for cell in cells:
                        # 获取单元格的字段名和值
                        # 飞书Base的单元格通常有data-field-id或类似属性
                        field_id = cell.get_attribute("data-field-id") or ""
                        text = cell.inner_text().strip()

                        if field_id:
                            record[field_id] = text

                    if len(record) > 1:
                        records.append(record)

                except Exception as e:
                    continue

        except Exception as e:
            print(f"[Base] 读取记录失败: {e}")

        return records

    def update_record(self, row_index: int, field_name: str, value: str) -> bool:
        """更新指定行的指定字段"""
        if not self.page:
            return False

        try:
            # 找到对应行和单元格并双击编辑
            # 这是一个简化的实现，实际需要根据飞书Base的DOM结构调整
            print(f"[Base] 更新第{row_index}行 {field_name} = {value}")

            # 滚动到目标行
            rows = self.page.query_selector_all("[class*='row']")
            if row_index < len(rows):
                target_row = rows[row_index]
                target_row.scroll_into_view_if_needed()
                time.sleep(0.5)

                # 找到目标列的单元格
                cells = target_row.query_selector_all("[class*='cell']")
                # 这里需要根据字段名找到对应的列索引
                # 简化处理：假设我们知道列索引
                for cell in cells:
                    cell_text = cell.inner_text().strip()
                    # 双击编辑
                    cell.dblclick()
                    time.sleep(0.5)
                    # 输入新值
                    self.page.keyboard.type(value)
                    self.page.keyboard.press("Enter")
                    time.sleep(0.5)
                    break

            return True

        except Exception as e:
            print(f"[Base] 更新记录失败: {e}")
            return False

    def close(self):
        """关闭浏览器"""
        if self.context:
            self.context.close()
        if hasattr(self, '_pw'):
            self._pw.stop()


class JobTracker:
    """主控制器"""

    def __init__(self, config_path: str = "config.json"):
        self.config = Config(config_path)
        self.scraper = JobScraper(self.config)
        self.email_reader = EmailReader(self.config)
        self.calendar_manager = CalendarManager(self.config)
        self.base_operator = FeishuBaseOperator(self.config)
        self.base_status_updater = BaseStatusUpdater(self.config)

    def run_job_link_scraping(self):
        """运行投递链接抓取任务"""
        print("\n" + "=" * 50)
        print("任务一：投递链接自动抓取与填写")
        print("=" * 50)

        if not self.base_operator.connect():
            print("[错误] 无法连接浏览器")
            return

        try:
            if not self.base_operator.navigate_to_base():
                print("[错误] 无法进入Base页面")
                return

            # 读取所有记录
            records = self.base_operator.read_records()
            print(f"[信息] 共读取到 {len(records)} 条记录")

            # 筛选需要处理的记录（有链接但公司或岗位为空）
            pending_records = []
            for record in records:
                link = record.get("投递链接", "") or record.get("link", "")
                company = record.get("公司名称", "") or record.get("company", "")
                position = record.get("岗位名称", "") or record.get("position", "")

                if link and (not company or not position):
                    pending_records.append(record)

            print(f"[信息] 需要处理的记录: {len(pending_records)} 条")

            # 逐条处理
            for record in pending_records:
                link = record.get("投递链接", "") or record.get("link", "")
                row_index = record.get("row_index", 0)

                print(f"\n[处理] 第{row_index}行: {link[:50]}...")

                # 抓取信息
                job_info = self.scraper.scrape(link)

                if job_info.company:
                    self.base_operator.update_record(row_index, "公司名称", job_info.company)
                if job_info.position:
                    self.base_operator.update_record(row_index, "岗位名称", job_info.position)
                if job_info.location:
                    self.base_operator.update_record(row_index, "地点", job_info.location)

                # 填写投递时间（当天）
                today = datetime.now().strftime("%Y/%m/%d")
                self.base_operator.update_record(row_index, "投递时间", today)

                # 设置初始状态
                self.base_operator.update_record(row_index, "最新状态", "已投递")

                print(f"[完成] 公司: {job_info.company}, 岗位: {job_info.position}, 地点: {job_info.location}")

        finally:
            self.base_operator.close()

    def run_email_monitoring(self):
        """运行邮箱监控任务"""
        print("\n" + "=" * 50)
        print("任务二：邮箱笔试/面试邮件识别与日历联动")
        print("=" * 50)

        # 收集缺失信息
        missing_time_emails = []      # 缺少时间的邮件
        missing_company_emails = []   # 匹配不到公司的邮件
        calendar_failed_emails = []   # 日历创建失败的邮件

        if not self.email_reader.connect():
            print("[错误] 无法连接邮箱")
            return

        try:
            # 读取最近的招聘邮件
            emails = self.email_reader.read_recent_emails()
            print(f"\n[信息] 共识别到 {len(emails)} 封招聘相关邮件")

            # 第一步：更新Base状态（按公司分组，用最新邮件状态）
            print("\n" + "-" * 50)
            print("步骤1：更新飞书Base状态")
            print("-" * 50)
            base_updated = 0
            base_skipped = 0
            base_failed = 0
            base_updated_list = []
            base_skipped_list = []
            base_failed_list = []
            try:
                # 先收集匹配不到公司的邮件（单独try-except，避免影响主流程）
                try:
                    for email in emails:
                        if email.company and email.email_type in ["assessment", "written_test", "interview", "rejection", "offer", "confirmation"]:
                            record = self.base_status_updater._find_record_by_company(email.company)
                            if not record:
                                missing_company_emails.append(email)
                except Exception as e:
                    print(f"[Base] 收集匹配不到公司的邮件时出错: {e}")
                    import traceback
                    traceback.print_exc()

                results = self.base_status_updater.batch_update(emails)
                base_updated = results['updated']
                base_skipped = results['skipped']
                base_failed = results['failed']
                base_updated_list = results['updated_list']
                base_skipped_list = results['skipped_list']
                base_failed_list = results['failed_list']
                print(f"\n[Base状态更新结果] 成功: {base_updated}, 跳过: {base_skipped}, 失败: {base_failed}")
            except Exception as e:
                print(f"[Base状态更新异常] {e}")
                import traceback
                traceback.print_exc()
                base_failed = len(emails)
                base_updated_list = []
                base_skipped_list = []
                base_failed_list = [("整体异常", str(e)[:200])]

            # 第二步：创建日历日程
            print("\n" + "-" * 50)
            print("步骤2：创建飞书日历日程")
            print("-" * 50)
            calendar_created = 0
            calendar_skipped = 0
            calendar_failed = 0
            for email_info in emails:
                print(f"\n[处理] {email_info.email_type}: {email_info.company} - {email_info.subject[:50]}")

                # 只处理测评、笔试、面试类型的邮件创建日历
                valid_types = ["written_test", "interview", "assessment"]
                if email_info.email_type not in valid_types:
                    print(f"[跳过] 非笔试/面试/测评类型，不创建日历")
                    calendar_skipped += 1
                    continue

                # 创建日历日程
                if email_info.start_time:
                    # 先检查是否已经创建过（去重）
                    msg_id = email_info.message_id
                    if msg_id and msg_id in self.calendar_manager.processed_ids:
                        print(f"[跳过] 该邮件已创建过日程")
                        calendar_skipped += 1
                        continue

                    success = self.calendar_manager.create_event(email_info)
                    if success:
                        calendar_created += 1
                    else:
                        calendar_failed += 1
                        calendar_failed_emails.append(email_info)
                else:
                    print("[跳过] 无法提取时间信息，跳过日历创建")
                    calendar_skipped += 1
                    missing_time_emails.append(email_info)

            print(f"\n[日历创建结果] 成功: {calendar_created}, 跳过: {calendar_skipped}, 失败: {calendar_failed}")

            # ========== 运行摘要 ==========
            print("\n" + "=" * 50)
            print("📊 本次运行摘要")
            print("=" * 50)
            print(f"  处理邮件总数：{len(emails)} 封")
            print(f"  Base状态更新：成功 {base_updated} 条，跳过 {base_skipped} 条，失败 {base_failed} 条")
            print(f"  日历日程创建：成功 {calendar_created} 个，跳过 {calendar_skipped} 个，失败 {calendar_failed} 个")

            # Base状态更新详细列表
            if base_updated_list:
                print(f"\n  【Base状态更新成功】({len(base_updated_list)}条)")
                for company, reason in base_updated_list:
                    print(f"    - {company}: {reason}")
            if base_skipped_list:
                print(f"\n  【Base状态更新跳过】({len(base_skipped_list)}条)")
                for company, reason in base_skipped_list:
                    print(f"    - {company}: {reason}")
            if base_failed_list:
                print(f"\n  【Base状态更新失败】({len(base_failed_list)}条)")
                for company, reason in base_failed_list:
                    print(f"    - {company}: {reason}")

            # 缺失信息
            has_missing = missing_time_emails or missing_company_emails or calendar_failed_emails
            if has_missing:
                print("\n⚠️  需要你关注的信息：")
                if missing_time_emails:
                    print(f"\n  【缺少时间，未创建日历】({len(missing_time_emails)}封)")
                    for e in missing_time_emails:
                        print(f"    - {e.company or '未知公司'}: {e.subject[:60]}")
                if missing_company_emails:
                    print(f"\n  【Base里匹配不到公司，未更新状态】({len(missing_company_emails)}封)")
                    for e in missing_company_emails:
                        print(f"    - {e.company or '未知公司'}: {e.subject[:60]}")
                if calendar_failed_emails:
                    print(f"\n  【日历创建失败】({len(calendar_failed_emails)}封)")
                    for e in calendar_failed_emails:
                        print(f"    - {e.company or '未知公司'}: {e.subject[:60]}")
            else:
                print("\n✅  所有邮件处理完成，无缺失信息")

            print("\n" + "=" * 50)

        finally:
            self.email_reader.disconnect()

    def run_all(self):
        """运行所有任务"""
        print("\n" + "#" * 50)
        print("# 简历投递自动化跟踪系统")
        print(f"# 运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("#" * 50)

        # 任务一：链接抓取
        self.run_job_link_scraping()

        # 任务二：邮箱监控
        self.run_email_monitoring()

        print("\n" + "=" * 50)
        print("所有任务执行完成！")
        print("=" * 50)


def main():
    import sys

    config_path = "config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]

    tracker = JobTracker(config_path)

    if len(sys.argv) > 2:
        task = sys.argv[2]
        if task == "links":
            tracker.run_job_link_scraping()
        elif task == "email":
            tracker.run_email_monitoring()
        else:
            print(f"未知任务: {task}")
            print("可用任务: links, email, all")
    else:
        tracker.run_all()


if __name__ == "__main__":
    main()
