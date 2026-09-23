from typing import Dict, Any, List
from .models import CombatState, Player, Monster, Card, Potion, Power


class StateCompressor:
    """
    状态压缩器：
    将庞大冗余的 Slay the Spire 游戏状态压缩为低 Token、高语义密度的紧凑 DSL 文本。
    供 Jev (System One) 极速解析。
    """

    @staticmethod
    def compress(state: CombatState) -> str:
        lines: List[str] = []
        lines.append(f"=== COMBAT TURN {state.turn} ===")

        # 1. Player 状态
        p = state.player
        p_powers = [f"{pw.name}:{pw.amount}" for pw in p.powers if pw.amount != 0]
        p_powers_str = f"[{', '.join(p_powers)}]" if p_powers else "none"
        relics_str = f"[{', '.join(p.relics[:5])}]" if p.relics else "none"

        lines.append(
            f"PLAYER: HP {p.current_hp}/{p.max_hp} | ENG {p.energy}/{p.max_energy} | BLK {p.block} | BUFFS: {p_powers_str} | RELICS: {relics_str}"
        )

        # 2. Monsters 状态
        lines.append("ENEMIES:")
        for m in state.alive_monsters:
            m_powers = [f"{pw.name}:{pw.amount}" for pw in m.powers if pw.amount != 0]
            m_powers_str = f"[{', '.join(m_powers)}]" if m_powers else "none"

            intent_desc = m.intent
            if "ATTACK" in m.intent.upper():
                intent_desc = f"ATK {m.move_damage}x{m.move_hits}"

            lines.append(
                f"- E{m.index} ({m.name}): HP {m.current_hp}/{m.max_hp} | BLK {m.block} | INTENT: {intent_desc} | BUFFS: {m_powers_str}"
            )

        # 3. Playable Hand
        lines.append("PLAYABLE_CARDS:")
        playable = state.playable_cards
        if not playable:
            lines.append("  (No playable cards with current energy)")
        else:
            for c in playable:
                effects: List[str] = []
                if c.damage > 0:
                    effects.append(f"{c.damage} dmg")
                if c.block > 0:
                    effects.append(f"{c.block} blk")
                if c.description:
                    effects.append(c.description)
                eff_str = ", ".join(effects) if effects else "Special effect"

                target_str = f"Target: {c.target_type}"
                lines.append(f"* [c{c.index}] {c.name} ({c.cost}E) -> {eff_str} ({target_str})")

        # 4. Unplayable Hand
        unplayable = [c for c in state.hand if c not in playable]
        if unplayable:
            lines.append("UNPLAYABLE_CARDS:")
            for c in unplayable:
                reason = "Not enough energy" if c.cost > p.energy else "Unplayable condition"
                lines.append(f"- [c{c.index}] {c.name} ({c.cost}E) -> {reason}")

        # 5. Potions & Decks
        usable_potions = [p for p in state.potions if p.can_use]
        if usable_potions:
            pot_strs = [f"[p{p.index}: {p.name}]" for p in usable_potions]
            lines.append(f"POTIONS: {', '.join(pot_strs)}")

        lines.append(f"DECK: Draw {state.draw_pile_count} | Discard {state.discard_pile_count} | Exhaust {state.exhaust_pile_count}")

        return "\n".join(lines)

    @classmethod
    def from_communication_mod_json(cls, raw: Dict[str, Any]) -> CombatState:
        """
        从 CommunicationMod 的标准 JSON 格式解析出 CombatState。
        """
        game_state = raw.get("game_state", raw)
        combat_state = game_state.get("combat_state", {})

        # 玩家
        raw_player = combat_state.get("player", {})
        player_powers = [
            Power(id=pw.get("id", ""), name=pw.get("name", pw.get("id", "")), amount=pw.get("amount", 0))
            for pw in raw_player.get("powers", [])
        ]
        relics = [r.get("name", r.get("id", "")) for r in game_state.get("relics", [])]

        player = Player(
            current_hp=raw_player.get("current_hp", 0),
            max_hp=raw_player.get("max_hp", 0),
            energy=raw_player.get("energy", 0),
            block=raw_player.get("block", 0),
            powers=player_powers,
            relics=relics,
        )

        # 敌人
        monsters: List[Monster] = []
        for idx, m in enumerate(combat_state.get("monsters", [])):
            m_powers = [
                Power(id=pw.get("id", ""), name=pw.get("name", pw.get("id", "")), amount=pw.get("amount", 0))
                for pw in m.get("powers", [])
            ]
            monsters.append(
                Monster(
                    index=idx,
                    id=m.get("id", ""),
                    name=m.get("name", f"Monster_{idx}"),
                    current_hp=m.get("current_hp", 0),
                    max_hp=m.get("max_hp", 0),
                    block=m.get("block", 0),
                    intent=m.get("intent", "UNKNOWN"),
                    move_damage=m.get("move_adjusted_damage", m.get("move_base_damage", 0)),
                    move_hits=m.get("move_hits", 1),
                    powers=m_powers,
                    is_gone=m.get("is_gone", False),
                    half_dead=m.get("half_dead", False),
                )
            )

        # 手牌
        hand: List[Card] = []
        for idx, c in enumerate(combat_state.get("hand", [])):
            # 兼容 CommunicationMod 的 target 字段 (ENEMY, ALL_ENEMY, SELF, NONE) 与 has_target 属性
            raw_target = str(c.get("target", "")).upper()
            has_target = c.get("has_target", False) or raw_target in ["ENEMY", "SELF_AND_ENEMY"]
            if has_target:
                target_type = "ENEMY"
            elif raw_target == "ALL_ENEMY":
                target_type = "ALL_ENEMY"
            elif raw_target == "SELF":
                target_type = "SELF"
            else:
                target_type = "NONE"

            hand.append(
                Card(
                    index=idx,
                    id=c.get("id", ""),
                    name=c.get("name", f"Card_{idx}"),
                    cost=c.get("cost", 1),
                    type=c.get("type", "SKILL"),
                    target_type=target_type,
                    has_target=has_target,
                    is_playable=c.get("is_playable", True),
                    damage=c.get("damage", 0),
                    block=c.get("block", 0),
                    description=c.get("raw_description", ""),
                    upgraded=c.get("upgrades", 0) > 0,
                )
            )

        # 药水
        potions: List[Potion] = []
        for idx, pot in enumerate(game_state.get("potions", [])):
            potions.append(
                Potion(
                    index=idx,
                    id=pot.get("id", ""),
                    name=pot.get("name", f"Potion_{idx}"),
                    can_use=pot.get("can_use", False),
                    requires_target=pot.get("requires_target", False),
                )
            )

        return CombatState(
            turn=combat_state.get("turn", 1),
            player=player,
            monsters=monsters,
            hand=hand,
            potions=potions,
            draw_pile_count=len(combat_state.get("draw_pile", [])),
            discard_pile_count=len(combat_state.get("discard_pile", [])),
            exhaust_pile_count=len(combat_state.get("exhaust_pile", [])),
        )
