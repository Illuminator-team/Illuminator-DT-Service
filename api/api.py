from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def root():
    return {"status": "OK"}

@app.get("/wfs")
def get_lamp_feature():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [4.373494941750751, 52.002189761571074]
                },
                "properties": {
                    "name": "Lamp",
                    "icon": "https://www.svgrepo.com/show/450454/lamp.svg"
                }
            }
        ]
    }

@app.middleware("http")
async def catch_all_404(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={"error": "FastAPI received the request, but no route matched."}
        )
    return response
