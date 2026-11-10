"""Completed synchronous Qiskit job, following the local-provider convention."""
import warnings

from qiskit.providers import JobV1, JobStatus


class QSim8Job(JobV1):
    _async = False

    def __init__(self, backend, job_id, result):
        super().__init__(backend, job_id)
        self._result = result

    def submit(self):
        """run() has already submitted and completed this job; never resend UART."""
        return None

    def result(self, timeout=None):
        if timeout is not None:
            warnings.warn('QSim8Q jobs are synchronous; timeout here does not change UART timeout.',
                          UserWarning, stacklevel=2)
        return self._result

    def status(self):
        return JobStatus.DONE

    def cancel(self):
        return False  # A returned job is already complete.
