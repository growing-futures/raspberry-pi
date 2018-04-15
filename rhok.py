#import logging
from enum import Enum, unique
from influxdb import InfluxDBClient
import json
#from sensor import sensor_fields
import serial  # For communication with arduino.
import time


hostName = 'growingfuturesapp.ca'
hostPort = 8086
dbname = 'gf'


# TODO - hardcoded for now
tower_name = 60
tower_group = "Tower 60 Postal Office"


#sensor_source = ["measurement", "tags", "fields"]
#
#sensor_tags = [
#        "towerName",
#        "towerGroup"
#]
#

@unique
class LightStatus(Enum):
    on  = 1
    off = 2
    on_expected  = 3  # light is off, but it should be on
    off_expected = 4  # light is on, but it should be off


def to_float(s):
    try:
        return float(s)
    except ValueError:
        # TODO
        return s

def to_str(s):
    return s

def to_light_status(light_data):
    # TODO - convert to enum
    if 1 == light_data: status = LightStatus.on
    else: status =  LightStatus.off
    return to_float(status.value)


sensor_fields = [
        ('water_level', to_float),
        ('air_humidity', to_float),
        ('air_temp', to_float),
        ('water_temp', to_float),
        ('pH', to_float),

        # Field values: 0, 1, 'x'.
        # Some setups have less than 4 lights, so 'x' is used as ignore
        # or not applicable.
        ('light_status_1', to_light_status),
        ('light_status_2', to_light_status),
        ('light_status_3', to_light_status),
        ('light_status_4', to_light_status),
]

sensor_fields_len = len(sensor_fields)

# Ref: https://oscarliang.com/connect-raspberry-pi-and-arduino-usb-cable/

def to_dict(sensor_data):
    # TODO - have dict already created, only need to populate with new sensor
    # data
    d = {}
    d['measurement'] = 'TowerData'

    tags = {}
    tags['towerName'] = 'Tower_{}'.format(tower_name)
    tags['towerGroup'] = 'Tower_Group_{}'.format(tower_group)
    d['tags'] = tags
    fields = {}

    for e, (field, func) in enumerate(sensor_fields):
        # We ignore 'x' fields. The arduino is sending 4 light statuses even
        # if they only have 1 light. We filter out any that don't have data.
        data = sensor_data[e]
        if 'x' == data: continue
        fields[field] = func(data)

    d['fields'] = fields
    return d


def main():
    # Use this cmd on the rpi to get the dev name of the arduino. There will
    # be a bunch of tty devices. It is usually something like ttyACM0
    # or ttypUSB0. The last number is dependant on the usb port being used.
    # ls /dev/tty*
    ser = serial.Serial('/dev/ttyUSB0', 9600)
    client = InfluxDBClient(host=hostName, port=hostPort, username='gfsensor',
            password='rhokmonitoring', ssl=True, verify_ssl=True)
    client.switch_database(dbname)

    #sensor_dict = {f:0.0 for f in sensor_fields}

    while True:
        try:
            sensor_data = ser.readline()
        except serial.SerialException:
            # One reason this can occur is when the rpi is disconnected from the
            # arduino.
            # TODO
            #logger.error('SerialError')
            pass

        # Convert byte array to a string.
        sensor_data = sensor_data.decode('utf-8').strip().split(',')
        print(sensor_data)

        if len(sensor_data) != sensor_fields_len:
            # TODO - error - drop data?
            print('WARNING: Sensor data length mismatch (ignoring sensor '
                    'data), received {} values, expecting {} values'.format(
                    len(sensor_data), sensor_fields_len))
            continue

        # Add timestamp.
        # TODO
        #logger.info(sensor_data)

        # Output to json.
        d = [to_dict(sensor_data)]
        print(json.dumps(d))

        if client.write_points(d):
            print("Insert success")


if '__main__' == __name__:
    main()
