
import re
import struct
import base64

from spytest import st

from apis.system.basic import poll_for_system_status, get_platform_summary
from apis.system.rest import get_rest, config_rest
from apis.system.gnmi import gnmi_get

try:
    import apis.yang.codegen.messages.system as umf_sys
except ImportError:
    pass

from utilities import utils
from utilities.common import filter_and_select, dicts_list_values, make_list
from utilities.common import get_query_params


def get_system_uptime_in_seconds(dut):
    """
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :return:
    """
    command = "show uptime"
    output = st.show(dut, command)
    if output[0]["years"]:
        years = int(output[0]["years"]) * 3600 * 24 * 365.25
    else:
        years = 0
    if output[0]["months"]:
        months = int(output[0]["months"]) * 2629746
    else:
        months = 0
    if output[0]["days"]:
        days = int(output[0]["days"]) * 3600 * 24
    else:
        days = 0
    if output[0]["hours"]:
        hours = int(output[0]["hours"]) * 3600
    else:
        hours = 0
    if output[0]["minutes"]:
        minutes = int(output[0]["minutes"]) * 60
    else:
        minutes = 0
    retval = years + months + days + hours + minutes
    print(retval)
    return retval


def config_hostname(dut, name, cli_type='', **kwargs):
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if cli_type in utils.get_supported_ui_type_list():
        sys_obj = umf_sys.System(Hostname=name)
        try:
            result = sys_obj.configure(dut, cli_type=cli_type)
        except ValueError:
            return False
        if not result.ok():
            st.warn('Failed to configure hostname {}'.format(result.data))
            return False
        return True
    elif cli_type in ["rest-patch", "rest-put"]:
        rest_urls = st.get_datastore(dut, "rest_urls")
        url1 = rest_urls['config_hostname'].format(name)
        data = {
            "openconfig-system:hostname": name
        }
        return config_rest(dut, http_method=cli_type, rest_url=url1, json_data=data)
    elif cli_type == "click":
        cmd = "sudo hostname {}".format(name)
        output = st.config(dut, cmd, type=cli_type, **kwargs)
        return bool("hostname: the specified hostname is invalid" not in output)
    elif cli_type == "klish":
        cmd = "hostname {}".format(name)
        output = st.config(dut, cmd, type=cli_type, **kwargs)
        return bool("Error: Invalid input detected" not in output)


def show_interfaces_transceiver_presence(dut, intf=None):
    """
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param intf:
    :return:
    """
    command = "show interfaces transceiver presence"
    output = st.show(dut, command)
    if intf is not None:
        entries = filter_and_select(output, ["port", "presence"], {"port": intf})
    else:
        entries = filter_and_select(output, ["port", "presence"])
    return entries


def verify_interfaces_transceiver_presence(dut, intf, status):
    """
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param intf:
    :param status:
    :return:
    """
    output = show_interfaces_transceiver_presence(dut, intf)
    retval = filter_and_select(output, ["presence"], {"port": intf})
    if retval[0]["presence"].lower() == status.lower():
        return True
    else:
        return False


def get_platform_ssdhealth(dut, cli_type=''):
    """
    Author: Kanala Ramprakash Reddy (ramprakash-reddy.kanala@broadcom.com)
    Function to get the platform temperature of the device.
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if cli_type in utils.get_supported_ui_type_list("click"):
        cli_type = 'klish'

    if cli_type == 'klish':
        command = "show platform ssdhealth"
        output = st.show(dut, command, type=cli_type)
        return output
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return False


def get_platform_temperature(dut, cli_type=''):
    """
    Author: Kanala Ramprakash Reddy (ramprakash-reddy.kanala@broadcom.com)
    Function to get the platform temperature of the device.
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if cli_type in utils.get_supported_ui_type_list("click"):
        cli_type = 'klish'

    if cli_type == 'klish':
        command = "show platform temperature"
        output = st.show(dut, command, type=cli_type)
        return output
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return False


