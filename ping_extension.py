from datetime import datetime
import logging
import socket
from tools_ping import Tools

from ruxit.api.exceptions import ConfigException
from ruxit.api.base_plugin import RemoteBasePlugin

import pingparsing

log = logging.getLogger(__name__)


class PingExtension(RemoteBasePlugin):
    def initialize(self, **kwargs):
        # The Dynatrace API client
        log_level = self.config.get("log_level")

        self.tools = Tools(log, log_level, "", "")
        if not self.config.get("target_list"):
            raise ConfigException(f"Cannot leave target_list field empty.")
        else:
            self.target_list = self.parse_targets(self.config.get("target_list"))
            if len(self.target_list) < 1:
                raise ConfigException(f"target_list cannot be empty.")

        self.frequency = self.config.get("frequency")
        if not self.frequency or self.frequency <= 0:
            raise ConfigException(f"Invalid value for frequency {self.frequency}")

        self.device_properties = self.config["device_properties"]

        self.ping_parser = pingparsing.PingParsing()
        self.transmitter = pingparsing.PingTransmitter()
        self.transmitter.count = 2
        self.transmitter.timeout = 2000

        # TODO: this needed ?
        self.hostname = socket.gethostname()
        log.debug(f"Hostname: {self.hostname}")

    def parse_targets(self, text):
        # TODO: return [{"target_name": "foo.com","failure_count":0}]
        target_list = []
        target_names = text.strip()
        for target in target_names.split(","):
            tmp = {"target_name": "","failure_count":0}
            tmp["target_name"] = target
            target_list.append(tmp)
        return target_list


    def send_availability_event(self, device, msg):
        device.report_availability_event(
            title=msg,
            description=msg
            # properties={"exp_date": str(expiration), "exp_days": str(days)},
        )

    def query(self, **kwargs) -> None:

        today = datetime.today()
        log.debug(f"START {today}")
        failure_count = self.config.get("failure_count", 1)

        # init metric
        log.setLevel(self.config.get("log_level"))
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
        # TODO: remove this log
        log.debug("Topology: group name=%s, device name=%s", group.name, device.name)

        minutes = today.minute
        if minutes % self.frequency != 0:
            log.debug(f"Waiting {minutes} freq: {self.frequency}")
            return

        #log.debug(f"target_list: {self.target_list}")
        for target in self.target_list:
            target_name = target["target_name"]

            ping_result = self.ping(target_name)
            #log.debug(ping_result.as_dict())
            success = ping_result.packet_loss_rate is not None and ping_result.packet_loss_rate == 0

            response_time = ping_result.rtt_avg or 0

            if not success:
                # TODO: store failure count for each target in dict
                target["failure_count"] += 1
                target_failures = target["failure_count"]
                if target["failure_count"] >= failure_count:
                    # TODO: send error event to device
                    msg = f"The result for {target_name} was: {success}. Attempt {target_failures}/{failure_count}"
                    log.error(msg)
                    self.send_availability_event(device, msg)
                    target["failure_count"] = 0
                device.absolute(key="success", value=0, dimensions={"hostname": target_name})
            else:
                log.info(f"Success for {target_name} rt was {response_time}")
                device.absolute(key="success", value=1, dimensions={"hostname": target_name})
                device.absolute(key="icmp_ping", value=response_time, dimensions={"hostname": target_name})

        end = datetime.today()
        log.debug(f"END {end}")

    def ping(self, host: str) -> pingparsing.PingStats:
        #log.debug(f"Pinging {host}")
        self.transmitter.destination = host
        return self.ping_parser.parse(self.transmitter.ping())
