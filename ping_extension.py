from datetime import datetime
import time
import logging
import requests
import json
import subprocess
import re

from tools_ping import Tools
import ping_success_metric

from ruxit.api.exceptions import ConfigException
from ruxit.api.base_plugin import RemoteBasePlugin

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class PingExtension(RemoteBasePlugin):
    def initialize(self, **kwargs):
        # The Dynatrace API client
        tmp_url = self.config.get("api_url")
        self.root_url = tmp_url[:-1] if tmp_url[-1] == "/" else tmp_url
        self.token = self.config.get("api_token")
        log_level = self.config.get("log_level")
        log.info(f"Log level {log_level}")
        #log.setLevel(self.config.get("log_level"))
        self.header = {
            "Authorization": "Api-TOKEN " + self.token,
            "Content-Type": "application/json",
        }

        self.tools = Tools(log, log_level, self.root_url, self.token)
        if not self.config.get("target_list"):
            raise ConfigException(f"Cannot leave target_list field empty.")
        else:
            self.target_list = self.parse_targets(self.config.get("target_list"))
            if len(self.target_list) < 1:
                raise ConfigException(f"target_list cannot be empty.")

        self.frequency = self.config.get("frequency", 1)
        self.failure_count = self.config.get("failure_count", 1)

        self.device_properties = self.config["device_porperties"]

        self.device_dict = {}
        for d in self.target_list:
            # Instead of getting one by one try with type("CUSTOM_DEVICE"),entityName.in("TEST1", "TEST2")
            hostname = d["hostname"]
            tmp = self.get_custom_device(hostname)
            if len(tmp) < 1:
                # raise ConfigException(f"Could not find device for {d}")
                log.error(f"Could not find device for {hostname}")
                raise ConfigException(f"Could not find device for {hostname}")
            # device_list.extend(tmp) ???
            self.device_dict[hostname] = tmp[0]
        # log.debug(device_dict)


        if self.tools.update_heartbeat_metric(self.device_dict):
            log.debug("Just updating ping")
            return
        ping_success_metric.update_ping_success_metric(self.tools, self.device_dict, log)

    def parse_targets(self, text):
        hostname_list = text.split(",")
        host_list = []
        for host in hostname_list:
            host_list.append({"hostname": host.strip(), "failure_count": 0})

        return host_list

    def get_custom_device(self, hostname):
        """returns json list with all CD"""

        _selctor = f'type("CUSTOM_DEVICE"),entityName("{hostname}")'
        _fields = "+properties.customProperties,+fromRelationships,+properties.dnsNames,+properties.ipAddress,+properties.detectedName"
        cd_list = self.tools.get_entities(entity_selector=_selctor, fields=_fields)
        return cd_list

    def send_error_event(self, hostname, ping_result):
        # rt = ping_result.rtt_avg
        rt = ping_result
        url = self.root_url + "/api/v2/events/ingest"
        # device_id = device['entityId']
        payload = {
            "eventType": "ERROR_EVENT",
            "title": f"Ping failed for {hostname}",
            "entitySelector": f"type(CUSTOM_DEVICE),entityName({hostname})",
            "properties": {
                "dt.event.description": f"Ping failed for {hostname}",
                "response_time": str(rt),
                # "packet_loss_rate": str(ping_result.packet_loss_rate),
                # "paclet_loss_count": str(ping_result.packet_loss_count),
            },
        }
        res = requests.post(
            url, data=json.dumps(payload), timeout=10, headers=self.header, verify=False
        )
        if res.status_code > 399:
            log.error(f"Could not send Evetn to hostname")
            log.error(res.text)
        else:
            log.debug(f"Sent event: {payload}")

    def query(self, **kwargs) -> None:

        self.tools.logger.setLevel(self.config.get("log_level"))
        group = self.topology_builder.create_group(
            identifier="IMO_Extensions",
            group_name="IMO_Extensions"
            # identifier="My_Extensions", group_name="My_Extensions"
        )
        device_name = self.activation.endpoint_name
        # properties = self.tools.parse_commands(self.device_properties)
        # logger.debug(f'Hostname {host_name}')
        device = group.create_device(identifier=device_name, display_name=device_name)
        self.tools.add_device_properties(device, self.device_properties)

        device.absolute(key="devices_pinged", value=len(self.target_list))
        today = datetime.today()
        minutes = today.minute

        if minutes % self.frequency != 0:
            log.debug("Nothing to do...")
            return

        # for target in target_list:
        for target in self.target_list:
            # frequency = int(target["frequency"])
            target_name = target["hostname"]
            log.debug(f"Starting test for {target}")

            success, response_time = self.subproc_ping(target_name)
            self.post_device_metric(self.device_dict[target_name], response_time, 1 if success else 0)

            if not success:
                target["failure_count"] += 1
                if target["failure_count"] >= self.failure_count:
                    failures = target["failure_count"]
                    log.error(f"The result was: {success}. Attempt {failures}/{self.failure_count}")
                    # self.send_error_event(target_name, ping_result)
                    self.send_error_event(target_name, response_time)
                    target["failure_count"] = 0
                success = True
        # TODO: maybe have 2 metrics, one the total amount of devices and another with succesfull/failed pings

    def get_device_template(self):
        data = {
            "properties": {},
            "series": [
                {"timeseriesId": "custom:ping", "dimensions": {}, "dataPoints": []},
                {"timeseriesId": "custom:ping_success", "dimensions": {}, "dataPoints": []},
            ],
        }
        return data

    def update_device(self, device, device_id):
        # device_id = device['displayName']
        payload = json.dumps(device)
        url = self.root_url + "/api/v1/entity/infrastructure/custom/" + device_id
        res = self.tools.make_request(url=url, method="POST", payload=payload)
        if res.status_code > 399:
            log.error(res.text)
            return
        log.debug("Ping sent to {}".format(device_id))

    def post_device_metric(self, device, ping_rt, ping_success):
        new_d = device
        old_d = self.get_device_template()
        # get group
        properties = {}
        for property in new_d["properties"]["customProperties"]:
            properties[property["key"]] = property["value"]
            # TODO: define a better key name ?
            if property["key"] == "Type" or property["key"] == "type":
                old_d["type"] = property["value"]
            if property["key"] == "Group" or property["key"] == "group":
                old_d["group"] = property["value"]
        old_d["properties"] = properties
        if "dnsNames" in new_d["properties"]:
            old_d["hostNames"] = new_d["properties"]["dnsNames"]
        if "ipAddress" in new_d["properties"]:
            old_d["ipAddresses"] = new_d["properties"]["ipAddress"]

        now = int(time.time()) * 1000
        data_point = [now, ping_rt]
        old_d["series"][0]["dataPoints"].append(data_point)
        data_point = [now, ping_success]
        old_d["series"][1]["dataPoints"].append(data_point)
        # old_d["series"][0]["dimensions"]['CUSTOM_DEVICE'] = new_d['entityId']
        # print(json.dumps(old_d))
        self.update_device(old_d, new_d["properties"]["detectedName"])

    def subproc_ping(self, host: str):
        try:
            out = subprocess.check_output(["ping", host, "-c", "1", "-W", "2"])
        except subprocess.CalledProcessError as e:
            log.error(f"Failed ping for {host}: {e}")
            return False, -1
        # log.debug(str(out))
        try:
            res = re.search("time=(.+?) ", str(out))
            avg_time = float(res.group(1))
        except Exception as e:
            log.error(f"Could not parse avg_time {e}")
            return False, -1

        return True, avg_time
