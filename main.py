import sys
import os
import argparse
import logging
from typing import Optional
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


def run_game_loop(agent: JevSpireAgent, driver, max_steps: Optional[int] = None):
    """
    全生命周期主循环：
    根据游戏全局状态（战斗中、战利品界面、选牌界面、地图路线、营地、事件）自动派发决策。
    若 max_steps 为 None，将持续常驻运行，支持多局连续通关。
    """
    step = 1
    full_state = driver.get_full_state()

    while full_state is not None and not driver.is_game_over():
        if max_steps is not None and step > max_steps:
            logger.info("达到指定的单次测试步数限制，主循环终止。")
            break

        print("\n" + "=" * 60, file=sys.stderr)

        # 1. 处于战斗阶段
        if full_state.in_combat and full_state.combat_state is not None:
            combat_state = full_state.combat_state
            logger.info(f"--- [战斗微步 Micro-step #{step} | 回合 {combat_state.turn}] ---")

            # 打印当前战斗压缩 DSL
            dsl_text = StateCompressor.compress(combat_state)
            print("\n[战斗状态压缩 DSL 预览]:", file=sys.stderr)
            print(dsl_text, file=sys.stderr)
            print("-" * 40, file=sys.stderr)

            # Agent 战斗出牌决策
            action = agent.decide_action(combat_state)
            logger.info(f"--> [Agent 战斗出牌]: {action.raw_command} ({action.action_type})")
            full_state = driver.send_full_action(action)

        # 2. 处于非战斗阶段（战利品结算、选牌、地图、营地、事件等）
        else:
            screen_name = full_state.screen_type if full_state.screen_type != "NONE" else "DUNGEON"
            logger.info(f"--- [非战斗流程 Step #{step} | 界面: {screen_name}] ---")
            action = agent.decide_screen_action(full_state)
            logger.info(f"--> [Agent 流程指令]: {action.raw_command} ({action.action_type})")
            full_state = driver.send_full_action(action)

        step += 1

    if driver.is_game_over():
        logger.info("游戏阶段结束或与游戏通信断开。")



def run_combat_loop(agent: JevSpireAgent, driver, max_steps: int = 150):
    """兼容旧接口"""
    run_game_loop(agent, driver, max_steps=max_steps)



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

    run_game_loop(agent, driver)


if __name__ == "__main__":
    main()
