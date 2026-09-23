import os
import logging
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# 自动加载当前目录或父目录的 .env 文件
load_dotenv()

from .models import (
    CombatState,
    FullGameState,
    BaseAction,
    PlayCardAction,
    EndTurnAction,
    UsePotionAction,
    ChooseAction,
    ProceedAction,
    CancelAction,
    Card,
    Monster,
    MapNode,
)
from .compressor import StateCompressor

try:
    import httpx2
    from typesafe_sdk import TypeSafeClient, Choice, Score, Noul
    HAS_TYPESAFE_SDK = True
except ImportError:
    HAS_TYPESAFE_SDK = False

logger = logging.getLogger("spire_agent")


class JevSpireAgent:
    """
    基于 TypeSafe Jev (System One) 的《杀戮尖塔》智能决策 Agent。
    支持 .env 自动加载、本地代理以及 Vercel AI Gateway 自动识别与路由。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        proxy: Optional[str] = None,
        enable_deterministic_lethal: bool = True,
    ):
        self.api_key = api_key or os.environ.get("TYPESAFE_API_KEY")
        self.base_url = base_url or os.environ.get("TYPESAFE_BASE_URL")
        self.model = model or os.environ.get("TYPESAFE_DEFAULT_MODEL")
        self.enable_deterministic_lethal = enable_deterministic_lethal

        # 智能识别 Vercel AI Gateway 凭证 (vck_...)
        if self.api_key and self.api_key.strip().startswith("vck_"):
            if not self.base_url:
                self.base_url = "https://ai-gateway.vercel.sh/typesafe"
                logger.info("检测到 Vercel AI Gateway 凭证，自动配置 Base URL 为 https://ai-gateway.vercel.sh/typesafe")
            if not self.model or self.model == "jev-latest":
                self.model = "typesafe-ai/jev"

        # 兜底默认模型名称
        if not self.model:
            self.model = "jev-latest"

        # 代理支持：优先显式传参 -> 环境变量 TYPESAFE_PROXY -> HTTPS_PROXY / HTTP_PROXY
        self.proxy = (
            proxy
            or os.environ.get("TYPESAFE_PROXY")
            or os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
        )

        self.client: Optional[TypeSafeClient] = None
        if HAS_TYPESAFE_SDK and self.api_key:
            client_kwargs: Dict[str, Any] = {
                "api_key": self.api_key,
                "model": self.model,
            }
            if self.base_url:
                client_kwargs["base_url"] = self.base_url

            # 若配置了代理，构造带 proxy 的自定义 httpx2.Client 注入 SDK
            if self.proxy:
                logger.info(f"Jev Agent 使用网络代理: {self.proxy}")
                http_client = httpx2.Client(proxy=self.proxy)
                client_kwargs["http_client"] = http_client

            self.client = TypeSafeClient(**client_kwargs)

    def decide_action(self, state: CombatState) -> BaseAction:
        """
        单微步决策入口：
        1. 检查是否有合法手牌；
        2. 进行确定性静态斩杀检测；
        3. 构建 Jev 原语（Score 危险度、Choice 选牌、Choice 目标、Noul 药水）；
        4. 单次并行调用 Jev，获得概率校准判断；
        5. 结构化组装并返回执行指令。
        """
        playable_cards = state.playable_cards
        alive_monsters = state.alive_monsters

        # 1. 如果没有存活怪物或无任何打出卡牌，直接结束回合
        if not alive_monsters or not playable_cards:
            logger.info("无可用手牌或无存活怪物，选择结束回合。")
            return EndTurnAction.create()

        # 2. 确定性静态斩杀检测（代码层责任：数学能算的绝不麻烦大模型）
        if self.enable_deterministic_lethal:
            lethal_action = self._check_deterministic_lethal(state, playable_cards, alive_monsters)
            if lethal_action:
                logger.info(f"[确定性斩杀触发] 指令: {lethal_action.raw_command}")
                return lethal_action

        # 3. 状态文本压缩（DSL）
        compressed_state = StateCompressor.compress(state)

        # 4. 构建 Jev 原语
        questions = self._build_jev_questions(state, playable_cards, alive_monsters)

        # 5. 调用 Jev / Mock 降级
        if self.client:
            try:
                response = self.client.system_one(
                    state=compressed_state,
                    questions=questions,
                )
                return self._parse_jev_response(state, response.answers, playable_cards, alive_monsters)
            except Exception as e:
                logger.warning(f"Jev API 调用失败 ({e})，降级使用启发式规则。")

        # 若未配置 API Key 或调用异常，执行离线启发式模拟（保证本地调试与离线单测畅通无阻）
        return self._heuristic_fallback(state, playable_cards, alive_monsters)

    def _check_deterministic_lethal(
        self, state: CombatState, playable_cards: List[Card], alive_monsters: List[Monster]
    ) -> Optional[PlayCardAction]:
        """
        确定性斩杀检查：
        如果手里存在能直接击杀单体怪物的攻击牌（单牌伤害 >= 剩余生命 + 格挡），立即打出！
        """
        energy = state.player.energy
        for m in alive_monsters:
            effective_hp = m.current_hp + m.block
            for c in playable_cards:
                if c.type == "ATTACK" and c.cost <= energy:
                    if c.damage >= effective_hp:
                        target = m.index if (c.has_target or c.target_type == "ENEMY") else None
                        return PlayCardAction.create(c.index, target)
        return None

    def _build_jev_questions(
        self, state: CombatState, playable_cards: List[Card], alive_monsters: List[Monster]
    ) -> Dict[str, Any]:
        """
        并行原语组装：
        一次性构建所有决策维度，保证单次回合决策只需 1 次 API 往返。
        """
        # A. Score: 战局威胁评估 (4 级光谱)
        threat_question = Score(
            instructions="Rate the severity of incoming enemy threat to the player's survival this turn and immediate next turns.",
            criteria=[
                "Negligible: Incoming damage is 0 or fully mitigated by existing block; player HP is high.",
                "Manageable: Moderate attack or debuffs; taking minor chip damage is acceptable to develop powers.",
                "Dangerous: Heavy incoming damage that threatens a major portion of HP; urgent blocking needed.",
                "Critical/Lethal: Incoming damage will kill or cripple the player this turn; absolute priority on survival.",
            ],
        )

        # B. Choice: 选牌决策（动态候选集 + end_turn 分支）
        card_criteria: Dict[str, str] = {}
        for c in playable_cards:
            card_key = f"card_{c.index}"
            effects: List[str] = []
            if c.damage > 0:
                effects.append(f"Deal {c.damage} damage")
            if c.block > 0:
                effects.append(f"Gain {c.block} block")
            if c.description:
                effects.append(c.description)
            desc = f"{c.name} (Cost: {c.cost}E) -> {', '.join(effects)}"
            card_criteria[card_key] = desc

        card_criteria["end_turn"] = "End turn now without playing further cards (e.g. saving HP, preserving energy, or no favorable actions)."

        card_choice_question = Choice(
            instructions="Which action should the player take next given the current battlefield state?",
            criteria=card_criteria,
        )

        # C. Choice: 目标集火选择（推测性提问，仅在打出单体牌时消费）
        target_criteria: Dict[str, str] = {}
        for m in alive_monsters:
            intent_str = f"Atk {m.move_damage}x{m.move_hits}" if "ATTACK" in m.intent.upper() else m.intent
            target_criteria[f"enemy_{m.index}"] = (
                f"{m.name} (HP: {m.current_hp}/{m.max_hp}, Block: {m.block}, Intent: {intent_str})"
            )

        target_choice_question = Choice(
            instructions="If a single-target attack or debuff card is chosen, which enemy should be the primary focus target?",
            criteria=target_criteria if target_criteria else {"enemy_0": "Default target"},
        )

        # D. Noul: 应急药水使用判定
        potion_question = Noul(
            instructions="Does the current battle situation urgently justify consuming a valuable potion to prevent lethal damage or secure immediate victory?"
        )

        return {
            "threat_level": threat_question,
            "card_choice": card_choice_question,
            "target_choice": target_choice_question,
            "use_potion": potion_question,
        }

    def _parse_jev_response(
        self,
        state: CombatState,
        answers: Dict[str, Any],
        playable_cards: List[Card],
        alive_monsters: List[Monster],
    ) -> BaseAction:
        """
        消费 Jev 的类型化概率判定并映射到确定性动作
        """
        # 1. 检查药水 Noul (高阈值触发)
        if "use_potion" in answers:
            potion_prob = answers["use_potion"].noul
            if potion_prob > 0.85:
                usable_potions = [p for p in state.potions if p.can_use]
                if usable_potions:
                    pot = usable_potions[0]
                    target = alive_monsters[0].index if pot.requires_target else None
                    logger.info(f"Jev 判定药水使用概率高 ({potion_prob:.2f})，使用药水: {pot.name}")
                    return UsePotionAction.create(pot.index, target)

        # 2. 获取威胁分值 (Score)
        threat_score = answers.get("threat_level", None)
        if threat_score:
            logger.info(f"Jev 评估战场威胁值: {threat_score.score:.2f} (Confidence: {threat_score.confidence:.2f})")

        # 3. 获取选牌 Choice
        card_ans = answers.get("card_choice")
        if not card_ans:
            return EndTurnAction.create()

        chosen_key = card_ans.choice
        logger.info(f"Jev 选择动作: {chosen_key} (Confidence: {card_ans.confidence:.2f})")

        if chosen_key == "end_turn":
            return EndTurnAction.create()

        # 解析 card_<index>
        try:
            card_idx = int(chosen_key.split("_")[1])
            selected_card = next((c for c in playable_cards if c.index == card_idx), None)
            if not selected_card:
                logger.warning(f"选中的卡牌索引 c{card_idx} 不在合法手牌中，结束回合。")
                return EndTurnAction.create()

            target_idx = None
            if selected_card.has_target or selected_card.target_type == "ENEMY":
                target_ans = answers.get("target_choice")
                if target_ans and target_ans.choice.startswith("enemy_"):
                    target_idx = int(target_ans.choice.split("_")[1])
                elif alive_monsters:
                    target_idx = alive_monsters[0].index
                else:
                    target_idx = 0

            return PlayCardAction.create(selected_card.index, target_idx)
        except Exception as e:
            logger.error(f"解析动作异常: {e}，默认结束回合。")
            return EndTurnAction.create()

    def _heuristic_fallback(
        self, state: CombatState, playable_cards: List[Card], alive_monsters: List[Monster]
    ) -> BaseAction:
        """
        离线启发式兜底逻辑（用于无 API Key 时的本地沙盒演示与单元测试）
        """
        total_incoming = sum(m.total_incoming_damage for m in alive_monsters)
        needed_block = max(0, total_incoming - state.player.block)

        if needed_block > 0:
            block_cards = [c for c in playable_cards if c.block > 0]
            if block_cards:
                best_block = max(block_cards, key=lambda c: c.block)
                return PlayCardAction.create(best_block.index, None)

        attack_cards = [c for c in playable_cards if c.type == "ATTACK"]
        if attack_cards:
            best_atk = max(attack_cards, key=lambda c: c.damage)
            target = alive_monsters[0].index if (best_atk.has_target or best_atk.target_type == "ENEMY") else None
            return PlayCardAction.create(best_atk.index, target)

        first_card = playable_cards[0]
        target = alive_monsters[0].index if (first_card.has_target or first_card.target_type == "ENEMY") else None
        return PlayCardAction.create(first_card.index, target)

    def decide_card_reward(
        self,
        deck: List[Card],
        relics: List[str],
        offered_cards: List[Card],
        can_skip: bool = True,
    ) -> BaseAction:
        """
        Jev 选牌决策：
        利用 Choice 原语评估当前卡组构筑需求与候选卡牌，支持主动放弃 (Skip)。
        """
        if not offered_cards:
            logger.info("无候选卡牌可选，跳过/确认。")
            return CancelAction.create()

        # 压缩状态 DSL
        compressed = StateCompressor.compress_card_reward(deck, relics, offered_cards, can_skip)
        logger.info(f"\n[选牌状态压缩 DSL]:\n{compressed}")

        # 构建 Choice 候选选项
        criteria: Dict[str, str] = {}
        for idx, c in enumerate(offered_cards):
            eff_desc = f"{c.name} ({c.cost}E, {c.type}): {c.description or ('Dmg: ' + str(c.damage))}"
            criteria[f"card_{idx}"] = eff_desc

        if can_skip:
            criteria["skip"] = "Skip card reward: avoid diluting the deck with mediocre cards to keep high card draw consistency."

        if HAS_TYPESAFE_SDK and self.client:
            try:
                card_question = Choice(
                    instructions="Given the player's deck and relics, which card best improves deck synergy and survivability, or should the reward be skipped?",
                    criteria=criteria,
                )
                res = self.client.system_one(
                    state=compressed,
                    questions={"card_pick": card_question},
                )
                pick_ans = res.answers.get("card_pick")
                if pick_ans:
                    choice_key = pick_ans.choice
                    logger.info(f"--> [Jev 选牌决策]: {choice_key} (置信度: {pick_ans.confidence:.2f})")
                    if choice_key == "skip":
                        return CancelAction.create()
                    if choice_key.startswith("card_"):
                        pick_idx = int(choice_key.split("_")[1])
                        return ChooseAction.create(pick_idx)
            except Exception as e:
                logger.warning(f"Jev 选牌 API 调用失败 ({e})，降级使用启发式选牌。")

        # 启发式兜底：优先挑选伤害最高的攻击牌或优质防御牌
        attacks = [c for c in offered_cards if c.type == "ATTACK"]
        if attacks:
            best_atk = max(attacks, key=lambda c: c.damage)
            return ChooseAction.create(best_atk.index)
        return ChooseAction.create(0)

    def decide_map_route(
        self,
        current_hp: int,
        max_hp: int,
        gold: int,
        floor: int,
        act: int,
        next_nodes: List[Any],
        boss_available: bool = False,
    ) -> BaseAction:
        """
        Jev 地图路径决策：
        利用 Choice 原语根据生命百分比、金币与层数权衡各分支风险与收益。
        """
        if boss_available:
            logger.info("--> [地图决策]: Boss 房间已解锁，发起 Boss 决战！")
            return ChooseAction.create("boss")

        if not next_nodes:
            logger.info("--> [地图决策]: 无可选节点，默认推进。")
            return ChooseAction.create(0)

        if len(next_nodes) == 1:
            logger.info("--> [地图决策]: 仅单一路线可选，直接前进。")
            return ChooseAction.create(0)

        # 压缩状态 DSL
        compressed = StateCompressor.compress_map_selection(
            current_hp, max_hp, gold, floor, act, next_nodes, boss_available
        )
        logger.info(f"\n[地图导航压缩 DSL]:\n{compressed}")

        criteria: Dict[str, str] = {}
        for idx, n in enumerate(next_nodes):
            symbol = getattr(n, "symbol", n.get("symbol", "?") if isinstance(n, dict) else "?")
            symbol_desc = {
                "M": "Monster (Normal Enemy) - Low risk, earns gold and cards",
                "?": "Event (? Room) - Unknown event, potential reward or encounter",
                "E": "Elite - High danger, but drops valuable relics",
                "R": "Rest Site (Campfire) - Safe recovery (heal 30% HP) or card smithing",
                "$": "Shop - Buy relics/cards or remove unwanted cards",
                "T": "Treasure - Free chest rewards",
            }.get(symbol, f"Room type '{symbol}'")
            criteria[f"node_{idx}"] = symbol_desc

        if HAS_TYPESAFE_SDK and self.client:
            try:
                route_question = Choice(
                    instructions="Given current HP percentage, gold, and floor, which path node is optimal for survival and progression?",
                    criteria=criteria,
                )
                res = self.client.system_one(
                    state=compressed,
                    questions={"path_choice": route_question},
                )
                ans = res.answers.get("path_choice")
                if ans and ans.choice.startswith("node_"):
                    pick_idx = int(ans.choice.split("_")[1])
                    logger.info(f"--> [Jev 地图决策]: 选择节点 #{pick_idx} ({ans.choice}, 置信度: {ans.confidence:.2f})")
                    return ChooseAction.create(pick_idx)
            except Exception as e:
                logger.warning(f"Jev 地图导航 API 调用失败 ({e})，降级使用启发式选路。")

        # 启发式兜底：残血优先营地/规避精英
        hp_ratio = current_hp / max_hp if max_hp > 0 else 1.0
        for idx, n in enumerate(next_nodes):
            sym = getattr(n, "symbol", n.get("symbol", "?") if isinstance(n, dict) else "?")
            if hp_ratio < 0.45 and sym == "R":
                return ChooseAction.create(idx)
        return ChooseAction.create(0)

    def decide_screen_action(self, game_state: FullGameState) -> BaseAction:
        """
        非战斗屏幕统一动作派发器：
        自动拾取战利品、触发选牌、触发地图导航、营地休息等。
        """
        st = game_state.screen_type.upper()
        logger.info(f"处理非战斗界面: [{st}]")

        if st == "COMBAT_REWARD":
            raw_rewards = game_state.screen_state.get("rewards", [])
            if not raw_rewards:
                logger.info("战利品已拾取完毕，发送 PROCEED 前进。")
                return ProceedAction.create()

            # 1. 优先自动拾取金币、被盗金币、遗物、钥匙
            for idx, r in enumerate(raw_rewards):
                rtype = str(r.get("reward_type", "")).upper()
                if rtype in ["GOLD", "STOLEN_GOLD"]:
                    logger.info(f"自动拾取战利品金币 (索引 #{idx}): {r.get('gold', '')}G")
                    return ChooseAction.create(idx)
                if rtype == "RELIC":
                    logger.info(f"自动拾取战利品遗物 (索引 #{idx})")
                    return ChooseAction.create(idx)
                if rtype in ["SAPPHIRE_KEY", "EMERALD_KEY"]:
                    logger.info(f"自动拾取钥匙 (索引 #{idx})")
                    return ChooseAction.create(idx)

            # 2. 拾取药水（若药水栏未满）
            potion_slots = 3  # 默认 3 槽位
            has_empty_slot = len(game_state.potions) < potion_slots or any(not p.can_use for p in game_state.potions)
            for idx, r in enumerate(raw_rewards):
                rtype = str(r.get("reward_type", "")).upper()
                if rtype == "POTION" and has_empty_slot:
                    logger.info(f"自动拾取战利品药水 (索引 #{idx})")
                    return ChooseAction.create(idx)

            # 3. 点击卡牌奖励进入选牌界面
            for idx, r in enumerate(raw_rewards):
                rtype = str(r.get("reward_type", "")).upper()
                if rtype == "CARD":
                    logger.info(f"开启卡牌奖励界面 (索引 #{idx})")
                    return ChooseAction.create(idx)

            # 4. 全部处理完成，推进
            return ProceedAction.create()

        elif st == "CARD_REWARD":
            raw_cards = game_state.screen_state.get("cards", [])
            offered: List[Card] = []
            for idx, c in enumerate(raw_cards):
                offered.append(
                    Card(
                        index=idx,
                        id=c.get("id", ""),
                        name=c.get("name", f"Card_{idx}"),
                        cost=c.get("cost", 1),
                        type=c.get("type", "SKILL"),
                        damage=c.get("damage", 0),
                        block=c.get("block", 0),
                        description=c.get("raw_description", ""),
                    )
                )
            can_skip = game_state.screen_state.get("skip_available", True)
            return self.decide_card_reward(game_state.deck, game_state.relics, offered, can_skip)

        elif st == "MAP":
            next_nodes = game_state.screen_state.get("next_nodes", [])
            boss_available = game_state.screen_state.get("boss_available", False)
            return self.decide_map_route(
                current_hp=game_state.current_hp,
                max_hp=game_state.max_hp,
                gold=game_state.gold,
                floor=game_state.floor,
                act=game_state.act,
                next_nodes=next_nodes,
                boss_available=boss_available,
            )

        elif st == "REST":
            # 营地休息处
            options = [str(opt).upper() for opt in game_state.screen_state.get("rest_options", [])]
            has_rested = game_state.screen_state.get("has_rested", False)
            if has_rested or not options:
                return ProceedAction.create()

            hp_ratio = game_state.current_hp / game_state.max_hp if game_state.max_hp > 0 else 1.0
            if hp_ratio < 0.5 and "REST" in options:
                logger.info("玩家生命值低于 50%，在营地选择【休息 (Rest)】恢复生命。")
                return ChooseAction.create("rest")
            elif "SMITH" in options:
                logger.info("玩家生命安全，在营地选择【锻造 (Smith)】强化卡牌。")
                return ChooseAction.create("smith")
            elif "REST" in options:
                return ChooseAction.create("rest")
            else:
                return ChooseAction.create(0)

        elif st == "GRID":
            # 卡牌升级或卡牌选择
            if game_state.screen_state.get("confirm_up", False):
                return ProceedAction.create()
            logger.info("在卡牌列表选择第一张卡牌进行升级/交互。")
            return ChooseAction.create(0)

        elif st == "CHEST":
            if game_state.screen_state.get("chest_open", False):
                return ProceedAction.create()
            logger.info("打开宝箱...")
            return ChooseAction.create("open")

        elif st == "EVENT":
            opts = game_state.screen_state.get("options", [])
            for idx, opt in enumerate(opts):
                if not opt.get("disabled", False):
                    logger.info(f"选择事件选项 #{idx}: {opt.get('text', '')}")
                    return ChooseAction.create(idx)
            return ProceedAction.create()

        # 兜底推进逻辑
        if "proceed" in game_state.available_commands:
            return ProceedAction.create()
        if "cancel" in game_state.available_commands:
            return CancelAction.create()
        return ProceedAction.create()

