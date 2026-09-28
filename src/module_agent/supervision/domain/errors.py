


class WorkflowStateValidationError(ValueError):
    """Workflow checkpoint or state fields are inconsistent."""


class WorkflowConfigurationError(RuntimeError):
    """Workflow cannot run because required configuration is invalid."""