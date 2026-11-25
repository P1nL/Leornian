from uuid import uuid4

from leornian.modules.knowledge.progress import MaterialPreparation


def test_progress_uses_real_chunk_and_embedding_receipts_and_keeps_unknown_visible():
    demand, job_id = uuid4(), uuid4()
    job = dict(id=job_id, phase="indexing", state="waiting_dependency",
               reason_code="indexing_pending", title="Official guide")
    build = dict(job_id=job_id, state="building", space={"mode": "hybrid"}, chunks=4, embedded=2)
    progress = MaterialPreparation.summarize(demand, {"status": "queued"}, [], [job], [build])
    steps = {step.key: step.status for step in progress.steps}
    assert steps["chunking"] == "completed" and steps["embedding"] == "running"
    assert progress.status == "processing"
    assert progress.steps[6].unit == "chunks"
    assert (progress.steps[6].completed, progress.steps[6].total) == (2, 4)
    assert steps["indexing"] == steps["retrieval"] == "pending"
    job.update(state="blocked_unknown", reason_code="external_result_unknown")
    unknown = MaterialPreparation.summarize(demand, {"status": "queued"}, [], [job], [build])
    assert unknown.status == "blocked_unknown"
    assert unknown.steps[6].status == "unknown"
    job.update(state="ready", reason_code=None)
    ready = MaterialPreparation.summarize(demand, {"status": "ready"}, [], [job], [build])
    assert ready.status == "ready" and all(step.status == "completed" for step in ready.steps)


def test_ready_documents_do_not_complete_a_retrieval_with_an_unknown_result():
    job = dict(id=uuid4(), phase="validating", state="ready",
               reason_code=None, title="Official guide")
    progress = MaterialPreparation.summarize(
        uuid4(), {"status": "blocked_unknown", "error_code": "external_result_unknown"},
        [], [job], [],
    )
    assert progress.status == "blocked_unknown"
    assert all(step.status == "completed" for step in progress.steps[:-1])
    assert progress.steps[-1].status == "unknown"
    assert progress.current_documents == progress.ready_documents == 1


def test_semantic_progress_counts_checks_in_the_current_reduction_level():
    job = dict(id=uuid4(), phase="validating", state="ready",
               reason_code=None, title="Official guide")
    checks = dict(completed=12, total=23, level=0)
    progress = MaterialPreparation.summarize(
        uuid4(), {"status": "queued", "error_code": "semantic_coverage_pending"},
        [], [job], [], checks,
    )
    step = progress.steps[-1]
    assert (step.unit, step.level, step.completed, step.total) == ("checks", 0, 12, 23)
    assert step.status == "running" and progress.status == "processing"


def test_unresolved_html_graphics_are_not_reported_as_completed_ocr():
    job = dict(id=uuid4(), phase="checking", state="waiting_config",
               reason_code="material_nontext_processing_required", title="Illustrated guide",
               issues=["html_nontext_content_pending"])
    progress = MaterialPreparation.summarize(uuid4(), {"status": "queued"}, [], [job], [])
    assert progress.steps[3].key == "ocr" and progress.steps[3].status == "waiting"
    assert progress.steps[4].status == "pending"
    assert progress.reason_code == "material_nontext_processing_required"
