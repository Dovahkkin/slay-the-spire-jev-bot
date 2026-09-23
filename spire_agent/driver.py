import sys
import time
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from .models import (
    CombatState,
    FullGameState,
    Player,
    Monster,
    Card,
    Power,
    Potion,
    BaseAction,
    PlayCardAction,
    EndTurnAction,
    ChooseAction,
    ProceedAction,
    CancelAction,
)
from .compressor import StateCompressor

logger = logging.getLogger("spire_agent.driver")


class BaseGameDriver(ABC):
    """游戏驱动基础接口"""

    @abstractmethod
    def get_full_state(self) -> Optional[FullGameState]:
        """获取当前全局游戏状态帧"""
        pass

    @abstractmethod
    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        """发送动作并获取更新后的全局状态帧"""
        pass

    @abstractmethod
    def is_game_over(self) -> bool:
        """全局游戏或通信是否彻底结束"""
        pass

    def get_current_state(self) -> Optional[CombatState]:
        """兼容接口：获取当前回合战斗切片"""
        full = self.get_full_state()
        return full.combat_state if full else None

    def send_action(self, action: BaseAction) -> Optional[CombatState]:
        """兼容接口：发送动作并返回当前回合战斗切片"""
        full = self.send_full_action(action)
        return full.combat_state if full else None

    def is_combat_over(self) -> bool:
        """检查当前战斗是否结束"""
        full = self.get_full_state()
        if not full:
            return True
        return not full.in_combat


