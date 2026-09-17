"""
邮件数据探查脚本
读取最近7天的所有邮件，输出详细信息，用于建立分类学
"""
import imaplib
import email
import os
from email.header import decode_header
import re
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

# 配置（从环境变量或config.json读取，不要硬编码）
EMAIL = os.getenv("EMAIL_USER", "your_email@163.com")
PASSWORD = os.getenv("EMAIL_PASSWORD", "your_imap_password")
IMAP_SERVER = "imap.163.com"
IMAP_PORT = 993
CHECK_DAYS = 38  # 从8月1日到9月7日


def decode_str(s):
    """解码邮件头字符串"""
    if not s:
        return ""
    if isinstance(s, bytes):
        s = s.decode('utf-8', errors='ignore')
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or 'utf-8', errors='ignore'))
            except:
                result.append(part.decode('utf-8', errors='ignore'))
        else:
            result.append(part)
    return ''.join(result)


def parse_date(date_str):
    """解析邮件日期"""
    if not date_str:
        return None
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except:
        return None


def get_body(msg):
    """获取邮件正文"""
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
            elif content_type == "text/html" and not html_body:
                try:
                    html_body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="ignore")
                except:
                    pass
    else:
        content_type = msg.get_content_type()
        if content_type == "text/plain":
            try:
                body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="ignore")
            except:
                pass
        elif content_type == "text/html":
            try:
                html_body = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="ignore")
            except:
                pass

    # 如果没有纯文本，从HTML提取
    if not body and html_body:
        # 简单的HTML标签去除
        body = re.sub(r'<[^>]+>', ' ', html_body)
        body = re.sub(r'\s+', ' ', body).strip()

    return body[:500]  # 只取前500字


def extract_company(subject, sender, body):
    """提取公司名（当前逻辑）"""
    text = f"{subject} {body}"

    # 从主题提取
    # 【公司名】... 格式
    match = re.search(r"【([^】]{2,20})】", subject)
    if match:
        company = match.group(1).strip()
        # 排除明显不是公司名的
        if not any(x in company for x in ["笔试", "面试", "测评", "邀请", "通知", "感谢", "投递", "招聘", "校招", "校园"]):
            return company, "主题【】"

    # XX公司/有限公司/科技/网络/集团 + 简历投递/招聘/结果/通知
    match = re.search(r"([\u4e00-\u9fa5]{2,20}(?:公司|有限公司|科技|网络|集团|股份))(?:简历投递|招聘|结果|通知|校园)", subject)
    if match:
        company = match.group(1).strip()
        city_prefixes = ["广州", "北京", "上海", "深圳", "杭州", "成都", "武汉", "南京", "苏州", "西安", "重庆", "天津", "长沙", "郑州", "青岛", "大连", "宁波", "厦门", "福州", "济南", "合肥", "昆明", "南昌", "石家庄", "太原", "沈阳", "长春", "哈尔滨", "贵阳", "南宁", "兰州", "乌鲁木齐", "呼和浩特", "银川", "西宁", "海口", "拉萨"]
        for city in city_prefixes:
            if company.startswith(city) and len(company) > len(city) + 2:
                company = company[len(city):]
                break
        return company, "主题公司+投递"

    # 主题开头是公司名+年份+校园招聘
    match = re.match(r"^([\u4e00-\u9fa5a-zA-Z0-9]{2,15})(?:202\d届|202\d年)?(?:校园招聘|校招|全球校园招聘)", subject)
    if match:
        return match.group(1).strip(), "主题开头+校招"

    # 来自XX的测评邀请
    match = re.search(r"来自([\u4e00-\u9fa5a-zA-Z0-9]{2,15})(?:的|招聘|校园)", subject)
    if match:
        return match.group(1).strip(), "来自XX"

    # 从发件人名称提取
    if sender:
        # 发件人名称可能是"公司名 <email>"或"公司名招聘 <email>"
        sender_name = re.sub(r'<[^>]+>', '', sender).strip()
        sender_name = re.sub(r'["\']', '', sender_name).strip()
        if sender_name and len(sender_name) <= 20:
            # 排除明显不是公司名的
            if not any(x in sender_name for x in ["通知", "邮箱", "服务", "系统", "管理员", "客服", "noreply", "no-reply", "recruiting", "campus", "hr", "HR"]):
                return sender_name, "发件人名称"
            # 如果包含"招聘"、"校招"等，去掉这些词
            cleaned = re.sub(r'(招聘|校招|校园招聘|人才|官方)', '', sender_name).strip()
            if cleaned and len(cleaned) >= 2 and len(cleaned) <= 20:
                return cleaned, "发件人名称(去招聘)"

    return "", "未提取到"