def get_platform_fan_status(dut, fan=None, cli_type=''):
    """
    To Get Platform Fan Status
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param fan:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    result = list()
    platform_name_summary = get_platform_summary(dut)
    platform_hwsku = platform_name_summary["hwsku"].lower()
    if cli_type in utils.get_supported_ui_type_list("click"):
        cli_type = 'klish'

    if cli_type == "klish":
        command = "show platform fanstatus"
        output = st.show(dut, command, type=cli_type)
        if platform_hwsku in ['dellemc-z9432f-o32', 'dellemc-Z9332f-O32', 'accton-as4630-54pe']:
            fan_mapping = {"FAN 1": "Fantray1_1", "FAN 2": "Fantray2_1", "FAN 3": "Fantray3_1"}
        else:
            fan_mapping = {"FAN 1": "Fantray1_1", "FAN 2": "Fantray1_2", "FAN 3": "Fantray2_1", "FAN 4": "Fantray2_2",
                           "FAN 5": "Fantray3_1", "FAN 6": "Fantray3_2", "FAN 7": "Fantray4_1", "FAN 8": "Fantray4_2",
                           "FAN 9": "Fantray5_1", "FAN 10": "Fantray5_2", "FAN 11": "Fantray6_1",
                           "FAN 12": "Fantray6_2"}
        for i in range(0, len(output)):
            output[i]["fan"] = fan_mapping[output[i]["fan"]]
    elif cli_type in ['rest-patch', 'rest-put']:
        rest_urls = st.get_datastore(dut, "rest_urls")
        url1 = rest_urls['get_fan_psu']
        data = get_rest(dut, rest_url=url1)
        output = _get_fan_server_info(data['output'])
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return False
    if output:
        for each in output:
            if each["status"] == "ACTIVE":
                each["status"] = "OK"
            elif each["status"] == "INACTIVE":
                each["status"] = "NOT OK"
            result.append(each)
    if fan and result:
        return filter_and_select(result, None, {"fan": fan})
    else:
        return result


def verify_platform_fan_params(dut, fan_list, cli_type=''):
    """
    To Verify platform Fan status parameters
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param fan_list:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    fans = fan_list if isinstance(fan_list, list) else [fan_list]
    output = get_platform_fan_status(dut, cli_type=cli_type)
    if not output:
        st.log("Platform fan details not found")
        return False
    cnt = 0
    for data in output:
        if data["fan"] not in fans:
            st.error("Invalid FAN detected - {}".format(data["fan"]))
            cnt += 1
        if data["status"] != "OK":
            st.error("Invalid FAN status detected - {}".format(data["status"]))
            cnt += 1
        if data["direction"] not in ["Intake", "Exhaust", "intake", "exhaust"]:
            st.error("Invalid FAN direction detected - {}".format(data["direction"]))
            cnt += 1
        if data["speed"] in ['0', 'N/A']:
            st.error("Invalid FAN speed detected - {}".format(data["speed"]))
            cnt += 1
    if cnt > 0:
        st.log("Fan parameters verification failed ..")
        return False
    return True


def verify_platform_fan_status(dut, fan, **kwargs):
    """
    To Verify Platform Fan Status
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param fan:
    :return:
    """
    cli_type = st.get_ui_type(dut, **kwargs)
    output = get_platform_fan_status(dut, fan, cli_type=cli_type)
    result = True
    for each in kwargs:
        if not filter_and_select(output, None, {each: kwargs[each]}):
            st.error("No match for {} = {} in table".format(each, kwargs[each]))
            result = False
    return result


def get_platform_psu_summary(dut, psu=None, cli_type=''):
    """
    To Get Platform PSU Status
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param psu:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    result = list()
    if cli_type in utils.get_supported_ui_type_list("click"):
        cli_type = 'klish'

    if cli_type == 'klish':
        command = "show platform psusummary"
        output = st.show(dut, command, type=cli_type)
    elif cli_type in ['rest-patch', 'rest-put']:
        rest_urls = st.get_datastore(dut, "rest_urls")
        url1 = rest_urls['get_fan_psu']
        data = get_rest(dut, rest_url=url1)
        output = _get_psu_server_info(data['output'])
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return []
    if output:
        for each in output:
            if each["psu_status"] == "ACTIVE":
                each["psu_status"] = "OK"
            elif each["psu_status"] == "INACTIVE":
                each["psu_status"] = "NOT OK"
            result.append(each)
    if psu and result:
        return filter_and_select(result, None, {"psu": psu})
    else:
        return result


def verify_platform_psu_params(dut, cli_type=''):
    """
    API to verify the Platform psu params
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    output = get_platform_psu_summary(dut, cli_type=cli_type)
    if not output:
        st.error("Output not found")
        return False
    psu_data = None
    for data in output:
        if data["psu_status"] == "OK":
            psu_data = data
            break
    if psu_data and utils.check_empty_values_in_dict(psu_data):
        st.log("PSU verification success")
        return True
    else:
        st.log("Verification failed for psu data")
        return False


def verify_platform_psu_summary(dut, psu=None, **kwargs):
    """
    To Verify Platform PSU Status
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param :dut:
    :param :fan:
    :return:
    """
    cli_type = st.get_ui_type(dut, **kwargs)
    output = get_platform_psu_summary(dut, psu, cli_type=cli_type)
    result = True
    for each in kwargs:
        if filter_and_select(output, None, {each: kwargs[each]}):
            st.error("No match for {} = {} in table".format(each, kwargs[each]))
            result = False
    return result


def config_pddf_mode(dut, file_path="/usr/local/bin/pddf_util.py", module_name="switch-pddf", iteration=150, delay=2):
    """
    API to enable / disable PDDF on the switch
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param file_path:
    :param module_name:
    :param iteration:
    :param delay:
    :return:
    """
    command = "{} {}".format(file_path, module_name)
    output = st.config(dut, command)
    st.log("OUTPUT : {}".format(output))
    if module_name == "switch-pddf":
        if 'REBOOT IS REQUIRED IMMEDIATELY' in output:
            st.reboot(dut, skip_fallback=True)
            if not poll_for_system_status(dut, iteration=iteration, delay=delay):
                st.log("System status is not up ...")
                return False
        if not is_service_active(dut):
            st.log("PDDF service is not active ...")
            return False
    else:
        if is_service_active(dut):
            st.log("PDDF service is still active ...")
            return False
    return True


