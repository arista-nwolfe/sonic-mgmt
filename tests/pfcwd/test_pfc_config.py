import json
import os
import pytest
import logging
import time

from tests.common.helpers.assertions import pytest_assert
from tests.common.plugins.loganalyzer.loganalyzer import LogAnalyzer
from tests.common.config_reload import config_reload
from tests.common.utilities import update_pfcwd_default_state

logger = logging.getLogger(__name__)

DUT_RUN_DIR = "/home/admin/pfc_wd_tests"
TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "templates")
TMP_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "testrun")
CONFIG_TEST_EXPECT_INVALID_ACTION_RE = ".* Invalid PFC Watchdog action .*"
CONFIG_TEST_EXPECT_INVALID_DETECT_TIME_RE = ".* Failed to parse PFC Watchdog .* detection_time .*"
CONFIG_TEST_EXPECT_INVALID_RESTORE_TIME_RE = ".* Failed to parse PFC Watchdog .* restoration_time .*"

pytestmark = [
    pytest.mark.disable_loganalyzer,    # disable automatic fixture and invoke within each test
    pytest.mark.topology('any')
]


def create_run_dir():
    """
    Creates a temp run dir 'testrun' within the pfcwd folder
    """
    try:
        os.mkdir(TMP_DIR)
    except OSError as err:
        pytest.fail("Failed to create a temp run dir: {}".format(str(err)))


def generate_cfg_templates(test_port):
    """
    Build all the config templates that will be used for the config validation test

    Args:
        test_port (string): a random port selected from the test port list

    Returns:
        cfg_params (dict): all config templates
    """
    create_run_dir()
    with open(os.path.join(TEMPLATES_DIR, "pfc_config_params.json"), "r") as read_file:
        cfg_params = json.load(read_file)

    for key in cfg_params:
        write_file = key
        write_params = dict()
        write_params["PFC_WD"] = {test_port: {"action": cfg_params[key]["pfc_wd_action"],
                                              "detection_time": cfg_params[key]["pfc_wd_detection_time"],
                                              "restoration_time": cfg_params[key]["pfc_wd_restoration_time"]
                                              }
                                  }
        # create individual template files for each test
        with open(os.path.join(TMP_DIR, "{}.json".format(write_file)), "w") as wfile:
            json.dump(write_params, wfile)

    return cfg_params


def copy_templates_to_dut(duthost, cfg_params):
    """
    Copy all the templates created to the DUT

    Args:
        duthost (AnsibleHost): instance
        cfg_params (dict): all config templates

    Returns:
        None
    """
    duthost.shell("mkdir -p {}".format(DUT_RUN_DIR))
    for key in cfg_params:
        src_file = os.path.join(TMP_DIR, "{}.json".format(key))
        duthost.copy(src=src_file, dest="{}/{}.json".format(DUT_RUN_DIR, key))


def cfg_teardown(duthost):
    """
    Cleans up the DUT temp dir and temp dir on the host after the module run

    Args:
        duthost (AnsibleHost): instance

    Returns:
        None
    """
    if os.path.exists(TMP_DIR):
        os.system("rm -rf {}".format(TMP_DIR))
    duthost.shell("rm -rf {}".format(DUT_RUN_DIR))


@pytest.fixture(scope='class')
def cfg_setup(setup_pfc_test, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
    """
    Class level automatic fixture. Prior to the test run, create all the templates
    needed for each individual test and copy them on the DUT.
    After the all the test cases are done, clean up temp dir on DUT and host

    Args:
        setup_pfc_test: module fixture defined in module conftest.py
        duthost: instance of AnsibleHost class
    """
    duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
    setup_info = setup_pfc_test
    pfc_wd_test_port = list(setup_info['test_ports'].keys())[0]
    logger.info("Creating json templates for all config tests")
    cfg_params = generate_cfg_templates(pfc_wd_test_port)
    logger.info("Copying templates over to the DUT")
    copy_templates_to_dut(duthost, cfg_params)

    yield
    logger.info("--- Start running config tests ---")

    logger.info("--- Clean up config dir from DUT ---")
    cfg_teardown(duthost)


@pytest.fixture(scope='class')
def mg_cfg_setup(duthosts, enum_rand_one_per_hwsku_frontend_hostname):
    """
    Class level automatic fixture. Prior to the test run, enable default pfcwd configuration
    before load_minigraph.
    After the test case is done, recover the configuration

    Args:
        duthost: instance of AnsibleHost class
        enum_rand_one_per_hwsku_frontend_hostname(string) : randomly pick a dut in multi DUT setup
    Returns:
        None
    """
    duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]

    logger.info("Enable pfcwd in configuration file")
    original_pfcwd_value = update_pfcwd_default_state(duthost, "/etc/sonic/init_cfg.json", "enable")

    yield

    logger.info("--- Recover configuration ---")
    if original_pfcwd_value == 'disable':
        update_pfcwd_default_state(duthost, '/etc/sonic/init_cfg.json', 'disable')
        config_reload(duthost, config_source='minigraph')


