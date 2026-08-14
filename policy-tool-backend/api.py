import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orchestration import ModelApiClient, OrchestrationError, TransformerProfileOrchestrator

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants for Docker environment
PYTHON_EXE = "python3"
BASE_DIR = "/app"
PROCESSED_DIR = os.path.join(BASE_DIR, "data", "processed")
LAYER_REGISTRY_PATH = Path(
    os.getenv("LAYER_REGISTRY_PATH", "/app/config/layer-manifest.json")
)
PC6_GEOMETRY_PATH = Path(
    os.getenv("PC6_GEOMETRY_PATH", "/app/config/alkmaar_energy_map.geojson")
)
GRID_API_URL = os.getenv("GRID_API_URL", "http://grid-api:8080")
CONGESTION_API_URL = os.getenv("CONGESTION_API_URL", "http://congestion-backend:8080")


class TransformerProfileScenario(BaseModel):
    start: datetime = datetime.fromisoformat("2022-12-31T23:00:00+00:00")
    end: datetime = datetime.fromisoformat("2023-01-01T00:00:00+00:00")

@app.get("/")
def home():
    return {"message": "Policy Tool API is active"}

@app.get("/layers")
def layers():
    try:
        manifest = json.loads(LAYER_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=503, detail="Layer registry is unavailable.") from exc

    records = []
    for layer in manifest.get("layers", []):
        source = layer.get("source", {})
        records.append(
            {
                "id": layer["id"],
                "local_id": layer["local_id"],
                "title": layer["title"],
                "description": layer["description"],
                "model": layer["model"],
                "group": layer["group"],
                "model_id": layer["model_id"],
                "model_version": layer["model_version"],
                "metadata_contract_version": layer["metadata_contract_version"],
                "metadata_url": source.get("metadata_url"),
                "geometry_type": layer["geometry_type"],
                "selectable_feature_type": layer["selectable_feature_type"],
                "crs": source["crs"],
                "attributes": layer["attributes"],
                "data_quality": layer["data_quality"],
                "services": layer["services"],
                "style": layer["style"],
                "actions": layer["actions"],
            }
        )
    return {
        "contract_version": manifest["contract_version"],
        "layers": records,
    }


@app.post("/transformer-profiles/pc6/{pc6}")
def transformer_profiles_pc6(
    pc6: str, scenario: TransformerProfileScenario
):
    orchestrator = TransformerProfileOrchestrator(
        grid_client=ModelApiClient(GRID_API_URL, "grid"),
        congestion_client=ModelApiClient(CONGESTION_API_URL, "congestion"),
        pc6_geometry_path=PC6_GEOMETRY_PATH,
    )
    try:
        return orchestrator.aggregate_pc6(
            pc6,
            start=scenario.start,
            end=scenario.end,
        )
    except OrchestrationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc

@app.get("/simulate/{pc6}")
async def run_simulation(pc6: str, electrification: float = 0.0):
    pc6_upper = pc6.upper()
    
    try:
        # Run the simulation module
        # -u ensures logs show up in docker logs immediately
        cmd = [
            PYTHON_EXE, "-u", "-m", "src.main",
            "--pc6", pc6_upper,
            "--electrification", str(electrification)
        ]

        # Execute simulation
        process = subprocess.run(
            cmd, 
            check=True, 
            cwd=BASE_DIR,
            capture_output=True,
            text=True
        )
        
        # Verify file existence in the volume-mounted folder
        filename = f"pc6_profile_{pc6_upper}.csv"
        file_path = os.path.join(PROCESSED_DIR, filename)

        if os.path.exists(file_path):
            return {
                "status": "success", 
                "pc6": pc6_upper,
                # This is the path the frontend uses to download the file via Nginx
                "url": f"/dashboard/processed/pc6_profile_{pc6.upper()}.csv"
            }
        else:
            print(f"File missing: {file_path}")
            raise HTTPException(status_code=404, detail="Simulation finished but CSV not found.")

    except subprocess.CalledProcessError as e:
            # This will print the ACTUAL Python error from src.main to your docker logs
            print("--- SIMULATION CRASH LOGS ---")
            print(f"STDOUT: {e.stdout}")
            print(f"STDERR: {e.stderr}") 
            print("------------------------------")
            raise HTTPException(status_code=500, detail=f"Simulation failed: {e.stderr[:100]}")