def is_service_active(dut, service="pddf"):
    """
    API to check whether service is active or not
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param service:
    :return:
    """
    command = "systemctl | grep -i {}".format(service)
    output = st.config(dut, command)
    if "active" not in output:
        return False
    return True


def get_psuutil_data(dut, mode="status", cli_type=""):
    """
    API to get psuutil data based on type of the command
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param mode:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if mode not in ["status", "numpsus", "version"]:
        st.log("Unsupported command type")
        return False
    if cli_type == "click":
        command = "sudo psuutil {}".format(mode)
        skip_tmpl = False
        if mode == "numpsus":
            skip_tmpl = True
        output = st.show(dut, command, skip_tmpl=skip_tmpl)
        if mode == "numpsus":
            return {"numpsus": utils.remove_last_line_from_string(output)}
        else:
            return output
    elif cli_type in ["klish", "rest-patch", "rest-put"] + utils.get_supported_ui_type_list():
        if mode == "numpsus":
            return {"numpsus": str(len(get_platform_psu_summary(dut, cli_type=cli_type)))}
        output = get_platform_psu_summary(dut, cli_type=cli_type)
        for i in range(0, len(output)):
            output[i]["psu"] = output[i]["psu"].replace(" ", "")
            output[i]["status"] = output[i]["psu_status"]
        return output
    else:
        st.error("Unsupported CLI Type provided: {}".format(cli_type))
        return []


def verify_psuutil_data(dut, *argv, **kwargs):
    """
    API to get psuutil data based on type of the command
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param argv:
    :param kwargs:
    :return:
    """
    result = True
    for each_mode in argv:
        output = get_psuutil_data(dut, each_mode)
        if "numpsus" in each_mode and int(output['numpsus']) != len(kwargs['psu_list']):
            st.error("Incorrect Number of PSUs detected.")
            result = False

        if "status" in each_mode:
            psu_li = dicts_list_values(output, "psu")
            for psu in kwargs['psu_list']:
                if psu not in psu_li:
                    st.error("PSU - {} is not present in DUT.".format(psu))
                    result = False

            status_li = dicts_list_values(output, "status")
            for status in status_li:
                if status not in ['NOT OK', 'OK']:
                    st.error("Invalid PSU status in DUT.")
                    result = False

            if "OK" not in status_li:
                st.error("None of the PSU status is - OK")
                result = False

    return result


def config_sfputil(dut, **kwargs):
    """
    API to config sfputils
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param kwargs:
    :return:
    """
    if kwargs.get("mode"):
        mode = kwargs.get("mode")
        if mode in ["lpmode", "reset"]:
            if not kwargs.get("interface"):
                st.log("Interface should be provided for {}".format(mode))
                return False
        if mode == "lpmode":
            if not kwargs.get("action"):
                st.log("Action should be provided for {}".format(mode))
                return False
            if kwargs.get("action") not in ["on", "off"]:
                st.log("Unsupported actions provided for {}".format(mode))
                return False
            command = "sudo sfputil {} {} {}".format(mode, kwargs.get("action"), kwargs.get("interface"))
            output = st.config(dut, command)
            if "OK" in output:
                return True
            else:
                return False
        elif mode == "reset":
            command = "sudo sfputil {} {}".format(mode, kwargs.get("interface"))
            output = st.config(dut, command)
            if "OK" in output:
                return True
            else:
                return False
        else:
            st.log("Unsupported modes provided")
            return False
    else:
        st.log("MODE NOT PROVIDED ..")
        return False


def show_sfputil(dut, mode, interface=None, cli_type=""):
    """
    API to get the sfputil output
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param interface:
    :param mode: eeprom, presence, lpmode
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if mode not in ["lpmode", "presence", "eeprom"]:
        st.log("Unsupported mode provided")
        return False
    cli_type = "click" if mode == "lpmode" else cli_type
    if cli_type == "click":
        command = "sudo sfputil show {}".format(mode)
        if interface:
            command = "sudo sfputil show {} | grep -w {}".format(mode, interface)
        output = st.show(dut, command)
    elif cli_type in ["klish", "rest-patch", "rest-put"] + utils.get_supported_ui_type_list():
        output = show_interface_transceiver(dut, mode, interface, cli_type)
    else:
        st.error("Unsupported CLI Type provided: {}".format(cli_type))
        return []
    return output


def verify_sfputil_show_interface_tranceiver(dut, mode, **kwargs):
    """
    To Verify sfputil
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param mode:
    :param kwargs:
    :return:
    """
    cmd = 'utils'
    if 'cmd' in kwargs:
        cmd = kwargs['cmd']
        kwargs.pop('cmd')
    if cmd == 'utils':
        output = show_sfputil(dut, mode, interface=kwargs.get('port'))
    else:
        output = show_interface_transceiver(dut, mode, interface=kwargs.get('port'))
    result = True
    for each in kwargs:
        if not filter_and_select(output, None, {each: kwargs[each]}):
            st.error("No match for {} = {} in table".format(each, kwargs[each]))
            result = False
    return result


