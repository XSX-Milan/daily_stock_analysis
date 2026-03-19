import unittest
from unittest.mock import Mock

from src.agent.agents.base_agent import BaseAgent
from src.agent.protocols import AgentContext
from src.agent.tools.registry import ToolRegistry


class _DummyBaseAgent(BaseAgent):
    agent_name = "dummy"

    def system_prompt(self, ctx: AgentContext) -> str:
        return "core system prompt"

    def build_user_message(self, ctx: AgentContext) -> str:
        return "analyze this stock"


class BaseAgentSkillInstructionsTestCase(unittest.TestCase):
    def test_build_messages_injects_skill_instructions_system_message(self) -> None:
        agent = _DummyBaseAgent(
            tool_registry=ToolRegistry(),
            llm_adapter=Mock(),
            skill_instructions="  Follow strategy constraints strictly.  ",
        )
        messages = agent._build_messages(AgentContext())

        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"], "core system prompt")
        self.assertEqual(messages[1]["role"], "system")
        self.assertEqual(
            messages[1]["content"],
            "[Skill Instructions]\nFollow strategy constraints strictly.",
        )
        self.assertEqual(messages[2]["role"], "user")
        self.assertEqual(messages[2]["content"], "analyze this stock")

    def test_build_messages_skips_blank_skill_instructions(self) -> None:
        agent = _DummyBaseAgent(
            tool_registry=ToolRegistry(),
            llm_adapter=Mock(),
            skill_instructions="   ",
        )
        messages = agent._build_messages(AgentContext())

        self.assertEqual(len(messages), 2)
        self.assertEqual(
            messages[0], {"role": "system", "content": "core system prompt"}
        )
        self.assertEqual(messages[1], {"role": "user", "content": "analyze this stock"})


if __name__ == "__main__":
    unittest.main()
