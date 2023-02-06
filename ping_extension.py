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
        self.proxies = self.build_proxy_url()
        self.executions = 0
        self.failures_detected = 0
        self.tools = Tools(log, log_level, self.root_url, self.token)
        if not self.config.get("target_list"):
            raise ConfigException(f"Cannot leave target_list field empty.")
        else:
            self.target_list = self.parse_targets(self.config.get("target_list"))
            if len(self.target_list["target_list"]) < 1:
                raise ConfigException(f"target_list cannot be empty.")
        self.hostname = socket.gethostname()
        log.debug(f"Hostname: {self.hostname}")



    def build_proxy_url(self):
        proxy_address = self.config.get("proxy_address")
        proxy_username = self.config.get("proxy_username")
        proxy_password = self.config.get("proxy_password")

        if proxy_address:
            protocol, address = proxy_address.split("://")
            proxy_url = f"{protocol}://"
            if proxy_username:
                proxy_url += proxy_username
            if proxy_password:
                proxy_url += f":{proxy_password}"
            proxy_url += f"@{address}"
            return {"https": proxy_url}

        return {}

    def parse_targets(self, text):
        try:
            dct = yaml.safe_load(text)
        except Exception as e:
            error = f"Could not parse cmd config: {e}"
            log.error(error)
            exit(-1)

        # self.logger.debug(dct)
        return dct

    def get_custom_device(self, hostname):
        """returns json list with all CD"""

        _selctor = f'type("CUSTOM_DEVICE"),entityName("{hostname}")'
        _fields = "+properties.customProperties,+fromRelationships,+properties.dnsNames,+properties.ipAddress,+properties.detectedName"
        cd_list = self.tools.get_entities(entity_selector=_selctor, fields=_fields)
        return cd_list

    def send_error_event(self, device, ping_result):
        rt = ping_result.rtt_avg
        url = self.root_url + '/api/v2/events/ingest'
        name = device['displayName']
        #device_id = device['entityId']
        payload = {
            "eventType": "ERROR_EVENT",
            "title": f"Ping failed for {name}",
            "entitySelector": f"type(CUSTOM_DEVICE),entityName({name})",
            "properties": {
                "dt.event.description": f"Ping failed for {name}",
                "response_time": str(rt),
                "packet_loss_rate": str(ping_result.packet_loss_rate),
                "paclet_loss_count": str(ping_result.packet_loss_count),
            }
        }
        res = requests.post(url, data=json.dumps(payload), timeout=10, headers=self.header, verify=False)
        if res.status_code > 399:
            log.error(f"Could not send Evetn to hostname")
            log.error(res.text)
        else:
            log.debug(f"Sent event: {payload}")

    def query(self, **kwargs) -> None:

        # init metric
        self.device_names = [t["target"] for t in self.target_list["target_list"]]
        log.debug(self.device_names)
        device_list = []
        for d in self.device_names:
            tmp = self.get_custom_device(d)
            if len(tmp) < 1:
                #raise ConfigException(f"Could not find device for {d}")
                log.error(f"Could not find device for {d}")
                continue
            # device_list.extend(tmp) ???
            for t in tmp:
                device_list.append(t)
        log.debug(device_list)
        log.setLevel(self.config.get("log_level"))

        # this should only happen once at the init of extension
        if self.tools.update_heartbeat_metric(device_list):
            log.debug("Just updating ping")
            return
        # target = self.config.get("test_target")
        # target_list = self.config.get("test_target").split(",")

        failure_count = self.config.get("failure_count", 1)
        # TODO: location should be hostname

        # frequency = int(self.config.get("frequency")) if self.config.get("frequency") else 15

        today = datetime.today()
        minutes = today.minute

        # for target in target_list:
        for target in self.target_list["target_list"]:
            frequency = int(target["frequency"])
            target_name = target["target"]
            log.debug(f"Starging test for {target}")

            # TODO: better handling of frequncy
            if minutes % frequency == 0:
                #device_list = self.get_custom_device(target)
                # should always be just one 1
                for device in device_list:
                    if device["displayName"] != target_name:
                        continue
                    ping_result = ping(target_name)
                    log.debug(ping_result.as_dict())

                    success = (
                        ping_result.packet_loss_rate is not None
                        and ping_result.packet_loss_rate == 0
                    )

                    # TODO: Report RT, as metric to device
                    response_time = ping_result.rtt_avg or 0
                    # TODO: rename
                    self.main(device, response_time)

                    if not success:
                        # refactor failures count
                        # each target should get a failure count !!
                        #self.failures_detected += 1
                        #if self.failures_detected < failure_count:
                        log.error(
                            f"The result was: {success}. Attempt {self.failures_detected}/{failure_count}, not reporting yet"
                        )
                        log.debug(device)
                        self.send_error_event(device, ping_result)
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
