import os
import sys
import asyncio
import websockets
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
from websockets.asyncio.client import ClientProtocol as client
from loguru import logger
from dotenv import load_dotenv
from ocpp.v16 import ChargePoint as cp
from ocpp.v16 import call, call_result
from ocpp.v16.enums import (RegistrationStatus, Action, ResetStatus,
                            UnlockStatus, DataTransferStatus, ReadingContext,
                            ValueFormat, Measurand, Phase, Location, UnitOfMeasure,
                            ChargePointStatus, ChargePointErrorCode, Reason,
                            AvailabilityType, AvailabilityStatus, ConfigurationStatus,
                            ClearCacheStatus, RemoteStartStopStatus)
from ocpp.v16.call_result import BootNotification, Authorize, StartTransaction, StopTransaction, GetConfiguration
from ocpp.routing import on
from ocpp.v16.datatypes import MeterValue, SampledValue, KeyValue

import logging
logging.getLogger('ocpp').setLevel(level=logging.INFO)
logging.getLogger('ocpp').addHandler(logging.StreamHandler())

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

BOOTNOTIFICATION_TIMEOUT = 60
MAX_RETRY_ATTEMPTS = 3

class Client(cp):

    def __init__(self, id, connection: client, response_timeout=30):
        self.CSMS_time = None
        self.retry_attempts = 0
        self.ws = connection
        self.id = id
        self.response_timeout = response_timeout
        super().__init__(self.id, self.ws, self.response_timeout)

    async def start(self):
        return await super().start()

    async def connect(self):
        try:
            if self.ws.connected:
                logger.warning("WS client already opened!")
            else:
                self.ws = await websockets.connect(
                    os.environ.get('CSMSADR') +
                    os.environ.get('VENDOR_NAME') +
                    os.environ.get('PRODUCT_CODE') +
                    os.environ.get('CHARGE_POINT_SERIAL_NUMBER'),
                    subprotocols=["ocpp" + os.environ.get('OCPP_V')]
                )
                logger.debug("WebSocket connection established.")
                super().__init__(self.id, self.ws, self.response_timeout)
        except Exception as e:
            logger.error(f"Failed to establish WebSocket connection: {e}")
            self.ws = None

    async def reconnect(self):
        logger.debug("Attempting to reconnect...")
        await asyncio.sleep(3)

    async def boot_notification(self,
                                     charge_point_model = "",
                                     charge_point_vendor = "",
                                     charge_box_serial_number = "",
                                     charge_point_serial_number = "",
                                     firmware_version = "",
                                     iccid = "",
                                     imsi = "",
                                     meter_serial_number = "",
                                     meter_type = "",
                                     retry_attempts = 1,
                                     ):
        while self.retry_attempts < MAX_RETRY_ATTEMPTS:
            try:
                request = call.BootNotification(
                    charge_point_model = os.environ.get('VENDOR_NAME') + os.environ.get('PRODUCT_CODE'),
                    charge_point_vendor = os.environ.get('VENDOR_NAME'),
                    charge_box_serial_number = os.environ.get('CHARGE_BOX_SERIAL_NUMBER'),
                    charge_point_serial_number = os.environ.get('CHARGE_POINT_SERIAL_NUMBER'),
                    firmware_version = os.environ.get('FIRMWARE_VERSION'),
                    iccid = os.environ.get('ICCID'),
                    imsi = os.environ.get('IMSI'),
                    meter_serial_number = os.environ.get('METER_SERIAL_NUMBER'),
                    meter_type = os.environ.get('METER_TYPE')
                )
                response:BootNotification = await asyncio.wait_for(self.call(request), timeout=BOOTNOTIFICATION_TIMEOUT)
                logger.debug(response)
                if response.status == RegistrationStatus.accepted:
                    self.CSMS_time = response.current_time
                    logger.debug(f"CSMS time {response.current_time}")
                    self.heart_beat_interval = response.interval #seconds
                    logger.debug(f"heart beat interval requested {response.interval}")
                    logger.debug(f"Connected to central system. Attempts to connect: {self.retry_attempts}")
                    self.retry_attempts = 0
                    return
            except asyncio.TimeoutError:
                logger.error("BootNotification request timed out.")
                self.retry_attempts += 1
                logger.debug(f"Retry attempt {self.retry_attempts}/{MAX_RETRY_ATTEMPTS}")
            except Exception as e:
                logger.error(f"Exception during BootNotification: {e}")
                self.retry_attempts += 1
                logger.debug(f"Retry attempt {self.retry_attempts}/{MAX_RETRY_ATTEMPTS}")
            await asyncio.sleep(30)

        # if max retryes then reconnect
        logger.error("Max retry attempts reached. Reconnecting...")
        await self.reconnect()

    async def heart_beat(self):
        while True:
            request = call.Heartbeat()
            response = await self.call(request)
            logger.debug(response)
            await asyncio.sleep(self.heart_beat_interval)



async def main():
    logger.debug("START OCPP Client")
    async with websockets.connect(uri=os.environ.get('CSMSADR') + 
                                    os.environ.get('VENDOR_NAME') + 
                                    os.environ.get('PRODUCT_CODE') + 
                                    os.environ.get('CHARGE_POINT_SERIAL_NUMBER'),
                                    subprotocols=["ocpp"+os.environ.get('OCPP_V')]) as ws:

        cp = Client(id = (os.environ.get('VENDOR_NAME') + os.environ.get('PRODUCT_CODE') + os.environ.get('CHARGE_POINT_SERIAL_NUMBER')), connection=ws)
        asyncio.ensure_future(cp.start())
        asyncio.ensure_future(cp.boot_notification())
        await asyncio.sleep(1)
        asyncio.ensure_future(cp.heart_beat())
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())