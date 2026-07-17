# 成绩监控 QQ 机器人（未完善）

自动监控广东技术师范大学正方教务系统成绩更新，通过 QQ 发送通知。

## 工作原理

每 30 分钟（可配置）自动检查教务系统成绩页面，发现新成绩后通过 QQ 私聊通知你。

## 前置要求

- 安装了 Docker 和 Docker Compose 的 Linux 云服务器
- 一个 QQ 账号（建议使用小号）
- 能访问教务系统的网络环境（如校园网或 VPN）

## 快速开始

### 1. 克隆项目

```bash
git clone <repo> grade-monitor && cd grade-monitor
```

### 2. 配置环境变量

编辑 `bot/.env`，填入你的实际配置：

```bash
QQ_ID=你的QQ号              # 接收通知的 QQ 号
JW_COOKIE=你的教务系统Cookie  # 浏览器登录后获取
CHECK_INTERVAL_MINUTES=30    # 检查间隔（分钟）
JW_BASE_URL=https://jwglxt.gpnu.edu.cn
```

### 3. 获取教务系统 Cookie

1. 用 Chrome/Edge 打开教务系统并登录
2. 按 F12 打开 DevTools → Application → Cookies
3. 复制完整的 Cookie 字符串

### 4. 启动服务

```bash
docker compose up -d
```

### 5. 扫码登录 QQ

启动后查看 NapCatQQ 的 WebUI：

```bash
# 查看 NapCatQQ 日志获取登录二维码或链接
docker logs napcat

# 或访问 WebUI
http://<服务器IP>:6099/webui
```

按提示扫码登录 QQ。

### 6. 配置 Cookie

给机器人 QQ 发送私聊消息：

```
/设置cookie <你的Cookie字符串>
```

然后测试：

```
/测试cookie
```

## QQ 命令

| 命令 | 功能 |
|------|------|
| `/设置cookie <cookie>` | 设置教务系统 Cookie |
| `/测试cookie` | 测试 Cookie 是否有效 |
| `/查成绩` | 手动触发成绩检查 |
| `/成绩状态` | 查看已有成绩 |
| `/成绩监控` | 查看监控状态 |
| `/帮助` | 显示帮助 |

## 注意事项

- Cookie 与密码等效，请妥善保管，不要分享给他人
- 首次启动时已有成绩不会触发通知，仅之后新出的成绩会通知
- 如果 Cookie 过期，机器人会发消息提醒你更新
- 教务系统可能需要校园网才能访问，请确保服务器能连通

## 目录结构

```
grade-monitor/
├── docker-compose.yml
├── bot/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── .env
│   ├── bot.py
│   └── src/plugins/grade_monitor/
│       ├── __init__.py
│       ├── scraper.py       # HTTP 抓取
│       ├── parser.py        # 成绩解析
│       ├── detector.py      # 新成绩检测
│       ├── storage.py       # SQLite 存储
│       ├── notifier.py      # 消息格式化
│       ├── commands.py      # QQ 命令
│       ├── scheduler.py     # 定时任务
│       └── config_manager.py
├── napcat/                  # NapCatQQ 配置
└── data/                    # 成绩数据库
```