def classify_email(subject, body):
    """分类邮件（当前逻辑）"""
    text = f"{subject} {body}"
    text_lower = text.lower()

    # 强拒信
    strong_rejection = [
        r"未通过", r"不合适", r"不适合", r"不匹配", r"未能进入", r"未能通过",
        r"没有通过", r"很遗憾.{0,20}通知", r"很抱歉.{0,20}通知", r"人才库",
        r"后续有合适的机会", r"遗憾地通知", r"抱歉地通知", r"不再继续",
        r"无法进入", r"未进入下一轮",
    ]
    for p in strong_rejection:
        if re.search(p, text):
            return "rejection", f"强拒信:{p}"

    # offer
    offer_patterns = [r"录用通知", r"offer", r"入职通知", r"发放offer", r"接受offer"]
    for p in offer_patterns:
        if re.search(p, text, re.IGNORECASE):
            return "offer", f"offer:{p}"

    # 测评
    assessment_keywords = [
        "性格测评", "在线测评", "人才测评", "综合素质测评", "心理测评",
        "能力测评", "测评邀请", "测评通知", "完成测评", "测评链接", "在线人才测评",
    ]
    for k in assessment_keywords:
        if k in text:
            return "assessment", f"测评关键词:{k}"
    if "测评" in text:
        return "assessment", "通用:测评"

    # 笔试
    written_test_keywords = [
        "在线笔试", "笔试邀请", "笔试通知", "线上笔试", "统一笔试",
        "编程测试", "笔试时间", "参加笔试",
    ]
    for k in written_test_keywords:
        if k in text:
            return "written_test", f"笔试关键词:{k}"
    if "笔试" in text:
        return "written_test", "通用:笔试"

    # 面试
    interview_keywords = [
        "ai面试", "ai 面试", "视频面试", "线上面试", "群面", "一面", "二面",
        "三面", "hr面", "面试邀请", "面试通知", "面试时间", "参加面试",
        "面试链接", "在线面试",
    ]
    for k in interview_keywords:
        if k in text_lower:
            return "interview", f"面试关键词:{k}"
    if "面试" in text:
        return "interview", "通用:面试"

    # 投递确认
    confirmation_patterns = [
        r"简历投递成功", r"投递成功", r"已收到您的简历", r"我们已收到.{0,10}简历",
        r"确认职位信息", r"感谢您投递.{0,30}职位", r"期待与你.{0,10}合拍",
        r"简历已收到", r"简历已经被发送", r"申请.{0,10}成功", r"投递提醒", r"投递通知",
    ]
    for p in confirmation_patterns:
        if re.search(p, text):
            return "confirmation", f"投递确认:{p}"

    # 弱拒信
    weak_rejection = [
        r"感谢您对.{0,20}的关注", r"祝您.{0,10}顺利", r"感谢您的理解与支持",
        r"经过综合评估", r"经过慎重考虑", r"感谢您的申请", r"感谢您应聘",
        r"我们会尽快阅读您的简历", r"我们会尽快给予回复",
    ]
    for p in weak_rejection:
        if re.search(p, text):
            if not re.search(r"(邀请您|邀请你|请在.{0,10}内完成|测评链接|笔试链接|面试链接|投递成功|已收到|简历已经被发送)", text):
                return "rejection", f"弱拒信:{p}"

    # 调研
    survey_patterns = [
        r"面试体验.{0,10}调研", r"面试体验.{0,10}反馈", r"评价.{0,10}面试官",
        r"面试.{0,10}问卷调查", r"体验调研", r"满意度调查", r"邀请您参与.{0,10}调研",
    ]
    for p in survey_patterns:
        if re.search(p, text):
            return "survey", f"调研:{p}"

    return "other", "未匹配"


