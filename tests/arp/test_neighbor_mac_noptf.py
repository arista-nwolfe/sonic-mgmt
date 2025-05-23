import json
import logging
import pytest
import time

from ipaddress import ip_interface
from tests.common.utilities import wait_until
from tests.common.helpers.assertions import pytest_assert
from tests.common.config_reload import config_reload

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.topology('any')
]

REDIS_NEIGH_ENTRY_MAC_ATTR = "SAI_NEIGHBOR_ENTRY_ATTR_DST_MAC_ADDRESS"
ROUTE_TABLE_NAME = 'ASIC_STATE:SAI_OBJECT_TYPE_ROUTE_ENTRY'
DEFAULT_ROUTE_NUM = 2


class TestNeighborMacNoPtf:
    """
        Test handling of neighbor MAC in SONiC switch
    """
    TEST_MAC = {
        4: ["08:bc:27:af:cc:45", "08:bc:27:af:cc:47"],
        6: ["08:bc:27:af:cc:65", "08:bc:27:af:cc:67"],
    }

    TEST_INTF = {
        4: {"intfIp": "29.0.0.1/24", "NeighborIp": "29.0.0.2"},
        6: {"intfIp": "fe00::1/64", "NeighborIp": "fe00::2"},
    }

    def count_routes(self, asichost, prefix):
        # Counts routes in ASIC_DB with a given prefix
        num = asichost.shell(
                '{} ASIC_DB eval "return #redis.call(\'keys\', \'{}:{{\\"dest\\":\\"{}*\')" 0'
                .format(asichost.sonic_db_cli, ROUTE_TABLE_NAME, prefix),
                module_ignore_errors=True, verbose=True)['stdout']
        return int(num)

    def _get_back_plane_port_ips(self, duthost):
        port_config = json.loads(duthost.shell("show runningconfiguration port",
                                 module_ignore_errors=True, verbose=False)['stdout'])

        back_plane_ports = [
            port for port, attrs in port_config.items()
            if attrs.get("role", "").lower() == "dpc"
        ]

        logger.info(f"back plane ports: {back_plane_ports}")

        back_plane_port_ips = []
        for port in back_plane_ports:
            try:
                output = duthost.shell(f"ip addr show {port} | grep -w inet | awk '{{print $2}}'",
                                       module_ignore_errors=True, verbose=False)["stdout"].strip()
                back_plane_port_ips.append(str(ip_interface(output).ip))
            except Exception as e:
                logger.warning(f"Error getting back plane {port} IP: {e}")

        logger.info(f"back plane port IPs: {back_plane_port_ips}")

        return back_plane_port_ips

    def _get_bgp_routes_asic(self, asichost, filter_ip_list=[]):
        # Get the routes installed by BGP in ASIC_DB by filtering out all local routes installed on asic
        localv6_prefixes = ["fc", "fe"]
        localv6 = sum(self.count_routes(asichost, prefix) for prefix in localv6_prefixes)
        # For 2 vlans with secondary subnet, the route subnet could be 192.169.0.0, not only 192.168.0.0
        localv4_prefixes = ["10.", "192."]
        localv4 = sum(self.count_routes(asichost, prefix) for prefix in localv4_prefixes)
        # these routes are present only on multi asic device, on single asic platform they will be zero
        internal_prefixes = ["8.", "2603"]
        if asichost.sonichost.facts['switch_type'] == 'voq':
            # voq inband_ip's
            internal_prefixes.append("3")
        internal = sum(self.count_routes(asichost, prefix) for prefix in internal_prefixes)
        # custom filtered ips
        filter = {
            ip for ip in set(filter_ip_list)
            if not any(ip.lower().startswith(prefix)
                       for prefix in (localv4_prefixes + localv6_prefixes + internal_prefixes))
        }
        logger.info("custom filter: {}".format(filter))
        filtered = sum(self.count_routes(asichost, ip) for ip in set(filter))

        allroutes = self.count_routes(asichost, "")
        logger.info("asic[{}] localv4 routes {} localv6 routes {} internalv4 {} filtered {} allroutes {}"
                    .format(asichost.asic_index, localv4, localv6, internal, filtered, allroutes))
        bgp_routes_asic = allroutes - localv6 - localv4 - internal - filtered - DEFAULT_ROUTE_NUM

        return bgp_routes_asic

    def _check_no_bgp_routes(self, duthost):
        bgp_routes = 0

        filter_ip_list = []
        if duthost.facts["asic_type"] == "cisco-8000":
            filter_ip_list = self._get_back_plane_port_ips(duthost)

        # Checks that there are no routes installed by BGP in ASIC_DB
        # by filtering out all local routes installed on testbed
        for asic in duthost.asics:
            bgp_routes += self._get_bgp_routes_asic(asic, filter_ip_list)

        return bgp_routes == 0

    @pytest.fixture(scope="module", autouse=True)
    def setupDutConfig(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
            Disabled BGP to reduce load on switch and restores DUT configuration after test completes

            Args:
                duthost (AnsibleHost): Device Under Test (DUT)

            Returns:
                None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        if not duthost.get_facts().get("modular_chassis"):
            duthost.command("sudo config bgp shutdown all")
            if not wait_until(120, 2.0, 0, self._check_no_bgp_routes, duthost):
                pytest.fail('BGP Shutdown Timeout: BGP route removal exceeded 120 seconds.')

        yield

        logger.info("Reload Config DB")
        config_reload(duthost, config_source='config_db', safe_reload=True, check_intf_up_ports=True)

    @pytest.fixture(params=[4, 6])
    def ipVersion(self, request):
        """
            Parameterized fixture for IP versions. This Fixture will run the test twice for both
            IPv4 and IPv6

            Args:
                request: pytest request object

            Returns:
                ipVersion (int): IP version to be used for testing
        """
        yield request.param

    @pytest.fixture(scope="module")
    def routedInterfaces(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
            Find routed interface to test neighbor MAC functionality with

            Args:
                duthost (AnsibleHost): Device Under Test (DUT)

            Returns:
                routedInterface (str): Routed interface used for testing
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        testRoutedInterface = {}

        def find_routed_interface():
            for asichost in duthost.asics:
                intfStatus = asichost.show_interface(command="status")["ansible_facts"]["int_status"]
                for intf, status in list(intfStatus.items()):
                    if "routed" in status["vlan"] and "up" in status["oper_state"]:
                        testRoutedInterface[asichost.asic_index] = intf
            return testRoutedInterface

        if not wait_until(120, 2, 0, find_routed_interface):
            pytest.fail('Failed to find routed interface in 120 s')

        yield testRoutedInterface

    @pytest.fixture
    def verifyOrchagentPresence(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname):
        """
            Verify orchagent is running before and after the test is finished

            Args:
                duthost (AnsibleHost): Device Under Test (DUT)

            Returns:
                None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]

        def verifyOrchagentRunningOrAssert(duthost):
            """
                Verifies that orchagent is running, asserts otherwise

                Args:
                    duthost (AnsibleHost): Device Under Test (DUT)
            """
            result = duthost.shell(argv=["pgrep", "orchagent"])
            orchagent_pids = result['stdout'].splitlines()
            pytest_assert(len(orchagent_pids) == duthost.num_asics(), "Orchagent is not running")
            for pid in orchagent_pids:
                pytest_assert(int(pid) > 0, "Orchagent is not running")

        verifyOrchagentRunningOrAssert(duthost)

        yield

        verifyOrchagentRunningOrAssert(duthost)

    def __updateNeighborIp(self, asichost, intf, ipVersion, macIndex, action=None):
        """
            Update IP neighbor

            Args:
                asichost (SonicHost): Asic Under Test (DUT)
                intf (str): Interface name
                ipVersion (Fixture<int>): IP version
                macIndex (int): test MAC index to be used
                action (str): action to perform

            Returns:
                None
        """
        neighborIp = self.TEST_INTF[ipVersion]["NeighborIp"]
        neighborMac = self.TEST_MAC[ipVersion][macIndex]
        logger.info("{0} neighbor {1} lladdr {2} for {3}".format(action, neighborIp, neighborMac, intf))
        cmd = asichost.ip_cmd if "add" in action else "{0} -{1}".format(asichost.ip_cmd, ipVersion)
        cmd += " neigh {0} {1} lladdr {2} dev {3}".format(action, neighborIp, neighborMac, intf)
        logger.info(cmd)
        asichost.shell(cmd)

    def __updateInterfaceIp(self, asichost, intf, ipVersion, action=None):
        """
            Update interface IP

            Args:
                asichost (SonicHost): Asic Under Test (DUT)
                intf (str): Interface name
                ipVersion (Fixture<int>): IP version
                action (str): action to perform

            Returns:
                None
        """
        logger.info("{0} an ip entry '{1}' for {2}".format(action, self.TEST_INTF[ipVersion]["intfIp"], intf))
        asichost.config_ip_intf(intf, self.TEST_INTF[ipVersion]["intfIp"], action)

    @pytest.fixture(autouse=True)
    def updateNeighborIp(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname,
                         enum_frontend_asic_index, routedInterfaces, ipVersion, verifyOrchagentPresence):
        """
            Update Neighbor/Interface IP

            Prepares the DUT for testing by adding IP to the test interface, add and update
            the neighbor MAC 2 times.

            Args:
                duthost (AnsibleHost): Device Under Test (DUT)
                routedInterface (Fixture<str>): test Interface name
                ipVersion (Fixture<int>): IP version
                verifyOrchagentPresence (Fixture): Make sure orchagent is running before and
                    after update takes place

            Returns:
                None
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        asichost = duthost.asic_instance(enum_frontend_asic_index)
        routedInterface = routedInterfaces[asichost.asic_index]
        self.__updateInterfaceIp(asichost, routedInterface, ipVersion, action="add")
        self.__updateNeighborIp(asichost, routedInterface, ipVersion, 0, action="add")
        self.__updateNeighborIp(asichost, routedInterface, ipVersion, 0, action="change")
        self.__updateNeighborIp(asichost, routedInterface, ipVersion, 1, action="change")

        time.sleep(2)

        yield

        self.__updateNeighborIp(asichost, routedInterface, ipVersion, 1, action="del")
        self.__updateInterfaceIp(asichost, routedInterface, ipVersion, action="remove")

    @pytest.fixture
    def arpTableMac(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname,
                    enum_frontend_asic_index, ipVersion, updateNeighborIp):
        """
            Retrieve DUT ARP table MAC entry of neighbor IP

            Args:
                duthost (AnsibleHost): Device Under Test (DUT)
                ipVersion (Fixture<int>): IP version
                updateNeighborIp (Fixture<str>): test fixture that assign/update IP/neighbor MAC

            Returns:
                arpTableMac (str): ARP MAC entry of neighbor IP
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        asichost = duthost.asic_instance(enum_frontend_asic_index)
        dutArpTable = asichost.switch_arptable()["ansible_facts"]["arptable"]
        yield dutArpTable["v{0}".format(ipVersion)][self.TEST_INTF[ipVersion]["NeighborIp"]]["macaddress"]

    @pytest.fixture
    def redisNeighborMac(self, duthosts, enum_rand_one_per_hwsku_frontend_hostname,
                         enum_frontend_asic_index, ipVersion, updateNeighborIp):
        """
            Retrieve DUT Redis MAC entry of neighbor IP

            Args:
                duthost (AnsibleHost): Device Under Test (DUT)
                ipVersion (Fixture<int>): IP version
                updateNeighborIp (Fixture<str>): test fixture that assign/update IP/neighbor MAC

            Returns:
                redisNeighborMac (str): Redis MAC entry of neighbor IP
        """
        duthost = duthosts[enum_rand_one_per_hwsku_frontend_hostname]
        asichost = duthost.asic_instance(enum_frontend_asic_index)
        redis_cmd = "{} ASIC_DB KEYS \"ASIC_STATE:SAI_OBJECT_TYPE_NEIGHBOR_ENTRY*\"".format(asichost.sonic_db_cli)

        # Sometimes it may take longer than usual to update interface address, add neighbor, and also change
        # neighbor MAC. Retry the validation of neighbor MAC to make test more robust.
        retry = 0
        maxRetry = 30
        result = None
        neighborMac = None
        expectedMac = self.TEST_MAC[ipVersion][1]
        while retry < maxRetry and neighborMac != expectedMac:
            neighborKey = None
            result = duthost.shell(redis_cmd)
            for key in result["stdout_lines"]:
                if self.TEST_INTF[ipVersion]["NeighborIp"] in key:
                    neighborKey = key
                    break

            if neighborKey:
                neighborKey = " '{}' {} ".format(
                    neighborKey,
                    REDIS_NEIGH_ENTRY_MAC_ATTR)
                result = duthost.shell("{} ASIC_DB HGET {}".format(asichost.sonic_db_cli, neighborKey))
                neighborMac = result['stdout_lines'][0].lower()

                # Since neighbor MAC is also changed/updated, check if all the updates have been processed already.
                # Stop retry if the neighbor MAC in ASIC_DB is what we expect.
                if neighborMac == expectedMac:
                    logger.info("Verified MAC of neighbor {} after {} retries".format(
                        self.TEST_INTF[ipVersion]["NeighborIp"], retry))
                    break

            logger.info("Failed to verify MAC of neighbor {}. Retry cnt: {}".format(
                self.TEST_INTF[ipVersion]["NeighborIp"], retry))
            retry += 1
            time.sleep(2)

        pytest_assert(neighborMac, "Neighbor key NOT found in Redis DB, Redis db Output '{0}'".format(result["stdout"]))
        yield neighborMac

    def testNeighborMacNoPtf(self, ipVersion, arpTableMac, redisNeighborMac):
        """
            Neighbor MAC test

            Args:
                ipVersion (Fixture<int>): IP version
                arpTableMac (Fixture<str>): ARP MAC entry of neighbor IP
                redisNeighborMac (Fixture<str>): Redis MAC entry of neighbor IP

            Returns:
                None
        """
        testMac = self.TEST_MAC[ipVersion][1]
        pytest_assert(
            arpTableMac.lower() == testMac,
            "Failed to find test MAC address '{0}' in ARP table '{1}'".format(testMac, arpTableMac)
        )

        pytest_assert(
            redisNeighborMac.lower() == testMac,
            "Failed to find test MAC address '{0}' in Redis Neighbor table '{1}'".format(testMac, redisNeighborMac)
        )
