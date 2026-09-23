import sys
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from .models import (
    CombatState,
    Player,
    Monster,
    Card,
    Power,
    Potion,
    BaseAction,
    PlayCardAction,
    EndTurnAction,
)
from .compressor import StateCompressor

logger = logging.getLogger("spire_agent.driver")


class BaseGameDriver(ABC):
    """游戏驱动基础接口"""

    @abstractmethod
    def get_current_state(self) -> Optional[CombatState]:
        pass

    @abstractmethod
    def send_action(self, action: BaseAction) -> Optional[CombatState]:
        pass

    @abstractmethod
    def is_combat_over(self) -> bool:
        pass


class MockGameDriver(BaseGameDriver):
    """
    本地沙盒模拟驱动：
    无需安装真实游戏，通过离线模拟状态机验证 Jev Agent 的微步决策流与伤害扣减逻辑。
    """

    def __init__(self, scenario: str = "cultist"):
        self.scenario = scenario
        self.combat_over = False
        self.state = self._init_scenario(scenario)

    def _init_scenario(self, scenario: str) -> CombatState:
        if scenario == "lethal":
            p = Player(current_hp=50, max_hp=80, energy=3, block=0, powers=[Power(id="Strength", name="Strength", amount=2)])
            m = Monster(index=0, id="Gremlin", name="Fat Gremlin", current_hp=15, max_hp=30, block=0, intent="ATTACK", move_damage=12, move_hits=1)
            cards = [
                Card(index=0, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
                Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=10, description="Apply 2 Vulnerable"),
                Card(index=2, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
            ]
            return CombatState(turn=2, player=p, monsters=[m], hand=cards, draw_pile_count=10, discard_pile_count=5)

        elif scenario == "danger":
            p = Player(current_hp=20, max_hp=80, energy=3, block=0)
            m = Monster(index=0, id="GremlinNob", name="Gremlin Nob", current_hp=55, max_hp=85, block=0, intent="ATTACK", move_damage=24, move_hits=1)
            cards = [
                Card(index=0, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=1, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=2, id="Iron Wave", name="Iron Wave", cost=1, type="ATTACK", target_type="ENEMY", damage=5, block=5),
                Card(index=3, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6),
            ]
            return CombatState(turn=3, player=p, monsters=[m], hand=cards, draw_pile_count=12, discard_pile_count=7)

        else:
            p = Player(current_hp=65, max_hp=80, energy=3, block=0, powers=[Power(id="Strength", name="Strength", amount=1)])
            m = Monster(
                index=0,
                id="Cultist",
                name="Cultist",
                current_hp=48,
                max_hp=48,
                block=0,
                intent="ATTACK",
                move_damage=6,
                move_hits=1,
                powers=[Power(id="Ritual", name="Ritual", amount=3)],
            )
            cards = [
                Card(index=0, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=10, description="Apply 2 Vulnerable"),
                Card(index=1, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=7),
                Card(index=2, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=3, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
                Card(index=4, id="Demon Form", name="Demon Form", cost=3, type="POWER", target_type="NONE", description="Gain 2 Strength each turn"),
            ]
            potions = [Potion(index=0, id="FirePotion", name="Fire Potion", can_use=True, requires_target=True, description="Deal 20 damage")]
            return CombatState(turn=1, player=p, monsters=[m], hand=cards, potions=potions, draw_pile_count=15, discard_pile_count=0)

    def get_current_state(self) -> Optional[CombatState]:
        return self.state

    def send_action(self, action: BaseAction) -> Optional[CombatState]:
        logger.info(f"[Mock Driver 接收动作]: {action.raw_command}")

        if isinstance(action, EndTurnAction):
            logger.info("玩家结束回合，模拟敌方行动与下一回合抽牌...")
            self._simulate_enemy_turn()
            return self.state

        if isinstance(action, PlayCardAction):
            card = next((c for c in self.state.hand if c.index == action.card_index), None)
            if not card:
                logger.error(f"打出的卡牌 c{action.card_index} 不存在！")
                return self.state

            self.state.player.energy = max(0, self.state.player.energy - card.cost)

            if card.block > 0:
                self.state.player.block += card.block
                logger.info(f"玩家打出 {card.name}，获得 {card.block} 点格挡 (当前总格挡: {self.state.player.block})")

            if card.damage > 0:
                target_m = self.state.alive_monsters[0]
                if action.target_index is not None:
                    target_m = next((m for m in self.state.monsters if m.index == action.target_index), target_m)

                remain_dmg = max(0, card.damage - target_m.block)
                target_m.block = max(0, target_m.block - card.damage)
                target_m.current_hp = max(0, target_m.current_hp - remain_dmg)
                logger.info(f"玩家对 {target_m.name} 造成 {card.damage} 伤害！(怪物剩余血量: {target_m.current_hp})")

                if target_m.current_hp <= 0:
                    logger.info(f"怪物 {target_m.name} 被击杀！")
                    target_m.is_gone = True

            self.state.hand = [c for c in self.state.hand if c.index != card.index]
            self.state.discard_pile_count += 1

            if not self.state.alive_monsters:
                logger.info("所有怪物均已阵亡，战斗胜利！")
                self.combat_over = True

        return self.state

    def _simulate_enemy_turn(self):
        total_dmg = sum(m.total_incoming_damage for m in self.state.alive_monsters)
        hp_loss = max(0, total_dmg - self.state.player.block)
        self.state.player.block = 0
        self.state.player.current_hp = max(0, self.state.player.current_hp - hp_loss)
        logger.info(f"敌方攻击造成 {total_dmg} 伤害，玩家承受 {hp_loss} 点净伤 (剩余血量: {self.state.player.current_hp})")

        if self.state.player.current_hp <= 0:
            logger.info("玩家生命归零，战斗失败。")
            self.combat_over = True
            return

        self.state.turn += 1
        self.state.player.energy = self.state.player.max_energy
        self.state.hand = [
            Card(index=0, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
            Card(index=1, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
            Card(index=2, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
        ]

    def is_combat_over(self) -> bool:
        return self.combat_over


class CommunicationModDriver(BaseGameDriver):
    """
    真实游戏双向标准管道通信驱动：
    通过 stdin / stdout 实时与安装了 CommunicationMod 的 Slay the Spire 交互。
    """

    def __init__(self):
        self.current_state: Optional[CombatState] = None
        self.combat_finished = False

        # 【关键握手逻辑】
        # CommunicationMod 在拉起外部子进程后，会在 10 秒超时内等待子进程向 stdout 输出一首行信号
        # 若未发送，CommunicationMod 会认为子进程无响应并报告:
        # "Timed out while waiting for signal from external process." 并中断通信
        logger.info("[CommunicationMod] 向游戏发送初始就绪握手信号...")
        sys.stdout.write("ready\n")
        sys.stdout.flush()

    def get_current_state(self) -> Optional[CombatState]:
        while not self.combat_finished:
            line = sys.stdin.readline()
            if not line:
                self.combat_finished = True
                logger.info("CommunicationMod 标准输入管道关闭 (EOF)。")
                return None
            line_str = line.strip()
            if not line_str:
                continue
            try:
                raw_json = json.loads(line_str)
                # 检查当前是否处于战斗中
                game_state = raw_json.get("game_state", raw_json)
                if not game_state.get("is_screen_up", False) and "combat_state" in game_state:
                    self.current_state = StateCompressor.from_communication_mod_json(raw_json)
                    return self.current_state
                elif "combat_state" in game_state:
                    self.current_state = StateCompressor.from_communication_mod_json(raw_json)
                    return self.current_state
                else:
                    logger.info("游戏当前处于非战斗界面（如大地图/选卡牌界面），等待进入战斗...")
                    continue
            except json.JSONDecodeError as e:
                logger.warning(f"接收到非 JSON 数据: {line_str[:60]}... 异常: {e}")
                continue
        return None

    def send_action(self, action: BaseAction) -> Optional[CombatState]:
        logger.info(f"[发送游戏指令]: {action.raw_command}")
        sys.stdout.write(f"{action.raw_command}\n")
        sys.stdout.flush()
        return self.get_current_state()

    def is_combat_over(self) -> bool:
        return self.combat_finished
