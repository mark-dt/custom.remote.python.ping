import json
import requests
import time
import logging

log = logging.getLogger(__name__)

def get_ping_success_metric(tools):
    url = tools.root_url + "/api/v1/timeseries?source=CUSTOM"
    res = requests.get(url=url, timeout=10, verify=False, headers=tools.header)
    if res.status_code > 399:
        tools.logger.error(f"Failed to get metric: {res.text}")
        return None
    tools.logger.debug(res.text)
    data = json.loads(res.text)
    for d in data:
        if d["timeseriesId"].split(":")[1] == "ping_success":
            return d
    tools.logger.error(f"Could not find metric {data}")
    return create_ping_success_metric(tools)


def create_ping_success_metric(tools):
    tools.logger.info("Creating ping_success metric")
    payload = {
        "timeseriesId": "custom:ping_success",
        "displayName": "Ping Success",
        "dimensions": [],
        "aggregationTypes": ["AVG", "SUM", "MIN", "MAX"],
        "unit": "Count",
        "filter": "CUSTOM",
        "detailedSource": "API",
        "types": ["placeholder"],
        "warnings": [],
    }
    url = tools.root_url + "/api/v1/timeseries/custom%3Aping_success"
    # res = tools.tools.make_request(URL=url, method="PUT", payload=json.dumps(payload))
    res = requests.put(
        url=url, data=json.dumps(payload), timeout=10, verify=False, headers=tools.header
    )
    if res.status_code > 399:
        tools.logger.error(f"Failed to create metric ping_success {res.text}")
        return None
    tools.logger.debug(res.text)
    return None


def update_ping_success_metric(tools, device_list, logger):
    logger.debug("Updating Ping Success")
    tools.logger.error("Error Test updating ping success")
    log.info("Test from new log resource")
    #logging.error("Error Test updating ping success")
    logging.info("Info Test updating ping success")
    # get types from all custom devices
    device_types = []
    for dev in device_list:
        device = device_list[dev]
        if "customProperties" in device["properties"]:
            for property in device["properties"]["customProperties"]:
                if property["key"] == "Type" or property["key"] == "type":
                    device_types.append(property["value"])
    heart_beat = get_ping_success_metric(tools)
    if heart_beat == None:
        tools.logger.error("Could not fetch ping_success metric, waiting for metric to be created...")
        time.sleep(10)
    tools.logger.debug(f"device_types:{device_types}")
    tools.logger.debug("ping_success types:")
    tools.logger.debug(heart_beat["types"])
    # checks if same types of devices
    if len(list(set(device_types) - set(heart_beat["types"]))) == 0:
        # no update needed
        tools.logger.info("No Update needed")
        return False
    if len(device_types) == 0:
        tools.logger.debug("No devices with type")
        return True
    data = {
        "timeseriesId": "custom:ping_success",
        "displayName": "Ping Success",
        "aggregationTypes": ["AVG", "SUM", "MIN", "MAX"],
        "unit": "Count",
        "filter": "CUSTOM",
        "detailedSource": "API",
        "types": [],
        "warnings": [],
    }
    for type in device_types:
        data["types"].append(type)
    tools.logger.info(data)
    # update metric
    url = tools.root_url + "/api/v1/timeseries/custom%3Aping_success"
    res = requests.put(
        url=url, data=json.dumps(data), timeout=10, verify=False, headers=tools.header
    )
    if res.status_code > 399:
        tools.logger.error(f"Failed to update metric {res.text}")
        return False
    return True