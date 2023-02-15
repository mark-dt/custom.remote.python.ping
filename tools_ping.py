import logging
import yaml


class Tools:
    def __init__(self, logger, log_level, root_url, token) -> None:
        self.logger = logger
        self.logger.debug(f"Initialize Tools..")
        if log_level == "DEBUG":
            log_level = logging.DEBUG
        elif log_level == "INFO":
            log_level = logging.INFO
        elif log_level == "WARNING":
            log_level = logging.WARNING
        elif log_level == "ERROR":
            log_level = logging.ERROR
        else:
            log_level = logging.INFO

        self.token = token
        self.root_url = root_url
        logger.setLevel(log_level)
        logger.debug(f"Log level is {log_level}")
        logger.info("Tools Init done")

    def parse_properties(self, text):
        try:
            dct = yaml.safe_load(text)
        except Exception as e:
            error = f"Could not parse cmd config: {e}"
            self.logger.error(error)
            return {}

        # self.logger.debug(dct)
        return dct

    def add_device_properties(self, device, device_properties):
        properties = self.parse_properties(device_properties)
        if not properties:
            self.logger.debug("No Properties to add")
            return
        #self.logger.debug(f"adding properties {properties}")
        # {'properties': [{'key1': 'value'}]}
        for p in properties["properties"]:
            key = list(p.keys())[0]
            val = p[list(p.keys())[0]]
            device.report_property(key, val)