def show_interface_transceiver(dut, mode, interface=None, cli_type=""):
    """
    API to get the interface transceiver eeprom details
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param mode: eeprom , presence
    :param interface:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = 'klish' if cli_type in utils.get_supported_ui_type_list() else cli_type
    if mode not in ["eeprom", "presence"]:
        st.log("Unsupported modes provided ...")
        return False
    if cli_type == "click":
        command = "show interface transceiver {}".format(mode)
        if interface:
            command = "show interface transceiver {} | grep -w {}".format(mode, interface)
        return st.show(dut, command)
    elif cli_type == "klish":
        if interface:
            intf_data = utils.get_interface_number_from_name(interface)
            command = "show interface transceiver {} {}".format(intf_data['type'], intf_data['number'])
        else:
            command = "show interface transceiver"
        output = st.show(dut, command, type=cli_type)
        for i in range(len(output)):
            if output[i]['presence'] == "PRESENT":
                output[i]['presence'] = "Present"
                output[i]['eeprom_status'] = "SFP EEPROM detected"
            else:
                output[i]['presence'] = "Not present"
                output[i]['eeprom_status'] = "SFP EEPROM Not detected"
    elif cli_type in ["rest-patch", "rest-put"]:
        rest_urls = st.get_datastore(dut, "rest_urls")
        url1 = rest_urls['get_fan_psu']
        data = get_rest(dut, rest_url=url1)["output"]
        output = _get_transceiver_data(data)
        if interface:
            output = filter_and_select(output, match={"port": interface})
    else:
        st.error("Unsupported CLI Type provided: {}".format(cli_type))
        return []
    return output


def show_pddf_psuutils(dut, mode, cli_type=""):
    """
    API to get PDDF PSUUTIL DATA based on type of mode
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param mode:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if mode not in ["numpsus", "status", "mfrinfo", "seninfo", "version"]:
        st.log("Unsupported modes provided ")
        return False
    if cli_type == "click":
        skip_tmpl = False
        if mode == "numpsus":
            skip_tmpl = True
        command = "sudo pddf_psuutil {}".format(mode)
        output = st.show(dut, command, skip_tmpl=skip_tmpl)
        if mode == "numpsus":
            return {"numpsus": utils.remove_last_line_from_string(output)}
        else:
            return output
    elif cli_type in ["click", "klish", "rest-patch"] + utils.get_supported_ui_type_list():
        if mode in ["numpsus", "status", "version"]:
            return get_psuutil_data(dut, mode, cli_type)
        else:
            return get_platform_psu_summary(dut, cli_type=cli_type)
    else:
        st.error("Unsupported CLI Type provided: {}".format(cli_type))
        return []


def verify_pddf_psuutils(dut, *argv, **kwargs):
    """
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param argv:
    :return:
    """
    result = True
    for each_mode in argv:
        output = show_pddf_psuutils(dut, each_mode)
        if "numpsus" in each_mode and int(output['numpsus']) != len(kwargs['psu_list']):
            st.error("Incorrect Number of PSUs detected.")
            result = False

        if "status" in each_mode:
            psu_li = dicts_list_values(output, "psu")
            for psu in kwargs['psu_list']:
                if psu not in psu_li:
                    st.error("PSU - {} is not present in DUT.")
                    result = False

            status_li = dicts_list_values(output, "status")
            for status in status_li:
                if status not in ['NOT OK', 'OK']:
                    st.error("Invalid PSU status in DUT.")
                    result = False

            if "OK" not in status_li:
                st.error("None of the PSU status is - OK")
                result = False

        if "mfrinfo" in each_mode:
            status_li = dicts_list_values(output, "psu_status")
            if "OK" not in status_li:
                st.error("None of the PSU status is - OK")
                result = False

        if 'seninfo' in each_mode:
            status_li = dicts_list_values(output, "psu_status")
            if "OK" not in status_li:
                st.error("None of the PSU status is - OK")
                result = False
            for each in ['voltage', 'current', 'power']:
                if '0.0' in dicts_list_values(output, "each"):
                    st.error("{} in 'seninfo' is 0.0".format(each))
                    result = False
            if '0' in dicts_list_values(output, "fan_speed"):
                st.error("fan_speed in 'seninfo' is 0.0")
                result = False

    return result


