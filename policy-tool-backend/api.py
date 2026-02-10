import os
import subprocess
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

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

@app.get("/")
def home():
    return {"message": "Policy Tool API is active"}

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