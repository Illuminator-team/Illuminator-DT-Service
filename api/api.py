from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()

@app.get("/")
def root():
    return {"status": "OK"}

@app.get("/wfs")
def get_lamp_feature():
    feature = {
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
    return JSONResponse(content=feature)