def show_pddf_fanutil(dut, mode, cli_type=""):
    """
    API to get PDDF FANUTIL DATA based on type of mode
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param mode:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "click" if mode == "version" else cli_type
    if cli_type == "click":
        if mode not in ["direction", "getspeed", "numfans", "status", "version"]:
            st.log("Unsupported modes provided ")
            return False
        skip_tmpl = False
        if mode == "numfans":
            skip_tmpl = True
        command = "sudo pddf_fanutil {}".format(mode)
        output = st.show(dut, command, skip_tmpl=skip_tmpl)
        if mode == "numfans":
            return {"numfans": utils.remove_last_line_from_string(output)}
        else:
            return output
    elif cli_type in ["klish", "rest-patch", "rest-put"] + utils.get_supported_ui_type_list():
        if mode == "numfans":
            return {"numfans": str(len(get_platform_fan_status(dut, cli_type=cli_type)))}
        return get_platform_fan_status(dut, cli_type=cli_type)
    else:
        st.error("Unsupported CLI Type provided: {}".format(cli_type))
        return []


def verify_pddf_fanutil(dut, mode, fan_list, version="2.0"):
    """
    API to verify the fan util output for the given fan list
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param mode:
    :param fan_list:
    :param version:
    :return:
    """
    fans = fan_list if isinstance(fan_list, list) else [fan_list]
    output = show_pddf_fanutil(dut, mode)
    if not output:
        st.error("PDDF FAN UTIL DATA NOT FOUND")
        return False
    for data in output:
        count = 0
        for fan in fans:
            if mode == "direction":
                if fan == data["fan"].upper() and data["direction"].upper() not in ["INTAKE", "EXHAUST"]:
                    st.error("Invalid FAN direction detected - {}".format(data["direction"]))
                    count += 1
            elif mode == "getspeed":
                if fan == data["fan"] and int(data["speed"]) == 0:
                    st.error("Invalid FAN speed detected - {}".format(data["speed"]))
                    count += 1
            elif mode == "numfans":
                if str(len(fan_list)) != str(output[data]):
                    st.error("Incorrect FAN numbers detected - {}".format(output[data]))
                    count += 1
            elif mode == "status":
                if fan == data["fan"] and data["status"] != "OK":
                    st.error("Invalid FAN status detected - {}".format(data["status"]))
                    count += 1
            elif mode == "version":
                if str(data["version"]) != str(version):
                    st.error("Invalid FAN version detected - {}".format(data["version"]))
                    count += 1
        if count:
            st.error("Mismatch in PDDF FAN UTIL data")
            return False
    return True


def config_pddf_fanutil(dut, speed):
    """
    API to set PDDF FANUTIL speed
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param speed:
    :return:
    """
    command = "sudo pddf_fanutil setspeed {}".format(speed)
    output = st.config(dut, command)
    if "Successful" not in utils.remove_last_line_from_string(output):
        st.log("Configuration of fan speed failed")
        return False
    return True


def run_debug_commands(dut, mode=None, module="pddf"):
    """
    API to execute debug commands
    Author: Chaitanya Vella (chaitanya-vella.kumar@broadcom.com)
    :param dut:
    :param mode:
    :param module:
    :return:
    """
    if mode:
        modes = make_list(mode)
    else:
        modes = ["lsmod", "systemctl", "pddf_fanutil", "pddf_psuutil"]
    for each_mode in modes:
        if each_mode in ["lsmod", "systemctl"]:
            command = "{} | grep -i {}".format(each_mode, module)
        if each_mode in ["pddf_fanutil", "pddf_psuutil"]:
            command = "sudo {} debug dump-sysfs".format(each_mode)
        output = st.config(dut, command)
    return utils.remove_last_line_from_string(output)


def generate_tech_support(dut, **kwargs):
    """
    To Generate tech support and return the error if occurs.
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    """
    skip_error_check = kwargs.get("skip_error_check", False)
    command = "show techsupport > /dev/null"
    return utils.remove_last_line_from_string(st.config(dut, command, max_time=600, skip_error_check=skip_error_check))


def verify_show_environment(dut, verify_str_list):
    """
    To get show environment.
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    """
    command = "show environment"
    fan_mapping = {"Fantray1_1": "FAN 1", "Fantray1_2": "FAN 2", "Fantray2_1": "FAN 3", "Fantray2_2": "FAN 4",
                   "Fantray3_1": "FAN 5", "Fantray3_2": "FAN 6", "Fantray4_1": "FAN 7", "Fantray4_2": "FAN 8",
                   "Fantray5_1": "FAN 9", "Fantray5_2": "FAN 10", "Fantray6_1": "FAN 11", "Fantray6_2": "FAN 12"}
    output = utils.remove_last_line_from_string(st.show(dut, command, skip_tmpl=True))
    result = True
    for item in verify_str_list:
        if item in fan_mapping:
            if not (re.findall(item, output, re.IGNORECASE) or re.findall(fan_mapping[item], output, re.IGNORECASE)):
                st.error("Item '{}' is NOT found".format(item))
                result = False
        else:
            if not re.findall(item, output, re.IGNORECASE):
                st.error("Item '{}' is NOT found".format(item))
                result = False
    return result


def config_pddf_ledutil(dut, mode, led_type, state=None):
    """
    API to set PDDF LEDUTIL
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param mode:
    :param led_type:
    :param state:
    :return:
    """
    command = "sudo pddf_ledutil getstatusled {}".format(led_type)
    if mode.lower() == 'set':
        command = "sudo pddf_ledutil setstatusled {} {}".format(led_type, state)
    output = st.config(dut, command)
    return utils.remove_last_line_from_string(output)


def verify_pddf_ledutil(dut, data):
    """
    Verify PDDF LEDUTIL
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param data:
    :return:
    """
    result = True
    for each_led in data:
        st.banner("Validating - {} ".format(each_led))
        for each_test in data[each_led]:
            st.log("Validating - {} - mode '{}'".format(each_led, each_test))
            set_out = config_pddf_ledutil(dut, 'set', each_led, data[each_led][each_test][0])
            if data[each_led][each_test][1] not in set_out:
                st.error(">>>> {} != {}".format(set_out, data[each_led][each_test][1]))
                st.error("Failed to SET - {} mode '{}'".format(each_led, each_test))
                result = False
            get_out = config_pddf_ledutil(dut, 'get', each_led)
            if get_out != data[each_led][each_test][2]:
                st.error(">>>> {} != {}".format(get_out, data[each_led][each_test][2]))
                st.error("Get Validation failed - {} mode '{}'".format(each_led, each_test))
                result = False
    return result


def show_pddf_thermalutil(dut, mode):
    """
    API to get PDDF thermal util DATA based on type of mode
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param mode:
    :return:
    """
    if mode not in ["gettemp", "numthermals", "version"]:
        st.log("Unsupported modes provided ")
        return False
    skip_tmpl = False
    if mode in ["numthermals", 'version']:
        skip_tmpl = True
    command = "sudo pddf_thermalutil {}".format(mode)
    output = st.show(dut, command, skip_tmpl=skip_tmpl)
    if mode == "numthermals":
        return {"numthermals": utils.remove_last_line_from_string(output)}
    elif mode == "version":
        return {"version": utils.remove_last_line_from_string(output)}
    else:
        return output


def verify_pddf_thermalutil(dut, mode, thermal_list, version="2.0"):
    """
    API to verify the thermal util output for the given thermal list
    Author: Prudvi Mangadu (prudvi.mangadu@broadcom.com)
    :param dut:
    :param mode:
    :param thermal_list:
    :param version:
    :return:
    """
    thermal_li = thermal_list if isinstance(thermal_list, list) else [thermal_list]
    output = show_pddf_thermalutil(dut, mode)
    if not output:
        st.error("PDDF THERMAL UTIL DATA NOT FOUND")
        return False
    count = 0
    if mode == "gettemp":
        for data in output:
            if data["temp_sensor"] not in thermal_li:
                st.error("Invalid Temp Sensor detected - {}".format(data["temp_sensor"]))
                count += 1
                break
    elif mode == "numthermals":
        for data in output:
            if int(len(thermal_list)) != int(output[data]):
                st.error("Incorrect Thermal sensors numbers detected - {}".format(output[data]))
                count += 1
                break
    elif mode == "version":
        for data in output:
            if str(version) not in str(output[data]):
                st.error("Invalid Thermal version detected - {}".format(data["version"]))
                count += 1
                break
    if count:
        st.error("Mismatch in PDDF Thermal UTIL data")
        return False

    return True


def _get_fan_server_info(data):
    ret_val = []
    for fan in data["openconfig-platform:components"]["component"]:
        if "FAN".lower() in fan["name"].lower():
            temp = {}
            temp["direction"] = fan["fan"]["state"]["openconfig-platform-fan:direction"]
            temp["speed"] = fan["fan"]["state"]["openconfig-platform-fan:speed"]
            temp["fan"] = fan["state"]["name"]
            temp["status"] = fan["state"]["oper-status"].split(":")[1]
            ret_val.append(temp)
            st.debug(ret_val)
    return ret_val


def _get_psu_server_info(data):
    ret_val = []
    for name in data["openconfig-platform:components"]["component"]:
        if "PSU".lower() in name["name"].lower():
            temp = {}
            temp['psu'] = name["name"]
            temp['psu_status'] = name['state']['oper-status'].split(":")[1]
            if temp['psu_status'] == "ACTIVE":
                temp['output_current'] = name['power-supply']['state']['openconfig-platform-psu:output-current']
                temp['output_power'] = name['power-supply']['state']['openconfig-platform-psu:output-power']
                temp['output_voltage'] = name['power-supply']['state']['openconfig-platform-psu:output-voltage']
                temp['model'] = name['state']['description']
                temp['manufacturer_id'] = name['state']['mfg-name']
                temp['empty'] = name['state']['empty']
                temp['serial_number'] = name['state']['serial-no']
                for each in ['output_current', 'output_power', 'output_voltage']:
                    temp[each] = struct.unpack('>f', base64.b64decode(temp[each]))[0]
            ret_val.append(temp)
            st.debug(ret_val)
    return ret_val


def _get_transceiver_data(data):
    ret_val = []
    for name in data["openconfig-platform:components"]["component"]:
        if "Eth" in name["name"]:
            temp = {}
            temp["port"] = name["name"]
            try:
                if name["openconfig-platform-transceiver:transceiver"]["state"]["present"] == "PRESENT":
                    temp["presence"] = "Present"
                    temp["eeprom_status"] = "SFP EEPROM detected"
            except Exception:
                temp["presence"] = "Not Present"
                temp["eeprom_status"] = "SFP EEPROM Not detected"
            ret_val.append(temp)
    return ret_val


def hw_watchdog_config(dut, mode=None, cli_type=""):
    """
    :param dut:
    :param mode:
    :param config:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "click"
    if mode == 'reset':
        cmd = "watchdogutil pause"
    elif mode == "enable":
        cmd = "watchdogutil arm"
    elif mode == "disable":
        cmd = "watchdogutil disarm"
    elif mode == "status":
        cmd = "watchdogutil status"
    elif mode == "timeout":
        cmd = "watchdogutil timeout"
    elif mode == "running_status":
        cmd = "systemctl status watchdog-control"
    elif mode == "kdump":
        cmd = "bash -c 'echo c>/proc/sysrq-trigger'"
        st.config(dut, cmd, expect_reboot=True, type=cli_type)
        st.config(dut, 'rm -rf /var/crash/20*')
        return True
    else:
        st.log("Provide supported mode")
        return False
    st.config(dut, cmd)
    return True


