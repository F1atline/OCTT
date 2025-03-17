from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime

app = FastAPI(docs_url=None, redoc_url=None)  # off standart
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
filename=f"logs_{timestamp}.log"
# loguru settings
logger.add(filename, rotation="100 KB", format="{time:YYYY-MM-DD HH:mm:ss} | {message}")  # save to file

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

@app.get("/test")
async def test_route():
    return {"message": "This is a test route"}

connected_websockets = []

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    counter = 0
    try:
        while True:
            await asyncio.sleep(1)
            counter+=1
            logger.info(f"Test log message {counter}")
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

async def broadcast_log(message: str):
    print(f"Broadcasting log: {message}")
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

logger.add(WebSocketSink(), format="{time:YYYY-MM-DD HH:mm:ss} | {message}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Server started")
    yield
    logger.info("Server shutdown")

app.router.lifespan_context = lifespan

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)