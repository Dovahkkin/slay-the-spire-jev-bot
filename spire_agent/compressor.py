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

        # 计算敌方总攻击伤害与净扣血威胁
        total_incoming_attack = sum(
            m.move_damage * max(1, m.move_hits)
            for m in state.alive_monsters
            if "ATTACK" in m.intent.upper()
        )
        net_damage = max(0, total_incoming_attack - p.block)
        threat_str = f"INCOMING THREAT: {total_incoming_attack} dmg"
        if total_incoming_attack == 0:
            threat_str += " (No incoming attack)"
        elif net_damage > 0:
            threat_str += f" (Current Block: {p.block} -> UNBLOCKED: {net_damage} HP damage!)"
        else:
            threat_str += f" (Current Block: {p.block} -> FULLY BLOCKED)"
        lines.append(threat_str)

        # 3. Playable Hand
        lines.append("PLAYABLE_CARDS:")
        playable = state.playable_cards
        if not playable:
            lines.append("  (No playable cards with current energy)")
        else:
            for c in playable:
                effects: List[str] = []
                tags: List[str] = []
                c_name_lower = c.name.lower()
                c_desc_lower = c.description.lower() if c.description else ""

                if "flex" in c_name_lower or ("strength" in c_desc_lower and "gain" in c_desc_lower):
                    tags.append("[SETUP BUFF: +Strength]")
                elif "vulnerable" in c_desc_lower or c.id == "Bash":
                    tags.append("[VULNERABLE DEBUFF (+50% DMG)]")
                elif "weak" in c_desc_lower:
                    tags.append("[WEAK DEBUFF (-25% ATK)]")
                elif c.type == "POWER":
                    tags.append("[POWER: Persistent Buff]")
                elif any(kw in c_name_lower for kw in ["battle trance", "offering", "seeing red", "warcry"]):
                    tags.append("[DRAW/ENERGY SETUP]")

                if c.damage > 0:
                    effects.append(f"{c.damage} dmg")
                if c.block > 0:
                    effects.append(f"{c.block} blk")
                if c.description:
                    effects.append(c.description)
                eff_str = ", ".join(effects) if effects else "Special effect"
                tag_str = f" {' '.join(tags)}" if tags else ""

                target_str = f"Target: {c.target_type}"
                lines.append(f"* [c{c.index}] {c.name} ({c.cost}E){tag_str} -> {eff_str} ({target_str})")

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
                    can_discard=pot.get("can_discard", False),
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

    @staticmethod
    def compress_card_reward(
        deck: List[Card],
        relics: List[str],
        offered_cards: List[Card],
        can_skip: bool = True,
    ) -> str:
        """
        将选牌界面的卡组信息与候选卡牌压缩为紧凑 DSL。
        """
        lines: List[str] = []
        lines.append("=== CARD REWARD SELECTION ===")

        # 统计卡组简况
        deck_names = [c.name for c in deck]
        from collections import Counter
        card_counts = Counter(deck_names)
        deck_summary_parts = [f"{name} x{cnt}" if cnt > 1 else name for name, cnt in card_counts.most_common(8)]
        deck_str = ", ".join(deck_summary_parts) if deck_summary_parts else "Starter deck"

        lines.append(f"CURRENT DECK ({len(deck)} cards): [{deck_str}]")
        relics_str = f"[{', '.join(relics[:6])}]" if relics else "none"
        lines.append(f"RELICS: {relics_str}")

        lines.append("OFFERED CARDS:")
        for idx, c in enumerate(offered_cards):
            effs: List[str] = []
            if c.damage > 0:
                effs.append(f"{c.damage} dmg")
            if c.block > 0:
                effs.append(f"{c.block} blk")
            if c.description:
                effs.append(c.description)
            eff_desc = ", ".join(effs) if effs else "Special"
            lines.append(f"* [{idx}] {c.name} ({c.cost}E, {c.type}) -> {eff_desc}")

        options = [f"card_{idx}" for idx in range(len(offered_cards))]
        if can_skip:
            options.append("skip")
        lines.append(f"OPTIONS: {', '.join(options)}")
        return "\n".join(lines)

    @staticmethod
    def compress_map_selection(
        current_hp: int,
        max_hp: int,
        gold: int,
        floor: int,
        act: int,
        next_nodes: List[Any],
        boss_available: bool = False,
    ) -> str:
        """
        将地图路径分支压缩为紧凑 DSL。
        """
        lines: List[str] = []
        lines.append(f"=== MAP ROUTE NAVIGATION (Act {act}, Floor {floor}) ===")
        hp_pct = int((current_hp / max_hp * 100)) if max_hp > 0 else 0
        lines.append(f"PLAYER STATUS: HP {current_hp}/{max_hp} ({hp_pct}%) | Gold {gold}")

        lines.append("AVAILABLE PATHS:")
        if boss_available:
            lines.append("* [boss] ACT BOSS ROOM (Proceed to climax)")
        else:
            for idx, node in enumerate(next_nodes):
                symbol = getattr(node, "symbol", node.get("symbol", "?") if isinstance(node, dict) else "?")
                desc = getattr(node, "description", symbol)
                lines.append(f"* [node_{idx}] {desc} (coords: x={getattr(node, 'x', '?')}, y={getattr(node, 'y', '?')})")

        return "\n".join(lines)

    @classmethod
    def from_communication_mod_full_json(cls, raw: Dict[str, Any]) -> "FullGameState":
        """
        从 CommunicationMod 全局 JSON 解析为 FullGameState。
        """
        from .models import FullGameState, Card, Potion, MapNode

        game_state = raw.get("game_state", raw)
        screen_type = game_state.get("screen_type", "NONE")
        screen_state = game_state.get("screen_state", {})

        # 卡组
        deck: List[Card] = []
        for idx, c in enumerate(game_state.get("deck", [])):
            deck.append(
                Card(
                    index=idx,
                    id=c.get("id", ""),
                    name=c.get("name", f"Card_{idx}"),
                    cost=c.get("cost", 1),
                    type=c.get("type", "SKILL"),
                    damage=c.get("damage", 0),
                    block=c.get("block", 0),
                    description=c.get("raw_description", ""),
                    upgraded=c.get("upgrades", 0) > 0,
                )
            )

        # 遗物与药水
        relics = [r.get("name", r.get("id", "")) for r in game_state.get("relics", [])]
        potions: List[Potion] = [
            Potion(
                index=idx,
                id=pot.get("id", ""),
                name=pot.get("name", f"Potion_{idx}"),
                can_use=pot.get("can_use", False),
                can_discard=pot.get("can_discard", False),
                requires_target=pot.get("requires_target", False),
            )
            for idx, pot in enumerate(game_state.get("potions", []))
        ]

        # 战斗状态切片
        combat_state = None
        if "combat_state" in game_state and game_state.get("combat_state"):
            combat_state = cls.from_communication_mod_json(raw)

        return FullGameState(
            screen_type=screen_type,
            screen_state=screen_state,
            available_commands=raw.get("available_commands", []),
            choice_list=game_state.get("choice_list", []),
            ready_for_command=raw.get("ready_for_command", True),
            in_game=raw.get("in_game", True),
            floor=game_state.get("floor", 0),
            act=game_state.get("act", 1),
            gold=game_state.get("gold", 0),
            current_hp=game_state.get("current_hp", 0),
            max_hp=game_state.get("max_hp", 0),
            deck=deck,
            relics=relics,
            potions=potions,
            combat_state=combat_state,
            is_screen_up=game_state.get("is_screen_up", False),
        )