def hw_watchdog_timeout_config(dut, timeout_value=None, cli_type=""):
    """
    :param dut:
    :param timeout_value:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "click"
    cmd = "watchdogutil  arm -s {}".format(timeout_value)
    st.config(dut, cmd, type=cli_type)
    return True


def hw_watch_service_isactive(dut, cli_type=""):
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "click"
    cmd = "systemctl is-active watchdog-control.service"
    out = st.show(dut, cmd, skip_tmpl=True, type=cli_type)
    return out


def hw_watchdog_start_service(dut, cli_type=""):
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "click"
    cmd = "systemctl start watchdog-control.service"
    out = st.config(dut, cmd, type=cli_type)
    return out


def hw_watchdog_stop_service(dut, cli_type=""):
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "click"
    cmd = "systemctl stop watchdog-control.service"
    st.config(dut, cmd, type=cli_type)
    return True


def trigger_kernel_crash(dut):
    st.config(dut, 'echo 1 | sudo tee /proc/sys/kernel/sysrq')
    st.config(dut, 'echo c | sudo tee /proc/sysrq-trigger', expect_ipchange=True, expect_reboot=True, skip_error_check=True)
    return True


def show_interface_transceiver_summary(dut, interface="", cli_type=""):
    """
    API to get the interface transceiver details
    Author: Praveen Kumar Kota (praveenkumar.kota@broadcom.com)
    :param dut:
    :param interface:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    cli_type = "klish" if cli_type in ['rest-patch', 'rest-put'] + utils.get_supported_ui_type_list() else cli_type
    if cli_type == "click":
        if interface:
            command = "show interfaces transceiver summary | grep -w {}".format(interface)
        else:
            command = "show interfaces transceiver summary"
        return st.show(dut, command)
    elif cli_type == "klish":
        if interface:
            intf_data = utils.get_interface_number_from_name(interface)
            command = "show interface transceiver {} {} summary".format(intf_data['type'], intf_data['number'])
        else:
            command = "show interface transceiver summary"
        return st.show(dut, command, type=cli_type)
    else:
        st.error("Unsupported CLI Type provided: {}".format(cli_type))
        return []


