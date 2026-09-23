# Slay the Spire Jev Agent 🃏⚡

基于 **TypeSafe AI - Jev (System One)** 的《杀戮尖塔》（Slay the Spire）全自动对战智能 Agent。

---

## 核心设计特性

1. **Jev 原语融合（Primitives Mapping）**：
   - **`Score` (威胁度评估)**：4 级生存压力光谱（Safe -> Manageable -> Dangerous -> Critical/Lethal）。
   - **`Choice` (选牌决策)**：动态封闭候选集（合法的当前手牌 + `end_turn` 分支）。
   - **`Choice` (集火目标选择)**：推测性提问（Speculative Fan-out），在一次网络往返中同步评估多敌人优先级。
   - **`Noul` (应急药水判定)**：二元概率判断是否值得消耗宝贵的消耗品。
2. **状态文本压缩器（State Compressor DSL）**：
   - 将几万字符的游戏原始 JSON 紧凑压缩为 **100~250 Tokens** 的高密度 DSL。
   - 真实伤害与费用在代码层预结算，彻底杜绝大模型算术幻觉。
3. **微步闭环状态机（Micro-step Loop）**：
   - 像人类高手一样玩牌：打出过牌 -> 接收新手牌 -> 继续下一步，无需复杂的未来穷举。
4. **双驱动解耦（Dual Driver Architecture）**：
   - **MockGameDriver**：离线沙盒模拟器，无需安装游戏即可毫秒级调试 Agent 策略。
   - **CommunicationModDriver**：标准双向管道，一键无缝热插拔接入真实 Steam 游戏。

---

## 项目结构

```
.
├── spire_agent/
│   ├── __init__.py
│   ├── models.py       # Pydantic 战局状态模型与结构化动作指令 (PLAY / POTION / END)
│   ├── compressor.py   # 状态文本压缩器 (CombatState -> 紧凑 DSL)
│   ├── agent.py        # JevSpireAgent (静态斩杀、Jev 并行原语组装与解析)
│   └── driver.py       # 游戏通信抽象 (MockGameDriver 沙盒 + CommunicationMod 管道)
├── tests/
│   └── test_agent.py   # 单元测试套件
├── main.py             # 运行入口
├── requirements.txt    # 依赖声明
└── README.md
```

---

## 快速上手与离线测试

### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 运行单元测试
```bash
python -m unittest discover tests
```

### 3. 体验沙盒模拟战斗
你可以自由切换不同的模拟战局：

- **残血斩杀局**（演示确定性斩杀直接收割）：
  ```bash
  python main.py --driver mock --scenario lethal
  ```
- **经典遭遇战**（邪教徒仪式成长对攻）：
  ```bash
  python main.py --driver mock --scenario cultist
  ```
- **高危生存局**（面对高爆发攻击时的防御与抉择）：
  ```bash
  python main.py --driver mock --scenario danger
  ```

---

## 配置真实 Jev 模型

当你准备好使用 TypeSafe 的 Jev 模型进行实测时：

1. 获取 API Key：[console.typesafe.ai](https://console.typesafe.ai/)
2. 设置环境变量：
   ```bash
   # Windows PowerShell
   $env:TYPESAFE_API_KEY="your_api_key_here"

   # 或 CMD
   set TYPESAFE_API_KEY=your_api_key_here
   ```
3. 运行 Agent（未配置 Key 时代码会自动安全降级为启发式规则，保障离线演示不崩溃）。

---

## 后续连接真实《杀戮尖塔》指引

当你安装好 Steam 游戏后，只需 3 步即可接入：

1. **安装前置 Mod**：
   - 在 Steam 创意工坊订阅 **ModTheSpire** 和 **BaseMod**。
   - 下载并放入 **CommunicationMod**（尖塔的标准通信接口插件）。
2. **启动游戏**：
   - 运行 ModTheSpire，勾选 CommunicationMod。
3. **启动 Agent 对战**：
   ```bash
   python main.py --driver live
   ```
Agent 将自动接管游戏中的每场战斗！
