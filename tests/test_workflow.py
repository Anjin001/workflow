"""验证流程的几条关键路径，使用标准库 unittest，无需 API Key。"""
import unittest

from workflow.llm import DEMO_REQUIREMENT, DemoModel, ModelClient
from workflow.runner import run_workflow
from workflow.state import WorkflowState


class WorkflowTests(unittest.TestCase):
    def run_scenario(self, scenario, max_repairs=2):
        return run_workflow(
            WorkflowState(DEMO_REQUIREMENT, max_repairs=max_repairs),
            DemoModel(scenario),
        )

    def test_repairs_then_rechecks_current_version(self):
        state = self.run_scenario("repair")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.repair_count, 1)
        checks = [event["validation"] for event in state.history if event["stage"] == "validate"]
        self.assertEqual([check["passed"] for check in checks], [False, True])
        self.assertEqual([check["code_version"] for check in checks], [1, 2])
        self.assertEqual(state.validation.code_version, state.code_version)
        self.assertIn("ZeroDivisionError", checks[0]["details"])

    def test_already_correct_code_skips_repair(self):
        state = self.run_scenario("pass")
        self.assertEqual(state.status, "completed")
        self.assertEqual(state.repair_count, 0)
        self.assertNotIn("fixer", [event["stage"] for event in state.history])

    def test_unsolved_problem_stops_at_limit(self):
        state = self.run_scenario("stuck")
        self.assertEqual(state.status, "needs_changes")
        self.assertEqual(state.repair_count, 2)
        self.assertFalse(state.validation.passed)
        self.assertTrue(state.issues)

    def test_zero_repairs_only_checks_initial_code(self):
        state = self.run_scenario("repair", max_repairs=0)
        self.assertEqual(state.status, "needs_changes")
        self.assertEqual(state.repair_count, 0)

    def test_model_error_is_recorded_as_failure(self):
        class BrokenModel(ModelClient):
            def generate(self, role, system_prompt, payload):
                raise RuntimeError("模拟模型请求失败")

        state = run_workflow(WorkflowState(DEMO_REQUIREMENT), BrokenModel())
        self.assertEqual(state.status, "failed")
        self.assertIn("模拟模型请求失败", state.error)

    def test_validation_failure_cannot_be_overridden_by_reviewer(self):
        class SilentReviewer(DemoModel):
            def generate(self, role, system_prompt, payload):
                if role == "reviewer":
                    return {"issues": []}
                return super().generate(role, system_prompt, payload)

        state = run_workflow(
            WorkflowState(DEMO_REQUIREMENT, max_repairs=0), SilentReviewer()
        )
        self.assertEqual(state.status, "needs_changes")
        self.assertFalse(state.validation.passed)

    def test_invalid_review_format_is_not_treated_as_success(self):
        class BadReviewer(DemoModel):
            def generate(self, role, system_prompt, payload):
                if role == "reviewer":
                    return {"issues": "看起来没问题"}
                return super().generate(role, system_prompt, payload)

        state = run_workflow(WorkflowState(DEMO_REQUIREMENT), BadReviewer("pass"))
        self.assertEqual(state.status, "failed")


if __name__ == "__main__":
    unittest.main()