def verify_cusfp_port(dut, intf):
    """
    Author: Praveen Kumar Kota (praveenkumar.kota@broadcom.com)
    :param dut:
    :param intf:
    :return:
    """
    output = show_interface_transceiver_summary(dut, intf)
    if "SFP" in output[0]['media_type'] and "BASE-T" in output[0]['media_name']:
        st.banner("port {} is a CuSFP port it will take time to come up".format(intf))
    else:
        st.banner("it is a non CuSFP port")
    return True


def get_last_config_time(dut, cli_type=''):
    """
    Function to get last configuration change timestamp
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, cli_type=cli_type)
    if cli_type == "klish":
        command = "show system config-update-time"
        output = utils.remove_last_line_from_string(st.show(dut, command, type=cli_type, skip_tmpl=True))
        if output.lower() == "not available":
            result = 0
        else:
            result = utils.convert_to_timestamp(output)
    elif cli_type in ["rest-put", "rest-patch"]:
        rest_url = st.get_datastore(dut, "rest_urls")["last_config_time"]
        resp = get_rest(dut, rest_url=rest_url)
        if "output" not in resp:
            st.error("Unexpected REST response")
            result = False
        else:
            result = resp["output"]
    elif cli_type == "gnmi":
        gnmi_url = "/openconfig-system:system/state/"
        result = gnmi_get(dut=dut, xpath=gnmi_url)
    else:
        st.error("Unsupported CLI TYPE {}".format(cli_type))
        return False
    return result


def get_device_name_by_sensor_data(output, temp_sensors):
    device_sensors = []
    for each in output:
        device_sensors.append(each.get('sensor'))
    st.log(device_sensors)

    for p_data in temp_sensors:
        for device, sensors in p_data.items():
            data = set(device_sensors).intersection(sensors)
            if len(data) == len(sensors):
                return device
    return None


def show_system_cpu(dut, **kwargs):
    """
    API to get cpu stats
    Author : Nagarjuna Suravarapu (nagarjuna.survarapu@broadcom.com)
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, **kwargs)
    yang_data_type = kwargs.get("yang_data_type", "ALL")
    if cli_type in utils.get_supported_ui_type_list():
        sys_obj = umf_sys.System()
        query_params_obj = get_query_params(yang_data_type=yang_data_type, cli_type=cli_type)
        out = sys_obj.get_payload(dut, query_param=query_params_obj, cli_type=cli_type)
        if not out.ok():
            st.log("test_step_failed: cpu stats output is not showing")
        output = process_cpu_output(out.payload)
    elif cli_type == 'klish':
        cmd = 'show system cpu'
        output = st.show(dut, cmd, type=cli_type)
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return []
    return output


