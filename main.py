import sys
import os
import argparse
import logging
from dotenv import load_dotenv

# 预先加载 .env 文件中的配置
load_dotenv()

# 所有日志与调试打印必须输出到 sys.stderr，绝对不能污染 sys.stdout 通道！
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("main")

from spire_agent import (
    JevSpireAgent,
    MockGameDriver,
    CommunicationModDriver,
    StateCompressor,
    PlayCardAction,
    EndTurnAction,
)


def run_combat_loop(agent: JevSpireAgent, driver, max_steps: int = 150):
    """
    微步战斗主循环：
    首次获取战局 -> 循环决策 -> 发送动作并获取下一瞬状态 -> 持续执行直至战斗结束。
    """
    step = 1
    # 首次获取战局状态
    current_state = driver.get_current_state()

    while current_state is not None and not driver.is_combat_over() and step <= max_steps:
        print("\n" + "=" * 60, file=sys.stderr)
        logger.info(f"--- [微步决策 Micro-step #{step}] ---")

        # 打印当前压缩后的高密度 DSL（仅输出到 stderr）
        dsl_text = StateCompressor.compress(current_state)
        print("\n[当前状态压缩 DSL 预览]:", file=sys.stderr)
        print(dsl_text, file=sys.stderr)
        print("-" * 40, file=sys.stderr)

        # Agent 裁决
        action = agent.decide_action(current_state)
        logger.info(f"--> [Agent 决策输出]: {action.raw_command} (类型: {action.action_type})")

        # 发送动作至游戏，并直接读取游戏执行后回传的下一个战局状态
        current_state = driver.send_action(action)
        step += 1

    if driver.is_combat_over():
        logger.info("战斗顺利结束或通信断开！")
    else:
        logger.info("达到最大单场步数限制，循环终止。")


def main():
    parser = argparse.ArgumentParser(description="Jev Slay the Spire Agent")
    parser.add_argument(
        "--driver",
        choices=["mock", "live"],
        default="mock",
        help="运行模式: mock 为离线沙盒模拟，live 为连接真实 CommunicationMod 游戏进程",
    )
    parser.add_argument(
        "--scenario",
        choices=["cultist", "lethal", "danger"],
        default="cultist",
        help="沙盒模拟场景: cultist (邪教徒), lethal (斩杀残血局), danger (高危生存局)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="TypeSafe API Key (若未指定则自动从 .env 或环境变量读取 TYPESAFE_API_KEY)",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="网络代理地址 (例如 http://127.0.0.1:7890，若未指定则从 .env 读取 HTTPS_PROXY)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="TypeSafe 模型名称 (默认自动根据 Key 识别，官方为 jev-latest，Vercel 为 typesafe-ai/jev)",
    )
    args = parser.parse_args()

    # 初始化 Agent（自动挂载 .env 和 proxy）
    agent = JevSpireAgent(
        api_key=args.api_key,
        proxy=args.proxy,
        model=args.model,
    )

    if args.driver == "live":
        logger.info("启动真实游戏通信驱动 (CommunicationMod)...")
        driver = CommunicationModDriver()
    else:
        logger.info(f"启动本地沙盒驱动 (场景: {args.scenario})...")
        driver = MockGameDriver(scenario=args.scenario)

    run_combat_loop(agent, driver)


if __name__ == "__main__":
    main()