class MockGameDriver(BaseGameDriver):
    """
    本地沙盒模拟驱动：
    模拟完整生命周期：战斗中 -> 战利品结算 (金币/药水) -> 选牌 (Jev 抓牌) -> 大地图路径选择。
    """

    def __init__(self, scenario: str = "cultist"):
        self.scenario = scenario
        self.combat_over = False
        self.game_finished = False
        self.phase = "combat"  # combat -> reward -> card_reward -> map -> done
        self.combat_state = self._init_scenario(scenario)
        self.gold = 99
        self.deck = [
            Card(index=0, id="Strike", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=1, id="Strike", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=2, id="Strike", name="Strike", cost=1, type="ATTACK", damage=6),
            Card(index=3, id="Defend", name="Defend", cost=1, type="SKILL", block=5),
            Card(index=4, id="Defend", name="Defend", cost=1, type="SKILL", block=5),
            Card(index=5, id="Bash", name="Bash", cost=2, type="ATTACK", damage=8),
        ]
        self.relics = ["Burning Blood"]
        self.potions: List[Potion] = []
        self.screen_rewards = [{"reward_type": "GOLD", "gold": 18}, {"reward_type": "CARD"}]

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

    def get_full_state(self) -> Optional[FullGameState]:
        if self.game_finished:
            return None

        if self.phase == "combat":
            return FullGameState(
                screen_type="NONE",
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.combat_state.potions,
                combat_state=self.combat_state,
                is_screen_up=False,
                available_commands=["play", "end", "potion"],
            )
        elif self.phase == "reward":
            return FullGameState(
                screen_type="COMBAT_REWARD",
                screen_state={"rewards": self.screen_rewards},
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose", "proceed"],
            )
        elif self.phase == "card_reward":
            cards = [
                {"id": "Carnage", "name": "Carnage", "cost": 2, "type": "ATTACK", "damage": 20, "raw_description": "Ethereal. Deal 20 damage."},
                {"id": "ShrugItOff", "name": "Shrug It Off", "cost": 1, "type": "SKILL", "block": 8, "raw_description": "Gain 8 Block. Draw 1 card."},
                {"id": "DemonForm", "name": "Demon Form", "cost": 3, "type": "POWER", "raw_description": "At the start of your turn, gain 2 Strength."},
            ]
            return FullGameState(
                screen_type="CARD_REWARD",
                screen_state={"cards": cards, "skip_available": True},
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose", "cancel"],
            )
        elif self.phase == "map":
            next_nodes = [
                {"x": 1, "y": 2, "symbol": "M"},
                {"x": 2, "y": 2, "symbol": "?"},
            ]
            return FullGameState(
                screen_type="MAP",
                screen_state={"next_nodes": next_nodes, "boss_available": False},
                floor=1,
                act=1,
                gold=self.gold,
                current_hp=self.combat_state.player.current_hp,
                max_hp=self.combat_state.player.max_hp,
                deck=self.deck,
                relics=self.relics,
                potions=self.potions,
                is_screen_up=True,
                available_commands=["choose"],
            )
        return None

    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        logger.info(f"[Mock Driver 接收动作]: {action.raw_command} (当前阶段: {self.phase})")

        if self.phase == "combat":
            if isinstance(action, EndTurnAction):
                self._simulate_enemy_turn()
                return self.get_full_state()

            if isinstance(action, PlayCardAction):
                card = next((c for c in self.combat_state.hand if c.index == action.card_index), None)
                if not card:
                    return self.get_full_state()

                self.combat_state.player.energy = max(0, self.combat_state.player.energy - card.cost)

                if card.block > 0:
                    self.combat_state.player.block += card.block

                if card.damage > 0:
                    target_m = self.combat_state.alive_monsters[0]
                    if action.target_index is not None:
                        target_m = next((m for m in self.combat_state.monsters if m.index == action.target_index), target_m)

                    remain_dmg = max(0, card.damage - target_m.block)
                    target_m.block = max(0, target_m.block - card.damage)
                    target_m.current_hp = max(0, target_m.current_hp - remain_dmg)

                    if target_m.current_hp <= 0:
                        logger.info(f"怪物 {target_m.name} 被击杀！")
                        target_m.is_gone = True

                self.combat_state.hand = [c for c in self.combat_state.hand if c.index != card.index]
                self.combat_state.discard_pile_count += 1

                if not self.combat_state.alive_monsters:
                    logger.info("所有怪物均已阵亡，战斗胜利！进入战利品结算界面...")
                    self.combat_over = True
                    self.phase = "reward"

            return self.get_full_state()

        elif self.phase == "reward":
            if isinstance(action, ChooseAction):
                # 拾取金币或点击卡牌
                if self.screen_rewards and self.screen_rewards[0]["reward_type"] == "GOLD":
                    self.gold += self.screen_rewards[0]["gold"]
                    logger.info(f"拾取金币成功！当前金币: {self.gold}")
                    self.screen_rewards.pop(0)
                    return self.get_full_state()
                elif self.screen_rewards and self.screen_rewards[0]["reward_type"] == "CARD":
                    logger.info("点击卡牌奖励，进入三选一选牌界面...")
                    self.phase = "card_reward"
                    return self.get_full_state()
            elif isinstance(action, ProceedAction):
                logger.info("奖励领取完毕，前往地图路线选择...")
                self.phase = "map"
                return self.get_full_state()

        elif self.phase == "card_reward":
            if isinstance(action, ChooseAction):
                logger.info(f"玩家选择将卡牌 #{action.choice} 加入卡组！")
            elif isinstance(action, CancelAction):
                logger.info("玩家跳过本次卡牌奖励 (Skip)！")
            # 选牌后返回战利品界面或直接进地图
            self.screen_rewards = []
            self.phase = "map"
            return self.get_full_state()

        elif self.phase == "map":
            if isinstance(action, ChooseAction):
                logger.info(f"玩家选择地图节点 #{action.choice}，前往下一层！")
                self.phase = "done"
                self.game_finished = True
                return None

        return self.get_full_state()

    def _simulate_enemy_turn(self):
        total_dmg = sum(m.total_incoming_damage for m in self.combat_state.alive_monsters)
        hp_loss = max(0, total_dmg - self.combat_state.player.block)
        self.combat_state.player.block = 0
        self.combat_state.player.current_hp = max(0, self.combat_state.player.current_hp - hp_loss)

        if self.combat_state.player.current_hp <= 0:
            logger.info("玩家生命归零，战斗失败。")
            self.combat_over = True
            self.game_finished = True
            return

        self.combat_state.turn += 1
        self.combat_state.player.energy = self.combat_state.player.max_energy
        self.combat_state.hand = [
            Card(index=0, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
            Card(index=1, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
            Card(index=2, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
        ]

    def is_game_over(self) -> bool:
        return self.game_finished


class CommunicationModDriver(BaseGameDriver):
    """
    真实游戏双向标准管道通信驱动：
    通过 stdin / stdout 实时与安装了 CommunicationMod 的 Slay the Spire 交互。
    """

    def __init__(self):
        self.current_full_state: Optional[FullGameState] = None
        self.game_finished = False

        # 【关键握手逻辑】
        logger.info("[CommunicationMod] 向游戏发送初始就绪握手信号...")
        sys.stdout.write("ready\n")
        sys.stdout.flush()

    def get_full_state(self) -> Optional[FullGameState]:
        while not self.game_finished:
            line = sys.stdin.readline()
            if not line:
                self.game_finished = True
                logger.info("CommunicationMod 标准输入管道关闭 (EOF)。")
                return None
            line_str = line.strip()
            if not line_str:
                continue
            try:
                raw_json = json.loads(line_str)

                # 1. 检查游戏内外状态
                in_game = raw_json.get("in_game", False)
                if not in_game:
                    logger.info("游戏当前处于主菜单或游戏外部，等待玩家进入/开始新游戏...")
                    continue

                # 2. 检查游戏是否已就绪（避免在出牌动画或场景过渡中提前执行）
                ready = raw_json.get("ready_for_command", False)
                available_cmds = raw_json.get("available_commands", [])

                if not ready or not available_cmds:
                    # 游戏正在处理卡牌动画或行动，等待下一帧稳定状态
                    continue

                self.current_full_state = StateCompressor.from_communication_mod_full_json(raw_json)
                return self.current_full_state
            except json.JSONDecodeError as e:
                logger.warning(f"接收到非 JSON 数据: {line_str[:60]}... 异常: {e}")
                continue
        return None

    def send_full_action(self, action: BaseAction) -> Optional[FullGameState]:
        logger.info(f"[发送游戏指令]: {action.raw_command}")
        sys.stdout.write(f"{action.raw_command}\n")
        sys.stdout.flush()
        time.sleep(0.08)
        return self.get_full_state()

    def is_game_over(self) -> bool:
        return self.game_finished
