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


if __name__ == "__main__":
    unittest.main()
