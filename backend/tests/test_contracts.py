import pytest
from pydantic import ValidationError

from leornian.modules.identity.contracts import LocalSessionRequest
from leornian.modules.learning.contracts import GoalInput


def test_normalize_inputs_before_validating():
    assert GoalInput(title="  Learn Python  ").title == "Learn Python"
    assert LocalSessionRequest(display_name="  Learner  ").display_name == "Learner"


@pytest.mark.parametrize("title", ["  ", "ab", "a" * 121])
def test_reject_invalid_titles(title):
    with pytest.raises(ValidationError):
        GoalInput(title=title)


def test_model_input_cannot_claim_another_actor():
    with pytest.raises(ValidationError):
        GoalInput(title="Learn Python", actor_id="someone-else")
