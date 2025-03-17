import json
import asyncio
import logging
import random
import string
from datetime import datetime
import websockets
from typing import Dict, List, Optional
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from ocpp.routing import on
from ocpp.v16 import ChargePoint as chargepoint
from ocpp.v16 import call_result, call
from ocpp.v16.enums import Action, RegistrationStatus, ResetType, AuthorizationStatus, DataTransferStatus, AvailabilityType, CiStringType
from ocpp.v16.datatypes import IdTagInfo

from loguru import logger

from typing import Annotated

logging.getLogger('ocpp').setLevel(level=logging.INFO)

ocpp_logger = logger.bind(name="ocpp", task="ocpp")

class LoguruHandler(logging.Handler):
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        log_entry = self.format(record)
        ocpp_logger.log(level, log_entry)

logging.getLogger('ocpp').addHandler(LoguruHandler())


timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
filename=f"./logs/logs_{timestamp}.log"
ocpp_logger.add(filename, rotation="10 KB", format="{time:YYYY-MM-DD HH:mm:ss} | {message}", filter=lambda record: record["extra"].get("name") == "ocpp")


async def broadcast_log(message: str):
    for websocket in connected_websockets:
        try:
            await websocket.send_text(message)
        except (RuntimeError, WebSocketDisconnect):
            connected_websockets.remove(websocket)

class WebSocketSink:
    def write(self, message):
        asyncio.create_task(broadcast_log(message))

    def flush(self):
        pass

ocpp_logger.add(WebSocketSink(), format="{time:YYYY-MM-DD HH:mm:ss} | {message}", filter=lambda record: record["extra"].get("name") == "ocpp")

class WebSocketHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        asyncio.create_task(broadcast_log(log_entry))

def custom_openapi():
    if not app.openapi_schema:
        app.openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            openapi_version=app.openapi_version,
            description=app.description,
            terms_of_service=app.terms_of_service,
            contact=app.contact,
            license_info=app.license_info,
            routes=app.routes,
            tags=app.openapi_tags,
            servers=app.servers,
        )
        for path, methods in app.openapi_schema.get('paths', {}).items():
            for method, details in methods.items():
                responses = details.get('responses', {})
                if '422' in responses:
                    del responses['422']
    return app.openapi_schema

app = FastAPI(docs_url=None, redoc_url=None, title="OCPP 1.6 API")
app.openapi = custom_openapi

# only Swagger UI
docs_html = ""
with open("./ocpp/docs.html") as f:
    docs_html = f.read()
# only logs
logs_html = ""
with open("./ocpp/logs.html") as f:
    logs_html = f.read()
# logs and Swagger UI
docslogs_html = ""
with open("./ocpp/docslogs.html") as f:
    docslogs_html = f.read()

@app.get("/docs", include_in_schema=False)
async def get_swagger_ui_html():
    return HTMLResponse(docs_html)

@app.get("/logs", include_in_schema=False)
async def get_logs_html():
    return HTMLResponse(logs_html)

@app.get("/docslogs", include_in_schema=False)
async def get_docslogs_html():
    return HTMLResponse(docslogs_html)

connected_websockets = []

class UnlockRequest(BaseModel):
    # id: call.UnlockConnector.connector_id
    id: int

cp = None

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        while True:
            await asyncio.sleep(1)
            if websocket.application_state.value != 1:
                logger.info("Client disconnected")
                break
    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        connected_websockets.remove(websocket)
        await websocket.close()

@app.get("/docs", include_in_schema=False)
async def get_swagger_ui_html():
    return HTMLResponse(docs_html)

@app.post("/ChangeAvailability", tags=["Initiated by CSMS"])
async def change_availability_connector(connector_id:Annotated[int, Query()], type:Annotated[AvailabilityType, Query()]):
    """
    """
    response = await cp.change_availability(connector_id, type)
    logger.debug(response)
    return response

