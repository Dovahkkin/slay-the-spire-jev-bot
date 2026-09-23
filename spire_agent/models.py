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


# --- 结构化出牌指令 ---
class BaseAction(BaseModel):
    action_type: Literal["play", "potion", "end_turn"]
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
