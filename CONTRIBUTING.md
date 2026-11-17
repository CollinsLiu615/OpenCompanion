# 贡献指南

感谢你的兴趣。本项目有一条底线：**它必须是可信的**。

## 硬性要求

以下任意一条不满足，PR 会被拒绝：

1. **不引入埋点或统计 SDK**（Firebase、友盟、Bugly、Sentry、Google Analytics 等）
2. **不引入硬编码的服务器地址** —— 请求只能发往用户自己填的 `base_url`
3. **不私自扩大权限** —— 新增权限必须在 PR 中说明用途与必要性
4. **隐私数据不得进入日志或明文存储**

CI 会自动检查前两条。

## 开发环境

### 安卓

```bash
cd android
./make-keystore.sh   # 首次构建
./build.sh
```

需要 JDK 21、Android SDK（build-tools **36.1.0**，更低版本的 d8 有 bug）。

## 提交 PR

- 一个 PR 只做一件事
- 说明「为什么要改」，而不只是「改了什么」
- 涉及界面的改动请附截图
- 修 Bug 请说明复现步骤

## 界面规范

### 输入框字号不得小于 16px

iOS Safari 对 `font-size < 16px` 的输入框**会强制放大整个页面**，
用户点进输入框时页面会突然缩放。这是 Safari 的既定行为，不是 bug。

现有一律用 `font-family: inherit; font-size: 16px`，改动时勿降低。

### 品牌图与背景的对比

品牌图是纯黑字/线（RGB 0,0,0），**只能配浅色背景**。
更换配色方案时务必实际查看渲染结果，不要只检查图片文件本身。

## 代码风格

- Python：PEP 8
- Java：遵循既有风格，避免使用 lambda（旧版 d8 解析匿名内部类会崩）
- HTML/CSS/JS：单文件内联，不引入构建工具

## 报告问题

- 一般问题 → [Issues](../../issues)
- 安全漏洞 → 邮件 collinsliu9@gmail.com，**不要公开**
