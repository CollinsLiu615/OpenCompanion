# OpenCompanion · 开源 AI 伴侣

**Benzene AI Studio · Eight Pixel · 作者 CollinsLiu**

一个可以**完全自己定义**的 AI 伴侣。填上你的 API Key，用一句大白话描述你想要的人，
它会用 AI 把人设打磨成完整版本，然后你就可以和它聊天、收它的定时问候了。

- 🆓 **MIT 协议**，随便改随便用
- 🔌 **不锁厂商**：OpenAI / DeepSeek / Moonshot / 智谱 / 通义 / 本地 Ollama 都行
- 💾 **数据全在本地**：纯 JSON 文件，没有云端账户，随时备份
- 📱 **电脑 + 安卓** 两端

---

## 三步就能用

### 1️⃣ 配置 API

选一个服务商（或自己填地址），粘贴 API Key 和模型名，点「测试连接」确认能通。

| 服务商 | 地址 | 常用模型 |
| :--- | :--- | :--- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-flash` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 本地 Ollama | `http://localhost:11434/v1` | `qwen2.5` |

> Key 存在本机，不会上传到任何地方。

### 2️⃣ 描述人设

写一句大白话就行，比如：

> 嘴硬心软的女大学生，会吐槽我但很关心我，说话简短带点毒舌

点「让 AI 写完整人设」，它会生成带这些内容的完整文档：

- 身份与背景
- 性格特质（每个都配「具体表现」，不是空泛形容词）
- 说话风格（含 3 句示例台词）
- 相处方式
- 边界与禁区

### 3️⃣ 修改并保存

生成的文档**是可编辑的文本框**，不满意随便改，也可以点「重新生成」。
最后可以上传一张头像，就完成了。

---

## 电脑端

**不用命令行，也不用 `python xxx.py`。** 直接双击桌面图标即可。

首次安装桌面图标：

```bash
./desktop/scripts/install-desktop.sh     # 在桌面创建 OpenCompanion.app
```

之后双击那个图标 → 自动起服务 → 自动打开浏览器。

也可以直接用脚本：

```bash
./desktop/scripts/start.sh    # 启动（自动装依赖、起服务、开浏览器）
./desktop/scripts/stop.sh     # 停止
```

`start.sh` 会自己找 Python、缺依赖自动装、等就绪后再开浏览器，全程无需干预。

## 安卓端

先构建 APK：

```bash
cd android
./build.sh          # 需要 JDK 21 + Android SDK
```

生成的 `OpenCompanion.apk` 直接传到手机安装。

**安卓端是完整离线的**：不走服务器，AI 请求由原生 Java 直接发出，
配置和聊天记录都存手机本地。

> 构建提示：Android build-tools **必须用 36.1.0 或更新**。
> 旧版（34.0.0）的 `d8` 处理匿名内部类时会崩：
> `NullPointerException: Cannot invoke "String.length()" because "<parameter1>" is null`。

---

## 项目结构

```
open-companion/
├── core/              后端
│   ├── config.py      配置、人设、AI 调用、对话
│   ├── server.py      Flask 路由 + 进程内定时排程
│   └── notify.py      可选推送（Bark / Webhook）
├── templates/         网页界面（向导 / 列表 / 聊天）
├── desktop/
│   └── launcher.py    电脑端启动器（起服务 + 开浏览器 + 建图标）
├── android/           安卓工程
│   ├── app/src/       Java 源码（WebView + 原生网络桥）
│   ├── assets/        离线界面
│   └── build.sh       无 Gradle 打包脚本
└── data/              运行后生成，你的配置与对话都在这
```

---

## 界面说明

**启动动画**：品牌图标 → 中文名 → 英文名，短暂息屏后展示 Benzene AI Studio，再息屏进入应用。

**首次进入**必须同意《用户协议与隐私政策》才能使用；点击"不同意，退出"会直接关闭程序。
协议全文见 `docs/用户协议.md`。

**聊天页**：
- 左上角 ☰ → 人物列表，可切换角色、新建
- 右上角 ⚙ → 设置面板，包含：
  - 查看/修改人设（名字、简介、完整人设正文）
  - 查看/更换头像
  - 定时问候（添加/修改/删除时刻）
  - 导出对话（Markdown / JSON）
  - 清除聊天记录
  - 删除这个人物（需输入名字二次确认）

## 定时问候

服务运行时，进程内线程每分钟检查一次，到点就用 AI 生成一句符合人设的问候。
每个角色可以单独设置时刻和类型（`morning` / `noon` / `dinner` / `night`）。

**不依赖 cron 或 launchd**，因为很多环境（尤其是被沙箱限制的终端）里
这两样都装不上。用进程内线程最稳。

> 注意：服务关掉就不发。电脑睡眠期间也不发，醒来不补发当天已过的时刻
> （避免半夜开机推一份早上八点的早报）。

想让问候推到手机上，配置 `data/push.json`：

```json
{
  "bark": "https://api.day.app/你的KEY",
  "webhook": "https://ntfy.sh/你的topic",
  "enabled": true
}
```

---

## 设计上的两个坑（踩过了）

写这类项目时容易犯、也容易被忽略的错误，记在这里：

**1. 通知不要写回对话历史。**
问候是单方面的，用户不会回。如果把每次问候都存进 `history`，
历史里就全是「早安心」而没有用户的话，模型下次会照着复读，
出现「中午还在发早安」这种错乱。本项目里问候只写 `greetings.log`，不进 `history`。

**2. 定时任务要标归属。**
如果多个实例共用一个任务表、只比对时刻，那每条任务会被每个实例都执行一遍。
本项目每个任务都有 `owner`，各实例只跑自己的。

---

## 许可

MIT。人设内容归创建者所有。
