from app.utils.background_tasks import BackgroundTaskWorker, safe_error_message


def test_background_task_worker_emits_progress_and_finished() -> None:
    events = []
    worker = BackgroundTaskWorker(
        "example",
        lambda context: (
            context.report(1, 2, "halfway"),
            context.report(2, 2, "done"),
            "ok",
        )[-1],
    )
    worker.progress.connect(lambda done, total, message: events.append((done, total, message)))
    worker.finished.connect(lambda result: events.append(("finished", result)))

    worker.run()

    assert events == [(1, 2, "halfway"), (2, 2, "done"), ("finished", "ok")]


def test_background_task_worker_cancels_cooperatively() -> None:
    events = []

    def task(context):
        context.cancel()
        context.check_cancelled()

    worker = BackgroundTaskWorker("cancel-example", task)
    worker.canceled.connect(lambda message: events.append(message))

    worker.run()

    assert events == ["任务已取消。"]


def test_background_task_worker_redacts_and_truncates_failures() -> None:
    message = safe_error_message("api_key='secret-value' " + "x" * 1000, limit=80)

    assert "secret-value" not in message
    assert "[REDACTED]" in message
    assert len(message) <= 83
