import unittest
from spire_agent import (
    CombatState,
    Player,
    Monster,
    Card,
    Power,
    StateCompressor,
    JevSpireAgent,
    MockGameDriver,
    PlayCardAction,
    EndTurnAction,
)


class TestSpireAgent(unittest.TestCase):

    def setUp(self):
        self.p = Player(current_hp=50, max_hp=80, energy=3, block=5, powers=[Power(id="Strength", name="Strength", amount=2)])
        self.m = Monster(
            index=0,
            id="Cultist",
            name="Cultist",
            current_hp=30,
            max_hp=48,
            block=0,
            intent="ATTACK",
            move_damage=6,
            move_hits=1,
            powers=[Power(id="Ritual", name="Ritual", amount=3)],
        )
        self.cards = [
            Card(index=0, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=10),
            Card(index=1, id="Strike", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8),
            Card(index=2, id="Defend", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5),
        ]
        self.state = CombatState(
            turn=1,
            player=self.p,
            monsters=[self.m],
            hand=self.cards,
            draw_pile_count=10,
            discard_pile_count=0,
        )

    def test_state_compressor(self):
        dsl = StateCompressor.compress(self.state)
        self.assertIn("PLAYER: HP 50/80", dsl)
        self.assertIn("ENG 3/3", dsl)
        self.assertIn("Cultist", dsl)
        self.assertIn("[c0] Bash (2E)", dsl)
        self.assertIn("[c1] Strike (1E)", dsl)
        self.assertIn("[c2] Defend (1E)", dsl)
        # 确保文本长度很短（通常小于 500 字符，几十到一百多 token）
        self.assertLess(len(dsl), 800)

    def test_deterministic_lethal(self):
        # 怪物仅剩 8 点血，手里有 8 点伤害的打击
        weak_m = Monster(
            index=0, id="Cultist", name="Cultist", current_hp=8, max_hp=48, block=0, intent="ATTACK", move_damage=6
        )
        state_lethal = CombatState(turn=1, player=self.p, monsters=[weak_m], hand=self.cards)
        agent = JevSpireAgent(enable_deterministic_lethal=True)
        action = agent.decide_action(state_lethal)

        self.assertIsInstance(action, PlayCardAction)
        # 应当打出能秒杀怪物的卡牌
        self.assertEqual(action.action_type, "play")
        self.assertEqual(action.target_index, 0)

    def test_mock_driver_simulation(self):
        # 跑通一个简单的战斗循环
        driver = MockGameDriver(scenario="lethal")
        agent = JevSpireAgent()

        steps = 0
        while not driver.is_combat_over() and steps < 10:
            st = driver.get_current_state()
            act = agent.decide_action(st)
            driver.send_action(act)
            steps += 1

        self.assertTrue(driver.is_combat_over(), "残血战局应当在几步内完成击杀！")

    def test_card_reward_and_looting(self):
        agent = JevSpireAgent()
        from spire_agent import FullGameState, ChooseAction, ProceedAction

        # 测试自动拾取金币与遗物
        reward_state = FullGameState(
            screen_type="COMBAT_REWARD",
            screen_state={"rewards": [{"reward_type": "GOLD", "gold": 25}, {"reward_type": "CARD"}]},
            available_commands=["choose", "proceed"],
        )
        act = agent.decide_screen_action(reward_state)
        self.assertIsInstance(act, ChooseAction)
        self.assertEqual(act.choice, "0")  # 优先拾取索引 0 的金币

        # 测试选牌决策
        cards = [
            Card(index=0, id="Carnage", name="Carnage", cost=2, type="ATTACK", damage=20),
            Card(index=1, id="Defend", name="Defend", cost=1, type="SKILL", block=5),
        ]
        card_act = agent.decide_card_reward(deck=self.cards, relics=["Burning Blood"], offered_cards=cards)
        self.assertTrue(card_act.action_type in ["choose", "cancel"])

    def test_map_route_decision(self):
        agent = JevSpireAgent()
        from spire_agent import ChooseAction

        # 测试地图路线选择
        next_nodes = [
            {"x": 1, "y": 2, "symbol": "M"},
            {"x": 2, "y": 2, "symbol": "R"},
        ]
        # 残血时偏好营地 (R)
        act = agent.decide_map_route(current_hp=15, max_hp=80, gold=50, floor=2, act=1, next_nodes=next_nodes)
        self.assertIsInstance(act, ChooseAction)

    def test_full_run_mock_loop(self):
        from main import run_game_loop
        driver = MockGameDriver(scenario="lethal")
        agent = JevSpireAgent()
        # 验证完整全流程：战斗斩杀 -> 拾取金币 -> 进入选牌 -> 挑选路线
        run_game_loop(agent, driver, max_steps=20)

    def test_shop_screen_leave_and_purge(self):
        from spire_agent import FullGameState, ChooseAction, LeaveAction
        agent = JevSpireAgent()

        # 1. 商店界面有 purge 选项时，优先净化卡牌
        shop_state_purge = FullGameState(
            screen_type="SHOP_SCREEN",
            screen_state={"purge_available": True, "purge_cost": 75},
            available_commands=["choose", "leave"],
            choice_list=["purge", "Strike", "Defend"],
            gold=100,
            floor=3,
        )
        act = agent.decide_screen_action(shop_state_purge)
        self.assertIsInstance(act, ChooseAction)
        self.assertEqual(act.choice, "0")

        # 2. 净化后或无购买选项（仅剩 leave）时，必须发出 LEAVE 指令离开商店
        shop_state_leave = FullGameState(
            screen_type="SHOP_SCREEN",
            screen_state={},
            available_commands=["potion", "leave", "key", "click", "wait", "state"],
            choice_list=[],
            gold=25,
            floor=3,
        )
        act_leave = agent.decide_screen_action(shop_state_leave)
        self.assertIsInstance(act_leave, LeaveAction)
        self.assertEqual(act_leave.raw_command, "LEAVE")

    def test_potion_looting_when_full_vs_empty(self):
        from spire_agent import FullGameState, ChooseAction, ProceedAction, Potion
        agent = JevSpireAgent()

        # 场景 A: 药水槽已满 (3 个真实药水，can_discard 为 True)
        # 战斗结算奖励中出现 POTION 奖励时，绝不尝试拾取药水，而是发送 PROCEED 前进
        full_potions = [
            Potion(index=0, id="Fire Potion", name="Fire Potion", can_discard=True),
            Potion(index=1, id="Block Potion", name="Block Potion", can_discard=True),
            Potion(index=2, id="Strength Potion", name="Strength Potion", can_discard=True),
        ]
        reward_potion_full = FullGameState(
            screen_type="COMBAT_REWARD",
            screen_state={"rewards": [{"reward_type": "POTION"}]},
            available_commands=["choose", "proceed"],
            potions=full_potions,
            floor=4,
        )
        act_full = agent.decide_screen_action(reward_potion_full)
        # 槽满时必须放弃药水直接推进，不能死锁发 CHOOSE 0
        self.assertIsInstance(act_full, ProceedAction)
        self.assertEqual(act_full.raw_command, "PROCEED")

        # 场景 B: 药水槽有空位 (包含 Potion Slot)
        # 应当正常拾取药水
        empty_potions = [
            Potion(index=0, id="Fire Potion", name="Fire Potion", can_discard=True),
            Potion(index=1, id="Block Potion", name="Block Potion", can_discard=True),
            Potion(index=2, id="Potion Slot", name="Potion Slot", can_discard=False),
        ]
        reward_potion_empty = FullGameState(
            screen_type="COMBAT_REWARD",
            screen_state={"rewards": [{"reward_type": "POTION"}]},
            available_commands=["choose", "proceed"],
            potions=empty_potions,
            floor=5,
        )
        act_empty = agent.decide_screen_action(reward_potion_empty)
        self.assertIsInstance(act_empty, ChooseAction)
        self.assertEqual(act_empty.choice, "0")


    def test_flex_before_attack_sequencing(self):
        """测试 0 费增益卡（如活动肌肉 Flex）必须先于攻击卡打出，杜绝时序倒挂"""
        strike = Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=6)
        flex = Card(index=1, id="Flex", name="Flex", cost=0, type="SKILL", target_type="SELF", description="Gain 2 Strength. At the end of your turn, lose 2 Strength.")
        defend = Card(index=2, id="Defend_R", name="Defend", cost=1, type="SKILL", target_type="SELF", block=5)

        m = Monster(index=0, id="JawWorm", name="Jaw Worm", current_hp=35, max_hp=42, block=0, intent="ATTACK", move_damage=11)
        state = CombatState(turn=1, player=self.p, monsters=[m], hand=[strike, flex, defend])

        agent = JevSpireAgent(enable_deterministic_lethal=True)
        act = agent.decide_action(state)

        # 必须优先打出索引为 1 的 Flex 卡牌，绝不能先打 Strike
        self.assertIsInstance(act, PlayCardAction)
        self.assertEqual(act.card_index, 1, "手牌有攻击卡时，0 费力量增益卡 Flex 必须优先于攻击牌打出！")

    def test_flex_assisted_lethal(self):
        """测试协同斩杀：单张打击打不死，但 Flex(+2)+打击(8+2=10)刚好斩杀时，优先打出 Flex"""
        strike = Card(index=0, id="Strike_R", name="Strike", cost=1, type="ATTACK", target_type="ENEMY", damage=8)
        flex = Card(index=1, id="Flex", name="Flex", cost=0, type="SKILL", target_type="SELF", description="Gain 2 Strength.")

        # 怪物剩余 10 点血，单独打击打不死，但 Flex 增益后恰好斩杀
        m = Monster(index=0, id="Cultist", name="Cultist", current_hp=10, max_hp=48, block=0, intent="ATTACK", move_damage=6)
        state = CombatState(turn=1, player=self.p, monsters=[m], hand=[strike, flex])

        agent = JevSpireAgent(enable_deterministic_lethal=True)
        act = agent.decide_action(state)

        self.assertIsInstance(act, PlayCardAction)
        self.assertEqual(act.card_index, 1, "协同斩杀应优先触发 Flex 增益牌！")

    def test_incoming_threat_dsl_and_synergy_tags(self):
        """测试 DSL 中包含明确的威胁计算与协同标签"""
        m = Monster(index=0, id="Cultist", name="Cultist", current_hp=30, max_hp=48, block=0, intent="ATTACK", move_damage=12, move_hits=1)
        flex = Card(index=0, id="Flex", name="Flex", cost=0, type="SKILL", target_type="SELF", description="Gain 2 Strength.")
        bash = Card(index=1, id="Bash", name="Bash", cost=2, type="ATTACK", target_type="ENEMY", damage=8, description="Deal 8 damage. Apply 2 Vulnerable.")

        state = CombatState(turn=1, player=self.p, monsters=[m], hand=[flex, bash])
        dsl = StateCompressor.compress(state)

        # 验证威胁计算
        self.assertIn("INCOMING THREAT: 12 dmg", dsl)
        self.assertIn("UNBLOCKED: 7 HP damage!", dsl)  # 12 incoming - 5 block = 7
        # 验证协同标签
        self.assertIn("[SETUP BUFF: +Strength]", dsl)
        self.assertIn("[VULNERABLE DEBUFF (+50% DMG)]", dsl)


if __name__ == "__main__":
    unittest.main()


