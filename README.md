# AI Job Workbench — 智能求职工作台

> 个人秋招全流程自动化管理系统：岗位自动抓取 + JD 智能打分 + 邮件追踪 + 飞书同步 + 知识库 + 复盘

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![ECharts](https://img.shields.io/badge/ECharts-5.4-orange.svg)](https://echarts.apache.org/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](#)

---

## 项目简介

这是一套为 2027 届应届生打造的秋招自动化工作台。核心解决三个问题：

1. **岗位太多看不过来** → 自动抓取 200+ 公司 7000+ 岗位，按简历匹配度三维打分，只推最适合的
2. **投递后没人管** → 自动追踪笔试/面试邮件，同步飞书表格 + 飞书日历
3. **信息太散记不住** → 求职知识库沉淀 + AI 问答辅助决策

## 功能模块

| 模块 | 功能 | 技术实现 |
|------|------|----------|
| 岗位抓取 | 每日自动抓 200+ 校招官网岗位 | Python + requests/playwright |
| JD 打分 | 三维打分（经验匹配/技术栈/薪资），85%+ 优先投 | 规则引擎 + LLM 精判 |
| 邮件追踪 | 自动识别笔试/面试邮件，同步飞书表+日历 | IMAP + 飞书 Open API |
| 投递管理 | 飞书表格实时更新投递状态 | 飞书多维表格 API |
| 知识库 | 求职博主内容沉淀 + AI 问答 | RAG（规划中） |
| 复盘 | 每日投递/面试记录 | 前端编辑器 + Markdown |

## 快速开始

```bash
# 克隆仓库
git clone https://github.com/你的用户名/ai-job-workbench.git
cd ai-job-workbench

# 安装依赖
pip install -r requirements.txt

# 配置简历和打分规则
cp config/resume.example.json config/resume.json
# 编辑 config/rules.yaml

# 每日运行（配合 Windows 定时任务 / crontab）
python src/job_matcher.py
```

## 项目结构

```
ai-job-workbench/
├── README.md
├── requirements.txt
├── config/
│   ├── rules.yaml           # 打分规则配置
│   └── resume.example.json  # 简历模板
├── src/
│   ├── job_matcher.py       # 岗位抓取 + JD 打分
│   ├── job_tracker.py       # 邮件追踪 + 状态识别
│   ├── build_excel.py       # 飞书表格同步
│   └── gen_report.py        # 每日报告生成
├── web/
│   └── index.html           # Dashboard 前端
├── data/
│   ├── jobs_raw.json        # 原始岗位数据
│   └── jobs_scored.json     # 打分后岗位
└── docs/
    └── architecture.md      # 架构设计文档
```

## 技术栈

- **后端**：Python 3.10+ / requests / playwright / pandas
- **前端**：HTML + ECharts（零构建工具，纯静态）
- **外部集成**：飞书 Open API（表格 + 日历）、IMAP 邮件
- **调度**：Windows 定时任务 / Linux crontab

## 参考项目

本项目设计参考了以下开源项目：
- [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) — 3.8万 Star 的 Claude Code 求职框架
- [loks666/get_jobs](https://github.com/loks666/get_jobs) — 全平台自动投递系统（Spring Boot）
- [yuyong513/spider](https://github.com/yuyong513/spider) — 招聘信息聚合可视化系统

## License

MIT
