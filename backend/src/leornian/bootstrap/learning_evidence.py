from leornian.modules.assessment.evidence import AssessmentEvidence
from leornian.modules.identity.application import Identity
from leornian.modules.identity.infrastructure import PgIdentityStore
from leornian.modules.item_bank.evidence_context import EvidenceContext
from leornian.modules.learning.evidence import project_evidence
from leornian.modules.learning.planning import Plans


class LearningEvidenceWorkflow:
    def __init__(self, database):
        self.database = database

    def get(self, token, plan_id=None, node_key=None):
        with self.database.transaction(snapshot=True) as connection:
            actor = Identity(PgIdentityStore(connection)).authenticate(token)
            if plan_id:
                Plans(connection).get(actor, plan_id)
            evidence = AssessmentEvidence(connection, EvidenceContext(connection)).list(actor)
            if plan_id:
                evidence = [fact for fact in evidence if fact.plan_id == plan_id]
            if node_key:
                evidence = [fact for fact in evidence if fact.node_key == node_key]
            return project_evidence(evidence)
