from __future__ import annotations
from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field


class Power(BaseModel):
    id: str
    name: str
    amount: int = 0


class Card(BaseModel):
    index: int
    name: str
    id: str
    cost: int
    type: Literal["ATTACK", "SKILL", "POWER", "STATUS", "CURSE"]
    target_type: Literal["ENEMY", "ALL_ENEMY", "SELF", "NONE"] = "NONE"
    has_target: bool = False
    is_playable: bool = True
    damage: int = 0
    block: int = 0
    description: str = ""
    upgraded: bool = False


class Monster(BaseModel):
    index: int
    id: str
    name: str
    current_hp: int
    max_hp: int
    block: int = 0
    intent: str = "UNKNOWN"
    move_damage: int = 0
    move_hits: int = 1
    powers: List[Power] = Field(default_factory=list)
    is_gone: bool = False
    half_dead: bool = False

    @property
    def total_incoming_damage(self) -> int:
        if "ATTACK" in self.intent.upper():
            return max(0, self.move_damage) * max(1, self.move_hits)
        return 0

    @property
    def is_alive(self) -> bool:
        return self.current_hp > 0 and not self.is_gone and not self.half_dead


class Player(BaseModel):
    current_hp: int
    max_hp: int
    energy: int
    max_energy: int = 3
    block: int = 0
    powers: List[Power] = Field(default_factory=list)
    relics: List[str] = Field(default_factory=list)


class Potion(BaseModel):
    index: int
    name: str
    id: str
    can_use: bool = False
    requires_target: bool = False
    description: str = ""


class CombatState(BaseModel):
    """当前战斗回合的战场切片"""
    turn: int = 1
    player: Player
    monsters: List[Monster] = Field(default_factory=list)
    hand: List[Card] = Field(default_factory=list)
    potions: List[Potion] = Field(default_factory=list)
    draw_pile_count: int = 0
    discard_pile_count: int = 0
    exhaust_pile_count: int = 0

    @property
    def alive_monsters(self) -> List[Monster]:
        return [m for m in self.monsters if m.is_alive]

    @property
    def playable_cards(self) -> List[Card]:
        return [c for c in self.hand if c.is_playable and c.cost <= self.player.energy]


# --- 非战斗屏幕与全屏状态模型 ---
class RewardItem(BaseModel):
    index: int
    reward_type: str  # GOLD, POTION, CARD, RELIC, STOLEN_GOLD, SAPPHIRE_KEY, etc.
    gold: int = 0
    potion: Optional[Dict[str, Any]] = None
    relic: Optional[Dict[str, Any]] = None
    link: Optional[Dict[str, Any]] = None


class MapNode(BaseModel):
    x: int
    y: int
    symbol: str  # M, ?, E, R, $, T, etc.

    @property
    def description(self) -> str:
        symbol_map = {
            "M": "Monster (Normal Enemy)",
            "?": "Event (Unknown ? Room)",
            "E": "Elite (Dangerous, Relic reward)",
            "R": "Rest Site (Campfire - Heal/Upgrade)",
            "$": "Shop (Merchant)",
            "T": "Treasure (Chest)",
        }
        return symbol_map.get(self.symbol, f"Room '{self.symbol}'")


class FullGameState(BaseModel):
    """通信层完整全局状态帧"""
    screen_type: str = "NONE"
    screen_state: Dict[str, Any] = Field(default_factory=dict)
    available_commands: List[str] = Field(default_factory=list)
    ready_for_command: bool = True
    in_game: bool = True
    floor: int = 0
    act: int = 1
    gold: int = 0
    current_hp: int = 0
    max_hp: int = 0
    deck: List[Card] = Field(default_factory=list)
    relics: List[str] = Field(default_factory=list)
    potions: List[Potion] = Field(default_factory=list)
    combat_state: Optional[CombatState] = None
    is_screen_up: bool = False

    @property
    def in_combat(self) -> bool:
        # 只要可用命令包含 play 或 end，无论动画状态如何均视为处于战斗中
        if "play" in self.available_commands or "end" in self.available_commands:
            return True
        if self.combat_state is not None and not self.is_screen_up:
            return len(self.combat_state.alive_monsters) > 0
        return False


# --- 结构化游戏指令 ---
class BaseAction(BaseModel):
    action_type: Literal["play", "potion", "end_turn", "choose", "proceed", "cancel", "confirm"]
    raw_command: str


class PlayCardAction(BaseAction):
    action_type: Literal["play"] = "play"
    card_index: int  # 内部 0-indexed
    target_index: Optional[int] = None  # 内部 0-indexed

    @classmethod
    def create(cls, card_index: int, target_index: Optional[int] = None) -> "PlayCardAction":
        # CommunicationMod 规范：PLAY <card_index (1-indexed)> [target_index (0-indexed)]
        card_param = card_index + 1
        cmd = f"PLAY {card_param}" if target_index is None else f"PLAY {card_param} {target_index}"
        return cls(raw_command=cmd, card_index=card_index, target_index=target_index)


class UsePotionAction(BaseAction):
    action_type: Literal["potion"] = "potion"
    potion_index: int
    target_index: Optional[int] = None

    @classmethod
    def create(cls, potion_index: int, target_index: Optional[int] = None) -> "UsePotionAction":
        cmd = f"POTION USE {potion_index}" if target_index is None else f"POTION USE {potion_index} {target_index}"
        return cls(raw_command=cmd, potion_index=potion_index, target_index=target_index)


class EndTurnAction(BaseAction):
    action_type: Literal["end_turn"] = "end_turn"

    @classmethod
    def create(cls) -> "EndTurnAction":
        return cls(raw_command="END")


class ChooseAction(BaseAction):
    action_type: Literal["choose"] = "choose"
    choice: str

    @classmethod
    def create(cls, choice: Any) -> "ChooseAction":
        return cls(raw_command=f"CHOOSE {choice}", choice=str(choice))


class ProceedAction(BaseAction):
    action_type: Literal["proceed"] = "proceed"

    @classmethod
    def create(cls) -> "ProceedAction":
        return cls(raw_command="PROCEED")


class CancelAction(BaseAction):
    action_type: Literal["cancel"] = "cancel"

    @classmethod
    def create(cls) -> "CancelAction":
        return cls(raw_command="CANCEL")


class ConfirmAction(BaseAction):
    action_type: Literal["confirm"] = "confirm"

    @classmethod
    def create(cls) -> "ConfirmAction":
        return cls(raw_command="CONFIRM")