@app.post("/ChangeConfiguration", tags=["Initiated by CSMS"])
async def change_configuration_charge_point(key:Annotated[str, Query()], value:Annotated[str, Query()]):
    """
    """
    response = await cp.change_configuration(key, value)
    logger.debug(response)
    return response

@app.post("/ClearCache", tags=["Initiated by CSMS"])
async def clear_cache_charge_point():
    """
    """
    response = await cp.clear_cache()
    logger.debug(response)
    return response

@app.post("/DataTransfer", tags=["Initiated by CSMS"])
async def data_transfer_to_charge_point(message_id:Annotated[str, Query()], message:Annotated[str, Query()]):
    """
    """
    response = await cp.data_transfer(message_id, message)
    logger.debug(response)
    return response

@app.post("/GetConfiguration", tags=["Initiated by CSMS"])
async def get_configuration_to_charge_point(key:Annotated[Optional[List[str]], Query()] = None):
    """
    """
    response = await cp.get_configuration(key)
    logger.debug(response)
    return response

@app.post("/RemoteStartTransaction", tags=["Initiated by CSMS"])
async def remote_start_transaction_charge_point(id_tag: Annotated[str, Query()],
                                                connector_id:Annotated[Optional[int], Query()] = None,
                                                charging_profile:Annotated[Optional[str], Query()] = None):
    """
    Endpoint to start a transaction remotely.
    """
    try:
        charging_profile_dict = json.loads(charging_profile)
    except json.JSONDecodeError:
        return {"error": "Invalid JSON format for charging_profile"}
    if charging_profile is None or charging_profile == {}:
        response = await cp.remote_start_transaction(id_tag, connector_id)
    else:
        response = await cp.remote_start_transaction(id_tag, connector_id, charging_profile)
    logger.debug(response)
    return response

@app.post("/RemoteStopTransaction", tags=["Initiated by CSMS"])
async def remote_stop_transaction_charge_point(transaction_id:Annotated[int, Query()]):
    """
    Endpoint to stop a transaction remotely.
    """
    response = await cp.remote_stop_transaction(transaction_id)
    logger.debug(response)
    return response

@app.post("/Reset", tags=["Initiated by CSMS"])
async def reset_charge_point(type: Annotated[ResetType, Query()]):
    """
    Endpoint to reset a device.

    Example request body:
    [2, "7fe84a15-9c4d-44fb-957f-b32ca9faf2c9", "Reset", {"type": "Hard"}]

    - The first element is an integer representing the message type.
    - The second element is a UUID string representing the message ID.
    - The third element is a string representing the message.
    - The fourth element is a dictionary containing additional parameters, e.g., {"type": "Hard"}.
    """
    response = await cp.reset(type)
    logger.debug(response)
    return response

@app.post("/UnlockConnector", tags=["Initiated by CSMS"])
async def unlock_connector_charge_point(connector_id: Annotated[int, Query()]):
    """
    """
    response = await cp.unlock_connector(connector_id)
    logger.debug(response)
    return response