def main():
    print("=" * 80)
    print("邮件数据探查")
    print("=" * 80)

    # 连接邮箱
    print("\n[1/3] 连接邮箱...")
    imap = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap.login(EMAIL, PASSWORD)
    # 163邮箱需要在登录后发送ID命令
    imaplib.Commands['ID'] = ('AUTH',)
    imap._simple_command('ID', '("name" "job_tracker" "version" "1.0")')
    print("  连接成功")

    # 读取邮件
    print(f"\n[2/3] 读取最近{CHECK_DAYS}天的邮件...")
    imap.select("INBOX")
    since_date = (datetime.now() - timedelta(days=CHECK_DAYS)).strftime("%d-%b-%Y")
    _, message_ids = imap.search(None, f'(SINCE "{since_date}")')
    msg_ids = message_ids[0].split()
    print(f"  共找到 {len(msg_ids)} 封邮件")

    # 分析每封邮件
    print(f"\n[3/3] 分析邮件...")
    print("=" * 80)

    all_emails = []
    type_count = {}
    company_source_count = {}

    for i, msg_id in enumerate(msg_ids):
        try:
            _, msg_data = imap.fetch(msg_id, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            subject = decode_str(msg["Subject"])
            sender = decode_str(msg["From"])
            date = parse_date(msg["Date"])
            body = get_body(msg)

            # 提取公司名
            company, company_source = extract_company(subject, sender, body)

            # 分类
            email_type, match_reason = classify_email(subject, body)

            # 统计
            type_count[email_type] = type_count.get(email_type, 0) + 1
            company_source_count[company_source] = company_source_count.get(company_source, 0) + 1

            email_info = {
                "index": i + 1,
                "date": date.strftime("%Y-%m-%d %H:%M") if date else "未知",
                "subject": subject[:80],
                "sender": sender[:50],
                "company": company,
                "company_source": company_source,
                "type": email_type,
                "match_reason": match_reason,
                "body_preview": body[:150].replace("\n", " "),
            }
            all_emails.append(email_info)

        except Exception as e:
            print(f"  [{i+1}] 解析失败: {e}")

    imap.logout()

    # 输出详细结果
    print("\n" + "=" * 80)
    print("详细邮件列表")
    print("=" * 80)

    for e in all_emails:
        print(f"\n[{e['index']}] {e['date']}")
        print(f"  主题: {e['subject']}")
        print(f"  发件人: {e['sender']}")
        print(f"  公司名: {e['company']} (来源: {e['company_source']})")
        print(f"  分类: {e['type']} (匹配: {e['match_reason']})")
        print(f"  正文摘要: {e['body_preview']}")

    # 输出统计
    print("\n" + "=" * 80)
    print("统计汇总")
    print("=" * 80)

    print(f"\n邮件总数: {len(all_emails)}")

    print("\n【按类型统计】")
    for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}封")

    print("\n【按公司名提取来源统计】")
    for s, c in sorted(company_source_count.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}封")

    # 输出分类错误的可疑邮件
    print("\n" + "=" * 80)
    print("可疑分类（需要人工确认）")
    print("=" * 80)

    print("\n【被分类为rejection但可能不是的】")
    for e in all_emails:
        if e["type"] == "rejection":
            print(f"  [{e['index']}] {e['company']}: {e['subject']}")
            print(f"       匹配: {e['match_reason']}")

    print("\n【被分类为offer但可能不是的】")
    for e in all_emails:
        if e["type"] == "offer":
            print(f"  [{e['index']}] {e['company']}: {e['subject']}")
            print(f"       匹配: {e['match_reason']}")

    print("\n【被分类为other的】")
    for e in all_emails:
        if e["type"] == "other":
            print(f"  [{e['index']}] {e['company']}: {e['subject']}")

    print("\n【公司名未提取到的】")
    for e in all_emails:
        if not e["company"]:
            print(f"  [{e['index']}] {e['subject']}")
            print(f"       发件人: {e['sender']}")

    # 保存到JSON文件
    output_file = "email_analysis.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_emails, f, ensure_ascii=False, indent=2)
    print(f"\n详细数据已保存到: {output_file}")

    print("\n" + "=" * 80)
    print("探查完成！")
    print("=" * 80)


if __name__ == "__main__":
    main()
