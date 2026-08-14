FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py pc6.py pv.py grid.py grid_postgis.py wind.py wind_postgis.py consumption.py ev.py model_postgis.py postgis_sql.py layer-manifest.json ./

CMD ["python", "main.py"]