@pytest.fixture(scope='function', autouse=True)
def stop_pfcwd(duthosts, enum_rand_one_per_hwsku_frontend_hostname):
    """
    Fixture that stops PFC Watchdog before each test run

    Args:
        duthost: instance of AnsibleHost class

    Returns:
        None
    """
    duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
    logger.info("--- Stop Pfcwd --")
    duthost.command("pfcwd stop")

    yield

    logger.info("--- Start Pfcwd--")
    duthost.command("pfcwd start_default")


@pytest.mark.usefixtures('cfg_setup')
class TestPfcConfig(object):
    """
    Test case definition and helper function class
    """
    def execute_test(self, duthost, syslog_marker, ignore_regex=None, expect_regex=None, expect_errors=False):
        """
        Helper function that loads each template on the DUT and verifies the expected behavior

        Args:
            duthost (AnsibleHost): instance
            syslog_marker (string): marker prefix name to be inserted in the syslog
            ignore_regex (string): file containing regexs to be ignored by loganalyzer
            expect_regex (string): regex pattern that is expected to be present in the syslog
            expect_erros (bool): if the test expects an error msg in the syslog or not. Default: False

        Returns:
            None
        """
        loganalyzer = LogAnalyzer(ansible_host=duthost, marker_prefix=syslog_marker)

        if ignore_regex:
            ignore_file = os.path.join(TEMPLATES_DIR, ignore_regex)
            reg_exp = loganalyzer.parse_regexp_file(src=ignore_file)
            loganalyzer.ignore_regex.extend(reg_exp)

        if expect_regex:
            loganalyzer.expect_regex = []
            loganalyzer.expect_regex.extend(expect_regex)

        loganalyzer.match_regex = []
        with loganalyzer(fail=not expect_errors):
            cmd = "sonic-cfggen -j {}/{}.json --write-to-db".format(DUT_RUN_DIR, syslog_marker)
            out = duthost.command(cmd)
            pytest_assert(out["rc"] == 0, "Failed to execute cmd {}: Error: {}".format(cmd, out["stderr"]))

    def test_forward_action_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests if the config gets loaded properly for a valid cfg template

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_fwd_action", "config_test_ignore_messages")

    def test_invalid_action_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when invalid action is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_invalid_action", None, [CONFIG_TEST_EXPECT_INVALID_ACTION_RE], True)

    def test_invalid_detect_time_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when invalid detect time is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_invalid_detect_time", None,
                          [CONFIG_TEST_EXPECT_INVALID_DETECT_TIME_RE], True)

    def test_low_detect_time_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when detect time < lower bound is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_low_detect_time", None, [CONFIG_TEST_EXPECT_INVALID_DETECT_TIME_RE], True)

    def test_high_detect_time_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when detect time > higher bound is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_high_detect_time", None, [CONFIG_TEST_EXPECT_INVALID_DETECT_TIME_RE], True)

    def test_invalid_restore_time_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when invalid restore time is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_invalid_restore_time", None,
                          [CONFIG_TEST_EXPECT_INVALID_RESTORE_TIME_RE], True)

    def test_low_restore_time_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when restore time < lower bound is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_low_restore_time", None, [CONFIG_TEST_EXPECT_INVALID_RESTORE_TIME_RE], True)

    def test_high_restore_time_cfg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for syslog error when restore time > higher bound is configured

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        self.execute_test(duthost, "pfc_wd_high_restore_time", None, [CONFIG_TEST_EXPECT_INVALID_RESTORE_TIME_RE], True)


@pytest.mark.usefixtures('mg_cfg_setup')
class TestDefaultPfcConfig(object):
    def test_default_cfg_after_load_mg(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
        Tests for checking if pfcwd gets started after load_minigraph

        Args:
            duthost(AnsibleHost): instance

        Returns:
            None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        config_reload(duthost, config_source='minigraph', safe_reload=True)
        # sleep 20 seconds to make sure configuration is loaded
        time.sleep(20)
        res = duthost.command('pfcwd show config')
        for port_config in res['stdout_lines']:
            if "ethernet" in port_config.lower():
                return
        # If no ethernet port existing in stdout, failed this case.
        pytest.fail("Failed to start pfcwd after load_minigraph")
