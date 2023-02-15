from datetime import datetime
import time
import logging
import yaml
import socket
import requests
import json
from tools_ping import Tools

from ruxit.api.exceptions import ConfigException
from ruxit.api.base_plugin import RemoteBasePlugin

import pingparsing

log = logging.getLogger(__name__)


class PingExtension(RemoteBasePlugin):
    def initialize(self, **kwargs):
        # The Dynatrace API client
        tmp_url = self.config.get("api_url")
        self.root_url = tmp_url[:-1] if tmp_url[-1] == "/" else tmp_url
        self.token = self.config.get("api_token")
        log_level = self.config.get("log_level")
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
        # TODO: remove ?
        self.hostname = socket.gethostname()
        log.debug(f"Hostname: {self.hostname}")

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

    def send_error_event(self, device, ping_result):
        rt = ping_result.rtt_avg
        url = self.root_url + "/api/v2/events/ingest"
        name = device["displayName"]
        # device_id = device['entityId']
        payload = {
            "eventType": "ERROR_EVENT",
            "title": f"Ping failed for {name}",
            "entitySelector": f"type(CUSTOM_DEVICE),entityName({name})",
            "properties": {
                "dt.event.description": f"Ping failed for {name}",
                "response_time": str(rt),
                "packet_loss_rate": str(ping_result.packet_loss_rate),
                "paclet_loss_count": str(ping_result.packet_loss_count),
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

        # init metric
        device_dict = {}
        for d in self.target_list:
            # Instead of getting one by one try with type("CUSTOM_DEVICE"),entityName.in("TEST1", "TEST2")
            tmp = self.get_custom_device(d["hostname"])
            if len(tmp) < 1:
                # raise ConfigException(f"Could not find device for {d}")
                log.error(f"Could not find device for {d}")
                continue
            # device_list.extend(tmp) ???
            device_dict[d["hostname"]] = tmp[0]
        log.debug(device_dict)


        log.setLevel(self.config.get("log_level"))

        # this should only happen once at the init of extension
        if self.tools.update_heartbeat_metric(device_dict):
            log.debug("Just updating ping")
            return

        today = datetime.today()
        minutes = today.minute

        if minutes % self.frequency != 0:
            log.debug("Nothing to do...")
            return

        # for target in target_list:
        for target in self.target_list:
            #frequency = int(target["frequency"])
            target_name = target["hostname"]
            log.debug(f"Starging test for {target}")


            ping_result = ping(target_name)
            log.debug(ping_result.as_dict())

            success = (
                ping_result.packet_loss_rate is not None
                and ping_result.packet_loss_rate == 0
            )

            # TODO: Report RT, as metric to device
            response_time = ping_result.rtt_avg or 0
            # TODO: rename
            self.main(device_dict[target_name], response_time)

            if not success:
                # refactor failures count
                # each target should get a failure count !!
                # self.failures_detected += 1
                # if self.failures_detected < failure_count:
                target["failure_count"] += 1
                if target["failure_count"] >= self.failure_count:
                    failures = target["failure_count"]
                    log.error(
                        f"The result was: {success}. Attempt {failures}/{self.failure_count}, not reporting yet"
                    )
                    #self.send_error_event(device, ping_result)
                    target["failure_count"] = 0
                success = True

    def get_device_template(self):
        data = {
            "properties": {},
            "series": [{"timeseriesId": "custom:ping", "dimensions": {}, "dataPoints": []}],
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

    def main(self, device, ping_rt):
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
        # old_d["series"][0]["dimensions"]['CUSTOM_DEVICE'] = new_d['entityId']
        # print(json.dumps(old_d))
        self.update_device(old_d, new_d["properties"]["detectedName"])


def ping(host: str) -> pingparsing.PingStats:
    ping_parser = pingparsing.PingParsing()
    transmitter = pingparsing.PingTransmitter()
    transmitter.destination = host
    transmitter.count = 2
    transmitter.timeout = 2000
    return ping_parser.parse(transmitter.ping())
