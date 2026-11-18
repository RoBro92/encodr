#!/usr/bin/env python3
import sys
from cli.docker import *
from cli.db import *
from cli.health import *
from cli.system import *
from cli.utils import *
from cli.main import *

if __name__ == "__main__":
    sys.exit(main())
