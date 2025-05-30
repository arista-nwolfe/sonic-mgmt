"""
Test the running status and format of alerting message of Monit service.
"""
import logging

import pytest
import random

from tests.common.utilities import wait_until
from tests.common.helpers.assertions import pytest_assert
from tests.common.helpers.assertions import pytest_require

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.topology('any', 't1-multi-asic'),
    pytest.mark.disable_loganalyzer
]


@pytest.fixture
def stop_and_start_lldpmgrd(duthosts, enum_rand_one_per_hwsku_frontend_hostname):
    """Stops `lldpmgrd` process at setup stage and restarts it at teardwon.

    Args:
        duthosts: The fixture returns list of DuTs.
        enum_rand_one_per_hwsku_frontend_hostname: The fixture randomly pick up
        a frontend DuT from testbed.

    Returns:
        None.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]

    if duthost.is_multi_asic:
        process = random.choice(["lldp0", "lldp1"])
    else:
        process = "lldp"

    logger.info("Stopping 'lldpmgrd' process in {} container ...".format(process))
    stop_command_result = duthost.command("docker exec {} supervisorctl stop lldpmgrd".format(process))
    exit_code = stop_command_result["rc"]
    pytest_assert(exit_code == 0, "Failed to stop 'lldpmgrd' process in {} container!".format(process))
    logger.info("'lldpmgrd' process in {} container is stopped.".format(process))

    yield

    logger.info("Starting 'lldpmgrd' process in {} container ...".format(process))
    start_command_result = duthost.command("docker exec {} supervisorctl start lldpmgrd".format(process))
    exit_code = start_command_result["rc"]
    pytest_assert(exit_code == 0, "Failed to start 'lldpmgrd' process in {} container!".format(process))
    logger.info("'lldpmgrd' process in {} container is started.".format(process))


def check_monit_last_output(duthost):
    """Checks whether alerting message appears as output of command 'monit status' if
    process `lldpmgrd` was stopped.

    Args:
        duthost: An AnsibleHost object of DuT.

    Returns:
        None.
    """
    monit_status_result = duthost.shell("sudo monit status 'lldp|lldpmgrd'", module_ignore_errors=True)
    exit_code = monit_status_result["rc"]
    pytest_assert(exit_code == 0, "Failed to get Monit status of process 'lldpmgrd'!")

    indices = [i for i, s in enumerate(monit_status_result["stdout_lines"]) if 'last output' in s]
    if len(indices) > 0:
        monit_last_output = monit_status_result["stdout_lines"][indices[0]]
        if duthost.is_multi_asic:
            return "/usr/bin/lldpmgrd' is not running in host and in namespace asic0" in monit_last_output
        else:
            return "/usr/bin/lldpmgrd' is not running in host" in monit_last_output
    else:
        return False


def check_monit_expected_container_logging(duthost):
    """Checks whether alerting message appears as syslog if
    there is unexpected container not running.
    Args:
        duthost: An AnsibleHost object of DuT.
    Returns:
        None.
    """
    syslog_output = duthost.command("sudo grep 'ERR monit' /var/log/syslog")["stdout"]
    pytest_assert("Expected containers not running" not in syslog_output,
                  f"Expected containers not running found in syslog. Output was:\n{syslog_output}")


def test_monit_status(duthosts, enum_rand_one_per_hwsku_frontend_hostname):
    """Checks whether the Monit service was running or not.

    Args:
        duthosts: The fixture returns list of DuTs.
        enum_rand_one_per_hwsku_frontend_hostname: The fixture randomly picks up
        a frontend DuT from testbed.

    Returns:
        None.
    """
    logger.info("Checking the running status of Monit ...")

    duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]

    def _monit_status():
        monit_status_result = duthost.shell("sudo monit status", module_ignore_errors=True)
        return monit_status_result["rc"] == 0
    # Monit is configured with start delay = 300s, hence we wait up to 320s here
    pytest_assert(wait_until(320, 20, 0, _monit_status),
                  "Monit is either not running or not configured correctly")

    logger.info("Checking the running status of Monit was done!")


def test_monit_reporting_message(duthosts, enum_rand_one_per_hwsku_frontend_hostname, stop_and_start_lldpmgrd):
    """Checks whether the format of alerting message from Monit is correct or not.
       202012 and newer image version will be skipped for testing since Supervisord
       replaced Monit to do the monitoring critical processes.

    Args:
        duthosts: The fixture returns list of DuTs.
        enum_rand_one_per_hwsku_frontend_hostname: The fixture randomly pick up
        a frontend DuT from testbed.
        disable_lldp: The fixture function stops `lldpmgrd` process before testing
        and restarts `lldpmgrd` process at teardown.

    Returns:
        None.
    """
    duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]

    pytest_require("201811" in duthost.os_version or "201911" in duthost.os_version,
                   "Test is not supported for 202012 and newer image versions!")

    logger.info("Checking the format of Monit alerting message ...")

    pytest_assert(wait_until(180, 60, 0, check_monit_last_output, duthost),
                  "Expected Monit reporting message not found")
    wait_until(180, 60, 0, check_monit_expected_container_logging, duthost)
    logger.info("Checking the format of Monit alerting message was done!")
