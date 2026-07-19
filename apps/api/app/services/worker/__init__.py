from .base import *
from .base import WorkerBaseService
from .health import WorkerHealthService
from .registration import WorkerRegistrationService
from .jobs import WorkerJobService
from .setup import WorkerSetupService
from .inventory import WorkerInventoryService

class WorkerService(
    WorkerRegistrationService,
    WorkerHealthService,
    WorkerJobService,
    WorkerInventoryService,
    WorkerSetupService,
):
    pass