class ChargePoint(chargepoint):
    transactions = []
    
    async def change_availability(self, connector_id, type):
        request = call.ChangeAvailability(connector_id, type)
        response = await self.call(request)
        return response
    
    async def change_configuration(self, key, value):
        request = call.ChangeConfiguration(key, value)
        response = await self.call(request)
        return response
    
    async def clear_cache(self):
        request = call.ClearCache()
        response = await self.call(request)
        return response
    
    async def data_transfer(self, message_id:str, message:str):
        request = call.DataTransfer(vendor_id="EKRA",
                                    message_id=message_id, message=message)
        response:DataTransferStatus = await self.call(request)
        return response
    
    async def get_configuration(self, key):
        request = call.GetConfiguration(key)
        response = await self.call(request)
        return response
    
    async def remote_start_transaction(self, id_tag, connector_id:Optional[int] = None, charging_profile:Optional[Dict] = None):
        request = call.RemoteStartTransaction(id_tag, connector_id, charging_profile)
        response = await self.call(request)
        return response
    
    async def remote_stop_transaction(self, transaction_id):
        request = call.RemoteStopTransaction(transaction_id)
        response = await self.call(request)
        return response

    async def reset(self, type:ResetType):
        request = call.Reset(type)
        response = await self.call(request)
        return response

    async def unlock_connector(self, connector_id):
        request = call.UnlockConnector(connector_id)
        response = await self.call(request)
        return response

    @on(Action.Authorize)
    def on_authorize_notification(self, **kwargs):
        return call_result.Authorize(
            IdTagInfo(AuthorizationStatus.accepted, None, None)
        )

    @on(Action.BootNotification)
    def on_boot_notification(
        self, charge_point_vendor: str, charge_point_model: str, **kwargs
    ):
        for key, value in kwargs.items():
            logger.debug(f"{key}: {value}")

        return call_result.BootNotification(
            current_time=datetime.now().isoformat(),
            interval=30,
            status=RegistrationStatus.accepted)

    @on(Action.DataTransfer)
    def on_data_transfer_notification(self, **kwargs):
        return call_result.DataTransfer(status=DataTransferStatus.accepted)
    
    @on(Action.Heartbeat)
    def on_hearbeat_notification(self, **kwargs):
        return call_result.Heartbeat(
            current_time=datetime.now().isoformat(),
        )

    @on(Action.MeterValues)
    def on_meter_values_notification(self, **kwargs):
        return call_result.MeterValues()

    @on(Action.StartTransaction)
    def on_start_transaction_notification(self, **kwargs):
        for key, value in kwargs.items():
            logger.debug(f"{key}: {value}")
        transactionId = random.randint(1, 0xFFFFFFFF)
        self.transactions.append(transactionId)
        id_tag_info = IdTagInfo(status=AuthorizationStatus.accepted,
                  parent_id_tag=''.join(random.choice(string.ascii_letters + string.digits) for _ in range(CiStringType.ci_string_20)),
                  expiry_date=datetime.now().isoformat())
        response = call_result.StartTransaction(transactionId, id_tag_info=id_tag_info)
        return response

    @on(Action.StatusNotification)
    def on_status_notification(self, **kwargs):
        for key, value in kwargs.items():
            logger.debug(f"{key}: {value}")
        return call_result.StatusNotification()

    @on(Action.StopTransaction)
    def on_stop_transaction_notification(self, transactionId, **kwargs):
        for key, value in kwargs.items():
            logger.debug(f"{key}: {value}")
        if transactionId in self.transactions:
            self.transactions.remove(transactionId)
            return call_result.StopTransaction(id_tag_info=IdTagInfo(status=AuthorizationStatus.accepted))
        else:
            return call_result.StopTransaction(id_tag_info=IdTagInfo(status=AuthorizationStatus.invalid))

async def on_connect(websocket):
    """For every new charge point that connects, create a ChargePoint
    instance and start listening for messages.
    """
    global cp
    try:
        requested_protocols = websocket.request.headers["Sec-WebSocket-Protocol"]
    except KeyError:
        ocpp_logger.error("Client hasn't requested any Subprotocol. Closing Connection")
        return await websocket.close()
    if websocket.subprotocol:
        ocpp_logger.info("Protocols Matched: {}", websocket.subprotocol)
    else:
        ocpp_logger.warning(
            "Protocols Mismatched | Expected Subprotocols: {},"
            " but client supports  {} | Closing connection",
            websocket.available_subprotocols,
            requested_protocols,
        )
        return await websocket.close()

    charge_point_id = websocket.request.path.strip("/")
    cp = ChargePoint(charge_point_id, websocket)
    try:
        await cp.start()
    except Exception as e:
        ocpp_logger.error("Close connection")
        logger.error(f"{e}")


async def main():
    server = await websockets.serve(
        on_connect, "192.168.88.100", 9000, subprotocols=["ocpp1.6"]
    )
    logger.info("Server Started listening to new connections...")
    await asyncio.gather(server.wait_closed(), uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000)).serve())

if __name__ == "__main__":
    asyncio.run(main())