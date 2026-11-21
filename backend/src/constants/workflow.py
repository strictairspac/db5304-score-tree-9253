from enum import StrEnum


class Role(StrEnum):
    OPERATOR = 'operator'
    REVIEWER = 'reviewer'
    VIEWER = 'viewer'


class Status(StrEnum):
    QUEUED = 'queued'
    RUNNING = 'running'
    COMPLETE = 'complete'
    FAILED = 'failed'
    REJECTED = 'rejected'


class BatchStatus(StrEnum):
    ACCEPTED = 'accepted'
    REJECTED = 'rejected'
    FAILED = 'failed'