def show_system_memory(dut, **kwargs):
    """
    API to get memory stats
    Author : Nagarjuna Suravarapu (nagarjuna.survarapu@broadcom.com)
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, **kwargs)
    yang_data_type = kwargs.get("yang_data_type", "ALL")
    cli_type = 'klish'
    if cli_type in utils.get_supported_ui_type_list():
        # TBD
        sys_obj = umf_sys.System()
        query_params_obj = get_query_params(yang_data_type=yang_data_type, cli_type=cli_type)
        out = sys_obj.get_payload(dut, query_param=query_params_obj, cli_type=cli_type)
        if not out.ok():
            st.log("test_step_failed: cpu stats output is not showing")
        output = process_cpu_output(out.payload)
    elif cli_type == 'klish':
        cmd = 'show system memory'
        output = st.show(dut, cmd, type=cli_type)
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return []
    return output


def config_system_resource_polling_interval(dut, poll_interval, **kwargs):
    """
    API to configure/unconfigure cpu polling interval
    Author : Nagarjuna Suravarapu (nagarjuna.survarapu@broadcom.com)
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, **kwargs)
    config = kwargs.get('config', True)
    if cli_type in utils.get_supported_ui_type_list() + ['klish']:
        sys_obj = umf_sys.System(ResourceStatsPollingInterval=poll_interval)
        if config:
            resp = sys_obj.configure(dut, cli_type=cli_type)
        else:
            resp = sys_obj.unConfigure(dut, target_path="config/openconfig-system-deviation:resource-stats-polling-interval", cli_type=cli_type)
        if not resp.ok():
            st.log('test_step_failed: Cpu polling interval operation failed {}'.format(resp.data))
            return False
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return False
    return True


def process_cpu_output(data):
    """
    Api to process the gnmi/rest output
    :param payload:
    :return:
    """
    retval = []
    if data.get("openconfig-system:system") and isinstance(data["openconfig-system:system"], dict):
        i2c_info = data["openconfig-system:system"]['cpus']['cpu']
    else:
        return False
    for output in i2c_info:
        temp = dict()
        if isinstance(output, dict) and output.get("state") and isinstance(output["state"], dict):
            temp['cpu'] = str(output['index']) if output['index'] != 0 else 'ALL'
            temp['idle'] = str(output['state']['idle']['avg'])
            temp['kernel'] = str(output['state']['kernel']['avg'])
            temp['user'] = str(output['state']['user']['avg'])
            temp['poll_interval'] = str(int(output['state']['idle']['interval']) / 10**9)
            retval.append(temp)
    st.debug(retval)
    return retval


def retry_poll_config(dut, current_poll, configured_poll):
    i = 1
    while True:
        output = show_system_cpu(dut)
        if int(output[0]['poll_interval'].split('.')[0]) == int(configured_poll):
            st.log("changes for configured poll {} are in active".format(configured_poll))
            return True
        st.wait(1, "wait for 1 sec to retry again")
        if i > int(current_poll):
            st.log("Max iterations {} reached".format(i))
            return False
        i += 1


def get_system_up_time(dut, **kwargs):
    """
    Function to get system up time
    :param dut:
    :return:
    """
    cli_type = st.get_ui_type(dut, **kwargs)
    yang_data_type = kwargs.get("yang_data_type", "ALL")
    if cli_type in utils.get_supported_ui_type_list():
        sys_obj = umf_sys.System()
        query_params_obj = get_query_params(yang_data_type=yang_data_type, cli_type=cli_type)
        out = sys_obj.get_payload(dut, query_param=query_params_obj, cli_type=cli_type)
        if not out.ok():
            st.log("test_step_failed: System Uptime output is not showing")
        output = process_system_uptime_output(out.payload)
    elif cli_type in ['klish', 'click']:
        cmd = 'show uptime'
        output = st.show(dut, cmd, type=cli_type)
    else:
        st.error("UNSUPPORTED CLI-TYPE: {}").format(cli_type)
        return []
    return output


def verify_uptime(dut):
    """
        API to verfiy klish and click uptime and return True or False

    """
    uptime1 = get_system_up_time(dut, cli_type="klish")
    uptime2 = get_system_up_time(dut, cli_type="click")
    for i in uptime1[0].keys():
        if uptime1[0][i] not in ['0', '']:
            if not uptime1[0][i] == uptime2[0][i]:
                st.log("Uptime is not matched: {}".format(i))
                return False
    st.log("Uptime is matched")
    return True


def process_system_uptime_output(uptime):
    if uptime and uptime.get('openconfig-system:system'):
        if isinstance(uptime.get('openconfig-system:system').get('openconfig-system-ext:infra'), dict):
            output = uptime['openconfig-system:system']['openconfig-system-ext:infra']['state']['uptime']
            pattern = r'((\d+\s+)(years|year))?(,\s+)?((\d+\s+)(weeks|week))?(,\s+)?((\d+\s+)(days|day))?(,\s+)?((\d+\s+)(hours|hour))?(,\s+)?((\d+\s+)(minutes|minute))?'
            match = re.search(pattern, output)
            if match:
                out = dict()
                out['years'] = match.group(2)
                out['weeks'] = match.group(6)
                out['days'] = match.group(10)
                out['hours'] = match.group(14)
                out['minutes'] = match.group(18)
            return out
        else:
            st.error("uptime output is not showing correctly")
    else:
        st.error("uptime output is not showing correctly")
