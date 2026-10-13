# 代码来源与第三方许可

## 与原项目的关系

本项目按仓库所有者的明确开源要求，从其 [kouqiang-beikao](https://github.com/19991621059/kouqiang-beikao) 本地工作副本中复用、改编以下代码；新项目的原创与经授权复用代码按根目录MIT许可证分发。这里没有把原项目所有内容重新许可或整体公开。

| 原路径 | 当前路径 | 复用内容 |
| --- | --- | --- |
| `services/legacy-api/app/ai/provider.py` | `backend/study_assistant/ai/provider.py` | 文本模型适配、流式回复、超时/错误处理；改为用户配置 |
| `packages/learning-ui/src/reader.tsx` | `frontend/src/components/ContentBlocks.tsx` | 原文安全显示与选择保存失败回退；适配当前数据接口 |

原项目基准提交、本地快照日期和复制时源文件SHA-256记录在 [upstream-provenance.json](docs/upstream-provenance.json)。哈希对应本地工作副本文件，不承诺与该基准提交文件完全相同。

未分发原项目的教材、试卷、题库、插图、字体文件、壁纸、宠物素材、安装包、账号、配置、数据库或密钥。示例正文与手写题为本项目原创MIT内容。AI参考题演示由这些原创示例生成并保留待核对标识，不是考试真题。

## 依赖

依赖分别受各自许可约束，根目录MIT许可不替代它们的许可。版本分别锁定在 `package-lock.json` 和 `backend/requirements.lock`。

浏览器构建包含 React、React DOM、Scheduler（MIT，Meta Platforms）以及Lucide图标（ISC；部分图标来自Feather，MIT，Cole Bemis）。对应版权及完整许可保存在：

- [React及同版权相关包许可](docs/licenses/react.txt)
- [Lucide与Feather许可](docs/licenses/lucide-react.txt)

FastAPI、Starlette、Uvicorn、HTTPX、Cryptography、pypdf、python-docx及其依赖通过Python包安装，原包的许可证与版权文件随安装包保留；本仓库不复制它们的实现。构建/测试工具亦保留安装包附带的许可。

真实截图与GIF只显示本项目原创示例及其运行结果，不包含模型密钥、访问密码、私有教材或第三方媒体。
