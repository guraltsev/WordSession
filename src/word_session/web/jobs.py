"""Background restore jobs whose progress the web API can report.

``JobManager.start_restore`` runs a restore on its own thread and
``JobManager.get`` returns a snapshot (``JobView``) of any recent job.
"""

import logging
import threading
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from word_session.model import RestoreReport, RestoreResult
from word_session.service import SessionService

_log = logging.getLogger(__name__)


class JobNotFound(KeyError):
    """Report that no recent job has the requested id."""


class JobError(BaseModel):
    """Describe why a job failed."""

    type: str
    message: str


class JobView(BaseModel):
    """Snapshot of a restore job.

    Attributes
    ----------
    id : str
        Job identifier.
    state : Literal["queued", "running", "done", "failed"]
        Lifecycle state.
    session_id : str
        Session being restored.
    results : list[RestoreResult]
        Per-document outcomes reported so far.
    report : RestoreReport | None
        Final report once the job is ``done``.
    error : JobError | None
        Failure details once the job is ``failed``.
    """

    id: str
    state: Literal["queued", "running", "done", "failed"]
    session_id: str
    results: list[RestoreResult] = Field(default_factory=list)
    report: RestoreReport | None = None
    error: JobError | None = None


class JobManager:
    """Run restores on background threads and remember the most recent ones.

    Parameters
    ----------
    service : SessionService
        Service whose ``restore`` is run; it serialises Word access and raises
        ``RestoreInProgress``, which becomes the job's error.
    keep : int
        Number of most recent jobs to remember.
    """

    def __init__(self, service: SessionService, *, keep: int = 50) -> None:
        self._service = service
        self._keep = keep
        self._jobs: dict[str, JobView] = {}  # insertion order = start order
        self._lock = threading.Lock()

    def start_restore(self, session_id: str, **options: Any) -> str:
        """Start restoring a session in the background.

        Parameters
        ----------
        session_id : str
            Selector of the session to restore.
        **options
            Keyword arguments for ``SessionService.restore`` (``only``,
            ``start_word``, ``restore_position``, ``dry_run``).

        Returns
        -------
        str
            The new job id.
        """
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = JobView(id=job_id, state="queued", session_id=session_id)
            # Forget the oldest jobs beyond the retention limit.
            while len(self._jobs) > self._keep:
                del self._jobs[next(iter(self._jobs))]
        thread = threading.Thread(
            target=self._run, args=(job_id, session_id, options), name=f"restore-{job_id[:8]}"
        )
        thread.daemon = True
        thread.start()
        return job_id

    def get(self, job_id: str) -> JobView:
        """Return a snapshot of a job.

        Raises
        ------
        JobNotFound
            If the id is unknown or the job was forgotten (a ``KeyError``).
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            return job.model_copy(deep=True)

    def _run(self, job_id: str, session_id: str, options: dict[str, Any]) -> None:
        """Execute one restore and record its progress and outcome."""
        self._update(job_id, state="running")

        def progress(result: RestoreResult) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.results.append(result)

        # Any failure, including RestoreInProgress, becomes the job's error.
        try:
            report = self._service.restore(session_id, progress=progress, **options)
        except Exception as exc:
            _log.warning("restore job %s failed: %r", job_id, exc, exc_info=True)
            error = JobError(type=type(exc).__name__, message=str(exc))
            self._update(job_id, state="failed", error=error)
            return
        self._update(job_id, state="done", report=report)

    def _update(self, job_id: str, **changes: Any) -> None:
        """Apply field changes to a job if it is still remembered."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                for key, value in changes.items():
                    setattr(job, key, value)
