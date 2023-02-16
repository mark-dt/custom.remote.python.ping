import logging
import requests
import json
import yaml


class Tools:
    def __init__(self, logger, log_level, root_url, token) -> None:
        self.logger = logger
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
        self.header = {
            "Authorization": "Api-TOKEN " + self.token,
            "Content-Type": "application/json",
        }
        logger.info("Ping Tools Init done")

    def make_request(self, url=None, parameters=None, method=None, payload=None):
        """
        Simplifies making requests

        Parameters:
            URL (str): endpoint for the API call
            parameters (dict): parameters for the POST/PUT requests
            method (str): type of request (POST, PUT, GET, DELETE)
            payload (str): json string of the object to be created/updated

        Returns:
            Request result
        """
        try:
            if method == "POST":
                res = requests.post(
                    url,
                    data=payload,
                    headers=self.header,
                    verify=False,
                    params=parameters,
                    timeout=10,
                )
            elif method == "GET":
                res = requests.get(
                    url,
                    headers=self.header,
                    verify=False,
                    params=parameters,
                    timeout=10,
                )
            elif method == "PUT":
                res = requests.put(
                    url,
                    data=payload,
                    headers=self.header,
                    verify=False,
                    params=parameters,
                    timeout=10,
                )
            else:
                self.logger.error("Unkown Request Method %s", method)
        except Exception as exception:
            # send_alert(
            #    exception, 'Exception thrown trying to send an HTTP request to Dynatrace')
            self.logger.error(exception)
            raise SystemExit(exception)
        if res.status_code > 399:
            # alert only if no event of unique name issue
            self.logger.error(res.text)
        return res

    def update_heartbeat_metric(self, device_list):
        # get types from all custom devices
        device_types = []
        for dev in device_list:
            device = device_list[dev]
            if "customProperties" in device["properties"]:
                for property in device["properties"]["customProperties"]:
                    if property["key"] == "Type" or property["key"] == "type":
                        device_types.append(property["value"])
        heart_beat = self.get_heartbeat()
        if heart_beat == None:
            self.logger.error("Could not fetch Ping metric")
            return True
        self.logger.debug(f"device_types:{device_types}")
        self.logger.debug("heartbeat types:")
        self.logger.debug(heart_beat["types"])
        # checks if same types of devices
        if len(list(set(device_types) - set(heart_beat["types"]))) == 0:
            # no update needed
            self.logger.info("No Update needed")
            return False
        if len(device_types) == 0:
            self.logger.debug("No devices with type")
            return True
        data = {
            "timeseriesId": "custom:ping",
            "displayName": "Ping",
            "aggregationTypes": ["AVG", "SUM", "MIN", "MAX"],
            "unit": "ms",
            "filter": "CUSTOM",
            "detailedSource": "API",
            "types": [],
            "warnings": [],
        }
        for type in device_types:
            data["types"].append(type)
        self.logger.info(data)
        # update metric
        url = self.root_url + "/api/v1/timeseries/custom%3Aping"
        res = requests.put(
            url=url, data=json.dumps(data), timeout=10, verify=False, headers=self.header
        )
        if res.status_code > 399:
            self.logger.error(f"Failed to update metric {res.text}")
            return False
        return True

    def get_heartbeat(self):
        url = self.root_url + "/api/v1/timeseries?source=CUSTOM"
        res = requests.get(url=url, timeout=10, verify=False, headers=self.header)
        if res.status_code > 399:
            self.logger.error(f"Failed to get metric: {res.text}")
            return None
        self.logger.debug(res.text)
        data = json.loads(res.text)
        for d in data:
            if d["timeseriesId"].split(":")[1] == "ping":
                return d
        self.logger.error(f"Could not find metric {data}")
        return self.create_heartbeat_metric()

    def create_heartbeat_metric(self):
        self.logger.info("Creating ping metric")
        payload = {
            "timeseriesId": "custom:ping",
            "displayName": "Ping",
            "dimensions": [],
            "aggregationTypes": ["AVG", "SUM", "MIN", "MAX"],
            "unit": "ms",
            "filter": "CUSTOM",
            "detailedSource": "API",
            "types": ["placeholder"],
            "warnings": [],
        }
        url = self.root_url + "/api/v1/timeseries/custom%3Aping"
        # res = self.tools.make_request(URL=url, method="PUT", payload=json.dumps(payload))
        res = requests.put(
            url=url, data=json.dumps(payload), timeout=10, verify=False, headers=self.header
        )
        if res.status_code > 399:
            self.logger.error(f"Failed to update metric {res.text}")
            return None
        self.logger.debug(res.text)
        return None

    def get_entities(self, entity_selector=None, fields=None, from_="-1w", to="now"):
        url = self.root_url + "/api/v2/entities"
        host_list = []
        parameters = {
            "pageSize": 500,
            "entitySelector": entity_selector,
            "fields": fields,
            "from": from_,
            "to": to,
        }
        res = self.make_request(url=url, parameters=parameters, method="GET")
        try:
            res_json = json.loads(res.text)
        except Exception as e:
            self.logger.error(f"Could not parse response{res.text}")
            return []
        if "entities" not in res_json:
            self.logger.error(f"No 'entities' in json response: {res_json}")
            return host_list
        host_list.extend(res_json["entities"])
        while "nextPageKey" in res_json:
            parameters = {"nextPageKey": res_json["nextPageKey"]}
            res = self.make_request(url=url, parameters=parameters, method="GET")
            res_json = json.loads(res.text)
            host_list.extend(res_json["entities"])

        return host_list

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
        # self.logger.debug(f"adding properties {properties}")
        # {'properties': [{'key1': 'value'}]}
        for p in properties["properties"]:
            key = list(p.keys())[0]
            val = p[list(p.keys())[0]]
            device.report_property(key, val)
